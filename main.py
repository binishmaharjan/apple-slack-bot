import os
import requests

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# We route through a public gateway to bypass Akamai/datacenter IP blocking
RSS_FEED_URL = "https://developer.apple.com/news/rss/news.rss"
PROXY_URL = f"https://api.rss2json.com/v1/api.json?rss_url={RSS_FEED_URL}"

def check_apple_news():
    if not WEBHOOK_URL:
        raise ValueError("❌ SLACK_WEBHOOK_URL environment variable is missing or empty!")

    print("Fetching Apple RSS feed via RSS-to-JSON proxy...")
    
    response = requests.get(PROXY_URL, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"❌ Proxy request failed with HTTP status {response.status_code}")

    data = response.json()

    if data.get("status") != "ok":
        raise RuntimeError(f"❌ RSS Proxy error: {data.get('message', 'Unknown error')}")

    items = data.get("items", [])
    print(f"Found {len(items)} feed entries.")

    if not items:
        raise RuntimeError("❌ No articles found in the feed.")

    latest = items[0]
    title = latest.get("title", "").strip()
    link = latest.get("link", "").strip()

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
