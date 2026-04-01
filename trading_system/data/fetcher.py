"""
TradeSage Data Layer
Data sources:
  - Alpaca Trading API  (paper trading, orders, positions, account)
  - Alpaca Market Data  (quotes, trades, bars - IEX feed, free)
  - Google News RSS     (free, no API key needed)
  - Marketstack         (optional, leave key blank to skip)
  - Stockdata.org       (optional, leave key blank to skip)
  - Portfolio Optimizer (optional)
"""

import requests
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, time as dtime, timezone, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CONFIG


# ─────────────────────────────────────────────
# MARKET HOURS HELPER
# ─────────────────────────────────────────────

def is_market_open() -> bool:
    """
    Returns True if US stock market is currently open.
    Regular hours: Mon-Fri 9:30am - 4:00pm Eastern.
    Does not account for holidays (Alpaca will reject orders on holidays anyway).
    """
    et_offset = timedelta(hours=-4)  # EDT; use -5 for EST (Nov-Mar)
    now_et = datetime.now(timezone.utc) + et_offset
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open  = dtime(9, 30)
    market_close = dtime(16, 0)
    return market_open <= now_et.time() < market_close

def market_status() -> str:
    """Human-readable market status string."""
    return "OPEN" if is_market_open() else "CLOSED"


# ─────────────────────────────────────────────
# ALPACA REQUEST ID LOG
# ─────────────────────────────────────────────

REQUEST_ID_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "logs", "alpaca_request_ids.json"
)

def _load_request_ids() -> deque:
    os.makedirs(os.path.dirname(REQUEST_ID_LOG_FILE), exist_ok=True)
    if os.path.exists(REQUEST_ID_LOG_FILE):
        try:
            with open(REQUEST_ID_LOG_FILE, "r") as f:
                return deque(json.load(f), maxlen=200)
        except Exception:
            pass
    return deque(maxlen=200)

def _save_request_ids(log: deque):
    try:
        os.makedirs(os.path.dirname(REQUEST_ID_LOG_FILE), exist_ok=True)
        with open(REQUEST_ID_LOG_FILE, "w") as f:
            json.dump(list(log), f, indent=2)
    except Exception:
        pass

def _record_request_id(response: requests.Response, endpoint: str):
    request_id = response.headers.get("X-Request-ID")
    if not request_id:
        return
    log = _load_request_ids()
    log.append({
        "request_id": request_id,
        "endpoint": endpoint,
        "status": response.status_code,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _save_request_ids(log)

def get_recent_request_ids(limit: int = 20) -> list:
    log = _load_request_ids()
    return list(log)[-limit:]


# ─────────────────────────────────────────────
# ALPACA CLIENT
# ─────────────────────────────────────────────

class AlpacaClient:
    DATA_URL = "https://data.alpaca.markets"

    def __init__(self):
        self.base_url = CONFIG["alpaca_base_url"]
        self.headers = {
            "APCA-API-KEY-ID":     CONFIG["alpaca_api_key"],
            "APCA-API-SECRET-KEY": CONFIG["alpaca_secret_key"],
        }

    def _get(self, path, params=None, base=None):
        url = f"{base or self.base_url}{path}"
        try:
            r = requests.get(url, headers=self.headers, params=params, timeout=10)
            _record_request_id(r, f"GET {path}")
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            req_id = e.response.headers.get("X-Request-ID", "unknown") if e.response else "unknown"
            return {"error": str(e), "x_request_id": req_id}
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path, payload):
        url = f"{self.base_url}{path}"
        try:
            r = requests.post(url, headers=self.headers, json=payload, timeout=10)
            _record_request_id(r, f"POST {path}")
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            req_id = e.response.headers.get("X-Request-ID", "unknown") if e.response else "unknown"
            return {"error": str(e), "x_request_id": req_id}
        except Exception as e:
            return {"error": str(e)}

    def _delete(self, path):
        url = f"{self.base_url}{path}"
        try:
            r = requests.delete(url, headers=self.headers, timeout=10)
            _record_request_id(r, f"DELETE {path}")
            r.raise_for_status()
            return {"success": True}
        except requests.HTTPError as e:
            req_id = e.response.headers.get("X-Request-ID", "unknown") if e.response else "unknown"
            return {"error": str(e), "x_request_id": req_id}
        except Exception as e:
            return {"error": str(e)}

    # ── Trading API ──────────────────────────

    def get_account(self):
        return self._get("/v2/account")

    def get_positions(self):
        return self._get("/v2/positions")

    def get_orders(self, status="all", limit=50):
        return self._get("/v2/orders", params={"status": status, "limit": limit})

    def place_order(self, symbol: str, qty: float, side: str,
                    order_type: str = "market", time_in_force: str = "day"):
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        return self._post("/v2/orders", payload)

    def cancel_all_orders(self):
        return self._delete("/v2/orders")

    def get_portfolio_history(self, period="1M", timeframe="1D"):
        return self._get("/v2/account/portfolio/history",
                         params={"period": period, "timeframe": timeframe})

    # ── Market Data API ──────────────────────
    # All use feed=iex which is free for paper accounts.

    def get_latest_quotes(self, symbols: list) -> dict:
        """Latest bid/ask quotes. Primary price source."""
        result = self._get("/v2/stocks/quotes/latest",
                           params={"symbols": ",".join(symbols), "feed": "iex"},
                           base=self.DATA_URL)
        return result

    def get_latest_trades(self, symbols: list) -> dict:
        """Latest trade prices. Used as fallback when quote has no price."""
        result = self._get("/v2/stocks/trades/latest",
                           params={"symbols": ",".join(symbols), "feed": "iex"},
                           base=self.DATA_URL)
        return result

    def get_bars(self, symbols: list, timeframe="1Day", limit=30) -> dict:
        """Historical OHLCV bars."""
        result = self._get("/v2/stocks/bars",
                           params={
                               "symbols": ",".join(symbols),
                               "timeframe": timeframe,
                               "limit": limit,
                               "feed": "iex",
                           },
                           base=self.DATA_URL)
        return result

    def get_snapshots(self, symbols: list) -> dict:
        """
        Snapshot = quote + trade + daily bar in one call.
        Best single call for getting current price + daily change.
        """
        result = self._get("/v2/stocks/snapshots",
                           params={"symbols": ",".join(symbols), "feed": "iex"},
                           base=self.DATA_URL)
        return result

    def get_alpaca_news(self, symbols: list = None, limit: int = 10) -> dict:
        """Alpaca's built-in news endpoint — no extra API key needed."""
        params = {"limit": limit, "sort": "desc"}
        if symbols:
            params["symbols"] = ",".join(symbols)
        return self._get("/v1beta1/news",
                         params=params,
                         base=self.DATA_URL)

    def get_prices(self, symbols: list) -> dict:
        """
        Best-effort price fetcher with three-tier fallback:
          1. Snapshots  (price + daily change in one call)
          2. Latest trades (price only, no change)
          3. Historical bars (last close, for after-hours)

        Returns dict: { "AAPL": {"price": 213.5, "change_pct": 1.2}, ... }
        """
        prices = {}

        # Tier 1: Snapshots
        try:
            snaps = self.get_snapshots(symbols)
            if "snapshots" in snaps:
                for sym, snap in snaps["snapshots"].items():
                    lt = snap.get("latestTrade", {})
                    dbar = snap.get("dailyBar", {})
                    prev = snap.get("prevDailyBar", {})
                    price = lt.get("p") or dbar.get("c")
                    prev_close = prev.get("c")
                    change_pct = None
                    if price and prev_close and prev_close > 0:
                        change_pct = round((price - prev_close) / prev_close * 100, 2)
                    if price:
                        prices[sym] = {
                            "price": float(price),
                            "change_pct": change_pct,
                            "volume": dbar.get("v"),
                            "high": dbar.get("h"),
                            "low":  dbar.get("l"),
                            "open": dbar.get("o"),
                            "source": "snapshot",
                        }
        except Exception:
            pass

        # Tier 2: Latest trades for any still missing
        missing = [s for s in symbols if s not in prices]
        if missing:
            try:
                trades = self.get_latest_trades(missing)
                if "trades" in trades:
                    for sym, trade in trades["trades"].items():
                        p = trade.get("p")
                        if p:
                            prices[sym] = {
                                "price": float(p),
                                "change_pct": None,
                                "volume": None,
                                "source": "latest_trade",
                            }
            except Exception:
                pass

        # Tier 3: Historical bar close for anything still missing
        missing = [s for s in symbols if s not in prices]
        if missing:
            try:
                bars = self.get_bars(missing, timeframe="1Day", limit=2)
                if "bars" in bars:
                    for sym, bar_list in bars["bars"].items():
                        if bar_list:
                            last_bar = bar_list[-1]
                            c = last_bar.get("c")
                            if c:
                                prices[sym] = {
                                    "price": float(c),
                                    "change_pct": None,
                                    "volume": last_bar.get("v"),
                                    "source": "historical_bar",
                                    "note": "Market closed — showing last close",
                                }
            except Exception:
                pass

        return prices


# ─────────────────────────────────────────────
# GOOGLE NEWS RSS
# No API key required. Uses Google's public RSS.
# ─────────────────────────────────────────────

class GoogleNewsRSS:
    BASE = "https://news.google.com/rss"

    def _fetch_rss(self, url: str) -> list:
        """Fetch and parse an RSS feed, return list of article dicts."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 TradeSage/1.0"}
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            articles = []
            for item in root.findall(".//item"):
                title = item.findtext("title", "")
                desc  = item.findtext("description", "")
                pub   = item.findtext("pubDate", "")
                link  = item.findtext("link", "")
                # Strip any HTML tags from description
                import re
                desc = re.sub(r"<[^>]+>", "", desc).strip()
                articles.append({
                    "title": title,
                    "description": desc[:300],
                    "published": pub,
                    "link": link,
                })
            return articles
        except Exception as e:
            return []

    def get_market_news(self, limit: int = 10) -> list:
        """General financial market news."""
        url = f"{self.BASE}/search?q=stock+market+finance&hl=en-US&gl=US&ceid=US:en"
        return self._fetch_rss(url)[:limit]

    def get_ticker_news(self, ticker: str, limit: int = 5) -> list:
        """News for a specific stock ticker."""
        url = f"{self.BASE}/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        return self._fetch_rss(url)[:limit]

    def get_sector_news(self, sector: str, limit: int = 5) -> list:
        """News for a sector e.g. 'technology', 'gold', 'forex'."""
        url = f"{self.BASE}/search?q={sector}+market&hl=en-US&gl=US&ceid=US:en"
        return self._fetch_rss(url)[:limit]


# ─────────────────────────────────────────────
# OPTIONAL: MARKETSTACK
# ─────────────────────────────────────────────

class MarketstackClient:
    BASE = "http://api.marketstack.com/v1"

    def __init__(self):
        self.key = CONFIG.get("marketstack_api_key", "")

    def available(self) -> bool:
        return bool(self.key)

    def _get(self, path, params=None):
        try:
            p = {"access_key": self.key, **(params or {})}
            r = requests.get(f"{self.BASE}{path}", params=p, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_eod(self, symbols: list, limit=30):
        return self._get("/eod", {"symbols": ",".join(symbols), "limit": limit})


# ─────────────────────────────────────────────
# OPTIONAL: STOCKDATA.ORG
# ─────────────────────────────────────────────

class StockdataClient:
    BASE = "https://api.stockdata.org/v1"

    def __init__(self):
        self.key = CONFIG.get("stockdata_api_key", "")

    def available(self) -> bool:
        return bool(self.key)

    def _get(self, path, params=None):
        try:
            p = {"api_token": self.key, **(params or {})}
            r = requests.get(f"{self.BASE}{path}", params=p, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_news(self, symbols: list, limit=10):
        return self._get("/news/all", {
            "symbols": ",".join(symbols),
            "filter_entities": "true",
            "limit": limit,
        })


# ─────────────────────────────────────────────
# OPTIONAL: PORTFOLIO OPTIMIZER
# ─────────────────────────────────────────────

class PortfolioOptimizerClient:
    BASE = "https://api.portfoliooptimizer.io/v1"

    def _post(self, path, payload):
        try:
            r = requests.post(f"{self.BASE}{path}", json=payload,
                              headers={"Content-Type": "application/json"}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def optimize_equal_weight(self, assets: list):
        return self._post("/portfolio/optimization/equal-weight",
                          {"assets": len(assets)})


# ─────────────────────────────────────────────
# DATA AGGREGATOR
# ─────────────────────────────────────────────

class DataAggregator:
    """
    Pulls from all available sources and returns a unified
    context dict ready to be passed to the LLM engine.
    Alpaca is the primary and only required source.
    All other sources are used only if API keys are configured.
    """
    def __init__(self):
        self.alpaca             = AlpacaClient()
        self.google_news        = GoogleNewsRSS()
        self.marketstack        = MarketstackClient()
        self.stockdata          = StockdataClient()
        self.portfolio_optimizer = PortfolioOptimizerClient()

    def get_market_context(self, symbols: list) -> dict:
        context = {
            "timestamp":      datetime.utcnow().isoformat(),
            "market_status":  market_status(),
            "market_open":    is_market_open(),
            "symbols":        symbols,
            "quotes":         {},
            "news":           [],
            "account":        {},
            "positions":      [],
            "errors":         [],
        }

        # ── Prices from Alpaca (with 3-tier fallback) ──
        try:
            prices = self.alpaca.get_prices(symbols)
            context["quotes"] = prices
            missing = [s for s in symbols if s not in prices]
            if missing:
                context["errors"].append(f"No price data for: {', '.join(missing)}")
        except Exception as e:
            context["errors"].append(f"Alpaca price error: {e}")

        # ── News: Alpaca built-in (always available) ──
        try:
            alpaca_news = self.alpaca.get_alpaca_news(symbols, limit=10)
            news_items = alpaca_news.get("news", [])
            for item in news_items:
                context["news"].append({
                    "source":      "Alpaca News",
                    "ticker":      ", ".join(item.get("symbols", [])),
                    "title":       item.get("headline", ""),
                    "description": item.get("summary", ""),
                    "published":   item.get("created_at", ""),
                    "sentiment":   "neutral",
                })
        except Exception as e:
            context["errors"].append(f"Alpaca news error: {e}")

        # ── News: Google News RSS (free, no key needed) ──
        try:
            # General market news
            gn_market = self.google_news.get_market_news(limit=5)
            for article in gn_market:
                context["news"].append({
                    "source":      "Google News",
                    "ticker":      "MARKET",
                    "title":       article.get("title", ""),
                    "description": article.get("description", ""),
                    "published":   article.get("published", ""),
                    "sentiment":   "neutral",
                })
            # Per-ticker news (limit to first 3 symbols to avoid rate limits)
            for sym in symbols[:3]:
                gn_ticker = self.google_news.get_ticker_news(sym, limit=3)
                for article in gn_ticker:
                    context["news"].append({
                        "source":      "Google News",
                        "ticker":      sym,
                        "title":       article.get("title", ""),
                        "description": article.get("description", ""),
                        "published":   article.get("published", ""),
                        "sentiment":   "neutral",
                    })
        except Exception as e:
            context["errors"].append(f"Google News error: {e}")

        # ── News: Stockdata.org (optional) ──
        if self.stockdata.available():
            try:
                sd = self.stockdata.get_news(symbols, limit=5)
                for item in sd.get("data", []):
                    context["news"].append({
                        "source":      "Stockdata.org",
                        "ticker":      ", ".join([e.get("symbol","") for e in item.get("entities",[])]),
                        "title":       item.get("title", ""),
                        "description": item.get("description", ""),
                        "published":   item.get("published_at", ""),
                        "sentiment":   item.get("sentiment", "neutral"),
                    })
            except Exception as e:
                context["errors"].append(f"Stockdata error: {e}")

        # ── Account + Positions from Alpaca ──
        try:
            context["account"] = self.alpaca.get_account()
            positions = self.alpaca.get_positions()
            if isinstance(positions, list):
                context["positions"] = [
                    {
                        "symbol":         p.get("symbol"),
                        "qty":            p.get("qty"),
                        "avg_cost":       p.get("avg_entry_price"),
                        "current_price":  p.get("current_price"),
                        "unrealized_pl":  p.get("unrealized_pl"),
                        "unrealized_plpc":p.get("unrealized_plpc"),
                    }
                    for p in positions
                ]
        except Exception as e:
            context["errors"].append(f"Alpaca account error: {e}")

        return context
