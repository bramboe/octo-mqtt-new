#!/usr/bin/with-contenv bashio

# ==============================================================================
# Home Assistant BLE Scanner Add-on
# MQTT-based BLE scanner compatible with smartbed-mqtt
# ==============================================================================

bashio::log.info "Starting BLE Scanner Add-on v1.0.54..."

# Check if the user configuration exists
if bashio::fs.file_exists '/data/options.json'; then
    bashio::log.info "Configuration found, starting BLE Scanner..."
else
    bashio::log.error "No configuration found!"
    exit 1
fi

# Start the Python application with Gunicorn
cd /opt/ble_scanner || exit 1
exec gunicorn --config gunicorn.conf.py main:app 