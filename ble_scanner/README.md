# BLE Scanner - Home Assistant Add-on

A Home Assistant add-on for discovering and managing BLE devices using ESP32 BLE proxies, following the [smartbed-mqtt](https://github.com/richardhopton/smartbed-mqtt) pattern.

## Overview

This add-on provides a web interface for discovering and managing BLE devices that are detected by ESP32 BLE proxies. It follows the same architecture as [smartbed-mqtt](https://github.com/richardhopton/smartbed-mqtt), using MQTT for communication with ESP32 BLE proxies.

## Features

- **MQTT-based BLE Discovery**: Listens for BLE advertisements published by ESP32 BLE proxies via MQTT
- **Device Classification**: Automatically classifies devices based on manufacturer and service UUIDs
- **Web UI**: Modern, responsive web interface for device management
- **Real-time Updates**: Live updates as new BLE devices are discovered
- **Device Persistence**: Saves discovered devices to persistent storage
- **Auto-detection**: Automatically detects MQTT broker and credentials
- **Smartbed-mqtt Compatibility**: Follows the same patterns as smartbed-mqtt for seamless integration

## How It Works

1. **ESP32 BLE Proxy**: Scans for BLE devices and publishes advertisements to MQTT
2. **BLE Scanner Add-on**: Subscribes to MQTT topics and listens for BLE advertisements
3. **Web UI**: Displays discovered devices in real-time with device classification

## Configuration

### Basic Configuration

```yaml
mqtt_host: "<auto_detect>"
mqtt_port: 1883
mqtt_username: "<auto_detect>"
mqtt_password: "<auto_detect>"
mqtt_discovery: false
bleProxies:
  - host: "192.168.1.109"
    port: 6053
```

### Configuration Options

- **mqtt_host**: MQTT broker hostname (use `<auto_detect>` for automatic detection)
- **mqtt_port**: MQTT broker port (default: 1883)
- **mqtt_username**: MQTT username (use `<auto_detect>` for automatic detection)
- **mqtt_password**: MQTT password (use `<auto_detect>` for automatic detection)
- **mqtt_discovery**: Enable MQTT device discovery (default: false)
- **bleProxies**: List of ESP32 BLE proxy configurations (for reference only)

## Device Classification

The add-on automatically classifies BLE devices based on manufacturer and service UUIDs:

- **Richmat Gen2**: Richmat/Leggett & Platt Gen2 devices
- **Linak**: Linak bed controllers
- **Solace**: Solace bed controllers
- **MotoSleep**: MotoSleep bed controllers
- **Reverie**: Reverie bed controllers
- **Keeson**: Keeson bed controllers
- **Octo**: Octo bed controllers
- **Generic BLE**: Standard BLE devices

## MQTT Topics

The add-on subscribes to the following MQTT topics for BLE advertisements:

- `esphome/+/ble_advertise` - ESPHome BLE proxy format
- `esphome/+/ble_advertise/+` - ESPHome with device ID
- `esphome/+/ble_advertise/#` - ESPHome wildcard
- `ble_proxy/+/advertisement` - Generic BLE proxy format
- `esp32_ble_proxy/+/data` - Alternative format
- `smartbed/+/ble_advertise` - Smartbed-mqtt format
- `+/ble_advertise` - Wildcard format

## Web Interface

Access the web interface at `http://your-ha-ip:8099`

### Features

- **Real-time Status**: Shows MQTT connection and scanning status
- **Device Discovery**: Displays all discovered BLE devices
- **Device Details**: Shows device type, manufacturer, RSSI, and last seen time
- **Device Management**: Add, remove, and manage devices
- **Testing Tools**: Test MQTT connection and ESP32 proxy configuration

## Smartbed-mqtt Compatibility

This add-on is designed to work seamlessly with [smartbed-mqtt](https://github.com/richardhopton/smartbed-mqtt):

- **Same MQTT Topics**: Uses the same MQTT topic patterns
- **Same Device Classification**: Classifies devices using the same logic
- **Same Architecture**: MQTT-only communication with ESP32 proxies
- **Complementary Functionality**: Focuses on device discovery while smartbed-mqtt handles device control

## Installation

1. Add this repository to your Home Assistant add-ons
2. Install the "BLE Scanner" add-on
3. Configure your ESP32 BLE proxies and MQTT settings
4. Start the add-on and access the web interface

## Troubleshooting

### No Devices Discovered

1. **Check MQTT Connection**: Use the "Test MQTT" button in the web UI
2. **Verify ESP32 Configuration**: Use the "Test ESP32" button to check proxy settings
3. **Check MQTT Topics**: Ensure your ESP32 proxies are publishing to the correct topics
4. **Start Scanning**: Click "Start Scan" to begin listening for advertisements

### MQTT Connection Issues

1. **Auto-detection**: The add-on automatically detects MQTT broker and credentials
2. **Manual Configuration**: If auto-detection fails, manually configure MQTT settings
3. **Network Access**: Ensure the add-on has network access to reach the MQTT broker

## Version History

- **1.0.45**: Enhanced smartbed-mqtt compatibility, improved device classification, better MQTT topic coverage
- **1.0.44**: Added detailed logging for MQTT connection and scanning
- **1.0.43**: Fixed MQTT connection issues with event loop handling
- **1.0.42**: Enhanced MQTT-based BLE scanning with multiple topic subscriptions
- **1.0.41**: Fixed build issues with aioesphomeapi dependency
- **1.0.40**: Added direct ESP32 API connection support
- **1.0.39**: Enhanced MQTT-based BLE scanning
- **1.0.38**: Implemented MQTT-based BLE device discovery
- **1.0.37**: Fixed MQTT connection with proper event loop handling
- **1.0.36**: Switched to MQTT-only architecture matching smartbed-mqtt
- **1.0.35**: Removed direct proxy connections, MQTT-only operation
- **1.0.34**: Added hybrid MQTT and direct proxy support
- **1.0.33**: Removed aioesphomeapi, MQTT-only operation
- **1.0.32**: Fixed protobuf compatibility issues
- **1.0.31**: Production-ready with Gunicorn and proper service management
- **1.0.30**: Switched to asyncio-mqtt for MQTT communication
- **1.0.29**: Fixed dependency issues and improved MQTT setup
- **1.0.28**: Added MQTT auto-detection and credential handling
- **1.0.27**: Refactored scan logic and improved API endpoints
- **1.0.26**: Fixed MQTT connection and ESP32 proxy integration
- **1.0.25**: Initial release with basic BLE scanning functionality

## Support

For help and support, please refer to the [smartbed-mqtt documentation](https://github.com/richardhopton/smartbed-mqtt) or create an issue in this repository.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 