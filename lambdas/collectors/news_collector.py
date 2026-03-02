"""
NewsCollector Lambda — Scrapes RSS feeds for supply-chain disruption keywords.
"""
import os
import json
import logging
import hashlib
from datetime import datetime, timezone

import boto3
import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3 = boto3.client("s3")
DDB = boto3.resource("dynamodb")

RAW_BUCKET = os.environ["RAW_BUCKET"]
SIGNALS_TABLE = os.environ["SIGNALS_TABLE"]

# Supply chain keywords for filtering
KEYWORDS = [
    "supply chain", "disruption", "shortage", "port congestion", "shipping delay",
    "trade embargo", "tariff", "semiconductor shortage", "raw material",
    "logistics", "freight", "container shortage", "factory shutdown",
    "strike", "hurricane", "typhoon", "earthquake", "flood",
    "supplier bankruptcy", "export ban", "customs delay",
]

RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.scmr.com/rss",
    "https://www.supplychaindive.com/feeds/news/",
    "https://www.freightwaves.com/feed",
]


def _matches_keywords(text: str) -> list:
    """Return list of matched keywords."""
    text_lower = text.lower()
    return [kw for kw in KEYWORDS if kw in text_lower]


def _hash_url(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def handler(event, context):
    """
    Triggered by EventBridge schedule or webhook.
    Scrapes RSS feeds, filters for supply chain relevance, stores signals.
    """
    logger.info("NewsCollector invoked: %s", json.dumps(event, default=str))

    table = DDB.Table(SIGNALS_TABLE)
    signals_found = 0
    ts = datetime.now(timezone.utc).isoformat()

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:  # Top 20 per feed
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                link = entry.get("link", "")
                combined_text = f"{title} {summary}"

                matched = _matches_keywords(combined_text)
                if not matched:
                    continue

                signal_id = f"news-{_hash_url(link)}"

                # Clean HTML from summary
                clean_summary = BeautifulSoup(summary, "html.parser").get_text()[:500]

                signal = {
                    "signal_id": signal_id,
                    "timestamp": ts,
                    "signal_type": "NEWS",
                    "source": feed_url,
                    "title": title[:200],
                    "summary": clean_summary,
                    "url": link,
                    "matched_keywords": matched,
                    "severity": "HIGH" if len(matched) >= 3 else "MEDIUM" if len(matched) >= 2 else "LOW",
                    "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400 * 7,
                }

                table.put_item(Item=signal)
                signals_found += 1

                # Store raw in S3
                S3.put_object(
                    Bucket=RAW_BUCKET,
                    Key=f"news/{ts[:10]}/{signal_id}.json",
                    Body=json.dumps(signal, default=str),
                    ContentType="application/json",
                )

        except Exception as e:
            logger.error("Error processing feed %s: %s", feed_url, str(e))
            continue

    logger.info("NewsCollector complete: %d signals found", signals_found)
    return {"signals_found": signals_found, "source": "NewsCollector"}
