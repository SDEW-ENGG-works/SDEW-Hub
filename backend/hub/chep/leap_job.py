"""Entry point inside the Vercel Sandbox:  python -m hub.chep.leap_job <job id>"""
import sys

from .services.leap_cloud import run_job

if __name__ == "__main__":
    sys.exit(run_job(int(sys.argv[1])))
