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
