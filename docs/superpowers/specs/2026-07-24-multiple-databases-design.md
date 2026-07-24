# Multiple databases — design

## Goal

Let a manifest declare multiple databases the same way it declares multiple `apps`,
`functions`, and `static_sites` — via a top-level `databases:` map. Each entry is a
database **server** hosting one or more **logical databases**. Apps and functions
opt in to the databases they need; only opted-in databases get connection strings
injected.

The existing singular `database:` form is kept unchanged as a legacy shorthand so
current manifests deploy byte-identical, with no resource renames.

## Manifest schema

### `databases:` (new, top-level)

```yaml
databases:
  primary:
    type: postgres # enum postgres|sqlserver, default postgres
    size: small # enum small|medium|large, default small
    storage_gb: 32 # 32..16384, default 32
    public_access: false # default false
    name: <server-override> # optional, mirrors apps/functions name override
    dbs: [orders, billing] # logical database names, default [main]
  reporting:
    type: sqlserver
    size: large # dbs omitted -> defaults to [main]
```

- `databases` is an object, `minProperties: 1`, key pattern `^[a-z][a-z0-9-]{0,29}$`,
  each value a `database` def.
- The `database` def gains two properties:
  - `name` — optional string, server resource-name override (same pattern as
    apps/functions: `^[a-z][a-z0-9-]{1,29}$`).
  - `dbs` — array of logical-database identifiers, each `^[a-z][a-z0-9-]{0,29}$`,
    default `["main"]`, `minItems: 1`, entries unique.
- `database` (singular) and `databases` (plural) are mutually exclusive — a top-level
  `not` rule forbids both, mirroring the existing `app`/`apps` rule.

### App/function opt-in

Apps and functions gain a `databases:` property: an array of `"<server>/<db>"` refs.

```yaml
apps:
  api:
    databases: [primary/orders, reporting/main]
    containers:
      main: {} # every container in the app receives the db env vars
      sidecar: {}
functions:
  worker:
    databases: [primary/orders]
```

- `databases` on an app is **app-level** (applies to all containers) and is allowed
  alongside `containers:`. This is a deliberate exception: the schema's `containers`
  branch forbids `cpu`/`memory`/`docker`/`env`/`secrets`/`image` but must permit
  `databases`.
- Ref format: `^[a-z][a-z0-9-]{0,29}/[a-z][a-z0-9-]{0,29}$`. Semantic validity
  (server exists, db exists on that server) is checked in the engine, not the schema.
- The `overlay` def gets `databases` (plural, top-level) and the app/function `databases`
  list, so environment overlays can add or resize databases and change opt-ins.

## Naming and env vars

### Server resource names

Mirror the apps rule (see `locals.tf` `app_bases`):

- 1 entry in `databases:` → `psql-<base>-<env>` / `sql-<base>-<env>` (identical to today).
- 2+ entries → `psql-<base>-<key>-<env>` / `sql-<base>-<key>-<env>`.
- explicit `name:` on the entry wins over both.

The `db_name` local becomes a `db_names` map (`server_key -> resource name`), and
`output.names.database` becomes `output.names.databases` (a map). The legacy singular
path still produces a single-key map so its resource name is unchanged.

### Logical databases

Each name in an entry's `dbs:` becomes a logical-database resource on that server:
`azurerm_postgresql_flexible_server_database` or `azurerm_mssql_database`. Default
`["main"]` reproduces today's single `main` database exactly.

### Key Vault secrets

One secret per (server, db): `database-url-<server>-<db>`, holding that logical db's
connection string. The connection string is built per logical db (its `database=`/
`Database=` component is the db name, not hardcoded `main`).

Legacy singular path keeps the single secret named `database-url`.

### Env vars

Uniform derivation: `<SERVER>_<DB>_DATABASE_URL`, with server key and db name
uppercased and `-` replaced by `_`. Example: `primary/orders` →
`PRIMARY_ORDERS_DATABASE_URL`.

Legacy singular path keeps the blanket `DATABASE_URL` injected into every app and
function (today's behavior).

### Injection (per-app/per-function opt-in)

- An app/function with no `databases:` list receives **no** database env vars.
- An app/function lists refs; each ref injects `<SERVER>_<DB>_DATABASE_URL` bound to
  the `database-url-<server>-<db>` Key Vault secret.
- `STORAGE_CONNECTION` remains blanket (storage is out of scope for this change).

## Where resolution happens

### Engine (`manifest.py`)

Validation and normalization only — no infra wiring.

- **Legacy fold:** a top-level singular `database:` normalizes into
  `databases: {main: {..., dbs: ["main"]}}` **and** sets `database_legacy: true` on the
  normalized config so Terraform keeps the `DATABASE_URL` / `database-url` blanket
  wiring. This synthetic key is safe: schema validation runs on the raw manifest
  _before_ `normalize`, so the config `normalize` returns is never re-validated against
  the `additionalProperties: false` root. `resolve.py` spreads the tool config into
  `config` verbatim, so the marker survives into tfvars; `locals.tf` reads it as
  `try(local.cfg.database_legacy, false)`. When a manifest uses `databases:` directly,
  the marker is absent (defaults to `false`).
- Each `databases` entry merges `defaults/database.yml` (via `deep_merge`) and defaults
  `dbs` to `["main"]`.
- Each app/function `databases:` list passes through normalization untouched.
- **Cross-ref validation:** after normalization, every app/function ref
  `"<server>/<db>"` is checked against the declared `databases` map. Unknown server or
  unknown db raises `ManifestError` with a message naming the bad ref and the owning
  app/function. This lives in the engine because it already owns semantic validation
  (the `app`/`apps` mix check, etc.).
- `defaults/database.yml` stays the per-entry default source.

### Terraform

Owns resources, secrets, and env wiring.

- `module.database` changes from `count = local.database != null ? 1 : 0` to
  `for_each = local.databases`. The module holds **no** secret-naming logic — names are
  computed once in `locals.tf` and passed in. The module gains:
  - a `dbs` input: a map `{ db_name => kv_secret_name }`. `locals.tf` fills it from
    `db_secret_names[server][db]`, which is `"database-url"` on the legacy path (single
    `main` db) and `"database-url-<server>-<db>"` otherwise.
  - a loop producing one logical-db resource per key, plus one KV secret per key named
    by its value, holding that db's connection string (its `database=`/`Database=`
    component is the db name).
    This makes `locals.tf` the single source of truth for secret names, so the per-app/
    function env maps and the actual secrets can never drift.
- `locals.tf`:
  - `databases = try(local.cfg.databases, {})`.
  - `db_names` map replacing scalar `db_name`, using the apps naming rule.
  - `per_app_db_env[app_key]` and `per_function_db_env[fn_key]` maps built from each
    entry's `databases:` refs → `{ "<SERVER>_<DB>_DATABASE_URL" => "database-url-<server>-<db>" }`.
  - Legacy marker set → `per_*_db_env` becomes the blanket `{ DATABASE_URL = "database-url" }`
    for every app/function (reproducing `shared_secret_env` today).
  - `shared_secret_env` narrows to just the storage entry; database wiring moves to the
    per-entity maps.
- `main.tf`:
  - `module.container_app` `extra_secret_env = merge(local.storage_secret_env, local.per_app_db_env[each.key])`.
  - `module.function` likewise with `per_function_db_env`.
  - `depends_on = [module.database, module.storage]` unchanged (works with `for_each`).
- `container-app` module precondition error message updates to reflect that reserved
  env names are now dynamic (`<SERVER>_<DB>_DATABASE_URL`, `STORAGE_CONNECTION`).
- `outputs.tf`: `names.database` → `names.databases` (map). Optionally add per-server
  logical-db / fqdn outputs if cheap; not required.

## Testing

### Engine

- New manifest fixtures: multi-server + multi-db, app/function opt-in, legacy singular
  still valid, invalid ref (unknown server), invalid ref (unknown db), duplicate `dbs`
  entries.
- Golden JSON regen for every affected manifest.
- New tests: unknown-ref raises `ManifestError`; legacy fold produces `databases.main`
  - legacy marker; `dbs` defaults to `[main]`.

### Terraform

- New / updated `.tftest.hcl` cases:
  - multi-server naming (1 entry keeps `psql-<base>-<env>`; 2+ append key),
  - logical-db resource count per server,
  - per-app env wiring (`PRIMARY_ORDERS_DATABASE_URL` bound to correct secret),
  - legacy `DATABASE_URL` / `database-url` preserved on the singular path.
- Update existing `partial` / `full` / `multi` fixtures + goldens.

### Fixtures

- `engine/generate_tf_fixtures.py` regen after schema/normalize changes.

## Migration / compatibility

- Manifests using singular `database:` deploy byte-identical: same server name, same
  `main` logical db, same `database-url` secret, same blanket `DATABASE_URL`. No
  resource renames, no plan diff.
- `databases:` is purely additive.
- Main cost is churn in golden/fixture files and the `names.database` →
  `names.databases` output shape (a breaking change for any consumer reading that
  output — call out in the plan).

## Out of scope

- Multiple storage accounts (storage stays singular + blanket `STORAGE_CONNECTION`).
- Per-db users/roles/least-privilege at the SQL level (all dbs on a server share the
  server admin credential, as today).
- Cross-manifest / shared database references.
