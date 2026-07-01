import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

GROUPS = ["lithiumhome", "design_interior", "kuhni_moskva", "premium_kuhni"]

def collect_vk_rss():
    mentions = []
    for group in GROUPS:
        url = f"https://vk.com/feeds/group/{group}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = item.find("title")
                description = item.find("description")
                pub_date = item.find("pubDate")
                if title is not None and title.text and "LITHIUM" in title.text:
                    text = description.text if description is not None else title.text
                    text = text[:500]
                    try:
                        if pub_date is not None and pub_date.text:
                            dt = datetime.strptime(pub_date.text[:25], "%a, %d %b %Y %H:%M:%S")
                            created_at = dt.isoformat()
                        else:
                            created_at = datetime.now().isoformat()
                    except:
                        created_at = datetime.now().isoformat()
                    mentions.append({
                        "source": "VK",
                        "text": text,
                        "sentiment": "neutral",
                        "is_b2b": 0,
                        "created_at": created_at,
                        "viewed": 0
                    })
        except Exception as e:
            logger.warning(f"Ошибка RSS для {group}: {e}")
    logger.info(f"✅ VK: {len(mentions)} записей")
    return mentions
