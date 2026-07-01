import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def collect_news():
    url = "https://news.yandex.ru/search.rss?text=кухня+LITHIUM"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        logger.error(f"Ошибка парсинга RSS: {e}")
        return []

    mentions = []
    for item in root.findall(".//item"):
        title = item.find("title")
        description = item.find("description")
        pub_date = item.find("pubDate")

        if title is not None and description is not None:
            text = f"{title.text}. {description.text}"[:500]
            try:
                if pub_date is not None and pub_date.text:
                    dt = datetime.strptime(pub_date.text[:25], "%a, %d %b %Y %H:%M:%S")
                    created_at = dt.isoformat()
                else:
                    created_at = datetime.now().isoformat()
            except:
                created_at = datetime.now().isoformat()

            mentions.append({
                "source": "Яндекс.Новости",
                "text": text,
                "sentiment": "neutral",
                "is_b2b": 0,
                "created_at": created_at,
                "viewed": 0
            })
    logger.info(f"✅ Яндекс.Новости: {len(mentions)} записей")
    return mentions
