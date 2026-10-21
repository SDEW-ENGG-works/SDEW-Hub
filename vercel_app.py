"""Vercel entrypoint (see pyproject.toml [tool.vercel]). On the PC use server.py instead."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from hub.wsgi import app  # noqa: E402,F401
