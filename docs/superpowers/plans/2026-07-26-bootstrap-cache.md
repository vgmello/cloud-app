# Bootstrap Result Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip the bootstrap dispatch when a cached `(stack, environment)` result is current, decided by a content fingerprint of the bootstrap stack that only the control repo produces.

**Architecture:** A committed `bootstrap.fingerprint` ships inside the action tree; the caller compares it against the fingerprint recorded in `registries/<env>/<stack>.bootstrap.yml` (fetched live) and dispatches only on a miss. `control-ref` follows `github.action_ref` so the action version and the bootstrap it triggers are one version.

**Tech Stack:** Python engine (`engine/cloudapp/`), GitHub Actions composite actions, GitHub REST API via `urllib`, pytest.

## Global Constraints

- **Fail safe in one direction only:** anything missing, unreadable, malformed, mismatched, or uncertain → dispatch. The cache may only be used on a positive match with all three values non-empty.
- Fingerprint covers `terraform/azure/bootstrap/**` and `environments/**`; it excludes any `.terraform/` directory and `*.tfstate*`. It is a content hash, never the version string.
- The caller never computes a fingerprint — it reads the committed file from its own action tree.
- The control-side cache write **fails open** (warn and continue). Only `registry.persist_lock` fails closed.
- Network code lives in `.github/scripts/` (alongside `dispatch_and_wait.py`), never in `engine/`.
- Engine tests drive injected seams; no network, no `az`, no `gh`. Tests `cd engine && python3 -m pytest`; lint `python3 -m ruff check .` (invoke via `python3 -m`).

---

### Task 1: `bootcache.py` — fingerprint and the use-cache decision

**Files:**

- Create: `engine/cloudapp/bootcache.py`
- Test: `engine/tests/py/test_bootcache.py`

**Interfaces:**

- Produces: `bootcache.fingerprint(root: str, subpaths: list[str]) -> str` — `"sha256:<hex>"` over the sorted contents of every file under each subpath.
- Produces: `bootcache.COVERED` — `("terraform/azure/bootstrap", "environments")`.
- Produces: `bootcache.use_cache(local_fingerprint: str, cache: dict | None) -> bool`.
- Produces: `bootcache.cache_values(cache: dict | None) -> dict` — `{"resource_group", "plan_client_id", "apply_client_id"}`, empty strings when absent.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/py/test_bootcache.py`:

```python
from cloudapp import bootcache


def _tree(tmp_path):
    (tmp_path / "terraform/azure/bootstrap").mkdir(parents=True)
    (tmp_path / "environments").mkdir()
    (tmp_path / "terraform/azure/bootstrap/main.tf").write_text("resource {}\n")
    (tmp_path / "environments/dev.yml").write_text("location: eastus2\n")
    return tmp_path


def test_fingerprint_is_stable_and_prefixed(tmp_path):
    root = _tree(tmp_path)
    first = bootcache.fingerprint(str(root), bootcache.COVERED)
    assert first.startswith("sha256:")
    assert first == bootcache.fingerprint(str(root), bootcache.COVERED)


def test_fingerprint_changes_when_a_covered_file_changes(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / "terraform/azure/bootstrap/main.tf").write_text("resource { changed }\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) != before


def test_fingerprint_changes_when_platform_config_changes(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / "environments/dev.yml").write_text("location: westus\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) != before


def test_fingerprint_ignores_files_outside_covered_paths(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / "README.md").write_text("docs change\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) == before


def test_fingerprint_ignores_terraform_working_dirs(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    noise = root / "terraform/azure/bootstrap/.terraform/providers"
    noise.mkdir(parents=True)
    (noise / "blob.bin").write_text("downloaded provider\n")
    (root / "terraform/azure/bootstrap/terraform.tfstate").write_text("{}\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) == before


FP = "sha256:abc"
GOOD = {
    "resource_group": "rg-orders-api-dev",
    "plan_client_id": "11111111-1111-1111-1111-111111111111",
    "apply_client_id": "22222222-2222-2222-2222-222222222222",
    "fingerprint": FP,
}


def test_use_cache_true_on_full_match():
    assert bootcache.use_cache(FP, GOOD) is True


def test_use_cache_false_when_absent():
    assert bootcache.use_cache(FP, None) is False


def test_use_cache_false_on_fingerprint_mismatch():
    assert bootcache.use_cache("sha256:different", GOOD) is False


def test_use_cache_false_when_any_value_missing():
    for key in ("resource_group", "plan_client_id", "apply_client_id"):
        cache = dict(GOOD)
        cache[key] = ""
        assert bootcache.use_cache(FP, cache) is False, key
        del cache[key]
        assert bootcache.use_cache(FP, cache) is False, key


def test_use_cache_false_on_malformed_document():
    assert bootcache.use_cache(FP, "not a mapping") is False
    assert bootcache.use_cache(FP, {}) is False


def test_use_cache_false_when_local_fingerprint_is_empty():
    # an unreadable local fingerprint must never match a cache
    assert bootcache.use_cache("", dict(GOOD, fingerprint="")) is False


def test_cache_values_returns_empty_strings_when_absent():
    assert bootcache.cache_values(None) == {
        "resource_group": "",
        "plan_client_id": "",
        "apply_client_id": "",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_bootcache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudapp.bootcache'`.

- [ ] **Step 3: Implement `bootcache.py`**

Create `engine/cloudapp/bootcache.py`:

```python
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


def use_cache(local_fingerprint, cache):
    """True only on a positive match. Every other outcome means dispatch."""
    if not local_fingerprint or not isinstance(cache, dict):
        return False
    if cache.get("fingerprint") != local_fingerprint:
        return False
    return all(cache.get(key) for key in _REQUIRED)


def cache_values(cache):
    """The three bootstrap values, empty strings when the cache is unusable."""
    source = cache if isinstance(cache, dict) else {}
    return {key: source.get(key) or "" for key in _REQUIRED}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engine && python3 -m pytest tests/py/test_bootcache.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Lint**

Run: `cd engine && python3 -m ruff check cloudapp/bootcache.py tests/py/test_bootcache.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/bootcache.py engine/tests/py/test_bootcache.py
git commit -m "feat(bootcache): bootstrap fingerprint and cache-currency decision"
```

---

### Task 2: CLI — `bootstrap-fingerprint` and `bootstrap-cache`

**Files:**

- Modify: `engine/cloudapp/cli.py`
- Test: `engine/tests/py/test_cli.py`

**Interfaces:**

- Consumes: `bootcache.fingerprint`, `use_cache`, `cache_values` (Task 1).
- Produces: `python -m cloudapp bootstrap-fingerprint --root <dir>` — prints the digest.
- Produces: `python -m cloudapp bootstrap-cache --fingerprint-file <path> --cache-file <path>` — writes step outputs `use_cache` (`"true"`/`"false"`), `resource_group`, `plan_client_id`, `apply_client_id`. A missing `--cache-file` is a normal cache miss, not an error.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_cli.py`:

```python
def test_bootstrap_cache_cli_uses_a_matching_cache(tmp_path, monkeypatch, capsys):
    from cloudapp import cli

    out_file = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    (tmp_path / "fp").write_text("sha256:abc\n")
    (tmp_path / "cache.yml").write_text(
        "resource_group: rg-orders-api-dev\n"
        "plan_client_id: 1111\n"
        "apply_client_id: 2222\n"
        "fingerprint: sha256:abc\n"
    )

    cli.main([
        "bootstrap-cache",
        "--fingerprint-file", str(tmp_path / "fp"),
        "--cache-file", str(tmp_path / "cache.yml"),
    ])

    written = out_file.read_text()
    assert "use_cache=true" in written
    assert "resource_group=rg-orders-api-dev" in written
    assert "plan_client_id=1111" in written


def test_bootstrap_cache_cli_misses_when_file_absent(tmp_path, monkeypatch):
    from cloudapp import cli

    out_file = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    (tmp_path / "fp").write_text("sha256:abc\n")

    cli.main([
        "bootstrap-cache",
        "--fingerprint-file", str(tmp_path / "fp"),
        "--cache-file", str(tmp_path / "nope.yml"),
    ])

    assert "use_cache=false" in out_file.read_text()


def test_bootstrap_cache_cli_misses_on_stale_fingerprint(tmp_path, monkeypatch):
    from cloudapp import cli

    out_file = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    (tmp_path / "fp").write_text("sha256:current\n")
    (tmp_path / "cache.yml").write_text(
        "resource_group: rg\nplan_client_id: 1\napply_client_id: 2\n"
        "fingerprint: sha256:stale\n"
    )

    cli.main([
        "bootstrap-cache",
        "--fingerprint-file", str(tmp_path / "fp"),
        "--cache-file", str(tmp_path / "cache.yml"),
    ])

    assert "use_cache=false" in out_file.read_text()


def test_bootstrap_cache_cli_misses_on_malformed_cache(tmp_path, monkeypatch):
    from cloudapp import cli

    out_file = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    (tmp_path / "fp").write_text("sha256:abc\n")
    (tmp_path / "cache.yml").write_text("just a string\n")

    cli.main([
        "bootstrap-cache",
        "--fingerprint-file", str(tmp_path / "fp"),
        "--cache-file", str(tmp_path / "cache.yml"),
    ])

    assert "use_cache=false" in out_file.read_text()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_cli.py -k bootstrap_cache -v`
Expected: FAIL — `argument command: invalid choice: 'bootstrap-cache'`.

- [ ] **Step 3: Implement the commands**

In `engine/cloudapp/cli.py`, add `bootcache` to the module import tuple in alphabetical position (it sorts after `backend`, before `builds`).

Add the two command functions next to `cmd_bootstrap_vars`:

```python
def cmd_bootstrap_fingerprint(args):
    print(bootcache.fingerprint(args.root))


def cmd_bootstrap_cache(args):
    local = Path(args.fingerprint_file).read_text().strip() if Path(args.fingerprint_file).exists() else ""
    cache = None
    cache_path = Path(args.cache_file)
    if cache_path.exists():
        try:
            cache = load_yaml(cache_path.read_text())
        except Exception as exc:  # a malformed cache is a miss, never a failure
            gha.warning(f"ignoring unreadable bootstrap cache: {exc}")
    hit = bootcache.use_cache(local, cache)
    outputs = {"use_cache": "true" if hit else "false"}
    outputs.update(bootcache.cache_values(cache) if hit else bootcache.cache_values(None))
    gha.write_outputs(outputs)
    print(f"bootstrap cache: {'hit' if hit else 'miss'}")
```

- [ ] **Step 4: Register the subparsers**

Add next to the `bootstrap-vars` subparser:

```python
    p = sub.add_parser("bootstrap-fingerprint")
    p.add_argument("--root", default=".")
    p.set_defaults(func=cmd_bootstrap_fingerprint)

    p = sub.add_parser("bootstrap-cache")
    p.add_argument("--fingerprint-file", required=True)
    p.add_argument("--cache-file", required=True)
    p.set_defaults(func=cmd_bootstrap_cache)
```

- [ ] **Step 5: Run tests + lint**

Run: `cd engine && python3 -m pytest -q && python3 -m ruff check .`
Expected: full suite green; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/cli.py engine/tests/py/test_cli.py
git commit -m "feat(cli): bootstrap-fingerprint and bootstrap-cache commands"
```

---

### Task 3: Fingerprint file, CI staleness check, release workflow

**Files:**

- Create: `bootstrap.fingerprint`
- Create: `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**

- Consumes: `python -m cloudapp bootstrap-fingerprint` (Task 2).

- [ ] **Step 1: Generate the committed fingerprint**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
PYTHONPATH=engine python3 -m cloudapp bootstrap-fingerprint --root . > bootstrap.fingerprint
cat bootstrap.fingerprint
```

Expected: one `sha256:<64 hex>` line.

- [ ] **Step 2: Add the CI staleness check**

In `.github/workflows/ci.yml`, add a step immediately after the existing fixture-drift step (the one running `generate_tf_fixtures.py` and `git diff --exit-code`), mirroring its style:

```yaml
- name: Bootstrap fingerprint drift
  run: |
    PYTHONPATH=engine python3 -m cloudapp bootstrap-fingerprint --root . > bootstrap.fingerprint
    git diff --exit-code bootstrap.fingerprint
```

This keeps the committed value honest, so releasing only has to move tags.

- [ ] **Step 3: Add the release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: release
# Moves the floating tags callers pin. v1 tracks every minor and patch; v1.1
# tracks every patch; v1.1.1 is immutable and created by the release itself.
# Callers pin whichever they want, and `control-ref` follows the ref the action
# was resolved at — so the bootstrap they trigger is the version they pinned.

on:
  workflow_dispatch:
    inputs:
      version:
        description: Full version to release, e.g. v1.2.3
        required: true

permissions:
  contents: write

jobs:
  tag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          fetch-depth: 0

      - name: Move floating tags
        env:
          VERSION: ${{ inputs.version }}
        run: |
          set -euo pipefail
          if ! printf '%s' "$VERSION" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
            echo "::error::version must look like v1.2.3 (got '$VERSION')"
            exit 1
          fi
          MAJOR="${VERSION%%.*}"
          MINOR="${VERSION%.*}"
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          # The immutable tag must not already exist; the floating ones move.
          if git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then
            echo "::error::$VERSION already exists; immutable tags are never moved"
            exit 1
          fi
          git tag "$VERSION"
          git tag -f "$MAJOR"
          git tag -f "$MINOR"
          git push origin "$VERSION"
          git push -f origin "$MAJOR" "$MINOR"
          echo "released $VERSION (moved $MAJOR, $MINOR)" >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 4: Verify**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('release OK')"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ci OK')"
PYTHONPATH=engine python3 -m cloudapp bootstrap-fingerprint --root . | diff - bootstrap.fingerprint && echo "fingerprint current"
```

Expected: both parse; the fingerprint matches the committed file.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.fingerprint .github/workflows/release.yml .github/workflows/ci.yml
git commit -m "feat(release): committed bootstrap fingerprint, drift check, floating tags"
```

---

### Task 4: Caller — read the cache and dispatch only on a miss

**Files:**

- Create: `.github/scripts/fetch_bootstrap_cache.py`
- Modify: `.github/actions/cloud-app/action.yml`

**Interfaces:**

- Consumes: `python -m cloudapp bootstrap-cache` (Task 2); `bootstrap.fingerprint` (Task 3).
- Produces: a `phase1` step whose outputs `resource_group`, `plan_client_id`, `apply_client_id` are the single source downstream, regardless of which path ran.

- [ ] **Step 1: Add the fetch script**

Create `.github/scripts/fetch_bootstrap_cache.py`:

```python
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

API = "https://api.github.com"


def main():
    dest = sys.argv[1]
    url = (
        f"{API}/repos/{os.environ['OWNER']}/{os.environ['CONTROL_REPO']}"
        f"/contents/{os.environ['CACHE_PATH']}"
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
        with urllib.request.urlopen(req) as resp:
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
```

- [ ] **Step 2: Follow the action ref and widen the token**

In `.github/actions/cloud-app/action.yml`:

Change the `control-ref` input's default so the bootstrap runs the version the caller pinned:

```yaml
control-ref:
  description: >-
    Ref of the control repo to run bootstrap.yml from. Defaults to the ref this
    action was resolved at, so the bootstrap matches the action version the
    caller pinned. Empty for a local (`./`) action reference, where it falls
    back to main.
  default: ""
```

Add `permission-contents: read` to the existing `permission-actions: write` on the `Generate control-repo App token` step (keep the comment already there).

- [ ] **Step 3: Add the cache lookup, before the dispatch**

Insert these two steps immediately after `Generate control-repo App token` and before `Bootstrap dispatch (Phase 1)`:

```yaml
# The fingerprint ships inside this action's own tree, so it describes the
# bootstrap stack at the ref the caller pinned. The caller never computes it.
- name: Look up bootstrap cache
  id: cachefetch
  shell: bash
  env:
    GH_TOKEN: ${{ steps.token.outputs.token }}
    OWNER: ${{ github.repository_owner }}
    CONTROL_REPO: ${{ inputs.control-repo }}
    CACHE_PATH: registries/${{ inputs.env }}/${{ steps.parse.outputs.name }}.bootstrap.yml
  run: python "${{ github.action_path }}/../../scripts/fetch_bootstrap_cache.py" bootstrap-cache.yml

- name: Decide bootstrap
  id: cache
  shell: bash
  run: >-
    PYTHONPATH="${{ github.action_path }}/../../../engine"
    python3 -m cloudapp bootstrap-cache
    --fingerprint-file "${{ github.action_path }}/../../../bootstrap.fingerprint"
    --cache-file bootstrap-cache.yml
```

- [ ] **Step 4: Make the dispatch conditional**

Add an `if:` to the existing `Bootstrap dispatch (Phase 1)` step and make `TARGET_BRANCH` follow the action ref. Change only these two things; leave every other line of that step as it is:

```yaml
- name: Bootstrap dispatch (Phase 1)
  id: bootstrap
  if: ${{ steps.cache.outputs.use_cache != 'true' || github.event_name == 'workflow_dispatch' }}
  shell: bash
  env:
    GH_TOKEN: ${{ steps.token.outputs.token }}
    TARGET_OWNER: ${{ github.repository_owner }}
    TARGET_REPO: ${{ inputs.control-repo }}
    TARGET_WORKFLOW: bootstrap.yml
    TARGET_BRANCH: ${{ inputs.control-ref || github.action_ref || 'main' }}
```

- [ ] **Step 5: Resolve the ids from whichever path ran**

`steps.bootstrap.outputs.*` is empty on the cached path, so add a single resolve step immediately after the dispatch step:

```yaml
# One source of truth for the ids: the dispatch when it ran, the cache
# otherwise. Everything downstream reads this step, never either branch.
- name: Resolve bootstrap identities
  id: phase1
  shell: bash
  env:
    RG: ${{ steps.bootstrap.outputs.resource_group || steps.cache.outputs.resource_group }}
    PLAN_ID: ${{ steps.bootstrap.outputs.plan_client_id || steps.cache.outputs.plan_client_id }}
    APPLY_ID: ${{ steps.bootstrap.outputs.apply_client_id || steps.cache.outputs.apply_client_id }}
  run: |
    if [ -z "$RG" ] || [ -z "$PLAN_ID" ] || [ -z "$APPLY_ID" ]; then
      echo "::error::bootstrap identities unresolved (resource_group='$RG'); the bootstrap dispatch did not return them"
      exit 1
    fi
    {
      echo "resource_group=$RG"
      echo "plan_client_id=$PLAN_ID"
      echo "apply_client_id=$APPLY_ID"
    } >> "$GITHUB_OUTPUT"
    echo "cloud-app: phase 1 via ${{ steps.bootstrap.outcome == 'skipped' && 'cache' || 'dispatch' }}"
```

- [ ] **Step 6: Repoint every consumer at `phase1`**

Replace all remaining `steps.bootstrap.outputs.` references with `steps.phase1.outputs.` — the action-level `resource_group` output and the three in-step uses (build login, deploy login, rotate-images `--resource-group`).

Run this and confirm the only matches left are the dispatch step's own `id: bootstrap` and the resolve step's `steps.bootstrap.outputs` inputs:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
grep -n "steps.bootstrap.outputs" .github/actions/cloud-app/action.yml
```

- [ ] **Step 7: Verify**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
python3 -c "import yaml; yaml.safe_load(open('.github/actions/cloud-app/action.yml')); print('action OK')"
python3 -c "import ast; ast.parse(open('.github/scripts/fetch_bootstrap_cache.py').read()); print('script OK')"
grep -n "name: Look up bootstrap cache\|name: Decide bootstrap\|name: Bootstrap dispatch\|name: Resolve bootstrap identities" .github/actions/cloud-app/action.yml
```

Expected: both parse; the four step names appear in that order.

- [ ] **Step 8: Commit**

```bash
git add .github/scripts/fetch_bootstrap_cache.py .github/actions/cloud-app/action.yml
git commit -m "feat(cloud-app): skip the bootstrap dispatch when the cache is current"
```

---

### Task 5: Control side writes the cache, plus docs

**Files:**

- Modify: `.github/actions/deploy-stack/action.yml`
- Modify: `registries/README.md`, `docs/usage.md`

**Interfaces:**

- Consumes: `python -m cloudapp bootstrap-fingerprint` (Task 2); the values already assembled into `outputs/deployment-results.json`.

- [ ] **Step 1: Write the cache file after a successful bootstrap**

In `.github/actions/deploy-stack/action.yml`, add a step after `Collect bootstrap outputs` and before `Upload bootstrap outputs`:

```yaml
# Cache the result so later deploys of this stack can skip the dispatch.
# Fails open: the cache is an optimisation, and a missing one just means the
# next deploy bootstraps as before. Never fail the bootstrap over it.
- name: Cache bootstrap result
  if: ${{ success() }}
  shell: bash
  env:
    STACK_NAME: ${{ inputs.stack-name }}
    TARGET_ENV: ${{ inputs.environment }}
  run: |
    set -uo pipefail
    RG=$(jq -r '.resource_group // ""' outputs/deployment-results.json)
    PLAN_ID=$(jq -r '.plan_client_id // ""' outputs/deployment-results.json)
    APPLY_ID=$(jq -r '.apply_client_id // ""' outputs/deployment-results.json)
    if [ -z "$RG" ] || [ -z "$PLAN_ID" ] || [ -z "$APPLY_ID" ]; then
      echo "::warning::bootstrap outputs incomplete; not caching"
      exit 0
    fi
    FP=$(PYTHONPATH=central-workspace/engine python3 -m cloudapp bootstrap-fingerprint --root central-workspace)
    DEST="central-workspace/registries/$TARGET_ENV/$STACK_NAME.bootstrap.yml"
    mkdir -p "$(dirname "$DEST")"
    cat > "$DEST" <<EOF
    stack_name: $STACK_NAME
    environment: $TARGET_ENV
    resource_group: $RG
    plan_client_id: $PLAN_ID
    apply_client_id: $APPLY_ID
    fingerprint: $FP
    updated_at: $(date -u +'%Y-%m-%dT%H:%M:%SZ')
    EOF
    cd central-workspace
    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git add "registries/$TARGET_ENV/$STACK_NAME.bootstrap.yml"
    if git diff --cached --quiet; then
      echo "bootstrap cache unchanged"
      exit 0
    fi
    git commit -m "cache(bootstrap): $STACK_NAME [$TARGET_ENV]" \
      && git pull --rebase origin main \
      && git push origin main \
      || echo "::warning::could not persist the bootstrap cache; the next deploy will bootstrap again"
```

- [ ] **Step 2: Document the cache and the revocation procedure**

In `registries/README.md`, add a section after the existing lock-file description:

````markdown
## Bootstrap cache

Alongside each lock, `registries/<env>/<stack>.bootstrap.yml` caches what the
bootstrap produced — the resource group, the plan/apply client ids, and a
fingerprint of the bootstrap stack it was produced from:

```yaml
stack_name: orders-api
environment: dev
resource_group: rg-orders-api-dev
plan_client_id: ...
apply_client_id: ...
fingerprint: sha256:...
```

A deploy skips the bootstrap dispatch when this file's `fingerprint` matches the
one shipped with the action version the caller pinned. It is written by the
bootstrap itself; deleting it is always safe and simply makes the next deploy
bootstrap again.

### Revoking a repository's access

Removing a repo from `allowed_repos` is **not sufficient on its own.** The
federated credential that lets that repo obtain Azure tokens lives in Azure
until a bootstrap re-runs and rewrites it — and while a valid cache exists, no
bootstrap runs. To revoke access:

1. Remove the repo from `allowed_repos` in `registries/<env>/<stack>.yml`.
2. **Delete `registries/<env>/<stack>.bootstrap.yml`.**

Step 2 forces the next deploy to bootstrap, which re-federates the identities to
the remaining `allowed_repos`.
````

- [ ] **Step 3: Document versioning for callers**

In `docs/usage.md`, add a short section explaining that the control repo publishes floating tags — `v1` moves on every minor and patch, `v1.1` on every patch, `v1.1.1` never — that callers pin whichever they want, and that the bootstrap runs the same version the action was pinned at. Note that pinning an immutable tag also pins the bootstrap: fixes to the bootstrap stack reach a caller only when they move the pin.

- [ ] **Step 4: Verify**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
python3 -c "import yaml; yaml.safe_load(open('.github/actions/deploy-stack/action.yml')); print('deploy-stack OK')"
(cd engine && python3 -m pytest -q | tail -1)
```

Expected: parses; the full engine suite is green.

- [ ] **Step 5: Commit**

```bash
git add .github/actions/deploy-stack/action.yml registries/README.md docs/usage.md
git commit -m "feat(deploy-stack): persist the bootstrap cache; document revocation"
```

---

## Self-Review

**Spec coverage:**

- Fingerprint over `bootstrap/**` + `environments/**`, excluding `.terraform`/state → Task 1. ✓
- Committed file, CI staleness check, release moves tags only → Task 3. ✓
- Content hash not version string → Task 1 (`fingerprint` hashes file bodies; the release workflow never writes it). ✓
- Separate cache file from the ownership lock → Task 5 Step 1 writes `<stack>.bootstrap.yml` only. ✓
- Caller reads the local fingerprint + live cache, dispatches on any miss → Task 4. ✓
- Fail safe in one direction → Task 1 `use_cache`, Task 2 malformed handling, Task 4 fetch script's best-effort behaviour, Task 4 Step 5's hard failure when ids are unresolved. ✓
- `control-ref` follows `github.action_ref` → Task 4 Steps 2 and 4. ✓
- Token gains `contents: read` → Task 4 Step 2. ✓
- Control side writes the cache, fails open → Task 5 Step 1. ✓
- Revocation procedure documented → Task 5 Step 2. ✓
- Versioning documented, incl. immutable-pin consequence → Task 5 Step 3. ✓
- `workflow_dispatch` still forces a bootstrap → Task 4 Step 4's `if:`. ✓

**Placeholder scan:** No TBD/TODO. Every code block is complete. Task 5 Step 3 describes prose content rather than quoting it, which is appropriate for a docs paragraph and names exactly what it must say.

**Type consistency:** `fingerprint(root, subpaths=COVERED)`, `use_cache(local_fingerprint, cache)`, `cache_values(cache)` match across Task 1's definitions, Task 2's calls, and the tests. Step-output names (`use_cache`, `resource_group`, `plan_client_id`, `apply_client_id`) are identical in Task 2's writer, Task 4's consumers, and the cache file written in Task 5. `phase1` is introduced in Task 4 Step 5 and is the only name Task 4 Step 6 repoints consumers to.

**Ordering:** Tasks 1-3 are independent of the action changes. Task 4 depends on Tasks 1-3 (the CLI command and the committed fingerprint file must exist before the action reads them). Task 5 is independent of Task 4 but must land in the same branch, since a caller that can read a cache is harmless before anything writes one — the miss path is today's behaviour.

**Note on live validation:** `github.action_ref` population, the Contents API shape, and the floating-tag mechanics are only exercisable on a real run. The engine decision logic, which is where a wrong answer would be dangerous, is fully unit-tested offline.
