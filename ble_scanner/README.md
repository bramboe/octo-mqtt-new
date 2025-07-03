# BLE Scanner Add-on for Home Assistant

A standalone BLE scanner add-on for Home Assistant that uses ESP32 BLE proxies to discover and manage Bluetooth Low Energy devices. Provides a web UI for device management and MQTT integration for Home Assistant automation.

## Features

- **ESP32 BLE Proxy Integration**: Connect to ESP32 devices running ESPHome BLE proxy firmware
- **Web UI**: Modern web interface for device discovery and management
- **MQTT Integration**: Automatic MQTT broker detection and credential management
- **Device Management**: Add, remove, and track BLE devices
- **Real-time Scanning**: Continuous BLE device discovery
- **Home Assistant Compatible**: Runs as a standalone add-on on Home Assistant OS

## Version 1.0.27

### Recent Fixes
- ✅ Fixed ESP32 proxy connection using proper APIConnection parameters
- ✅ Improved MQTT credential auto-detection
- ✅ Enhanced error logging and debugging
- ✅ Updated to use asyncio-mqtt for reliable MQTT connections
- ✅ Production-ready with Gunicorn WSGI server

## Installation

1. **Add this repository to Home Assistant**:
   ```
   https://github.com/yourusername/ble_scanner
   ```

2. **Install the BLE Scanner add-on** from the Add-on Store

3. **Configure ESP32 proxies** in the add-on configuration:
   ```yaml
   esp32_proxies:
     - host: "192.168.1.109"
       port: 6053
       password: ""
   ```

4. **Configure MQTT** (optional):
   ```yaml
   mqtt_host: "<auto_detect>"
   mqtt_port: 1883
   mqtt_username: ""
   mqtt_password: ""
   mqtt_discovery: false
   ```

## ESP32 BLE Proxy Setup

Your ESP32 devices need to be running ESPHome firmware with BLE proxy enabled. Example configuration:

```yaml
esp32_ble_proxy:
  active: true
  on_ble_advertise:
    - then:
        - logger.log: "BLE Advertisement: {{ packet }}"
```

## Usage

1. **Access the Web UI** at `http://your-ha-ip:8099`
2. **Start scanning** to discover BLE devices
3. **Add devices** to your tracking list
4. **Monitor devices** in real-time
5. **MQTT integration** automatically publishes device data

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `esp32_proxies` | `[]` | List of ESP32 BLE proxy devices |
| `mqtt_host` | `<auto_detect>` | MQTT broker hostname |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_username` | `""` | MQTT username |
| `mqtt_password` | `""` | MQTT password |
| `mqtt_discovery` | `false` | Enable Home Assistant MQTT discovery |

## MQTT Topics

When MQTT is enabled, the add-on publishes to:
- `ble_scanner/data` - Device advertisement data
- `ble_scanner/status` - Add-on status information

## Troubleshooting

### ESP32 Proxy Connection Issues
- Ensure ESP32 is running ESPHome firmware with BLE proxy enabled
- Check network connectivity to ESP32 IP address
- Verify port 6053 is accessible
- Check ESP32 logs for connection errors

### MQTT Connection Issues
- The add-on auto-detects MQTT broker and credentials
- Check Home Assistant MQTT add-on configuration
- Verify MQTT broker is running and accessible
- Check add-on logs for MQTT connection errors

### Web UI Issues
- Ensure port 8099 is not blocked by firewall
- Check add-on logs for Flask/Gunicorn errors
- Verify add-on is running and healthy

## Development

### Building Locally
```bash
./build.sh
```

### Testing
```bash
python3 test_addon.py
```

## License

This project is licensed under the MIT License.

## Support

For issues and feature requests, please create an issue on GitHub. 