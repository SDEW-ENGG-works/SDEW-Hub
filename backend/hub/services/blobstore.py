"""Vercel Blob: where the WEBSITE keeps its backups (a Vercel function has no disk that lasts).

Turned on when a Blob store is connected to the project (Vercel > Storage > Create > Blob, private):
Vercel adds BLOB_STORE_ID (the website then signs in with its OIDC token) or, for older stores,
BLOB_READ_WRITE_TOKEN. Put the same token in the PC's .env
and the PC's backups are copied to Blob too.
Backups are stored as  backups/sdew_hub_<date>_<time>_<reason>.zip  in a PRIVATE store (nobody can open
them without the token).
"""
import os

from .. import config

PREFIX = "backups/"


def _token():
    t = (os.environ.get("BLOB_READ_WRITE_TOKEN") or os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN")
         or config.read_env().get("BLOB_READ_WRITE_TOKEN") or "").strip()
    if t and not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        os.environ["BLOB_READ_WRITE_TOKEN"] = t          # the SDK reads it from the environment
    return t


def access():
    return "public" if (config.read_env().get("BLOB_ACCESS") or os.environ.get("BLOB_ACCESS") or "").lower() == "public" \
        else "private"


def _store_id():
    """New Vercel Blob stores connect with BLOB_STORE_ID + the function's OIDC token (no token env)."""
    return (os.environ.get("BLOB_STORE_ID") or "").strip()


def _oidc_ok():
    return bool(_store_id()) and (config.ON_VERCEL or bool(os.environ.get("VERCEL_OIDC_TOKEN")))


def enabled():
    if not _token() and not _oidc_ok():
        return False
    try:
        import vercel.blob.sync  # noqa: F401
        return True
    except ImportError:
        return False


def why_not():
    if not _token() and not _oidc_ok():
        return "No Blob store connected (BLOB_STORE_ID or BLOB_READ_WRITE_TOKEN is not set)"
    try:
        import vercel.blob.sync  # noqa: F401
    except ImportError:
        return "The vercel-blob package is not installed (pip install vercel-blob)"
    return ""


def _sdk():
    _token()
    from vercel.blob import sync as blob
    return blob


def put(name, data):
    """-> pathname stored"""
    r = _sdk().put_blob(PREFIX + name, data, access=access(), content_type="application/zip",
                        allow_overwrite=True)
    return r.pathname


def get(name):
    return bytes(_sdk().get_blob(PREFIX + os.path.basename(name), access=access()).body)


def names():
    """{file name: size} of every backup in the store."""
    out = {}
    for b in _sdk().query_blobs(prefix=PREFIX):
        out[b.pathname[len(PREFIX):]] = b.size
    return out


def delete(names_):
    names_ = [PREFIX + os.path.basename(n) for n in names_]
    for i in range(0, len(names_), 500):
        _sdk().delete_blob(names_[i:i + 500])
