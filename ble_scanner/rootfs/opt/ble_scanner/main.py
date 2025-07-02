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

ADDON_VERSION = "1.0.8"

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
        # Proxy connection tracking
        self.proxy_connections = {}
        
        # Load configuration
        self.load_config()
        
        # Setup MQTT
        self.setup_mqtt()
        
        # Setup routes
        self.setup_routes()
        
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
                self.mqtt_topic = config.get('mqtt_topic', 'ble_scanner/devices')
                # Set log level
                if log_level == 'debug':
                    logging.getLogger().setLevel(logging.DEBUG)
                logger.info(f"[CONFIG] Loaded: {len(self.esp32_proxies)} ESP32 proxies, MQTT host: {self.mqtt_host}, MQTT port: {self.mqtt_port}")
            else:
                logger.warning("[CONFIG] No configuration file found, using defaults")
        except Exception as e:
            logger.error(f"[CONFIG] Error loading configuration: {e}")
    
    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            return render_template('index.html')
        
        @self.app.route('/api/devices')
        def get_devices():
            logger.info("[API] /api/devices called")
            try:
                return jsonify(list(self.devices.values()))
            except Exception as e:
                logger.error(f"[API] Error in /api/devices: {e}")
                return jsonify({"error": str(e)}), 500
        
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
        
        @self.app.route('/api/start_scan', methods=['POST'])
        def start_scan():
            logger.info("[API] /api/start_scan called")
            try:
                if self.running:
                    logger.warning("[API] Scan already running")
                    return jsonify({"status": "already_running", "error": "Scan already running"}), 400
                self.running = True
                self.scan_thread = threading.Thread(target=self._run_scan_loop, daemon=True)
                self.scan_thread.start()
                logger.info("[API] Scan started successfully")
                return jsonify({"status": "started", "message": "Scan started successfully"})
            except Exception as e:
                logger.error(f"[API] Error in /api/start_scan: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/stop_scan', methods=['POST'])
        def stop_scan():
            logger.info("[API] /api/stop_scan called")
            try:
                if not self.running:
                    logger.warning("[API] Scan not running")
                    return jsonify({"status": "not_running", "error": "Scan not running"}), 400
                self.running = False
                logger.info("[API] Scan stopped successfully")
                return jsonify({"status": "stopped", "message": "Scan stopped successfully"})
            except Exception as e:
                logger.error(f"[API] Error in /api/stop_scan: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/status')
        def get_status():
            connected_proxies = sum(1 for status in self.proxy_connections.values() if status)
            return jsonify({
                'running': self.running,
                'device_count': len(self.devices),
                'proxy_count': len(self.esp32_proxies),
                'connected_proxies': connected_proxies,
                'scan_interval': self.scan_interval,
                'mqtt_connected': self.mqtt_connected,
                'proxy_connections': self.proxy_connections
            })
        
        @self.app.route('/api/config', methods=['GET'])
        def api_config():
            logger.info("[API] /api/config called")
            try:
                return jsonify({
                    "esp32_proxies": self.esp32_proxies,
                    "scan_interval": self.scan_interval,
                    "mqtt_host": self.mqtt_host,
                    "mqtt_port": self.mqtt_port,
                    "mqtt_topic": self.mqtt_topic,
                    "version": ADDON_VERSION
                })
            except Exception as e:
                logger.error(f"[API] Error in /api/config: {e}")
                return jsonify({"error": str(e)}), 500
        
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
            logger.info("[MQTT] MQTT host not set, MQTT will be disabled.")
            self.mqtt_client = None
            return
        self.mqtt_client = mqtt.Client(client_id=f"ble_scanner_{int(time.time())}")
        if self.mqtt_user and self.mqtt_user != '<auto_detect>':
            self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_password)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        try:
            logger.info(f"[MQTT] Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}...")
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"[MQTT] MQTT connection failed: {e}")
            self.mqtt_client = None
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("[MQTT] Successfully connected to MQTT broker")
            self.mqtt_connected = True
        else:
            error_codes = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier", 
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized"
            }
            error_msg = error_codes.get(rc, f"Unknown error code {rc}")
            logger.error(f"[MQTT] Failed to connect to MQTT broker: {error_msg} (code {rc})")
            self.mqtt_connected = False
    
    def on_mqtt_disconnect(self, client, userdata, rc):
        if rc == 0:
            logger.info("[MQTT] Cleanly disconnected from MQTT broker")
        else:
            logger.warning(f"[MQTT] Unexpectedly disconnected from MQTT broker (code {rc})")
        self.mqtt_connected = False
    
    async def connect_esp32_proxy(self, proxy):
        """Connect to ESP32 BLE proxy with detailed logging"""
        # Try WebSocket connection first (ESPHome API)
        ws_uri = f"ws://{proxy['host']}:{proxy['port']}"
        logger.info(f"[BLEPROXY] Attempting WebSocket connection to {ws_uri}")
        start_time = time.time()
        
        try:
            async with websockets.connect(ws_uri, ping_interval=30, ping_timeout=10) as websocket:
                proxy_key = f"{proxy['host']}:{proxy['port']}"
                self.proxy_connections[proxy_key] = True
                logger.info(f"[BLEPROXY] Connected to {proxy['host']}:{proxy['port']} after {time.time() - start_time:.2f}s")
                
                # Send ESPHome API authentication (if needed)
                auth_msg = {
                    "type": "auth",
                    "api_password": ""  # Empty for no password
                }
                await websocket.send(json.dumps(auth_msg))
                logger.info(f"[BLEPROXY] Sent authentication to {proxy['host']}:{proxy['port']}")
                
                # Subscribe to BLE advertisements
                subscribe_msg = {
                    "id": 1,
                    "type": "subscribe_bluetooth_le_advertisements"
                }
                await websocket.send(json.dumps(subscribe_msg))
                logger.info(f"[BLEPROXY] Subscribed to BLE advertisements on {proxy['host']}:{proxy['port']}")
                
                # Listen for BLE advertisements
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        logger.debug(f"[BLEPROXY] Received message from {proxy['host']}:{proxy['port']}: {data}")
                        await self.process_ble_advertisement(data, f"{proxy['host']}:{proxy['port']}")
                    except json.JSONDecodeError:
                        logger.warning(f"[BLEPROXY] Invalid JSON from proxy {proxy['host']}:{proxy['port']}: {message}")
                    except Exception as e:
                        logger.error(f"[BLEPROXY] Error processing message from {proxy['host']}:{proxy['port']}: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            proxy_key = f"{proxy['host']}:{proxy['port']}"
            self.proxy_connections[proxy_key] = False
            logger.warning(f"[BLEPROXY] WebSocket connection closed to {proxy['host']}:{proxy['port']}")
        except websockets.exceptions.InvalidURI:
            proxy_key = f"{proxy['host']}:{proxy['port']}"
            self.proxy_connections[proxy_key] = False
            logger.error(f"[BLEPROXY] Invalid WebSocket URI: {ws_uri}")
        except Exception as e:
            proxy_key = f"{proxy['host']}:{proxy['port']}"
            self.proxy_connections[proxy_key] = False
            logger.error(f"[BLEPROXY] Error connecting to {proxy['host']}:{proxy['port']}: {e}")
            # Try HTTP API as fallback
            await self.try_http_api(proxy)

    async def try_http_api(self, proxy):
        """Try HTTP API as fallback for ESP32 proxy"""
        http_url = f"http://{proxy['host']}:{proxy['port']}/api"
        logger.info(f"[BLEPROXY] Trying HTTP API fallback: {http_url}")
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get ESP32 info
                async with session.get(f"{http_url}/info") as response:
                    if response.status == 200:
                        info = await response.json()
                        logger.info(f"[BLEPROXY] ESP32 Info: {info}")
                    else:
                        logger.warning(f"[BLEPROXY] HTTP API info failed: {response.status}")
                        
                # Try to get BLE devices via HTTP
                async with session.get(f"{http_url}/ble_devices") as response:
                    if response.status == 200:
                        devices = await response.json()
                        logger.info(f"[BLEPROXY] Found {len(devices)} devices via HTTP API")
                        for device in devices:
                            await self.process_ble_advertisement({
                                'bluetooth_le_advertisement': device
                            }, f"{proxy['host']}:{proxy['port']} (HTTP)")
                    else:
                        logger.warning(f"[BLEPROXY] HTTP API BLE devices failed: {response.status}")
                        
        except Exception as e:
            logger.error(f"[BLEPROXY] HTTP API fallback failed: {e}")
    
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
                result = self.mqtt_client.publish(self.mqtt_topic, payload, qos=0, retain=False)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    logger.debug(f"[MQTT] Published device {device['mac_address']} to {self.mqtt_topic}")
                else:
                    logger.error(f"[MQTT] Failed to publish device {device['mac_address']}: error code {result.rc}")
            except Exception as e:
                logger.error(f"[MQTT] Exception publishing device {device['mac_address']}: {e}")
        else:
            logger.debug(f"[MQTT] Skipping publish for {device['mac_address']} - MQTT not connected")
    
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
                    # Wait for all proxy connections with timeout
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*tasks, return_exceptions=True),
                            timeout=self.scan_interval
                        )
                    except asyncio.TimeoutError:
                        logger.info(f"[SCAN] Scan cycle completed after {self.scan_interval}s timeout")
                else:
                    logger.warning("[SCAN] No ESP32 proxies configured")
                    await asyncio.sleep(5)
                    
            except Exception as e:
                logger.error(f"[SCAN] Error in scan loop: {e}")
                await asyncio.sleep(5)
                
        logger.info("[SCAN] BLE scan loop stopped")

    def _run_scan_loop(self):
        """Run the scan loop in a separate thread"""
        logger.info("[SCAN] Starting scan thread")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.scan_loop())
        except Exception as e:
            logger.error(f"[SCAN] Exception in scan thread: {e}")
        finally:
            logger.info("[SCAN] Scan thread exited")
    
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