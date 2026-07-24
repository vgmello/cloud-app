import pytest

from cloudapp import rotate


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


SINGLE = {"name": "orders-api", "apps": {"main": {}}, "functions": {}}


def _recorder(results=None):
    calls = []
    seq = list(results or [])

    def run(cmd, check=False, capture=False):
        calls.append(cmd)
        return seq.pop(0) if seq else _Result(0)

    run.calls = calls
    return run


def test_rotate_container_app_uses_containerapp_update():
    run = _recorder()
    n = rotate.rotate(SINGLE, "", "dev", {"main/main": "reg/orders-api/main-main:sha1"}, "rg-x", run)
    assert n == 1
    assert run.calls[0] == [
        "az", "containerapp", "update",
        "--name", "ca-orders-api-dev",
        "--resource-group", "rg-x",
        "--container-name", "main",
        "--image", "reg/orders-api/main-main:sha1",
    ]


def test_rotate_function_uses_functionapp_container_set():
    tool = {"name": "orders-api", "apps": {}, "functions": {"processor": {}}}
    run = _recorder()
    n = rotate.rotate(tool, "", "dev", {"processor": "reg/orders-api/processor:sha1"}, "rg-x", run)
    assert n == 1
    assert run.calls[0] == [
        "az", "functionapp", "config", "container", "set",
        "--name", "func-orders-api-dev",
        "--resource-group", "rg-x",
        "--image", "reg/orders-api/processor:sha1",
    ]


def test_rotate_empty_map_is_noop():
    run = _recorder()
    assert rotate.rotate(SINGLE, "", "dev", {}, "rg-x", run) == 0
    assert run.calls == []


def test_rotate_raises_on_az_failure():
    run = _recorder([_Result(1, "", "boom")])
    with pytest.raises(rotate.RotateError, match="main/main"):
        rotate.rotate(SINGLE, "", "dev", {"main/main": "reg/o/main-main:sha1"}, "rg-x", run)
