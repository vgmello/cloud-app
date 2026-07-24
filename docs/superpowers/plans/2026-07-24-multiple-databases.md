# Multiple Databases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a manifest declare multiple database servers (each hosting one or more logical databases) via a top-level `databases:` map, with apps/functions opting in to the connection strings they need — while the legacy singular `database:` form keeps deploying byte-identical.

**Architecture:** The engine (`manifest.py`) validates the schema, folds the legacy `database:` into `databases: {main: ...}` plus a `database_legacy` marker, defaults `dbs` to `[main]`, and cross-ref-checks every app/function opt-in. Terraform runs the database module with `for_each = local.databases`; `locals.tf` is the single source of truth for Key Vault secret names and per-app/function env-var wiring. The legacy marker only affects secret naming (`database-url`) and blanket `DATABASE_URL` injection.

**Tech Stack:** Python 3 + jsonschema (Draft 2020-12), Terraform (azurerm), pytest, terraform `.tftest.hcl`.

## Global Constraints

- Manifest key pattern for `databases` keys and `dbs` entries: `^[a-z][a-z0-9-]{0,29}$` (same as apps/functions/static_sites keys).
- Server `name` override pattern: `^[a-z][a-z0-9-]{1,29}$` (same as apps `name`).
- Env-var derivation is uniform: ref `<server>/<db>` → `<SERVER>_<DB>_DATABASE_URL` (uppercased, `-`→`_`). No plain-`DATABASE_URL` special case except the legacy path.
- Key Vault secret per (server, db): `database-url-<server>-<db>`; legacy path uses `database-url`.
- Server resource names mirror the apps rule: one entry → `psql-<base>-<env>` / `sql-<base>-<env>`; 2+ → append the server key; explicit `name:` wins.
- Existing singular-`database:` manifests must produce an identical Azure plan (same server name, one `main` logical db, `database-url` secret, blanket `DATABASE_URL`). Golden/fixture JSON _shape_ changes are expected and accepted.
- Schema validation runs on the raw manifest **before** `normalize`; the normalized config is never re-validated, so the synthetic `database_legacy` key is safe.
- Storage is out of scope: `STORAGE_CONNECTION` stays blanket.
- Run engine tests from `engine/`: `cd engine && python -m pytest`. Run terraform tests from `terraform/azure/`: `terraform test`.

---

### Task 1: Schema — `databases:` map, `dbs`, app/function opt-in, mutual exclusion

**Files:**

- Modify: `terraform/schema/cloud-app.schema.json`
- Create: `engine/tests/fixtures/manifests/databases.yml`
- Create: `engine/tests/fixtures/manifests/invalid-database-and-databases.yml`
- Modify: `engine/tests/py/test_manifest.py:6-19` (VALID / INVALID lists)

**Interfaces:**

- Produces: a schema that accepts a top-level `databases` map (values = `database` def with new `name` + `dbs`), an app/function `databases` array of `"<server>/<db>"` refs, both allowed inside the `overlay` def; and rejects a manifest with both `database` and `databases`.

- [ ] **Step 1: Add the new valid fixture manifest**

Create `engine/tests/fixtures/manifests/databases.yml`:

```yaml
name: shop

apps:
  api:
    port: 8080
    ingress: internal
    databases: [primary/orders, reporting/main]
  worker:
    ingress: none
    databases: [primary/orders, primary/billing]

functions:
  sync:
    image: myacr.azurecr.io/sync:1.0
    databases: [reporting/main]

databases:
  primary:
    type: postgres
    size: small
    dbs: [orders, billing]
  reporting:
    type: sqlserver
    size: large

environments:
  dev: {}
  prod:
    databases:
      primary:
        size: medium
```

- [ ] **Step 2: Add the new schema-invalid fixture**

Create `engine/tests/fixtures/manifests/invalid-database-and-databases.yml`:

```yaml
name: shop
app:
  port: 8080
database:
  size: small
databases:
  primary:
    type: postgres
```

- [ ] **Step 3: Write the failing tests**

Edit `engine/tests/py/test_manifest.py`. Add `"databases"` to `VALID` and `"invalid-database-and-databases"` to `INVALID`:

```python
VALID = ["minimal", "full", "multi", "partial", "databases"]
INVALID = [
    "invalid-missing-name",
    "invalid-legacy-type",
    "invalid-unknown-key",
    "invalid-empty-environments",
    "invalid-no-compute",
    "invalid-mixed-container",
    "invalid-db-type",
    "invalid-app-and-apps",
    "invalid-image-and-docker",
    "invalid-function-image-docker",
    "invalid-env-number",
    "invalid-database-and-databases",
]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd engine && python -m pytest tests/py/test_manifest.py -k "schema" -v`
Expected: FAIL — `databases` fixture fails validation (unknown keys `databases`, `dbs`, app `databases`) and `invalid-database-and-databases` currently passes.

- [ ] **Step 5: Add the `dbs` and `name` properties to the `database` def**

In `terraform/schema/cloud-app.schema.json`, inside `$defs.database.properties` (currently `type`, `size`, `storage_gb`, `public_access`), add:

```json
"name": {
  "type": "string",
  "pattern": "^[a-z][a-z0-9-]{1,29}$"
},
"dbs": {
  "type": "array",
  "minItems": 1,
  "uniqueItems": true,
  "items": {
    "type": "string",
    "pattern": "^[a-z][a-z0-9-]{0,29}$"
  }
}
```

- [ ] **Step 6: Add the top-level `databases` map and the `databases` ref array to the `app` and `function` defs**

In `$defs` add a reusable ref-list under a new key `db_refs`:

```json
"db_refs": {
  "type": "array",
  "items": {
    "type": "string",
    "pattern": "^[a-z][a-z0-9-]{0,29}/[a-z][a-z0-9-]{0,29}$"
  }
}
```

Add `"databases": { "$ref": "#/$defs/db_refs" }` to `$defs.app.properties` and to `$defs.function.properties`.

Add a top-level `databases` map to the root `properties` (alongside the existing singular `database`):

```json
"databases": {
  "type": "object",
  "minProperties": 1,
  "propertyNames": { "pattern": "^[a-z][a-z0-9-]{0,29}$" },
  "additionalProperties": { "$ref": "#/$defs/database" }
}
```

- [ ] **Step 7: Allow `databases` alongside `containers` in the app def**

The `app` def's `allOf` first clause sets `cpu/memory/docker/env/secrets/image` to `false` when `containers` is present. Do **not** add `databases` there — leaving it out means it stays permitted alongside `containers`. Confirm the `then.properties` block is unchanged (only the six existing keys forbidden).

- [ ] **Step 8: Add `databases` to the overlay def**

In `$defs.overlay.properties`, add both the plural top-level map and pass-through for app/function refs (the overlay already `$ref`s `app`/`function` via its `apps`/`functions`, which now include `databases`, so only the top-level plural needs adding):

```json
"databases": {
  "type": "object",
  "additionalProperties": { "$ref": "#/$defs/database" }
}
```

- [ ] **Step 9: Add the `database`/`databases` mutual-exclusion rule**

The root `allOf` already forbids `app`+`apps`. Add a second clause forbidding `database`+`databases`:

```json
{
  "not": {
    "required": ["database", "databases"]
  }
}
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `cd engine && python -m pytest tests/py/test_manifest.py -k "schema" -v`
Expected: PASS — `databases` validates, `invalid-database-and-databases` rejected.

- [ ] **Step 11: Commit**

```bash
git add terraform/schema/cloud-app.schema.json engine/tests/fixtures/manifests/databases.yml engine/tests/fixtures/manifests/invalid-database-and-databases.yml engine/tests/py/test_manifest.py
git commit -m "feat(schema): databases map, dbs list, per-app db opt-in"
```

---

### Task 2: Engine — legacy fold, `dbs` default, defaults merge, cross-ref validation

**Files:**

- Modify: `engine/cloudapp/manifest.py:91-108` (`normalize`)
- Modify: `engine/cloudapp/manifest.py:110-118` (`_uses_docker_build` unaffected — verify only)
- Modify: `engine/tests/py/test_manifest.py` (new behavior tests)
- Regenerate: `engine/tests/golden/*.json` (full, partial, multi change; minimal unchanged; add databases.dev, databases.prod)

**Interfaces:**

- Consumes: Task 1 schema (validation already passed before `normalize`).
- Produces:
  - `normalize(merged)` returns a config where a singular `database` is replaced by `databases: {"main": {<merged defaults>, "dbs": ["main"]}}` plus `database_legacy: True`; and where each plural `databases` entry has defaults merged and `dbs` defaulting to `["main"]`.
  - A new module-level function `validate_db_refs(cfg)` raising `ManifestError` on an app/function `databases` ref whose server or db is not declared.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_manifest.py`:

```python
def test_legacy_database_folds_into_databases_main():
    _, _, tools, _ = manifest.parse(FIXTURES / "full.yml")
    cfg = tools["dev"]
    assert "database" not in cfg
    assert list(cfg["databases"]) == ["main"]
    assert cfg["databases"]["main"]["dbs"] == ["main"]
    assert cfg["database_legacy"] is True


def test_databases_entry_defaults_dbs_to_main():
    _, _, tools, _ = manifest.parse(FIXTURES / "databases.yml")
    assert tools["dev"]["databases"]["reporting"]["dbs"] == ["main"]
    assert "database_legacy" not in tools["dev"]


def test_databases_merges_entry_defaults():
    _, _, tools, _ = manifest.parse(FIXTURES / "databases.yml")
    primary = tools["dev"]["databases"]["primary"]
    assert primary["type"] == "postgres"
    assert primary["storage_gb"] == 32
    assert primary["public_access"] is False


def test_unknown_db_server_ref_raises():
    with pytest.raises(manifest.ManifestError, match="ghost/main"):
        manifest.parse(FIXTURES / "invalid-db-ref-server.yml")


def test_unknown_db_name_ref_raises():
    with pytest.raises(manifest.ManifestError, match="primary/ghost"):
        manifest.parse(FIXTURES / "invalid-db-ref-name.yml")
```

- [ ] **Step 2: Add the two ref-validation invalid fixtures**

Create `engine/tests/fixtures/manifests/invalid-db-ref-server.yml`:

```yaml
name: shop
apps:
  api:
    port: 8080
    databases: [ghost/main]
databases:
  primary:
    type: postgres
    dbs: [main]
```

Create `engine/tests/fixtures/manifests/invalid-db-ref-name.yml`:

```yaml
name: shop
apps:
  api:
    port: 8080
    databases: [primary/ghost]
databases:
  primary:
    type: postgres
    dbs: [main]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd engine && python -m pytest tests/py/test_manifest.py -k "legacy or databases_entry or databases_merges or unknown_db" -v`
Expected: FAIL — `normalize` does not yet produce `databases` from legacy, and `validate_db_refs` does not exist.

- [ ] **Step 4: Implement the legacy fold + `dbs`/defaults handling in `normalize`**

In `engine/cloudapp/manifest.py`, replace the database/storage block in `normalize` (currently lines ~105-107) with:

```python
    if "database" in cfg and "databases" in cfg:
        raise ManifestError(
            "manifest mixes singular database with databases; use one form"
        )
    db_defaults = _load_yaml(DEFAULTS_DIR / "database.yml")
    if "database" in cfg:
        merged_db = deep_merge(db_defaults, cfg.pop("database"))
        merged_db.setdefault("dbs", ["main"])
        cfg["databases"] = {"main": merged_db}
        cfg["database_legacy"] = True
    elif "databases" in cfg:
        entries = {}
        for k, v in cfg["databases"].items():
            merged = deep_merge(db_defaults, v)
            merged.setdefault("dbs", ["main"])
            entries[k] = merged
        cfg["databases"] = entries
    if "storage" in cfg:
        cfg["storage"] = deep_merge(_load_yaml(DEFAULTS_DIR / "storage.yml"), cfg["storage"])
```

(The `database_legacy` marker is a plain `bool`, JSON-serializable, and survives `resolve.resolve` verbatim.)

- [ ] **Step 5: Implement `validate_db_refs` and call it from `parse`**

Add near `normalize` in `manifest.py`:

```python
def validate_db_refs(cfg):
    """Raise if any app/function databases ref names an undeclared server or db."""
    declared = {k: set(v["dbs"]) for k, v in cfg.get("databases", {}).items()}
    for section in ("apps", "functions"):
        for owner, entry in (cfg.get(section) or {}).items():
            for ref in entry.get("databases", []):
                server, _, db = ref.partition("/")
                if server not in declared:
                    raise ManifestError(
                        f"{section}/{owner} references unknown database server in '{ref}'"
                    )
                if db not in declared[server]:
                    raise ManifestError(
                        f"{section}/{owner} references unknown database in '{ref}'"
                    )
```

In `normalize`, `_normalize_app` currently drops unknown keys because it rebuilds `normalized`. Add `databases` pass-through in `_normalize_app` (after the `replicas`/`containers` assignments, before `return normalized`):

```python
    if "databases" in app:
        normalized["databases"] = app["databases"]
```

Functions are merged via `deep_merge(defaults, v)` (line ~104) which preserves `databases` already — no change needed there.

Call `validate_db_refs` at the end of `normalize`, just before `return cfg`:

```python
    validate_db_refs(cfg)
    return cfg
```

- [ ] **Step 6: Run the behavior tests to verify they pass**

Run: `cd engine && python -m pytest tests/py/test_manifest.py -k "legacy or databases_entry or databases_merges or unknown_db" -v`
Expected: PASS.

- [ ] **Step 7: Add the two ref-invalid fixtures to a parse-error test group (not the schema list)**

These fixtures are schema-valid but fail at `parse`. Confirm they are **not** in `INVALID` (schema list) — they are covered by `test_unknown_db_*` above. No further list change.

- [ ] **Step 8: Regenerate the engine golden files**

The `full`, `partial`, `multi` goldens change (`database` → `databases` + `database_legacy`); `minimal` is unchanged (no db). Add `databases.dev` and `databases.prod`. Regenerate with a one-off snapshot:

```bash
cd engine && python - <<'PY'
import json
from pathlib import Path
from cloudapp import manifest
FIX = Path("tests/fixtures/manifests"); GOLD = Path("tests/golden")
cases = [("minimal","dev"),("full","dev"),("full","prod"),("multi","dev"),
         ("partial","dev"),("partial","prod"),("databases","dev"),("databases","prod")]
for name, env in cases:
    _, _, tools, _ = manifest.parse(FIX / f"{name}.yml")
    (GOLD / f"{name}.{env}.json").write_text(json.dumps(tools[env], indent=2) + "\n")
    print("wrote", name, env)
PY
```

Then eyeball `git diff engine/tests/golden/full.dev.json` and confirm the only change is the database block reshaping (server `main`, `dbs: ["main"]`, `database_legacy: true`) — no app/ingress/replica drift.

- [ ] **Step 9: Add the new golden cases to the golden test parametrize**

Edit `engine/tests/py/test_manifest.py` `test_normalized_tool_matches_golden` parametrize list, appending:

```python
        ("databases", "dev", "databases.dev"),
        ("databases", "prod", "databases.prod"),
```

- [ ] **Step 10: Run the full engine manifest suite**

Run: `cd engine && python -m pytest tests/py/test_manifest.py -v`
Expected: PASS (all, including golden comparisons).

- [ ] **Step 11: Commit**

```bash
git add engine/cloudapp/manifest.py engine/tests/py/test_manifest.py engine/tests/fixtures/manifests/ engine/tests/golden/
git commit -m "feat(engine): legacy database fold, dbs defaults, db ref validation"
```

---

### Task 3: Terraform database module — per-server `for_each`, per-db resources + secrets

**Files:**

- Modify: `terraform/azure/modules/shared/database/variables.tf`
- Modify: `terraform/azure/modules/shared/database/main.tf`
- Modify: `terraform/azure/modules/shared/database/outputs.tf`

**Interfaces:**

- Consumes: from `locals.tf` (Task 4): `name` (server resource name), `type`, `size`, `storage_gb`, `public_access`, and a new `dbs` input — a map `{ db_name => kv_secret_name }`.
- Produces: one logical-db resource per `dbs` key; one KV secret per key named by its value; outputs `server_name` (string) and `secret_names` (the `dbs` map echoed back).

- [ ] **Step 1: Add the `dbs` variable, remove the stale `secret_env` output usage**

Edit `terraform/azure/modules/shared/database/variables.tf`, add:

```hcl
variable "dbs" {
  description = "Logical database name -> Key Vault secret name"
  type        = map(string)
}
```

- [ ] **Step 2: Replace the single-`main` logical db + connection string + secret with per-db loops**

Edit `terraform/azure/modules/shared/database/main.tf`. Replace the `locals` `connection_string` and the single `azurerm_postgresql_flexible_server_database` / `azurerm_mssql_database` / `azurerm_key_vault_secret.database_url` resources with:

```hcl
locals {
  pg_sku  = { small = "B_Standard_B1ms", medium = "GP_Standard_D2ds_v4", large = "GP_Standard_D4ds_v4" }
  sql_sku = { small = "S0", medium = "S2", large = "S4" }

  is_postgres = var.type == "postgres"
  fqdn        = local.is_postgres ? "${var.name}.postgres.database.azure.com" : "${var.name}.database.windows.net"

  connection_strings = {
    for db, _ in var.dbs :
    db => local.is_postgres ? (
      "postgresql://dbadmin:${random_password.admin.result}@${local.fqdn}:5432/${db}?sslmode=require"
      ) : (
      "Server=tcp:${local.fqdn},1433;Database=${db};User ID=dbadmin;Password=${random_password.admin.result};Encrypt=true;"
    )
  }
}
```

Keep `random_password.admin`, `azurerm_postgresql_flexible_server.this` (count), `azurerm_mssql_server.this` (count), and `module.private_endpoint` exactly as they are.

Replace the two logical-db resources:

```hcl
resource "azurerm_postgresql_flexible_server_database" "this" {
  for_each = local.is_postgres ? var.dbs : {}

  name      = each.key
  server_id = azurerm_postgresql_flexible_server.this[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_mssql_database" "this" {
  for_each = local.is_postgres ? {} : var.dbs

  name        = each.key
  server_id   = azurerm_mssql_server.this[0].id
  sku_name    = local.sql_sku[var.size]
  max_size_gb = var.storage_gb
}
```

Replace `azurerm_key_vault_secret.database_url`:

```hcl
resource "azurerm_key_vault_secret" "database_url" {
  for_each = var.dbs

  name         = each.value
  value        = local.connection_strings[each.key]
  key_vault_id = var.keyvault_id
}
```

- [ ] **Step 3: Update the module outputs**

Replace `terraform/azure/modules/shared/database/outputs.tf` with:

```hcl
output "server_name" {
  value = var.name
}

output "secret_names" {
  description = "Logical db name -> Key Vault secret name"
  value       = var.dbs
}
```

- [ ] **Step 4: Format-check the module**

Run: `cd terraform/azure && terraform fmt -check -recursive modules/shared/database`
Expected: no output (formatted). If it reformats, that is fine — re-run to confirm clean.

- [ ] **Step 5: Commit**

```bash
git add terraform/azure/modules/shared/database/
git commit -m "feat(tf): database module supports multiple logical dbs per server"
```

_(No standalone test here — the module is exercised through the root module in Task 5.)_

---

### Task 4: Terraform root — locals wiring, `for_each` module, outputs, precondition

**Files:**

- Modify: `terraform/azure/locals.tf`
- Modify: `terraform/azure/main.tf:19-33` (`module.database`)
- Modify: `terraform/azure/main.tf:50-85` (`extra_secret_env` on container_app + function)
- Modify: `terraform/azure/outputs.tf:1-12` (`names`)
- Modify: `terraform/azure/modules/container-app/main.tf:116` (precondition message)

**Interfaces:**

- Consumes: Task 2 config shape (`databases` map with `dbs` + optional `name`; optional `database_legacy`; app/function `databases` ref lists); Task 3 module (`dbs` input, `server_name`/`secret_names` outputs).
- Produces: `local.databases`, `local.db_legacy`, `local.db_names`, `local.db_secret_names`, `local.per_app_db_env`, `local.per_function_db_env`, `local.storage_secret_env`; `output.names.databases`.

- [ ] **Step 1: Replace the database locals**

In `terraform/azure/locals.tf`, replace `database = try(local.cfg.database, null)` (line ~11) with:

```hcl
  databases = try(local.cfg.databases, {})
  db_legacy = try(local.cfg.database_legacy, false)
```

Replace the `db_name` local (lines ~35-37) with server bases + names + secret names:

```hcl
  db_server_bases = {
    for k, v in local.databases :
    k => coalesce(try(v.name, null), length(local.databases) == 1 ? local.base : "${local.base}-${k}")
  }
  db_names = {
    for k, v in local.databases :
    k => v.type == "postgres" ? "psql-${local.db_server_bases[k]}-${local.env}" : "sql-${local.db_server_bases[k]}-${local.env}"
  }
  db_secret_names = {
    for sk, sv in local.databases :
    sk => {
      for db in sv.dbs :
      db => local.db_legacy ? "database-url" : "database-url-${sk}-${db}"
    }
  }
```

- [ ] **Step 2: Replace `shared_secret_env` with storage-only + per-entity db env maps**

Replace the `shared_secret_env` block (lines ~42-46) with:

```hcl
  storage_secret_env = local.storage != null ? { STORAGE_CONNECTION = "storage-connection" } : {}

  db_blanket_env = local.db_legacy ? { DATABASE_URL = "database-url" } : {}

  per_app_db_env = {
    for ak, av in local.apps :
    ak => local.db_legacy ? local.db_blanket_env : {
      for ref in try(av.databases, []) :
      "${upper(replace(split("/", ref)[0], "-", "_"))}_${upper(replace(split("/", ref)[1], "-", "_"))}_DATABASE_URL"
      => local.db_secret_names[split("/", ref)[0]][split("/", ref)[1]]
    }
  }

  per_function_db_env = {
    for fk, fv in local.functions :
    fk => local.db_legacy ? local.db_blanket_env : {
      for ref in try(fv.databases, []) :
      "${upper(replace(split("/", ref)[0], "-", "_"))}_${upper(replace(split("/", ref)[1], "-", "_"))}_DATABASE_URL"
      => local.db_secret_names[split("/", ref)[0]][split("/", ref)[1]]
    }
  }
```

- [ ] **Step 3: Rewrite `module.database` as `for_each`**

In `terraform/azure/main.tf`, replace the `module.database` block (lines ~19-33) with:

```hcl
module "database" {
  source   = "./modules/shared/database"
  for_each = local.databases

  name                        = local.db_names[each.key]
  type                        = each.value.type
  size                        = each.value.size
  storage_gb                  = each.value.storage_gb
  public_access               = each.value.public_access
  dbs                         = local.db_secret_names[each.key]
  location                    = local.platform.location
  resource_group_name         = azurerm_resource_group.this.name
  keyvault_id                 = module.keyvault.id
  private_endpoints_subnet_id = local.platform.network.subnets.private_endpoints
  private_dns_zone_id         = each.value.type == "postgres" ? local.platform.network.private_dns_zone_ids.postgres : local.platform.network.private_dns_zone_ids.sqlserver
}
```

- [ ] **Step 4: Point apps/functions at the per-entity db env maps**

In `module.container_app` (line ~64) change:

```hcl
  extra_secret_env              = merge(local.storage_secret_env, local.per_app_db_env[each.key])
```

In `module.function` (line ~81) change:

```hcl
  extra_secret_env    = merge(local.storage_secret_env, local.per_function_db_env[each.key])
```

`depends_on = [module.database, module.storage]` stays — it works with the `for_each`'d module.

- [ ] **Step 5: Update the `names` output**

In `terraform/azure/outputs.tf`, replace `database = local.db_name` with:

```hcl
    databases = local.db_names
```

- [ ] **Step 6: Update the container-app precondition message**

In `terraform/azure/modules/container-app/main.tf` line ~116, change the message to reflect dynamic reserved names:

```hcl
      error_message = "container env keys must not collide with secret names or reserved env vars (per-database *_DATABASE_URL, STORAGE_CONNECTION)"
```

- [ ] **Step 7: Format + validate**

Run: `cd terraform/azure && terraform fmt -recursive && terraform validate`
Expected: `terraform validate` → "Success! The configuration is valid." (fmt may rewrite files; that is fine.)

- [ ] **Step 8: Commit**

```bash
git add terraform/azure/locals.tf terraform/azure/main.tf terraform/azure/outputs.tf terraform/azure/modules/container-app/main.tf
git commit -m "feat(tf): wire per-app database opt-in and multi-server naming"
```

---

### Task 5: Terraform fixtures + tftest coverage

**Files:**

- Modify: `engine/generate_tf_fixtures.py:17` (CASES)
- Regenerate: `terraform/azure/tests/fixtures/tfvars.*.json` (full, partial, multi change; add databases.dev)
- Modify: `terraform/azure/tests/full.tftest.hcl`, `minimal.tftest.hcl`, `multi.tftest.hcl`, `partial.tftest.hcl` (update `output.names.database` → `output.names.databases`, update DATABASE_URL assertions)
- Create: `terraform/azure/tests/databases.tftest.hcl`

**Interfaces:**

- Consumes: Task 4 root module + Task 2 tfvars shape.

- [ ] **Step 1: Add the `databases` case to the fixture generator**

In `engine/generate_tf_fixtures.py`, extend `CASES`:

```python
CASES = [("minimal", "dev"), ("full", "prod"), ("multi", "dev"), ("partial", "dev"), ("databases", "dev")]
```

- [ ] **Step 2: Regenerate the terraform tfvars fixtures**

Run: `cd engine && python generate_tf_fixtures.py`
Expected: prints `wrote terraform/azure/tests/fixtures/tfvars.{minimal,full,multi,partial,databases}.*.json`.

Confirm `git diff` on `tfvars.full.prod.json` shows only the database block reshaping to `databases`/`database_legacy`.

- [ ] **Step 3: Update the existing tftest database-naming assertions**

In `terraform/azure/tests/partial.tftest.hcl`, the `naming` run asserts `output.names.database == "psql-partial-dev"`. Change to:

```hcl
  assert {
    condition     = output.names.databases["main"] == "psql-partial-dev"
    error_message = "legacy database defaulting to postgres must use psql- prefix"
  }
```

Search the other three test files for `output.names.database` and any `DATABASE_URL`/`database-url` assertions:

Run: `cd terraform/azure && grep -rn "names.database\|DATABASE_URL\|database-url" tests/`

For each hit in `full`/`multi`/`minimal`, update `output.names.database` → `output.names.databases["main"]`. Any assertion checking that an app receives `DATABASE_URL` stays valid (legacy path still injects blanket `DATABASE_URL`) — confirm it references the app's env, and leave it.

- [ ] **Step 4: Run the existing terraform tests to verify legacy parity**

Run: `cd terraform/azure && terraform test`
Expected: PASS for `minimal`, `full`, `multi`, `partial` — proving singular-`database:` manifests still produce `psql-...` servers, a `database-url` secret, and blanket `DATABASE_URL`.

- [ ] **Step 5: Write the multi-database test**

Create `terraform/azure/tests/databases.tftest.hcl`:

```hcl
mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config = jsondecode(file("tests/fixtures/tfvars.databases.dev.json")).config
}

run "server_naming" {
  command = plan

  assert {
    condition     = output.names.databases["primary"] == "psql-shop-primary-dev"
    error_message = "multiple servers must append the server key"
  }
  assert {
    condition     = output.names.databases["reporting"] == "sql-shop-reporting-dev"
    error_message = "sqlserver server must use sql- prefix and append key"
  }
}

run "logical_databases" {
  command = plan

  assert {
    condition     = length(azurerm_postgresql_flexible_server_database.this) == 2
    error_message = "primary must create orders + billing logical dbs"
  }
  assert {
    condition     = length(azurerm_mssql_database.this) == 1
    error_message = "reporting must create one logical db (main)"
  }
}

run "secret_names" {
  command = plan

  assert {
    condition     = module.database["primary"].secret_names["orders"] == "database-url-primary-orders"
    error_message = "non-legacy secret name must be database-url-<server>-<db>"
  }
}

run "app_opt_in_env" {
  command = plan

  # api opts into primary/orders + reporting/main -> two db env vars, no billing
  assert {
    condition = length(setintersection(
      keys(module.container_app["api"].extra_secret_env),
      ["PRIMARY_ORDERS_DATABASE_URL", "REPORTING_MAIN_DATABASE_URL"]
    )) == 2
    error_message = "api must receive exactly its two opted-in database env vars"
  }
  assert {
    condition     = !contains(keys(module.container_app["api"].extra_secret_env), "PRIMARY_BILLING_DATABASE_URL")
    error_message = "api did not opt into primary/billing and must not receive it"
  }
}
```

Note: `module.database[...]` for `azurerm_*_database.this` counts — the `length(...)` assertions reference the resource **inside the module**, so use `module.database["primary"].<output>` for anything the module doesn't already export. The resource-count asserts above must instead go through module outputs; if the module does not expose db counts, assert on `module.database["primary"].secret_names` length instead:

```hcl
  assert {
    condition     = length(module.database["primary"].secret_names) == 2
    error_message = "primary must expose two logical-db secrets"
  }
```

Use the `secret_names`-length form (module output) rather than reaching into module-internal resources.

- [ ] **Step 6: Add an `extra_secret_env` output to the container-app module (test hook)**

The `app_opt_in_env` run reads `module.container_app["api"].extra_secret_env`, which the module must expose. In `terraform/azure/modules/container-app/outputs.tf`, add:

```hcl
output "extra_secret_env" {
  description = "Reserved env var -> Key Vault secret name wired into every container"
  value       = var.extra_secret_env
}
```

- [ ] **Step 7: Run the new test**

Run: `cd terraform/azure && terraform test -filter=tests/databases.tftest.hcl`
Expected: PASS.

- [ ] **Step 8: Run the whole terraform + engine suites**

Run: `cd terraform/azure && terraform test`
Then: `cd engine && python -m pytest`
Expected: PASS for both.

- [ ] **Step 9: Commit**

```bash
git add engine/generate_tf_fixtures.py terraform/azure/tests/ terraform/azure/modules/container-app/outputs.tf
git commit -m "test(tf): multi-database fixtures and coverage"
```

---

### Task 6: Docs + sample

**Files:**

- Modify: `docs/usage.md` (database section)
- Modify: `README.md` (if it lists manifest features)
- Modify: `samples/caller-app/cloud-app.yml` (optional illustrative `databases` example)

**Interfaces:** none (documentation).

- [ ] **Step 1: Document `databases:` and per-app opt-in**

In `docs/usage.md`, next to the existing `database:` example, add a `databases:` example showing multiple servers, `dbs:`, app opt-in, and the derived `<SERVER>_<DB>_DATABASE_URL` env var names. State that the singular `database:` form still works and injects blanket `DATABASE_URL`.

Suggested block:

```markdown
### Multiple databases

    name: shop
    apps:
      api:
        databases: [primary/orders, reporting/main]
    databases:
      primary:
        type: postgres
        dbs: [orders, billing]
      reporting:
        type: sqlserver

Each app receives `<SERVER>_<DB>_DATABASE_URL` (e.g. `PRIMARY_ORDERS_DATABASE_URL`)
for every ref it opts into. The singular `database:` form still works and injects a
blanket `DATABASE_URL`.
```

- [ ] **Step 2: Skim README for a feature list mentioning databases and update if present**

Run: `grep -n -i "database" README.md`
If a feature/config list mentions the singular database, add a one-line note that multiple databases are supported via `databases:`.

- [ ] **Step 3: Run a final full check**

Run: `cd engine && python -m pytest` and `cd terraform/azure && terraform test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/usage.md README.md samples/
git commit -m "docs: multiple databases usage"
```

---

## Self-Review

**Spec coverage:**

- `databases:` map + `dbs` + `name` override → Task 1 (schema), Task 2 (defaults/fold), Task 4 (naming).
- App/function opt-in `databases:` list, allowed alongside `containers:` → Task 1 (schema, Step 7), Task 2 (`_normalize_app` pass-through), Task 4 (`per_app_db_env`).
- Uniform `<SERVER>_<DB>_DATABASE_URL` env + `database-url-<server>-<db>` secret → Task 4 Steps 1-2, verified Task 5 run `app_opt_in_env`.
- Legacy `database:` byte-identical (server name, `main` db, `database-url`, blanket `DATABASE_URL`) → Task 2 fold + marker, Task 4 `db_legacy` branch, verified by unchanged Task 5 `terraform test` on partial/full/multi.
- Server naming mirrors apps rule → Task 4 `db_server_bases`, verified Task 5 `server_naming`.
- `locals.tf` single source of truth for secret names → Task 3 `dbs` map input (module holds no naming), Task 4 `db_secret_names`.
- Cross-ref validation raises `ManifestError` → Task 2 `validate_db_refs`.
- `names.database` → `names.databases` breaking output change → Task 4 Step 5, Task 5 assertion updates. Called out here as the one consumer-visible breaking change.
- Fixture/golden regen → Task 2 Step 8, Task 5 Steps 1-2.
- Docs → Task 6.

**Placeholder scan:** none — every code step shows full code; every command has expected output.

**Type consistency:** module input `dbs` is a `map(string)` (db_name → secret_name) in Task 3 and is fed `local.db_secret_names[each.key]` (same shape) in Task 4. Env-var derivation expression is identical in `per_app_db_env` and `per_function_db_env`. `output.names.databases` (Task 4) matches the assertion key `output.names.databases["main"]`/`["primary"]` (Task 5). Module output `secret_names` (Task 3) matches `module.database["primary"].secret_names` (Task 5).
