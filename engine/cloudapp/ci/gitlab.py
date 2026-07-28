"""GitLab CI I/O: dotenv report outputs, plain log diagnostics.

Two differences from GitHub are forced by GitLab rather than chosen:

- ``dotenv`` report keys must match ``[A-Za-z_][A-Za-z0-9_]*``, so GitLab
  rejects the hyphenated keys the engine emits (``image-tags``,
  ``secret-count``, ``vault-exists``). They are normalised on the way into the
  report; the pipeline reads ``IMAGE_TAGS``. ``fallback_file`` keeps the engine
  spelling so the portable encoding is identical on every provider.
- GitLab has no job-summary surface, so summaries go to the job log. That path
  must never raise: losing a summary is cosmetic, and failing a deploy over one
  would not be.
"""

import os
import re
from pathlib import Path

from .base import append_summary, error, notice, render, warning

__all__ = [
    "append_summary",
    "dotenv_key",
    "error",
    "notice",
    "warning",
    "write_outputs",
]

_UNSAFE = re.compile(r"[^A-Za-z0-9_]")


def dotenv_key(key):
    """A dotenv-safe spelling of an engine output key ('image-tags' -> 'IMAGE_TAGS')."""
    return _UNSAFE.sub("_", key).upper()


def write_outputs(outputs, fallback_file=None):
    if fallback_file:
        Path(fallback_file).write_text(render(outputs))
    dotenv = os.environ.get("CLOUDAPP_DOTENV")
    if dotenv:
        with open(dotenv, "a") as f:
            f.write("".join(f"{dotenv_key(k)}={v}\n" for k, v in outputs.items()))
