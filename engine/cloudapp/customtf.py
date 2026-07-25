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

# Only plain .tf is accepted. .tf.json was dropped: the forbidden-block scan
# below is HCL-only, so a JSON provider/terraform/backend block would pass
# validation unchecked, and nothing in the feature needs JSON syntax.
TF_SUFFIXES = (".tf",)

# Top-of-line block openers the caller may not declare: providers come from the
# manifest allowlist, and the backend/terraform settings belong to the platform.
_FORBIDDEN_BLOCK = re.compile(r'^\s*(provider\s+"|terraform\s*\{|backend\s+")', re.MULTILINE)

# Matches a heredoc introducer (`<<EOT` / `<<-EOT`) anywhere on a line, so its
# body can be excluded from the forbidden-block scan below.
_HEREDOC_MARKER = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_]*)")

# Platform-owned files that survive a prepare() cleanup pass. _providers.g.tf
# is generated but NOT listed here — it is always removed up front and
# rewritten only when the manifest still declares providers.
_PLATFORM_FILES = {"_context.tf", "_versions.tf"}
_GENERATED_PROVIDERS_FILE = "_providers.g.tf"


class CustomTfError(Exception):
    pass


def _entry(tool):
    return (tool or {}).get("terraform")


def _blank_block_comments(text):
    """Replace /* ... */ spans with equivalent whitespace (newlines kept) so a
    comment-prefixed line like `/**/provider "x" {` can't hide a real block
    from the line-anchored forbidden-block scan."""

    def repl(match):
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return re.sub(r"/\*.*?\*/", repl, text, flags=re.DOTALL)


def _blank_heredoc_bodies(text):
    """Blank out heredoc body lines so a heredoc that merely starts with
    `provider "` as string content isn't mistaken for a real block."""
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        out.append(line)
        match = _HEREDOC_MARKER.search(line)
        i += 1
        if not match:
            continue
        marker = match.group(1)
        while i < n and lines[i].strip() != marker:
            out.append("")
            i += 1
        if i < n:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _has_forbidden_block(text):
    scan_text = _blank_heredoc_bodies(_blank_block_comments(text))
    return bool(_FORBIDDEN_BLOCK.search(scan_text))


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
        try:
            text = path.read_text()
        except UnicodeDecodeError as exc:
            raise CustomTfError(f"'{path.name}' is not valid UTF-8: {exc}") from exc
        if _has_forbidden_block(text):
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
    """Clean custom_dir back to platform-owned files, copy in the caller's
    current .tf, and (re)write _providers.g.tf. Returns names copied.

    Cleans unconditionally — even when the manifest has no `terraform:` field
    and even when the caller dir has zero .tf files — because custom_dir lives
    in the action checkout, which self-hosted runners reuse across jobs. A
    stale file from a previous run, or another app's file on a shared runner,
    must not survive into this run's plan/apply.
    """
    destination = Path(custom_dir)
    try:
        existing = list(destination.iterdir())
    except FileNotFoundError as exc:
        raise CustomTfError(f"custom terraform directory '{custom_dir}' not found") from exc

    for entry in existing:
        # _PLATFORM_FILES excludes _providers.g.tf on purpose: it is
        # regenerated below (or dropped) on every prepare() run.
        if entry.is_file() and entry.name in _PLATFORM_FILES:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    files = collect(tool, app_root)
    for path in files:
        shutil.copyfile(path, destination / path.name)

    tf_entry = _entry(tool)
    if tf_entry:
        body = render_providers(tf_entry.get("providers", []))
        if body is not None:
            (destination / _GENERATED_PROVIDERS_FILE).write_text(body)

    return [p.name for p in files]
