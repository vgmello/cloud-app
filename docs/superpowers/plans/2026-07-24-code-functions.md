# Non-container (code) Functions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Azure Functions from application code (native runtime stack + zip) as an alternative to the existing container-image path, switched by a `runtime` field in the manifest.

**Architecture:** A `runtime` field on a function turns on _code mode_. In code mode the artifact key (`image`/`docker`/`package`) names a throwaway **builder** (or a directory to zip raw), never a deploy image. The engine skips the ACR push for code functions, produces a zip on the runner (optionally by running a builder container that writes to a `/out` volume), and after `terraform apply` ships it with `az functionapp deployment source config-zip`. Terraform creates the Function App with a native `application_stack` and no image. Container functions are untouched.

**Tech Stack:** Python 3 (engine, pytest), Terraform (azurerm 4.x, `terraform test`), GitHub composite action (bash), Azure CLI.

## Global Constraints

- Function App SKU stays `EP1` (Elastic Premium) — VNet integration, private by default. Consumption/Flex out of scope.
- Linux Function App stacks only (`os_type = "Linux"`).
- Runtime enum values and their `application_stack` mapping (copy verbatim):
  - `dotnet-isolated:8.0` → `dotnet_version="8.0"`, `use_dotnet_isolated_runtime=true`
  - `dotnet-isolated:9.0` → `dotnet_version="9.0"`, `use_dotnet_isolated_runtime=true`
  - `node:20` → `node_version="20"`
  - `node:22` → `node_version="22"`
  - `python:3.11` → `python_version="3.11"`
  - `python:3.12` → `python_version="3.12"`
  - `java:17` → `java_version="17"`
  - `java:21` → `java_version="21"`
  - `powershell:7.4` → `powershell_core_version="7.4"`
- Builder output convention: platform mounts a volume at `/out` inside the builder; the builder writes artifacts there; the zip is the contents of `/out`.
- Container mode (no `runtime`) behavior is unchanged, including the existing default where a function with neither `image` nor `docker` builds `./Dockerfile`.
- Code mode (`runtime` present) requires exactly one of `image` | `docker` | `package`.
- `config-zip` runs on the caller's job runner (a VNet self-hosted runner in production); no `runs-on` input is added to the action.
- Style: match existing files — no new deps beyond `jsonschema`, stdlib `shutil`/`tempfile` allowed. Run `ruff` clean.

---

### Task 1: Schema — `runtime` + `package` + code-mode constraints

**Files:**

- Modify: `terraform/schema/cloud-app.schema.json` (the `$defs.function` object)
- Test: `engine/tests/py/test_manifest.py`

**Interfaces:**

- Produces: manifest schema accepting `runtime` (enum) and `package` (string) on a function, with the mutual-exclusion and requires rules below. Consumed by `manifest.validate`.

- [ ] **Step 1: Write failing tests**

Add to `engine/tests/py/test_manifest.py`:

```python
from cloudapp import manifest


def _validate(m):
    return manifest.validate(m)


def test_runtime_package_function_is_valid():
    m = {
        "name": "orders",
        "functions": {"worker": {"runtime": "python:3.11", "package": "./scripts"}},
    }
    assert _validate(m) == []


def test_runtime_docker_builder_is_valid():
    m = {
        "name": "orders",
        "functions": {"worker": {"runtime": "dotnet-isolated:8.0", "docker": {"file": "./Dockerfile.build"}}},
    }
    assert _validate(m) == []


def test_package_requires_runtime():
    m = {"name": "orders", "functions": {"worker": {"package": "./scripts"}}}
    assert _validate(m) != []


def test_runtime_needs_exactly_one_artifact():
    m = {"name": "orders", "functions": {"worker": {"runtime": "python:3.11"}}}
    assert _validate(m) != []


def test_runtime_rejects_two_artifacts():
    m = {
        "name": "orders",
        "functions": {"worker": {"runtime": "python:3.11", "package": "./s", "image": "x:1"}},
    }
    assert _validate(m) != []


def test_bad_runtime_value_rejected():
    m = {"name": "orders", "functions": {"worker": {"runtime": "ruby:3", "package": "./s"}}}
    assert _validate(m) != []


def test_container_function_no_runtime_still_valid():
    m = {"name": "orders", "functions": {"worker": {"image": "myacr.io/x:1"}}}
    assert _validate(m) == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -k "runtime or package or container_function" -v`
Expected: the new tests FAIL (schema does not yet know `runtime`/`package`; `additionalProperties:false` rejects them).

- [ ] **Step 3: Edit the schema**

In `terraform/schema/cloud-app.schema.json`, in `$defs.function.properties`, add:

```json
"runtime": {
  "type": "string",
  "enum": [
    "dotnet-isolated:8.0",
    "dotnet-isolated:9.0",
    "node:20",
    "node:22",
    "python:3.11",
    "python:3.12",
    "java:17",
    "java:21",
    "powershell:7.4"
  ]
},
"package": {
  "type": "string",
  "minLength": 1
}
```

Replace the `$defs.function.allOf` array (currently only the image/docker `not`) with:

```json
"allOf": [
  { "not": { "required": ["image", "docker"] } },
  { "not": { "required": ["image", "package"] } },
  { "not": { "required": ["docker", "package"] } },
  { "if": { "required": ["package"] }, "then": { "required": ["runtime"] } },
  {
    "if": { "required": ["runtime"] },
    "then": {
      "oneOf": [
        { "required": ["image"] },
        { "required": ["docker"] },
        { "required": ["package"] }
      ]
    }
  }
]
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add terraform/schema/cloud-app.schema.json engine/tests/py/test_manifest.py
git commit -m "feat(schema): add runtime/package to functions for code deploy"
```

---

### Task 2: `manifest.function_mode` helper + docker-build gate excludes code functions

**Files:**

- Modify: `engine/cloudapp/manifest.py`
- Test: `engine/tests/py/test_manifest.py`

**Interfaces:**

- Produces:
  - `manifest.function_mode(fn: dict) -> str` — returns `"code"` if `"runtime" in fn` else `"container"`.
  - `manifest._uses_docker_build(tool)` updated so a code-mode function's `docker` builder is **not** counted as an ACR docker build.
- Consumed by: Task 3 (`builds.py`), Task 5 (`funcdeploy`/`funcpackage`), the composite action's `docker` output.

- [ ] **Step 1: Write failing tests**

Add to `engine/tests/py/test_manifest.py`:

```python
def test_function_mode():
    assert manifest.function_mode({"runtime": "python:3.11", "package": "./s"}) == "code"
    assert manifest.function_mode({"image": "x:1"}) == "container"
    assert manifest.function_mode({"docker": {"file": "./Dockerfile"}}) == "container"


def test_docker_gate_ignores_code_functions():
    # A code function whose builder is a Dockerfile must NOT flip the ACR docker gate.
    tool = {"functions": {"w": {"runtime": "dotnet-isolated:8.0", "docker": {"file": "./Dockerfile.build"}}}}
    assert manifest._uses_docker_build(tool) is False


def test_docker_gate_still_true_for_container_function():
    tool = {"functions": {"w": {"docker": {"file": "./Dockerfile"}}}}
    assert manifest._uses_docker_build(tool) is True
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -k "function_mode or docker_gate" -v`
Expected: FAIL (`function_mode` missing; `_uses_docker_build` counts the code builder).

- [ ] **Step 3: Implement**

In `engine/cloudapp/manifest.py`, add near the top (after `SHORTHAND_FIELDS`):

```python
def function_mode(fn):
    """"code" when the function declares a runtime stack, else "container"."""
    return "code" if "runtime" in fn else "container"
```

Replace `_uses_docker_build` with:

```python
def _uses_docker_build(tool):
    containers = [
        c
        for app in (tool.get("apps") or {}).values()
        for c in app["containers"].values()
    ]
    container_functions = [
        f for f in (tool.get("functions") or {}).values()
        if function_mode(f) == "container"
    ]
    return any("docker" in e for e in containers + container_functions)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/cloudapp/manifest.py engine/tests/py/test_manifest.py
git commit -m "feat(manifest): function_mode helper; exclude code funcs from docker gate"
```

---

### Task 3: `builds.py` — skip ACR push for code functions

**Files:**

- Modify: `engine/cloudapp/builds.py`
- Create: `engine/tests/fixtures/manifests/codefn.yml`
- Create: `engine/tests/golden/builds.codefn.json`
- Test: `engine/tests/py/test_builds.py`

**Interfaces:**

- Consumes: `manifest.function_mode` (Task 2).
- Produces: `builds.enumerate_builds` excludes code-mode functions from both `builds` and `tags`. The `codefn` manifest fixture is reused by Task 6's Terraform fixture.

- [ ] **Step 1: Add the fixture manifest**

Create `engine/tests/fixtures/manifests/codefn.yml` (`conftest.FIXTURES` and the Task 6 generator both read `tests/fixtures/manifests/`):

```yaml
name: codefn
functions:
  worker:
    runtime: python:3.11
    package: ./scripts
  builder:
    runtime: dotnet-isolated:8.0
    docker: { file: ./Dockerfile.build }
  legacy:
    image: myacr.azurecr.io/legacy:1.0
environments:
  dev: {}
```

- [ ] **Step 2: Write the failing test**

Add to `engine/tests/py/test_builds.py` parametrize list a new case, and rely on the existing golden assertion:

```python
@pytest.mark.parametrize(
    ("fixture", "env", "name"),
    [
        ("minimal", "dev", "orders-api"),
        ("full", "prod", "orders-api"),
        ("multi", "dev", "billing"),
        ("partial", "dev", "partial"),
        ("codefn", "dev", "codefn"),
    ],
)
def test_build_plan_matches_golden(fixture, env, name):
    _, _, tools, _ = manifest.parse(FIXTURES / f"{fixture}.yml")
    plan = builds.enumerate_builds(tools[env], name, "acr.example.io", "shaabc")
    assert plan == load_golden(f"builds.{fixture}")
```

Create the expected golden `engine/tests/golden/builds.codefn.json` (only the container function `legacy` survives; code functions are excluded):

```json
{
  "builds": [],
  "tags": {
    "legacy": "acr.example.io/codefn/legacy:shaabc"
  }
}
```

- [ ] **Step 3: Run test, verify it fails**

Run: `cd engine && python3 -m pytest tests/py/test_builds.py -k codefn -v`
Expected: FAIL — current `enumerate_builds` adds `worker` and `builder` (they lack `image`) as `./Dockerfile` builds, so `builds`/`tags` won't match.

- [ ] **Step 4: Implement**

In `engine/cloudapp/builds.py`, add the import and guard the functions loop:

```python
from .manifest import function_mode
```

Change the functions loop in `enumerate_builds`:

```python
    for function_key, function in (tool.get("functions") or {}).items():
        if function_mode(function) == "code":
            continue
        if "image" not in function:
            entries.append((function_key, function.get("docker", {})))
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_builds.py -v`
Expected: PASS (all fixtures, including `codefn`).

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/builds.py engine/tests/py/test_builds.py engine/tests/fixtures/manifests/codefn.yml engine/tests/golden/builds.codefn.json
git commit -m "feat(builds): exclude code-mode functions from ACR builds"
```

---

### Task 4: `funcpackage.py` — produce a deploy zip per code function

**Files:**

- Create: `engine/cloudapp/funcpackage.py`
- Test: `engine/tests/py/test_funcpackage.py`

**Interfaces:**

- Consumes: `manifest.function_mode` (Task 2).
- Produces:
  - `funcpackage.code_functions(tool: dict) -> dict[str, dict]` — `{function_key: function}` for code-mode functions only.
  - `funcpackage.package(key: str, fn: dict, workdir: str, run) -> str` — returns the path to a `.zip`. For `package` (zip mode) it zips the directory; for a builder (`docker`/`image`) it runs the builder container with `/out` mounted, then zips `/out`. `run` is `runner.run`-compatible: `run(cmd_list)`.

- [ ] **Step 1: Write failing tests**

Create `engine/tests/py/test_funcpackage.py`:

```python
import os
import zipfile
from pathlib import Path

from cloudapp import funcpackage


def test_code_functions_filters_by_mode():
    tool = {
        "functions": {
            "a": {"runtime": "python:3.11", "package": "./s"},
            "b": {"image": "x:1"},
        }
    }
    assert list(funcpackage.code_functions(tool)) == ["a"]


def test_package_zip_mode_zips_directory(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hi')\n")
    workdir = tmp_path / "work"
    workdir.mkdir()

    calls = []

    def run(cmd, **kw):
        calls.append(cmd)

    zip_path = funcpackage.package("worker", {"runtime": "python:3.11", "package": str(src)}, str(workdir), run)

    assert calls == []  # no docker in zip mode
    with zipfile.ZipFile(zip_path) as z:
        assert "app.py" in z.namelist()


def test_package_build_mode_runs_builder_and_zips_out(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        # emulate the builder writing to the mounted /out dir
        if cmd[0] == "docker" and cmd[1] == "run":
            out_host = cmd[cmd.index("-v") + 1].split(":")[0]
            Path(out_host, "func.dll").write_text("binary")

    fn = {"runtime": "dotnet-isolated:8.0", "docker": {"file": "./Dockerfile.build", "context": "."}}
    zip_path = funcpackage.package("worker", fn, str(workdir), run)

    kinds = [c[1] for c in calls if c[0] == "docker"]
    assert "build" in kinds and "run" in kinds
    with zipfile.ZipFile(zip_path) as z:
        assert "func.dll" in z.namelist()


def test_package_build_mode_prebuilt_image_skips_build(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "docker" and cmd[1] == "run":
            out_host = cmd[cmd.index("-v") + 1].split(":")[0]
            Path(out_host, "index.js").write_text("x")

    fn = {"runtime": "node:20", "image": "myreg/builder:1"}
    funcpackage.package("worker", fn, str(workdir), run)

    kinds = [c[1] for c in calls if c[0] == "docker"]
    assert "build" not in kinds and "run" in kinds
    # runs the named image directly
    run_cmd = next(c for c in calls if c[:2] == ["docker", "run"])
    assert "myreg/builder:1" in run_cmd
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_funcpackage.py -v`
Expected: FAIL (`funcpackage` module does not exist).

- [ ] **Step 3: Implement `funcpackage.py`**

Create `engine/cloudapp/funcpackage.py`:

```python
"""Produce a deployable zip for each code-mode function.

Zip mode (`package:`): archive the directory as-is.
Builder mode (`docker:`/`image:`): run a throwaway builder container with a
host dir mounted at /out; the builder writes its build output there; zip /out.
"""

import shutil
import tempfile
from pathlib import Path

from .manifest import function_mode

OUT_MOUNT = "/out"


def code_functions(tool):
    return {
        k: fn
        for k, fn in (tool.get("functions") or {}).items()
        if function_mode(fn) == "code"
    }


def _zip_dir(src_dir, dest_base):
    # make_archive appends ".zip"; return the actual path.
    return shutil.make_archive(str(dest_base), "zip", root_dir=str(src_dir))


def package(key, fn, workdir, run):
    """Return the path to a zip of the function's deployable content."""
    workdir = Path(workdir)
    dest_base = workdir / key

    if "package" in fn:
        return _zip_dir(fn["package"], dest_base)

    out_dir = Path(tempfile.mkdtemp(prefix=f"out-{key}-", dir=str(workdir)))

    if "docker" in fn:
        docker = fn["docker"]
        image = f"cloudapp-builder-{key}"
        run(["docker", "build", "-f", docker.get("file", "./Dockerfile"),
             "-t", image, docker.get("context", ".")])
    else:
        image = fn["image"]

    run(["docker", "run", "--rm", "-v", f"{out_dir}:{OUT_MOUNT}", image])
    return _zip_dir(out_dir, dest_base)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_funcpackage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/cloudapp/funcpackage.py engine/tests/py/test_funcpackage.py
git commit -m "feat(funcpackage): zip code functions via package dir or builder container"
```

---

### Task 5: `funcdeploy.py` + `deploy-functions` CLI command

**Files:**

- Create: `engine/cloudapp/funcdeploy.py`
- Modify: `engine/cloudapp/cli.py`
- Test: `engine/tests/py/test_funcdeploy.py`

**Interfaces:**

- Consumes: `funcpackage.code_functions`, `funcpackage.package` (Task 4); `backend.render` (existing, `backend.render(platform_path, tool_name, env, stack="main") -> list[str]`).
- Produces:
  - `funcdeploy.deploy(tool, tf_dir, backend_lines, workdir, run) -> list[str]` — inits Terraform (to read outputs authoritatively even when the apply was skipped), reads `terraform output -json names`, and for each code function packages a zip and runs `az functionapp deployment source config-zip`. Returns the list of deployed function-app names.
  - CLI: `python3 -m cloudapp deploy-functions --terraform-dir --tfvars-file --tool-json --tool-name --environment --platform-file`.

- [ ] **Step 1: Write failing tests**

Create `engine/tests/py/test_funcdeploy.py`:

```python
import json

from cloudapp import funcdeploy


def _names_json():
    return json.dumps({
        "resource_group": "rg-orders-dev",
        "functions": {"worker": "func-orders-dev"},
    })


def test_deploy_packages_and_config_zips(tmp_path, monkeypatch):
    tool = {"name": "orders", "functions": {"worker": {"runtime": "python:3.11", "package": str(tmp_path)}}}
    calls = []

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "terraform" and "output" in cmd:
            return Result(_names_json())
        return Result("")

    # stub packaging so the test does not shell out to zip internals
    monkeypatch.setattr(funcdeploy.funcpackage, "package", lambda k, fn, wd, r: f"/w/{k}.zip")

    deployed = funcdeploy.deploy(tool, "/tf", ["key=v"], str(tmp_path), run)

    assert deployed == ["func-orders-dev"]
    assert ["terraform", "-chdir=/tf", "init", "-input=false", "-backend-config=key=v"] in calls
    config_zip = next(c for c in calls if c[:2] == ["az", "functionapp"])
    assert "func-orders-dev" in config_zip
    assert "rg-orders-dev" in config_zip
    assert "/w/worker.zip" in config_zip


def test_deploy_noop_when_no_code_functions(tmp_path):
    tool = {"name": "orders", "functions": {"c": {"image": "x:1"}}}
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        raise AssertionError("run must not be called when there are no code functions")

    assert funcdeploy.deploy(tool, "/tf", ["key=v"], str(tmp_path), run) == []
    assert calls == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_funcdeploy.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `funcdeploy.py`**

Create `engine/cloudapp/funcdeploy.py`:

```python
"""Deploy code-mode functions: terraform output -> package -> config-zip.

Runs after `terraform apply`. Re-inits Terraform so function-app names are read
from state authoritatively even on manifest-unchanged runs where the apply was
skipped. Must run on a runner with network access to the (private) SCM endpoint.
"""

import json

from . import funcpackage

INPUT_FALSE = "-input=false"


def deploy(tool, tf_dir, backend_lines, workdir, run):
    functions = funcpackage.code_functions(tool)
    if not functions:
        return []

    tf = ["terraform", f"-chdir={tf_dir}"]
    run(tf + ["init", INPUT_FALSE] + [f"-backend-config={line}" for line in backend_lines])
    result = run(tf + ["output", "-json", "names"], capture=True)
    names = json.loads(result.stdout)
    rg = names["resource_group"]
    func_names = names["functions"]

    deployed = []
    for key, fn in functions.items():
        app_name = func_names[key]
        zip_path = funcpackage.package(key, fn, workdir, run)
        run([
            "az", "functionapp", "deployment", "source", "config-zip",
            "-g", rg, "-n", app_name, "--src", zip_path,
        ])
        deployed.append(app_name)
    return deployed
```

- [ ] **Step 4: Wire the CLI command**

In `engine/cloudapp/cli.py`, add `funcdeploy` and `backend` are already imported (`backend` is). Add the import:

```python
from . import (
    backend,
    builds,
    dockerbuild,
    funcdeploy,
    gha,
    identity,
    manifest,
    registry,
    resolve,
    runner,
    secrets,
    tfdeploy,
)
```

Add the command handler (after `cmd_terraform_deploy`):

```python
def cmd_deploy_functions(args):
    import tempfile

    tool = _load_json(args.tool_json)
    backend_lines = backend.render(args.platform_file, args.tool_name, args.environment, stack="main")
    with tempfile.TemporaryDirectory(prefix="funcpkg-") as workdir:
        deployed = funcdeploy.deploy(tool, args.terraform_dir, backend_lines, workdir, runner.run)
    gha.write_outputs({"deployed": json.dumps(deployed, separators=(",", ":"))})
```

Register the subparser (in `main`, after the `terraform-deploy` parser):

```python
    p = sub.add_parser("deploy-functions")
    p.add_argument("--terraform-dir", required=True)
    p.add_argument("--tool-json", required=True)
    p.add_argument("--tool-name", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--platform-file", required=True)
    p.set_defaults(func=cmd_deploy_functions)
```

Add `funcdeploy` failures to the caught exceptions if it defines its own error type — it does not, so no change to the `except` tuple is needed.

- [ ] **Step 5: Run tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_funcdeploy.py tests/py/test_cli.py -v`
Expected: PASS (new tests pass; existing CLI tests unaffected).

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/funcdeploy.py engine/cloudapp/cli.py engine/tests/py/test_funcdeploy.py
git commit -m "feat(funcdeploy): config-zip code functions after apply"
```

---

### Task 6: Terraform function module — native `application_stack`

**Files:**

- Modify: `terraform/azure/modules/function/main.tf`
- Modify: `terraform/azure/modules/function/outputs.tf`
- Modify: `engine/generate_tf_fixtures.py` (add `codefn` to `CASES`)
- Create (generated): `terraform/azure/tests/fixtures/tfvars.codefn.dev.json`
- Create: `terraform/azure/tests/codefn.tftest.hcl`

**Interfaces:**

- Consumes: `var.function` may carry `runtime` (string `stack:version`) instead of an image; the `codefn` manifest fixture from Task 3.
- Produces: module renders a native `application_stack` when `runtime` is set and no `docker` block otherwise; new output `runtime_stack`.

- [ ] **Step 1: Generate the Terraform fixture from the real pipeline**

Do not hand-author the tfvars — generate it so the CI fixture-drift check (`generate_tf_fixtures.py` then `git diff --exit-code terraform/azure/tests/fixtures`) stays green. In `engine/generate_tf_fixtures.py`, add `codefn` to `CASES`:

```python
CASES = [
    ("minimal", "dev"),
    ("full", "prod"),
    ("multi", "dev"),
    ("partial", "dev"),
    ("databases", "dev"),
    ("codefn", "dev"),
]
```

Run: `python3 engine/generate_tf_fixtures.py`
Expected: prints `wrote terraform/azure/tests/fixtures/tfvars.codefn.dev.json` (and rewrites the existing five with no diff). This resolves the Task 3 `codefn.yml` manifest through `manifest.parse` + `resolve.resolve`, so the `platform` block matches exactly what the root module expects — no guessing.

- [ ] **Step 2: Write the failing Terraform test**

Create `terraform/azure/tests/codefn.tftest.hcl` (asserts all three modes — python code, dotnet builder, container image — resolved from the one fixture):

```hcl
mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.codefn.dev.json")).config
  image_tags = {}
}

run "code_function_uses_runtime_stack" {
  command = plan

  assert {
    condition     = module.function["worker"].runtime_stack == "python:3.11"
    error_message = "python code function must surface its runtime stack"
  }
  assert {
    condition     = module.function["worker"].docker_image == null
    error_message = "code function must not render a docker application stack"
  }
  assert {
    condition     = module.function["builder"].runtime_stack == "dotnet-isolated:8.0"
    error_message = "dotnet builder function must surface its runtime stack"
  }
  assert {
    condition     = module.function["builder"].docker_image == null
    error_message = "builder-mode function must not render a docker application stack"
  }
  assert {
    condition     = module.function["legacy"].runtime_stack == null
    error_message = "container function must have no runtime stack"
  }
  assert {
    condition     = module.function["legacy"].docker_image != null
    error_message = "container function must still render a docker application stack"
  }
  assert {
    condition     = module.function["worker"].plan_sku == "EP1"
    error_message = "code function must still run on EP1"
  }
}
```

- [ ] **Step 3: Run the test, verify it fails**

Run: `terraform -chdir=terraform/azure test -filter=tests/codefn.tftest.hcl`
Expected: FAIL — the module has a precondition requiring an image (the `worker`/`builder` functions have none), and there is no `runtime_stack` output.

- [ ] **Step 4: Implement in the module**

In `terraform/azure/modules/function/main.tf`, extend `locals` (append inside the existing `locals { ... }` block):

```hcl
  runtime       = try(var.function.runtime, null)
  runtime_stack = local.runtime != null ? split(":", local.runtime)[0] : null
  runtime_ver   = local.runtime != null ? split(":", local.runtime)[1] : null
```

Replace the `site_config` block's `application_stack` handling with both branches (keep the existing container-registry managed-identity settings):

```hcl
  site_config {
    container_registry_use_managed_identity       = local.image != null
    container_registry_managed_identity_client_id = local.image != null ? azurerm_user_assigned_identity.this.client_id : null

    dynamic "application_stack" {
      for_each = local.image != null ? [1] : []
      content {
        docker {
          registry_url = "https://${local.image_registry}"
          image_name   = local.image_repo
          image_tag    = local.image_tag_part
        }
      }
    }

    dynamic "application_stack" {
      for_each = local.runtime != null ? [1] : []
      content {
        dotnet_version              = local.runtime_stack == "dotnet-isolated" ? local.runtime_ver : null
        use_dotnet_isolated_runtime = local.runtime_stack == "dotnet-isolated" ? true : null
        node_version                = local.runtime_stack == "node" ? local.runtime_ver : null
        python_version              = local.runtime_stack == "python" ? local.runtime_ver : null
        java_version                = local.runtime_stack == "java" ? local.runtime_ver : null
        powershell_core_version     = local.runtime_stack == "powershell" ? local.runtime_ver : null
      }
    }
  }
```

Relax the precondition:

```hcl
  lifecycle {
    precondition {
      condition     = local.image != null || local.runtime != null
      error_message = "function has no image and no runtime: set a container image (or docker build) for container mode, or a runtime for code mode"
    }
  }
```

In `terraform/azure/modules/function/outputs.tf`, add:

```hcl
output "runtime_stack" {
  description = "The manifest runtime value (stack:version), null for container functions"
  value       = local.runtime
}
```

- [ ] **Step 5: Run tests, verify pass**

Run: `terraform -chdir=terraform/azure test`
Expected: PASS (new `codefn` test and all existing tests — the container `partial` function still asserts `docker_image` correctly).

- [ ] **Step 6: `terraform fmt` + commit**

```bash
terraform -chdir=terraform/azure fmt
git add terraform/azure/modules/function terraform/azure/tests/codefn.tftest.hcl terraform/azure/tests/fixtures/tfvars.codefn.dev.json engine/generate_tf_fixtures.py
git commit -m "feat(tf): native application_stack for code functions"
```

---

### Task 7: Composite action — post-apply code-function deploy

**Files:**

- Modify: `.github/actions/cloud-app/action.yml`
- Modify: `engine/cloudapp/cli.py` (parse-manifest emits a `code_functions` output)
- Test: `engine/tests/py/test_cli.py` (parse-manifest output includes `code_functions`)

**Interfaces:**

- Consumes: `funcdeploy` CLI (Task 5); `manifest.function_mode` (Task 2).
- Produces: `parse-manifest` writes output `code_functions=true|false`; the action runs `deploy-functions` after Terraform, whenever `plan_only == 'false'` and `code_functions == 'true'`.

- [ ] **Step 1: Write the failing test**

Add to `engine/tests/py/test_cli.py` a test that runs `parse-manifest` on the `codefn` fixture and asserts the emitted outputs contain `code_functions=true`. Follow the existing parse-manifest test pattern in that file (locate it first). Example shape:

```python
def test_parse_manifest_flags_code_functions(tmp_path):
    out_dir = tmp_path / "out"
    rc = main([
        "parse-manifest",
        "--manifest", str(FIXTURES / "codefn.yml"),  # FIXTURES = tests/fixtures/manifests
        "--output-dir", str(out_dir),
        "--app-root", str(tmp_path),
    ])
    assert rc == 0
    outputs = (out_dir / "outputs.txt").read_text()
    assert "code_functions=true" in outputs
```

(Use the same `FIXTURES`/`main` imports the existing tests in `test_cli.py` use.)

- [ ] **Step 2: Run test, verify it fails**

Run: `cd engine && python3 -m pytest tests/py/test_cli.py -k code_functions -v`
Expected: FAIL — no such output.

- [ ] **Step 3: Implement the parse signal in the CLI**

Do **not** change `manifest.parse`'s return arity — it is unpacked as a 4-tuple in ~20 call sites (tests + `generate_tf_fixtures.py`). Instead compute `code_functions` inside `cmd_parse_manifest` from the `tools` it already returns, using the public `manifest.function_mode` from Task 2.

In `engine/cloudapp/cli.py`, replace `cmd_parse_manifest`:

```python
def cmd_parse_manifest(args):
    name, environments, tools, docker = manifest.parse(args.manifest, args.app_root)
    code_functions = any(
        manifest.function_mode(f) == "code"
        for tool in tools.values()
        for f in (tool.get("functions") or {}).values()
    )
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in list(out.glob("tool.*.json")) + [out / "outputs.txt"]:
        if stale.exists():
            stale.unlink()
    for env, tool in tools.items():
        _write_json(out / f"tool.{env}.json", tool)
    gha.write_outputs(
        {
            "name": name,
            "environments": json.dumps(environments, separators=(",", ":")),
            "docker": str(docker).lower(),
            "code_functions": str(code_functions).lower(),
        },
        fallback_file=out / "outputs.txt",
    )
```

No other call site changes — `manifest.parse` still returns its 4-tuple.

- [ ] **Step 4: Add the action output + deploy step**

In `.github/actions/cloud-app/action.yml`, add to `outputs:`:

```yaml
code_functions:
  description: Whether any environment declares a code (runtime) function
  value: ${{ steps.parse.outputs.code_functions }}
```

After the `Terraform deploy` step (the one with `id: deploy`), add:

```yaml
# Code (non-container) functions deploy their zip after apply, via the SCM
# endpoint. Runs on the caller's runner — in production a VNet self-hosted
# runner that can reach the private SCM endpoint. Independent of the apply
# gate: a code change on an unchanged manifest still needs the zip pushed.
- name: Deploy code functions
  if: ${{ inputs.plan_only == 'false' && steps.parse.outputs.code_functions == 'true' }}
  shell: bash
  env:
    DEPLOY_ENV: ${{ inputs.env }}
  run: >-
    PYTHONPATH="${{ github.action_path }}/../../../engine"
    python3 -m cloudapp deploy-functions
    --terraform-dir "${{ github.action_path }}/../../../terraform/azure"
    --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
    --tool-name "${{ steps.parse.outputs.name }}"
    --environment "$DEPLOY_ENV"
    --platform-file "${{ steps.platform.outputs.file }}"
```

- [ ] **Step 5: Run tests + actionlint, verify pass**

Run:

```bash
cd engine && python3 -m pytest tests/py -q
```

Expected: PASS (all).
Run (from repo root, if actionlint is installed as CI uses it):

```bash
actionlint .github/actions/cloud-app/action.yml || echo "actionlint not installed locally — CI will check"
```

- [ ] **Step 6: Commit**

```bash
git add .github/actions/cloud-app/action.yml engine/cloudapp/cli.py engine/tests/py/test_cli.py
git commit -m "feat(action): deploy code functions after apply"
```

---

### Task 8: Docs + sample

**Files:**

- Modify: `README.md`
- Modify: `docs/usage.md`
- Modify: `samples/caller-app/cloud-app.yml`
- Modify: `samples/caller-app/.github/workflows/cloud-app.yml`

**Interfaces:** none (documentation only). Must accurately reflect Tasks 1–7.

- [ ] **Step 1: README manifest section**

In `README.md`, under "Manifest at a glance", update the compute bullet to mention code functions. Add after the existing functions/static-sites bullet:

```markdown
- A `functions:` entry deploys a container by default. Add `runtime:`
  (`dotnet-isolated:8.0`, `node:20`, `python:3.11`, `java:17`, `powershell:7.4`, …)
  to deploy application code instead: supply `package:` (a directory zipped as-is)
  or a `docker`/`image` **builder** that writes build output to `/out` (zipped and
  shipped via `config-zip` after apply). Code functions require a runner that can
  reach the app's SCM endpoint — a VNet self-hosted runner when private.
```

- [ ] **Step 2: usage.md reference**

In `docs/usage.md`, add a "Code (non-container) functions" subsection near the functions documentation, covering: the `runtime` enum, the three artifact keys, the `/out` builder convention, the post-apply `config-zip` step, and the runner requirement. Include a worked example:

```yaml
functions:
  worker:
    runtime: dotnet-isolated:8.0
    docker: { file: ./Dockerfile.build } # builder writes /out
  cron:
    runtime: python:3.11
    package: ./cron # zipped as-is, no build
```

- [ ] **Step 3: Sample manifest + workflow**

In `samples/caller-app/cloud-app.yml`, add a code function example (a commented block is fine if adding a live one would require a builder Dockerfile that the sample lacks). In `samples/caller-app/.github/workflows/cloud-app.yml`, add a comment above `runs-on:` noting that private deployments must target a VNet self-hosted runner, e.g.:

```yaml
# For code (runtime) functions with a private SCM endpoint, set this to a
# self-hosted runner inside the VNet, e.g. runs-on: [self-hosted, vnet-dev]
runs-on: ubuntu-latest
```

- [ ] **Step 4: Verify docs build / links**

Run: `cd engine && python3 -m pytest tests/py -q` (guards against any doc-embedded fixture drift check).
Manually re-read the three edited docs for accuracy against Tasks 1–7.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/usage.md samples/caller-app
git commit -m "docs: code (non-container) functions"
```

---

## Final verification

- [ ] Run full engine suite: `cd engine && python3 -m pytest tests/py -q` → all pass.
- [ ] Run Terraform tests: `terraform -chdir=terraform/azure test` → all pass.
- [ ] `terraform -chdir=terraform/azure fmt -check` and `cd engine && ruff check .` → clean.
- [ ] Fixture-drift check (the CI step): run `python3 engine/generate_tf_fixtures.py` then `git diff --exit-code terraform/azure/tests/fixtures` → clean. The `tfvars.codefn.dev.json` fixture is generated (Task 6 added `codefn` to `CASES`); the `builds.codefn.json` golden is hand-authored (the builds goldens are not generated by that script — confirm no generator owns `engine/tests/golden/builds.*.json`).
