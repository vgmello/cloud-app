"""Fetch a stack's bootstrap cache file from the control repo's default branch.

Best effort by design: any failure (404, auth, network, malformed response)
writes nothing, which the engine treats as a cache miss and therefore a
dispatch. Never fails the step.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

API = "https://api.github.com"


def encode_path(path):
    """Percent-encode each path segment, preserving the '/' separators. Kept
    structural rather than relying on the caller's charset validation."""
    return "/".join(quote(segment, safe="") for segment in path.split("/"))


def main():
    dest = sys.argv[1]
    # Clear any stale file from a previous invocation in the same job (two
    # stacks/environments sharing a runner) before the request, so a failed
    # fetch below can never leave another stack's cached identities in place.
    try:
        os.remove(dest)
    except FileNotFoundError:
        pass
    url = (
        f"{API}/repos/{os.environ['OWNER']}/{os.environ['CONTROL_REPO']}"
        f"/contents/{encode_path(os.environ['CACHE_PATH'])}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        body = base64.b64decode(payload.get("content", "")).decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            print(f"::warning::bootstrap cache lookup failed ({exc.code}); will bootstrap")
        return
    except Exception as exc:
        print(f"::warning::bootstrap cache lookup failed ({exc}); will bootstrap")
        return
    with open(dest, "w") as fh:
        fh.write(body)


if __name__ == "__main__":
    main()
