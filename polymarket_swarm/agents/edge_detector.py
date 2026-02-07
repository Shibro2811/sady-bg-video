"""Agent that combines news + market data to detect trading edges using Claude."""

from __future__ import annotations

import asyncio
import json
import time

import anthropic

from ..base_agent import BaseAgent
from ..types import (
    EdgeSignal,
    MarketInfo,
    Message,
    MessageType,
    NewsItem,
    Side,
)

ANALYSIS_PROMPT = """\
You are a quantitative trader analyzing prediction markets for arbitrage.

ACTIVE POLYMARKET MARKETS (showing question, outcomes, current prices):
{markets_block}

NEWS EVENT:
Title: {title}
Summary: {summary}
Source: {source}
Keywords matched: {keywords}

TASK:
1. Identify which markets above are directly affected by this news.
2. For each affected market, estimate the FAIR probability after this news.
3. Calculate the edge (fair_price - current_price) for each affected outcome.
4. Only flag edges where |edge| > 0.05 (5 percentage points).

Respond with ONLY a JSON array. Each element:
{{
  "condition_id": "<condition_id of the affected market>",
  "token_index": <0-based index of the outcome token to trade>,
  "side": "BUY" or "SELL",
  "current_price": <current market price>,
  "fair_price": <your estimated fair price>,
  "edge": <fair_price - current_price for BUY, current_price - fair_price for SELL>,
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one sentence>",
  "pattern": "<one of: scheduled_announcement, settlement_lag, correlated_divergence, overreaction, calendar_mispricing, other>"
}}

If no markets are affected or no edge > 0.05 exists, return an empty array: []
Return ONLY the JSON array, no other text.
"""

SUM_CHECK_PROMPT = """\
You are scanning Polymarket for structural arbitrage.

These markets have outcome probabilities that sum to {total:.3f} instead of ~1.0:

{markets_block}

For each market, identify:
1. Which outcome is most mispriced
2. Whether to BUY (underpriced) or SELL (overpriced) that outcome
3. The fair price assuming probabilities should sum to 1.0

Respond with ONLY a JSON array:
{{
  "condition_id": "<condition_id>",
  "token_index": <index>,
  "side": "BUY" or "SELL",
  "current_price": <float>,
  "fair_price": <float>,
  "edge": <float>,
  "confidence": 0.8,
  "reasoning": "<one sentence>",
  "pattern": "sum_mispricing"
}}

Return ONLY the JSON array.
"""


class EdgeDetectorAgent(BaseAgent):
    name = "edge_detector"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client: anthropic.AsyncAnthropic | None = None
        self._markets: dict[str, MarketInfo] = {}
        self._pending_news: list[NewsItem] = []
        self._last_sum_check: float = 0.0

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            api_key = self.config.news.anthropic_api_key
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set — edge detector cannot analyze news")
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        return self._client

    # ---- proactive: periodic sum-of-probabilities check ----

    async def _run(self) -> None:
        # Process any queued news items
        while self._pending_news:
            item = self._pending_news.pop(0)
            await self._analyze_news(item)

        # Structural arbitrage: check probability sums every 2 minutes
        now = time.time()
        if now - self._last_sum_check > 120 and self._markets:
            await self._check_probability_sums()
            self._last_sum_check = now

        await asyncio.sleep(5)

    async def _analyze_news(self, news: NewsItem) -> None:
        if not self._markets:
            self.logger.info("No markets loaded yet, skipping news analysis")
            return

        # Build a compact market listing (top 200 by volume)
        sorted_markets = sorted(self._markets.values(), key=lambda m: m.volume, reverse=True)[:200]
        lines = []
        for m in sorted_markets:
            prices_str = ", ".join(
                f"{o}: ${p:.2f}" for o, p in zip(m.outcomes, m.outcome_prices)
            )
            lines.append(f"[{m.condition_id[:12]}...] {m.question} | {prices_str}")

        markets_block = "\n".join(lines)

        prompt = ANALYSIS_PROMPT.format(
            markets_block=markets_block,
            title=news.title,
            summary=news.summary,
            source=news.source,
            keywords=", ".join(news.keywords_matched),
        )

        try:
            client = self._get_client()
            resp = await client.messages.create(
                model=self.config.news.anthropic_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            signals = json.loads(raw)
        except json.JSONDecodeError:
            self.logger.warning("Claude returned non-JSON for news analysis")
            return
        except Exception as exc:
            self.logger.warning("Claude API error: %s", exc)
            return

        for sig in signals:
            cid = sig.get("condition_id", "")
            # Resolve truncated condition_id
            full_cid = self._resolve_condition_id(cid)
            if not full_cid:
                continue

            market = self._markets.get(full_cid)
            if not market:
                continue

            token_idx = sig.get("token_index", 0)
            if token_idx >= len(market.token_ids):
                continue

            edge_val = float(sig.get("edge", 0))
            if abs(edge_val) < self.config.trading.min_edge:
                continue

            signal = EdgeSignal(
                market=market,
                token_id=market.token_ids[token_idx],
                side=Side(sig.get("side", "BUY")),
                current_price=float(sig.get("current_price", 0)),
                estimated_fair_price=float(sig.get("fair_price", 0)),
                edge=edge_val,
                confidence=float(sig.get("confidence", 0)),
                reasoning=sig.get("reasoning", ""),
                news_item=news,
                pattern=sig.get("pattern", "other"),
            )

            self.logger.info(
                "EDGE DETECTED: %s | %s @ $%.2f -> fair $%.2f | edge %.2f | %s",
                market.question[:60],
                signal.side.value,
                signal.current_price,
                signal.estimated_fair_price,
                signal.edge,
                signal.pattern,
            )

            await self.bus.publish(Message(
                type=MessageType.EDGE_SIGNAL,
                sender=self.name,
                payload=signal,
            ))

    async def _check_probability_sums(self) -> None:
        """Find markets where outcome probabilities don't sum to ~1.0."""
        mispriced = []
        for m in self._markets.values():
            if len(m.outcome_prices) < 2:
                continue
            total = sum(m.outcome_prices)
            if abs(total - 1.0) > 0.05:  # more than 5% off
                mispriced.append((m, total))

        if not mispriced:
            return

        self.logger.info("Found %d markets with probability sum != 1.0", len(mispriced))

        # For simple cases, generate signals directly without LLM
        for market, total in mispriced[:20]:
            if total > 1.05:
                # Overpriced — sell the most overpriced outcome
                max_idx = max(range(len(market.outcome_prices)), key=lambda i: market.outcome_prices[i])
                fair = market.outcome_prices[max_idx] / total
                edge = market.outcome_prices[max_idx] - fair
                if edge > self.config.trading.min_edge and max_idx < len(market.token_ids):
                    signal = EdgeSignal(
                        market=market,
                        token_id=market.token_ids[max_idx],
                        side=Side.SELL,
                        current_price=market.outcome_prices[max_idx],
                        estimated_fair_price=fair,
                        edge=edge,
                        confidence=0.8,
                        reasoning=f"Probability sum {total:.3f} > 1.0, outcome overpriced",
                        pattern="sum_mispricing",
                    )
                    await self.bus.publish(Message(
                        type=MessageType.EDGE_SIGNAL,
                        sender=self.name,
                        payload=signal,
                    ))
            elif total < 0.95:
                # Underpriced — buy the cheapest outcome
                min_idx = min(range(len(market.outcome_prices)), key=lambda i: market.outcome_prices[i])
                fair = market.outcome_prices[min_idx] / total
                edge = fair - market.outcome_prices[min_idx]
                if edge > self.config.trading.min_edge and min_idx < len(market.token_ids):
                    signal = EdgeSignal(
                        market=market,
                        token_id=market.token_ids[min_idx],
                        side=Side.BUY,
                        current_price=market.outcome_prices[min_idx],
                        estimated_fair_price=fair,
                        edge=edge,
                        confidence=0.8,
                        reasoning=f"Probability sum {total:.3f} < 1.0, outcome underpriced",
                        pattern="sum_mispricing",
                    )
                    await self.bus.publish(Message(
                        type=MessageType.EDGE_SIGNAL,
                        sender=self.name,
                        payload=signal,
                    ))

    def _resolve_condition_id(self, partial: str) -> str | None:
        """Resolve a possibly truncated condition_id to its full form."""
        if partial in self._markets:
            return partial
        clean = partial.rstrip(".")
        for cid in self._markets:
            if cid.startswith(clean):
                return cid
        return None

    # ---- reactive: receive news and market updates ----

    async def _handle_message(self, message: Message) -> None:
        if message.type == MessageType.NEWS_EVENT:
            if isinstance(message.payload, NewsItem):
                self._pending_news.append(message.payload)

        elif message.type == MessageType.MARKET_UPDATE:
            payload = message.payload
            if isinstance(payload, list):
                for m in payload:
                    if isinstance(m, MarketInfo):
                        self._markets[m.condition_id] = m
            elif isinstance(payload, MarketInfo):
                self._markets[payload.condition_id] = payload
