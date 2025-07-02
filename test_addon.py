#!/usr/bin/env python3
"""
Test script for BLE Scanner Addon
This script tests the API endpoints and basic functionality
"""

import requests
import json
import time
import sys

class BLEScannerTester:
    def __init__(self, base_url="http://localhost:8099"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def test_status(self):
        """Test the status endpoint"""
        print("🔍 Testing status endpoint...")
        try:
            response = self.session.get(f"{self.base_url}/api/status")
            if response.status_code == 200:
                status = response.json()
                print(f"✅ Status: {status}")
                return True
            else:
                print(f"❌ Status failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Status error: {e}")
            return False
    
    def test_devices(self):
        """Test the devices endpoint"""
        print("📱 Testing devices endpoint...")
        try:
            response = self.session.get(f"{self.base_url}/api/devices")
            if response.status_code == 200:
                devices = response.json()
                print(f"✅ Devices: {len(devices)} found")
                return True
            else:
                print(f"❌ Devices failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Devices error: {e}")
            return False
    
    def test_add_device(self):
        """Test adding a device manually"""
        print("➕ Testing manual device addition...")
        test_device = {
            "name": "Test Device",
            "rssi": -60,
            "manufacturer": "Test Manufacturer",
            "services": ["1800", "1801"]
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/devices/AA:BB:CC:DD:EE:FF",
                json=test_device,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code == 200:
                device = response.json()
                print(f"✅ Device added: {device['mac_address']}")
                return True
            else:
                print(f"❌ Add device failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Add device error: {e}")
            return False
    
    def test_scan_control(self):
        """Test scan start/stop functionality"""
        print("🎯 Testing scan control...")
        
        # Test start scan
        try:
            response = self.session.post(f"{self.base_url}/api/scan/start")
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Start scan: {result['message']}")
            else:
                print(f"❌ Start scan failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Start scan error: {e}")
            return False
        
        # Wait a moment
        time.sleep(2)
        
        # Test stop scan
        try:
            response = self.session.post(f"{self.base_url}/api/scan/stop")
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Stop scan: {result['message']}")
                return True
            else:
                print(f"❌ Stop scan failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Stop scan error: {e}")
            return False
    
    def test_web_ui(self):
        """Test web UI accessibility"""
        print("🌐 Testing web UI...")
        try:
            response = self.session.get(f"{self.base_url}/")
            if response.status_code == 200:
                print("✅ Web UI accessible")
                return True
            else:
                print(f"❌ Web UI failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Web UI error: {e}")
            return False
    
    def run_all_tests(self):
        """Run all tests"""
        print("🚀 Starting BLE Scanner Addon Tests")
        print("=" * 50)
        
        tests = [
            ("Web UI", self.test_web_ui),
            ("Status", self.test_status),
            ("Devices", self.test_devices),
            ("Add Device", self.test_add_device),
            ("Scan Control", self.test_scan_control),
        ]
        
        passed = 0
        total = len(tests)
        
        for test_name, test_func in tests:
            print(f"\n📋 Running {test_name} test...")
            if test_func():
                passed += 1
            print("-" * 30)
        
        print(f"\n📊 Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! The addon is working correctly.")
            return True
        else:
            print("⚠️  Some tests failed. Check the addon configuration and logs.")
            return False

def main():
    """Main test function"""
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = "http://localhost:8099"
    
    tester = BLEScannerTester(base_url)
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 