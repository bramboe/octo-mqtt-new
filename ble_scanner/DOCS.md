# BLE Scanner Add-on Documentation

## About

The BLE Scanner Add-on is a MQTT-based BLE device scanner that's fully compatible with [smartbed-mqtt](https://github.com/richardhopton/smartbed-mqtt). It discovers BLE devices via ESP32 proxies and integrates them into Home Assistant through MQTT discovery.

## How it works

1. **ESP32 BLE Proxy** scans for BLE devices and publishes advertisements to MQTT
2. **BLE Scanner** subscribes to MQTT topics and processes the advertisements  
3. **Home Assistant** discovers devices via MQTT discovery protocol
4. **Web UI** provides real-time monitoring and device management

This is the exact same architecture used by smartbed-mqtt, ensuring full compatibility.

## Installation

1. Add this repository to your Home Assistant add-on store
2. Install the "BLE Scanner" add-on
3. Configure your ESP32 BLE proxy details
4. Start the add-on
5. Access the web UI to monitor discovered devices

## Configuration

### Example configuration:

```yaml
bleProxies:
  - host: "192.168.1.109"
    port: 6053
    password: ""
mqtt:
  host: ""                    # Leave empty for auto-detection
  port: 1883
  username: ""               # Leave empty for auto-detection  
  password: ""               # Leave empty for auto-detection
  discovery: true
```

### Configuration Options

#### `bleProxies` (required)
List of ESP32 BLE proxy configurations. These proxies will publish BLE advertisements to MQTT.

- **host** (string): IP address of your ESP32 BLE proxy
- **port** (integer, optional): Port number (default: 6053)  
- **password** (string, optional): Password for ESP32 proxy (if configured)

#### `mqtt` (optional)
MQTT broker configuration. Leave fields empty for auto-detection.

- **host** (string, optional): MQTT broker hostname (auto-detected if empty)
- **port** (integer, optional): MQTT broker port (default: 1883)
- **username** (string, optional): MQTT username (auto-detected if empty)
- **password** (string, optional): MQTT password (auto-detected if empty)
- **discovery** (boolean, optional): Enable MQTT discovery for Home Assistant (default: true)

## ESP32 BLE Proxy Setup

Your ESP32 BLE proxy should be configured to publish BLE advertisements to MQTT. The add-on subscribes to these standard topic patterns:

- `esphome/+/ble_advertise`
- `ble_proxy/+/advertisement`
- `esp32_ble_proxy/+/data`
- And many other patterns for maximum compatibility

## Supported Device Types

The add-on automatically classifies smart bed devices from these manufacturers:

- **Richmat**: RTS remote bed bases
- **Linak**: DeskLine and medical beds  
- **Solace**: Solace smart beds
- **MotoSleep**: MotoSleep adjustable beds
- **Reverie**: Reverie smart beds
- **Keeson**: Member's Mark, Purple, ErgoMotion beds
- **Octo**: Octo smart bed systems

## Web Interface

Access the web UI at: `http://homeassistant.local:8099`

Features:
- Real-time device discovery monitoring
- Device classification and details
- MQTT connection status
- Manual device management
- Diagnostic tools

## MQTT Topics

### Subscribed Topics (Input)
The add-on listens for BLE advertisements on these patterns:
- `esphome/+/ble_advertise`
- `ble_proxy/+/advertisement`
- `smartbed/+/ble_advertise`
- And many other patterns

### Published Topics (Output)
When discovery is enabled:
- `ble_scanner/discovered/{mac}`: Device discovery notifications
- `ble_scanner/status`: Scanner status updates

## Troubleshooting

### Add-on won't start
1. Check the add-on logs for error messages
2. Verify your configuration syntax
3. Ensure ESP32 proxy is reachable

### No devices discovered
1. Verify ESP32 BLE proxy is running and scanning
2. Check MQTT broker connectivity
3. Confirm ESP32 is publishing to correct MQTT topics
4. Use the web UI diagnostic tools

### MQTT connection issues
1. Check MQTT broker is running (usually Mosquitto add-on)
2. Verify network connectivity
3. Check MQTT credentials if required
4. Use auto-detection by leaving MQTT fields empty

## API Endpoints

The add-on provides a REST API:

- `GET /api/status`: Get add-on status
- `GET /api/devices`: Get discovered devices
- `POST /api/scan/start`: Start scanning
- `POST /api/scan/stop`: Stop scanning
- `POST /api/devices/clear`: Clear all devices
- `GET /api/diagnostic`: Get diagnostic information

## Security

This add-on follows Home Assistant security best practices:

- Host network access for MQTT communication
- No unnecessary privileges
- Secure MQTT auto-detection
- Standard Home Assistant configuration patterns

## Support

For issues and support:
1. Check the add-on logs first
2. Review this documentation  
3. Open an issue on the GitHub repository
4. Join the Home Assistant community forums

## License

This add-on is licensed under the MIT License. 