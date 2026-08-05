import html
import json
import os
import re
import sys
import time

import feedparser
import requests

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
LEGACY_APPLE_STATE_FILE = os.path.join(STATE_DIR, "last_article_id.txt")
FEED_ENTRY_LIMIT = 100
SLACK_POST_DELAY_SECONDS = 1
STATE_VERSION = 2

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


def state_json_file(source_id):
    return os.path.join(STATE_DIR, f"{source_id}.json")


def legacy_state_file(source_id):
    return os.path.join(STATE_DIR, f"{source_id}.txt")


def normalize_entry_id(raw_id):
    if not raw_id:
        return ""

    entry_id = raw_id.strip()
    if "id=" in entry_id:
        entry_id = entry_id.rsplit("id=", 1)[-1].split("&", 1)[0]
    if entry_id.startswith("http"):
        entry_id = entry_id.rstrip("/")

    return entry_id


def load_legacy_txt_id(source_id):
    for path in (legacy_state_file(source_id),):
        try:
            with open(path, encoding="utf-8") as f:
                entry_id = normalize_entry_id(f.read())
                if entry_id:
                    return entry_id
        except FileNotFoundError:
            continue

    if source_id == "apple" and os.path.isfile(LEGACY_APPLE_STATE_FILE):
        with open(LEGACY_APPLE_STATE_FILE, encoding="utf-8") as f:
            entry_id = normalize_entry_id(f.read())
            if entry_id:
                return entry_id

    return None


def load_state(source_id):
    json_path = state_json_file(source_id)
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        seen_ids = {normalize_entry_id(entry_id) for entry_id in data.get("seen_ids", [])}
        seen_ids.discard("")
        state_version = int(data.get("version", 1))
        return seen_ids, bool(data.get("bootstrapped", False)), False, state_version
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid state file '{json_path}': {exc}") from exc

    legacy_id = load_legacy_txt_id(source_id)
    if legacy_id:
        return {legacy_id}, False, True, 1

    return set(), False, False, 1


def save_state(source_id, seen_ids, bootstrapped, version=STATE_VERSION):
    os.makedirs(STATE_DIR, exist_ok=True)
    payload = {
        "version": version,
        "seen_ids": sorted(seen_ids),
        "bootstrapped": bootstrapped,
    }
    with open(state_json_file(source_id), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def strip_html(text):
    if not text:
        return ""
    cleaned = html.unescape(HTML_TAG_PATTERN.sub(" ", text))
    return re.sub(r"\s+", " ", cleaned).strip()


def fetch_apple_news_entries(url):
    print(f"Fetching {url}...")

    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"Server returned HTTP status {response.status_code}")

    entries = []
    for match in ARTICLE_PATTERN.finditer(response.text):
        path, title = match.groups()
        entry_id = normalize_entry_id(path.rsplit("id=", 1)[-1])
        link = f"{APPLE_NEWS_BASE}{path}"
        if not entry_id or not title.strip():
            continue
        entries.append(
            {
                "id": entry_id,
                "title": title.strip(),
                "link": link,
                "description": "",
                "image_url": "",
            }
        )

    if not entries:
        raise RuntimeError("Could not find any news articles on the page.")

    print(f"Found {len(entries)} article(s) on the page.")
    return entries


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


def fetch_feed_entries(url, limit=FEED_ENTRY_LIMIT):
    print(f"Fetching feed from {url}...")

    response = requests.get(url, headers=HEADERS, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"Server returned HTTP status {response.status_code}")

    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        detail = parsed.bozo_exception if parsed.bozo else "Feed contains no entries."
        raise RuntimeError(f"Could not parse feed: {detail}")

    entries = []
    for entry in parsed.entries[:limit]:
        title = strip_html(entry.get("title", ""))
        link = (entry.get("link") or "").strip()
        entry_id = normalize_entry_id(entry.get("id") or link)
        description = strip_html(entry.get("summary") or entry.get("description", ""))
        image_url = get_feed_image(entry)

        if not title or not link or not entry_id:
            continue

        entries.append(
            {
                "id": entry_id,
                "title": title,
                "link": link,
                "description": description,
                "image_url": image_url,
            }
        )

    if not entries:
        raise RuntimeError("Feed entries are missing title, link, or id.")

    print(f"Found {len(entries)} feed entry(ies).")
    return entries


def fetch_entries(source):
    if source["type"] == "html":
        return fetch_apple_news_entries(source["url"])
    return fetch_feed_entries(source["url"])


def enrich_entry_preview(entry):
    if entry.get("description"):
        return

    description, image_url = fetch_article_preview(entry["link"])
    entry["description"] = description
    if image_url:
        entry["image_url"] = image_url


def build_slack_payload(source, entry):
    attachment = {
        "fallback": f"{entry['title']} - {entry['link']}",
        "title": entry["title"],
        "title_link": entry["link"],
        "text": entry.get("description", ""),
        "color": source["color"],
    }

    if entry.get("image_url"):
        attachment["image_url"] = entry["image_url"]

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

    entries = fetch_entries(source)
    seen_ids, bootstrapped, legacy_migration, state_version = load_state(source["id"])
    current_ids = {entry["id"] for entry in entries}

    print(f"Seen IDs: {len(seen_ids)} | Fetched: {len(current_ids)}")

    if legacy_migration:
        save_state(source["id"], current_ids, bootstrapped=True)
        print(
            f"Legacy migration: marked {len(current_ids)} current ID(s) as seen. "
            "No posts during migration."
        )
        return 0

    if not bootstrapped:
        save_state(source["id"], current_ids, bootstrapped=True)
        print(
            f"Bootstrap complete: marked {len(current_ids)} ID(s) as seen. "
            "No posts on first run."
        )
        return 0

    if state_version < STATE_VERSION:
        added = len(current_ids - seen_ids)
        seen_ids |= current_ids
        save_state(source["id"], seen_ids, bootstrapped=True)
        print(
            f"State v{STATE_VERSION} migration: merged {added} ID(s) into seen set. "
            "No posts during migration."
        )
        return 0

    new_entries = [entry for entry in entries if entry["id"] not in seen_ids]
    new_entries.reverse()

    if not new_entries:
        print("No new entries since last run.")
        return 0

    print(f"Found {len(new_entries)} new entr{'y' if len(new_entries) == 1 else 'ies'} to post.")
    posted = 0

    for index, entry in enumerate(new_entries):
        print(f"Posting ({index + 1}/{len(new_entries)}): '{entry['title']}'")

        if source["type"] == "html":
            enrich_entry_preview(entry)

        payload = build_slack_payload(source, entry)
        post_to_slack(payload)

        seen_ids.add(entry["id"])
        save_state(source["id"], seen_ids, bootstrapped=True)
        posted += 1
        print("Successfully posted to Slack!")

        if index < len(new_entries) - 1:
            time.sleep(SLACK_POST_DELAY_SECONDS)

    print(f"Posted {posted} update(s) for {source['label']}.")
    return posted


def main():
    if not WEBHOOK_URL:
        raise ValueError("SLACK_WEBHOOK_URL environment variable is missing or empty!")

    errors = []
    posted = 0

    for source in SOURCES:
        try:
            posted += check_source(source)
        except Exception as exc:
            message = f"{source['label']}: {exc}"
            print(f"ERROR: {message}")
            errors.append(message)

    print(f"\nDone. Posted {posted} update(s) total.")

    if errors:
        print("\nFailures:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
