"""GitHub Actions I/O: step outputs, step summary, workflow annotations."""

import os
from pathlib import Path

from .base import render


def write_outputs(outputs, fallback_file=None):
    """Write ``key=value`` outputs to GITHUB_OUTPUT (when set) and optionally a fallback file."""
    lines = render(outputs)
    if fallback_file:
        Path(fallback_file).write_text(lines)
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(lines)


def append_summary(markdown):
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(markdown + "\n")


def notice(msg):
    print(f"::notice::{msg}")


def warning(msg):
    print(f"::warning::{msg}")


def error(msg):
    print(f"::error::{msg}")
