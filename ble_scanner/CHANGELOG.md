# Changelog

All notable changes to this project will be documented in this file.

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