#!/usr/bin/env python3
"""
BLE Scanner Addon for Home Assistant - MQTT + BLE Proxy Version
"""

import json
import logging
import os
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt
import requests
from flask import Flask, jsonify, render_template_string

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.58"

# Global variables
mqtt_client = None
config = {}
discovered_devices = {}

# Create Flask app
app = Flask(__name__)

logger.info("=== BLE SCANNER WITH MQTT STARTING ===")

def load_config():
    """Load Home Assistant add-on configuration"""
    global config
    try:
        with open('/data/options.json', 'r') as f:
            config = json.load(f)
        logger.info(f"Configuration loaded: {list(config.keys())}")
        return True
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return False

def setup_mqtt():
    """Setup MQTT connection"""
    global mqtt_client
    
    if not config.get('mqtt'):
        logger.error("No MQTT configuration found")
        return False
        
    mqtt_config = config['mqtt']
    
    # Auto-detect or use provided MQTT settings
    host = mqtt_config.get('host', 'core-mosquitto')
    port = mqtt_config.get('port', 1883)
    username = mqtt_config.get('username', '')
    password = mqtt_config.get('password', '')
    
    try:
        mqtt_client = mqtt.Client()
        
        if username and password:
            mqtt_client.username_pw_set(username, password)
            
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_disconnect = on_mqtt_disconnect
        
        mqtt_client.connect(host, port, 60)
        mqtt_client.loop_start()
        
        logger.info(f"MQTT client connecting to {host}:{port}")
        return True
        
    except Exception as e:
        logger.error(f"MQTT setup failed: {e}")
        return False

def on_mqtt_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    if rc == 0:
        logger.info("MQTT connected successfully")
    else:
        logger.error(f"MQTT connection failed with code {rc}")

def on_mqtt_disconnect(client, userdata, rc):
    """MQTT disconnection callback"""
    logger.warning("MQTT disconnected")

def scan_ble_proxy(proxy_host, proxy_port):
    """Scan BLE devices via ESP32 proxy"""
    try:
        url = f"http://{proxy_host}:{proxy_port}/api/ble/scan"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            devices = response.json()
            logger.info(f"Found {len(devices)} BLE devices via proxy {proxy_host}")
            return devices
        else:
            logger.warning(f"BLE proxy {proxy_host} returned status {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"Failed to scan BLE proxy {proxy_host}: {e}")
        return []

def create_mqtt_device(mac_address, device_info):
    """Create MQTT device discovery message"""
    if not mqtt_client:
        logger.error("MQTT client not available")
        return False
        
    try:
        # Create Home Assistant device discovery
        device_name = f"BLE_Device_{mac_address.replace(':', '_')}"
        
        discovery_topic = f"homeassistant/sensor/{device_name}/config"
        state_topic = f"ble_scanner/{device_name}/state"
        
        discovery_payload = {
            "name": f"BLE Device {mac_address}",
            "unique_id": f"ble_{mac_address.replace(':', '_')}",
            "state_topic": state_topic,
            "device": {
                "identifiers": [mac_address],
                "name": device_name,
                "manufacturer": "BLE Scanner",
                "model": "BLE Device"
            }
        }
        
        # Publish discovery message
        mqtt_client.publish(discovery_topic, json.dumps(discovery_payload), retain=True)
        
        # Publish device state
        state_payload = {
            "mac": mac_address,
            "last_seen": datetime.now().isoformat(),
            "rssi": device_info.get('rssi', 0),
            "name": device_info.get('name', 'Unknown')
        }
        
        mqtt_client.publish(state_topic, json.dumps(state_payload))
        
        logger.info(f"Created MQTT device for {mac_address}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to create MQTT device for {mac_address}: {e}")
        return False

def ble_scanner_thread():
    """Background thread for BLE scanning"""
    logger.info("BLE scanner thread started")
    
    while True:
        try:
            if not config.get('bleProxies'):
                time.sleep(30)
                continue
                
            for proxy in config['bleProxies']:
                host = proxy.get('host')
                port = proxy.get('port', 6053)
                
                if host:
                    devices = scan_ble_proxy(host, port)
                    
                    for device in devices:
                        mac = device.get('mac')
                        if mac and mac not in discovered_devices:
                            logger.info(f"New BLE device discovered: {mac}")
                            discovered_devices[mac] = device
                            create_mqtt_device(mac, device)
                            
            time.sleep(30)  # Scan every 30 seconds
            
        except Exception as e:
            logger.error(f"BLE scanner thread error: {e}")
            time.sleep(60)

@app.route('/')
def index():
    """Main dashboard"""
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>BLE Scanner v{{ version }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .status { padding: 10px; margin: 10px 0; border-radius: 5px; }
        .success { background-color: #d4edda; border: 1px solid #c3e6cb; }
        .warning { background-color: #fff3cd; border: 1px solid #ffeaa7; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <h1>🔍 BLE Scanner v{{ version }}</h1>
    
    <div class="status success">
        <strong>✅ Status:</strong> Running (MQTT + BLE Proxy Mode)
    </div>
    
    <div class="status warning">
        <strong>📡 MQTT:</strong> {{ 'Connected' if mqtt_connected else 'Disconnected' }}
    </div>
    
    <h2>Configuration</h2>
    <p><strong>BLE Proxies:</strong> {{ proxy_count }} configured</p>
    <p><strong>Discovered Devices:</strong> {{ device_count }}</p>
    
    <h2>Discovered BLE Devices</h2>
    <table>
        <tr>
            <th>MAC Address</th>
            <th>Name</th>
            <th>RSSI</th>
            <th>Last Seen</th>
        </tr>
        {% for mac, device in devices.items() %}
        <tr>
            <td>{{ mac }}</td>
            <td>{{ device.get('name', 'Unknown') }}</td>
            <td>{{ device.get('rssi', 'N/A') }}</td>
            <td>{{ device.get('last_seen', 'N/A') }}</td>
        </tr>
        {% endfor %}
    </table>
    
    <p><em>Last updated: {{ timestamp }}</em></p>
</body>
</html>
    """, 
    version=ADDON_VERSION,
    mqtt_connected=mqtt_client and mqtt_client.is_connected() if mqtt_client else False,
    proxy_count=len(config.get('bleProxies', [])),
    device_count=len(discovered_devices),
    devices=discovered_devices,
    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

@app.route('/api/status')
def api_status():
    """API status endpoint"""
    return jsonify({
        "version": ADDON_VERSION,
        "status": "running",
        "mqtt_connected": mqtt_client.is_connected() if mqtt_client else False,
        "proxy_count": len(config.get('bleProxies', [])),
        "device_count": len(discovered_devices),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/devices')
def api_devices():
    """API devices endpoint"""
    return jsonify(discovered_devices)

if __name__ == '__main__':
    logger.info("=== LOADING CONFIGURATION ===")
    if not load_config():
        logger.error("Failed to load configuration, exiting")
        exit(1)
    
    logger.info("=== SETTING UP MQTT ===")
    setup_mqtt()
    
    logger.info("=== STARTING BLE SCANNER THREAD ===")
    scanner_thread = threading.Thread(target=ble_scanner_thread, daemon=True)
    scanner_thread.start()
    
    logger.info("=== STARTING FLASK SERVER ===")
    try:
        app.run(host='0.0.0.0', port=8099, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"Flask startup error: {e}")
        raise 