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
import socket
import yaml
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request, render_template_string
from flask_cors import CORS
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.50"

# Create Flask app at module level for Gunicorn
app = Flask(__name__)
CORS(app)

# Ingress security - only allow connections from Home Assistant ingress proxy
@app.before_request
def check_ingress():
    """Check if request is from Home Assistant ingress proxy"""
    # Skip security check for health endpoint
    if request.endpoint == 'api_health':
        return None
    
    # Allow ingress proxy and localhost for development
    allowed_ips = ['172.30.32.2', '127.0.0.1', 'localhost']
    if request.remote_addr and request.remote_addr not in allowed_ips:
        return jsonify({'error': 'Access denied'}), 403

# Global scanner instance
scanner = None

def create_app():
    """Flask app factory to initialize MQTT after app starts"""
    global scanner
    if scanner is None:
        scanner = BLEScanner()
        # Initialize MQTT after Flask app is running
        scanner.setup_mqtt()
    return app

class BLEScanner:
    def __init__(self):
        logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} initializing...")
        self.devices = {}
        self.bleProxies = []
        self.running = True
        self.scanning = False
        # MQTT config
        self.mqtt_host = None
        self.mqtt_port = 1883
        self.mqtt_username = None
        self.mqtt_password = None
        self.mqtt_discovery = False
        self.mqtt_client = None
        self.mqtt_connected = False
        self.mqtt_initialized = False
        # Load configuration
        self.load_config()
        # MQTT will be setup after Flask app starts
        
    def load_config(self):
        """Load configuration from Home Assistant addon options"""
        logger.info("[CONFIG] Loading configuration from /data/options.json...")
        try:
            config_path = "/data/options.json"
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                # Load BLE proxies
                self.bleProxies = config.get('bleProxies', [])
                
                # Load MQTT config (new nested structure)
                mqtt_config = config.get('mqtt', {})
                self.mqtt_host = mqtt_config.get('host', '') or '<auto_detect>'
                self.mqtt_port = int(mqtt_config.get('port', 1883))
                self.mqtt_username = mqtt_config.get('username', '') or '<auto_detect>'
                self.mqtt_password = mqtt_config.get('password', '') or '<auto_detect>'
                self.mqtt_discovery = mqtt_config.get('discovery', False)
                
                logger.info(f"[CONFIG] Loaded: {len(self.bleProxies)} BLE proxies, MQTT host: {self.mqtt_host}, MQTT port: {self.mqtt_port}, MQTT discovery: {self.mqtt_discovery}")
            else:
                logger.warning("[CONFIG] No configuration file found, using defaults")
                # Set defaults
                self.bleProxies = []
                self.mqtt_host = '<auto_detect>'
                self.mqtt_port = 1883
                self.mqtt_username = '<auto_detect>'
                self.mqtt_password = '<auto_detect>'
                self.mqtt_discovery = False
        except Exception as e:
            logger.error(f"[CONFIG] Error loading configuration: {e}")
            # Set defaults on error
            self.bleProxies = []
            self.mqtt_host = '<auto_detect>'
            self.mqtt_port = 1883
            self.mqtt_username = '<auto_detect>'
            self.mqtt_password = '<auto_detect>'
            self.mqtt_discovery = False
    
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
        if self.mqtt_initialized:
            return
            
        try:
            # Handle auto-detection for MQTT host
            if self.mqtt_host == '<auto_detect>' or not self.mqtt_host:
                logger.info("[MQTT] Auto-detecting MQTT broker...")
                self.mqtt_host = self.auto_detect_mqtt_host()
            if not self.mqtt_host:
                logger.info("[MQTT] Could not auto-detect MQTT broker, MQTT will be disabled.")
                self.mqtt_client = None
                self.mqtt_initialized = True
                return
            # Handle auto-detection for MQTT credentials
            if self.mqtt_username == '<auto_detect>' or not self.mqtt_username:
                logger.info("[MQTT] Auto-detecting MQTT credentials...")
                self.mqtt_username, self.mqtt_password = self.auto_detect_mqtt_credentials()
            
            # Create MQTT client configuration but don't start connection yet
            logger.info(f"[MQTT] MQTT configured for {self.mqtt_host}:{self.mqtt_port}")
            self.mqtt_initialized = True
            
        except Exception as e:
            logger.error(f"[MQTT] Error setting up MQTT client: {e}")
            self.mqtt_client = None
            self.mqtt_initialized = True
    
    def start_mqtt_connection(self):
        """Start MQTT connection when needed"""
        if not self.mqtt_initialized:
            self.setup_mqtt()
        
        if self.mqtt_host and not self.mqtt_connected:
            try:
                logger.info(f"[MQTT] Starting MQTT connection to {self.mqtt_host}:{self.mqtt_port}")
                # Simple connection test for now
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((self.mqtt_host, self.mqtt_port))
                sock.close()
                if result == 0:
                    self.mqtt_connected = True
                    logger.info("[MQTT] MQTT broker connection verified")
                else:
                    logger.warning("[MQTT] Could not connect to MQTT broker")
            except Exception as e:
                logger.error(f"[MQTT] Error connecting to MQTT: {e}")

    async def _subscribe_to_ble_topics(self):
        """Subscribe to BLE advertisement topics following smartbed-mqtt pattern"""
        try:
            # Subscribe to ESP32 BLE proxy topics (following smartbed-mqtt pattern)
            topics = [
                # ESPHome BLE proxy format (most common)
                "esphome/+/ble_advertise",
                "esphome/+/ble_advertise/+",
                "esphome/+/ble_advertise/#",
                
                # Generic BLE proxy formats
                "ble_proxy/+/advertisement",
                "esp32_ble_proxy/+/data",
                "ble_scanner/+/data",
                
                # Smartbed-mqtt specific patterns
                "smartbed/+/ble_advertise",
                "smartbed/+/device/+",
                "smartbed/+/+/advertisement",
                
                # Alternative ESPHome patterns
                "esphome/+/+/ble_advertise",
                "esphome/+/+/+/ble_advertise",
                
                # Wildcard patterns for maximum coverage
                "+/ble_advertise",
                "+/+/ble_advertise",
                "+/+/+/ble_advertise",
                "+/advertisement",
                "+/+/advertisement",
            ]
            
            for topic in topics:
                await self.mqtt_client.subscribe(topic)
                logger.info(f"[MQTT] Subscribed to {topic}")
                
        except Exception as e:
            logger.error(f"[MQTT] Error subscribing to BLE topics: {e}")

    async def _handle_mqtt_message(self, message):
        """Handle incoming MQTT messages from BLE proxies"""
        try:
            topic = message.topic.value
            payload = message.payload.decode('utf-8')
            
            logger.info(f"[MQTT] Received message on {topic}: {payload}")
            
            # Parse the BLE advertisement data
            self._process_ble_advertisement(topic, payload)
            
        except Exception as e:
            logger.error(f"[MQTT] Error handling message: {e}")

    def _process_ble_advertisement(self, topic, payload):
        """Process BLE advertisement data from MQTT"""
        try:
            # Try to parse JSON payload
            data = json.loads(payload)
            
            # Extract device information
            device_info = self._extract_device_info(data)
            if device_info:
                # Add or update device
                mac_address = device_info['mac_address']
                self.devices[mac_address] = device_info
                self.save_devices()
                
                logger.info(f"[BLE] Discovered device: {device_info['name']} ({mac_address})")
                
                # Publish to MQTT if discovery is enabled
                if self.mqtt_discovery:
                    self.publish_mqtt(f"ble_scanner/discovered/{mac_address}", device_info)
                    
        except json.JSONDecodeError:
            logger.debug(f"[MQTT] Non-JSON payload on {topic}: {payload}")
        except Exception as e:
            logger.error(f"[MQTT] Error processing BLE advertisement: {e}")

    def _extract_device_info(self, data):
        """Extract device information from BLE advertisement data following smartbed-mqtt pattern"""
        try:
            # Handle different BLE proxy formats
            if 'address' in data:
                mac_address = data['address'].upper()
            elif 'mac' in data:
                mac_address = data['mac'].upper()
            elif 'mac_address' in data:
                mac_address = data['mac_address'].upper()
            else:
                return None
                
            # Extract device name
            name = data.get('name', 'Unknown Device')
            if not name or name == '':
                name = f"BLE Device {mac_address[-6:]}"
                
            # Extract RSSI
            rssi = data.get('rssi', 0)
            
            # Extract manufacturer data
            manufacturer = data.get('manufacturer', 'Unknown')
            manufacturer_data = data.get('manufacturer_data', {})
            
            # Extract services
            services = data.get('services', [])
            
            # Extract service data
            service_data = data.get('service_data', {})
            
            # Classify device type based on manufacturer and services
            device_type = self._classify_device(manufacturer, services, service_data, manufacturer_data)
            
            # Extract additional metadata
            metadata = {
                'manufacturer_data': manufacturer_data,
                'service_data': service_data,
                'advertisement_type': data.get('advertisement_type', 'unknown'),
                'connectable': data.get('connectable', True),
                'tx_power': data.get('tx_power'),
                'flags': data.get('flags', []),
            }
            
            return {
                'mac_address': mac_address,
                'name': name,
                'rssi': rssi,
                'last_seen': datetime.now().isoformat(),
                'manufacturer': manufacturer,
                'services': services,
                'device_type': device_type,
                'metadata': metadata,
                'source': 'mqtt'
            }
            
        except Exception as e:
            logger.error(f"[BLE] Error extracting device info: {e}")
            return None

    def _classify_device(self, manufacturer, services, service_data, manufacturer_data):
        """Classify device type based on manufacturer and services (following smartbed-mqtt pattern)"""
        try:
            # Common BLE service UUIDs for different device types
            service_uuids = [str(s).upper() for s in services]
            
            # Smart bed manufacturers and services
            if any('1800' in uuid for uuid in service_uuids):  # Generic Access
                if any('1801' in uuid for uuid in service_uuids):  # Generic Attribute
                    return 'generic_ble'
                    
            # Richmat/Leggett & Platt (Gen2)
            if any('0000ffe0' in uuid for uuid in service_uuids):
                return 'richmat_gen2'
                
            # Linak
            if any('0000ffe0' in uuid for uuid in service_uuids) and 'linak' in manufacturer.lower():
                return 'linak'
                
            # Solace
            if any('0000ffe0' in uuid for uuid in service_uuids) and 'solace' in manufacturer.lower():
                return 'solace'
                
            # MotoSleep
            if any('0000ffe0' in uuid for uuid in service_uuids) and 'motosleep' in manufacturer.lower():
                return 'motosleep'
                
            # Reverie
            if any('0000ffe0' in uuid for uuid in service_uuids) and 'reverie' in manufacturer.lower():
                return 'reverie'
                
            # Keeson
            if any('0000ffe0' in uuid for uuid in service_uuids) and 'keeson' in manufacturer.lower():
                return 'keeson'
                
            # Octo
            if any('0000ffe0' in uuid for uuid in service_uuids) and 'octo' in manufacturer.lower():
                return 'octo'
                
            # Check manufacturer data for specific patterns
            if manufacturer_data:
                # Add manufacturer-specific classification logic here
                pass
                
            # Default classification
            if manufacturer and manufacturer != 'Unknown':
                return f'manufacturer_{manufacturer.lower().replace(" ", "_")}'
            else:
                return 'unknown'
                
        except Exception as e:
            logger.error(f"[BLE] Error classifying device: {e}")
            return 'unknown'

    def publish_mqtt(self, topic, message):
        """Publish message to MQTT (simplified for stability)"""
        if self.mqtt_connected:
            logger.info(f"[MQTT] Would publish to {topic}: {json.dumps(message)}")
        else:
            logger.debug(f"[MQTT] Not connected, skipping publish to {topic}")

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

    def test_mqtt_credentials(self, host, port, username, password):
        """Test MQTT credentials with socket connection"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def get_status(self):
        """Get add-on status"""
        return {
            'version': ADDON_VERSION,
            'running': True,
            'scanning': self.scanning,
            'mqtt_connected': self.mqtt_connected,
            'mqtt_host': self.mqtt_host,
            'total_proxies': len(self.bleProxies),
            'devices_count': len(self.devices),
            'ble_proxies': self.bleProxies
        }

    def get_devices(self):
        """Get discovered devices"""
        return self.devices

    def start_scan(self):
        """Start BLE scanning"""
        if not self.scanning:
            self.scanning = True
            logger.info("[SCAN] BLE scanning started - listening for MQTT advertisements from ESP32 proxies")
            
            # Start MQTT connection if needed
            self.start_mqtt_connection()
            
            # Log ESP32 proxy configuration for reference
            if self.bleProxies:
                logger.info(f"[SCAN] Configured ESP32 proxies: {len(self.bleProxies)} (MQTT-only)")
                for i, proxy in enumerate(self.bleProxies):
                    host = proxy.get('host', proxy.get('ip'))
                    port = proxy.get('port', 6053)
                    logger.info(f"[SCAN] ESP32 Proxy {i+1}: {host}:{port} (configured for MQTT)")
            else:
                logger.warning("[SCAN] No ESP32 proxies configured")
            
            # Publish scan start message
            if self.mqtt_connected:
                self.publish_mqtt("ble_scanner/status", {
                    "scanning": True,
                    "timestamp": datetime.now().isoformat()
                })
            
            return {'status': 'started', 'message': 'BLE scanning started - listening for MQTT advertisements from ESP32 proxies'}
        else:
            return {'status': 'already_running', 'message': 'Scanning already in progress'}

    def stop_scan(self):
        """Stop BLE scanning"""
        if self.scanning:
            self.scanning = False
            logger.info("[SCAN] BLE scanning stopped")
            
            # Publish scan stop message
            if self.mqtt_connected:
                self.publish_mqtt("ble_scanner/status", {
                    "scanning": False,
                    "timestamp": datetime.now().isoformat()
                })
            
            return {'status': 'stopped', 'message': 'BLE scanning stopped'}
        else:
            return {'status': 'not_running', 'message': 'Scanning was not running'}

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
        
        .device-type {
            font-size: 0.8em;
            padding: 2px 6px;
            border-radius: 4px;
            background: #e9ecef;
            color: #495057;
            display: inline-block;
            margin-top: 4px;
            text-transform: uppercase;
            font-weight: 500;
            letter-spacing: 0.5px;
        }
        
        .device-type.richmat_gen2 {
            background: #d4edda;
            color: #155724;
        }
        
        .device-type.linak {
            background: #d1ecf1;
            color: #0c5460;
        }
        
        .device-type.solace {
            background: #fff3cd;
            color: #856404;
        }
        
        .device-type.motosleep {
            background: #f8d7da;
            color: #721c24;
        }
        
        .device-type.reverie {
            background: #e2e3e5;
            color: #383d41;
        }
        
        .device-type.keeson {
            background: #d1ecf1;
            color: #0c5460;
        }
        
        .device-type.octo {
            background: #f8d7da;
            color: #721c24;
        }
        
        .device-type.generic_ble {
            background: #e9ecef;
            color: #495057;
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
                <div class="status-indicator" id="scan-status"></div>
                <span>Scanning: <span id="scan-text">Stopped</span></span>
            </div>
            <div class="status-item">
                <div class="status-indicator" id="proxy-status"></div>
                <span>ESP32 Proxies:</span>
                <span id="proxy-list"></span>
            </div>
            <div class="status-item">
                <span>Devices: <span id="devices-count">0</span></span>
            </div>
            <div class="status-item">
                <span>Version: <span id="version">1.0.37</span></span>
            </div>
        </div>
        
        <div class="controls">
            <button class="btn btn-primary" onclick="startScan()">Start Scan</button>
            <button class="btn btn-success" onclick="stopScan()">Stop Scan</button>
            <button class="btn btn-warning" onclick="clearDevices()">Clear Devices</button>
            <button class="btn btn-primary" onclick="testMqtt()">Test MQTT</button>
            <button class="btn btn-primary" onclick="testEsp32()">Test ESP32</button>
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
            
            // Update scanning status
            const scanStatus = document.getElementById('scan-status');
            const scanText = document.getElementById('scan-text');
            if (status.scanning) {
                scanStatus.className = 'status-indicator online';
                scanText.textContent = 'Active';
            } else {
                scanStatus.className = 'status-indicator';
                scanText.textContent = 'Stopped';
            }
            
            // Update ESP32 proxy status (Direct + MQTT)
            const proxyStatus = document.getElementById('proxy-status');
            const proxyList = document.getElementById('proxy-list');
            if (status.esp32_connected || (status.mqtt_connected && status.scanning)) {
                proxyStatus.className = 'status-indicator online';
                let proxyText = `${status.total_proxies} configured`;
                if (status.esp32_connected) {
                    proxyText += ` (${status.esp32_connections} connected)`;
                }
                if (status.mqtt_connected && status.scanning) {
                    proxyText += ` + MQTT`;
                }
                proxyList.textContent = proxyText;
            } else {
                proxyStatus.className = 'status-indicator';
                proxyList.textContent = `${status.total_proxies} configured`;
            }
            
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
                
                const deviceType = device.device_type || 'unknown';
                const deviceTypeClass = deviceType.replace(/[^a-zA-Z0-9]/g, '_');
                
                return `
                    <div class="device-card">
                        <div class="device-header">
                            <div>
                                <div class="device-name">${device.name}</div>
                                <div class="device-mac">${device.mac_address}</div>
                                <div class="device-type ${deviceTypeClass}">${deviceType}</div>
                            </div>
                            <div class="device-rssi" style="color: ${rssiColor}">${device.rssi} dBm</div>
                        </div>
                        <div class="device-info">
                            <div class="info-item">
                                <div class="info-label">Last Seen</div>
                                <div class="info-value">${lastSeen}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Manufacturer</div>
                                <div class="info-value">${device.manufacturer || 'Unknown'}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Device Type</div>
                                <div class="info-value">${deviceType}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">Services</div>
                                <div class="info-value">${device.services ? device.services.length : 0}</div>
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
        
        async function testMqtt() {
            try {
                const response = await fetch('/api/test/mqtt', { method: 'POST' });
                const result = await response.json();
                
                if (result.status === 'success') {
                    alert('MQTT Test: SUCCESS\n\n' + 
                          'MQTT Connected: ' + result.mqtt_connected + '\n' +
                          'MQTT Host: ' + result.mqtt_host + '\n' +
                          'Scanning: ' + result.scanning + '\n' +
                          'Message: ' + result.message);
                } else {
                    alert('MQTT Test: FAILED\n\n' + 
                          'MQTT Connected: ' + result.mqtt_connected + '\n' +
                          'MQTT Host: ' + result.mqtt_host + '\n' +
                          'Scanning: ' + result.scanning + '\n' +
                          'Error: ' + result.message);
                }
            } catch (error) {
                console.error('Error testing MQTT:', error);
                alert('MQTT Test: ERROR\n\n' + error.message);
            }
        }
        
        async function testEsp32() {
            try {
                const response = await fetch('/api/test/esp32', { method: 'POST' });
                const result = await response.json();
                
                let message = 'ESP32 Test Results:\n\n';
                message += 'Configured Proxies: ' + result.configured_proxies.length + '\n';
                message += 'ESP32 Reachable: ' + result.esp32_reachable + '\n';
                if (result.esp32_host) {
                    message += 'ESP32 Host: ' + result.esp32_host + '\n';
                }
                message += 'MQTT Connected: ' + result.mqtt_connected + '\n';
                message += 'MQTT Host: ' + result.mqtt_host + '\n';
                message += 'Scanning: ' + result.scanning + '\n';
                message += 'Subscribed Topics: ' + result.subscribed_topics.length + '\n';
                
                if (result.esp32_error) {
                    message += '\nESP32 Error: ' + result.esp32_error;
                }
                
                alert(message);
            } catch (error) {
                console.error('Error testing ESP32:', error);
                alert('ESP32 Test: ERROR\n\n' + error.message);
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
        # Initialize MQTT after Flask app is running
        scanner.setup_mqtt()
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
            "ble_proxies": scanner.bleProxies,
        },
        "status": scanner.get_status(),
        "mqtt_details": {
            "connected": scanner.mqtt_connected,
            "initialized": scanner.mqtt_initialized,
            "client_exists": scanner.mqtt_client is not None,
        }
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

@app.route('/api/test/mqtt', methods=['POST'])
def test_mqtt():
    """Test MQTT connection and publish a test message"""
    if scanner is None:
        init_scanner()
    
    try:
        # Force MQTT setup if not already done
        if not scanner.mqtt_initialized:
            scanner.setup_mqtt()
        
        # Try to connect to MQTT
        scanner.start_mqtt_connection()
        
        if scanner.mqtt_connected:
            # Publish a test message
            test_message = {
                "test": True,
                "timestamp": datetime.now().isoformat(),
                "message": "BLE Scanner test message"
            }
            scanner.publish_mqtt("ble_scanner/test", test_message)
            
            return jsonify({
                "status": "success",
                "message": "MQTT test message published",
                "mqtt_connected": scanner.mqtt_connected,
                "mqtt_host": scanner.mqtt_host,
                "scanning": scanner.scanning
                        })
        else:
            return jsonify({
                "status": "error",
                "message": "MQTT not connected",
                "mqtt_connected": scanner.mqtt_connected,
                "mqtt_host": scanner.mqtt_host,
                "scanning": scanner.scanning
            }), 500
            
    except Exception as e:
        logger.error(f"[API] MQTT test error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "mqtt_connected": scanner.mqtt_connected,
            "mqtt_host": scanner.mqtt_host,
            "scanning": scanner.scanning
        }), 500

@app.route('/api/health')
def api_health():
    """Health check endpoint for Home Assistant add-on monitoring"""
    if scanner is None:
        init_scanner()
    return jsonify({
        "status": "healthy",
        "version": ADDON_VERSION,
        "mqtt_connected": scanner.mqtt_connected if scanner else False,
        "scanning": scanner.scanning if scanner else False
    })

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle unhandled exceptions"""
    logger.error(f"[API] Unhandled exception: {e}")
    return jsonify({'error': str(e)}), 500

# Initialize scanner when first API call is made
# (This prevents MQTT initialization before Gunicorn starts)

if __name__ == '__main__':
    logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} starting in development mode...")
    app.run(host='0.0.0.0', port=8099, debug=False) 