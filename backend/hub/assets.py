"""Cache-busting for the pages' css/js files (and images in assets/).

Each index.html (hub page and the three module pages) loads every file with a version tag, e.g.
    <script defer src="js/main.js?v=3f9a1c2e"></script>
The tag is a fingerprint of the file's contents, so browsers fetch a file again exactly when it changed.
"""
import hashlib
import os

import re

from . import config

_TAG = re.compile(r'((?:href|src)="(/?(?:css|js|assets)/[^"?]+))(?:\?v=[^"]*)?"')
PAGES = ("", "supp", "chep", "dqms", "grin", "pay", "admin")


def fingerprint(base, rel_path):
    root = config.FRONTEND_DIR if rel_path.startswith("/") else base
    try:
        with open(os.path.join(root, rel_path.lstrip("/")), "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:10]
    except OSError:
        return "missing"


def stamp_html(html, base=None):
    base = base or config.FRONTEND_DIR
    return _TAG.sub(lambda m: f'{m.group(1)}?v={fingerprint(base, m.group(2))}"', html)


def page_dir(page):
    return os.path.join(config.FRONTEND_DIR, page) if page else config.FRONTEND_DIR


def stamp_index_files():
    """Updates the tags in every index.html. Returns how many changed."""
    n = 0
    for page in PAGES:
        path = os.path.join(page_dir(page), "index.html")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                html = fh.read()
        except OSError:
            continue
        new = stamp_html(html, page_dir(page))
        if new != html:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
            n += 1
    return n


def index_page(path):
    """'/' -> hub page, '/supp/' -> Supplementary Bill page ... -> (html, base dir) or None."""
    p = path.split("?")[0]
    for page in PAGES:
        prefix = f"/{page}/" if page else "/"
        if p in (prefix, prefix + "index.html") or (page and p == f"/{page}"):
            with open(os.path.join(page_dir(page), "index.html"), "r", encoding="utf-8") as fh:
                return stamp_html(fh.read(), page_dir(page)), page
    return None
