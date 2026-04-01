"""
TradeSage Learning System
Analyzes paper trade outcomes and improves LLM prompts over time.
Runs after enough trades accumulate to form meaningful patterns.
"""

import json
import os
import threading
from datetime import datetime
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CONFIG
from core.trading_engine import load_trades, load_performance_notes, save_performance_notes


class LearningSystem:
    def __init__(self, llm_engine):
        self.llm = llm_engine
        self._lock = threading.Lock()

    def should_run_learning(self) -> bool:
        trades = load_trades()
        completed = [t for t in trades if t["status"] == "closed"]
        min_trades = CONFIG.get("min_trades_to_learn", 10)
        return len(completed) >= min_trades

    def run_learning_cycle(self, callback=None) -> dict:
        """
        Feeds completed trades to the LLM to generate updated performance notes.
        Runs in a background thread so it doesn't block the UI.
        """
        def _run():
            with self._lock:
                try:
                    trades = load_trades()
                    completed = [t for t in trades if t["status"] == "closed"]
                    if not completed:
                        if callback:
                            callback({"status": "no_trades", "notes": ""})
                        return

                    previous_notes = load_performance_notes()
                    result = self.llm.generate_learning_update(completed[-50:], previous_notes)

                    new_notes = result.get("performance_notes", previous_notes)
                    if new_notes:
                        save_performance_notes(new_notes)

                    outcome = {
                        "status": "success",
                        "win_rate": result.get("win_rate", 0),
                        "key_learnings": result.get("key_learnings", []),
                        "notes": new_notes,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    if callback:
                        callback(outcome)
                    return outcome

                except Exception as e:
                    if callback:
                        callback({"status": "error", "error": str(e)})

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"status": "started"}

    def get_performance_summary(self) -> dict:
        trades = load_trades()
        completed = [t for t in trades if t["status"] == "closed"]

        if not completed:
            return {"total_trades": 0}

        by_symbol = {}
        for t in completed:
            sym = t.get("symbol", "?")
            if sym not in by_symbol:
                by_symbol[sym] = {"trades": 0, "wins": 0, "pnl_sum": 0}
            by_symbol[sym]["trades"] += 1
            pnl = t.get("pnl_pct") or 0
            by_symbol[sym]["pnl_sum"] += pnl
            if pnl > 0:
                by_symbol[sym]["wins"] += 1

        return {
            "total_trades": len(completed),
            "by_symbol": by_symbol,
            "performance_notes": load_performance_notes(),
        }
