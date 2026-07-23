import os
import re
import requests

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

APPLE_NEWS_URL = "https://developer.apple.com/news/"
APPLE_NEWS_BASE = "https://developer.apple.com"
STATE_FILE = os.path.join(os.path.dirname(__file__), "state", "last_article_id.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ARTICLE_PATTERN = re.compile(
    r'<a class="article-title" href="(/news/\?id=[^"]+)"><h2>([^<]+)</h2></a>'
)

def load_last_article_id():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            article_id = f.read().strip()
            return article_id or None
    except FileNotFoundError:
        return None

def save_last_article_id(article_id):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(article_id)

def fetch_latest_apple_news():
    print(f"Fetching Apple Developer News from {APPLE_NEWS_URL}...")

    response = requests.get(APPLE_NEWS_URL, headers=HEADERS, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"❌ Failed to fetch Apple Developer News. Server returned HTTP status {response.status_code}")

    match = ARTICLE_PATTERN.search(response.text)
    if not match:
        raise RuntimeError("❌ Could not find any news articles on the Apple Developer News page.")

    path, title = match.groups()
    article_id = path.rsplit("id=", 1)[-1]
    return title.strip(), f"{APPLE_NEWS_BASE}{path}", article_id

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL environment variable is missing or empty!")

    title, link, article_id = fetch_latest_apple_news()
    last_id = load_last_article_id()

    print(f"Latest Article ID: '{article_id}'")
    print(f"Latest Article Title: '{title}'")

    if last_id == article_id:
        print("No new articles since last run. Skipping Slack post.")
        return

    if last_id:
        print(f"New article detected (previous ID: '{last_id}').")
    else:
        print("First run with no saved state. Posting latest article.")

    print("Posting to Slack...")

    payload = {
        "text": f"📢 *Latest Apple Developer News*\n*<{link}|{title}>*"
    }

    res = requests.post(WEBHOOK_URL, json=payload, timeout=10)

    if res.status_code != 200:
        raise RuntimeError(f"❌ Slack Webhook rejected the message. Status: {res.status_code}, Response: {res.text}")

    save_last_article_id(article_id)
    print("✅ Successfully posted to Slack!")

if __name__ == "__main__":
    check_apple_news()
