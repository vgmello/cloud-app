"""Minimal Azure Blob client for Azurite, standard library only.

The shims that use this run inside the act container, where `pip install
azure-storage-blob` on every scenario would cost more than the Shared Key
signing it replaces. Only the handful of operations the deploy path needs are
implemented: create container, put blob, head blob, get blob, list blobs.

Azurite is addressed path-style (``/<account>/<container>/<blob>``), which is
why the canonicalized resource repeats the account name -- it is built as
``/<account>`` + the URL path, and the URL path already starts with the
account.
"""

import base64
import hashlib
import hmac
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Azurite's well-known development credentials. Public constants, not secrets:
# they are baked into the emulator and documented by Microsoft.
DEFAULT_ACCOUNT = "devstoreaccount1"
DEFAULT_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
)

API_VERSION = "2021-08-06"


class BlobError(Exception):
    pass


def _endpoint():
    return os.environ.get("AZURITE_BLOB_URL", "http://127.0.0.1:10000").rstrip("/")


def _account():
    return os.environ.get("AZURITE_ACCOUNT", DEFAULT_ACCOUNT)


def _key():
    return os.environ.get("AZURITE_KEY", DEFAULT_KEY)


def _canonicalized_headers(headers):
    ms = sorted((k.lower(), v) for k, v in headers.items() if k.lower().startswith("x-ms-"))
    return "".join(f"{k}:{v}\n" for k, v in ms)


def _canonicalized_resource(path, query):
    lines = [f"/{_account()}{path}"]
    for key in sorted(query):
        lines.append(f"{key.lower()}:{query[key]}")
    return "\n".join(lines)


def _sign(method, path, query, headers, content_length):
    # An empty Content-Length line means "no body" for x-ms-version 2015-02-21
    # and later; sending "0" there produces a signature mismatch.
    length = "" if not content_length else str(content_length)
    to_sign = "\n".join([
        method,
        "",                                   # Content-Encoding
        "",                                   # Content-Language
        length,                               # Content-Length
        "",                                   # Content-MD5
        headers.get("Content-Type", ""),      # Content-Type
        "",                                   # Date (we send x-ms-date instead)
        "",                                   # If-Modified-Since
        "",                                   # If-Match
        "",                                   # If-None-Match
        "",                                   # If-Unmodified-Since
        "",                                   # Range
    ]) + "\n" + _canonicalized_headers(headers) + _canonicalized_resource(path, query)
    digest = hmac.new(
        base64.b64decode(_key()), to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return f"SharedKey {_account()}:{base64.b64encode(digest).decode()}"


def _request(method, path, query=None, body=None, extra_headers=None):
    """Issue a signed request. Returns (status, body_bytes); 404 is not an error."""
    query = dict(query or {})
    headers = {
        "x-ms-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        "x-ms-version": API_VERSION,
    }
    headers.update(extra_headers or {})
    headers["Authorization"] = _sign(method, path, query, headers, len(body or b""))
    if body is not None:
        headers["Content-Length"] = str(len(body))

    url = _endpoint() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except OSError as exc:
        raise BlobError(f"azurite unreachable at {_endpoint()}: {exc}") from exc


def _path(container, blob=None):
    path = f"/{_account()}/{container}"
    if blob:
        path += "/" + "/".join(urllib.parse.quote(part, safe="") for part in blob.split("/"))
    return path


def create_container(container):
    """Create the container; already-existing is success."""
    status, body = _request("PUT", _path(container), query={"restype": "container"})
    if status in (201, 409):
        return
    raise BlobError(f"create container {container} failed ({status}): {body[:300]!r}")


def container_exists(container):
    status, _ = _request(
        "GET", _path(container), query={"restype": "container", "comp": "list"}
    )
    return status == 200


def put_blob(container, blob, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    status, body = _request(
        "PUT", _path(container, blob), body=data,
        extra_headers={"x-ms-blob-type": "BlockBlob", "Content-Type": "application/json"},
    )
    if status != 201:
        raise BlobError(f"put blob {container}/{blob} failed ({status}): {body[:300]!r}")


def blob_exists(container, blob):
    status, _ = _request("HEAD", _path(container, blob))
    return status == 200


def get_blob(container, blob):
    """Blob bytes, or None when the blob (or its container) does not exist."""
    status, body = _request("GET", _path(container, blob))
    if status == 200:
        return body
    if status == 404:
        return None
    raise BlobError(f"get blob {container}/{blob} failed ({status}): {body[:300]!r}")


def list_blobs(container):
    """Blob names in the container; empty when the container does not exist."""
    status, body = _request(
        "GET", _path(container), query={"restype": "container", "comp": "list"}
    )
    if status != 200:
        return []
    return re.findall(r"<Name>([^<]*)</Name>", body.decode("utf-8", "replace"))
