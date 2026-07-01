import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def collect_forum():
    url = "https://forumhouse.ru/search/?q=LITHIUM"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.error(f"Ошибка форума: {e}")
        return []

    mentions = []
    for post in soup.select(".search-result, .topic, .post"):
        text = post.get_text(strip=True)[:500]
        if len(text) > 20 and "LITHIUM" in text:
            mentions.append({
                "source": "ForumHouse",
                "text": text,
                "sentiment": "neutral",
                "is_b2b": 0,
                "created_at": datetime.now().isoformat(),
                "viewed": 0
            })
    logger.info(f"✅ ForumHouse: {len(mentions)} записей")
    return mentions
