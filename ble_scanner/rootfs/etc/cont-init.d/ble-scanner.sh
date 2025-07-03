#!/usr/bin/with-contenv bashio

# Initialize BLE scanner
bashio::log.info "Initializing BLE Scanner addon..."

# Create data directory
mkdir -p /data

# Set permissions
chown -R root:root /data
chmod -R 755 /data

# BLE scanner service will be started by s6-rc
bashio::log.info "BLE Scanner addon initialized successfully." 