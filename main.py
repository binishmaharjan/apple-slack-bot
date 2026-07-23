import os
import requests
import feedparser

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Raw proxy wrapper to bypass Akamai / Datacenter IP blocks
APPLE_RSS = "https://developer.apple.com/news/rss/news.rss"
PROXY_FEED_URL = f"https://api.allorigins.win/raw?url={APPLE_RSS}"

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL environment variable is missing or empty!")

    print("Fetching Apple RSS feed via AllOrigins raw proxy...")
    
    response = requests.get(PROXY_FEED_URL, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"❌ Proxy request failed with HTTP status {response.status_code}")

    # Parse the returned XML content
    feed = feedparser.parse(response.content)
    print(f"Found {len(feed.entries)} feed entries.")

    if not feed.entries:
        raise RuntimeError("❌ RSS Feed returned 0 entries. Proxy payload was empty or invalid XML.")

    latest = feed.entries[0]
    title = latest.title.strip()
    link = latest.link.strip()

    print(f"Latest Article Title: '{title}'")
    print("Posting to Slack...")

    payload = {
        "text": f"📢 *Latest Apple Developer News*\n*<{link}|{title}>*"
    }

    res = requests.post(WEBHOOK_URL, json=payload, timeout=10)

    if res.status_code != 200:
        raise RuntimeError(f"❌ Slack Webhook rejected the message. Status: {res.status_code}, Response: {res.text}")

    print("✅ Successfully posted to Slack!")

if __name__ == "__main__":
    check_apple_news()
