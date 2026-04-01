"""
TradeSage Configuration
All API keys, endpoints, and application settings
"""
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config", "settings.json")

DEFAULT_CONFIG = {
    # API Keys - filled in by user via Settings UI
    "alpaca_api_key": "",
    "alpaca_secret_key": "",
    "alpaca_paper": True,
    "alpaca_base_url": "https://paper-api.alpaca.markets",

    "marketstack_api_key": "",
    "stockdata_api_key": "",
    "newsdata_api_key": "",
    "ap_news_api_key": "",
    "portfolio_optimizer_url": "https://api.portfoliooptimizer.io/v1",

    # LLM Settings
    "llm_provider": "ollama",
    "llm_model": "llama3.1:8b",
    "ollama_base_url": "http://localhost:11434",
    "anthropic_api_key": "",
    "openai_api_key": "",
    "anthropic_model": "claude-sonnet-4-20250514",
    "openai_model": "gpt-4o",

    # Trading Settings
    "watchlist": ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"],
    "max_position_pct": 5.0,
    "min_confidence": 75,
    "max_daily_loss_pct": 3.0,
    "poll_interval_seconds": 60,

    # Autonomous Mode
    "autonomous_mode": False,           # Auto-execute signals without confirmation
    "auto_stop_loss_pct": 2.0,          # Close position if loss exceeds X%
    "auto_take_profit_pct": 4.0,        # Close position if gain exceeds X%
    "max_open_positions": 5,            # Max simultaneous open positions
    "autonomous_max_trades_per_day": 10, # Safety cap on daily autonomous trades

    # Learning Settings
    "learning_enabled": True,
    "min_trades_to_learn": 10,
    "performance_window_days": 30,
}


def load_config():
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            saved = json.load(f)
            merged = {**DEFAULT_CONFIG, **saved}
            return merged
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


CONFIG = load_config()
