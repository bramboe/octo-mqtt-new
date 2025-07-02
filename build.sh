#!/bin/bash

# BLE Scanner Addon Build Script
# This script builds the Home Assistant addon for all supported architectures

set -e

echo "🚀 Building BLE Scanner Addon..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Build for all architectures
echo "📦 Building for all architectures..."
docker run --rm -v "$(pwd)":/data ghcr.io/hassio-addons/builder:latest --target ble-scanner --all

echo "✅ Build completed successfully!"
echo ""
echo "📋 Next steps:"
echo "1. Copy the built images to your Home Assistant addons directory"
echo "2. Add the addon to Home Assistant via Settings → Add-ons → Add-on Store"
echo "3. Configure your ESP32 BLE proxies"
echo "4. Start the addon and access the web UI"
echo ""
echo "📖 For more information, see the README.md file" 