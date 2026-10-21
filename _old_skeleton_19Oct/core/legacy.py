"""Run the copied apps (legacy/<folder>) side by side with the hub."""
import os
import socket
import subprocess
import sys
from . import config

_procs = {}


def is_up(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def status():
    out = []
    for app in config.LEGACY_APPS:
        folder = config.LEGACY / app["folder"]
        out.append({
            "key": app["key"], "name": app["name"], "port": app["port"],
            "copied": (folder / "server.py").exists(),
            "running": is_up(app["port"]),
            "started_by_hub": app["key"] in _procs and _procs[app["key"]].poll() is None,
            "url": f"http://localhost:{app['port']}",
        })
    return out


def start(key):
    app = config.LEGACY_BY_KEY[key]
    folder = config.LEGACY / app["folder"]
    if not (folder / "server.py").exists():
        return False, "Not copied yet. Run tools/setup_from_existing.py first."
    if is_up(app["port"]):
        return True, f"Already running on port {app['port']}."
    env = dict(os.environ, PORT=str(app["port"]))
    kwargs = {"cwd": str(folder), "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    _procs[key] = subprocess.Popen([sys.executable, "server.py"], **kwargs)
    return True, f"Starting {app['name']} on port {app['port']}."


def stop(key):
    p = _procs.get(key)
    if p and p.poll() is None:
        p.terminate()
        return True, "Stopped."
    return False, "This app was not started by the hub. Close its own window to stop it."


def stop_all():
    for p in _procs.values():
        if p.poll() is None:
            p.terminate()
