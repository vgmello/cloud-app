"""Bootstrap result cache: is a previously bootstrapped stack still current?

The fingerprint is produced only in the control repo and committed, so it ships
inside the action tree at every tag. Callers compare, never compute — two sides
computing a hash from two different checkouts is exactly how a cache silently
stops matching.

Covered inputs (anything here changing invalidates every cached bootstrap):
  - terraform/azure/bootstrap: the bootstrap stack definition itself.
  - environments: the per-environment platform config the tfvars derive from.
  - engine/cloudapp/identity.py: produces the OIDC federation subjects fed to
    the bootstrap tfvars; a format change means every trust relationship is
    stale.
  - .github/actions/deploy-stack/action.yml: the control-side action that
    invokes the bootstrap (mode, terraform dir, etc).

Deliberately NOT covered:
  - The registry lock's `allowed_repos` (registries/<env>/<stack>.yml) — that
    is an authorization decision, not an input to what bootstrap produces.
  - Anything outside the paths above (e.g. the rest of cloudapp, docs, CI
    workflows other than deploy-stack) — a change there does not change a
    bootstrap's output.

CACHE_EPOCH is a manual escape hatch: bump it to invalidate every cache in one
line, independent of any file content, for situations the file-based
fingerprint can't see (e.g. a bug in a past bootstrap run that this module
would not otherwise detect).
"""

import hashlib
import os
import re

# The bootstrap stack plus the config its tfvars derive from, plus the two
# out-of-tree inputs that change what a bootstrap produces without touching
# the bootstrap module itself. Entries may be directories or single files.
COVERED = (
    "terraform/azure/bootstrap",
    "environments",
    "engine/cloudapp/identity.py",
    ".github/actions/deploy-stack/action.yml",
)

# Bump to invalidate every cached bootstrap regardless of file content.
CACHE_EPOCH = 1

_SKIP_DIRS = {".terraform", "tests"}
_REQUIRED = ("resource_group", "plan_client_id", "apply_client_id")

_CLIENT_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_RESOURCE_GROUP_RE = re.compile(r"^[A-Za-z0-9._()-]{1,90}$")


def _skip_file(name):
    """Build artefacts and test-only files: never part of the fingerprint.

    tfplan/*.tfplan/crash.log are Terraform run artefacts that appear in a
    covered path only because the control side plans/applies there — they are
    never committed, so including them means the fingerprint the control side
    records can never match the one it committed, and the cache never hits.
    tests/ (see _SKIP_DIRS) holds *.tftest.hcl files: their content doesn't
    change what bootstrap produces, and covering them would force every stack
    in every environment to re-bootstrap on an unrelated test-only edit.

    .terraform.lock.hcl is excluded deliberately, not by omission: `terraform
    init` rewrites it on the runner, adding platform-specific provider hashes,
    which would churn the fingerprint spuriously on every run. A provider
    version bump normally accompanies a versions.tf change, which IS covered.
    """
    if ".tfstate" in name:
        return True
    if name == "tfplan" or name.endswith(".tfplan"):
        return True
    if name == "crash.log":
        return True
    if name == ".terraform.lock.hcl":
        return True
    return False


def _covered_files(root, subpaths):
    for subpath in subpaths:
        base = os.path.join(root, subpath)
        if os.path.isfile(base):
            name = os.path.basename(base)
            if not _skip_file(name):
                yield os.path.relpath(base, root), base
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for name in sorted(filenames):
                if _skip_file(name):
                    continue
                full = os.path.join(dirpath, name)
                yield os.path.relpath(full, root), full


def fingerprint(root, subpaths=COVERED):
    """sha256 over CACHE_EPOCH and the covered files' paths and contents,
    sorted for stability."""
    digest = hashlib.sha256()
    digest.update(str(CACHE_EPOCH).encode())
    digest.update(b"\0")
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


def _field_matches(cache, key, expected):
    """True only if the field is present in cache AND equals expected once both
    are stripped. A missing field is always a miss, even against an empty
    `expected` — a cache with no stack_name must never match by accident."""
    raw = cache.get(key)
    if raw is None:
        return False
    return str(raw).strip() == str(expected).strip()


def use_cache(local_fingerprint, cache, stack_name, env):
    """True only on a positive match. Every other outcome means dispatch.

    Defence in depth against a cache belonging to a different stack/environment
    reaching this decision (e.g. two `cloud-app` invocations sharing one temp
    cache path in the same job, or a stale file left behind by a failed
    fetch): the cache's own stack_name/environment fields must match the
    caller's, in addition to the fingerprint and required values matching.
    """
    if not local_fingerprint or not isinstance(cache, dict):
        return False
    if cache.get("fingerprint") != local_fingerprint:
        return False
    if not _field_matches(cache, "stack_name", stack_name):
        return False
    if not _field_matches(cache, "environment", env):
        return False
    if not all(_value(cache, key) for key in _REQUIRED):
        return False
    if not _CLIENT_ID_RE.fullmatch(_value(cache, "plan_client_id")):
        return False
    if not _CLIENT_ID_RE.fullmatch(_value(cache, "apply_client_id")):
        return False
    return bool(_RESOURCE_GROUP_RE.fullmatch(_value(cache, "resource_group")))


def cache_values(cache):
    """The three bootstrap values, empty strings when the cache is unusable."""
    source = cache if isinstance(cache, dict) else {}
    return {key: _value(source, key) for key in _REQUIRED}
