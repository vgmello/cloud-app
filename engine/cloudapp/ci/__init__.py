"""CI provider adapter: step outputs, job summary, log diagnostics.

The engine reports progress and results through this module only — no business
logic module knows which CI it is running under.

Which provider is in use is a process-global fact (the CI you run under never
changes mid-run), so the implementation is a module-level singleton. It is
resolved on first use rather than at import, so a test can substitute one with
``use()`` without having to arrange the environment before the import happens.
"""

import os

from . import base, github

PROVIDERS = {"base": base, "github": github}

_impl = None


def detect(env=None):
    """The provider implied by ``env``. Explicit ``CLOUDAPP_CI`` wins."""
    env = os.environ if env is None else env
    name = env.get("CLOUDAPP_CI") or ("github" if env.get("GITHUB_ACTIONS") else "base")
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"unknown CI provider '{name}'; expected one of {', '.join(sorted(PROVIDERS))}"
        ) from None


def use(impl):
    """Force an implementation. ``use(None)`` restores autodetection."""
    global _impl
    _impl = impl


def _get():
    global _impl
    if _impl is None:
        _impl = detect()
    return _impl


def write_outputs(outputs, fallback_file=None):
    return _get().write_outputs(outputs, fallback_file)


def append_summary(markdown):
    return _get().append_summary(markdown)


def notice(msg):
    return _get().notice(msg)


def warning(msg):
    return _get().warning(msg)


def error(msg):
    return _get().error(msg)
