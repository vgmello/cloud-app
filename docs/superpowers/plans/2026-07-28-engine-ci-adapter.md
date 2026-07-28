# Engine CI Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the cloudapp engine provider-neutral and self-contained, so it can run under GitHub Actions, GitLab CI, or no CI at all, without any business-logic module knowing which.

**Architecture:** All CI coupling in the engine flows through one module today (`gha.py`, 24 call sites). It becomes a `cloudapp.ci` package with a thin implementation per provider (`base`, `github`, `gitlab`), selected once per process by environment detection and dispatched late so tests can substitute it. The manifest JSON Schema moves inside the package so the engine no longer reaches out of its own directory, and a `pyproject.toml` makes it installable.

**Tech Stack:** Python 3.12, pytest, ruff, jsonschema, pyyaml. Site tests are vitest (TypeScript).

## Global Constraints

- Python 3.12 (`.github/workflows/ci.yml:18`).
- Engine tests run from `engine/`: `python3 -m pytest tests/py -q --cov=cloudapp --cov-report=term-missing --cov-fail-under=90`. **Coverage must stay at or above 90%** — every new module needs tests.
- Lint runs from `engine/`: `ruff check --config ruff.toml . ../.github/scripts`. Rules selected are `F`, `I`, `W`, `UP`; `I` means **import blocks must stay alphabetically sorted**.
- `engine/tests/py/conftest.py` puts `engine/` on `sys.path`, so tests import as `from cloudapp import x`. The `repo` fixture returns the `engine/` directory.
- Dependencies are unchanged: `pyyaml>=6.0.3,<7`, `jsonschema>=4.26.0,<5`.
- `engine/requirements.txt` stays in place. Five callers reference it (`ci.yml:35,67`, `release.yml:31`, `deploy-stack/action.yml:57`, `cloud-app/action.yml:132`); replacing it belongs to the runtime-image plan, not this one.
- No behavior change on the GitHub path. Every task must leave the existing suite green.

## Scope

This plan covers rollout steps 1 and 2 of `docs/superpowers/specs/2026-07-27-ci-provider-adapter-design.md`. The remaining steps are separate plans, in this order:

1. **This plan** — engine CI adapter + self-containment.
2. Naming contract (`config.names` emitted by the engine, reference module updated).
3. Runtime container image + the GitHub `docker run` wrapper.
4. Monorepo restructure and the four-artifact publish pipeline.
5. Control-repo template and the Phase 2 control fetch.
6. `identity.py` returning `{issuer, subject, audience}` + bootstrap Terraform `for_each`.
7. GitLab components — blocked on the spec's open OIDC decision.

Nothing in this plan depends on that OIDC decision.

## File Structure

**Created**

| File                                           | Responsibility                                                                                                            |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `engine/cloudapp/ci/__init__.py`               | Provider selection (`detect`), test substitution (`use`), and late-bound dispatch of the five protocol functions.         |
| `engine/cloudapp/ci/base.py`                   | Provider-neutral I/O: files and standard streams. The fallback, and the reference for the minimum every provider must do. |
| `engine/cloudapp/ci/github.py`                 | GitHub Actions: `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY`, `::notice/warning/error::`.                                       |
| `engine/cloudapp/ci/gitlab.py`                 | GitLab CI: dotenv report outputs with key normalization, log-only diagnostics.                                            |
| `engine/cloudapp/schema/cloud-app.schema.json` | The manifest schema, relocated into the package (moved, not rewritten).                                                   |
| `engine/pyproject.toml`                        | Package metadata, entry point, and package-data declaration.                                                              |
| `engine/tests/py/test_ci.py`                   | Tests for selection, dispatch, and all three providers.                                                                   |

**Modified**

| File                           | Change                                                                                                                 |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `engine/cloudapp/cli.py`       | Import `ci` instead of `gha` (line 20, alphabetical position changes); 18 call sites; 3 new `validate-lock` arguments. |
| `engine/cloudapp/secrets.py`   | Import (line 8), 3 call sites, 1 GitHub-specific message (line 125).                                                   |
| `engine/cloudapp/tfdeploy.py`  | Import (line 10), 2 call sites.                                                                                        |
| `engine/cloudapp/bootcache.py` | Import (line 34), 1 call site.                                                                                         |
| `engine/cloudapp/registry.py`  | `persist_lock` gains bot identity, remote, and branch parameters (lines 83-109).                                       |
| `engine/cloudapp/manifest.py`  | `SCHEMA_PATH` points inside the package (lines 15-17).                                                                 |
| `site/tests/content.test.ts`   | Schema URL follows the move (line 12).                                                                                 |
| `README.md`                    | Schema path in the repo table (line 64).                                                                               |

**Deleted**

| File                     | Why                                  |
| ------------------------ | ------------------------------------ |
| `engine/cloudapp/gha.py` | Replaced by `cloudapp/ci/github.py`. |

---

### Task 1: The `ci` package — selection, dispatch, and the neutral provider

**Files:**

- Create: `engine/cloudapp/ci/__init__.py`
- Create: `engine/cloudapp/ci/base.py`
- Test: `engine/tests/py/test_ci.py`

**Interfaces:**

- Consumes: nothing.
- Produces: the protocol every provider implements and every later task depends on —
  - `write_outputs(outputs: dict[str, Any], fallback_file: str | Path | None = None) -> None`
  - `append_summary(markdown: str) -> None`
  - `notice(msg: str) -> None`
  - `warning(msg: str) -> None`
  - `error(msg: str) -> None`

  Plus, on the package itself: `detect(env: Mapping | None = None) -> module`, `use(impl) -> None`, and `PROVIDERS: dict[str, module]`. On `base` only: `render(outputs: dict) -> str`, the shared `key=value` encoder that `github` and `gitlab` both reuse.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/py/test_ci.py`:

```python
"""The CI provider adapter: selection, dispatch, and per-provider I/O.

Provider tests call the provider modules directly rather than through the
package-level functions, so that a real GITHUB_ACTIONS in the ambient
environment cannot change what they exercise.
"""

import pytest

from cloudapp import ci
from cloudapp.ci import base

PROTOCOL = ("write_outputs", "append_summary", "notice", "warning", "error")


@pytest.fixture(autouse=True)
def reset_impl():
    """No test may leak a selected implementation into the next one."""
    ci.use(None)
    yield
    ci.use(None)


class FakeCI:
    def __init__(self):
        self.outputs = []
        self.summaries = []
        self.messages = []

    def write_outputs(self, outputs, fallback_file=None):
        self.outputs.append((outputs, fallback_file))

    def append_summary(self, markdown):
        self.summaries.append(markdown)

    def notice(self, msg):
        self.messages.append(("notice", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


def test_detect_defaults_to_base_outside_ci():
    assert ci.detect({}) is base


def test_unknown_provider_is_an_error_not_a_silent_fallback():
    with pytest.raises(ValueError, match="unknown CI provider 'jenkins'"):
        ci.detect({"CLOUDAPP_CI": "jenkins"})


def test_use_substitutes_the_implementation():
    fake = FakeCI()
    ci.use(fake)

    ci.write_outputs({"a": "1"})
    ci.append_summary("# hi")
    ci.notice("n")
    ci.warning("w")
    ci.error("e")

    assert fake.outputs == [({"a": "1"}, None)]
    assert fake.summaries == ["# hi"]
    assert fake.messages == [("notice", "n"), ("warning", "w"), ("error", "e")]


def test_use_none_restores_autodetection(monkeypatch):
    ci.use(FakeCI())
    ci.use(None)
    monkeypatch.delenv("CLOUDAPP_CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    assert ci.detect() is base


def test_base_writes_outputs_to_the_fallback_file(tmp_path):
    out = tmp_path / "outputs.txt"
    base.write_outputs({"name": "orders", "docker": "true"}, fallback_file=out)
    assert out.read_text() == "name=orders\ndocker=true\n"


def test_base_without_a_fallback_file_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base.write_outputs({"name": "orders"})
    assert list(tmp_path.iterdir()) == []


def test_base_summary_goes_to_stdout(capsys):
    base.append_summary("### plan")
    assert capsys.readouterr().out == "### plan\n"


def test_base_diagnostics_split_across_streams(capsys):
    base.notice("n")
    base.warning("w")
    base.error("e")
    captured = capsys.readouterr()
    assert captured.out == "notice: n\n"
    assert captured.err == "warning: w\nerror: e\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd engine && python3 -m pytest tests/py/test_ci.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'cloudapp.ci'`.

- [ ] **Step 3: Write `base.py`**

Create `engine/cloudapp/ci/base.py`:

```python
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
```

- [ ] **Step 4: Write `__init__.py`**

Create `engine/cloudapp/ci/__init__.py`. `github` and `gitlab` do not exist yet, so this version registers only `base`; Tasks 2 and 3 add them.

```python
"""CI provider adapter: step outputs, job summary, log diagnostics.

The engine reports progress and results through this module only — no business
logic module knows which CI it is running under.

Which provider is in use is a process-global fact (the CI you run under never
changes mid-run), so the implementation is a module-level singleton. It is
resolved on first use rather than at import, so a test can substitute one with
``use()`` without having to arrange the environment before the import happens.
"""

import os

from . import base

PROVIDERS = {"base": base}

_impl = None


def detect(env=None):
    """The provider implied by ``env``. Explicit ``CLOUDAPP_CI`` wins."""
    env = os.environ if env is None else env
    name = env.get("CLOUDAPP_CI") or "base"
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
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd engine && python3 -m pytest tests/py/test_ci.py -q
```

Expected: PASS, 8 tests.

- [ ] **Step 6: Lint**

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add engine/cloudapp/ci/__init__.py engine/cloudapp/ci/base.py engine/tests/py/test_ci.py
git commit -m "feat(engine): add the CI provider adapter with a neutral implementation"
```

---

### Task 2: The GitHub provider

**Files:**

- Create: `engine/cloudapp/ci/github.py`
- Modify: `engine/cloudapp/ci/__init__.py` (register the provider, extend `detect`)
- Modify: `engine/tests/py/test_ci.py` (append)

**Interfaces:**

- Consumes: `base.render` from Task 1; the five protocol functions Task 1 defined.
- Produces: `cloudapp.ci.github`, behaviorally identical to today's `cloudapp.gha`. Task 4 replaces `gha` with it.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/py/test_ci.py`, and extend the existing import line to `from cloudapp.ci import base, github`:

```python
def test_detect_recognises_github():
    assert ci.detect({"GITHUB_ACTIONS": "true"}) is github


def test_explicit_override_beats_github_autodetection():
    assert ci.detect({"CLOUDAPP_CI": "base", "GITHUB_ACTIONS": "true"}) is base


def test_github_appends_outputs_to_github_output(tmp_path, monkeypatch):
    gh = tmp_path / "gh-output"
    gh.write_text("existing=1\n")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    github.write_outputs({"image-tags": "{}"})
    assert gh.read_text() == "existing=1\nimage-tags={}\n"


def test_github_writes_both_the_fallback_file_and_github_output(tmp_path, monkeypatch):
    gh = tmp_path / "gh-output"
    fallback = tmp_path / "outputs.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    github.write_outputs({"name": "orders"}, fallback_file=fallback)
    assert gh.read_text() == "name=orders\n"
    assert fallback.read_text() == "name=orders\n"


def test_github_outputs_are_a_no_op_off_ci(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    github.write_outputs({"name": "orders"})


def test_github_appends_to_the_step_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    github.append_summary("### plan")
    assert summary.read_text() == "### plan\n"


def test_github_summary_is_a_no_op_off_ci(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    github.append_summary("### plan")


def test_github_annotations_use_the_workflow_command_syntax(capsys):
    github.notice("n")
    github.warning("w")
    github.error("e")
    assert capsys.readouterr().out == "::notice::n\n::warning::w\n::error::e\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd engine && python3 -m pytest tests/py/test_ci.py -q
```

Expected: collection error — `ImportError: cannot import name 'github' from 'cloudapp.ci'`.

- [ ] **Step 3: Write `github.py`**

Create `engine/cloudapp/ci/github.py`. This is `cloudapp/gha.py` with the shared encoder factored out; behavior is unchanged.

```python
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
```

- [ ] **Step 4: Register it in `__init__.py`**

In `engine/cloudapp/ci/__init__.py`, change the import, the registry, and the detection expression:

```python
from . import base, github

PROVIDERS = {"base": base, "github": github}
```

```python
    name = env.get("CLOUDAPP_CI") or ("github" if env.get("GITHUB_ACTIONS") else "base")
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd engine && python3 -m pytest tests/py/test_ci.py -q
```

Expected: PASS, 16 tests.

- [ ] **Step 6: Lint and commit**

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
```

```bash
git add engine/cloudapp/ci/__init__.py engine/cloudapp/ci/github.py engine/tests/py/test_ci.py
git commit -m "feat(engine): add the GitHub Actions CI provider"
```

---

### Task 3: The GitLab provider

**Files:**

- Create: `engine/cloudapp/ci/gitlab.py`
- Modify: `engine/cloudapp/ci/__init__.py` (register the provider, extend `detect`)
- Modify: `engine/tests/py/test_ci.py` (append)

**Interfaces:**

- Consumes: `base.render`, `base.append_summary`, `base.notice`, `base.warning`, `base.error` from Task 1.
- Produces: `cloudapp.ci.gitlab`, plus `gitlab.dotenv_key(key: str) -> str`, the normalization the GitLab pipeline templates must mirror when they read outputs.

**Why this provider differs.** Two things are forced by GitLab, not chosen:

1. GitLab `dotenv` report keys must match `[A-Za-z_][A-Za-z0-9_]*`. The engine emits hyphenated keys (`image-tags`, `secret-count`, `vault-exists`), which GitLab rejects outright. They are normalized on the way into the report. The `fallback_file` deliberately keeps the engine spelling, so the portable encoding stays identical across providers.
2. GitLab has no job-summary surface. Summaries go to the job log, and must never raise — losing a summary is cosmetic, failing a deploy over one is not.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/py/test_ci.py`, and extend the import line to `from cloudapp.ci import base, github, gitlab`:

```python
def test_detect_recognises_gitlab():
    assert ci.detect({"GITLAB_CI": "true"}) is gitlab


def test_explicit_override_beats_autodetection():
    assert ci.detect({"CLOUDAPP_CI": "gitlab", "GITHUB_ACTIONS": "true"}) is gitlab


@pytest.mark.parametrize(
    ("engine_key", "expected"),
    [
        ("image-tags", "IMAGE_TAGS"),
        ("secret-count", "SECRET_COUNT"),
        ("vault-exists", "VAULT_EXISTS"),
        ("custom_tf", "CUSTOM_TF"),
        ("name", "NAME"),
    ],
)
def test_hyphenated_keys_become_valid_dotenv_identifiers(engine_key, expected):
    assert gitlab.dotenv_key(engine_key) == expected


def test_gitlab_appends_normalised_outputs_to_the_dotenv_report(tmp_path, monkeypatch):
    dotenv = tmp_path / "cloudapp.env"
    monkeypatch.setenv("CLOUDAPP_DOTENV", str(dotenv))
    gitlab.write_outputs({"image-tags": "{}", "vault-exists": "true"})
    assert dotenv.read_text() == "IMAGE_TAGS={}\nVAULT_EXISTS=true\n"


def test_gitlab_dotenv_appends_rather_than_truncating(tmp_path, monkeypatch):
    dotenv = tmp_path / "cloudapp.env"
    dotenv.write_text("EXISTING=1\n")
    monkeypatch.setenv("CLOUDAPP_DOTENV", str(dotenv))
    gitlab.write_outputs({"name": "orders"})
    assert dotenv.read_text() == "EXISTING=1\nNAME=orders\n"


def test_gitlab_fallback_file_keeps_the_engine_spelling(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDAPP_DOTENV", raising=False)
    fallback = tmp_path / "outputs.txt"
    gitlab.write_outputs({"image-tags": "{}"}, fallback_file=fallback)
    assert fallback.read_text() == "image-tags={}\n"


def test_gitlab_outputs_are_a_no_op_without_a_dotenv_target(monkeypatch):
    monkeypatch.delenv("CLOUDAPP_DOTENV", raising=False)
    gitlab.write_outputs({"name": "orders"})


def test_gitlab_summary_goes_to_the_log_and_never_raises(capsys):
    gitlab.append_summary("### plan")
    assert capsys.readouterr().out == "### plan\n"


@pytest.mark.parametrize("impl", [base, github, gitlab], ids=["base", "github", "gitlab"])
def test_every_provider_implements_the_protocol(impl):
    for name in PROTOCOL:
        assert callable(getattr(impl, name, None)), f"{impl.__name__} is missing {name}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd engine && python3 -m pytest tests/py/test_ci.py -q
```

Expected: collection error — `ImportError: cannot import name 'gitlab' from 'cloudapp.ci'`.

- [ ] **Step 3: Write `gitlab.py`**

Create `engine/cloudapp/ci/gitlab.py`. Diagnostics and summary are re-exported from `base` rather than retyped — GitLab offers nothing richer than a log line, so there is no second implementation to write. `__all__` documents the re-export and keeps ruff's `F401` quiet.

```python
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
```

- [ ] **Step 4: Register it in `__init__.py`**

In `engine/cloudapp/ci/__init__.py`:

```python
from . import base, github, gitlab

PROVIDERS = {"base": base, "github": github, "gitlab": gitlab}
```

```python
    name = env.get("CLOUDAPP_CI") or (
        "github" if env.get("GITHUB_ACTIONS")
        else "gitlab" if env.get("GITLAB_CI")
        else "base"
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd engine && python3 -m pytest tests/py/test_ci.py -q
```

Expected: PASS, 30 tests.

- [ ] **Step 6: Lint and commit**

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
```

```bash
git add engine/cloudapp/ci/__init__.py engine/cloudapp/ci/gitlab.py engine/tests/py/test_ci.py
git commit -m "feat(engine): add the GitLab CI provider"
```

---

### Task 4: Migrate the call sites and retire `gha.py`

**Files:**

- Modify: `engine/cloudapp/cli.py` (import at line 20; call sites at 92, 113, 114, 125, 138, 143, 175, 185, 245, 253, 257, 271, 273, 287, 290, 295, 425, 437)
- Modify: `engine/cloudapp/secrets.py` (import at line 8; call sites at 60, 77, 101)
- Modify: `engine/cloudapp/tfdeploy.py` (import at line 10; call sites at 93, 114)
- Modify: `engine/cloudapp/bootcache.py` (import at line 34; call site at 129)
- Delete: `engine/cloudapp/gha.py`
- Modify: `engine/tests/py/test_ci.py` (append the guard test)

**Interfaces:**

- Consumes: `cloudapp.ci` and its five protocol functions from Tasks 1-3.
- Produces: no new interface. After this task, `cloudapp.gha` does not exist and no engine module references it.

This is a mechanical rename. `ci.<fn>` takes exactly the arguments `gha.<fn>` took, so no call-site argument changes.

- [ ] **Step 1: Write the failing guard test**

Append to `engine/tests/py/test_ci.py`. Add `import re` to the imports at the top of the file.

```python
def test_no_engine_module_references_the_retired_gha_module(repo):
    offenders = sorted(
        path.name
        for path in (repo / "cloudapp").rglob("*.py")
        if re.search(r"\bgha\b", path.read_text())
    )
    assert offenders == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd engine && python3 -m pytest tests/py/test_ci.py::test_no_engine_module_references_the_retired_gha_module -q
```

Expected: FAIL — the assertion lists `bootcache.py`, `cli.py`, `gha.py`, `secrets.py`, `tfdeploy.py`.

- [ ] **Step 3: Rewrite the four imports**

In `engine/cloudapp/cli.py`, the import block spans lines 13-30 and is alphabetically sorted, so `gha` is not simply renamed in place — `ci` sorts between `builds` and `customtf`:

```python
from . import (
    backend,
    bootcache,
    builds,
    ci,
    customtf,
    dockerbuild,
    funcdeploy,
    identity,
    manifest,
    registry,
    resolve,
    rotate,
    runner,
    secrets,
    tfdeploy,
    verify,
)
```

In `engine/cloudapp/secrets.py` line 8:

```python
from . import ci
```

In `engine/cloudapp/tfdeploy.py` line 10:

```python
from . import backend, builds, ci, runner
```

In `engine/cloudapp/bootcache.py` line 34 — keep the absolute form this module already uses; normalising it to a relative import is out of scope:

```python
from cloudapp import ci
```

- [ ] **Step 4: Rewrite the 24 call sites**

Replace every `gha.` with `ci.` in the four modules. Nothing else on those lines changes.

```bash
cd engine && sed -i '' 's/\bgha\./ci./g' cloudapp/cli.py cloudapp/secrets.py cloudapp/tfdeploy.py cloudapp/bootcache.py
```

On GNU sed (Linux) drop the `''` after `-i`.

- [ ] **Step 5: Delete `gha.py`**

```bash
git rm engine/cloudapp/gha.py
```

- [ ] **Step 6: Run the whole suite**

```bash
cd engine && python3 -m pytest tests/py -q --cov=cloudapp --cov-report=term-missing --cov-fail-under=90
```

Expected: PASS, including the guard test, with coverage at or above 90%. Any failure here is a missed call site — re-grep with `grep -rn '\bgha\b' cloudapp/`.

- [ ] **Step 7: Lint and commit**

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
```

```bash
git add engine/cloudapp/cli.py engine/cloudapp/secrets.py engine/cloudapp/tfdeploy.py engine/cloudapp/bootcache.py engine/tests/py/test_ci.py
git commit -m "refactor(engine): route CI I/O through the provider adapter

Replaces the 24 direct gha.* call sites with ci.*, so no business-logic
module knows which CI it runs under. gha.py is removed; its behaviour
lives on unchanged as cloudapp.ci.github."
```

---

### Task 5: Remove the remaining provider assumptions

**Files:**

- Modify: `engine/cloudapp/secrets.py:125`
- Modify: `engine/cloudapp/registry.py:83-109`
- Modify: `engine/cloudapp/cli.py` (the `validate-lock` parser at lines 409-416, and `cmd_validate_lock`'s `persist_lock` call)
- Modify: `engine/tests/py/test_registry.py` (append)
- Modify: `engine/tests/py/test_secrets.py` (update the assertion on the missing-secrets message)

**Interfaces:**

- Consumes: `registry.persist_lock` as it exists today — `persist_lock(runner, cwd, env, stack_name, caller_repo)`.
- Produces: the widened signature every later plan's pipeline templates call —
  `persist_lock(runner, cwd, env, stack_name, caller_repo, *, bot_name="github-actions[bot]", bot_email="github-actions[bot]@users.noreply.github.com", remote="origin", branch="main") -> None`.
  And three new `validate-lock` CLI arguments: `--bot-name`, `--bot-email`, `--registry-branch`.

Defaults reproduce today's hardcoded values exactly, so the GitHub path is byte-identical and this task changes no behavior.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/py/test_registry.py`:

```python
def test_persist_lock_defaults_to_the_github_actions_bot():
    runner = FakeRunner()
    registry.persist_lock(runner, "central-workspace", "prod", "orders", "acme/orders")
    assert ["git", "config", "user.name", "github-actions[bot]"] in runner.calls
    assert ["git", "push", "origin", "HEAD:main"] in runner.calls


def test_persist_lock_accepts_a_different_bot_and_branch():
    runner = FakeRunner()
    registry.persist_lock(
        runner, "central-workspace", "prod", "orders", "acme/orders",
        bot_name="cloud-app-bot",
        bot_email="cloud-app-bot@example.com",
        remote="upstream",
        branch="trunk",
    )
    assert ["git", "config", "user.name", "cloud-app-bot"] in runner.calls
    assert ["git", "config", "user.email", "cloud-app-bot@example.com"] in runner.calls
    assert ["git", "pull", "--rebase", "--autostash", "upstream", "trunk"] in runner.calls
    assert ["git", "push", "upstream", "HEAD:trunk"] in runner.calls
```

`FakeRunner` is already imported at `engine/tests/py/test_registry.py:3` (`from conftest import FakeResult, FakeRunner`) — no import change is needed.

In `engine/tests/py/test_secrets.py`, change line 30 from:

```python
    with pytest.raises(secrets.SyncError, match="missing GitHub environment secrets: STRIPE_KEY"):
```

to:

```python
    with pytest.raises(secrets.SyncError, match="missing environment secrets: STRIPE_KEY"):
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd engine && python3 -m pytest tests/py/test_registry.py tests/py/test_secrets.py -q
```

Expected: FAIL — `persist_lock() got an unexpected keyword argument 'bot_name'`, plus the secrets assertion mismatch.

- [ ] **Step 3: Widen `persist_lock`**

In `engine/cloudapp/registry.py`, replace the signature and the body's hardcoded values (lines 83-104). The docstring keeps its existing `--autostash` explanation; only the parameter note is new.

```python
def persist_lock(runner, cwd, env, stack_name, caller_repo, *,
                 bot_name="github-actions[bot]",
                 bot_email="github-actions[bot]@users.noreply.github.com",
                 remote="origin", branch="main"):
    """Commit and push the new lock back to the central repo. Fail-closed: if
    any git step fails (e.g. a push race), the lock was not persisted, so we
    raise instead of letting the deploy proceed with an unregistered stack.
    Arg-lists (never a shell string) keep the caller-controlled name/repo from
    being interpolated into a command.

    The committer identity and push target are parameters because the control
    plane may be hosted anywhere; the defaults reproduce the GitHub-hosted
    values this ran with before they were configurable.

    ``--autostash`` on the rebase: `terraform init` on the runner can leave
    the tree dirty (e.g. appending a platform hash to a tracked provider lock
    file) even before this function's own commit. Since this path fails
    closed, a plain `pull --rebase` refusing on a dirty tree would turn into a
    hard failure here rather than a warning."""
    def git(*args):
        runner(["git", *args], cwd=cwd)

    try:
        git("config", "user.name", bot_name)
        git("config", "user.email", bot_email)
        git("add", f"registries/{env}/{stack_name}.yml")
        git("commit", "-m", f"lock(registry): auto-register {stack_name} to {caller_repo} [{env}]")
        git("pull", "--rebase", "--autostash", remote, branch)
        git("push", remote, f"HEAD:{branch}")
    except subprocess.CalledProcessError as exc:
        raise RegistryError(
            f"Failed to persist stack lock for '{stack_name}' ({exc}); "
            "aborting so ownership is not silently lost."
        )
```

- [ ] **Step 4: Thread the new arguments through the CLI**

In `engine/cloudapp/cli.py`, add three arguments to the `validate-lock` parser (after `--central-root`, line 415):

```python
    p.add_argument("--bot-name", default="github-actions[bot]")
    p.add_argument("--bot-email", default="github-actions[bot]@users.noreply.github.com")
    p.add_argument("--registry-branch", default="main")
```

And pass them at the `persist_lock` call in `cmd_validate_lock`:

```python
    registry.persist_lock(
        runner.run, args.central_root, args.environment, args.stack_name, args.caller_repo,
        bot_name=args.bot_name, bot_email=args.bot_email, branch=args.registry_branch,
    )
```

- [ ] **Step 5: Reword the GitHub-specific message**

In `engine/cloudapp/secrets.py` line 125:

```python
        raise SyncError("missing environment secrets: " + ", ".join(missing))
```

- [ ] **Step 6: Run the whole suite**

```bash
cd engine && python3 -m pytest tests/py -q --cov=cloudapp --cov-report=term-missing --cov-fail-under=90
```

Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
```

```bash
git add engine/cloudapp/registry.py engine/cloudapp/secrets.py engine/cloudapp/cli.py engine/tests/py/test_registry.py engine/tests/py/test_secrets.py
git commit -m "refactor(engine): make the committer identity and push target configurable

The lock registry hardcoded github-actions[bot] and origin/main. Both are
now parameters whose defaults reproduce the previous values exactly, so the
GitHub path is unchanged. Also drops 'GitHub' from the missing-secrets
message, which is shown on every host."
```

---

### Task 6: Move the schema inside the package

**Files:**

- Move: `terraform/schema/cloud-app.schema.json` → `engine/cloudapp/schema/cloud-app.schema.json`
- Modify: `engine/cloudapp/manifest.py:15-17`
- Modify: `site/tests/content.test.ts:12`
- Modify: `README.md:64`
- Modify: `engine/tests/py/test_manifest.py` (append)

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `manifest.SCHEMA_PATH` now resolves inside the package. Task 7 relies on this to declare the file as package data.

The schema defines the manifest interface, which is the engine's contract. `terraform/` is a consumer-owned reference implementation per the spec, so a schema living there is the wrong side of the boundary — and it is what stops the engine from being installable, since `_PKG.parents[1]` only resolves inside a source checkout.

- [ ] **Step 1: Write the failing test**

`engine/tests/py/test_manifest.py` currently imports only `pytest`, three conftest helpers, and `manifest`. Add `Path` to the top of the file, keeping ruff's `I` rule satisfied — standard library first, then a blank line:

```python
from pathlib import Path

import pytest
from conftest import FIXTURES, load_golden, load_manifest

from cloudapp import manifest
```

Then append:

```python
def test_the_schema_ships_inside_the_package():
    """The engine must not reach outside its own directory to validate a manifest."""
    package_root = Path(manifest.__file__).parent
    assert manifest.SCHEMA_PATH.is_file()
    assert manifest.SCHEMA_PATH.is_relative_to(package_root)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd engine && python3 -m pytest tests/py/test_manifest.py::test_the_schema_ships_inside_the_package -q
```

Expected: FAIL on the `is_relative_to` assertion — the path currently resolves to `terraform/schema/`.

- [ ] **Step 3: Move the file**

```bash
mkdir -p engine/cloudapp/schema
git mv terraform/schema/cloud-app.schema.json engine/cloudapp/schema/cloud-app.schema.json
```

`terraform/schema/` is now empty; git removes it automatically.

- [ ] **Step 4: Repoint `manifest.py`**

Replace lines 15-17 of `engine/cloudapp/manifest.py`:

```python
_PKG = Path(__file__).parent
SCHEMA_PATH = _PKG / "schema" / "cloud-app.schema.json"
DEFAULTS_DIR = _PKG / "defaults"
```

The old comment on line 16 (`engine/cloudapp -> repo root; terraform/ lives at the repo root, not in engine/`) goes away with the line it explained.

- [ ] **Step 5: Repoint the site test**

In `site/tests/content.test.ts` line 12:

```typescript
      new URL("../../engine/cloudapp/schema/cloud-app.schema.json", import.meta.url),
```

- [ ] **Step 6: Update the README table**

In `README.md` line 64, change the path in the first column from `terraform/schema/cloud-app.schema.json` to `engine/cloudapp/schema/cloud-app.schema.json`.

- [ ] **Step 7: Run both suites**

```bash
cd engine && python3 -m pytest tests/py -q --cov=cloudapp --cov-report=term-missing --cov-fail-under=90
```

Expected: PASS.

```bash
cd site && npm test
```

Expected: PASS — `content.test.ts` still validates every sample manifest against the schema at its new location.

- [ ] **Step 8: Lint and commit**

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
```

```bash
git add engine/cloudapp/schema/cloud-app.schema.json engine/cloudapp/manifest.py site/tests/content.test.ts README.md
git commit -m "refactor(engine): move the manifest schema into the package

The schema is the engine's interface contract, while terraform/ is a
consumer-owned reference implementation. Keeping the schema there also
made the engine unimportable outside a source checkout, since the path
resolved via parents[1]."
```

---

### Task 7: Make the engine installable

**Files:**

- Create: `engine/pyproject.toml`
- Modify: `engine/tests/py/test_manifest.py` (append)

**Interfaces:**

- Consumes: `manifest.SCHEMA_PATH` inside the package (Task 6); `cloudapp.cli:main` as the console entry point.
- Produces: an installable distribution named `cloud-app-engine` exposing the `cloudapp` console script. The runtime-image plan installs this instead of setting `PYTHONPATH`.

`engine/requirements.txt` stays. Five call sites reference it, and `ci.yml:35` feeds it to `pip-audit`; retiring it belongs to the runtime-image plan.

- [ ] **Step 1: Write the failing test**

Append to `engine/tests/py/test_manifest.py`:

```python
def test_package_data_covers_every_non_python_file_the_engine_reads():
    """Schema and defaults must be declared as package data, or an installed
    engine validates nothing and resolves no defaults."""
    import tomllib

    pyproject = Path(manifest.__file__).parents[2] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["tool"]["setuptools"]["package-data"]["cloudapp"]
    assert "schema/*.json" in declared
    assert "defaults/*.yml" in declared
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd engine && python3 -m pytest tests/py/test_manifest.py::test_package_data_covers_every_non_python_file_the_engine_reads -q
```

Expected: FAIL — `FileNotFoundError` on `pyproject.toml`.

- [ ] **Step 3: Write `pyproject.toml`**

Create `engine/pyproject.toml`. Dependency pins are copied verbatim from `engine/requirements.txt`; `requires-python` matches the CI interpreter.

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "cloud-app-engine"
version = "0.1.0"
description = "cloud-app deployment engine: manifest parsing, config resolution, and deploy orchestration"
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6.0.3,<7",
    "jsonschema>=4.26.0,<5",
]

[project.scripts]
cloudapp = "cloudapp.cli:main"

[tool.setuptools.packages.find]
include = ["cloudapp*"]

[tool.setuptools.package-data]
cloudapp = ["defaults/*.yml", "schema/*.json"]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd engine && python3 -m pytest tests/py/test_manifest.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify a real install works end to end**

```bash
cd engine && python3 -m venv /tmp/cloudapp-install-check \
  && /tmp/cloudapp-install-check/bin/pip install -q . \
  && /tmp/cloudapp-install-check/bin/cloudapp --help \
  && /tmp/cloudapp-install-check/bin/python -c "from cloudapp import manifest; assert manifest.SCHEMA_PATH.is_file(), manifest.SCHEMA_PATH; print('schema packaged OK')"
```

Expected: the subcommand list from `--help`, then `schema packaged OK`. A `FileNotFoundError` here means `package-data` did not take effect.

```bash
rm -rf /tmp/cloudapp-install-check
```

- [ ] **Step 6: Run the whole suite**

```bash
cd engine && python3 -m pytest tests/py -q --cov=cloudapp --cov-report=term-missing --cov-fail-under=90
```

Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
```

```bash
git add engine/pyproject.toml engine/tests/py/test_manifest.py
git commit -m "feat(engine): make the engine an installable package

Adds pyproject.toml with a cloudapp console script and package-data for
the schema and defaults. requirements.txt stays for now; five call sites
and pip-audit still consume it."
```

---

## Verification

After Task 7, the full gate the repo's CI runs:

```bash
cd engine && ruff check --config ruff.toml . ../.github/scripts
cd engine && python3 -m pytest tests/py -q --cov=cloudapp --cov-report=term-missing --cov-fail-under=90
python3 -m pytest .github/scripts/tests -q
cd site && npm test
```

Then confirm the GitHub path is genuinely unchanged — the fingerprint covers `engine/cloudapp/identity.py`, which this plan does not touch, so it must still match:

```bash
PYTHONPATH=engine python3 -m cloudapp bootstrap-fingerprint --root . | diff - bootstrap.fingerprint
```

Expected: no output.
