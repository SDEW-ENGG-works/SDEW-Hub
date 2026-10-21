"""Run the hub:  python server.py   ->  http://localhost:8050"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from hub.local_server import run_server  # noqa: E402

if __name__ == "__main__":
    run_server()
