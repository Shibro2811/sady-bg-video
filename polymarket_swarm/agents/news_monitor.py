"""Agent that monitors news sources and emits NewsItem messages."""

from __future__ import annotations

import asyncio
import hashlib
import time

import aiohttp
import feedparser

from ..base_agent import BaseAgent
from ..types import Message, MessageType, NewsItem


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

        feed = feedparser.parse(text)
        keywords = [kw.lower() for kw in self.config.news.keywords]

        for entry in feed.entries[:20]:
            title = getattr(entry, "title", "")
            summary = getattr(entry, "summary", "")
            link = getattr(entry, "link", "")
            published = getattr(entry, "published_parsed", None)

            content_lower = f"{title} {summary}".lower()
            matched = [kw for kw in keywords if kw in content_lower]

            if not matched:
                continue

            fingerprint = hashlib.md5(f"{title}{link}".encode()).hexdigest()
            if fingerprint in self._seen:
                continue
            self._seen.add(fingerprint)

            pub_ts = time.mktime(published) if published else time.time()

            items.append(NewsItem(
                title=title,
                summary=summary[:500],
                source=url,
                url=link,
                published=pub_ts,
                keywords_matched=matched,
                relevance_score=min(1.0, len(matched) * 0.25),
            ))

        return items

    # ---- reactive: nothing for now ----

    async def _handle_message(self, message: Message) -> None:
        pass
