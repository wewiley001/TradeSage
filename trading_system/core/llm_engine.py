"""
TradeSage LLM Engine
Flexible LLM provider: Ollama (local) | Anthropic | OpenAI
Handles prompt construction, signal extraction, and learning.
"""

import json
import re
import requests
from datetime import datetime
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CONFIG


# ─────────────────────────────────────────────
# BASE PROMPT TEMPLATES
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are TradeSage, an expert quantitative trading analyst AI.
Your job is to analyze market data, news sentiment, and technical conditions
to produce structured trade signals.

RULES:
- You only output valid JSON — never prose, never markdown.
- Confidence scores are 0-100 integers.
- Signals are: BUY, SELL, or HOLD.
- You must cite specific news or data points that drive your signal.
- Be conservative — when uncertain, default to HOLD.
- Never recommend position sizes exceeding the user's max_position_pct setting.
"""

SIGNAL_PROMPT_TEMPLATE = """
Analyze the following market context and produce trade signals.

=== MARKET CONTEXT ===
Timestamp: {timestamp}
Watchlist: {symbols}

=== CURRENT QUOTES ===
{quotes}

=== RECENT NEWS (last 24h) ===
{news}

=== CURRENT POSITIONS ===
{positions}

=== ACCOUNT ===
Portfolio Value: {portfolio_value}
Cash Available: {cash}

=== PERFORMANCE NOTES (from learning system) ===
{performance_notes}

=== USER SETTINGS ===
Max position size: {max_position_pct}% of portfolio
Minimum confidence to act: {min_confidence}

Respond ONLY with this exact JSON structure:
{{
  "analysis_timestamp": "<ISO timestamp>",
  "market_sentiment": "bullish|bearish|neutral|mixed",
  "market_summary": "<2-3 sentence overall market read>",
  "signals": [
    {{
      "symbol": "<TICKER>",
      "signal": "BUY|SELL|HOLD",
      "confidence": <0-100>,
      "reasoning": "<specific data-backed reasoning>",
      "suggested_position_pct": <0-5>,
      "key_catalysts": ["<catalyst 1>", "<catalyst 2>"],
      "risk_factors": ["<risk 1>", "<risk 2>"],
      "time_horizon": "intraday|swing|position"
    }}
  ],
  "top_opportunity": "<ticker or null>",
  "risk_alert": "<any portfolio-level risk warning or null>"
}}
"""

SENTIMENT_PROMPT_TEMPLATE = """
Analyze the following news articles and rate the sentiment for each ticker.

=== NEWS ARTICLES ===
{news_text}

Respond ONLY with this exact JSON:
{{
  "sentiments": [
    {{
      "ticker": "<TICKER or MARKET>",
      "score": <-100 to 100>,
      "label": "very_bearish|bearish|neutral|bullish|very_bullish",
      "key_themes": ["<theme>"],
      "notable_headline": "<most impactful headline>"
    }}
  ],
  "overall_market_mood": "risk_on|risk_off|neutral"
}}
"""

LEARNING_PROMPT_TEMPLATE = """
Review the following completed paper trades and their outcomes.
Identify what patterns led to successful vs unsuccessful predictions.

=== COMPLETED TRADES ===
{trades}

=== PREVIOUS PROMPT NOTES ===
{previous_notes}

Produce updated guidance notes (max 200 words) that should be prepended
to future analysis prompts to improve accuracy. Focus on:
- Market conditions where signals were wrong
- News patterns that were misleading
- Time-of-day or volatility patterns

Respond ONLY with JSON:
{{
  "performance_notes": "<updated guidance string>",
  "win_rate": <0-100>,
  "key_learnings": ["<learning 1>", "<learning 2>", "<learning 3>"]
}}
"""


# ─────────────────────────────────────────────
# LLM PROVIDERS
# ─────────────────────────────────────────────

class OllamaProvider:
    def complete(self, system: str, user: str, model: str = None) -> str:
        model = model or CONFIG["llm_model"]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
        }
        r = requests.post(
            f"{CONFIG['ollama_base_url']}/api/chat",
            json=payload, timeout=120
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


class AnthropicProvider:
    def complete(self, system: str, user: str, model: str = None) -> str:
        model = model or CONFIG["anthropic_model"]
        headers = {
            "x-api-key": CONFIG["anthropic_api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers, json=payload, timeout=60
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


class OpenAIProvider:
    def complete(self, system: str, user: str, model: str = None) -> str:
        model = model or CONFIG["openai_model"]
        headers = {
            "Authorization": f"Bearer {CONFIG['openai_api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=payload, timeout=60
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def get_provider():
    p = CONFIG.get("llm_provider", "ollama")
    if p == "anthropic":
        return AnthropicProvider()
    elif p == "openai":
        return OpenAIProvider()
    else:
        return OllamaProvider()


# ─────────────────────────────────────────────
# MAIN LLM ENGINE
# ─────────────────────────────────────────────

class LLMEngine:
    def __init__(self):
        self.provider = get_provider()

    def reload_provider(self):
        self.provider = get_provider()

    def _safe_parse(self, raw: str) -> dict:
        """Strip markdown fences and parse JSON safely."""
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        return json.loads(cleaned)

    def generate_signals(self, context: dict, performance_notes: str = "") -> dict:
        """
        Given aggregated market context, return structured trade signals.
        """
        quotes_text = "\n".join([
            f"  {sym}: ${data.get('price','N/A')} | "
            f"Change: {data.get('change_pct','N/A')}% | "
            f"Vol: {data.get('volume','N/A')}"
            for sym, data in context.get("quotes", {}).items()
        ]) or "No quote data available."

        news_items = context.get("news", [])
        news_text = "\n".join([
            f"  [{n.get('ticker','?')}] {n.get('title','')} "
            f"(sentiment: {n.get('sentiment','?')}, source: {n.get('source','?')})"
            for n in news_items[:15]
        ]) or "No news data available."

        positions_text = "\n".join([
            f"  {p.get('symbol')}: {p.get('qty')} shares @ ${p.get('avg_cost')} | "
            f"P&L: {p.get('unrealized_plpc','?')}%"
            for p in context.get("positions", [])
        ]) or "No open positions."

        account = context.get("account", {})
        portfolio_value = account.get("portfolio_value", "N/A")
        cash = account.get("cash", "N/A")

        user_prompt = SIGNAL_PROMPT_TEMPLATE.format(
            timestamp=context.get("timestamp", datetime.utcnow().isoformat()),
            symbols=", ".join(context.get("symbols", [])),
            quotes=quotes_text,
            news=news_text,
            positions=positions_text,
            portfolio_value=portfolio_value,
            cash=cash,
            performance_notes=performance_notes or "No performance notes yet.",
            max_position_pct=CONFIG["max_position_pct"],
            min_confidence=CONFIG["min_confidence"],
        )

        try:
            raw = self.provider.complete(SYSTEM_PROMPT, user_prompt)
            result = self._safe_parse(raw)
            result["_raw"] = raw
            result["_error"] = None
            return result
        except Exception as e:
            return {
                "error": str(e),
                "_error": str(e),
                "signals": [],
                "market_summary": f"LLM error: {e}",
            }

    def analyze_sentiment(self, news_items: list) -> dict:
        """Pure news sentiment analysis pass."""
        news_text = "\n".join([
            f"[{n.get('ticker','MARKET')}] {n.get('title','')} - {n.get('description','')[:200]}"
            for n in news_items[:20]
        ])
        prompt = SENTIMENT_PROMPT_TEMPLATE.format(news_text=news_text)
        try:
            raw = self.provider.complete(SYSTEM_PROMPT, prompt)
            return self._safe_parse(raw)
        except Exception as e:
            return {"error": str(e), "sentiments": []}

    def generate_learning_update(self, completed_trades: list, previous_notes: str = "") -> dict:
        """
        After trades close, feed outcomes back to improve future prompts.
        """
        trades_text = json.dumps(completed_trades, indent=2)
        prompt = LEARNING_PROMPT_TEMPLATE.format(
            trades=trades_text,
            previous_notes=previous_notes or "None yet.",
        )
        try:
            raw = self.provider.complete(SYSTEM_PROMPT, prompt)
            return self._safe_parse(raw)
        except Exception as e:
            return {"error": str(e), "performance_notes": previous_notes}
