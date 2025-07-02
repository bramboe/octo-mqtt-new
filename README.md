# BLE Scanner - Home Assistant Addon

A standalone Home Assistant addon that scans for Bluetooth Low Energy (BLE) devices using ESP32 BLE proxies. This addon provides a modern web UI for discovering, managing, and monitoring BLE devices without requiring integration with your main Home Assistant instance.

## Features

- 🔍 **BLE Device Discovery**: Automatically scan for BLE devices using ESP32 proxies
- 🌐 **Modern Web UI**: Beautiful, responsive interface for device management
- 📱 **Real-time Updates**: Live device status and RSSI monitoring
- ➕ **Manual Device Addition**: Add devices manually by MAC address
- 💾 **Persistent Storage**: Devices are saved and restored between restarts
- 🔧 **Configurable**: Customize scan intervals and proxy settings
- 📊 **Device Analytics**: View RSSI, manufacturer data, and service information

## Prerequisites

### ESP32 BLE Proxy Setup

Before using this addon, you need to set up ESP32 devices as BLE proxies. Follow these steps:

1. **Flash ESP32 with ESPHome**:
   ```yaml
   # Example ESPHome configuration for BLE proxy
   esphome:
     name: my-ble-proxy
     platform: ESP32
     board: esp32dev
     framework:
       type: esp-idf

   # Enable BLE tracker
   esp32_ble_tracker:
     scan_parameters:
       interval: 1100ms
       window: 1100ms
       active: true

   # Enable Bluetooth proxy
   bluetooth_proxy:
     active: true
     connection_slots: 3

   # Enable API for communication
   api:
     port: 6053

   # Optional: Use Ethernet for better performance
   ethernet:
     type: LAN8720
     mdc_pin: GPIO23
     mdio_pin: GPIO18
     clk_mode: GPIO17_OUT
     phy_addr: 0
     power_pin: GPIO12
   ```

2. **Network Configuration**: Ensure your ESP32 proxies are accessible on your network

## Installation

### Method 1: Manual Installation

1. **Clone or download this repository** to your Home Assistant addons directory:
   ```bash
   cd /opt/addons
   git clone <repository-url> ble-scanner
   ```

2. **Build the addon**:
   ```bash
   cd ble-scanner
   docker build -t ble-scanner .
   ```

3. **Add to Home Assistant**:
   - Go to Settings → Add-ons → Add-on Store
   - Click the three dots menu → Repositories
   - Add your local path: `/opt/addons/ble-scanner`

### Method 2: Using Home Assistant Builder

1. **Set up the builder** (if not already done):
   ```bash
   docker run --rm -v "$(pwd)":/data ghcr.io/hassio-addons/builder:latest --target ble-scanner --all
   ```

2. **Build the addon**:
   ```bash
   ./build.sh
   ```

## Configuration

### Basic Configuration

Configure the addon through the Home Assistant addon interface:

```yaml
esp32_proxies:
  - name: "Living Room Proxy"
    host: "192.168.1.100"
    port: 6053
  - name: "Bedroom Proxy"
    host: "192.168.1.101"
    port: 6053

scan_interval: 30  # seconds
log_level: info    # debug, info, warning, error
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `esp32_proxies` | list | `[]` | List of ESP32 BLE proxy configurations |
| `esp32_proxies[].name` | string | - | Friendly name for the proxy |
| `esp32_proxies[].host` | string | - | IP address of the ESP32 proxy |
| `esp32_proxies[].port` | integer | `6053` | WebSocket port of the ESP32 proxy |
| `scan_interval` | integer | `30` | Interval between scan attempts (seconds) |
| `log_level` | string | `info` | Logging level |

## Usage

### Web Interface

1. **Access the UI**: Navigate to the addon in Home Assistant and click "Open Web UI"
2. **Start Scanning**: Click "Start Scan" to begin discovering BLE devices
3. **View Devices**: Discovered devices will appear in the list with their details
4. **Add Manually**: Use the form to add devices manually by MAC address
5. **Monitor Status**: View real-time scan status and device counts

### API Endpoints

The addon provides a REST API for integration:

- `GET /api/devices` - Get all discovered devices
- `POST /api/devices/{mac_address}` - Add a device manually
- `DELETE /api/devices/{mac_address}` - Remove a device
- `POST /api/scan/start` - Start scanning
- `POST /api/scan/stop` - Stop scanning
- `GET /api/status` - Get addon status

### Device Information

Each discovered device includes:

- **MAC Address**: Unique device identifier
- **Name**: Device name (if available)
- **RSSI**: Signal strength indicator
- **Manufacturer**: Manufacturer data
- **Services**: Available BLE services
- **Last Seen**: Timestamp of last detection
- **Proxy**: Which ESP32 proxy discovered the device

## Troubleshooting

### Common Issues

1. **No devices discovered**:
   - Check ESP32 proxy connectivity
   - Verify network connectivity
   - Ensure BLE devices are in range
   - Check ESP32 proxy configuration

2. **Connection errors**:
   - Verify ESP32 proxy IP addresses
   - Check firewall settings
   - Ensure ESP32 proxies are running

3. **Web UI not loading**:
   - Check addon logs
   - Verify port 8099 is accessible
   - Restart the addon

### Logs

View addon logs in Home Assistant:
- Go to the addon page
- Click "Logs" tab
- Look for error messages or connection issues

### Debug Mode

Enable debug logging by setting `log_level: debug` in the configuration.

## Development

### Local Development

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd ble-scanner
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run locally**:
   ```bash
   python main.py
   ```

### Building

```bash
# Build for all architectures
docker run --rm -v "$(pwd)":/data ghcr.io/hassio-addons/builder:latest --target ble-scanner --all

# Build for specific architecture
docker run --rm -v "$(pwd)":/data ghcr.io/hassio-addons/builder:latest --target ble-scanner --aarch64
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For support and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the logs for error messages

## Changelog

### Version 1.0.0
- Initial release
- BLE device discovery via ESP32 proxies
- Modern web UI
- Manual device management
- Persistent storage
- REST API 