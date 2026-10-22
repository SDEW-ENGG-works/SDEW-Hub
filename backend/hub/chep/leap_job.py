"""Entry point inside the Vercel Sandbox:  python -m hub.chep.leap_job <job id>"""
import sys

from .services.leap_cloud import main

if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))
