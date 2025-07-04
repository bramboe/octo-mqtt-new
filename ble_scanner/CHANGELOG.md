# Changelog

All notable changes to this project will be documented in this file.

## [1.0.49] - 2025-07-04

### Added
- Ingress support for secure web interface access
- AppArmor security profile for enhanced security
- Ingress-only access control (172.30.32.2)
- Gunicorn production server deployment
- Panel icon for Home Assistant sidebar

### Changed
- Removed host_network and privileged settings
- Improved security rating from 3 to 7
- Web interface now accessible via Home Assistant ingress
- Production deployment with Gunicorn instead of Flask dev server

### Security
- Added ingress security (+2 points)
- Added custom AppArmor profile (+1 point)
- Removed host_network (-1 point removed)
- Removed privileged settings (-1 point removed)
- Total security rating: 7/6

## [1.0.48] - 2025-07-04

### Added
- Pure MQTT approach following smartbed-mqtt pattern
- Compatibility with ESP32 BLE proxies via MQTT
- Device classification for smart bed manufacturers (Richmat, Linak, Solace, MotoSleep, Reverie, Keeson, Octo)
- Auto-detection of MQTT broker and credentials
- Web UI for device management and status monitoring
- Real-time BLE device discovery via MQTT
- Support for multiple MQTT topic patterns
- Device persistence across restarts

### Changed
- Removed direct ESP32 API connections (aioesphomeapi)
- Simplified to MQTT-only communication
- Updated configuration structure with nested MQTT options
- Improved Docker base image configuration
- Enhanced security with proper Home Assistant add-on standards

### Fixed
- Configuration loading from /data/options.json
- Dockerfile compliance with Home Assistant standards
- Removed unnecessary s6-overlay complexity
- Fixed syntax errors in main application
- Proper run.sh script for container startup

### Removed
- Direct ESP32 BLE proxy connections
- Complex s6-overlay service management
- Unused dependencies and imports 