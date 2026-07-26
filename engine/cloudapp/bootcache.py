"""Bootstrap result cache: is a previously bootstrapped stack still current?

The fingerprint is produced only in the control repo and committed, so it ships
inside the action tree at every tag. Callers compare, never compute — two sides
computing a hash from two different checkouts is exactly how a cache silently
stops matching.
"""

import hashlib
import os

# The bootstrap stack plus the config its tfvars derive from. A change to either
# means a previously bootstrapped stack is no longer current.
COVERED = ("terraform/azure/bootstrap", "environments")

_SKIP_DIRS = {".terraform"}
_REQUIRED = ("resource_group", "plan_client_id", "apply_client_id")


def _covered_files(root, subpaths):
    for subpath in subpaths:
        base = os.path.join(root, subpath)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for name in sorted(filenames):
                if ".tfstate" in name:
                    continue
                full = os.path.join(dirpath, name)
                yield os.path.relpath(full, root), full


def fingerprint(root, subpaths=COVERED):
    """sha256 over the covered files' paths and contents, sorted for stability."""
    digest = hashlib.sha256()
    for relpath, full in sorted(_covered_files(root, subpaths)):
        digest.update(relpath.replace(os.sep, "/").encode())
        digest.update(b"\0")
        with open(full, "rb") as fh:
            body = fh.read()
        digest.update(str(len(body)).encode())
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _value(cache, key):
    """A required value, normalised. Whitespace-only is treated as absent: it is
    truthy in Python, and a blank identity must never read as a genuine match."""
    raw = cache.get(key)
    return "" if raw is None else str(raw).strip()


def use_cache(local_fingerprint, cache):
    """True only on a positive match. Every other outcome means dispatch."""
    if not local_fingerprint or not isinstance(cache, dict):
        return False
    if cache.get("fingerprint") != local_fingerprint:
        return False
    return all(_value(cache, key) for key in _REQUIRED)


def cache_values(cache):
    """The three bootstrap values, empty strings when the cache is unusable."""
    source = cache if isinstance(cache, dict) else {}
    return {key: _value(source, key) for key in _REQUIRED}
