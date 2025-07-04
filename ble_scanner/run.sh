#!/usr/bin/with-contenv bashio

# ==============================================================================
# Home Assistant BLE Scanner Add-on
# MQTT-based BLE scanner compatible with smartbed-mqtt
# ==============================================================================

bashio::log.info "Starting BLE Scanner Add-on v1.0.59..."

# Check if the user configuration exists
if bashio::fs.file_exists '/data/options.json'; then
    bashio::log.info "Configuration found, starting BLE Scanner..."
else
    bashio::log.error "No configuration found!"
    exit 1
fi

# DEBUGGING: Start Flask directly (bypassing Gunicorn to debug segfault)
cd /opt/ble_scanner || exit 1
bashio::log.info "Running Flask directly to isolate segfault..."
exec python3 main.py 