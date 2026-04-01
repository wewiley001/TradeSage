"""
TradeSage - AI-Powered Trading Analytics Platform
Main entry point
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.app import TradeSageApp

if __name__ == "__main__":
    app = TradeSageApp()
    app.run()
