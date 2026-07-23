import os
import feedparser
from curl_cffi import requests

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
APPLE_RSS = "https://developer.apple.com/news/rss/news.rss"

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL environment variable is missing or empty!")

    print("Fetching Apple RSS feed using TLS browser impersonation...")
    
    # Impersonate a real Chrome browser's TLS signature and HTTP/2 framing
    response = requests.get(
        APPLE_RSS,
        impersonate="chrome",
        timeout=15
    )
    
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"❌ Failed to fetch feed. Server returned HTTP status {response.status_code}")

    # Parse the returned XML content
    feed = feedparser.parse(response.content)
    print(f"Found {len(feed.entries)} feed entries.")

    if not feed.entries:
        raise RuntimeError("❌ RSS Feed returned 0 entries. Parsing failed or payload empty.")

    latest = feed.entries[0]
    title = latest.title.strip()
    link = latest.link.strip()

    print(f"Latest Article Title: '{title}'")
    print("Posting to Slack...")

    payload = {
        "text": f"📢 *Latest Apple Developer News*\n*<{link}|{title}>*"
    }

    # Standard post to Slack Webhook
    res = requests.post(WEBHOOK_URL, json=payload, timeout=10)

    if res.status_code != 200:
        raise RuntimeError(f"❌ Slack Webhook rejected the message. Status: {res.status_code}, Response: {res.text}")

    print("✅ Successfully posted to Slack!")

if __name__ == "__main__":
    check_apple_news()
