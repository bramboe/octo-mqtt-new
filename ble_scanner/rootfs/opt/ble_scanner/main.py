#!/usr/bin/env python3
"""
BLE Scanner Addon for Home Assistant - Minimal Version
"""

import json
import logging
import os
import time
from datetime import datetime

from flask import Flask, jsonify

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.51"

# Create Flask app (no CORS for now to test)
app = Flask(__name__)

# Simple health check route (no before_request needed for now)
@app.route('/api/health')
def api_health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "version": ADDON_VERSION,
        "message": "BLE Scanner is running"
    })

@app.route('/')
def index():
    """Simple index page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>BLE Scanner</title>
    </head>
    <body>
        <h1>BLE Scanner v""" + ADDON_VERSION + """</h1>
        <p>Status: Running</p>
        <p>This is a minimal version to test startup stability.</p>
    </body>
    </html>
    """

@app.route('/api/status')
def api_status():
    """Get addon status"""
    return jsonify({
        "version": ADDON_VERSION,
        "status": "running",
        "timestamp": datetime.now().isoformat()
    })

# Error handler
@app.errorhandler(Exception)
def handle_exception(e):
    """Handle exceptions"""
    logger.error(f"Exception: {e}")
    return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info(f"BLE Scanner Add-on v{ADDON_VERSION} starting...")
    app.run(host='0.0.0.0', port=8099, debug=False) 