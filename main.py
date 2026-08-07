import html
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone

import feedparser
import requests

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
LEGACY_APPLE_STATE_FILE = os.path.join(STATE_DIR, "last_article_id.txt")
FEED_ENTRY_LIMIT = 100
SLACK_POST_DELAY_SECONDS = 1
STATE_VERSION = 4

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


def today_utc():
    return datetime.now(timezone.utc).date()


def parse_date_string(value):
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass

    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if match:
        return date.fromisoformat(match.group(1))

    return None


def parse_feed_entry_date(entry):
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)

    for field in ("published", "updated"):
        parsed = parse_date_string(entry.get(field, ""))
        if parsed:
            return parsed

    return None


def parse_stored_date(raw_value):
    if not raw_value:
        return None
    if isinstance(raw_value, date):
        return raw_value
    return parse_date_string(str(raw_value))


def is_older_than_last_posted(entry, last_posted_date):
    if not last_posted_date:
        return False

    published_date = entry.get("published_date")
    if not published_date:
        return False

    return published_date < last_posted_date


def derive_last_posted_date(entries, seen_ids, fallback=None):
    seen_dates = [
        entry["published_date"]
        for entry in entries
        if entry["id"] in seen_ids and entry.get("published_date")
    ]
    if seen_dates:
        return max(seen_dates)

    entry_dates = [entry.get("published_date") for entry in entries if entry.get("published_date")]
    if entry_dates:
        return max(entry_dates)

    return fallback


def advance_last_posted_date(last_posted_date, entry):
    published_date = entry.get("published_date")
    if not published_date:
        return last_posted_date
    if not last_posted_date or published_date > last_posted_date:
        return published_date
    return last_posted_date


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
        last_posted_date = parse_stored_date(
            data.get("last_posted_date") or data.get("cutoff_date")
        )
        return (
            seen_ids,
            bool(data.get("bootstrapped", False)),
            False,
            state_version,
            last_posted_date,
        )
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid state file '{json_path}': {exc}") from exc

    legacy_id = load_legacy_txt_id(source_id)
    if legacy_id:
        return {legacy_id}, False, True, 1, None

    return set(), False, False, 1, None


def save_state(
    source_id, seen_ids, bootstrapped, version=STATE_VERSION, last_posted_date=None
):
    os.makedirs(STATE_DIR, exist_ok=True)
    payload = {
        "version": version,
        "seen_ids": sorted(seen_ids),
        "bootstrapped": bootstrapped,
    }
    if last_posted_date:
        payload["last_posted_date"] = last_posted_date.isoformat()
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
        return "", "", None

    tags = {
        match.group("key"): match.group("value")
        for match in META_TAG_PATTERN.finditer(response.text)
    }

    description = tags.get("og:description") or tags.get("twitter:description") or ""
    image_url = tags.get("og:image") or tags.get("twitter:image") or ""
    published_raw = (
        tags.get("article:published_time")
        or tags.get("og:updated_time")
        or tags.get("article:modified_time")
        or ""
    )
    published_date = parse_date_string(published_raw)
    return description.strip(), image_url.strip(), published_date


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
                "published_date": parse_feed_entry_date(entry),
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
    if entry.get("description") and entry.get("published_date"):
        return

    description, image_url, published_date = fetch_article_preview(entry["link"])
    if description and not entry.get("description"):
        entry["description"] = description
    if image_url and not entry.get("image_url"):
        entry["image_url"] = image_url
    if published_date and not entry.get("published_date"):
        entry["published_date"] = published_date


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
    seen_ids, bootstrapped, legacy_migration, state_version, last_posted_date = load_state(
        source["id"]
    )
    current_ids = {entry["id"] for entry in entries}

    print(f"Seen IDs: {len(seen_ids)} | Fetched: {len(current_ids)}")
    if last_posted_date:
        print(f"Last posted date: {last_posted_date.isoformat()}")

    if legacy_migration:
        last_posted_date = derive_last_posted_date(entries, current_ids, fallback=today_utc())
        save_state(
            source["id"],
            current_ids,
            bootstrapped=True,
            last_posted_date=last_posted_date,
        )
        print(
            f"Legacy migration: marked {len(current_ids)} current ID(s) as seen. "
            f"Last posted date set to {last_posted_date.isoformat()}. "
            "No posts during migration."
        )
        return 0

    if not bootstrapped:
        last_posted_date = derive_last_posted_date(entries, current_ids, fallback=today_utc())
        save_state(
            source["id"],
            current_ids,
            bootstrapped=True,
            last_posted_date=last_posted_date,
        )
        print(
            f"Bootstrap complete: marked {len(current_ids)} ID(s) as seen. "
            f"Last posted date set to {last_posted_date.isoformat()}. "
            "No posts on first run."
        )
        return 0

    if state_version < STATE_VERSION:
        if state_version < 2:
            added = len(current_ids - seen_ids)
            seen_ids |= current_ids
            print(
                f"State v2 migration: merged {added} ID(s) into seen set. "
                "No posts during migration."
            )
        if state_version < 4:
            last_posted_date = derive_last_posted_date(
                entries, seen_ids, fallback=last_posted_date or today_utc()
            )
            print(
                f"State v4 migration: last posted date set to "
                f"{last_posted_date.isoformat()}."
            )
        save_state(
            source["id"],
            seen_ids,
            bootstrapped=True,
            last_posted_date=last_posted_date,
        )
        return 0

    new_entries = [entry for entry in entries if entry["id"] not in seen_ids]
    new_entries.reverse()

    if not new_entries:
        print("No new entries since last run.")
        return 0

    entries_to_post = []
    skipped_old = 0

    for entry in new_entries:
        if source["type"] == "html" or not entry.get("published_date"):
            enrich_entry_preview(entry)

        if is_older_than_last_posted(entry, last_posted_date):
            seen_ids.add(entry["id"])
            skipped_old += 1
            published = entry.get("published_date")
            published_label = published.isoformat() if published else "unknown date"
            print(f"Skipping old entry ({published_label}): '{entry['title']}'")
            continue

        entries_to_post.append(entry)

    if skipped_old:
        save_state(
            source["id"],
            seen_ids,
            bootstrapped=True,
            last_posted_date=last_posted_date,
        )
        print(f"Marked {skipped_old} old entr{'y' if skipped_old == 1 else 'ies'} as seen.")

    if not entries_to_post:
        print("No new entries to post after date filter.")
        return 0

    print(
        f"Found {len(entries_to_post)} new entr{'y' if len(entries_to_post) == 1 else 'ies'} to post."
    )
    posted = 0

    for index, entry in enumerate(entries_to_post):
        print(f"Posting ({index + 1}/{len(entries_to_post)}): '{entry['title']}'")

        if source["type"] == "html" and not entry.get("description"):
            enrich_entry_preview(entry)

        payload = build_slack_payload(source, entry)
        post_to_slack(payload)

        seen_ids.add(entry["id"])
        last_posted_date = advance_last_posted_date(last_posted_date, entry)
        save_state(
            source["id"],
            seen_ids,
            bootstrapped=True,
            last_posted_date=last_posted_date,
        )
        posted += 1
        print("Successfully posted to Slack!")

        if index < len(entries_to_post) - 1:
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
