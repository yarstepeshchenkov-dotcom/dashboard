import feedparser
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def collect_news():
    url = "https://news.yandex.ru/search.rss?text=кухня+LITHIUM"
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logger.error(f"Ошибка RSS: {e}")
        return []

    mentions = []
    for entry in feed.entries:
        text = f"{entry.title}. {entry.summary}"[:500]
        mentions.append({
            "source": "Яндекс.Новости",
            "text": text,
            "sentiment": "neutral",
            "is_b2b": 0,
            "created_at": datetime(*entry.published_parsed[:6]).isoformat(),
            "viewed": 0
        })
    logger.info(f"✅ Яндекс.Новости: {len(mentions)} записей")
    return mentions
