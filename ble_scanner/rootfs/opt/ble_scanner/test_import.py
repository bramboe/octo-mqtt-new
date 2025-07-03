#!/usr/bin/env python3
"""
Test script to verify module import in container
"""

import sys
import os

print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")
print(f"Python path: {sys.path}")

try:
    import main
    print("✓ Successfully imported main module")
    
    if hasattr(main, 'app'):
        print("✓ Flask app found")
        print(f"  App type: {type(main.app)}")
    else:
        print("✗ Flask app not found")
        
except ImportError as e:
    print(f"✗ Import error: {e}")
    print(f"Available files in current directory: {os.listdir('.')}")
except Exception as e:
    print(f"✗ Unexpected error: {e}") 