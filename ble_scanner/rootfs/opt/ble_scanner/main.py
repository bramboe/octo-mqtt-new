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
from flask import Flask, jsonify, render_template_string, request

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.59"

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
    
    # Try multiple MQTT hosts for Home Assistant
    possible_hosts = [
        mqtt_config.get('host', '').replace('<auto_detect>', ''),
        'core-mosquitto',
        'mosquitto', 
        'homeassistant.local',
        'localhost',
        '172.30.32.2'  # HA supervisor
    ]
    
    # Filter out empty hosts
    hosts_to_try = [h for h in possible_hosts if h]
    
    port = mqtt_config.get('port', 1883)
    username = mqtt_config.get('username', '').replace('<auto_detect>', '')
    password = mqtt_config.get('password', '').replace('<auto_detect>', '')
    
    for host in hosts_to_try:
        try:
            logger.info(f"Trying MQTT connection to {host}:{port}")
            mqtt_client = mqtt.Client()
            
            if username and password:
                mqtt_client.username_pw_set(username, password)
                
            mqtt_client.on_connect = on_mqtt_connect
            mqtt_client.on_disconnect = on_mqtt_disconnect
            
            mqtt_client.connect(host, port, 10)  # Shorter timeout
            mqtt_client.loop_start()
            
            logger.info(f"MQTT client connected to {host}:{port}")
            return True
            
        except Exception as e:
            logger.warning(f"MQTT connection to {host}:{port} failed: {e}")
            
    logger.error("All MQTT connection attempts failed")
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

def test_ble_proxy(proxy_host, proxy_port):
    """Test BLE proxy connectivity"""
    try:
        # Try different common endpoints
        endpoints = [
            f"http://{proxy_host}:{proxy_port}/api/ble/scan",
            f"http://{proxy_host}:{proxy_port}/api/status",
            f"http://{proxy_host}:{proxy_port}/status",
            f"http://{proxy_host}:{proxy_port}/"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=5)
                if response.status_code == 200:
                    logger.info(f"BLE proxy {proxy_host}:{proxy_port} responding on {endpoint}")
                    return True, f"OK - {endpoint}"
            except:
                continue
                
        return False, "No response from any endpoint"
        
    except Exception as e:
        return False, str(e)

def scan_ble_proxy(proxy_host, proxy_port):
    """Scan BLE devices via ESP32 proxy"""
    try:
        # First try the expected endpoint
        url = f"http://{proxy_host}:{proxy_port}/api/ble/scan"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            devices = response.json()
            logger.info(f"Found {len(devices)} BLE devices via proxy {proxy_host}")
            return devices
        else:
            logger.warning(f"BLE proxy {proxy_host} returned status {response.status_code}")
            
            # Try alternative endpoints if main one fails
            alt_endpoints = [
                f"http://{proxy_host}:{proxy_port}/ble/scan",
                f"http://{proxy_host}:{proxy_port}/scan",
                f"http://{proxy_host}:{proxy_port}/devices"
            ]
            
            for alt_url in alt_endpoints:
                try:
                    response = requests.get(alt_url, timeout=5)
                    if response.status_code == 200:
                        devices = response.json()
                        logger.info(f"Found {len(devices)} BLE devices via proxy {proxy_host} (alt endpoint)")
                        return devices
                except:
                    continue
                    
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
                        if mac:
                            device['source'] = f"{host}:{port}"
                            device['last_seen'] = datetime.now().isoformat()
                            
                            if mac not in discovered_devices:
                                logger.info(f"New BLE device discovered: {mac} from {host}:{port}")
                                discovered_devices[mac] = device
                                create_mqtt_device(mac, device)
                            else:
                                # Update existing device info
                                discovered_devices[mac].update(device)
                            
            time.sleep(30)  # Scan every 30 seconds
            
        except Exception as e:
            logger.error(f"BLE scanner thread error: {e}")
            time.sleep(60)

@app.route('/')
def index():
    """Main dashboard"""
    # Test proxy connectivity
    proxy_status = []
    for proxy in config.get('bleProxies', []):
        host = proxy.get('host')
        port = proxy.get('port', 6053)
        if host:
            is_online, message = test_ble_proxy(host, port)
            proxy_status.append({
                'host': host,
                'port': port,
                'online': is_online,
                'message': message
            })
    
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>BLE Scanner v{{ version }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .status { padding: 15px; margin: 10px 0; border-radius: 8px; display: flex; align-items: center; }
        .success { background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
        .warning { background-color: #fff3cd; border: 1px solid #ffeaa7; color: #856404; }
        .error { background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
        .controls { margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-radius: 8px; }
        .btn { padding: 10px 20px; margin: 5px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }
        .btn-primary { background-color: #007bff; color: white; }
        .btn-success { background-color: #28a745; color: white; }
        .btn-warning { background-color: #ffc107; color: black; }
        .btn:hover { opacity: 0.8; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background-color: #f2f2f2; font-weight: bold; }
        .proxy-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin: 20px 0; }
        .proxy-card { padding: 15px; border-radius: 8px; border: 1px solid #ddd; }
        .proxy-online { background-color: #d4edda; border-color: #c3e6cb; }
        .proxy-offline { background-color: #f8d7da; border-color: #f5c6cb; }
        .icon { font-size: 1.2em; margin-right: 8px; }
    </style>
    <script>
        function scanNow() {
            fetch('/api/scan_now', {method: 'POST'})
                .then(response => response.json())
                .then(data => {
                    alert('Scan initiated: ' + data.message);
                    setTimeout(() => location.reload(), 2000);
                });
        }
        
        function testProxy(host, port) {
            fetch('/api/test_proxy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({host: host, port: port})
            })
            .then(response => response.json())
            .then(data => alert(host + ': ' + data.message));
        }
        
        function clearDevices() {
            if(confirm('Clear all discovered devices?')) {
                fetch('/api/clear_devices', {method: 'POST'})
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message);
                        location.reload();
                    });
            }
        }
        
        // Auto-refresh every 30 seconds
        setTimeout(() => location.reload(), 30000);
    </script>
</head>
<body>
    <div class="container">
        <h1>🔍 BLE Scanner v{{ version }}</h1>
        
        <div class="status {{ 'success' if mqtt_connected else 'error' }}">
            <span class="icon">{{ '📡' if mqtt_connected else '❌' }}</span>
            <strong>MQTT:</strong> {{ 'Connected' if mqtt_connected else 'Disconnected' }}
        </div>
        
        <div class="controls">
            <h3>🎛️ Controls</h3>
            <button class="btn btn-primary" onclick="scanNow()">🔄 Scan Now</button>
            <button class="btn btn-warning" onclick="clearDevices()">🗑️ Clear Devices</button>
            <button class="btn btn-success" onclick="location.reload()">♻️ Refresh</button>
        </div>
        
        <h2>🌐 BLE Proxy Status</h2>
        <div class="proxy-list">
            {% for proxy in proxy_status %}
            <div class="proxy-card {{ 'proxy-online' if proxy.online else 'proxy-offline' }}">
                <h4>{{ '✅' if proxy.online else '❌' }} {{ proxy.host }}:{{ proxy.port }}</h4>
                <p><strong>Status:</strong> {{ proxy.message }}</p>
                <button class="btn btn-primary" onclick="testProxy('{{ proxy.host }}', {{ proxy.port }})">🧪 Test</button>
            </div>
            {% endfor %}
        </div>
        
        <h2>📱 Discovered BLE Devices ({{ device_count }})</h2>
        {% if devices %}
        <table>
            <tr>
                <th>MAC Address</th>
                <th>Name</th>
                <th>RSSI</th>
                <th>Last Seen</th>
                <th>Source</th>
            </tr>
            {% for mac, device in devices.items() %}
            <tr>
                <td><code>{{ mac }}</code></td>
                <td>{{ device.get('name', 'Unknown') }}</td>
                <td>{{ device.get('rssi', 'N/A') }} dBm</td>
                <td>{{ device.get('last_seen', 'N/A') }}</td>
                <td>{{ device.get('source', 'Unknown') }}</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <div class="status warning">
            <span class="icon">⚠️</span>
            No BLE devices discovered yet. Click "Scan Now" or check proxy connectivity.
        </div>
        {% endif %}
        
        <p><em>Last updated: {{ timestamp }} | Auto-refresh in 30s</em></p>
    </div>
</body>
</html>
    """, 
    version=ADDON_VERSION,
    mqtt_connected=mqtt_client and mqtt_client.is_connected() if mqtt_client else False,
    proxy_count=len(config.get('bleProxies', [])),
    device_count=len(discovered_devices),
    devices=discovered_devices,
    proxy_status=proxy_status,
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

@app.route('/api/scan_now', methods=['POST'])
def api_scan_now():
    """Manual scan trigger"""
    try:
        devices_found = 0
        proxies_scanned = 0
        
        for proxy in config.get('bleProxies', []):
            host = proxy.get('host')
            port = proxy.get('port', 6053)
            
            if host:
                proxies_scanned += 1
                devices = scan_ble_proxy(host, port)
                
                for device in devices:
                    mac = device.get('mac')
                    if mac:
                        device['source'] = f"{host}:{port}"
                        device['last_seen'] = datetime.now().isoformat()
                        
                        if mac not in discovered_devices:
                            discovered_devices[mac] = device
                            create_mqtt_device(mac, device)
                            devices_found += 1
                        else:
                            # Update existing device
                            discovered_devices[mac].update(device)
        
        message = f"Scanned {proxies_scanned} proxies, found {devices_found} new devices"
        logger.info(f"Manual scan: {message}")
        
        return jsonify({
            "success": True,
            "message": message,
            "proxies_scanned": proxies_scanned,
            "devices_found": devices_found
        })
        
    except Exception as e:
        logger.error(f"Manual scan failed: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/test_proxy', methods=['POST'])
def api_test_proxy():
    """Test specific proxy connectivity"""
    try:
        data = request.get_json()
        host = data.get('host')
        port = data.get('port', 6053)
        
        if not host:
            return jsonify({"success": False, "message": "Host required"}), 400
            
        is_online, message = test_ble_proxy(host, port)
        
        return jsonify({
            "success": is_online,
            "message": message,
            "host": host,
            "port": port
        })
        
    except Exception as e:
        logger.error(f"Proxy test failed: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/clear_devices', methods=['POST'])
def api_clear_devices():
    """Clear all discovered devices"""
    try:
        global discovered_devices
        count = len(discovered_devices)
        discovered_devices.clear()
        
        message = f"Cleared {count} devices"
        logger.info(message)
        
        return jsonify({
            "success": True,
            "message": message,
            "cleared_count": count
        })
        
    except Exception as e:
        logger.error(f"Clear devices failed: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

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