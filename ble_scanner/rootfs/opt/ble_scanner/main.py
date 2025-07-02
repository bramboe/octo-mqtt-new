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
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import paho.mqtt.client as mqtt
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ADDON_VERSION = "1.0.1"

class BLEScanner:
    def __init__(self):
        logger.info(f"[STARTUP] BLE Scanner Add-on v{ADDON_VERSION} initializing...")
        self.app = Flask(__name__)
        CORS(self.app)
        self.devices = {}
        self.esp32_proxies = []
        self.scan_interval = 30
        self.running = False
        self.scan_thread = None
        # MQTT config
        self.mqtt_host = None
        self.mqtt_port = 1883
        self.mqtt_user = None
        self.mqtt_password = None
        self.mqtt_topic = "ble_scanner/devices"
        self.mqtt_client = None
        self.mqtt_connected = False
        
        # Load configuration
        self.load_config()
        
        # Setup MQTT
        self.setup_mqtt()
        
        # Setup routes
        self.setup_routes()
        
    def load_config(self):
        """Load configuration from Home Assistant addon options"""
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
                self.mqtt_port = config.get('mqtt_port', 1883)
                self.mqtt_user = config.get('mqtt_user', None)
                self.mqtt_password = config.get('mqtt_password', None)
                self.mqtt_topic = config.get('mqtt_topic', 'ble_scanner/devices')
                # Set log level
                if log_level == 'debug':
                    logging.getLogger().setLevel(logging.DEBUG)
                logger.info(f"Loaded configuration: {len(self.esp32_proxies)} ESP32 proxies, MQTT host: {self.mqtt_host}")
            else:
                logger.warning("No configuration file found, using defaults")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
    
    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            return render_template('index.html')
        
        @self.app.route('/api/devices')
        def get_devices():
            return jsonify(list(self.devices.values()))
        
        @self.app.route('/api/devices/<mac_address>', methods=['POST'])
        def add_device(mac_address):
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
            if mac_address.upper() in self.devices:
                del self.devices[mac_address.upper()]
                self.save_devices()
                return jsonify({'message': 'Device removed'})
            return jsonify({'error': 'Device not found'}), 404
        
        @self.app.route('/api/scan/start', methods=['POST'])
        def start_scan():
            logger.info("[SCAN] /api/scan/start called")
            try:
                if self.running:
                    logger.info("[SCAN] Scan already running.")
                    return jsonify({'message': 'Scan already running'})
                logger.info("[SCAN] Starting BLE scan loop (user request)")
                self.running = True
                def scan_thread():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.scan_loop())
                    except Exception as e:
                        logger.error(f"[SCAN] Exception in scan thread: {e}")
                    finally:
                        logger.error("[SCAN] Scan thread exited unexpectedly!")
                self.scan_thread = threading.Thread(target=scan_thread, daemon=True)
                self.scan_thread.start()
                return jsonify({'message': 'Scan started'})
            except Exception as e:
                logger.error(f"[SCAN] Exception in /api/scan/start: {e}")
                return jsonify({'message': f'Error starting scan: {e}'}), 500
        
        @self.app.route('/api/scan/stop', methods=['POST'])
        def stop_scan():
            logger.info("[SCAN] /api/scan/stop called")
            if not self.running:
                logger.info("[SCAN] Scan already stopped.")
                return jsonify({'message': 'Scan already stopped'})
            logger.info("[SCAN] Stopping BLE scan loop (user request)")
            self.running = False
            return jsonify({'message': 'Scan stopped'})
        
        @self.app.route('/api/status')
        def get_status():
            return jsonify({
                'running': self.running,
                'device_count': len(self.devices),
                'proxy_count': len(self.esp32_proxies),
                'scan_interval': self.scan_interval
            })
        
        @self.app.errorhandler(Exception)
        def handle_exception(e):
            logger.error(f"[FLASK] Unhandled exception: {e}")
            return jsonify({'message': f'Internal server error: {e}'}), 500
    
    def save_devices(self):
        """Save discovered devices to file"""
        try:
            with open('/data/ble_devices/devices.json', 'w') as f:
                json.dump(self.devices, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving devices: {e}")
    
    def load_devices(self):
        """Load previously discovered devices from file"""
        try:
            devices_file = '/data/ble_devices/devices.json'
            if os.path.exists(devices_file):
                with open(devices_file, 'r') as f:
                    self.devices = json.load(f)
                logger.info(f"Loaded {len(self.devices)} devices from storage")
        except Exception as e:
            logger.error(f"Error loading devices: {e}")
    
    def setup_mqtt(self):
        """Setup MQTT client and connect"""
        if not self.mqtt_host or self.mqtt_host == '<auto_detect>':
            logger.info("MQTT host not set, MQTT will be disabled.")
            self.mqtt_client = None
            return
        self.mqtt_client = mqtt.Client()
        if self.mqtt_user and self.mqtt_user != '<auto_detect>':
            self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_password)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        try:
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self.mqtt_client = None
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker.")
            self.mqtt_connected = True
        else:
            logger.error(f"Failed to connect to MQTT broker, code {rc}")
            self.mqtt_connected = False
    
    def on_mqtt_disconnect(self, client, userdata, rc):
        logger.warning("Disconnected from MQTT broker.")
        self.mqtt_connected = False
    
    async def connect_esp32_proxy(self, proxy):
        """Connect to ESP32 BLE proxy with detailed logging"""
        uri = f"ws://{proxy['host']}:{proxy['port']}"
        logger.info(f"[BLEProxy] Attempting connection to {uri}")
        start_time = time.time()
        try:
            async with websockets.connect(uri) as websocket:
                logger.info(f"[BLEProxy] Connected to {proxy['host']}:{proxy['port']} after {time.time() - start_time:.2f}s")
                # Subscribe to BLE advertisements
                subscribe_msg = {
                    "id": 1,
                    "type": "subscribe_bluetooth_le_advertisements"
                }
                await websocket.send(json.dumps(subscribe_msg))
                logger.info(f"[BLEProxy] Subscribed to BLE advertisements on {proxy['host']}:{proxy['port']}")
                # Listen for BLE advertisements
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self.process_ble_advertisement(data, f"{proxy['host']}:{proxy['port']}")
                    except json.JSONDecodeError:
                        logger.warning(f"[BLEProxy] Invalid JSON from proxy {proxy['host']}:{proxy['port']}: {message}")
                    except Exception as e:
                        logger.error(f"[BLEProxy] Error processing message from {proxy['host']}:{proxy['port']}: {e}")
        except Exception as e:
            logger.error(f"[BLEProxy] Error connecting to {proxy['host']}:{proxy['port']}: {e}")
    
    async def process_ble_advertisement(self, data, proxy_name):
        """Process BLE advertisement data and publish to MQTT if enabled"""
        try:
            if 'bluetooth_le_advertisement' in data:
                adv = data['bluetooth_le_advertisement']
                mac_address = adv.get('address', '').upper()
                
                if not mac_address:
                    return
                
                device = {
                    'mac_address': mac_address,
                    'name': adv.get('name', 'Unknown Device'),
                    'rssi': adv.get('rssi', 0),
                    'last_seen': datetime.now().isoformat(),
                    'manufacturer': adv.get('manufacturer_data', {}),
                    'services': adv.get('service_uuids', []),
                    'proxy': proxy_name,
                    'added_manually': False
                }
                
                # Update existing device or add new one
                if mac_address in self.devices:
                    # Update last seen and RSSI
                    self.devices[mac_address].update({
                        'last_seen': device['last_seen'],
                        'rssi': device['rssi'],
                        'proxy': device['proxy']
                    })
                else:
                    self.devices[mac_address] = device
                    logger.info(f"New device discovered: {mac_address} ({device['name']})")
                
                # Publish to MQTT
                self.publish_mqtt_device(device)
        except Exception as e:
            logger.error(f"Error processing BLE advertisement: {e}")
    
    def publish_mqtt_device(self, device):
        """Publish a device dict to MQTT as JSON"""
        if self.mqtt_client and self.mqtt_connected:
            try:
                payload = json.dumps(device)
                self.mqtt_client.publish(self.mqtt_topic, payload, qos=0, retain=False)
                logger.debug(f"Published device to MQTT: {device['mac_address']}")
            except Exception as e:
                logger.error(f"Failed to publish to MQTT: {e}")
    
    async def scan_loop(self):
        logger.info("[SCAN] Starting BLE scan loop")
        while self.running:
            try:
                logger.info(f"[SCAN] Connecting to {len(self.esp32_proxies)} proxies...")
                tasks = []
                for proxy in self.esp32_proxies:
                    logger.info(f"[SCAN] Scheduling connection to proxy {proxy['host']}:{proxy['port']}")
                    task = asyncio.create_task(self.connect_esp32_proxy(proxy))
                    tasks.append(task)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(self.scan_interval)
            except Exception as e:
                logger.error(f"[SCAN] Error in scan loop: {e}")
                await asyncio.sleep(5)
        logger.info("[SCAN] BLE scan loop stopped")
    
    def run(self):
        """Start the Flask application"""
        # Load previously discovered devices
        self.load_devices()
        # Do not start scan loop here; only start on user request
        # Run Flask app
        self.app.run(host='0.0.0.0', port=8099, debug=False)
        # Cleanup MQTT
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

def main():
    """Main entry point"""
    try:
        scanner = BLEScanner()
        scanner.run()
    except KeyboardInterrupt:
        logger.info("Shutting down BLE Scanner")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 