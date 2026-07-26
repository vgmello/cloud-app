"""Shared state for the fake cloud: a JSON resource graph and call logs.

Everything lives under ``$FAKECLOUD_STATE``, a directory inside the repo tree.
act bind-mounts the repo, so whatever the shims write inside the container is
readable by pytest on the host without any artifact plumbing.

The graph is deliberately dumb -- a dict of resource kind to name to
properties. It is a record of what the deploy did, not a model of Azure.
"""

import json
import os
from pathlib import Path

KINDS = ("resource_groups", "keyvaults", "containerapps", "functionapps", "identities")


def state_dir():
    path = os.environ.get("FAKECLOUD_STATE")
    if not path:
        raise RuntimeError("FAKECLOUD_STATE is not set; the fake cloud shims need it")
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _graph_path():
    return state_dir() / "graph.json"


def load():
    path = _graph_path()
    if not path.exists():
        return {kind: {} for kind in KINDS}
    graph = json.loads(path.read_text())
    for kind in KINDS:
        graph.setdefault(kind, {})
    return graph


def save(graph):
    _graph_path().write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n")


def scenario():
    """Knobs pytest writes before the run to arm failures and seed resources."""
    path = state_dir() / "scenario.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def record(log_name, entry):
    """Append one call record. Every shim invocation lands here, so an assertion
    can check both what ran and what did not."""
    with open(state_dir() / log_name, "a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def calls(log_name):
    """Read back a call log (used from pytest, on the host)."""
    path = state_dir() / log_name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def bump(counter):
    """Increment and return a named counter. Backs the 'fail once, then
    succeed' knobs that exercise the engine's retry paths."""
    path = state_dir() / "counters.json"
    counters = json.loads(path.read_text()) if path.exists() else {}
    counters[counter] = counters.get(counter, 0) + 1
    path.write_text(json.dumps(counters, indent=2, sort_keys=True) + "\n")
    return counters[counter]


def parse_args(argv, booleans=(), multi=()):
    """Split a CLI invocation into its command path, flags, and positionals.

    ``az functionapp deployment source config-zip -g rg -n app --src z.zip``
    becomes ``(["functionapp", "deployment", "source", "config-zip"],
    {"-g": "rg", "-n": "app", "--src": "z.zip"}, [])``.

    `booleans` names flags that take no value, so ``terraform show -no-color
    tfplan`` does not read "tfplan" as the value of ``-no-color``. `multi`
    names flags that may repeat (``-backend-config``, ``-var``, ``-target``)
    and always collect into a list.
    """
    command, flags, positional = [], {}, []
    index = 0
    while index < len(argv) and not argv[index].startswith("-"):
        command.append(argv[index])
        index += 1

    def put(name, value):
        if name in multi:
            flags.setdefault(name, []).append(value)
        else:
            flags[name] = value

    while index < len(argv):
        token = argv[index]
        if not token.startswith("-"):
            positional.append(token)
            index += 1
        elif "=" in token:
            name, value = token.split("=", 1)
            put(name, value)
            index += 1
        elif token in booleans or index + 1 >= len(argv) or argv[index + 1].startswith("-"):
            put(token, True)
            index += 1
        else:
            put(token, argv[index + 1])
            index += 2
    return command, flags, positional
