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
import threading
import requests
from aioesphomeapi import APIConnection, APIConnectionError
from asyncio_mqtt import Client as MqttClient
import asyncio_mqtt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.21"

# Create Flask app at module level for Gunicorn
app = Flask(__name__)
CORS(app)

# Global scanner instance
scanner = None

class BLEScanner:
    def __init__(self):
        logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} initializing...")
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
                await self.mqtt_client.connect()
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
        """Publish message to MQTT (thread-safe wrapper)"""
        if self.mqtt_client and self.mqtt_connected:
            threading.Thread(target=self._async_publish_mqtt, args=(topic, message), daemon=True).start()

    async def _async_publish_mqtt(self, topic, message):
        """Async MQTT publish"""
        try:
            await self.mqtt_client.connect()
            await self.mqtt_client.publish(topic, json.dumps(message))
            await self.mqtt_client.disconnect()
        except Exception as e:
            logger.error(f"[MQTT] Error publishing: {e}")

    def auto_detect_mqtt_host(self):
        """Auto-detect MQTT broker host using smartbed-mqtt approach"""
        logger.info("[MQTT] Auto-detecting MQTT broker...")
        
        # Try common MQTT broker hostnames
        possible_hosts = [
            'core-mosquitto',  # Home Assistant MQTT add-on
            'mosquitto',       # Alternative name
            'mqtt',           # Generic MQTT service
            'localhost',      # Local MQTT
            '127.0.0.1'       # Local MQTT IP
        ]
        
        for host in possible_hosts:
            try:
                logger.info(f"[MQTT] Trying to connect to {host}:{self.mqtt_port}...")
                # Try to connect to MQTT broker
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((host, self.mqtt_port))
                sock.close()
                
                if result == 0:
                    logger.info(f"[MQTT] Found MQTT broker at {host}:{self.mqtt_port}")
                    return host
                    
            except Exception as e:
                logger.debug(f"[MQTT] Failed to connect to {host}: {e}")
                continue
        
        logger.warning("[MQTT] Could not auto-detect MQTT broker")
        return None

    def auto_detect_mqtt_credentials(self):
        """Auto-detect MQTT credentials using smartbed-mqtt approach"""
        logger.info("[MQTT] Auto-detecting MQTT credentials...")
        
        # Try to read from Home Assistant secrets
        secrets_path = "/config/secrets.yaml"
        if os.path.exists(secrets_path):
            try:
                import yaml
                with open(secrets_path, 'r') as f:
                    secrets = yaml.safe_load(f)
                
                if secrets:
                    # Look for MQTT credentials in secrets
                    mqtt_user = secrets.get('mqtt_username') or secrets.get('mqtt_user')
                    mqtt_password = secrets.get('mqtt_password') or secrets.get('mqtt_pass')
                    
                    if mqtt_user and mqtt_password:
                        logger.info("[MQTT] Found MQTT credentials in secrets.yaml")
                        return mqtt_user, mqtt_password
                        
            except Exception as e:
                logger.debug(f"[MQTT] Error reading secrets.yaml: {e}")
        
        # Try to read from configuration.yaml
        config_path = "/config/configuration.yaml"
        if os.path.exists(config_path):
            try:
                import yaml
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                
                if config and 'mqtt' in config:
                    mqtt_config = config['mqtt']
                    mqtt_user = mqtt_config.get('username') or mqtt_config.get('user')
                    mqtt_password = mqtt_config.get('password') or mqtt_config.get('pass')
                    
                    if mqtt_user and mqtt_password:
                        logger.info("[MQTT] Found MQTT credentials in configuration.yaml")
                        return mqtt_user, mqtt_password
                        
            except Exception as e:
                logger.debug(f"[MQTT] Error reading configuration.yaml: {e}")
        
        # Try common default credentials
        default_credentials = [
            ('homeassistant', 'homeassistant'),
            ('admin', 'admin'),
            ('mqtt', 'mqtt'),
            ('user', 'password')
        ]
        
        for username, password in default_credentials:
            try:
                # Test credentials by trying to connect
                test_client = MqttClient(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    username=username,
                    password=password,
                    client_id=f"ble_scanner_test_{int(time.time())}"
                )
                
                # Try to connect
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(test_client.connect())
                    loop.run_until_complete(test_client.disconnect())
                    logger.info(f"[MQTT] Found working credentials: {username}")
                    return username, password
                except Exception:
                    pass
                finally:
                    loop.close()
                    
            except Exception as e:
                logger.debug(f"[MQTT] Failed to test credentials {username}: {e}")
                continue
        
        logger.warning("[MQTT] Could not auto-detect MQTT credentials")
        return None, None

    async def test_mqtt_credentials(self, client):
        """Test MQTT credentials"""
        try:
            await client.connect()
            await client.disconnect()
            return True
        except Exception:
            return False

    def start_esp32_proxies(self):
        """Start ESP32 proxy connections"""
        for proxy in self.esp32_proxies:
            threading.Thread(target=self._run_esp32_proxy, args=(proxy,), daemon=True).start()

    def _run_esp32_proxy(self, proxy):
        """Run ESP32 proxy connection in background thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.connect_esp32_proxy(proxy))
        except Exception as e:
            logger.error(f"[PROXY] Error in ESP32 proxy connection: {e}")
        finally:
            loop.close()

    async def connect_esp32_proxy(self, proxy):
        """Connect to ESP32 BLE proxy using ESPHome API"""
        proxy_key = f"{proxy['host']}:{proxy.get('port', 6053)}"
        
        while self.running:
            try:
                logger.info(f"[PROXY] Connecting to ESP32 proxy at {proxy_key}...")
                
                # Use ESPHome API connection
                connection = APIConnection(
                    proxy['host'],
                    proxy.get('port', 6053),
                    proxy.get('password', ''),
                    client_info="BLE Scanner Add-on"
                )
                
                await connection.connect()
                logger.info(f"[PROXY] Connected to ESP32 proxy at {proxy_key}")
                
                # Store connection
                self.proxy_connections[proxy_key] = connection
                
                # Subscribe to BLE advertisements
                async def handle_ble_advertisement(adv):
                    # adv is a dict with keys like 'address', 'name', 'rssi', etc.
                    await self.process_ble_advertisement(adv, proxy_key)
                
                # Subscribe to BLE advertisements
                await connection.subscribe_ble_advertisements(handle_ble_advertisement)
                
                # Keep connection alive
                while self.running:
                    try:
                        await asyncio.sleep(10)
                        # Ping to keep connection alive
                        await connection.ping()
                    except Exception as e:
                        logger.error(f"[PROXY] Connection error for {proxy_key}: {e}")
                        break
                        
            except Exception as e:
                logger.error(f"[PROXY] Failed to connect to ESP32 proxy at {proxy_key}: {e}")
                self.proxy_connections[proxy_key] = None
                
            # Wait before retrying
            if self.running:
                await asyncio.sleep(30)

    async def process_ble_advertisement(self, data, proxy_key):
        """Process BLE advertisement data"""
        try:
            # Extract device information
            mac_address = data.get('address', '').upper()
            if not mac_address:
                return
                
            device_info = {
                'mac_address': mac_address,
                'name': data.get('name', 'Unknown Device'),
                'rssi': data.get('rssi', 0),
                'last_seen': datetime.now().isoformat(),
                'manufacturer': data.get('manufacturer', 'Unknown'),
                'services': data.get('services', []),
                'proxy': proxy_key,
                'seen_count': 1
            }
            
            # Update or add device
            if mac_address in self.devices:
                existing = self.devices[mac_address]
                device_info['seen_count'] = existing.get('seen_count', 0) + 1
                # Keep the original name if it was manually added
                if existing.get('added_manually'):
                    device_info['name'] = existing['name']
            
            self.devices[mac_address] = device_info
            
            # Save devices periodically
            if len(self.devices) % 10 == 0:  # Save every 10 devices
                self.save_devices()
            
            # Publish to MQTT if enabled
            if self.mqtt_client and self.mqtt_connected:
                mqtt_message = {
                    'mac_address': mac_address,
                    'name': device_info['name'],
                    'rssi': device_info['rssi'],
                    'last_seen': device_info['last_seen'],
                    'proxy': proxy_key,
                    'seen_count': device_info['seen_count']
                }
                
                # Publish to main topic
                self.publish_mqtt(self.mqtt_topic, mqtt_message)
                
                # Publish to device-specific topic if discovery enabled
                if self.mqtt_discovery_enabled:
                    device_topic = f"{self.mqtt_topic}/devices/{mac_address.replace(':', '_')}"
                    self.publish_mqtt(device_topic, mqtt_message)
            
            logger.debug(f"[BLE] Discovered device: {mac_address} ({device_info['name']}) via {proxy_key}")
            
        except Exception as e:
            logger.error(f"[BLE] Error processing advertisement: {e}")

    def scan_loop(self):
        """Main scan loop - currently just keeps the thread alive"""
        logger.info("[SCAN] BLE scan loop started")
        while self.running:
            time.sleep(1)
        logger.info("[SCAN] BLE scan loop stopped")

    def get_status(self):
        """Get add-on status"""
        return {
            'version': ADDON_VERSION,
            'running': self.running,
            'mqtt_connected': self.mqtt_connected,
            'proxy_connections': len([c for c in self.proxy_connections.values() if c is not None]),
            'total_proxies': len(self.esp32_proxies),
            'devices_count': len(self.devices),
            'scan_interval': self.scan_interval
        }

    def get_devices(self):
        """Get discovered devices"""
        return self.devices

    def start_scan(self):
        """Start BLE scanning"""
        logger.info("[SCAN] BLE scanning started")
        return {'status': 'started'}

    def stop_scan(self):
        """Stop BLE scanning"""
        logger.info("[SCAN] BLE scanning stopped")
        return {'status': 'stopped'}

    def clear_devices(self):
        """Clear all devices"""
        self.devices = {}
        self.save_devices()
        logger.info("[SCAN] All devices cleared")
        return {'status': 'cleared'}

    async def test_websocket_connection(self, proxy):
        """Test ESP32 proxy connection"""
        proxy_key = f"{proxy['host']}:{proxy.get('port', 6053)}"
        
        try:
            logger.info(f"[TEST] Testing ESP32 proxy connection to {proxy_key}...")
            
            # Try ESPHome API connection
            connection = APIConnection(
                proxy['host'],
                proxy.get('port', 6053),
                proxy.get('password', ''),
                client_info="BLE Scanner Add-on Test"
            )
            
            await connection.connect()
            await connection.ping()
            await connection.disconnect()
            
            logger.info(f"[TEST] ESP32 proxy connection test successful for {proxy_key}")
            return {'status': 'success', 'method': 'esphome_api', 'proxy': proxy_key}
            
        except Exception as e:
            logger.error(f"[TEST] ESP32 proxy connection test failed for {proxy_key}: {e}")
            return {'status': 'failed', 'error': str(e), 'proxy': proxy_key}

    async def try_http_api(self, proxy):
        """Try HTTP API as fallback"""
        try:
            url = f"http://{proxy['host']}:{proxy.get('port', 6053)}/ping"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        return True
        except Exception:
            pass
        return False

    def run(self):
        """Run the scanner"""
        logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} starting...")
        
        # Load saved devices
        self.load_devices()
        
        # Keep running
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("[SHUTDOWN] Received shutdown signal")
            self.running = False

# HTML template for the web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BLE Scanner - Home Assistant Add-on</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 300;
        }
        
        .header p {
            font-size: 1.1em;
            opacity: 0.9;
        }
        
        .status-bar {
            background: #f8f9fa;
            padding: 20px 30px;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #dc3545;
        }
        
        .status-indicator.online {
            background: #28a745;
        }
        
        .controls {
            background: #f8f9fa;
            padding: 20px 30px;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
        }
        
        .btn-primary {
            background: #007bff;
            color: white;
        }
        
        .btn-primary:hover {
            background: #0056b3;
            transform: translateY(-2px);
        }
        
        .btn-success {
            background: #28a745;
            color: white;
        }
        
        .btn-success:hover {
            background: #1e7e34;
            transform: translateY(-2px);
        }
        
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        
        .btn-danger:hover {
            background: #c82333;
            transform: translateY(-2px);
        }
        
        .btn-warning {
            background: #ffc107;
            color: #212529;
        }
        
        .btn-warning:hover {
            background: #e0a800;
            transform: translateY(-2px);
        }
        
        .content {
            padding: 30px;
        }
        
        .devices-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .devices-count {
            font-size: 1.2em;
            color: #6c757d;
        }
        
        .devices-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }
        
        .device-card {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 12px;
            padding: 20px;
            transition: all 0.3s ease;
            position: relative;
        }
        
        .device-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        }
        
        .device-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
        }
        
        .device-name {
            font-size: 1.2em;
            font-weight: 600;
            color: #212529;
            margin-bottom: 5px;
        }
        
        .device-mac {
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            color: #6c757d;
        }
        
        .device-rssi {
            background: #e9ecef;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: 500;
        }
        
        .device-info {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 15px;
        }
        
        .info-item {
            display: flex;
            flex-direction: column;
        }
        
        .info-label {
            font-size: 0.8em;
            color: #6c757d;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 2px;
        }
        
        .info-value {
            font-size: 0.9em;
            color: #212529;
            font-weight: 500;
        }
        
        .device-actions {
            display: flex;
            gap: 10px;
        }
        
        .btn-sm {
            padding: 6px 12px;
            font-size: 12px;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #6c757d;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        
        @media (max-width: 768px) {
            .status-bar {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .controls {
                flex-direction: column;
            }
            
            .devices-grid {
                grid-template-columns: 1fr;
            }
            
            .device-info {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>BLE Scanner</h1>
            <p>Home Assistant Add-on for discovering and managing BLE devices</p>
        </div>
        
        <div class="status-bar">
            <div class="status-item">
                <div class="status-indicator" id="mqtt-status"></div>
                <span>MQTT: <span id="mqtt-text">Unknown</span></span>
            </div>
            <div class="status-item">
                <div class="status-indicator" id="proxy-status"></div>
                <span>Proxies: <span id="proxy-text">0/0</span></span>
            </div>
            <div class="status-item">
                <span>Devices: <span id="devices-count">0</span></span>
            </div>
            <div class="status-item">
                <span>Version: <span id="version">1.0.20</span></span>
            </div>
        </div>
        
        <div class="controls">
            <button class="btn btn-primary" onclick="startScan()">Start Scan</button>
            <button class="btn btn-success" onclick="stopScan()">Stop Scan</button>
            <button class="btn btn-warning" onclick="clearDevices()">Clear Devices</button>
            <a href="/api/diagnostic" class="btn btn-primary" target="_blank">Diagnostic</a>
        </div>
        
        <div class="content">
            <div class="devices-header">
                <h2>Discovered Devices</h2>
                <div class="devices-count" id="devices-count-header">0 devices</div>
            </div>
            
            <div id="devices-content">
                <div class="loading">Loading devices...</div>
            </div>
        </div>
    </div>
    
    <script>
        let refreshInterval;
        
        function updateStatus(status) {
            // Update MQTT status
            const mqttStatus = document.getElementById('mqtt-status');
            const mqttText = document.getElementById('mqtt-text');
            if (status.mqtt_connected) {
                mqttStatus.className = 'status-indicator online';
                mqttText.textContent = 'Connected';
            } else {
                mqttStatus.className = 'status-indicator';
                mqttText.textContent = 'Disconnected';
            }
            
            // Update proxy status
            const proxyStatus = document.getElementById('proxy-status');
            const proxyText = document.getElementById('proxy-text');
            const proxyCount = status.proxy_connections;
            const totalProxies = status.total_proxies;
            
            if (proxyCount > 0) {
                proxyStatus.className = 'status-indicator online';
            } else {
                proxyStatus.className = 'status-indicator';
            }
            proxyText.textContent = `${proxyCount}/${totalProxies}`;
            
            // Update devices count
            document.getElementById('devices-count').textContent = status.devices_count;
            document.getElementById('devices-count-header').textContent = `${status.devices_count} devices`;
            
            // Update version
            document.getElementById('version').textContent = status.version;
        }
        
        function updateDevices(devices) {
            const devicesContent = document.getElementById('devices-content');
            
            if (!devices || Object.keys(devices).length === 0) {
                devicesContent.innerHTML = '<div class="loading">No devices discovered yet. Start scanning to discover BLE devices.</div>';
                return;
            }
            
            const html = Object.values(devices).map(device => {
                const lastSeen = new Date(device.last_seen).toLocaleString();
                const rssiColor = device.rssi > -50 ? '#28a745' : device.rssi > -70 ? '#ffc107' : '#dc3545';
                
                return `
                    <div class="device-card">
                        <div class="device-header">
                            <div>
                                <div class="device-name">${device.name}</div>
                                <div class="device-mac">${device.mac_address}</div>
                            </div>
                            <div class="device-rssi" style="color: ${rssiColor}">${device.rssi} dBm</div>
                        </div>
                        <div class="device-info">
                            <div class="info-item">
                                <div class="info-label">Manufacturer</div>
                                <div class="info-value">${device.manufacturer}</div>
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
            }).join('');
            
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

# Initialize scanner instance
def init_scanner():
    global scanner
    if scanner is None:
        scanner = BLEScanner()
    return scanner

# Flask routes
@app.route('/')
def index():
    """Main web interface"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def api_status():
    """Get add-on status"""
    if scanner is None:
        init_scanner()
    return jsonify(scanner.get_status())

@app.route('/api/devices')
def api_devices():
    """Get discovered devices"""
    if scanner is None:
        init_scanner()
    return jsonify(scanner.get_devices())

@app.route('/api/scan/start', methods=['POST'])
def api_start_scan():
    """Start BLE scanning"""
    if scanner is None:
        init_scanner()
    return jsonify(scanner.start_scan())

@app.route('/api/scan/stop', methods=['POST'])
def api_stop_scan():
    """Stop BLE scanning"""
    if scanner is None:
        init_scanner()
    return jsonify(scanner.stop_scan())

@app.route('/api/devices/clear', methods=['POST'])
def api_clear_devices():
    """Clear all devices"""
    if scanner is None:
        init_scanner()
    return jsonify(scanner.clear_devices())

@app.route('/api/diagnostic')
def api_diagnostic():
    """Diagnostic endpoint"""
    if scanner is None:
        init_scanner()
    return jsonify({
        "version": ADDON_VERSION,
        "config": {
            "mqtt_host": scanner.mqtt_host,
            "mqtt_port": scanner.mqtt_port,
            "mqtt_topic": scanner.mqtt_topic,
            "mqtt_discovery_enabled": scanner.mqtt_discovery_enabled,
            "esp32_proxies": scanner.esp32_proxies
        },
        "status": scanner.get_status(),
        "proxy_connections": scanner.proxy_connections
    })

@app.route('/api/devices/<mac_address>', methods=['POST'])
def add_device(mac_address):
    """Add a device manually"""
    if scanner is None:
        init_scanner()
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
    
    scanner.devices[mac_address.upper()] = device
    scanner.save_devices()
    
    return jsonify(device)

@app.route('/api/devices/<mac_address>', methods=['DELETE'])
def remove_device(mac_address):
    """Remove a device"""
    if scanner is None:
        init_scanner()
    logger.info("[API] /api/devices/<mac_address> called")
    if mac_address.upper() in scanner.devices:
        del scanner.devices[mac_address.upper()]
        scanner.save_devices()
        return jsonify({'message': 'Device removed'})
    return jsonify({'error': 'Device not found'}), 404

@app.route('/api/test_proxy/<int:proxy_index>', methods=['GET'])
def test_proxy(proxy_index):
    """Test ESP32 proxy connection"""
    if scanner is None:
        init_scanner()
    if proxy_index >= len(scanner.esp32_proxies):
        return jsonify({'error': 'Invalid proxy index'}), 400
    
    proxy = scanner.esp32_proxies[proxy_index]
    logger.info(f"[API] Testing proxy {proxy_index}: {proxy['host']}:{proxy.get('port', 6053)}")
    
    # Run test in background thread
    def run_test():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(scanner.test_websocket_connection(proxy))
            logger.info(f"[API] Proxy test result: {result}")
        except Exception as e:
            logger.error(f"[API] Proxy test error: {e}")
        finally:
            loop.close()
    
    threading.Thread(target=run_test, daemon=True).start()
    return jsonify({'message': 'Proxy test started', 'proxy': proxy})

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle unhandled exceptions"""
    logger.error(f"[API] Unhandled exception: {e}")
    return jsonify({'error': str(e)}), 500

# Initialize scanner when module is imported
init_scanner()

if __name__ == '__main__':
    logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} starting in development mode...")
    app.run(host='0.0.0.0', port=8099, debug=False) 