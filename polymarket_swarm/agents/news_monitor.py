"""Agent that monitors news sources and emits NewsItem messages."""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET

import aiohttp

from ..base_agent import BaseAgent
from ..types import Message, MessageType, NewsItem


def _parse_rss(xml_text: str) -> list[dict]:
    """Minimal RSS/Atom parser using stdlib xml."""
    entries: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return entries

    # RSS 2.0
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        # Strip HTML tags from description
        desc = re.sub(r"<[^>]+>", " ", html.unescape(desc))
        desc = re.sub(r"\s+", " ", desc).strip()
        entries.append({"title": title, "link": link, "summary": desc, "published": pub})

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title = (entry.findtext("atom:title", "", ns) or entry.findtext("title") or "").strip()
        link_el = entry.find("atom:link[@href]", ns) or entry.find("link[@href]")
        link = link_el.get("href", "") if link_el is not None else ""
        summary = (entry.findtext("atom:summary", "", ns) or entry.findtext("atom:content", "", ns) or "").strip()
        summary = re.sub(r"<[^>]+>", " ", html.unescape(summary))
        summary = re.sub(r"\s+", " ", summary).strip()
        pub = (entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns) or "").strip()
        entries.append({"title": title, "link": link, "summary": summary, "published": pub})

    return entries


class NewsMonitorAgent(BaseAgent):
    name = "news_monitor"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen: set[str] = set()
        self._session: aiohttp.ClientSession | None = None

    # ---- proactive: poll RSS feeds on interval ----

    async def _run(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

        feeds = self.config.news.rss_feeds
        if not feeds:
            self.logger.warning("No RSS feeds configured, sleeping")
            await asyncio.sleep(60)
            return

        tasks = [self._poll_feed(url) for url in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self.logger.warning("Feed error: %s", result)
                continue
            if isinstance(result, list):
                for item in result:
                    await self.bus.publish(Message(
                        type=MessageType.NEWS_EVENT,
                        sender=self.name,
                        payload=item,
                    ))
                    self.logger.info("Published news: %s", item.title[:80])

        await asyncio.sleep(self.config.news.poll_interval_sec)

    async def _poll_feed(self, url: str) -> list[NewsItem]:
        items: list[NewsItem] = []
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                text = await resp.text()
        except Exception as exc:
            self.logger.debug("Fetch failed %s: %s", url, exc)
            return items

        entries = _parse_rss(text)
        keywords = [kw.lower() for kw in self.config.news.keywords]

        for entry in entries[:20]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")

            content_lower = f"{title} {summary}".lower()
            matched = [kw for kw in keywords if kw in content_lower]

            if not matched:
                continue

            fingerprint = hashlib.md5(f"{title}{link}".encode()).hexdigest()
            if fingerprint in self._seen:
                continue
            self._seen.add(fingerprint)

            items.append(NewsItem(
                title=title,
                summary=summary[:500],
                source=url,
                url=link,
                published=time.time(),
                keywords_matched=matched,
                relevance_score=min(1.0, len(matched) * 0.25),
            ))

        return items

    # ---- reactive: nothing for now ----

    async def _handle_message(self, message: Message) -> None:
        pass
