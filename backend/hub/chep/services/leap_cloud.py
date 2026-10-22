"""LEAP upload in a Vercel Sandbox - a small Linux machine with Chromium that the website starts
on demand - so the upload works with no PC switched on.

  website  launch(job_id)   start (or wake up) the sandbox "sdew-leap", copy this program into it
                            and start  python -m hub.chep.leap_job <job_id>  in the background.
  sandbox  run_job(job_id)  the same Playwright code as on the PC (leap.py): it claims the job,
                            copies every step into leap_jobs, waits for the Submit pressed on the
                            website, then checks the report - exactly like the PC agent.

The first run installs Python packages and Chromium (about 3 minutes); the sandbox is persistent,
so later runs start from the saved disk in seconds.

Vercel settings: nothing extra on Pro - the website uses its own OIDC token (header
x-vercel-oidc-token). Otherwise set VERCEL_TOKEN, VERCEL_TEAM_ID and VERCEL_PROJECT_ID.
LEAP_USER / LEAP_PASS must be Vercel environment variables (they are passed to the sandbox
process only, never written to its disk). LEAP_RUNNER = auto (default: the PC when it is
online, else the sandbox) | cloud | pc.
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import time
import traceback
from datetime import timedelta

from .. import config

SANDBOX_NAME = os.environ.get("LEAP_SANDBOX_NAME") or "sdew-leap"
WORKDIR = "/vercel/sandbox"
PASS_ENV = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "CHEP_TURSO_DATABASE_URL", "CHEP_TURSO_AUTH_TOKEN",
            "LEAP_USER", "LEAP_PASS", "LEAP_URL", "LEAP_VERIFY_GAP")

RUN_SH = r"""#!/bin/bash
# started by the website: unpack the code, make sure python3 exists, then hand over to Python
# (Python does the one-time install of Playwright + Chromium and reports every step to the website)
cd /vercel/sandbox
rm -rf pkg && mkdir -p pkg data && tar xzf hub.tgz -C pkg
if ! command -v python3 >/dev/null; then
  (sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv) || sudo dnf install -y -q python3
fi
cd pkg
exec python3 -u -m hub.chep.leap_job "$1" >> /vercel/sandbox/job.log 2>&1
"""


# ---------------------------------------------------------------- website side
def credentials_ok():
    if os.environ.get("VERCEL_OIDC_TOKEN"):
        return True
    return all(os.environ.get(k) for k in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"))


def usable():
    """(ok, why) - can this website start the cloud browser?"""
    if not config.ON_VERCEL:
        return False, "only on the website"
    try:
        import vercel.sandbox  # noqa: F401
    except ImportError:
        return False, "the vercel-sandbox package is not installed (requirements.txt)"
    env = config.read_env()
    if not env.get("LEAP_USER") or not env.get("LEAP_PASS"):
        return False, "LEAP_USER / LEAP_PASS are not set in Vercel's environment variables"
    if not credentials_ok():
        return False, "no Vercel credentials (OIDC token, or VERCEL_TOKEN + VERCEL_TEAM_ID + VERCEL_PROJECT_ID)"
    return True, ""


def _hub_tarball():
    """This program's hub package (code only) as .tar.gz."""
    hub_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def skip(ti):
            name = os.path.basename(ti.name)
            return None if name == "__pycache__" or name.endswith(".pyc") else ti
        tar.add(hub_dir, arcname="hub", filter=skip)
    return buf.getvalue()


def launch(job_id):
    """Start the sandbox job. Raises RuntimeError with a readable reason."""
    ok, why = usable()
    if not ok:
        raise RuntimeError(f"The cloud browser can't start: {why}.")
    from vercel.sandbox import sync as vsb
    env = config.read_env()
    penv = {k: env.get(k) or os.environ.get(k) for k in PASS_ENV}
    penv = {k: v for k, v in penv.items() if v}
    penv.update(USE_CLOUD_DB="1", HUB_DATA_DIR=WORKDIR + "/data", PYTHONUNBUFFERED="1", HUB_FORCE_IST="1",
                LEAP_SANDBOX="1")
    try:
        box, _created = vsb.get_or_create_sandbox(name=SANDBOX_NAME, persistent=True,
                                                  execution_time_limit=timedelta(minutes=50))
        try:
            box.extend_execution_time_limit(timedelta(minutes=45))
        except Exception:  # noqa: BLE001 - a fresh sandbox already has its 50 minutes
            pass
        box.fs.write_bytes(WORKDIR + "/run.sh", RUN_SH.encode(), mode=0o755)
        box.fs.write_bytes(WORKDIR + "/hub.tgz", _hub_tarball())
        box.create_process("bash", [WORKDIR + "/run.sh", str(int(job_id))], cwd=WORKDIR, env=penv,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        raise RuntimeError(f"The cloud browser could not be started: {e}")


# ---------------------------------------------------------------- sandbox side
VENV = WORKDIR + "/venv"
READY = WORKDIR + "/.ready"


def _setup_state(job_id, steps, error=None):
    from ..db import get_db
    st = dict(active=error is None, phase="error" if error else "running", runner="cloud", steps=steps,
              log=[], parts=[], current=None, verify=None)
    if error:
        st["error"] = error
    con = get_db()
    con.execute("UPDATE leap_jobs SET status=?, state=?, updated_ts=? WHERE id=?",
                ("error" if error else "starting",
                 json.dumps(dict(st, file_name=_file_name(job_id))), time.time(), job_id))
    con.commit()


def _file_name(job_id):
    from ..db import one
    j = one("SELECT state FROM leap_jobs WHERE id=?", (job_id,))
    try:
        return json.loads(j["state"] or "{}").get("file_name", "") if j else ""
    except ValueError:
        return ""


def _install(job_id):
    """One-time install (system Python): venv, Playwright, Chromium. Each step shows on the website."""
    plan = [
        ("venv", "Make a Python environment", [sys.executable, "-m", "venv", VENV]),
        ("pip", "Install Playwright", [VENV + "/bin/pip", "install", "-q", "playwright", "openpyxl", "xlrd"]),
        ("deps", "Install Chromium's system libraries",
         ["sudo", VENV + "/bin/python", "-m", "playwright", "install-deps", "chromium"]),
        ("chromium", "Download Chromium", [VENV + "/bin/python", "-m", "playwright", "install", "chromium"]),
    ]
    steps = [dict(key=k, label=l, status="todo", detail="") for k, l, _ in plan]
    steps.insert(0, dict(key="box", label="Start the cloud browser (Vercel)", status="done",
                         detail="First run - installing (about 3 minutes, only once)"))
    for i, (key, label, cmd) in enumerate(plan, start=1):
        steps[i]["status"] = "doing"
        _setup_state(job_id, steps)
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 and key == "venv":   # Debian/Ubuntu without python3-venv
            subprocess.run("sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv || "
                           "sudo dnf install -y -q python3-pip", shell=True)
            r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 and key == "deps":   # not Debian/Ubuntu: try the dnf package names
            r = subprocess.run("sudo dnf install -y -q nss nspr atk at-spi2-atk cups-libs libdrm libxkbcommon "
                               "libXcomposite libXdamage libXrandr libXfixes libXext libX11 libxcb mesa-libgbm "
                               "pango cairo alsa-lib", shell=True, capture_output=True, text=True)
        if r.returncode != 0:
            tail = ((r.stderr or "") + (r.stdout or "")).strip()[-600:]
            steps[i].update(status="error", detail=tail)
            _setup_state(job_id, steps, error=f"{label} failed: {tail[-300:]}")
            return False
        steps[i].update(status="done", detail=f"{int(time.time() - t0)} s")
    open(READY, "w").close()
    _setup_state(job_id, steps)
    return True


def main(job_id):
    """Entry point in the sandbox. System Python: install once, then restart in the venv."""
    if not os.environ.get("LEAP_IN_VENV"):
        if not os.path.exists(READY) and not _install(job_id):
            return 1
        os.environ["LEAP_IN_VENV"] = "1"
        os.execv(VENV + "/bin/python", [VENV + "/bin/python", "-u", "-m", "hub.chep.leap_job", str(job_id)])
    return run_job(job_id)


def run_job(job_id):
    """Runs inside the sandbox: claim the job, do it, mirror it to leap_jobs, exit."""
    from ..db import get_db, one
    from . import leap
    from .leap_remote import follow_job

    j = one("SELECT id, run_id, mode, headed, status FROM leap_jobs WHERE id=?", (job_id,))
    if not j:
        print(f"job {job_id} not found")
        return 1
    if j["status"] not in ("queued", "starting"):
        print(f"job {job_id} is {j['status']} - nothing to do")
        return 0
    con = get_db()
    con.execute("UPDATE leap_jobs SET status='running', updated_ts=? WHERE id=?", (time.time(), job_id))
    con.commit()
    try:
        leap.start(j["run_id"], j["mode"], False)   # headless: there is no screen in the sandbox
    except RuntimeError as e:
        con.execute("UPDATE leap_jobs SET status='error', state=?, updated_ts=? WHERE id=?",
                    (json.dumps(dict(active=False, phase="error", error=str(e), mode=j["mode"], steps=[],
                                     log=[f"Cloud browser: {e}"])), time.time(), job_id))
        con.commit()
        return 1
    leap._log("Running in the Vercel cloud browser (no PC needed)")
    follow_job(None, job_id)
    return 0
