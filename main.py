import os
import requests
import feedparser

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
FEED_URL = "https://developer.apple.com/news/rss/news.rss"

# Custom User-Agent to mimic a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"
}

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL variable is missing or empty!")

    print("Fetching Apple RSS feed...")
    response = requests.get(FEED_URL, headers=HEADERS, timeout=15)
    
    print(f"HTTP Status Code: {response.status_code}")
    
    if response.status_code != 200:
        raise RuntimeError(f"❌ Failed to fetch RSS feed. Server returned status {response.status_code}")

    # Parse RSS feed content
    feed = feedparser.parse(response.content)
    print(f"Found {len(feed.entries)} feed entries.")

    if not feed.entries:
        # Print snippet of response body if feedparser found no entries
        print("Response preview:", response.text[:300])
        raise RuntimeError("❌ RSS Feed returned 0 entries. Cloudflare or Apple might be blocking the request.")

    latest = feed.entries[0]
    title = latest.title.strip()
    link = latest.link.strip()

    print(f"Latest Article Title: '{title}'")
    print(f"Posting to Slack...")

    payload = {
        "text": f"📢 *Latest Apple Developer News*\n*<{link}|{title}>*"
    }

    res = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    
    if res.status_code != 200:
        raise RuntimeError(f"❌ Slack Webhook rejected the message. Status: {res.status_code}, Response: {res.text}")

    print("✅ Successfully posted to Slack!")

if __name__ == "__main__":
    check_apple_news()
