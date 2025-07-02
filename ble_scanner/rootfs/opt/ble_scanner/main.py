#!/usr/bin/env python3
"""
BLE Scanner Addon for Home Assistant
Scans for BLE devices and provides a web UI for management
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
import websockets
from flask import Flask, jsonify, render_template, request, render_template_string
from flask_cors import CORS
import paho.mqtt.client as mqtt
import threading
import requests
from aioesphomeapi import APIClient, APIConnectionError
from asyncio_mqtt import Client as MqttClient
import asyncio_mqtt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.19"

class BLEScanner:
    def __init__(self):
        logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} initializing...")
        self.app = Flask(__name__)
        CORS(self.app)
        self.devices = {}
        self.esp32_proxies = []
        self.scan_interval = 30
        self.running = True
        self.scan_thread = None
        # MQTT config
        self.mqtt_host = None
        self.mqtt_port = 1883
        self.mqtt_user = None
        self.mqtt_password = None
        self.mqtt_topic = "ble_scanner/data"
        self.mqtt_discovery_enabled = False
        self.mqtt_client = None
        self.mqtt_connected = False
        # Proxy connection tracking
        self.proxy_connections = {}
        
        # Load configuration
        self.load_config()
        
        # Setup MQTT
        self.setup_mqtt()
        
        # Setup routes
        self.setup_routes()
        
        # Start ESP32 proxy connections
        self.start_esp32_proxies()
        
        # Start scan loop
        self.scan_thread = threading.Thread(target=self.scan_loop, daemon=True)
        self.scan_thread.start()
        
    def load_config(self):
        """Load configuration from Home Assistant addon options"""
        logger.info("[CONFIG] Loading configuration from /data/options.json...")
        try:
            config_path = "/data/options.json"
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                self.esp32_proxies = config.get('esp32_proxies', [])
                self.scan_interval = config.get('scan_interval', 30)
                log_level = config.get('log_level', 'info')
                # MQTT
                self.mqtt_host = config.get('mqtt_host', None)
                mqtt_port_config = config.get('mqtt_port', '1883')
                # Handle auto_detect for port
                if mqtt_port_config == '<auto_detect>' or mqtt_port_config == '<auto_detect>':
                    self.mqtt_port = 1883  # Default MQTT port
                else:
                    try:
                        self.mqtt_port = int(mqtt_port_config)
                    except (ValueError, TypeError):
                        logger.warning(f"[CONFIG] Invalid MQTT port '{mqtt_port_config}', using default 1883")
                        self.mqtt_port = 1883
                self.mqtt_user = config.get('mqtt_user', None)
                self.mqtt_password = config.get('mqtt_password', None)
                self.mqtt_topic = config.get('mqtt_topic', 'ble_scanner/data')
                self.mqtt_discovery_enabled = config.get('mqtt_discovery_enabled', False)
                # Set log level
                if log_level == 'debug':
                    logging.getLogger().setLevel(logging.DEBUG)
                logger.info(f"[CONFIG] Loaded: {len(self.esp32_proxies)} ESP32 proxies, MQTT host: {self.mqtt_host}, MQTT port: {self.mqtt_port}, MQTT discovery: {self.mqtt_discovery_enabled}")
            else:
                logger.warning("[CONFIG] No configuration file found, using defaults")
        except Exception as e:
            logger.error(f"[CONFIG] Error loading configuration: {e}")
    
    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            """Main web interface"""
            return render_template_string(HTML_TEMPLATE)
        
        @self.app.route('/api/status')
        def api_status():
            """Get add-on status"""
            return jsonify(self.get_status())
        
        @self.app.route('/api/devices')
        def api_devices():
            """Get discovered devices"""
            return jsonify(self.get_devices())
        
        @self.app.route('/api/scan/start', methods=['POST'])
        def api_start_scan():
            """Start BLE scanning"""
            return jsonify(self.start_scan())
        
        @self.app.route('/api/scan/stop', methods=['POST'])
        def api_stop_scan():
            """Stop BLE scanning"""
            return jsonify(self.stop_scan())
        
        @self.app.route('/api/devices/clear', methods=['POST'])
        def api_clear_devices():
            """Clear all devices"""
            return jsonify(self.clear_devices())
        
        @self.app.route('/api/diagnostic')
        def api_diagnostic():
            """Diagnostic endpoint"""
            return jsonify({
                "version": ADDON_VERSION,
                "config": {
                    "mqtt_host": self.mqtt_host,
                    "mqtt_port": self.mqtt_port,
                    "mqtt_topic": self.mqtt_topic,
                    "mqtt_discovery_enabled": self.mqtt_discovery_enabled,
                    "esp32_proxies": self.esp32_proxies
                },
                "status": self.get_status(),
                "proxy_connections": self.proxy_connections
            })
        
        @self.app.route('/api/devices/<mac_address>', methods=['POST'])
        def add_device(mac_address):
            logger.info("[API] /api/devices/<mac_address> called")
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
                
            device = {
                'mac_address': mac_address.upper(),
                'name': data.get('name', 'Unknown Device'),
                'rssi': data.get('rssi', 0),
                'last_seen': datetime.now().isoformat(),
                'manufacturer': data.get('manufacturer', 'Unknown'),
                'services': data.get('services', []),
                'added_manually': True
            }
            
            self.devices[mac_address.upper()] = device
            self.save_devices()
            
            return jsonify(device)
        
        @self.app.route('/api/devices/<mac_address>', methods=['DELETE'])
        def remove_device(mac_address):
            logger.info("[API] /api/devices/<mac_address> called")
            if mac_address.upper() in self.devices:
                del self.devices[mac_address.upper()]
                self.save_devices()
                return jsonify({'message': 'Device removed'})
            return jsonify({'error': 'Device not found'}), 404
        
        @self.app.route('/api/test_proxy/<int:proxy_index>', methods=['GET'])
        def test_proxy(proxy_index):
            """Test ESP32 proxy connection"""
            if proxy_index >= len(self.esp32_proxies):
                return jsonify({'error': 'Invalid proxy index'}), 400
            
            proxy = self.esp32_proxies[proxy_index]
            logger.info(f"[API] Testing proxy {proxy_index}: {proxy['host']}:{proxy.get('port', 6053)}")
            
            # Run test in background thread
            def run_test():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(self.test_websocket_connection(proxy))
                    logger.info(f"[API] Proxy test result: {result}")
                except Exception as e:
                    logger.error(f"[API] Proxy test error: {e}")
                finally:
                    loop.close()
            
            threading.Thread(target=run_test, daemon=True).start()
            return jsonify({'message': 'Proxy test started', 'proxy': proxy})
        
        @self.app.errorhandler(Exception)
        def handle_exception(e):
            logger.error(f"[API] Unhandled exception: {e}")
            return jsonify({'error': str(e)}), 500

    def save_devices(self):
        """Save devices to persistent storage"""
        try:
            with open('/data/devices.json', 'w') as f:
                json.dump(self.devices, f)
        except Exception as e:
            logger.error(f"Error saving devices: {e}")

    def load_devices(self):
        """Load devices from persistent storage"""
        try:
            if os.path.exists('/data/devices.json'):
                with open('/data/devices.json', 'r') as f:
                    self.devices = json.load(f)
        except Exception as e:
            logger.error(f"Error loading devices: {e}")

    def setup_mqtt(self):
        """Setup MQTT client using smartbed-mqtt approach"""
        # Handle auto-detection for MQTT host
        if self.mqtt_host == '<auto_detect>' or not self.mqtt_host:
            logger.info("[MQTT] Auto-detecting MQTT broker...")
            self.mqtt_host = self.auto_detect_mqtt_host()
        
        if not self.mqtt_host:
            logger.info("[MQTT] Could not auto-detect MQTT broker, MQTT will be disabled.")
            self.mqtt_client = None
            return
        
        # Handle auto-detection for MQTT credentials
        if self.mqtt_user == '<auto_detect>' or not self.mqtt_user:
            logger.info("[MQTT] Auto-detecting MQTT credentials...")
            self.mqtt_user, self.mqtt_password = self.auto_detect_mqtt_credentials()
        
        # Only create MQTT client if we have a host
        if not self.mqtt_host:
            logger.info("[MQTT] No MQTT host available, MQTT will be disabled.")
            self.mqtt_client = None
            return
        
        # Check if we have credentials
        if self.mqtt_user is None and self.mqtt_password is None:
            logger.info("[MQTT] No valid credentials found, MQTT will be disabled.")
            self.mqtt_client = None
            return
        
        # Create MQTT client using asyncio-mqtt (smartbed-mqtt approach)
        try:
            mqtt_config = {
                'hostname': self.mqtt_host,
                'port': self.mqtt_port,
                'username': self.mqtt_user,
                'password': self.mqtt_password,
                'client_id': f"ble_scanner_{int(time.time())}"
            }
            
            logger.info(f"[MQTT] Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}...")
            self.mqtt_client = MqttClient(**mqtt_config)
            
            # Start MQTT connection in background
            threading.Thread(target=self._run_mqtt_connect_loop, daemon=True).start()
            
        except Exception as e:
            logger.error(f"[MQTT] Error setting up MQTT client: {e}")
            self.mqtt_client = None

    def _run_mqtt_connect_loop(self):
        """Run MQTT connection loop in background thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.mqtt_connect_loop())
        except Exception as e:
            logger.error(f"[MQTT] Error in MQTT connection loop: {e}")
        finally:
            loop.close()

    async def mqtt_connect_loop(self):
        """MQTT connection loop using smartbed-mqtt approach"""
        while self.running:
            try:
                async with self.mqtt_client as client:
                    self.mqtt_connected = True
                    logger.info("[MQTT] Connected to MQTT broker")
                    
                    # Keep connection alive
                    while self.running:
                        await asyncio.sleep(10)
                        
            except Exception as e:
                self.mqtt_connected = False
                logger.error(f"[MQTT] Connection error: {e}")
                await asyncio.sleep(10)  # Wait before retrying

    def publish_mqtt(self, topic, message):
        """Publish message to MQTT using smartbed-mqtt approach"""
        if not self.mqtt_client or not self.mqtt_connected:
            return
        
        try:
            if isinstance(message, dict):
                message = json.dumps(message)
            
            # Run async publish in background
            asyncio.create_task(self._async_publish_mqtt(topic, message))
            
        except Exception as e:
            logger.error(f"[MQTT] Error publishing to {topic}: {e}")

    async def _async_publish_mqtt(self, topic, message):
        """Async MQTT publish"""
        try:
            await self.mqtt_client.publish(topic, message, qos=1)
            logger.debug(f"[MQTT] Published to {topic}: {message}")
        except Exception as e:
            logger.error(f"[MQTT] Error in async publish to {topic}: {e}")

    def auto_detect_mqtt_host(self):
        """Auto-detect MQTT broker host"""
        # Try to detect Home Assistant MQTT add-on
        try:
            response = requests.get("http://supervisor/addons", timeout=5)
            if response.status_code == 200:
                addons = response.json()
                for addon in addons.get('data', {}).get('addons', []):
                    if addon.get('slug') == 'core-mosquitto':
                        return 'core-mosquitto'
        except Exception as e:
            logger.debug(f"[MQTT] Auto-detection failed: {e}")
        
        # Fallback to common MQTT hosts
        common_hosts = ['core-mosquitto', 'mosquitto', 'localhost', '192.168.1.1']
        for host in common_hosts:
            try:
                # Try to connect to test if host is reachable
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, 1883))
                sock.close()
                if result == 0:
                    logger.info(f"[MQTT] Auto-detected MQTT host: {host}")
                    return host
            except Exception:
                continue
        
        return None

    def auto_detect_mqtt_credentials(self):
        """Auto-detect MQTT credentials"""
        # Try to get credentials from Home Assistant configuration
        try:
            response = requests.get("http://supervisor/addons/core-mosquitto/config", timeout=5)
            if response.status_code == 200:
                config = response.json()
                return config.get('username'), config.get('password')
        except Exception as e:
            logger.debug(f"[MQTT] Credential auto-detection failed: {e}")
        
        # Try to get from Home Assistant core config
        try:
            response = requests.get("http://supervisor/core/api/config", timeout=5)
            if response.status_code == 200:
                config = response.json()
                mqtt_config = config.get('mqtt', {})
                return mqtt_config.get('username'), mqtt_config.get('password')
        except Exception as e:
            logger.debug(f"[MQTT] Core config auto-detection failed: {e}")
        
        # Try common default credentials
        common_credentials = [
            (None, None),  # No auth
            ('homeassistant', 'homeassistant'),
            ('admin', 'admin'),
            ('mqtt', 'mqtt'),
        ]
        
        for username, password in common_credentials:
            try:
                # Test connection with these credentials
                test_client = MqttClient(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    username=username,
                    password=password,
                    client_id=f"test_{int(time.time())}"
                )
                
                # Try to connect
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.test_mqtt_credentials(test_client))
                    logger.info(f"[MQTT] Auto-detected working credentials: {username}")
                    return username, password
                finally:
                    loop.close()
                
            except Exception as e:
                logger.debug(f"[MQTT] Credential test failed for {username}: {e}")
                continue
        
        return None, None

    async def test_mqtt_credentials(self, client):
        """Test MQTT credentials"""
        try:
            async with client:
                await asyncio.sleep(1)  # Brief connection test
        except Exception:
            raise

    def start_esp32_proxies(self):
        """Start ESP32 proxy connection tasks"""
        for proxy in self.esp32_proxies:
            threading.Thread(target=self._run_esp32_proxy, args=(proxy,), daemon=True).start()

    def _run_esp32_proxy(self, proxy):
        """Run ESP32 proxy connection in background thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.connect_esp32_proxy(proxy))
        except Exception as e:
            logger.error(f"[BLEPROXY] Error in ESP32 proxy thread: {e}")
        finally:
            loop.close()

    async def connect_esp32_proxy(self, proxy):
        """Robust ESPHome BLE proxy connection loop, smartbed-mqtt style."""
        host = proxy['host']
        port = proxy.get('port', 6053)
        password = proxy.get('password', '')
        proxy_key = f"{host}:{port}"
        
        while self.running:
            client = APIClient(host, port, password=password)
            try:
                await client.connect(login=True)
                self.proxy_connections[proxy_key] = True
                logger.info(f"[BLEPROXY] Connected to ESPHome BLE proxy at {host}:{port}")

                async def handle_ble_advertisement(adv):
                    # adv is a dict with keys like 'address', 'name', 'rssi', etc.
                    adv_dict = {
                        'address': adv.get('address'),
                        'name': adv.get('name', 'Unknown Device'),
                        'rssi': adv.get('rssi'),
                        'manufacturer_data': adv.get('manufacturer_data', {}),
                        'service_uuids': adv.get('service_uuids', []),
                    }
                    await self.process_ble_advertisement({'bluetooth_le_advertisement': adv_dict}, proxy_key)

                await client.subscribe_bluetooth_le_advertisements(handle_ble_advertisement)
                logger.info(f"[BLEPROXY] Subscribed to BLE advertisements on {host}:{port}")
                
                # Keep the connection open while running
                while self.running:
                    await asyncio.sleep(10)
                    
                await client.disconnect()
                self.proxy_connections[proxy_key] = False
                logger.info(f"[BLEPROXY] Disconnected from ESPHome BLE proxy at {host}:{port}")
                
            except APIConnectionError as e:
                self.proxy_connections[proxy_key] = False
                logger.error(f"[BLEPROXY] ESPHome API connection error: {e}")
                await asyncio.sleep(10)  # Wait before retrying
            except Exception as e:
                self.proxy_connections[proxy_key] = False
                logger.error(f"[BLEPROXY] Error connecting to ESPHome BLE proxy at {host}:{port}: {e}")
                await asyncio.sleep(10)  # Wait before retrying

    async def process_ble_advertisement(self, data, proxy_key):
        """Process BLE advertisement data"""
        try:
            adv = data.get('bluetooth_le_advertisement', {})
            address = adv.get('address')
            name = adv.get('name', 'Unknown Device')
            rssi = adv.get('rssi', 0)
            
            if not address:
                return
            
            # Update device data
            device_key = address.lower()
            if device_key not in self.devices:
                self.devices[device_key] = {
                    'address': address,
                    'name': name,
                    'first_seen': datetime.now().isoformat(),
                    'last_seen': datetime.now().isoformat(),
                    'rssi': rssi,
                    'proxy': proxy_key,
                    'manufacturer_data': adv.get('manufacturer_data', {}),
                    'service_uuids': adv.get('service_uuids', []),
                    'seen_count': 1
                }
            else:
                self.devices[device_key].update({
                    'last_seen': datetime.now().isoformat(),
                    'rssi': rssi,
                    'proxy': proxy_key,
                    'manufacturer_data': adv.get('manufacturer_data', {}),
                    'service_uuids': adv.get('service_uuids', []),
                    'seen_count': self.devices[device_key].get('seen_count', 0) + 1
                })
            
            # Publish to MQTT if enabled
            if self.mqtt_connected and self.mqtt_discovery_enabled:
                self.publish_mqtt(f"{self.mqtt_topic}/{device_key}", self.devices[device_key])
            
            logger.debug(f"[BLE] Processed advertisement from {name} ({address}) via {proxy_key}")
            
        except Exception as e:
            logger.error(f"[BLE] Error processing advertisement: {e}")

    def scan_loop(self):
        """Main scan loop - runs in background thread"""
        while self.running:
            try:
                if self.running:
                    # Scan logic is handled by ESP32 proxies
                    pass
                time.sleep(1)
            except Exception as e:
                logger.error(f"[SCAN] Error in scan loop: {e}")
                time.sleep(5)

    def get_status(self):
        """Get current status"""
        return {
            'version': ADDON_VERSION,
            'running': self.running,
            'device_count': len(self.devices),
            'proxy_count': len(self.esp32_proxies),
            'connected_proxies': sum(1 for status in self.proxy_connections.values() if status),
            'scan_interval': self.scan_interval,
            'mqtt_connected': self.mqtt_connected,
            'mqtt_discovery_enabled': self.mqtt_discovery_enabled,
            'proxy_connections': self.proxy_connections
        }

    def get_devices(self):
        """Get all discovered devices"""
        return self.devices

    def start_scan(self):
        """Start BLE scanning"""
        self.running = True
        logger.info("[SCAN] BLE scanning started")
        return {"status": "started"}

    def stop_scan(self):
        """Stop BLE scanning"""
        self.running = False
        logger.info("[SCAN] BLE scanning stopped")
        return {"status": "stopped"}

    def clear_devices(self):
        """Clear all discovered devices"""
        self.devices.clear()
        logger.info("[SCAN] All devices cleared")
        return {"status": "cleared"}

    async def test_websocket_connection(self, proxy):
        """Test WebSocket connection to ESP32 proxy"""
        host = proxy['host']
        port = proxy.get('port', 6053)
        password = proxy.get('password', '')
        
        logger.info(f"[TEST] Testing WebSocket connection to {host}:{port}")
        
        try:
            # Try ESPHome native API first
            client = APIClient(host, port, password=password)
            await client.connect(login=True)
            await client.disconnect()
            logger.info(f"[TEST] ESPHome API connection successful to {host}:{port}")
            return {"status": "success", "method": "esphome_api", "host": host, "port": port}
            
        except APIConnectionError as e:
            logger.warning(f"[TEST] ESPHome API failed: {e}")
            # Try HTTP API fallback
            return await self.try_http_api(proxy)
            
        except Exception as e:
            logger.error(f"[TEST] Connection test failed: {e}")
            return {"status": "error", "error": str(e), "host": host, "port": port}

    async def try_http_api(self, proxy):
        """Try HTTP API as fallback"""
        host = proxy['host']
        port = proxy.get('port', 6053)
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://{host}:{port}/"
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        logger.info(f"[TEST] HTTP API connection successful to {host}:{port}")
                        return {"status": "success", "method": "http_api", "host": host, "port": port}
                    else:
                        logger.warning(f"[TEST] HTTP API returned status {response.status}")
                        return {"status": "error", "error": f"HTTP status {response.status}", "host": host, "port": port}
        except Exception as e:
            logger.error(f"[TEST] HTTP API fallback failed: {e}")
            return {"status": "error", "error": str(e), "host": host, "port": port}

    def run(self):
        """Start the Flask application"""
        logger.info("[STARTUP] Starting Flask development server...")
        self.app.run(host='0.0.0.0', port=8099, debug=False)

# HTML template for web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BLE Scanner</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { text-align: center; margin-bottom: 30px; }
        .status { background: #e8f5e8; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .controls { margin-bottom: 20px; }
        .btn { background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin-right: 10px; }
        .btn:hover { background: #0056b3; }
        .btn.danger { background: #dc3545; }
        .btn.danger:hover { background: #c82333; }
        .btn.success { background: #28a745; }
        .btn.success:hover { background: #218838; }
        .devices { margin-top: 20px; }
        .device { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 5px; padding: 15px; margin-bottom: 10px; }
        .device h3 { margin: 0 0 10px 0; color: #495057; }
        .device-info { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
        .info-item { background: white; padding: 8px; border-radius: 3px; border: 1px solid #e9ecef; }
        .info-label { font-weight: bold; color: #6c757d; font-size: 0.9em; }
        .info-value { color: #495057; }
        .scanning { color: #28a745; font-weight: bold; }
        .stopped { color: #dc3545; font-weight: bold; }
        .refresh-btn { float: right; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>BLE Scanner v{{ version }}</h1>
            <p>Discover and monitor BLE devices via ESP32 proxies</p>
        </div>
        
        <div class="status" id="status">
            <h3>Status</h3>
            <div id="status-content">Loading...</div>
        </div>
        
        <div class="controls">
            <button class="btn success" onclick="startScan()">Start Scan</button>
            <button class="btn danger" onclick="stopScan()">Stop Scan</button>
            <button class="btn" onclick="clearDevices()">Clear Devices</button>
            <button class="btn" onclick="refreshData()" class="refresh-btn">Refresh</button>
        </div>
        
        <div class="devices" id="devices">
            <h3>Discovered Devices (<span id="device-count">0</span>)</h3>
            <div id="devices-content">No devices discovered yet.</div>
        </div>
    </div>

    <script>
        let refreshInterval;
        
        function updateStatus(data) {
            const statusContent = document.getElementById('status-content');
            const scanStatus = data.running ? '<span class="scanning">SCANNING</span>' : '<span class="stopped">STOPPED</span>';
            
            statusContent.innerHTML = `
                <div class="device-info">
                    <div class="info-item">
                        <div class="info-label">Scan Status</div>
                        <div class="info-value">${scanStatus}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Devices Found</div>
                        <div class="info-value">${data.device_count}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">ESP32 Proxies</div>
                        <div class="info-value">${data.proxy_count}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">MQTT Connected</div>
                        <div class="info-value">${data.mqtt_connected ? 'Yes' : 'No'}</div>
                    </div>
                </div>
            `;
        }
        
        function updateDevices(devices) {
            const devicesContent = document.getElementById('devices-content');
            const deviceCount = document.getElementById('device-count');
            
            deviceCount.textContent = Object.keys(devices).length;
            
            if (Object.keys(devices).length === 0) {
                devicesContent.innerHTML = '<p>No devices discovered yet.</p>';
                return;
            }
            
            let html = '';
            Object.values(devices).forEach(device => {
                const lastSeen = new Date(device.last_seen).toLocaleString();
                const rssiColor = device.rssi > -50 ? '#28a745' : device.rssi > -70 ? '#ffc107' : '#dc3545';
                
                html += `
                    <div class="device">
                        <h3>${device.name || 'Unknown Device'}</h3>
                        <div class="device-info">
                            <div class="info-item">
                                <div class="info-label">Address</div>
                                <div class="info-value">${device.address}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">RSSI</div>
                                <div class="info-value" style="color: ${rssiColor}">${device.rssi} dBm</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Last Seen</div>
                                <div class="info-value">${lastSeen}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Seen Count</div>
                                <div class="info-value">${device.seen_count}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Proxy</div>
                                <div class="info-value">${device.proxy}</div>
                            </div>
                        </div>
                    </div>
                `;
            });
            
            devicesContent.innerHTML = html;
        }
        
        async function refreshData() {
            try {
                const [statusResponse, devicesResponse] = await Promise.all([
                    fetch('/api/status'),
                    fetch('/api/devices')
                ]);
                
                const status = await statusResponse.json();
                const devices = await devicesResponse.json();
                
                updateStatus(status);
                updateDevices(devices);
            } catch (error) {
                console.error('Error refreshing data:', error);
            }
        }
        
        async function startScan() {
            try {
                await fetch('/api/scan/start', { method: 'POST' });
                refreshData();
            } catch (error) {
                console.error('Error starting scan:', error);
            }
        }
        
        async function stopScan() {
            try {
                await fetch('/api/scan/stop', { method: 'POST' });
                refreshData();
            } catch (error) {
                console.error('Error stopping scan:', error);
            }
        }
        
        async function clearDevices() {
            try {
                await fetch('/api/devices/clear', { method: 'POST' });
                refreshData();
            } catch (error) {
                console.error('Error clearing devices:', error);
            }
        }
        
        // Initial load
        refreshData();
        
        // Auto-refresh every 5 seconds
        refreshInterval = setInterval(refreshData, 5000);
        
        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            if (refreshInterval) {
                clearInterval(refreshInterval);
            }
        });
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} initializing...")
    
    # Create scanner instance
    scanner = BLEScanner()
    
    # Import and run with Gunicorn for production
    import gunicorn.app.base
    
    class StandaloneApplication(gunicorn.app.base.BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()
        
        def load_config(self):
            config = {key: value for key, value in self.options.items()
                     if key in self.cfg.settings and value is not None}
            for key, value in config.items():
                self.cfg.set(key.lower(), value)
        
        def load(self):
            return self.application
    
    # Gunicorn configuration for production
    options = {
        'bind': '0.0.0.0:8099',
        'workers': 1,  # Single worker for this add-on
        'worker_class': 'sync',
        'worker_connections': 1000,
        'max_requests': 1000,
        'max_requests_jitter': 50,
        'timeout': 30,
        'keepalive': 2,
        'preload_app': True,
        'access_logfile': '-',  # Log to stdout
        'error_logfile': '-',   # Log to stderr
        'loglevel': 'info',
        'access_log_format': '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
    }
    
    # Start Gunicorn server
    StandaloneApplication(scanner.app, options).run() 