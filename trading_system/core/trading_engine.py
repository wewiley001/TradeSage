"""
TradeSage Trading Engine
Handles:
 - Risk rules enforcement (kill switch, position limits, PDT, etc.)
 - Order execution via Alpaca paper trading
 - Autonomous mode: auto-execute + auto stop-loss/take-profit
 - Trade logging and outcome tracking for learning
"""

import json
import os
import uuid
from datetime import datetime, date
from typing import Optional
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CONFIG
from data.fetcher import AlpacaClient, is_market_open, market_status

TRADES_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "trades.json")
PERFORMANCE_NOTES_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "performance_notes.txt")


def load_trades() -> list:
    os.makedirs(os.path.dirname(TRADES_FILE), exist_ok=True)
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    return []


def save_trades(trades: list):
    os.makedirs(os.path.dirname(TRADES_FILE), exist_ok=True)
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)


def load_performance_notes() -> str:
    if os.path.exists(PERFORMANCE_NOTES_FILE):
        with open(PERFORMANCE_NOTES_FILE, "r") as f:
            return f.read()
    return ""


def save_performance_notes(notes: str):
    os.makedirs(os.path.dirname(PERFORMANCE_NOTES_FILE), exist_ok=True)
    with open(PERFORMANCE_NOTES_FILE, "w") as f:
        f.write(notes)


# ─────────────────────────────────────────────
# RISK ENGINE
# ─────────────────────────────────────────────

class RiskEngine:
    """
    Validates LLM signals against hard risk rules before execution.
    Returns (approved: bool, reason: str)

    Enforces:
    - Daily loss kill switch
    - Max position size
    - Min confidence threshold
    - Cash availability
    - Max open positions
    - Daily trade cap (autonomous mode)
    - Pattern Day Trader (PDT) rule
    """
    PDT_THRESHOLD = 25000.0
    PDT_MAX_DAY_TRADES = 3

    def __init__(self, account: dict, trades: list = None):
        self.account = account
        self.portfolio_value = float(account.get("portfolio_value", 0) or 0)
        self.cash = float(account.get("cash", 0) or 0)
        self.trades = trades or []
        self.daytrade_count = int(account.get("daytrade_count", 0) or 0)
        self.pattern_day_trader = account.get("pattern_day_trader", False)

    def check_daily_loss_killswitch(self) -> tuple:
        prev_close = float(self.account.get("last_equity", 0) or 0)
        if prev_close <= 0:
            return True, "OK"
        loss_pct = ((self.portfolio_value - prev_close) / prev_close) * 100
        limit = CONFIG["max_daily_loss_pct"]
        if loss_pct <= -limit:
            return False, f"KILL SWITCH: Daily loss {loss_pct:.1f}% exceeds -{limit}%"
        return True, f"Daily P&L: {loss_pct:.1f}%"

    def check_pdt_rule(self, symbol: str) -> tuple:
        if self.portfolio_value >= self.PDT_THRESHOLD:
            return True, "OK"
        if self.pattern_day_trader:
            return False, (
                f"PDT BLOCK: Account flagged as Pattern Day Trader "
                f"with portfolio ${self.portfolio_value:,.0f} < $25,000."
            )
        if self.daytrade_count >= self.PDT_MAX_DAY_TRADES:
            return False, (
                f"PDT BLOCK: {self.daytrade_count}/{self.PDT_MAX_DAY_TRADES} "
                f"day trades used in rolling 5-day window."
            )
        return True, f"PDT OK ({self.daytrade_count}/{self.PDT_MAX_DAY_TRADES} used)"

    def check_open_positions(self, positions: list) -> tuple:
        max_pos = CONFIG.get("max_open_positions", 5)
        open_count = len(positions)
        if open_count >= max_pos:
            return False, f"Max open positions reached ({open_count}/{max_pos})"
        return True, f"Positions: {open_count}/{max_pos}"

    def check_daily_trade_cap(self) -> tuple:
        """Prevents runaway autonomous trading — caps total trades per day."""
        max_daily = CONFIG.get("autonomous_max_trades_per_day", 10)
        today = date.today().isoformat()
        todays_trades = [
            t for t in self.trades
            if t.get("timestamp", "").startswith(today)
        ]
        if len(todays_trades) >= max_daily:
            return False, f"Daily trade cap reached ({len(todays_trades)}/{max_daily})"
        return True, f"Trades today: {len(todays_trades)}/{max_daily}"

    def validate_signal(self, signal: dict, current_price: float,
                        positions: list = None, autonomous: bool = False) -> tuple:
        symbol = signal.get("symbol", "?")
        action = signal.get("signal", "HOLD")
        confidence = signal.get("confidence", 0)
        suggested_pct = signal.get("suggested_position_pct", 0)

        if action == "HOLD":
            return True, "HOLD — no action needed"

        ok, reason = self.check_daily_loss_killswitch()
        if not ok:
            return False, reason

        if confidence < CONFIG["min_confidence"]:
            return False, f"Confidence {confidence} below minimum {CONFIG['min_confidence']}"

        max_pct = CONFIG["max_position_pct"]
        if suggested_pct > max_pct:
            return False, f"Suggested {suggested_pct}% exceeds max {max_pct}%"

        ok, reason = self.check_pdt_rule(symbol)
        if not ok:
            return False, reason

        if action == "BUY" and positions is not None:
            ok, reason = self.check_open_positions(positions)
            if not ok:
                return False, reason

        if autonomous:
            ok, reason = self.check_daily_trade_cap()
            if not ok:
                return False, reason

        if action == "BUY":
            max_dollars = self.portfolio_value * (max_pct / 100)
            max_dollars = min(max_dollars, self.cash)
            if max_dollars < current_price:
                return False, f"Insufficient cash (${self.cash:.0f}) for {symbol} @ ${current_price:.2f}"

        return True, "OK"

    def calculate_shares(self, signal: dict, current_price: float) -> float:
        pct = min(signal.get("suggested_position_pct", 1.0), CONFIG["max_position_pct"])
        dollars = self.portfolio_value * (pct / 100)
        dollars = min(dollars, self.cash * 0.95)
        if current_price <= 0:
            return 0
        return round(dollars / current_price, 2)


# ─────────────────────────────────────────────
# TRADING ENGINE
# ─────────────────────────────────────────────

class TradingEngine:
    def __init__(self):
        self.alpaca = AlpacaClient()
        self.trades = load_trades()
        self.active = True
        self.autonomous = CONFIG.get("autonomous_mode", False)
        # Callbacks for UI updates
        self.on_trade_executed = None    # fn(result: dict)
        self.on_position_closed = None  # fn(trade: dict)
        self.on_learning_needed = None  # fn()

    def set_autonomous(self, enabled: bool):
        self.autonomous = enabled
        CONFIG["autonomous_mode"] = enabled
        from config import save_config
        save_config(CONFIG)

    def execute_signal(self, signal: dict, context: dict,
                       force: bool = False) -> dict:
        """
        Execute a signal. force=True skips the autonomous check
        (used when user manually clicks Execute in the UI).
        """
        if not self.active:
            return {"status": "HALTED", "reason": "Trading engine manually halted"}

        if not is_market_open():
            return {
                "status": "MARKET_CLOSED",
                "symbol": signal.get("symbol"),
                "reason": f"Market is currently closed. Signals recorded but not executed.",
            }

        symbol = signal.get("symbol")
        action = signal.get("signal", "HOLD")
        confidence = signal.get("confidence", 0)

        if action == "HOLD":
            return {"status": "HOLD", "symbol": symbol, "reason": "Signal is HOLD"}

        quotes = context.get("quotes", {})
        quote = quotes.get(symbol, {})
        current_price = float(quote.get("price") or 0)

        if current_price <= 0:
            return {"status": "ERROR", "symbol": symbol, "reason": "No valid price data"}

        account = context.get("account", {})
        positions = context.get("positions", [])
        risk = RiskEngine(account, trades=self.trades)
        approved, reason = risk.validate_signal(
            signal, current_price,
            positions=positions,
            autonomous=self.autonomous and not force
        )

        if not approved:
            return {"status": "REJECTED", "symbol": symbol, "reason": reason, "signal": action}

        shares = risk.calculate_shares(signal, current_price)
        if shares <= 0:
            return {"status": "REJECTED", "symbol": symbol, "reason": "Calculated 0 shares"}

        side = "buy" if action == "BUY" else "sell"
        order_result = self.alpaca.place_order(symbol, shares, side)

        if "error" in order_result:
            return {
                "status": "ERROR",
                "symbol": symbol,
                "reason": order_result["error"],
                "x_request_id": order_result.get("x_request_id"),
            }

        trade_record = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "action": action,
            "shares": shares,
            "entry_price": current_price,
            "confidence": confidence,
            "reasoning": signal.get("reasoning", ""),
            "catalysts": signal.get("key_catalysts", []),
            "risks": signal.get("risk_factors", []),
            "order_id": order_result.get("id"),
            "status": "open",
            "exit_price": None,
            "exit_timestamp": None,
            "pnl_pct": None,
            "outcome": None,
            "autonomous": self.autonomous and not force,
            "stop_loss_pct": CONFIG.get("auto_stop_loss_pct", 2.0),
            "take_profit_pct": CONFIG.get("auto_take_profit_pct", 4.0),
        }

        self.trades.append(trade_record)
        save_trades(self.trades)

        result = {
            "status": "EXECUTED",
            "symbol": symbol,
            "action": action,
            "shares": shares,
            "price": current_price,
            "order_id": order_result.get("id"),
            "trade_id": trade_record["id"],
            "autonomous": trade_record["autonomous"],
        }

        if self.on_trade_executed:
            self.on_trade_executed(result)

        return result

    def run_autonomous_cycle(self, signals_result: dict, context: dict) -> list:
        """
        Called automatically after each analysis in autonomous mode.
        Iterates all signals and executes those that pass risk checks.
        Returns list of execution results.
        """
        if not self.autonomous or not self.active:
            return []

        results = []
        signals = signals_result.get("signals", [])

        for signal in signals:
            if signal.get("signal") == "HOLD":
                continue
            result = self.execute_signal(signal, context)
            results.append(result)

        return results

    def check_stop_loss_take_profit(self, context: dict) -> list:
        """
        Checks all open BUY trades against current prices.
        Auto-closes positions that hit stop-loss or take-profit targets.
        Returns list of closed trade records.
        """
        if not self.active:
            return []

        quotes = context.get("quotes", {})
        closed = []

        for trade in self.trades:
            if trade["status"] != "open" or trade["action"] != "BUY":
                continue

            symbol = trade["symbol"]
            entry = float(trade.get("entry_price") or 0)
            if entry <= 0:
                continue

            quote = quotes.get(symbol, {})
            current = float(quote.get("price") or 0)
            if current <= 0:
                continue

            pnl_pct = ((current - entry) / entry) * 100
            sl = float(trade.get("stop_loss_pct") or CONFIG.get("auto_stop_loss_pct", 2.0))
            tp = float(trade.get("take_profit_pct") or CONFIG.get("auto_take_profit_pct", 4.0))

            should_close = False
            close_reason = ""

            if pnl_pct <= -sl:
                should_close = True
                close_reason = f"Stop-loss hit ({pnl_pct:.1f}% <= -{sl}%)"
            elif pnl_pct >= tp:
                should_close = True
                close_reason = f"Take-profit hit ({pnl_pct:.1f}% >= +{tp}%)"

            if should_close:
                # Place sell order
                sell_result = self.alpaca.place_order(
                    symbol, float(trade["shares"]), "sell"
                )
                trade["status"] = "closed"
                trade["exit_price"] = current
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["pnl_pct"] = round(pnl_pct, 3)
                trade["outcome"] = "win" if pnl_pct > 0 else "loss"
                trade["close_reason"] = close_reason
                closed.append(trade)

                if self.on_position_closed:
                    self.on_position_closed(trade)

        if closed:
            save_trades(self.trades)
            # Trigger learning if enough closed trades
            completed = self.get_completed_trades()
            if (CONFIG.get("learning_enabled", True) and
                    len(completed) >= CONFIG.get("min_trades_to_learn", 10) and
                    len(completed) % CONFIG.get("min_trades_to_learn", 10) == 0):
                if self.on_learning_needed:
                    self.on_learning_needed()

        return closed

    def reconcile_open_trades(self, context: dict = None):
        """
        Sync open trade records against actual Alpaca positions.
        Marks trades closed if the position no longer exists.
        """
        positions = self.alpaca.get_positions()
        if not isinstance(positions, list):
            return

        held = {p["symbol"]: p for p in positions}
        updated = False

        for trade in self.trades:
            if trade["status"] != "open" or trade["action"] != "BUY":
                continue
            if trade["symbol"] not in held:
                # Position gone — closed externally
                entry = float(trade.get("entry_price") or 0)
                # Try to get price from context quotes
                current = 0
                if context:
                    q = context.get("quotes", {}).get(trade["symbol"], {})
                    current = float(q.get("price") or 0)
                pnl_pct = ((current - entry) / entry * 100) if entry > 0 and current > 0 else None
                trade["status"] = "closed"
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["exit_price"] = current or None
                trade["pnl_pct"] = round(pnl_pct, 3) if pnl_pct is not None else None
                trade["outcome"] = ("win" if pnl_pct and pnl_pct > 0 else "loss") if pnl_pct is not None else "unknown"
                trade["close_reason"] = "Closed externally / reconciled"
                updated = True

        if updated:
            save_trades(self.trades)

    def get_completed_trades(self, limit=200) -> list:
        return [t for t in self.trades if t["status"] == "closed"][-limit:]

    def get_open_trades(self) -> list:
        return [t for t in self.trades if t["status"] == "open"]

    def get_stats(self) -> dict:
        closed = self.get_completed_trades()
        if not closed:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_pnl": 0}

        wins = [t for t in closed if (t.get("pnl_pct") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl_pct") or 0) <= 0]
        pnls = [t.get("pnl_pct") or 0 for t in closed]
        auto_trades = [t for t in closed if t.get("autonomous")]

        return {
            "total": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "autonomous_trades": len(auto_trades),
        }

    def get_todays_trade_count(self) -> int:
        today = date.today().isoformat()
        return len([t for t in self.trades if t.get("timestamp", "").startswith(today)])

    def halt(self):
        self.active = False
        self.autonomous = False
        self.alpaca.cancel_all_orders()

    def resume(self):
        self.active = True
