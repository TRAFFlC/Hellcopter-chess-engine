"""Direct test of the uci_engine path with node_limit"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uci_engine import UCIEngine

# Create engine with book disabled
eng = UCIEngine()
eng._book_config['own_book'] = False

# Simulate UCI initialization
eng.cmd_uci()

# Set node limit
eng.cmd_setoption("name nodes value 1000")
print(f"[TEST] node_limit after setoption: {eng._node_limit}", flush=True)

# Set position
eng.cmd_position("startpos")

# Go with minimal time
import threading
import time

# Use a direct approach - call go with a very short time
eng.cmd_go("movetime 1000")

# Wait for search to finish
time.sleep(3)

# Check if bestmove was sent
print("[TEST] Done waiting", flush=True)
