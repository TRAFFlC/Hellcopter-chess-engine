import os
import sys

os.environ["ENGINE_PARAMS"] = "E:/world/python/chess/configs/v1.7.0.json"
sys.path.insert(0, "E:/world/python/chess")

from uci_engine import UCIEngine

if __name__ == "__main__":
    uci = UCIEngine()
    uci.run()
