import json

from cloudapp import funcdeploy


def _names_json():
    return json.dumps({
        "resource_group": "rg-orders-dev",
        "functions": {"worker": "func-orders-dev"},
    })


def test_deploy_packages_and_config_zips(tmp_path, monkeypatch):
    tool = {"name": "orders", "functions": {"worker": {"runtime": "python:3.11", "package": str(tmp_path)}}}
    calls = []

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "terraform" and "output" in cmd:
            return Result(_names_json())
        return Result("")

    # stub packaging so the test does not shell out to zip internals
    monkeypatch.setattr(funcdeploy.funcpackage, "package", lambda k, fn, wd, r: f"/w/{k}.zip")

    deployed = funcdeploy.deploy(tool, "/tf", ["key=v"], str(tmp_path), run)

    assert deployed == ["func-orders-dev"]
    assert ["terraform", "-chdir=/tf", "init", "-input=false", "-backend-config=key=v"] in calls
    config_zip = next(c for c in calls if c[:2] == ["az", "functionapp"])
    assert "func-orders-dev" in config_zip
    assert "rg-orders-dev" in config_zip
    assert "/w/worker.zip" in config_zip


def test_deploy_noop_when_no_code_functions(tmp_path):
    tool = {"name": "orders", "functions": {"c": {"image": "x:1"}}}
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        raise AssertionError("run must not be called when there are no code functions")

    assert funcdeploy.deploy(tool, "/tf", ["key=v"], str(tmp_path), run) == []
    assert calls == []
