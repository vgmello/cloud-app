"""Resource-name derivation, mirroring terraform/azure/locals.tf.

Deliberately re-implemented rather than importing cloudapp.naming. The engine
computes the names it expects to find (verify, rotate); this computes the names
the fake cloud creates. If the two drift, the e2e scenarios fail -- which is
the point. Importing the engine here would make the check tautological.
"""


def _entry_base(entries, key, base):
    explicit = (entries.get(key) or {}).get("name")
    if explicit:
        return explicit
    return base if len(entries) == 1 else f"{base}-{key}"


def resource_names(config):
    """The `names` output of terraform/azure/outputs.tf for a resolved config."""
    platform = config.get("platform") or {}
    env = config["environment"]
    base = f"{platform.get('naming_prefix') or ''}{config['name']}"

    apps = config.get("apps") or {}
    functions = config.get("functions") or {}
    static_sites = config.get("static_sites") or {}
    databases = config.get("databases") or {}

    keyvault = f"kv-{base}-{env}"[:24]
    if keyvault.endswith("-"):  # trimsuffix(substr(..., 0, 24), "-")
        keyvault = keyvault[:-1]

    storage = None
    if config.get("storage") is not None:
        storage = f"st{(base + env).replace('-', '')}"[:24]

    db_names = {}
    for key, db in databases.items():
        db_base = _entry_base(databases, key, base)
        kind = "psql" if db.get("type", "postgres") == "postgres" else "sql"
        db_names[key] = f"{kind}-{db_base}-{env}"

    return {
        "resource_group": f"rg-{base}-{env}",
        "keyvault": keyvault,
        "storage": storage,
        "databases": db_names,
        "apps": {k: f"ca-{_entry_base(apps, k, base)}-{env}" for k in apps},
        "functions": {k: f"func-{_entry_base(functions, k, base)}-{env}" for k in functions},
        "static_sites": {k: f"swa-{_entry_base(static_sites, k, base)}-{env}" for k in static_sites},
    }
