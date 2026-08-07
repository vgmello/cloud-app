"""Azure resource-name derivation — mirrors terraform/azure/locals.tf.

Kept in lockstep with locals.tf so the Lane B image rotation targets the exact
container app / function app names Terraform created. See test_naming.py.
"""


def _base(tool, prefix):
    """Entry-name base: the stack name, suffixed with the component when the
    manifest declares one. Components share a stack (and its resource group and
    Key Vault) but must never derive the same resource name — mirrors
    `local.base` in locals.tf."""
    component = tool.get("component")
    return f"{prefix}{tool['name']}-{component}" if component else f"{prefix}{tool['name']}"


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
