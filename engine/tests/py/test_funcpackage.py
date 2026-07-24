import zipfile
from pathlib import Path

from cloudapp import funcpackage


def test_code_functions_filters_by_mode():
    tool = {
        "functions": {
            "a": {"runtime": "python:3.11", "package": "./s"},
            "b": {"image": "x:1"},
        }
    }
    assert list(funcpackage.code_functions(tool)) == ["a"]


def test_package_zip_mode_zips_directory(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hi')\n")
    workdir = tmp_path / "work"
    workdir.mkdir()

    calls = []

    def run(cmd, **kw):
        calls.append(cmd)

    zip_path = funcpackage.package("worker", {"runtime": "python:3.11", "package": str(src)}, str(workdir), run)

    assert calls == []  # no docker in zip mode
    with zipfile.ZipFile(zip_path) as z:
        assert "app.py" in z.namelist()


def test_package_build_mode_runs_builder_and_zips_out(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        # emulate the builder writing to the mounted /out dir
        if cmd[0] == "docker" and cmd[1] == "run":
            out_host = cmd[cmd.index("-v") + 1].split(":")[0]
            Path(out_host, "func.dll").write_text("binary")

    fn = {"runtime": "dotnet-isolated:8.0", "docker": {"file": "./Dockerfile.build", "context": "."}}
    zip_path = funcpackage.package("worker", fn, str(workdir), run)

    kinds = [c[1] for c in calls if c[0] == "docker"]
    assert "build" in kinds and "run" in kinds
    with zipfile.ZipFile(zip_path) as z:
        assert "func.dll" in z.namelist()


def test_package_build_mode_prebuilt_image_skips_build(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "docker" and cmd[1] == "run":
            out_host = cmd[cmd.index("-v") + 1].split(":")[0]
            Path(out_host, "index.js").write_text("x")

    fn = {"runtime": "node:20", "image": "myreg/builder:1"}
    funcpackage.package("worker", fn, str(workdir), run)

    kinds = [c[1] for c in calls if c[0] == "docker"]
    assert "build" not in kinds and "run" in kinds
    # runs the named image directly
    run_cmd = next(c for c in calls if c[:2] == ["docker", "run"])
    assert "myreg/builder:1" in run_cmd
