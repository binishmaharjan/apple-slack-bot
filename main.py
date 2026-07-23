import html
import os
import re
import sys

import feedparser
import requests

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
LEGACY_APPLE_STATE_FILE = os.path.join(STATE_DIR, "last_article_id.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/atom+xml,application/rss+xml,*/*;q=0.8",
}

APPLE_NEWS_BASE = "https://developer.apple.com"

ARTICLE_PATTERN = re.compile(
    r'<a class="article-title" href="(/news/\?id=[^"]+)"><h2>([^<]+)</h2></a>'
)
META_TAG_PATTERN = re.compile(
    r'<meta\s+(?:property|name)="(?P<key>[^"]+)"\s+content="(?P<value>[^"]*)"',
    re.IGNORECASE,
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

SOURCES = [
    {
        "id": "apple",
        "type": "html",
        "label": "Apple Developer News",
        "color": "#007AFF",
        "url": "https://developer.apple.com/news/",
    },
    {
        "id": "apple-releases",
        "type": "feed",
        "label": "Apple Developer Releases",
        "color": "#5856D6",
        "url": "https://developer.apple.com/news/releases/rss/releases.rss",
    },
    {
        "id": "android-blog",
        "type": "feed",
        "label": "Android Developers Blog",
        "color": "#3DDC84",
        "url": "https://developer.android.com/blog/atom.xml",
    },
    {
        "id": "android-jp",
        "type": "feed",
        "label": "Android Developers Japan Blog",
        "color": "#34A853",
        "url": "https://feeds.feedburner.com/AndroidDevJapanBlog",
    },
    {
        "id": "android-dagashi",
        "type": "feed",
        "label": "Android Dagashi",
        "color": "#FBBC04",
        "url": "https://feeds.feedburner.com/AndroidDagashi",
    },
]


def state_file(source_id):
    return os.path.join(STATE_DIR, f"{source_id}.txt")


def load_last_entry_id(source_id):
    path = state_file(source_id)
    try:
        with open(path, encoding="utf-8") as f:
            entry_id = f.read().strip()
            return entry_id or None
    except FileNotFoundError:
        if source_id == "apple" and os.path.isfile(LEGACY_APPLE_STATE_FILE):
            with open(LEGACY_APPLE_STATE_FILE, encoding="utf-8") as f:
                entry_id = f.read().strip()
                return entry_id or None
        return None


def save_last_entry_id(source_id, entry_id):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_file(source_id), "w", encoding="utf-8") as f:
        f.write(entry_id)


def strip_html(text):
    if not text:
        return ""
    cleaned = html.unescape(HTML_TAG_PATTERN.sub(" ", text))
    return re.sub(r"\s+", " ", cleaned).strip()


def fetch_latest_apple_news(url):
    print(f"Fetching {url}...")

    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"Server returned HTTP status {response.status_code}")

    match = ARTICLE_PATTERN.search(response.text)
    if not match:
        raise RuntimeError("Could not find any news articles on the page.")

    path, title = match.groups()
    entry_id = path.rsplit("id=", 1)[-1]
    link = f"{APPLE_NEWS_BASE}{path}"
    return title.strip(), link, entry_id, "", ""


def fetch_article_preview(link):
    response = requests.get(link, headers=HEADERS, timeout=15)
    if response.status_code != 200:
        return "", ""

    tags = {
        match.group("key"): match.group("value")
        for match in META_TAG_PATTERN.finditer(response.text)
    }

    description = tags.get("og:description") or tags.get("twitter:description") or ""
    image_url = tags.get("og:image") or tags.get("twitter:image") or ""
    return description.strip(), image_url.strip()


def get_feed_image(entry):
    if getattr(entry, "media_thumbnail", None):
        return entry.media_thumbnail[0].get("url", "").strip()
    if getattr(entry, "media_content", None):
        return entry.media_content[0].get("url", "").strip()
    return ""


def fetch_latest_feed_entry(url):
    print(f"Fetching feed from {url}...")

    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"Server returned HTTP status {response.status_code}")

    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        detail = parsed.bozo_exception if parsed.bozo else "Feed contains no entries."
        raise RuntimeError(f"Could not parse feed: {detail}")

    entry = parsed.entries[0]
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")
    entry_id = entry.get("id") or link
    description = strip_html(entry.get("summary") or entry.get("description", ""))
    image_url = get_feed_image(entry)

    if not title or not link or not entry_id:
        raise RuntimeError("Latest feed entry is missing title, link, or id.")

    return title, link, entry_id, description, image_url


def fetch_latest_entry(source):
    if source["type"] == "html":
        title, link, entry_id, description, image_url = fetch_latest_apple_news(source["url"])
        if not description:
            description, preview_image = fetch_article_preview(link)
            if preview_image:
                image_url = preview_image
        return title, link, entry_id, description, image_url

    return fetch_latest_feed_entry(source["url"])


def build_slack_payload(source, title, link, description, image_url):
    attachment = {
        "fallback": f"{title} - {link}",
        "title": title,
        "title_link": link,
        "text": description,
        "color": source["color"],
    }

    if image_url:
        attachment["image_url"] = image_url

    return {
        "text": f"📢 *Latest {source['label']}*",
        "attachments": [attachment],
    }


def post_to_slack(payload):
    response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    if response.status_code != 200:
        raise RuntimeError(
            f"Slack webhook rejected the message. Status: {response.status_code}, Response: {response.text}"
        )


def check_source(source):
    print(f"\n--- {source['label']} ---")

    title, link, entry_id, description, image_url = fetch_latest_entry(source)
    last_id = load_last_entry_id(source["id"])

    print(f"Latest entry ID: '{entry_id}'")
    print(f"Latest entry title: '{title}'")

    if last_id == entry_id:
        print("No new entries since last run. Skipping Slack post.")
        return False

    if last_id:
        print(f"New entry detected (previous ID: '{last_id}').")
    else:
        print("First run with no saved state. Posting latest entry.")

    print("Posting to Slack...")
    payload = build_slack_payload(source, title, link, description, image_url)
    post_to_slack(payload)
    save_last_entry_id(source["id"], entry_id)
    print("Successfully posted to Slack!")
    return True


def main():
    if not WEBHOOK_URL:
        raise ValueError("SLACK_WEBHOOK_URL environment variable is missing or empty!")

    errors = []
    posted = 0

    for source in SOURCES:
        try:
            if check_source(source):
                posted += 1
        except Exception as exc:
            message = f"{source['label']}: {exc}"
            print(f"ERROR: {message}")
            errors.append(message)

    print(f"\nDone. Posted {posted} update(s).")

    if errors:
        print("\nFailures:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
