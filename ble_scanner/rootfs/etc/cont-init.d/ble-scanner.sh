#!/usr/bin/with-contenv bashio

# Initialize BLE scanner
bashio::log.info "Initializing BLE Scanner addon..."

# Create data directory
mkdir -p /data/ble_devices

# Set permissions
chown -R root:root /data/ble_devices
chmod -R 755 /data/ble_devices

# Start the BLE scanner service with Gunicorn
bashio::log.info "Starting BLE Scanner service..."
exec s6-setuidgid root gunicorn -c /opt/ble_scanner/gunicorn.conf.py main:app 