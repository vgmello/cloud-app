"""Provider-neutral CI I/O: files and standard streams only.

The fallback for local runs, for tests, and for any CI the engine does not
recognise. Also the reference for the minimum every provider must do: outputs
land in ``fallback_file`` when one is given, and diagnostics reach the operator.
"""

import sys
from pathlib import Path


def render(outputs):
    """``key=value`` lines, one per output — the portable output encoding."""
    return "".join(f"{k}={v}\n" for k, v in outputs.items())


def write_outputs(outputs, fallback_file=None):
    if fallback_file:
        Path(fallback_file).write_text(render(outputs))


def append_summary(markdown):
    print(markdown)


def notice(msg):
    print(f"notice: {msg}")


def warning(msg):
    print(f"warning: {msg}", file=sys.stderr)


def error(msg):
    print(f"error: {msg}", file=sys.stderr)
