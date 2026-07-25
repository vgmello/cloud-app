# Caller-supplied Terraform (`terraform:` field) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an app team ship extra Terraform in their own repo that deploys alongside the platform stack, confined to their resource group by the RG-scoped apply identity.

**Architecture:** A new optional manifest field `terraform:` names a directory of `*.tf` in the caller repo. The platform ships an empty `custom/` child module under `terraform/azure/`; the root module always calls it, passing a curated context (RG, location, subnets, Key Vault, per-app/function identity principal ids). Before `terraform init`, the action copies the caller's `.tf` into `custom/` and generates a `required_providers` file from a manifest-declared, allowlisted provider list. Because this lives in the main stack, it inherits the existing plan/apply identity gating — the apply identity is Contributor on the RG only, and that scope is the confinement.

**Tech Stack:** Python 3 (engine, pytest), Terraform (azurerm 4.x, `terraform test`), JSON Schema (Draft 2020-12), GitHub composite action (bash).

## Global Constraints

- Trusted, additive model. The security boundary is the RG-scoped apply identity, **not** sandboxing the Terraform. Do not build state isolation or a separate identity.
- Provider allowlist — exactly these `name` → `source` pairs are permitted, and a declared `source` must match its `name`'s canonical source:
  - `random` → `hashicorp/random`
  - `null` → `hashicorp/null`
  - `tls` → `hashicorp/tls`
  - `time` → `hashicorp/time`
  - `local` → `hashicorp/local`
  - `external` → `hashicorp/external`
  - `azuread` → `hashicorp/azuread`
  - `azapi` → `Azure/azapi`
- The `custom/` module is declared **unconditionally** in the root module. With no caller files it must create zero resources and plan clean.
- Platform-owned files inside `custom/` are `_`-prefixed (`_context.tf`, `_versions.tf`, generated `_providers.g.tf`). Caller files must **not** start with `_`.
- Copy only `*.tf` and `*.tf.json`, top level only (no subdirectories).
- Reject a `dir` that is absolute or contains a `..` segment.
- Reject caller files containing a top-level `provider "`, `terraform {`, or `backend "` block.
- `local-exec`, `data "external"`, and `data "terraform_remote_state"` are **allowed** — documented residual risk, not blocked.
- Real names in this codebase (use these verbatim, they were verified against the tree):
  - Root locals: `local.rg_name`, `local.base`, `local.env`, `local.platform.location`, `local.platform.network.vnet_id`, `local.platform.network.subnets`.
  - The RG is consumed via `data.azurerm_resource_group.this.name`.
  - Subnet keys are `private_endpoints` and `functions` (there is **no** `apps` subnet).
  - Key Vault module outputs: `module.keyvault.id`, `module.keyvault.vault_uri`.
  - Container-app module already outputs `identity_principal_id`. The function module does **not** — Task 4 adds it.
- Style: match existing files. No new Python dependencies. Keep `ruff` clean (no unused imports) and `terraform fmt` clean.

---

### Task 1: Schema — `terraform` field + provider allowlist

**Files:**

- Modify: `terraform/schema/cloud-app.schema.json`
- Test: `engine/tests/py/test_manifest.py`

**Interfaces:**

- Produces: the manifest schema accepts a top-level `terraform` that is either a string or `{dir, providers}`, with the allowlist enforced. Consumed by `manifest.validate`.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_manifest.py`:

```python
def test_terraform_shorthand_string_is_valid():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": "./terraform"}
    assert manifest.validate(m) == []


def test_terraform_object_with_providers_is_valid():
    m = {
        "name": "orders",
        "app": {"port": 8080},
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}],
        },
    }
    assert manifest.validate(m) == []


def test_terraform_object_requires_dir():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": {"providers": []}}
    assert manifest.validate(m) != []


def test_terraform_rejects_non_allowlisted_provider():
    m = {
        "name": "orders",
        "app": {"port": 8080},
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "aws", "source": "hashicorp/aws", "version": "~> 5"}],
        },
    }
    assert manifest.validate(m) != []


def test_terraform_rejects_parent_escape_dir():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": "../evil"}
    assert manifest.validate(m) != []


def test_terraform_rejects_absolute_dir():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": "/etc"}
    assert manifest.validate(m) != []


def test_terraform_allowed_in_environment_overlay():
    m = {
        "name": "orders",
        "app": {"port": 8080},
        "environments": {"prod": {"terraform": "./terraform-prod"}},
    }
    assert manifest.validate(m) == []
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -k terraform -v`
Expected: FAIL — the top-level schema sets `additionalProperties: false`, so `terraform` is rejected outright.

- [ ] **Step 3: Edit the schema**

In `terraform/schema/cloud-app.schema.json`, add to `$defs` a `custom_terraform` and a `provider_ref`:

```json
"provider_ref": {
  "type": "object",
  "additionalProperties": false,
  "required": ["name", "source", "version"],
  "properties": {
    "name": {
      "type": "string",
      "enum": ["random", "null", "tls", "time", "local", "external", "azuread", "azapi"]
    },
    "source": { "type": "string", "minLength": 1 },
    "version": { "type": "string", "minLength": 1 }
  }
},
"custom_terraform": {
  "oneOf": [
    { "type": "string", "minLength": 1, "pattern": "^(?!/)(?!.*\\.\\.).+$" },
    {
      "type": "object",
      "additionalProperties": false,
      "required": ["dir"],
      "properties": {
        "dir": { "type": "string", "minLength": 1, "pattern": "^(?!/)(?!.*\\.\\.).+$" },
        "providers": { "type": "array", "items": { "$ref": "#/$defs/provider_ref" } }
      }
    }
  ]
}
```

Add to the top-level `properties`:

```json
"terraform": { "$ref": "#/$defs/custom_terraform" }
```

Add the same line to `$defs.overlay.properties` so per-environment overrides validate.

> The `^(?!/)(?!.*\.\.).+$` lookahead was verified against this repo's installed `jsonschema` (Draft202012Validator): `./terraform` and `terraform/x` accept; `../evil`, `/etc`, and `a/../b` reject. `customtf._resolve_dir` (Task 3) enforces the same boundary again at copy time — belt and braces, since the schema only guards the manifest, not a path assembled at runtime.

- [ ] **Step 4: Run the tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -v`
Expected: PASS (all, new and pre-existing).

- [ ] **Step 5: Commit**

```bash
git add terraform/schema/cloud-app.schema.json engine/tests/py/test_manifest.py
git commit -m "feat(schema): add terraform field with provider allowlist"
```

---

### Task 2: Engine — normalize `terraform` shorthand

**Files:**

- Modify: `engine/cloudapp/manifest.py`
- Test: `engine/tests/py/test_manifest.py`

**Interfaces:**

- Produces: after `normalize`, `cfg["terraform"]` (when present) is always the object form `{"dir": str, "providers": list}`. Consumed by Task 3 (`customtf`) and Task 6 (the action's parse signal).

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_manifest.py`:

```python
def test_normalize_terraform_shorthand_folds_to_object():
    cfg = manifest.normalize({"name": "orders", "terraform": "./terraform"})
    assert cfg["terraform"] == {"dir": "./terraform", "providers": []}


def test_normalize_terraform_object_defaults_providers():
    cfg = manifest.normalize({"name": "orders", "terraform": {"dir": "./tf"}})
    assert cfg["terraform"] == {"dir": "./tf", "providers": []}


def test_normalize_terraform_object_keeps_providers():
    providers = [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}]
    cfg = manifest.normalize({"name": "orders", "terraform": {"dir": "./tf", "providers": providers}})
    assert cfg["terraform"] == {"dir": "./tf", "providers": providers}


def test_normalize_without_terraform_leaves_key_absent():
    cfg = manifest.normalize({"name": "orders"})
    assert "terraform" not in cfg
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -k normalize_terraform -v`
Expected: FAIL — `normalize` passes `terraform` through unchanged, so the shorthand string is not folded.

- [ ] **Step 3: Implement**

In `engine/cloudapp/manifest.py`, add this helper next to the other module-level helpers (after `function_mode`):

```python
def normalize_terraform(value):
    """Fold the `terraform:` shorthand string into the {dir, providers} object."""
    entry = {"dir": value} if isinstance(value, str) else dict(value)
    entry.setdefault("providers", [])
    return entry
```

In `normalize`, after the `storage` handling and before `validate_db_refs(cfg)`, add:

```python
    if "terraform" in cfg:
        cfg["terraform"] = normalize_terraform(cfg["terraform"])
```

- [ ] **Step 4: Run the tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/cloudapp/manifest.py engine/tests/py/test_manifest.py
git commit -m "feat(manifest): normalize terraform shorthand to object form"
```

---

### Task 3: `customtf.py` — validate, copy, generate providers

**Files:**

- Create: `engine/cloudapp/customtf.py`
- Test: `engine/tests/py/test_customtf.py`

**Interfaces:**

- Consumes: the normalized `terraform` entry from Task 2.
- Produces:
  - `customtf.ALLOWED_PROVIDERS: dict[str, str]` — provider name → canonical source.
  - `customtf.CustomTfError(Exception)`.
  - `customtf.collect(tool: dict, app_root: str) -> list[pathlib.Path]` — resolves the dir, validates it, returns the accepted `.tf` files sorted by name. Returns `[]` when the manifest has no `terraform`.
  - `customtf.render_providers(providers: list[dict]) -> str | None` — the `_providers.g.tf` content, or `None` when the list is empty.
  - `customtf.prepare(tool: dict, app_root: str, custom_dir: str) -> list[str]` — collect + copy into `custom_dir` + write `_providers.g.tf`; returns the copied file names.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/py/test_customtf.py`:

```python
import pytest

from cloudapp import customtf


def _tool(dir_, providers=None):
    return {"terraform": {"dir": dir_, "providers": providers or []}}


def test_collect_returns_empty_without_terraform(tmp_path):
    assert customtf.collect({"name": "x"}, str(tmp_path)) == []


def test_collect_accepts_tf_files(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "queue.tf").write_text('resource "random_pet" "p" {}\n')
    (src / "notes.md").write_text("ignored\n")
    files = customtf.collect(_tool("./terraform"), str(tmp_path))
    assert [f.name for f in files] == ["queue.tf"]


def test_collect_rejects_missing_dir(tmp_path):
    with pytest.raises(customtf.CustomTfError, match="not found"):
        customtf.collect(_tool("./nope"), str(tmp_path))


def test_collect_rejects_parent_escape(tmp_path):
    with pytest.raises(customtf.CustomTfError):
        customtf.collect(_tool("../outside"), str(tmp_path))


def test_collect_rejects_reserved_underscore_name(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "_context.tf").write_text("variable \"x\" {}\n")
    with pytest.raises(customtf.CustomTfError, match="reserved"):
        customtf.collect(_tool("./terraform"), str(tmp_path))


def test_collect_rejects_provider_block(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "bad.tf").write_text('provider "azurerm" {\n  features {}\n}\n')
    with pytest.raises(customtf.CustomTfError, match="provider"):
        customtf.collect(_tool("./terraform"), str(tmp_path))


def test_collect_rejects_terraform_block(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "bad.tf").write_text('terraform {\n  backend "local" {}\n}\n')
    with pytest.raises(customtf.CustomTfError):
        customtf.collect(_tool("./terraform"), str(tmp_path))


def test_collect_allows_local_exec(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "ok.tf").write_text(
        'resource "null_resource" "r" {\n  provisioner "local-exec" {\n    command = "echo hi"\n  }\n}\n'
    )
    assert [f.name for f in customtf.collect(_tool("./terraform"), str(tmp_path))] == ["ok.tf"]


def test_render_providers_empty_is_none():
    assert customtf.render_providers([]) is None


def test_render_providers_emits_required_providers():
    body = customtf.render_providers(
        [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}]
    )
    assert "required_providers" in body
    assert 'random = {' in body
    assert 'source  = "hashicorp/random"' in body
    assert 'version = "~> 3"' in body


def test_render_providers_rejects_non_allowlisted():
    with pytest.raises(customtf.CustomTfError, match="not allowed"):
        customtf.render_providers([{"name": "aws", "source": "hashicorp/aws", "version": "~> 5"}])


def test_render_providers_rejects_source_mismatch():
    with pytest.raises(customtf.CustomTfError, match="source"):
        customtf.render_providers(
            [{"name": "random", "source": "evil/random", "version": "~> 3"}]
        )


def test_prepare_copies_files_and_writes_providers(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "queue.tf").write_text('resource "random_pet" "p" {}\n')
    custom = tmp_path / "custom"
    custom.mkdir()

    copied = customtf.prepare(
        _tool("./terraform", [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}]),
        str(tmp_path),
        str(custom),
    )

    assert copied == ["queue.tf"]
    assert (custom / "queue.tf").read_text() == 'resource "random_pet" "p" {}\n'
    assert "hashicorp/random" in (custom / "_providers.g.tf").read_text()


def test_prepare_noop_without_terraform(tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    assert customtf.prepare({"name": "x"}, str(tmp_path), str(custom)) == []
    assert not (custom / "_providers.g.tf").exists()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_customtf.py -v`
Expected: FAIL — module `cloudapp.customtf` does not exist.

- [ ] **Step 3: Implement `customtf.py`**

Create `engine/cloudapp/customtf.py`:

```python
"""Caller-supplied Terraform: validate, copy into the custom child module, and
generate its required_providers.

The caller names a directory of *.tf in the manifest (`terraform:`). Those files
are merged into the platform's `custom/` child module, which runs in the main
stack under the RG-scoped apply identity. Providers are declared in the manifest
and allowlisted here so authentication stays on the ambient Azure identity —
raw provider/terraform/backend blocks in caller files are rejected.
"""

import re
import shutil
from pathlib import Path

# provider name -> the only source allowed for it. Every entry is either
# credential-less or authenticates with the ambient apply-identity OIDC.
ALLOWED_PROVIDERS = {
    "random": "hashicorp/random",
    "null": "hashicorp/null",
    "tls": "hashicorp/tls",
    "time": "hashicorp/time",
    "local": "hashicorp/local",
    "external": "hashicorp/external",
    "azuread": "hashicorp/azuread",
    "azapi": "Azure/azapi",
}

TF_SUFFIXES = (".tf", ".tf.json")

# Top-of-line block openers the caller may not declare: providers come from the
# manifest allowlist, and the backend/terraform settings belong to the platform.
_FORBIDDEN_BLOCK = re.compile(r'^\s*(provider\s+"|terraform\s*\{|backend\s+")', re.MULTILINE)


class CustomTfError(Exception):
    pass


def _entry(tool):
    return (tool or {}).get("terraform")


def _resolve_dir(entry, app_root):
    root = Path(app_root).resolve()
    target = (root / entry["dir"]).resolve()
    if not (target == root or root in target.parents):
        raise CustomTfError(
            f"terraform dir '{entry['dir']}' escapes the repository root"
        )
    if not target.is_dir():
        raise CustomTfError(f"terraform dir '{entry['dir']}' not found")
    return target


def collect(tool, app_root):
    """Validated, sorted list of caller .tf files. Empty when no terraform field."""
    entry = _entry(tool)
    if not entry:
        return []

    target = _resolve_dir(entry, app_root)
    files = sorted(
        (p for p in target.iterdir() if p.is_file() and p.name.endswith(TF_SUFFIXES)),
        key=lambda p: p.name,
    )
    for path in files:
        if path.name.startswith("_"):
            raise CustomTfError(
                f"'{path.name}' uses a reserved name: files starting with '_' belong to the platform"
            )
        if _FORBIDDEN_BLOCK.search(path.read_text()):
            raise CustomTfError(
                f"'{path.name}' declares a provider/terraform/backend block; "
                f"declare providers under the manifest's terraform.providers instead"
            )
    return files


def render_providers(providers):
    """The _providers.g.tf body, or None when nothing extra is declared."""
    if not providers:
        return None
    lines = ["# Generated from the manifest terraform.providers list. Do not edit.",
             "terraform {", "  required_providers {"]
    for provider in providers:
        name = provider["name"]
        expected = ALLOWED_PROVIDERS.get(name)
        if expected is None:
            raise CustomTfError(
                f"provider '{name}' is not allowed "
                f"(allowed: {', '.join(sorted(ALLOWED_PROVIDERS))})"
            )
        if provider["source"] != expected:
            raise CustomTfError(
                f"provider '{name}' must use source '{expected}', got '{provider['source']}'"
            )
        lines += [
            f"    {name} = {{",
            f'      source  = "{expected}"',
            f'      version = "{provider["version"]}"',
            "    }",
        ]
    lines += ["  }", "}", ""]
    return "\n".join(lines)


def prepare(tool, app_root, custom_dir):
    """Copy caller .tf into custom_dir and write _providers.g.tf. Returns names copied."""
    files = collect(tool, app_root)
    if not files:
        return []

    destination = Path(custom_dir)
    for path in files:
        shutil.copyfile(path, destination / path.name)

    body = render_providers(_entry(tool).get("providers", []))
    if body is not None:
        (destination / "_providers.g.tf").write_text(body)

    return [p.name for p in files]
```

- [ ] **Step 4: Run the tests, verify pass**

Run: `cd engine && python3 -m pytest tests/py/test_customtf.py -v`
Expected: PASS (all 14).

- [ ] **Step 5: Commit**

```bash
git add engine/cloudapp/customtf.py engine/tests/py/test_customtf.py
git commit -m "feat(customtf): validate and stage caller-supplied terraform"
```

---

### Task 4: Terraform — `custom/` child module + root wiring

**Files:**

- Create: `terraform/azure/custom/_context.tf`
- Create: `terraform/azure/custom/_versions.tf`
- Modify: `terraform/azure/main.tf`
- Modify: `terraform/azure/modules/function/outputs.tf`
- Create: `terraform/azure/tests/custom.tftest.hcl`

**Interfaces:**

- Consumes: root locals `local.rg_name`, `local.base`, `local.env`, `local.platform.location`, `local.platform.network.vnet_id`, `local.platform.network.subnets`; `data.azurerm_resource_group.this.name`; `module.keyvault.id` / `.vault_uri`; `module.container_app[*].identity_principal_id`; `module.function[*].identity_principal_id` (added here).
- Produces: `module "custom"` in the root module, always declared, creating nothing until caller files land in `custom/`.

- [ ] **Step 1: Write the failing Terraform test**

Create `terraform/azure/tests/custom.tftest.hcl` (reuses an existing fixture — `partial` has one app and one function, so both identity maps are exercised):

```hcl
mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.partial.dev.json")).config
  image_tags = { "main/main" = "acrplatformdev.azurecr.io/partial:abc123" }
}

run "custom_module_receives_context" {
  command = plan

  assert {
    condition     = module.custom.context.resource_group_name == "rg-partial-dev"
    error_message = "custom module must receive the tool's resource group"
  }
  assert {
    condition     = module.custom.context.environment == "dev"
    error_message = "custom module must receive the environment"
  }
  assert {
    condition     = module.custom.context.tool_name == "partial"
    error_message = "custom module must receive the tool base name"
  }
  assert {
    condition     = module.custom.context.subnets.functions != ""
    error_message = "custom module must receive the functions subnet id"
  }
  assert {
    condition     = contains(keys(module.custom.context.app_identity_principal_ids), "main")
    error_message = "custom module must receive per-app identity principal ids"
  }
  assert {
    condition     = contains(keys(module.custom.context.function_identity_principal_ids), "relay")
    error_message = "custom module must receive per-function identity principal ids"
  }
}
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `terraform -chdir=terraform/azure test -filter=tests/custom.tftest.hcl`
Expected: FAIL — there is no `module "custom"`, no `custom/` directory, and the function module has no `identity_principal_id` output.

- [ ] **Step 3: Create the `custom/` module**

Create `terraform/azure/custom/_context.tf`:

```hcl
# Platform-owned. The curated context caller-supplied .tf may reference.
# Caller files are copied into this directory at deploy time; they must not
# start with "_" (reserved for these platform files).

variable "resource_group_name" {
  description = "The tool's resource group — the only RG the apply identity can write"
  type        = string
}

variable "location" {
  type = string
}

variable "environment" {
  type = string
}

variable "tool_name" {
  description = "Manifest name with the platform naming prefix applied"
  type        = string
}

variable "vnet_id" {
  type = string
}

variable "subnets" {
  description = "Landing-zone subnet ids (private_endpoints, functions)"
  type        = any
}

variable "key_vault_id" {
  type = string
}

variable "key_vault_uri" {
  type = string
}

variable "app_identity_principal_ids" {
  description = "App key -> managed identity principal id, for role assignments"
  type        = map(string)
  default     = {}
}

variable "function_identity_principal_ids" {
  description = "Function key -> managed identity principal id, for role assignments"
  type        = map(string)
  default     = {}
}

output "context" {
  description = "Echoes the received context so the platform can assert the wiring"
  value = {
    resource_group_name             = var.resource_group_name
    location                        = var.location
    environment                     = var.environment
    tool_name                       = var.tool_name
    vnet_id                         = var.vnet_id
    subnets                         = var.subnets
    key_vault_id                    = var.key_vault_id
    key_vault_uri                   = var.key_vault_uri
    app_identity_principal_ids      = var.app_identity_principal_ids
    function_identity_principal_ids = var.function_identity_principal_ids
  }
}
```

Create `terraform/azure/custom/_versions.tf` — mirrors the root's `required_providers` (verified against `terraform/azure/versions.tf`, which declares `azurerm ~> 4.0` and `random ~> 3.6`). Both are inherited by the child module, so a caller using `random_*` needs no extra declaration:

```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
```

- [ ] **Step 4: Add the function module's identity output**

Append to `terraform/azure/modules/function/outputs.tf`:

```hcl
output "identity_principal_id" {
  value = azurerm_user_assigned_identity.this.principal_id
}
```

- [ ] **Step 5: Wire the module into the root**

Append to `terraform/azure/main.tf`:

```hcl
# Caller-supplied Terraform. Always declared; the module ships empty and creates
# nothing until the action copies the caller's *.tf into ./custom. It runs in the
# main stack, so it applies under the RG-scoped apply identity — that scope is
# what confines custom resources to this tool's resource group.
module "custom" {
  source = "./custom"

  resource_group_name             = data.azurerm_resource_group.this.name
  location                        = local.platform.location
  environment                     = local.env
  tool_name                       = local.base
  vnet_id                         = local.platform.network.vnet_id
  subnets                         = local.platform.network.subnets
  key_vault_id                    = module.keyvault.id
  key_vault_uri                   = module.keyvault.vault_uri
  app_identity_principal_ids      = { for k, m in module.container_app : k => m.identity_principal_id }
  function_identity_principal_ids = { for k, m in module.function : k => m.identity_principal_id }
}
```

- [ ] **Step 6: Run the tests, verify pass**

Run: `terraform -chdir=terraform/azure test`
Expected: PASS — the new `custom` test plus every pre-existing test (the empty `custom` module must not change any other plan).

- [ ] **Step 7: Ignore staged caller files**

Append to `.gitignore` so a local staging run (Task 5) or a runner-side `prepare-custom-tf` never commits caller files into the platform repo:

```gitignore
# Caller-supplied terraform staged into the custom module at deploy time.
# Only the platform's _-prefixed files belong in the repo.
terraform/azure/custom/*
!terraform/azure/custom/_context.tf
!terraform/azure/custom/_versions.tf
```

- [ ] **Step 8: `terraform fmt` + commit**

```bash
terraform -chdir=terraform/azure fmt
git add .gitignore terraform/azure/custom terraform/azure/main.tf terraform/azure/modules/function/outputs.tf terraform/azure/tests/custom.tftest.hcl
git commit -m "feat(tf): custom child module wired with platform context"
```

---

### Task 5: End-to-end — caller files actually plan

**Files:**

- Create: `terraform/azure/tests/fixtures/custom/queue.tf` (sample caller file, staged only during the check)
- Create: `terraform/azure/tests/staged-custom-check.sh` (stages, runs, always unstages)
- Modify: `terraform/azure/tests/custom.tftest.hcl`

**Interfaces:**

- Consumes: the `custom/` module and root wiring from Task 4.
- Produces: `tests/staged-custom-check.sh` — proof that a real caller `.tf` compiles and plans against the context. Task 3 proves the copying; this proves the planning. The repo still ships an empty `custom/`.

Why a script and not a plain `terraform test` run: `terraform test` cannot copy files into a module, and the sample must **not** be committed inside `terraform/azure/custom/` (it would ship to every caller). The script stages it, runs the test, and removes it in a `trap` so a failure never leaves the tree dirty.

- [ ] **Step 1: Write the sample caller file**

Create `terraform/azure/tests/fixtures/custom/queue.tf` — uses the context variables, an in-RG Azure resource, and the `random` provider (already in the root's `required_providers`, so child modules inherit it — no generated providers file is needed for this check):

```hcl
resource "random_pet" "suffix" {
  length = 2
}

resource "azurerm_storage_account" "custom" {
  name                     = substr(replace("stcustom${var.tool_name}${var.environment}", "-", ""), 0, 24)
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}
```

- [ ] **Step 2: Add the staged run block**

Append to `terraform/azure/tests/custom.tftest.hcl`:

```hcl
# Only meaningful when tests/staged-custom-check.sh has staged the sample caller
# file into ../custom. With an empty custom/ this block still passes (the module
# plans clean either way) — the real signal is that the staged plan succeeds.
run "staged_caller_file_plans" {
  command = plan

  assert {
    condition     = module.custom.context.location != ""
    error_message = "custom module must plan with a location in context"
  }
}
```

- [ ] **Step 3: Write the check script**

Create `terraform/azure/tests/staged-custom-check.sh`:

```bash
#!/usr/bin/env bash
# Stage the sample caller .tf into the custom module, run the terraform tests,
# then always unstage. Proves a real caller file compiles and plans against the
# platform context; the repo itself always ships an empty custom/ module.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tf_dir="$(dirname "$here")"
staged="$tf_dir/custom/queue.tf"

cleanup() { rm -f "$staged"; }
trap cleanup EXIT

cp "$here/fixtures/custom/queue.tf" "$staged"
terraform -chdir="$tf_dir" test -filter=tests/custom.tftest.hcl
echo "staged custom check: OK"
```

Make it executable: `chmod +x terraform/azure/tests/staged-custom-check.sh`

- [ ] **Step 4: Run the check, verify it passes**

Run: `./terraform/azure/tests/staged-custom-check.sh`
Expected: the terraform test passes and the script prints `staged custom check: OK`. This is the evidence that a caller file plans — record the full output in the report.

To confirm the check actually bites, temporarily break the sample (e.g. change `var.resource_group_name` to `var.no_such_variable`), re-run, and confirm it FAILS with an unknown-variable error; then restore the sample. Record both outcomes.

- [ ] **Step 5: Confirm the repo ships an empty custom module**

Run: `git status --short terraform/azure/custom && ls terraform/azure/custom`
Expected: no untracked/modified files under `custom/`, and only `_context.tf` and `_versions.tf` present (the trap removed the staged file).

- [ ] **Step 6: Commit**

```bash
git add terraform/azure/tests/fixtures/custom/queue.tf terraform/azure/tests/staged-custom-check.sh terraform/azure/tests/custom.tftest.hcl
git commit -m "test(tf): staged-caller-file check for the custom module"
```

---

### Task 6: CLI + composite action wiring

**Files:**

- Modify: `engine/cloudapp/cli.py`
- Modify: `.github/actions/cloud-app/action.yml`
- Test: `engine/tests/py/test_cli.py`

**Interfaces:**

- Consumes: `customtf.prepare` (Task 3); the normalized `terraform` entry (Task 2).
- Produces:
  - CLI: `python3 -m cloudapp prepare-custom-tf --tool-json --app-root --custom-dir`, which stages the caller files and prints/records what it copied.
  - The action runs it before `Resolve config` / `Terraform deploy`, so `terraform init` sees the staged files.

- [ ] **Step 1: Write the failing test**

Add to `engine/tests/py/test_cli.py` (follow the existing conventions in that file for `main` and fixture paths):

```python
def test_prepare_custom_tf_stages_caller_files(tmp_path):
    app_root = tmp_path / "app"
    (app_root / "terraform").mkdir(parents=True)
    (app_root / "terraform" / "queue.tf").write_text('resource "random_pet" "p" {}\n')

    tool_json = tmp_path / "tool.dev.json"
    tool_json.write_text(json.dumps({
        "name": "orders",
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}],
        },
    }))

    custom = tmp_path / "custom"
    custom.mkdir()

    rc = cli.main([
        "prepare-custom-tf",
        "--tool-json", str(tool_json),
        "--app-root", str(app_root),
        "--custom-dir", str(custom),
    ])

    assert rc == 0
    assert (custom / "queue.tf").exists()
    assert "hashicorp/random" in (custom / "_providers.g.tf").read_text()


def test_prepare_custom_tf_reports_error_for_bad_provider(tmp_path):
    app_root = tmp_path / "app"
    (app_root / "terraform").mkdir(parents=True)
    (app_root / "terraform" / "q.tf").write_text("# empty\n")

    tool_json = tmp_path / "tool.dev.json"
    tool_json.write_text(json.dumps({
        "name": "orders",
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "aws", "source": "hashicorp/aws", "version": "~> 5"}],
        },
    }))

    custom = tmp_path / "custom"
    custom.mkdir()

    rc = cli.main([
        "prepare-custom-tf",
        "--tool-json", str(tool_json),
        "--app-root", str(app_root),
        "--custom-dir", str(custom),
    ])

    assert rc == 1
```

`test_cli.py` already has `import json`, `from conftest import ENVDIR, FIXTURES`, and `from cloudapp import cli` at the top, and calls `cli.main([...])` — the tests above match that convention; no new imports are needed.

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_cli.py -k custom_tf -v`
Expected: FAIL — no such subcommand.

- [ ] **Step 3: Implement the CLI command**

In `engine/cloudapp/cli.py`, add `customtf` to the existing `from . import (...)` block (keep alphabetical order). Add the handler after `cmd_resolve_config`:

```python
def cmd_prepare_custom_tf(args):
    tool = _load_json(args.tool_json)
    copied = customtf.prepare(tool, args.app_root, args.custom_dir)
    if copied:
        gha.notice(f"staged caller terraform: {', '.join(copied)}")
    gha.write_outputs({"custom_tf": "true" if copied else "false"})
```

Register the subparser in `main`, after the `resolve-config` parser:

```python
    p = sub.add_parser("prepare-custom-tf")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--app-root", default=".")
    p.add_argument("--custom-dir", required=True)
    p.set_defaults(func=cmd_prepare_custom_tf)
```

Add `customtf.CustomTfError` to the `except` tuple at the bottom of `main` so a validation failure becomes a clean `::error::` + exit 1 rather than a traceback:

```python
    except (manifest.ManifestError, resolve.ResolveError, secrets.SyncError,
            tfdeploy.DeployError, backend.BackendError, customtf.CustomTfError,
            registry.RegistryError, ValueError) as exc:
```

- [ ] **Step 4: Add the action step**

In `.github/actions/cloud-app/action.yml`, insert this step immediately **before** the `Resolve config` step (it must run before `terraform init`, which happens inside `terraform-deploy`):

```yaml
# Stage caller-supplied Terraform into the platform's custom child module.
# No-op when the manifest has no `terraform:` field. Runs before any
# terraform init so the staged files are part of the module from the start.
- name: Prepare custom terraform
  shell: bash
  env:
    DEPLOY_ENV: ${{ inputs.env }}
  run: >-
    PYTHONPATH="${{ github.action_path }}/../../../engine"
    python3 -m cloudapp prepare-custom-tf
    --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
    --app-root "."
    --custom-dir "${{ github.action_path }}/../../../terraform/azure/custom"
```

- [ ] **Step 5: Run the tests, verify pass**

Run:

```bash
cd engine && python3 -m pytest tests/py -q
```

Expected: PASS (all).
Then, from the repo root: `actionlint` (CI runs it; if not installed locally, note that).

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/cli.py engine/tests/py/test_cli.py .github/actions/cloud-app/action.yml
git commit -m "feat(action): stage caller terraform before deploy"
```

---

### Task 7: Docs + sample

**Files:**

- Modify: `README.md`
- Modify: `docs/usage.md`
- Modify: `samples/caller-app/cloud-app.yml`
- Create: `samples/caller-app/terraform/queue.tf`

**Interfaces:** none (documentation only). Must accurately describe Tasks 1–6 as built.

- [ ] **Step 1: README bullet**

In `README.md`, under "Manifest at a glance", add:

```markdown
- Need a resource the platform doesn't model? Point `terraform: ./terraform` at a
  directory of `*.tf` in your repo. They merge into a `custom` child module that
  receives platform context (resource group, subnets, Key Vault, per-app managed
  identity principal ids) and applies under the same RG-scoped identity — so custom
  resources are confined to your resource group. Extra providers are declared in
  the manifest from a fixed allowlist.
```

- [ ] **Step 2: usage.md section**

Add a `## Caller-supplied Terraform` section to `docs/usage.md` covering: the `terraform:` shorthand and object form, per-env override, the provider allowlist table (all eight, with sources), the context-variable table (the ten variables from `custom/_context.tf`), the rejection rules (`_`-prefixed names, `..`/absolute dirs, raw `provider`/`terraform`/`backend` blocks, `.tf` only, no subdirs), and the documented residual risk that `local-exec`/`external` run on the runner under the apply identity. Include a worked example:

```yaml
terraform:
  dir: ./terraform
  providers:
    - { name: random, source: hashicorp/random, version: "~> 3" }
```

```hcl
# terraform/queue.tf in the caller repo
resource "azurerm_storage_queue" "jobs" {
  name                 = "jobs"
  storage_account_name = azurerm_storage_account.custom.name
}

resource "azurerm_role_assignment" "app_can_read" {
  scope                = azurerm_storage_account.custom.id
  role_definition_name = "Storage Queue Data Reader"
  principal_id         = var.app_identity_principal_ids["main"]
}
```

- [ ] **Step 3: Sample**

Create `samples/caller-app/terraform/queue.tf` with a small, valid example that uses `var.resource_group_name`, `var.location`, and one `var.app_identity_principal_ids` reference. Add to `samples/caller-app/cloud-app.yml`:

```yaml
terraform:
  dir: ./terraform
  providers:
    - { name: random, source: hashicorp/random, version: "~> 3" }
```

- [ ] **Step 4: Verify the sample manifest validates**

Run:

```bash
cd engine && python3 -c "
from cloudapp import manifest
print(manifest.validate(manifest._load_yaml('../samples/caller-app/cloud-app.yml')) or 'valid')
"
```

Expected: prints `valid`.
Then run the full engine suite: `cd engine && python3 -m pytest tests/py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/usage.md samples/caller-app
git commit -m "docs: caller-supplied terraform"
```

---

## Final verification

- [ ] `cd engine && python3 -m pytest tests/py -q` → all pass.
- [ ] `terraform -chdir=terraform/azure test` → all pass.
- [ ] `terraform -chdir=terraform/azure fmt -check -recursive` → clean.
- [ ] `python3 engine/generate_tf_fixtures.py && git diff --exit-code terraform/azure/tests/fixtures` → clean (this feature adds no manifest fixture to `CASES`; if a fixture manifest gained a `terraform:` field, regenerate and commit).
- [ ] `git status --short terraform/azure/custom` → only `_context.tf` and `_versions.tf` tracked (no staged caller files, no generated `_providers.g.tf`).
- [ ] Add `terraform/azure/custom/_providers.g.tf` and any non-underscore `.tf` under `terraform/azure/custom/` to `.gitignore` so a local staging run never gets committed.
