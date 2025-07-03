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
from asyncio_mqtt import Client as MqttClient
import asyncio_mqtt
from aioesphomeapi import APIConnection, APIConnectionError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.32"

# Create Flask app at module level for Gunicorn
app = Flask(__name__)
CORS(app)

# Global scanner instance
scanner = None

class BLEScanner:
    def __init__(self):
        logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} initializing...")
        self.devices = {}
        self.bleProxies = []
        self.proxy_connections = {}
        self.running = True
        # MQTT config
        self.mqtt_host = None
        self.mqtt_port = 1883
        self.mqtt_username = None
        self.mqtt_password = None
        self.mqtt_discovery = False
        self.mqtt_client = None
        self.mqtt_connected = False
        # Load configuration
        self.load_config()
        # Setup MQTT
        self.setup_mqtt()
        # Start BLE proxy connections
        self.start_ble_proxies()
        
    def load_config(self):
        """Load configuration from Home Assistant addon options"""
        logger.info("[CONFIG] Loading configuration from /data/options.json...")
        try:
            config_path = "/data/options.json"
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                self.bleProxies = config.get('bleProxies', [])
                self.mqtt_host = config.get('mqtt_host', '<auto_detect>')
                self.mqtt_port = int(config.get('mqtt_port', 1883))
                self.mqtt_username = config.get('mqtt_username', '')
                self.mqtt_password = config.get('mqtt_password', '')
                self.mqtt_discovery = config.get('mqtt_discovery', False)
                logger.info(f"[CONFIG] Loaded: {len(self.bleProxies)} BLE proxies, MQTT host: {self.mqtt_host}, MQTT port: {self.mqtt_port}, MQTT discovery: {self.mqtt_discovery}")
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
        if self.mqtt_username == '<auto_detect>' or not self.mqtt_username:
            logger.info("[MQTT] Auto-detecting MQTT credentials...")
            self.mqtt_username, self.mqtt_password = self.auto_detect_mqtt_credentials()
        # Only create MQTT client if we have a host
        if not self.mqtt_host:
            logger.info("[MQTT] No MQTT host available, MQTT will be disabled.")
            self.mqtt_client = None
            return
        # Create MQTT client using asyncio-mqtt (smartbed-mqtt approach)
        try:
            mqtt_config = {
                'hostname': self.mqtt_host,
                'port': self.mqtt_port,
                'username': self.mqtt_username,
                'password': self.mqtt_password,
                'client_id': f"ble_scanner_{int(time.time())}"
            }
            logger.info(f"[MQTT] Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}...")
            self.mqtt_client = MqttClient(**mqtt_config)
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
        possible_hosts = [
            'core-mosquitto',
            'mosquitto',
            'mqtt',
            'localhost',
            '127.0.0.1'
        ]
        for host in possible_hosts:
            try:
                logger.info(f"[MQTT] Trying to connect to {host}:{self.mqtt_port}...")
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
        # Try to get credentials from MQTT add-on config (most reliable)
        try:
            response = requests.get("http://supervisor/addons/core-mosquitto/config", timeout=5)
            if response.status_code == 200:
                config = response.json()
                mqtt_user = config.get('username')
                mqtt_password = config.get('password')
                if mqtt_user and mqtt_password:
                    logger.info("[MQTT] Found MQTT credentials from MQTT add-on config")
                    return mqtt_user, mqtt_password
                logger.info("[MQTT] MQTT add-on config found but no credentials - trying no auth")
                return '', ''
        except Exception as e:
            logger.debug(f"[MQTT] Error getting credentials from MQTT add-on: {e}")
        # Try to read from Home Assistant secrets
        secrets_path = "/config/secrets.yaml"
        if os.path.exists(secrets_path):
            try:
                import yaml
                with open(secrets_path, 'r') as f:
                    secrets = yaml.safe_load(f)
                if secrets:
                    mqtt_user = secrets.get('mqtt_username') or secrets.get('mqtt_user')
                    mqtt_password = secrets.get('mqtt_password') or secrets.get('mqtt_pass')
                    if mqtt_user and mqtt_password:
                        logger.info("[MQTT] Found MQTT credentials in secrets.yaml")
                        return mqtt_user, mqtt_password
            except Exception as e:
                logger.debug(f"[MQTT] Error reading secrets.yaml: {e}")
        # Try no authentication first
        try:
            test_client = MqttClient(
                hostname=self.mqtt_host,
                port=self.mqtt_port,
                username=None,
                password=None,
                client_id=f"ble_scanner_test_{int(time.time())}"
            )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(test_client.connect())
                loop.run_until_complete(test_client.disconnect())
                logger.info(f"[MQTT] Found working credentials: no auth")
                return '', ''
            except Exception:
                pass
            finally:
                loop.close()
        except Exception as e:
            logger.debug(f"[MQTT] Failed to test credentials no auth: {e}")
        # Try common default credentials
        default_credentials = [
            ('homeassistant', 'homeassistant'),
            ('admin', 'admin'),
            ('mqtt', 'mqtt'),
            ('user', 'password')
        ]
        for username, password in default_credentials:
            try:
                test_client = MqttClient(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    username=username,
                    password=password,
                    client_id=f"ble_scanner_test_{int(time.time())}"
                )
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
        return '', ''

    async def test_mqtt_credentials(self, client):
        """Test MQTT credentials"""
        try:
            await client.connect()
            await client.disconnect()
            return True
        except Exception:
            return False

    def start_ble_proxies(self):
        for proxy in self.bleProxies:
            threading.Thread(target=self._run_ble_proxy, args=(proxy,), daemon=True).start()

    def _run_ble_proxy(self, proxy):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.connect_ble_proxy(proxy))
        except Exception as e:
            logger.error(f"[PROXY] Error in BLE proxy connection: {e}")
        finally:
            loop.close()

    async def connect_ble_proxy(self, proxy):
        proxy_key = f"{proxy['host']}:{proxy.get('port', 6053)}"
        while True:
            try:
                logger.info(f"[PROXY] Connecting to BLE proxy at {proxy_key}...")
                connection = APIConnection(
                    proxy['host'],
                    proxy.get('port', 6053),
                    proxy.get('password', ''),
                    "BLE Scanner Add-on"
                )
                await connection.connect()
                logger.info(f"[PROXY] Connected to BLE proxy at {proxy_key}")
                self.proxy_connections[proxy_key] = connection
                async def handle_ble_advertisement(adv):
                    await self.process_ble_advertisement(adv, proxy_key)
                await connection.subscribe_ble_advertisements(handle_ble_advertisement)
                while True:
                    try:
                        await asyncio.sleep(10)
                        await connection.ping()
                    except Exception as e:
                        logger.error(f"[PROXY] Connection error for {proxy_key}: {e}")
                        break
            except Exception as e:
                logger.error(f"[PROXY] Failed to connect to BLE proxy at {proxy_key}: {e}")
                self.proxy_connections[proxy_key] = None
            await asyncio.sleep(30)

    async def process_ble_advertisement(self, data, proxy_key):
        try:
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
            if mac_address in self.devices:
                existing = self.devices[mac_address]
                device_info['seen_count'] = existing.get('seen_count', 0) + 1
                if existing.get('added_manually'):
                    device_info['name'] = existing['name']
            self.devices[mac_address] = device_info
            if len(self.devices) % 10 == 0:
                self.save_devices()
            if self.mqtt_client and self.mqtt_connected:
                mqtt_message = {
                    'mac_address': mac_address,
                    'name': device_info['name'],
                    'rssi': device_info['rssi'],
                    'last_seen': device_info['last_seen'],
                    'proxy': proxy_key,
                    'seen_count': device_info['seen_count']
                }
                self.publish_mqtt("ble_scanner/data", mqtt_message)
                if self.mqtt_discovery:
                    device_topic = f"ble_scanner/data/devices/{mac_address.replace(':', '_')}"
                    self.publish_mqtt(device_topic, mqtt_message)
            logger.debug(f"[BLE] Discovered device: {mac_address} ({device_info['name']}) via {proxy_key}")
        except Exception as e:
            logger.error(f"[BLE] Error processing advertisement: {e}")

    def get_status(self):
        """Get add-on status"""
        return {
            'version': ADDON_VERSION,
            'running': True,
            'mqtt_connected': self.mqtt_connected,
            'proxy_connections': {k: (v is not None) for k, v in self.proxy_connections.items()},
            'total_proxies': len(self.bleProxies),
            'devices_count': len(self.devices)
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
                <span>Proxies:</span>
                <span id="proxy-list"></span>
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
            const proxyList = document.getElementById('proxy-list');
            proxyList.innerHTML = Object.entries(status.proxy_connections)
                .map(([proxy, connected]) => `<span style='color:${connected ? '#28a745' : '#dc3545'}'>${proxy} ${connected ? '●' : '○'}</span>`)
                .join(' ');
            
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
                                <div class="info-label">Last Seen</div>
                                <div class="info-value">${lastSeen}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Seen Count</div>
                                <div class="info-value">${device.seen_count}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Proxy</div>
                                <div class="info-value">${device.proxy || 'N/A'}</div>
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
            "mqtt_discovery_enabled": scanner.mqtt_discovery,
        },
        "status": scanner.get_status(),
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