"""
TradeSage - Main Desktop Application
PyQt5-based Windows desktop UI with:
 - News Sentiment Dashboard
 - LLM Trade Signals
 - Paper Trading Simulation Panel
 - Performance & Learning Tracker
 - Settings
"""

import sys
import os
import json
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTabWidget, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
        QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
        QGroupBox, QGridLayout, QSplitter, QFrame, QScrollArea,
        QProgressBar, QCheckBox, QHeaderView, QMessageBox, QSystemTrayIcon,
        QMenu, QAction, QStatusBar, QToolBar, QSizePolicy
    )
    from PyQt5.QtCore import (
        Qt, QTimer, QThread, pyqtSignal, QSize
    )
    from PyQt5.QtGui import (
        QFont, QColor, QPalette, QIcon, QPixmap, QBrush, QLinearGradient
    )
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False

from config import CONFIG, save_config
from data.fetcher import DataAggregator
from core.llm_engine import LLMEngine
from core.trading_engine import TradingEngine, load_performance_notes
from core.learning import LearningSystem
from data.fetcher import get_recent_request_ids, market_status, is_market_open


# ─────────────────────────────────────────────
# COLORS & THEME
# ─────────────────────────────────────────────

DARK_BG        = "#0D1117"
PANEL_BG       = "#161B22"
BORDER         = "#30363D"
ACCENT_GREEN   = "#00FF94"
ACCENT_RED     = "#FF4757"
ACCENT_BLUE    = "#58A6FF"
ACCENT_YELLOW  = "#FFD700"
TEXT_PRIMARY   = "#E6EDF3"
TEXT_SECONDARY = "#8B949E"
SIGNAL_BUY     = "#00FF94"
SIGNAL_SELL    = "#FF4757"
SIGNAL_HOLD    = "#FFD700"

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {DARK_BG};
    color: {TEXT_PRIMARY};
    font-family: 'Consolas', 'Courier New', monospace;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {PANEL_BG};
}}
QTabBar::tab {{
    background: {DARK_BG};
    color: {TEXT_SECONDARY};
    padding: 8px 20px;
    border: 1px solid {BORDER};
    border-bottom: none;
    font-size: 12px;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    background: {PANEL_BG};
    color: {ACCENT_GREEN};
    border-bottom: 2px solid {ACCENT_GREEN};
}}
QTabBar::tab:hover {{
    color: {TEXT_PRIMARY};
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
    font-size: 11px;
    color: {TEXT_SECONDARY};
    letter-spacing: 1px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QPushButton {{
    background-color: {PANEL_BG};
    color: {ACCENT_GREEN};
    border: 1px solid {ACCENT_GREEN};
    border-radius: 3px;
    padding: 6px 16px;
    font-family: 'Consolas', monospace;
    font-size: 11px;
    letter-spacing: 1px;
}}
QPushButton:hover {{
    background-color: {ACCENT_GREEN};
    color: {DARK_BG};
}}
QPushButton:disabled {{
    color: {TEXT_SECONDARY};
    border-color: {BORDER};
}}
QPushButton#danger {{
    color: {ACCENT_RED};
    border-color: {ACCENT_RED};
}}
QPushButton#danger:hover {{
    background-color: {ACCENT_RED};
    color: {DARK_BG};
}}
QPushButton#info {{
    color: {ACCENT_BLUE};
    border-color: {ACCENT_BLUE};
}}
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {DARK_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 4px 8px;
    font-family: 'Consolas', monospace;
    font-size: 12px;
    selection-background-color: {ACCENT_BLUE};
}}
QLineEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT_BLUE};
}}
QTableWidget {{
    background-color: {PANEL_BG};
    color: {TEXT_PRIMARY};
    gridline-color: {BORDER};
    border: none;
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 4px 8px;
    border-bottom: 1px solid {BORDER};
}}
QTableWidget::item:selected {{
    background-color: #1F2937;
}}
QHeaderView::section {{
    background-color: {DARK_BG};
    color: {TEXT_SECONDARY};
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QScrollBar:vertical {{
    background: {DARK_BG};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
}}
QStatusBar {{
    background: {PANEL_BG};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}
QLabel#heading {{
    color: {ACCENT_GREEN};
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 2px;
}}
QLabel#metric {{
    color: {TEXT_PRIMARY};
    font-size: 22px;
    font-weight: bold;
}}
QLabel#metric_label {{
    color: {TEXT_SECONDARY};
    font-size: 10px;
    letter-spacing: 1px;
}}
QProgressBar {{
    background: {DARK_BG};
    border: 1px solid {BORDER};
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT_GREEN};
    border-radius: 3px;
}}
"""


# ─────────────────────────────────────────────
# WORKER THREAD
# ─────────────────────────────────────────────

class AnalysisWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, aggregator, llm_engine, symbols):
        super().__init__()
        self.aggregator = aggregator
        self.llm_engine = llm_engine
        self.symbols = symbols

    def run(self):
        try:
            context = self.aggregator.get_market_context(self.symbols)
            notes = load_performance_notes()
            signals = self.llm_engine.generate_signals(context, notes)
            sentiment = self.llm_engine.analyze_sentiment(context.get("news", []))
            self.finished.emit({
                "context": context,
                "signals": signals,
                "sentiment": sentiment,
            })
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────
# SENTIMENT DASHBOARD TAB
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# SCROLLING TICKER BAR
# ─────────────────────────────────────────────

class TickerBar(QWidget):
    """
    Scrolling live ticker strip showing symbol, price, and % change.
    Animates continuously using a QTimer-driven offset.
    Updates data from the latest market context on each analysis cycle.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._items = []       # list of (symbol, price, change_pct)
        self._offset = 0.0
        self._content_width = 0
        self._speed = 1.0      # pixels per timer tick

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scroll)
        self._timer.start(30)  # ~33fps

    def update_quotes(self, quotes: dict):
        """Called with context["quotes"] after each analysis."""
        self._items = []
        for sym, data in quotes.items():
            price = data.get("price")
            chg = data.get("change_pct")
            if price is not None:
                self._items.append((sym, float(price), float(chg) if chg is not None else 0.0))
        self._offset = 0.0
        self._content_width = 0  # will be recalculated on next paint
        self.update()

    def _scroll(self):
        if self._content_width > self.width():
            self._offset += self._speed
            if self._offset > self._content_width:
                self._offset = 0
            self.update()

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QFont, QFontMetrics
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QColor(PANEL_BG))

        # Separator line at bottom
        painter.setPen(QColor(BORDER))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

        if not self._items:
            painter.setPen(QColor(TEXT_SECONDARY))
            painter.setFont(QFont("Consolas", 10))
            painter.drawText(self.rect(), Qt.AlignCenter, "Awaiting market data...")
            painter.end()
            return

        font = QFont("Consolas", 10, QFont.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        # Build item strings and measure total width
        ITEM_PAD = 40
        segments = []
        for sym, price, chg in self._items:
            arrow = "▲" if chg >= 0 else "▼"
            text = f"  {sym}  ${price:,.2f}  {arrow} {abs(chg):.2f}%  ·"
            w = fm.horizontalAdvance(text)
            color = ACCENT_GREEN if chg >= 0 else ACCENT_RED
            segments.append((text, w, color))

        total_w = sum(s[1] for s in segments) + ITEM_PAD
        self._content_width = total_w

        # Draw two copies for seamless looping
        x = -self._offset
        for _ in range(2):
            for text, w, color in segments:
                if x + w > 0 and x < self.width():
                    painter.setPen(QColor(color))
                    painter.drawText(int(x), int(self.height() * 0.72), text)
                x += w
            x += ITEM_PAD

        painter.end()



class SentimentTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # Header
        hdr = QLabel("◈  NEWS SENTIMENT DASHBOARD")
        hdr.setObjectName("heading")
        layout.addWidget(hdr)

        # Live scrolling ticker bar
        self.ticker_bar = TickerBar()
        layout.addWidget(self.ticker_bar)

        splitter = QSplitter(Qt.Horizontal)

        # Left: news feed table
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("RECENT NEWS FEED"))

        self.news_table = QTableWidget(0, 4)
        self.news_table.setHorizontalHeaderLabels(["TIME", "TICKER", "HEADLINE", "SENTIMENT"])
        self.news_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.news_table.setColumnWidth(0, 80)
        self.news_table.setColumnWidth(1, 70)
        self.news_table.setColumnWidth(3, 90)
        self.news_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.news_table.setSelectionBehavior(QTableWidget.SelectRows)
        left_layout.addWidget(self.news_table)
        splitter.addWidget(left)

        # Right: sentiment scores per ticker
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("TICKER SENTIMENT SCORES"))

        self.sentiment_table = QTableWidget(0, 3)
        self.sentiment_table.setHorizontalHeaderLabels(["TICKER", "SCORE", "LABEL"])
        self.sentiment_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sentiment_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.sentiment_table)

        self.market_mood_label = QLabel("MARKET MOOD: —")
        self.market_mood_label.setStyleSheet(f"color: {ACCENT_YELLOW}; font-size: 13px; font-weight: bold;")
        right_layout.addWidget(self.market_mood_label)

        splitter.addWidget(right)
        splitter.setSizes([600, 300])
        layout.addWidget(splitter)

    def update(self, context: dict, sentiment: dict):
        # Update ticker bar with latest quotes
        self.ticker_bar.update_quotes(context.get("quotes", {}))

        # News table
        news = context.get("news", [])
        self.news_table.setRowCount(0)
        for article in news:
            row = self.news_table.rowCount()
            self.news_table.insertRow(row)
            ts = article.get("published", "")[:16]
            ticker = article.get("ticker", "MARKET")
            title = article.get("title", "")
            sent = article.get("sentiment", "neutral")

            self.news_table.setItem(row, 0, QTableWidgetItem(ts))
            self.news_table.setItem(row, 1, QTableWidgetItem(ticker))
            self.news_table.setItem(row, 2, QTableWidgetItem(title))
            sent_item = QTableWidgetItem(sent.upper())
            color = ACCENT_GREEN if "pos" in sent else ACCENT_RED if "neg" in sent else ACCENT_YELLOW
            sent_item.setForeground(QBrush(QColor(color)))
            self.news_table.setItem(row, 3, sent_item)

        # Sentiment scores
        sentiments = sentiment.get("sentiments", [])
        self.sentiment_table.setRowCount(0)
        for s in sentiments:
            row = self.sentiment_table.rowCount()
            self.sentiment_table.insertRow(row)
            score = s.get("score", 0)
            label = s.get("label", "neutral")
            self.sentiment_table.setItem(row, 0, QTableWidgetItem(s.get("ticker", "?")))
            score_item = QTableWidgetItem(f"{score:+d}")
            color = ACCENT_GREEN if score > 0 else ACCENT_RED if score < 0 else ACCENT_YELLOW
            score_item.setForeground(QBrush(QColor(color)))
            self.sentiment_table.setItem(row, 1, score_item)
            self.sentiment_table.setItem(row, 2, QTableWidgetItem(label.upper()))

        # Market mood
        mood = sentiment.get("overall_market_mood", "neutral")
        mood_color = ACCENT_GREEN if mood == "risk_on" else ACCENT_RED if mood == "risk_off" else ACCENT_YELLOW
        self.market_mood_label.setText(f"MARKET MOOD: {mood.upper().replace('_',' ')}")
        self.market_mood_label.setStyleSheet(f"color: {mood_color}; font-size: 13px; font-weight: bold;")


# ─────────────────────────────────────────────
# SIGNALS TAB
# ─────────────────────────────────────────────

class SignalsTab(QWidget):
    execute_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("◈  LLM TRADE SIGNALS")
        hdr.setObjectName("heading")
        layout.addWidget(hdr)

        # Market summary box
        self.summary_box = QTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.setMaximumHeight(80)
        self.summary_box.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {BORDER}; color: {TEXT_PRIMARY};")
        layout.addWidget(self.summary_box)

        # Signals table
        self.signals_table = QTableWidget(0, 8)
        self.signals_table.setHorizontalHeaderLabels([
            "TICKER", "SIGNAL", "CONFIDENCE", "HORIZON", "POSITION %", "CATALYSTS", "RISKS", "ACTION"
        ])
        self.signals_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.signals_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.signals_table.setColumnWidth(0, 70)
        self.signals_table.setColumnWidth(1, 70)
        self.signals_table.setColumnWidth(2, 100)
        self.signals_table.setColumnWidth(3, 80)
        self.signals_table.setColumnWidth(4, 80)
        self.signals_table.setColumnWidth(7, 90)
        self.signals_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.signals_table)

        # Reasoning detail
        detail_label = QLabel("SIGNAL REASONING")
        detail_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; letter-spacing: 1px;")
        layout.addWidget(detail_label)

        self.reasoning_box = QTextEdit()
        self.reasoning_box.setReadOnly(True)
        self.reasoning_box.setMaximumHeight(100)
        layout.addWidget(self.reasoning_box)

        self.signals_table.cellClicked.connect(self._show_reasoning)
        self._signals_data = []

    def _show_reasoning(self, row, col):
        if row < len(self._signals_data):
            sig = self._signals_data[row]
            text = f"[{sig.get('symbol')}] {sig.get('signal')} | Confidence: {sig.get('confidence')}%\n\n"
            text += f"Reasoning: {sig.get('reasoning','')}\n\n"
            text += f"Catalysts: {', '.join(sig.get('key_catalysts',[]))}\n"
            text += f"Risks: {', '.join(sig.get('risk_factors',[]))}"
            self.reasoning_box.setPlainText(text)

    def update(self, signals_result: dict):
        self._signals_data = signals_result.get("signals", [])
        summary = signals_result.get("market_summary", "")
        sentiment_label = signals_result.get("market_sentiment", "").upper()
        self.summary_box.setPlainText(f"[{sentiment_label}] {summary}")

        risk_alert = signals_result.get("risk_alert")
        if risk_alert:
            self.summary_box.append(f"\n⚠ RISK ALERT: {risk_alert}")

        self.signals_table.setRowCount(0)
        for sig in self._signals_data:
            row = self.signals_table.rowCount()
            self.signals_table.insertRow(row)

            symbol = sig.get("symbol", "?")
            signal = sig.get("signal", "HOLD")
            confidence = sig.get("confidence", 0)
            horizon = sig.get("time_horizon", "?")
            pos_pct = sig.get("suggested_position_pct", 0)
            catalysts = ", ".join(sig.get("key_catalysts", []))
            risks = ", ".join(sig.get("risk_factors", []))

            self.signals_table.setItem(row, 0, QTableWidgetItem(symbol))

            sig_item = QTableWidgetItem(signal)
            color = SIGNAL_BUY if signal == "BUY" else SIGNAL_SELL if signal == "SELL" else SIGNAL_HOLD
            sig_item.setForeground(QBrush(QColor(color)))
            sig_item.setFont(QFont("Consolas", 11, QFont.Bold))
            self.signals_table.setItem(row, 1, sig_item)

            # Confidence bar simulation via color
            conf_item = QTableWidgetItem(f"{confidence}%")
            conf_color = ACCENT_GREEN if confidence >= 75 else ACCENT_YELLOW if confidence >= 50 else ACCENT_RED
            conf_item.setForeground(QBrush(QColor(conf_color)))
            self.signals_table.setItem(row, 2, conf_item)

            self.signals_table.setItem(row, 3, QTableWidgetItem(horizon))
            self.signals_table.setItem(row, 4, QTableWidgetItem(f"{pos_pct}%"))
            self.signals_table.setItem(row, 5, QTableWidgetItem(catalysts))
            self.signals_table.setItem(row, 6, QTableWidgetItem(risks))

            if signal != "HOLD":
                exec_btn = QPushButton("EXECUTE")
                exec_btn.setObjectName("info" if signal == "BUY" else "danger")
                exec_btn.setStyleSheet(
                    f"color: {SIGNAL_BUY if signal == 'BUY' else SIGNAL_SELL}; "
                    f"border: 1px solid {SIGNAL_BUY if signal == 'BUY' else SIGNAL_SELL}; "
                    f"background: transparent; padding: 2px 8px; font-size: 10px;"
                )
                exec_btn.clicked.connect(lambda checked, s=sig: self.execute_signal.emit(s))
                self.signals_table.setCellWidget(row, 7, exec_btn)
            else:
                self.signals_table.setItem(row, 7, QTableWidgetItem("—"))


# ─────────────────────────────────────────────
# PAPER TRADING TAB
# ─────────────────────────────────────────────

class PaperTradingTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("◈  PAPER TRADING SIMULATION")
        hdr.setObjectName("heading")
        layout.addWidget(hdr)

        # Account metrics
        metrics_frame = QFrame()
        metrics_layout = QHBoxLayout(metrics_frame)
        metrics_layout.setSpacing(20)

        self.portfolio_val = self._metric_widget("PORTFOLIO VALUE", "$0.00")
        self.cash_val = self._metric_widget("CASH", "$0.00")
        self.pnl_val = self._metric_widget("TODAY P&L", "$0.00")
        self.positions_count = self._metric_widget("POSITIONS", "0")

        for w in [self.portfolio_val, self.cash_val, self.pnl_val, self.positions_count]:
            metrics_layout.addWidget(w)
        layout.addWidget(metrics_frame)

        splitter = QSplitter(Qt.Horizontal)

        # Open positions
        left = QGroupBox("OPEN POSITIONS")
        left_layout = QVBoxLayout(left)
        self.positions_table = QTableWidget(0, 6)
        self.positions_table.setHorizontalHeaderLabels(
            ["SYMBOL", "QTY", "ENTRY", "CURRENT", "P&L $", "P&L %"])
        self.positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.positions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        left_layout.addWidget(self.positions_table)
        splitter.addWidget(left)

        # Trade log
        right = QGroupBox("TRADE LOG")
        right_layout = QVBoxLayout(right)
        self.trades_table = QTableWidget(0, 6)
        self.trades_table.setHorizontalHeaderLabels(
            ["TIME", "SYMBOL", "ACTION", "SHARES", "PRICE", "STATUS"])
        self.trades_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trades_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.trades_table)
        splitter.addWidget(right)

        layout.addWidget(splitter)

    def _metric_widget(self, label: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 4px; padding: 8px;")
        vl = QVBoxLayout(frame)
        vl.setSpacing(2)
        val_label = QLabel(value)
        val_label.setObjectName("metric")
        lbl = QLabel(label)
        lbl.setObjectName("metric_label")
        vl.addWidget(val_label)
        vl.addWidget(lbl)
        frame._value_label = val_label
        return frame

    def update_account(self, account: dict):
        pv = float(account.get("portfolio_value") or 0)
        cash = float(account.get("cash") or 0)
        prev = float(account.get("last_equity") or pv)
        pnl = pv - prev

        self.portfolio_val._value_label.setText(f"${pv:,.2f}")
        self.cash_val._value_label.setText(f"${cash:,.2f}")
        pnl_color = ACCENT_GREEN if pnl >= 0 else ACCENT_RED
        self.pnl_val._value_label.setText(f"${pnl:+,.2f}")
        self.pnl_val._value_label.setStyleSheet(f"color: {pnl_color}; font-size: 22px; font-weight: bold;")

    def update_positions(self, positions: list):
        self.positions_count._value_label.setText(str(len(positions)))
        self.positions_table.setRowCount(0)
        for p in positions:
            row = self.positions_table.rowCount()
            self.positions_table.insertRow(row)
            plpc = float(p.get("unrealized_plpc") or 0) * 100
            pl = float(p.get("unrealized_pl") or 0)
            self.positions_table.setItem(row, 0, QTableWidgetItem(p.get("symbol", "")))
            self.positions_table.setItem(row, 1, QTableWidgetItem(str(p.get("qty", ""))))
            self.positions_table.setItem(row, 2, QTableWidgetItem(f"${float(p.get('avg_cost') or 0):.2f}"))
            self.positions_table.setItem(row, 3, QTableWidgetItem(f"${float(p.get('current_price') or 0):.2f}"))
            pl_item = QTableWidgetItem(f"${pl:+.2f}")
            plpc_item = QTableWidgetItem(f"{plpc:+.1f}%")
            color = ACCENT_GREEN if pl >= 0 else ACCENT_RED
            pl_item.setForeground(QBrush(QColor(color)))
            plpc_item.setForeground(QBrush(QColor(color)))
            self.positions_table.setItem(row, 4, pl_item)
            self.positions_table.setItem(row, 5, plpc_item)

    def update_trades(self, trades: list):
        self.trades_table.setRowCount(0)
        for t in reversed(trades[-50:]):
            row = self.trades_table.rowCount()
            self.trades_table.insertRow(row)
            ts = t.get("timestamp", "")[:16]
            action = t.get("action", "")
            self.trades_table.setItem(row, 0, QTableWidgetItem(ts))
            self.trades_table.setItem(row, 1, QTableWidgetItem(t.get("symbol", "")))
            action_item = QTableWidgetItem(action)
            action_item.setForeground(QBrush(QColor(SIGNAL_BUY if action == "BUY" else SIGNAL_SELL)))
            self.trades_table.setItem(row, 2, action_item)
            self.trades_table.setItem(row, 3, QTableWidgetItem(str(t.get("shares", ""))))
            self.trades_table.setItem(row, 4, QTableWidgetItem(f"${float(t.get('entry_price') or 0):.2f}"))
            self.trades_table.setItem(row, 5, QTableWidgetItem(t.get("status", "").upper()))


# ─────────────────────────────────────────────
# PERFORMANCE TAB
# ─────────────────────────────────────────────

class PerformanceTab(QWidget):
    run_learning = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("◈  PERFORMANCE & LEARNING")
        hdr.setObjectName("heading")
        layout.addWidget(hdr)

        # Stats row
        stats_frame = QFrame()
        stats_layout = QHBoxLayout(stats_frame)
        self.total_trades_w = self._stat("TOTAL TRADES", "0")
        self.win_rate_w = self._stat("WIN RATE", "0%")
        self.avg_pnl_w = self._stat("AVG P&L", "0%")
        self.learning_status_w = self._stat("LEARNING", "IDLE")
        for w in [self.total_trades_w, self.win_rate_w, self.avg_pnl_w, self.learning_status_w]:
            stats_layout.addWidget(w)
        layout.addWidget(stats_frame)

        # Learning notes
        notes_group = QGroupBox("AI PERFORMANCE NOTES (auto-updated)")
        notes_layout = QVBoxLayout(notes_group)
        self.notes_box = QTextEdit()
        self.notes_box.setReadOnly(True)
        self.notes_box.setPlaceholderText("Performance notes will appear here after the learning system runs...")
        notes_layout.addWidget(self.notes_box)
        layout.addWidget(notes_group)

        # Key learnings
        learnings_group = QGroupBox("KEY LEARNINGS FROM RECENT TRADES")
        learnings_layout = QVBoxLayout(learnings_group)
        self.learnings_table = QTableWidget(0, 1)
        self.learnings_table.setHorizontalHeaderLabels(["LEARNING"])
        self.learnings_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.learnings_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.learnings_table.setMaximumHeight(150)
        learnings_layout.addWidget(self.learnings_table)
        layout.addWidget(learnings_group)

        # Run learning button
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("⟳  RUN LEARNING CYCLE NOW")
        self.run_btn.clicked.connect(self.run_learning.emit)
        btn_layout.addStretch()
        btn_layout.addWidget(self.run_btn)
        layout.addWidget(QWidget())
        layout.addLayout(btn_layout)

    def _stat(self, label: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 4px; padding: 8px;")
        vl = QVBoxLayout(frame)
        val = QLabel(value)
        val.setObjectName("metric")
        lbl = QLabel(label)
        lbl.setObjectName("metric_label")
        vl.addWidget(val)
        vl.addWidget(lbl)
        frame._value = val
        return frame

    def update_stats(self, stats: dict):
        self.total_trades_w._value.setText(str(stats.get("total", 0)))
        wr = stats.get("win_rate", 0)
        self.win_rate_w._value.setText(f"{wr:.1f}%")
        wr_color = ACCENT_GREEN if wr >= 55 else ACCENT_YELLOW if wr >= 45 else ACCENT_RED
        self.win_rate_w._value.setStyleSheet(f"color: {wr_color}; font-size: 22px; font-weight: bold;")
        avg = stats.get("avg_pnl", 0)
        self.avg_pnl_w._value.setText(f"{avg:+.2f}%")
        avg_color = ACCENT_GREEN if avg > 0 else ACCENT_RED
        self.avg_pnl_w._value.setStyleSheet(f"color: {avg_color}; font-size: 22px; font-weight: bold;")

    def update_learning(self, result: dict):
        self.learning_status_w._value.setText("COMPLETE")
        self.learning_status_w._value.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 22px; font-weight: bold;")
        notes = result.get("notes", "")
        if notes:
            self.notes_box.setPlainText(notes)
        learnings = result.get("key_learnings", [])
        self.learnings_table.setRowCount(0)
        for l in learnings:
            row = self.learnings_table.rowCount()
            self.learnings_table.insertRow(row)
            self.learnings_table.setItem(row, 0, QTableWidgetItem(l))

    def set_learning_running(self):
        self.learning_status_w._value.setText("RUNNING...")
        self.learning_status_w._value.setStyleSheet(f"color: {ACCENT_YELLOW}; font-size: 22px; font-weight: bold;")
        self.run_btn.setEnabled(False)

    def set_learning_idle(self):
        self.run_btn.setEnabled(True)


# ─────────────────────────────────────────────
# SETTINGS TAB
# ─────────────────────────────────────────────

class SettingsTab(QWidget):
    settings_saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("◈  SETTINGS & API CONFIGURATION")
        hdr.setObjectName("heading")
        layout.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"border: none; background: transparent;")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)

        # API Keys
        api_group = QGroupBox("API KEYS")
        api_layout = QGridLayout(api_group)
        api_layout.setSpacing(8)

        self.fields = {}
        api_fields = [
            ("alpaca_api_key",      "Alpaca API Key  (required)"),
            ("alpaca_secret_key",   "Alpaca Secret Key  (required)"),
            ("marketstack_api_key", "Marketstack API Key  (optional)"),
            ("stockdata_api_key",   "Stockdata.org API Key  (optional)"),
            ("anthropic_api_key",   "Anthropic API Key  (optional LLM)"),
            ("openai_api_key",      "OpenAI API Key  (optional LLM)"),
        ]
        # Note shown below keys
        news_note = QLabel("Google News RSS is used automatically for news — no key needed.")
        news_note.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 10px; padding: 2px 0;")
        for i, (key, label) in enumerate(api_fields):
            api_layout.addWidget(QLabel(label), i, 0)
            field = QLineEdit(CONFIG.get(key, ""))
            field.setEchoMode(QLineEdit.Password)
            self.fields[key] = field
            api_layout.addWidget(field, i, 1)
        api_layout.addWidget(news_note, len(api_fields), 0, 1, 2)
        content_layout.addWidget(api_group)

        # LLM Settings
        llm_group = QGroupBox("LLM SETTINGS")
        llm_layout = QGridLayout(llm_group)

        llm_layout.addWidget(QLabel("LLM Provider"), 0, 0)
        self.llm_provider = QComboBox()
        self.llm_provider.addItems(["ollama", "anthropic", "openai"])
        self.llm_provider.setCurrentText(CONFIG.get("llm_provider", "ollama"))
        llm_layout.addWidget(self.llm_provider, 0, 1)

        llm_layout.addWidget(QLabel("Ollama Model"), 1, 0)
        self.fields["llm_model"] = QLineEdit(CONFIG.get("llm_model", "llama3.1:8b"))
        llm_layout.addWidget(self.fields["llm_model"], 1, 1)

        llm_layout.addWidget(QLabel("Ollama URL"), 2, 0)
        self.fields["ollama_base_url"] = QLineEdit(CONFIG.get("ollama_base_url", "http://localhost:11434"))
        llm_layout.addWidget(self.fields["ollama_base_url"], 2, 1)

        llm_layout.addWidget(QLabel("Anthropic Model"), 3, 0)
        self.fields["anthropic_model"] = QLineEdit(CONFIG.get("anthropic_model", "claude-sonnet-4-20250514"))
        llm_layout.addWidget(self.fields["anthropic_model"], 3, 1)

        content_layout.addWidget(llm_group)

        # Trading Settings
        trading_group = QGroupBox("TRADING SETTINGS")
        trading_layout = QGridLayout(trading_group)

        trading_layout.addWidget(QLabel("Watchlist (comma-separated)"), 0, 0)
        self.watchlist_field = QLineEdit(",".join(CONFIG.get("watchlist", [])))
        trading_layout.addWidget(self.watchlist_field, 0, 1)

        trading_layout.addWidget(QLabel("Max Position Size (%)"), 1, 0)
        self.max_position = QDoubleSpinBox()
        self.max_position.setRange(0.1, 25.0)
        self.max_position.setValue(CONFIG.get("max_position_pct", 5.0))
        trading_layout.addWidget(self.max_position, 1, 1)

        trading_layout.addWidget(QLabel("Min Confidence to Execute (0-100)"), 2, 0)
        self.min_confidence = QSpinBox()
        self.min_confidence.setRange(0, 100)
        self.min_confidence.setValue(CONFIG.get("min_confidence", 75))
        trading_layout.addWidget(self.min_confidence, 2, 1)

        trading_layout.addWidget(QLabel("Max Daily Loss (%)"), 3, 0)
        self.max_loss = QDoubleSpinBox()
        self.max_loss.setRange(0.1, 20.0)
        self.max_loss.setValue(CONFIG.get("max_daily_loss_pct", 3.0))
        trading_layout.addWidget(self.max_loss, 3, 1)

        trading_layout.addWidget(QLabel("Poll Interval (seconds)"), 4, 0)
        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(10, 3600)
        self.poll_interval.setValue(CONFIG.get("poll_interval_seconds", 60))
        trading_layout.addWidget(self.poll_interval, 4, 1)

        # Autonomous Mode Settings
        auto_group = QGroupBox("AUTONOMOUS MODE SETTINGS")
        auto_layout = QGridLayout(auto_group)

        auto_layout.addWidget(QLabel("Stop-Loss (%)"), 0, 0)
        self.stop_loss = QDoubleSpinBox()
        self.stop_loss.setRange(0.1, 20.0)
        self.stop_loss.setValue(CONFIG.get("auto_stop_loss_pct", 2.0))
        self.stop_loss.setSuffix("%")
        auto_layout.addWidget(self.stop_loss, 0, 1)

        auto_layout.addWidget(QLabel("Take-Profit (%)"), 1, 0)
        self.take_profit = QDoubleSpinBox()
        self.take_profit.setRange(0.1, 50.0)
        self.take_profit.setValue(CONFIG.get("auto_take_profit_pct", 4.0))
        self.take_profit.setSuffix("%")
        auto_layout.addWidget(self.take_profit, 1, 1)

        auto_layout.addWidget(QLabel("Max Open Positions"), 2, 0)
        self.max_positions = QSpinBox()
        self.max_positions.setRange(1, 20)
        self.max_positions.setValue(CONFIG.get("max_open_positions", 5))
        auto_layout.addWidget(self.max_positions, 2, 1)

        auto_layout.addWidget(QLabel("Max Trades Per Day (safety cap)"), 3, 0)
        self.max_daily_trades = QSpinBox()
        self.max_daily_trades.setRange(1, 100)
        self.max_daily_trades.setValue(CONFIG.get("autonomous_max_trades_per_day", 10))
        auto_layout.addWidget(self.max_daily_trades, 3, 1)

        content_layout.addWidget(auto_group)

        content_layout.addWidget(trading_group)

        # Alpaca Request ID Log
        reqid_group = QGroupBox("ALPACA REQUEST IDs  (provide to Alpaca support if needed)")
        reqid_layout = QVBoxLayout(reqid_group)
        reqid_note = QLabel("Last 20 X-Request-ID values from Alpaca API responses. Copy these when contacting Alpaca support.")
        reqid_note.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        reqid_note.setWordWrap(True)
        reqid_layout.addWidget(reqid_note)
        self.reqid_table = QTableWidget(0, 3)
        self.reqid_table.setHorizontalHeaderLabels(["TIMESTAMP", "ENDPOINT", "X-REQUEST-ID"])
        self.reqid_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.reqid_table.setColumnWidth(0, 140)
        self.reqid_table.setColumnWidth(1, 180)
        self.reqid_table.setMaximumHeight(160)
        self.reqid_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.reqid_table.setSelectionBehavior(QTableWidget.SelectRows)
        reqid_layout.addWidget(self.reqid_table)
        refresh_reqid_btn = QPushButton("↻  REFRESH REQUEST IDs")
        refresh_reqid_btn.clicked.connect(self._refresh_request_ids)
        reqid_layout.addWidget(refresh_reqid_btn)
        content_layout.addWidget(reqid_group)

        scroll.setWidget(content)
        layout.addWidget(scroll)

        save_btn = QPushButton("💾  SAVE SETTINGS")
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
        self._refresh_request_ids()

    def _refresh_request_ids(self):
        ids = get_recent_request_ids(20)
        self.reqid_table.setRowCount(0)
        for entry in reversed(ids):
            row = self.reqid_table.rowCount()
            self.reqid_table.insertRow(row)
            ts = entry.get("timestamp", "")[:19].replace("T", " ")
            endpoint = entry.get("endpoint", "")
            req_id = entry.get("request_id", "")
            status = entry.get("status", "")
            self.reqid_table.setItem(row, 0, QTableWidgetItem(ts))
            ep_item = QTableWidgetItem(f"{endpoint} ({status})")
            color = ACCENT_GREEN if str(status).startswith("2") else ACCENT_RED
            ep_item.setForeground(QBrush(QColor(color)))
            self.reqid_table.setItem(row, 1, ep_item)
            self.reqid_table.setItem(row, 2, QTableWidgetItem(req_id))

    def _save(self):
        for key, field in self.fields.items():
            CONFIG[key] = field.text().strip()
        CONFIG["llm_provider"] = self.llm_provider.currentText()
        CONFIG["max_position_pct"] = self.max_position.value()
        CONFIG["min_confidence"] = self.min_confidence.value()
        CONFIG["max_daily_loss_pct"] = self.max_loss.value()
        CONFIG["poll_interval_seconds"] = self.poll_interval.value()
        watchlist_raw = self.watchlist_field.text()
        CONFIG["watchlist"] = [s.strip().upper() for s in watchlist_raw.split(",") if s.strip()]
        CONFIG["auto_stop_loss_pct"] = self.stop_loss.value()
        CONFIG["auto_take_profit_pct"] = self.take_profit.value()
        CONFIG["max_open_positions"] = self.max_positions.value()
        CONFIG["autonomous_max_trades_per_day"] = self.max_daily_trades.value()
        save_config(CONFIG)
        self.settings_saved.emit()
        QMessageBox.information(self, "TradeSage", "Settings saved successfully.")


# ─────────────────────────────────────────────
# MAIN APPLICATION WINDOW
# ─────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TradeSage  ◈  AI Trading Analytics")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        self.setStyleSheet(STYLESHEET)

        # Core components
        self.aggregator = DataAggregator()
        self.llm_engine = LLMEngine()
        self.trading_engine = TradingEngine()
        self.learning_system = LearningSystem(self.llm_engine)
        self._last_context = {}
        self._worker = None

        # Wire engine callbacks for autonomous events
        self.trading_engine.on_trade_executed = self._on_auto_trade
        self.trading_engine.on_position_closed = self._on_position_closed
        self.trading_engine.on_learning_needed = self._run_learning

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()

        # Auto-refresh timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._run_analysis)
        self._apply_timer_interval()

    def _apply_timer_interval(self):
        interval = CONFIG.get("poll_interval_seconds", 60) * 1000
        self.timer.setInterval(interval)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};")
        title_bar.setFixedHeight(50)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 0, 16, 0)

        logo = QLabel("◈ TRADESAGE")
        logo.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 16px; font-weight: bold; letter-spacing: 4px;")
        self.market_status_label = QLabel("AI-POWERED PAPER TRADING ANALYTICS  |  PAPER MODE  |  MARKET: --")
        self.market_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; letter-spacing: 2px;")

        self.status_indicator = QLabel("● OFFLINE")
        self.status_indicator.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px;")

        title_layout.addWidget(logo)
        title_layout.addWidget(self.market_status_label)
        title_layout.addStretch()
        title_layout.addWidget(self.status_indicator)
        main_layout.addWidget(title_bar)

        # Tabs
        self.tabs = QTabWidget()
        self.sentiment_tab = SentimentTab()
        self.signals_tab = SignalsTab()
        self.paper_tab = PaperTradingTab()
        self.performance_tab = PerformanceTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.sentiment_tab, "  NEWS SENTIMENT  ")
        self.tabs.addTab(self.signals_tab, "  TRADE SIGNALS  ")
        self.tabs.addTab(self.paper_tab, "  PAPER TRADING  ")
        self.tabs.addTab(self.performance_tab, "  PERFORMANCE  ")
        self.tabs.addTab(self.settings_tab, "  SETTINGS  ")

        self.signals_tab.execute_signal.connect(self._execute_signal)
        self.performance_tab.run_learning.connect(self._run_learning)
        self.settings_tab.settings_saved.connect(self._on_settings_saved)

        main_layout.addWidget(self.tabs)

    def _build_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER}; spacing: 4px;")

        self.analyze_btn = QAction("⟳  ANALYZE NOW", self)
        self.analyze_btn.triggered.connect(self._run_analysis)
        toolbar.addAction(self.analyze_btn)

        toolbar.addSeparator()

        self.auto_action = QAction("▶  START AUTO-REFRESH", self)
        self.auto_action.triggered.connect(self._toggle_auto)
        toolbar.addAction(self.auto_action)

        toolbar.addSeparator()

        toolbar.addSeparator()

        self.autonomous_btn = QPushButton("🤖  AUTONOMOUS: OFF")
        self.autonomous_btn.setCheckable(True)
        self.autonomous_btn.setChecked(CONFIG.get("autonomous_mode", False))
        self.autonomous_btn.setStyleSheet(
            f"color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; "
            f"background: transparent; padding: 4px 12px; font-size: 11px; letter-spacing: 1px;"
        )
        self.autonomous_btn.clicked.connect(self._toggle_autonomous)
        toolbar.addWidget(self.autonomous_btn)

        toolbar.addSeparator()

        self.halt_action = QAction("⬛  HALT TRADING", self)
        self.halt_action.triggered.connect(self._halt_trading)
        toolbar.addAction(self.halt_action)

        self.addToolBar(toolbar)
        self._update_autonomous_btn()

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Configure API keys in Settings, then click ANALYZE NOW.")

    def _toggle_auto(self):
        if self.timer.isActive():
            self.timer.stop()
            self.auto_action.setText("▶  START AUTO-REFRESH")
            self.status_bar.showMessage("Auto-refresh stopped.")
        else:
            self._apply_timer_interval()
            self.timer.start()
            self.auto_action.setText("⏸  STOP AUTO-REFRESH")
            self.status_bar.showMessage(f"Auto-refresh every {CONFIG.get('poll_interval_seconds',60)}s")
            self._run_analysis()

    def _run_analysis(self):
        if self._worker and self._worker.isRunning():
            return
        symbols = CONFIG.get("watchlist", ["AAPL", "MSFT", "NVDA"])
        self.status_bar.showMessage("⟳ Fetching market data and running LLM analysis...")
        self.status_indicator.setText("● ANALYZING")
        self.status_indicator.setStyleSheet(f"color: {ACCENT_YELLOW}; font-size: 11px;")
        self.analyze_btn.setEnabled(False)

        self._worker = AnalysisWorker(self.aggregator, self.llm_engine, symbols)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _on_analysis_done(self, result: dict):
        self._last_context = result.get("context", {})
        signals_result = result.get("signals", {})

        # Stop-loss / Take-profit check
        closed = self.trading_engine.check_stop_loss_take_profit(self._last_context)
        if closed:
            for t in closed:
                self.status_bar.showMessage(
                    f"CLOSED {t['symbol']}: {t.get('close_reason','')} | P&L: {t.get('pnl_pct',0):+.2f}%"
                )

        # Reconcile positions
        self.trading_engine.reconcile_open_trades(self._last_context)

        # Autonomous trade execution
        if self.trading_engine.autonomous:
            auto_results = self.trading_engine.run_autonomous_cycle(signals_result, self._last_context)
            executed = [r for r in auto_results if r.get("status") == "EXECUTED"]
            rejected = [r for r in auto_results if r.get("status") not in ("EXECUTED", "HOLD")]
            if executed:
                syms = ", ".join(r["symbol"] for r in executed)
                self.status_bar.showMessage(f"AUTO-EXECUTED: {syms}")
            elif rejected:
                reasons = " | ".join(
                    f"{r.get('symbol','?')}: {r.get('status','?')} — {r.get('reason','')}"
                    for r in rejected[:3]
                )
                self.status_bar.showMessage(f"AUTO BLOCKED: {reasons}")

        # Update UI
        self.sentiment_tab.update(self._last_context, result.get("sentiment", {}))
        self.signals_tab.update(signals_result)
        self.paper_tab.update_account(self._last_context.get("account", {}))
        self.paper_tab.update_positions(self._last_context.get("positions", []))
        self.paper_tab.update_trades(self.trading_engine.trades)
        self.performance_tab.update_stats(self.trading_engine.get_stats())

        mode = "AUTONOMOUS" if self.trading_engine.autonomous else "LIVE"
        color = ACCENT_YELLOW if self.trading_engine.autonomous else ACCENT_GREEN
        self.status_indicator.setText(f"● {mode}")
        self.status_indicator.setStyleSheet(f"color: {color}; font-size: 11px;")
        mkt = market_status()
        mkt_color = ACCENT_GREEN if is_market_open() else ACCENT_RED
        self.market_status_label.setText(
            f"AI-POWERED PAPER TRADING ANALYTICS  |  PAPER MODE  |  MARKET: {mkt}"
        )
        self.market_status_label.setStyleSheet(
            f"color: {mkt_color}; font-size: 11px; letter-spacing: 2px;"
        )
        ts = datetime.now().strftime("%H:%M:%S")
        today_count = self.trading_engine.get_todays_trade_count()
        mkt = market_status()
        mkt_str = f"MARKET: {mkt}"
        self.status_bar.showMessage(
            f"Updated: {ts}  |  {mkt_str}  |  Signals: {len(signals_result.get('signals',[]))}  |  Trades today: {today_count}"
        )
        self.analyze_btn.setEnabled(True)

        if self.learning_system.should_run_learning():
            self._run_learning()

    def _on_analysis_error(self, error: str):
        self.status_indicator.setText("● ERROR")
        self.status_indicator.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px;")
        self.status_bar.showMessage(f"Error: {error}")
        self.analyze_btn.setEnabled(True)

    def _execute_signal(self, signal: dict):
        sym = signal.get("symbol", "?")
        action = signal.get("signal", "?")
        conf = signal.get("confidence", 0)
        reply = QMessageBox.question(
            self, "Confirm Trade",
            f"Execute {action} on {sym}?\nConfidence: {conf}%\n\nThis is a PAPER TRADE only.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            result = self.trading_engine.execute_signal(signal, self._last_context)
            status = result.get("status", "?")
            if status == "EXECUTED":
                QMessageBox.information(self, "Trade Executed",
                    f"{action} {result.get('shares')} shares of {sym} @ ${result.get('price',0):.2f}\nOrder ID: {result.get('order_id','?')}")
                self.paper_tab.update_trades(self.trading_engine.trades)
            else:
                QMessageBox.warning(self, "Trade Rejected",
                    f"Status: {status}\nReason: {result.get('reason','Unknown')}")

    def _toggle_autonomous(self):
        enabled = self.autonomous_btn.isChecked()
        if enabled:
            reply = QMessageBox.warning(
                self, "Enable Autonomous Trading",
                "AUTONOMOUS MODE will automatically execute paper trades "
                "based on LLM signals without asking for confirmation.\n\n"
                "Stop-loss and take-profit limits are enforced automatically.\n"
                "A daily trade cap prevents runaway execution.\n\n"
                "This uses PAPER TRADING only - no real money.\n\n"
                "Enable autonomous mode?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                self.autonomous_btn.setChecked(False)
                return
        self.trading_engine.set_autonomous(enabled)
        self._update_autonomous_btn()
        state = "ENABLED" if enabled else "DISABLED"
        self.status_bar.showMessage(f"Autonomous mode {state}.")

    def _update_autonomous_btn(self):
        on = self.trading_engine.autonomous
        if on:
            self.autonomous_btn.setText("AUTONOMOUS: ON")
            self.autonomous_btn.setStyleSheet(
                f"color: {DARK_BG}; border: 1px solid {ACCENT_YELLOW}; "
                f"background: {ACCENT_YELLOW}; padding: 4px 12px; "
                f"font-size: 11px; letter-spacing: 1px; font-weight: bold;"
            )
        else:
            self.autonomous_btn.setText("AUTONOMOUS: OFF")
            self.autonomous_btn.setStyleSheet(
                f"color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; "
                f"background: transparent; padding: 4px 12px; "
                f"font-size: 11px; letter-spacing: 1px;"
            )

    def _on_auto_trade(self, result: dict):
        self.paper_tab.update_trades(self.trading_engine.trades)
        self.performance_tab.update_stats(self.trading_engine.get_stats())

    def _on_position_closed(self, trade: dict):
        self.paper_tab.update_trades(self.trading_engine.trades)
        self.performance_tab.update_stats(self.trading_engine.get_stats())

    def _run_learning(self):
        self.performance_tab.set_learning_running()

        def on_done(result):
            self.performance_tab.update_learning(result)
            self.performance_tab.set_learning_idle()

        self.learning_system.run_learning_cycle(callback=on_done)

    def _halt_trading(self):
        reply = QMessageBox.warning(
            self, "HALT TRADING",
            "This will cancel all open orders and halt the trading engine.\nProceed?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.trading_engine.halt()
            self.timer.stop()
            self.auto_action.setText("▶  START AUTO-REFRESH")
            self.autonomous_btn.setChecked(False)
            self._update_autonomous_btn()
            self.status_indicator.setText("● HALTED")
            self.status_indicator.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px;")
            self.status_bar.showMessage("HALTED. Autonomous mode off. All orders cancelled.")

    def _on_settings_saved(self):
        self._apply_timer_interval()
        self.llm_engine.reload_provider()
        self.status_bar.showMessage("Settings saved. Reloaded LLM provider.")

    def closeEvent(self, event):
        if self.timer.isActive():
            self.timer.stop()
        event.accept()


# ─────────────────────────────────────────────
# APP ENTRY POINT
# ─────────────────────────────────────────────

class TradeSageApp:
    def run(self):
        if not PYQT_AVAILABLE:
            print("ERROR: PyQt5 is not installed.")
            print("Install with: pip install PyQt5")
            sys.exit(1)

        app = QApplication(sys.argv)
        app.setApplicationName("TradeSage")
        app.setStyle("Fusion")

        window = MainWindow()
        window.show()

        sys.exit(app.exec_())
