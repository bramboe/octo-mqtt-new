# Home Assistant Add-on: BLE Scanner

A robust BLE device scanner that follows [smartbed-mqtt](https://github.com/richardhopton/smartbed-mqtt) patterns for reliable MQTT integration with Home Assistant.

## Installation

1. Add this repository to your Home Assistant add-ons
2. Install the "BLE Scanner" add-on
3. Configure your MQTT settings (auto-detection available)
4. Configure your ESP32 BLE proxy settings
5. Start the add-on

## Configuration

### MQTT Settings

```yaml
mqtt:
  host: "<auto_detect>"
  port: 1883
  username: "<auto_detect>"
  password: "<auto_detect>"
  discovery: true
```

- **host**: MQTT broker hostname (use `<auto_detect>` for Home Assistant integration)
- **port**: MQTT broker port (default: 1883)
- **username**: MQTT username (use `<auto_detect>` for automatic detection) 
- **password**: MQTT password (use `<auto_detect>` for automatic detection)
- **discovery**: Enable MQTT device discovery (default: true)

The add-on automatically detects Home Assistant's MQTT broker configuration using supervisor API calls, similar to smartbed-mqtt. It tries multiple connection methods:

1. Home Assistant supervisor MQTT addon detection
2. Core-mosquitto addon
3. Standard MQTT broker discovery
4. Multiple fallback hosts (homeassistant.local, localhost, etc.)

### BLE Proxy Configuration

```yaml
bleProxies:
  - host: "192.168.1.109"
    port: 6053
    password: ""
```

- **host**: IP address of your ESP32 BLE proxy
- **port**: Port number (usually 6053)
- **password**: Password for ESP32 connection (if required)

## Usage

1. **Access the Web Interface**: The addon provides a web interface accessible through Home Assistant's sidebar
2. **Start Scanning**: Click "Start Scan" to begin listening for BLE advertisements via MQTT
3. **View Devices**: Discovered BLE devices will appear in real-time
4. **Device Management**: Add, remove, and classify devices through the interface

## MQTT Topics

The add-on subscribes to these MQTT topics for BLE advertisements:

- `esphome/+/ble_advertise`
- `esphome/+/ble_advertise/+` 
- `esphome/+/ble_advertise/#`
- `ble_proxy/+/advertisement`
- `esp32_ble_proxy/+/data`
- `smartbed/+/ble_advertise`

## Device Classification

Automatically classifies devices by manufacturer:

- **Richmat Gen2**: Richmat/Leggett & Platt Gen2 devices
- **Linak**: Linak bed controllers
- **Solace**: Solace bed controllers  
- **MotoSleep**: MotoSleep bed controllers
- **Reverie**: Reverie bed controllers
- **Keeson**: Keeson bed controllers
- **Octo**: Octo bed controllers
- **Generic BLE**: Standard BLE devices

## Troubleshooting

### No Devices Discovered

1. Check MQTT connection status in the web interface
2. Verify ESP32 BLE proxy is publishing to correct MQTT topics
3. Ensure MQTT broker is accessible
4. Start scanning if not already active

### MQTT Connection Issues

1. Try auto-detection by setting host to `<auto_detect>`
2. Manually configure MQTT broker details
3. Check network connectivity between addon and MQTT broker
4. Verify MQTT credentials

## MQTT Device Discovery

Following smartbed-mqtt patterns, discovered BLE devices are automatically created in Home Assistant with:

- **Binary Sensor**: Device presence/connectivity status
- **Sensor**: RSSI signal strength (dBm)  
- **Sensor**: Last seen timestamp
- **Device Attributes**: MAC address, source proxy, discovery info

Each device appears in Home Assistant with proper device registry entries and can be used in automations.

## Support

This add-on follows the proven patterns from [smartbed-mqtt](https://github.com/richardhopton/smartbed-mqtt), a mature BLE integration project. For additional help:

- Check the [smartbed-mqtt documentation](https://github.com/richardhopton/smartbed-mqtt) for similar BLE setup patterns
- Join the Discord server at <https://discord.gg/Hf3kpFjbZs> for community support
- Create an issue in this repository for specific problems 