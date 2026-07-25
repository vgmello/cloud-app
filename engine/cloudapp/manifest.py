"""Manifest pipeline: validate cloud-app.yml, merge env overlays, normalize.

Normalized shape (per environment) is the Terraform contract: every app has an
explicit ``containers`` map and a full ingress object (or none for workers);
single-container shorthand folds into ``containers.main``.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .yamlcompat import load_yaml as _load_yaml_12

_PKG = Path(__file__).parent
# engine/cloudapp -> repo root; terraform/ lives at the repo root, not in engine/
SCHEMA_PATH = _PKG.parents[1] / "terraform" / "schema" / "cloud-app.schema.json"
DEFAULTS_DIR = _PKG / "defaults"

CONTAINER_DEFAULTS = {"cpu": 0.5, "memory": "1Gi", "env": {}, "secrets": []}
REPLICA_DEFAULTS = {"min": 1, "max": 3}
SHORTHAND_FIELDS = ("cpu", "memory", "docker", "image", "env", "secrets")


def function_mode(fn):
    """"code" when the function declares a runtime stack, else "container"."""
    return "code" if "runtime" in fn else "container"


def normalize_terraform(value):
    """Fold the `terraform:` shorthand string into the {dir, providers} object."""
    entry = {"dir": value} if isinstance(value, str) else dict(value)
    entry.setdefault("providers", [])
    return entry


class ManifestError(Exception):
    pass


def deep_merge(base, override):
    """yq `*` semantics: maps merge recursively, arrays and scalars replace."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base[key], value) if key in base else value
        return merged
    return override


def _load_yaml(path):
    return _load_yaml_12(Path(path).read_text()) or {}


def validate(manifest):
    """Return human-readable schema violations, empty when valid."""
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: list(e.absolute_path),
    )
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    ]


def _normalize_ingress(app):
    base = {
        "external": False,
        "target_port": app.get("port", 8080),
        "transport": "auto",
        "allow_insecure": False,
    }
    ingress = app.get("ingress")
    if ingress == "none":
        return None
    if ingress is None or ingress == "internal":
        return base
    if ingress == "public":
        return {**base, "external": True}
    return {**base, **ingress}


def _normalize_app(app):
    if "containers" in app:
        containers = app["containers"]
    else:
        containers = {"main": {k: app[k] for k in SHORTHAND_FIELDS if k in app}}
    containers = {k: deep_merge(CONTAINER_DEFAULTS, c) for k, c in containers.items()}

    normalized = {}
    if "name" in app:
        normalized["name"] = app["name"]
    ingress = _normalize_ingress(app)
    if ingress is not None:
        normalized["ingress"] = ingress
    normalized["replicas"] = deep_merge(REPLICA_DEFAULTS, app.get("replicas", {}))
    normalized["containers"] = containers
    if "databases" in app:
        normalized["databases"] = app["databases"]
    return normalized


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


def normalize(merged):
    cfg = dict(merged)
    if "app" in cfg and "apps" in cfg:
        raise ManifestError(
            "manifest mixes singular app with apps (possibly via an environment overlay); use one form"
        )
    if "app" in cfg:
        cfg["apps"] = {"main": cfg.pop("app")}
    if "apps" in cfg:
        cfg["apps"] = {k: _normalize_app(a) for k, a in cfg["apps"].items()}
    for section, defaults_file in (("functions", "function"), ("static_sites", "static_site")):
        if section in cfg:
            defaults = _load_yaml(DEFAULTS_DIR / f"{defaults_file}.yml")
            cfg[section] = {k: deep_merge(defaults, v) for k, v in cfg[section].items()}
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
    if "terraform" in cfg:
        cfg["terraform"] = normalize_terraform(cfg["terraform"])
    validate_db_refs(cfg)
    return cfg


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


def parse(manifest_path, app_root="."):
    """Validate and expand a manifest into per-environment normalized configs.

    Returns (name, environments, tools, docker) where tools maps env -> config.
    """
    manifest = _load_yaml_12(Path(manifest_path).read_text())
    errors = validate(manifest)
    if errors:
        raise ManifestError("manifest validation failed:\n" + "\n".join(errors))

    environments = list(manifest.get("environments") or {"dev": {}})
    base = {k: v for k, v in manifest.items() if k != "environments"}
    tools = {}
    for env in environments:
        overlay = (manifest.get("environments") or {}).get(env) or {}
        tools[env] = normalize(deep_merge(base, overlay))

    docker = any(_uses_docker_build(t) for t in tools.values()) or (
        Path(app_root) / "Dockerfile"
    ).exists()
    return manifest["name"], environments, tools, docker
