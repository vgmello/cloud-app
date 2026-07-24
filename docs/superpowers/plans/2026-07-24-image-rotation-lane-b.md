# Lane B Image Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the `cloud-app` action's Terraform-skip path (`should_apply == 'false'`), deploy the freshly built image by updating the existing Azure Container Apps / Function Apps directly, instead of doing nothing.

**Architecture:** A new pure engine module `naming.py` reproduces the Terraform resource-name derivation (`locals.tf`). A new `rotate.py` + `cloudapp rotate-images` CLI command iterates the `image_tags` map and runs `az containerapp update` (keys with `/`) or `az functionapp config container set` (keys without) per image. The action gains one `Rotate images` step gated on `should_apply == 'false'`.

**Tech Stack:** Python engine (`python -m cloudapp`), Azure CLI, GitHub Actions composite action, pytest.

## Global Constraints

- Naming MUST mirror `terraform/azure/locals.tf`: `base = naming_prefix + name`; entry base = explicit `name` → (single entry) `base` → (multi) `base-<key>`; container app = `ca-<app_base>-<env>`; function app = `func-<func_base>-<env>`.
- `image_tags` key contract (`engine/cloudapp/builds.py`): `"<app_key>/<container_key>"` for app containers, `"<function_key>"` (no `/`) for functions.
- `naming_prefix` is a top-level key in the platform env yml (`environments/<env>.yml`), default `""`.
- Runner seam: `runner.run(cmd_list, check=False, capture=True)` returns an object with `.returncode`, `.stdout`, `.stderr` (same shape used by `secrets.py` / `backend.state_exists`).
- Engine tests: `cd engine && python3 -m pytest`; lint `python3 -m ruff check .` (binaries invoked via `python3 -m` — they are not on PATH).
- The action lives at `.github/actions/cloud-app/`; engine reachable via `${{ github.action_path }}/../../../engine`.
- Container-app container name = the manifest container key; static sites are never rotated.

---

### Task 1: `naming.py` — Azure resource-name derivation

Pure functions mirroring `locals.tf`, so `rotate-images` targets the exact names Terraform created.

**Files:**

- Create: `engine/cloudapp/naming.py`
- Test: `engine/tests/py/test_naming.py`

**Interfaces:**

- Produces: `naming.container_app_name(tool: dict, prefix: str, env: str, app_key: str) -> str`
- Produces: `naming.function_app_name(tool: dict, prefix: str, env: str, func_key: str) -> str`
- `tool` is a parsed `tool.<env>.json` (`{"name": str, "apps": {..}, "functions": {..}}`); `prefix` is `platform.naming_prefix` or `""`.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/py/test_naming.py`:

```python
from cloudapp import naming

# Expected values are hand-derived from terraform/azure/locals.tf and must stay
# in lockstep with it (ca_names / func_names / app_bases rules).

SINGLE = {"name": "orders-api", "apps": {"main": {}}, "functions": {}}
MULTI = {
    "name": "orders-api",
    "apps": {"api": {}, "worker": {}},
    "functions": {"processor": {}},
}


def test_container_app_name_single_app_uses_base():
    assert naming.container_app_name(SINGLE, "", "dev", "main") == "ca-orders-api-dev"


def test_container_app_name_multi_app_suffixes_key():
    assert naming.container_app_name(MULTI, "", "dev", "api") == "ca-orders-api-api-dev"
    assert naming.container_app_name(MULTI, "", "dev", "worker") == "ca-orders-api-worker-dev"


def test_container_app_name_applies_prefix():
    assert naming.container_app_name(SINGLE, "acme-", "prod", "main") == "ca-acme-orders-api-prod"


def test_container_app_name_explicit_name_override():
    tool = {"name": "orders-api", "apps": {"api": {"name": "custom-app"}, "b": {}}, "functions": {}}
    assert naming.container_app_name(tool, "", "dev", "api") == "ca-custom-app-dev"


def test_function_app_name_single_function_uses_base():
    tool = {"name": "orders-api", "apps": {}, "functions": {"processor": {}}}
    assert naming.function_app_name(tool, "", "dev", "processor") == "func-orders-api-dev"


def test_function_app_name_multi_function_suffixes_key():
    tool = {"name": "orders-api", "apps": {}, "functions": {"a": {}, "b": {}}}
    assert naming.function_app_name(tool, "", "dev", "a") == "func-orders-api-a-dev"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudapp.naming'`.

- [ ] **Step 3: Implement `naming.py`**

Create `engine/cloudapp/naming.py`:

```python
"""Azure resource-name derivation — mirrors terraform/azure/locals.tf.

Kept in lockstep with locals.tf so the Lane B image rotation targets the exact
container app / function app names Terraform created. See test_naming.py.
"""


def _base(tool, prefix):
    return f"{prefix}{tool['name']}"


def _entry_base(entries, key, base):
    """Per-entry base name: explicit `name` > (single entry) base > base-<key>."""
    explicit = (entries.get(key) or {}).get("name")
    if explicit:
        return explicit
    return base if len(entries) == 1 else f"{base}-{key}"


def container_app_name(tool, prefix, env, app_key):
    app_base = _entry_base(tool.get("apps") or {}, app_key, _base(tool, prefix))
    return f"ca-{app_base}-{env}"


def function_app_name(tool, prefix, env, func_key):
    func_base = _entry_base(tool.get("functions") or {}, func_key, _base(tool, prefix))
    return f"func-{func_base}-{env}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engine && python3 -m pytest tests/py/test_naming.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint**

Run: `cd engine && python3 -m ruff check cloudapp/naming.py tests/py/test_naming.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/naming.py engine/tests/py/test_naming.py
git commit -m "feat(naming): Azure resource-name derivation mirroring locals.tf"
```

---

### Task 2: `rotate.py` — image rotation logic

Iterate `image_tags` and run the right `az` verb per key. Pure logic with the `run` seam injected, so it is unit-testable without Azure.

**Files:**

- Create: `engine/cloudapp/rotate.py`
- Test: `engine/tests/py/test_rotate.py`

**Interfaces:**

- Consumes: `naming.container_app_name`, `naming.function_app_name` (Task 1).
- Produces: `rotate.RotateError` (Exception).
- Produces: `rotate.rotate(tool: dict, prefix: str, env: str, image_tags: dict, resource_group: str, run) -> int` — updates each image, returns the count; raises `RotateError` on a non-zero `az` exit.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/py/test_rotate.py`:

```python
import pytest

from cloudapp import rotate


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


SINGLE = {"name": "orders-api", "apps": {"main": {}}, "functions": {}}


def _recorder(results=None):
    calls = []
    seq = list(results or [])

    def run(cmd, check=False, capture=False):
        calls.append(cmd)
        return seq.pop(0) if seq else _Result(0)

    run.calls = calls
    return run


def test_rotate_container_app_uses_containerapp_update():
    run = _recorder()
    n = rotate.rotate(SINGLE, "", "dev", {"main/main": "reg/orders-api/main-main:sha1"}, "rg-x", run)
    assert n == 1
    assert run.calls[0] == [
        "az", "containerapp", "update",
        "--name", "ca-orders-api-dev",
        "--resource-group", "rg-x",
        "--container-name", "main",
        "--image", "reg/orders-api/main-main:sha1",
    ]


def test_rotate_function_uses_functionapp_container_set():
    tool = {"name": "orders-api", "apps": {}, "functions": {"processor": {}}}
    run = _recorder()
    n = rotate.rotate(tool, "", "dev", {"processor": "reg/orders-api/processor:sha1"}, "rg-x", run)
    assert n == 1
    assert run.calls[0] == [
        "az", "functionapp", "config", "container", "set",
        "--name", "func-orders-api-dev",
        "--resource-group", "rg-x",
        "--image", "reg/orders-api/processor:sha1",
    ]


def test_rotate_empty_map_is_noop():
    run = _recorder()
    assert rotate.rotate(SINGLE, "", "dev", {}, "rg-x", run) == 0
    assert run.calls == []


def test_rotate_raises_on_az_failure():
    run = _recorder([_Result(1, "", "boom")])
    with pytest.raises(rotate.RotateError, match="main/main"):
        rotate.rotate(SINGLE, "", "dev", {"main/main": "reg/o/main-main:sha1"}, "rg-x", run)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_rotate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudapp.rotate'`.

- [ ] **Step 3: Implement `rotate.py`**

Create `engine/cloudapp/rotate.py`:

```python
"""Lane B: update running Azure images in place, no Terraform.

For each entry in the docker-build image_tags map, roll the image on the
existing container app / function app so a code-only change ships without a
Terraform run. Only reached when the manifest is unchanged and state exists
(the action gate guarantees the resources already exist).
"""

from . import naming


class RotateError(Exception):
    pass


def rotate(tool, prefix, env, image_tags, resource_group, run):
    rotated = 0
    for key, image in image_tags.items():
        if "/" in key:
            app_key, container_key = key.split("/", 1)
            name = naming.container_app_name(tool, prefix, env, app_key)
            cmd = [
                "az", "containerapp", "update",
                "--name", name,
                "--resource-group", resource_group,
                "--container-name", container_key,
                "--image", image,
            ]
        else:
            name = naming.function_app_name(tool, prefix, env, key)
            cmd = [
                "az", "functionapp", "config", "container", "set",
                "--name", name,
                "--resource-group", resource_group,
                "--image", image,
            ]
        result = run(cmd, check=False, capture=True)
        if result.returncode != 0:
            raise RotateError(f"failed to rotate image for {key} ({name}):\n{result.stderr}")
        print(f"rotated {key} -> {image} on {name}")
        rotated += 1
    print(f"rotated {rotated} image(s)")
    return rotated
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engine && python3 -m pytest tests/py/test_rotate.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint**

Run: `cd engine && python3 -m ruff check cloudapp/rotate.py tests/py/test_rotate.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/rotate.py engine/tests/py/test_rotate.py
git commit -m "feat(rotate): az image rotation for container apps and functions"
```

---

### Task 3: `rotate-images` CLI command

Wire the command the action calls: read `tool.json`, `naming_prefix` from the platform file, the `image_tags` JSON, and the resource group; call `rotate.rotate`.

**Files:**

- Modify: `engine/cloudapp/cli.py`
- Test: `engine/tests/py/test_cli.py`

**Interfaces:**

- Consumes: `rotate.rotate`, `rotate.RotateError` (Task 2).
- Produces: CLI `python -m cloudapp rotate-images --tool-json --environment --platform-file --image-tags --resource-group`.

- [ ] **Step 1: Write the failing test**

Add to `engine/tests/py/test_cli.py` (imports at top of that file already include `from cloudapp import cli`; add whatever this test needs locally):

```python
def test_rotate_images_cli_invokes_az_per_image(tmp_path, monkeypatch, capsys):
    import json as _json
    from cloudapp import cli, runner

    tool = {"name": "orders-api", "apps": {"main": {}}, "functions": {}}
    (tmp_path / "tool.dev.json").write_text(_json.dumps(tool))
    (tmp_path / "dev.yml").write_text('naming_prefix: ""\nstate_backend:\n  type: azurerm\n')

    calls = []

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, check=False, capture=False):
        calls.append(cmd)
        return _R()

    monkeypatch.setattr(runner, "run", fake_run)

    cli.main([
        "rotate-images",
        "--tool-json", str(tmp_path / "tool.dev.json"),
        "--environment", "dev",
        "--platform-file", str(tmp_path / "dev.yml"),
        "--image-tags", _json.dumps({"main/main": "reg/orders-api/main-main:sha1"}),
        "--resource-group", "rg-x",
    ])

    assert calls[0][:3] == ["az", "containerapp", "update"]
    assert "ca-orders-api-dev" in calls[0]
    assert "reg/orders-api/main-main:sha1" in calls[0]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd engine && python3 -m pytest tests/py/test_cli.py::test_rotate_images_cli_invokes_az_per_image -v`
Expected: FAIL — `argument command: invalid choice: 'rotate-images'` (subparser not registered).

- [ ] **Step 3: Add `rotate` to the imports and implement the command**

In `engine/cloudapp/cli.py`, add `rotate` to the module import tuple (keep alphabetical: it sorts after `resolve`, before `runner`):

```python
from . import (
    backend,
    builds,
    dockerbuild,
    gha,
    identity,
    manifest,
    naming,
    registry,
    resolve,
    rotate,
    runner,
    secrets,
    tfdeploy,
)
```

(Adding `naming` too keeps the tuple complete even though `cli` uses it only via `rotate`; if `ruff` flags `naming` as unused, drop it from this tuple — `rotate` imports it directly.)

Add the command function next to `cmd_state_exists`:

```python
def cmd_rotate_images(args):
    tool = _load_json(args.tool_json)
    platform = load_yaml(Path(args.platform_file).read_text()) or {}
    prefix = platform.get("naming_prefix") or ""
    image_tags = json.loads(args.image_tags or "{}")
    rotate.rotate(tool, prefix, args.environment, image_tags, args.resource_group, runner.run)
```

- [ ] **Step 4: Register the subparser and the exception**

In `engine/cloudapp/cli.py`, add the subparser next to the `state-exists` one:

```python
    p = sub.add_parser("rotate-images")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--platform-file", required=True)
    p.add_argument("--image-tags", default="{}")
    p.add_argument("--resource-group", required=True)
    p.set_defaults(func=cmd_rotate_images)
```

And add `rotate.RotateError` to the caught-exception tuple in `main`:

```python
    except (manifest.ManifestError, resolve.ResolveError, secrets.SyncError,
            tfdeploy.DeployError, backend.BackendError, rotate.RotateError,
            registry.RegistryError, ValueError) as exc:
        gha.error(str(exc))
```

- [ ] **Step 5: Run the test + full suite**

Run: `cd engine && python3 -m pytest tests/py/test_cli.py::test_rotate_images_cli_invokes_az_per_image -v && python3 -m pytest -q && python3 -m ruff check .`
Expected: the new test PASSES; full suite green; `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/cli.py engine/tests/py/test_cli.py
git commit -m "feat(cli): rotate-images command"
```

---

### Task 4: Action `Rotate images` step + docs

Run the rotation on the Lane B skip path and report it; note the two lanes and caveats in docs.

**Files:**

- Modify: `.github/actions/cloud-app/action.yml`
- Modify: `samples/caller-app/README.md`

**Interfaces:**

- Consumes: `python -m cloudapp rotate-images` (Task 3); `steps.gate.outputs.should_apply`, `steps.build.outputs.image-tags`, `steps.platform.outputs.file`, `steps.bootstrap.outputs.resource_group`, `steps.parse.outputs.name` (all already produced in `action.yml`).

- [ ] **Step 1: Add the `Rotate images` step**

In `.github/actions/cloud-app/action.yml`, insert this step immediately **before** the `Terraform deploy` step (both are mutually exclusive on `should_apply`):

```yaml
# Lane B: manifest unchanged (should_apply == false) — skip Terraform and
# roll the freshly built image on the existing container apps / functions.
# Reached only when state exists (never first deploy), so the resources exist.
- name: Rotate images
  id: rotate
  if: ${{ steps.gate.outputs.should_apply == 'false' }}
  shell: bash
  env:
    DEPLOY_ENV: ${{ inputs.env }}
    IMAGE_TAGS: ${{ steps.build.outputs.image-tags || '{}' }}
  run: >-
    PYTHONPATH="${{ github.action_path }}/../../../engine"
    python3 -m cloudapp rotate-images
    --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
    --environment "$DEPLOY_ENV"
    --platform-file "${{ steps.platform.outputs.file }}"
    --image-tags "$IMAGE_TAGS"
    --resource-group "${{ steps.bootstrap.outputs.resource_group }}"
```

- [ ] **Step 2: Update the skip-path summary**

In the `Write summary` step, replace the `else` branch line so it reports the rotation instead of "rotation pending". Change:

```bash
          echo "### cloud-app: Terraform run skipped — manifest unchanged since the previous commit (set always_run_terraform: true to force it). Image rebuilt; rotation pending (next phase)." >> "$GITHUB_STEP_SUMMARY"
```

to:

```bash
          echo "### cloud-app: Terraform skipped — manifest unchanged. Rolled the new image directly on the existing container apps/functions (set always_run_terraform: true to force a full Terraform run)." >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 3: Validate the action YAML parses and steps are ordered**

Run:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/actions/cloud-app/action.yml')); print('parse OK')"
grep -n "name: Decide apply\|name: Rotate images\|name: Terraform deploy\|name: Write summary" .github/actions/cloud-app/action.yml
```

Expected: `parse OK`; the four names appear in this order: `Decide apply`, `Rotate images`, `Terraform deploy`, `Write summary`.

- [ ] **Step 4: Document the two lanes in the sample README**

In `samples/caller-app/README.md`, under "How it works", add a bullet after the deploy step describing the split (keep the existing numbered steps intact — append a short paragraph):

```markdown
On an unchanged manifest (a code-only change), the action skips Terraform and
rolls the freshly built image directly onto the existing container apps /
functions (`az containerapp update` / `az functionapp config container set`) —
fast, no plan/apply. A manifest change, first deploy, manual dispatch, or
`always_run_terraform: true` runs the full Terraform plan+apply instead. Static
sites are not image-rotated, and a rotated secret with no new commit is picked
up on the next revision (push a commit or restart the revision to force it).
```

- [ ] **Step 5: Commit**

```bash
git add .github/actions/cloud-app/action.yml samples/caller-app/README.md
git commit -m "feat(cloud-app): rotate images directly on the terraform-skip path"
```

---

## Self-Review

**Spec coverage:**

- `naming.py` mirroring `locals.tf` → Task 1. ✓
- `rotate-images` command, container-app + function `az` verbs → Task 2 (logic) + Task 3 (CLI). ✓
- Action `Rotate images` step on `should_apply == 'false'`, using existing deploy login + `resource_group` → Task 4. ✓
- Exactly one of deploy/rotate runs (both gated on `should_apply`) → Task 4 Step 1 (insert before `Terraform deploy`, opposite `if`). ✓
- Summary reports rotation → Task 4 Step 2. ✓
- Static site / same-sha secret caveats documented → Task 4 Step 4. ✓
- `RotateError` surfaced via the CLI exception tuple → Task 3 Step 4. ✓
- Empty `image_tags` no-op → Task 2 test. ✓

**Placeholder scan:** No TBD/TODO; every code block is complete. `<env>`/`reg/...`/`sha1` are concrete test/template values.

**Type consistency:** `naming.container_app_name(tool, prefix, env, app_key)` / `function_app_name(...)` signatures identical across Task 1 (def), Task 2 (call), tests. `rotate.rotate(tool, prefix, env, image_tags, resource_group, run)` identical across Task 2 (def), Task 3 (call), tests. `run` seam matches `runner.run(cmd, check, capture)` used elsewhere. Step-output names in Task 4 (`steps.gate.outputs.should_apply`, `steps.build.outputs.image-tags`, `steps.platform.outputs.file`, `steps.bootstrap.outputs.resource_group`) all exist in the current `action.yml`.

**Note on live validation:** GitHub Actions execution isn't run locally; Task 4 verifies via YAML parse + step-order grep. The `az` calls themselves are exercised only on a real Lane B deploy, consistent with the platform's "wired, not yet live-validated" status.
