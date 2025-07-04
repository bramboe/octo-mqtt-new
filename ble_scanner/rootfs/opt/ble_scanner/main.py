#!/usr/bin/env python3
"""
BLE Scanner Addon for Home Assistant - Minimal Version
"""

import json
import logging
import os
import time
from datetime import datetime

from flask import Flask, jsonify, request, abort

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.55"

# Create Flask app (no CORS for now to test)
app = Flask(__name__)

# CRITICAL: Ingress security - only allow connections from Home Assistant Supervisor
@app.before_request
def limit_remote_addr():
    """Restrict access to Home Assistant ingress only (172.30.32.2)"""
    client_ip = request.environ.get('REMOTE_ADDR')
    if client_ip != '172.30.32.2':
        logger.warning(f"[SECURITY] Blocked unauthorized access from {client_ip}")
        abort(403)  # Forbidden

# Log startup at module level - VERY OBVIOUS MESSAGE
logger.info("="*80)
logger.info("🔥🔥🔥 SCHEMA FIXED v1.0.55 - PRIVILEGED LIST FORMAT 🔥🔥🔥")
logger.info("="*80)
logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} Flask app initialized")
logger.info(f"[SECURITY] Ingress access restricted to 172.30.32.2 only")

# Simple health check route (no before_request needed for now)
@app.route('/api/health')
def api_health():
    """Health check endpoint"""
    logger.info(f"[API] Health check requested")
    return jsonify({
        "status": "healthy",
        "version": ADDON_VERSION,
        "message": "BLE Scanner is running"
    })

@app.route('/')
def index():
    """Simple index page"""
    logger.info(f"[API] Index page requested")
    return """
<!DOCTYPE html>
    <html>
<head>
        <title>BLE Scanner v""" + ADDON_VERSION + """</title>
</head>
<body>
        <h1>🔥 BLE Scanner v""" + ADDON_VERSION + """ - SCHEMA FIXED 🔥</h1>
        <h2 style="color: green;">✅ Status: Running (Schema Fixed!)</h2>
        <p><strong>Fixed: privileged field now uses proper list format []</strong></p>
        <p><strong>Minimal version - pure Flask only!</strong></p>
        <p style="color: blue;">If you see this page, the NEW code is working correctly!</p>
        <hr>
        <p>Build: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
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