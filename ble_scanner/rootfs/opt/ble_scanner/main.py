#!/usr/bin/env python3
"""
BLE Scanner Addon for Home Assistant - Ultra Minimal Version to Debug Segfault
"""

import logging
from flask import Flask

# Minimal logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("=== STARTING ULTRA MINIMAL VERSION ===")

ADDON_VERSION = "1.0.57"

# Create ultra minimal Flask app
app = Flask(__name__)

logger.info("=== FLASK APP CREATED ===")

@app.route('/')
def index():
    """Ultra minimal index page"""
    logger.info("Index page requested")
    return f"<h1>BLE Scanner v{ADDON_VERSION} - SEGFAULT DEBUG</h1><p>If you see this, Flask is working!</p>"

if __name__ == '__main__':
    logger.info("=== STARTING FLASK SERVER ===")
    try:
        app.run(host='0.0.0.0', port=8099, debug=False, threaded=False, processes=1)
    except Exception as e:
        logger.error(f"Flask startup error: {e}")
        raise 