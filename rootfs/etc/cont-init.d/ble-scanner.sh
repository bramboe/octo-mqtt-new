#!/usr/bin/with-contenv bashio

# Initialize BLE scanner
bashio::log.info "Initializing BLE Scanner addon..."

# Create data directory
mkdir -p /data/ble_devices

# Set permissions
chown -R root:root /data/ble_devices
chmod -R 755 /data/ble_devices

# Start the BLE scanner service
bashio::log.info "Starting BLE Scanner service..."
exec s6-setuidgid root python3 /opt/ble_scanner/main.py 