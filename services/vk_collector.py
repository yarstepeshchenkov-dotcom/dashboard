import feedparser
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

GROUPS = ["lithiumhome", "design_interior", "kuhni_moskva", "premium_kuhni"]

def collect_vk_rss():
    mentions = []
    for group in GROUPS:
        url = f"https://vk.com/feeds/group/{group}"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                text = entry.get("summary", "")[:500]
                if "LITHIUM" in text:
                    mentions.append({
                        "source": "VK",
                        "text": text,
                        "sentiment": "neutral",
                        "is_b2b": 0,
                        "created_at": datetime(*entry.published_parsed[:6]).isoformat(),
                        "viewed": 0
                    })
        except Exception as e:
            logger.warning(f"Ошибка RSS для {group}: {e}")
    logger.info(f"✅ VK: {len(mentions)} записей")
    return mentions
