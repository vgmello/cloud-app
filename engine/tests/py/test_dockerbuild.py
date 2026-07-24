from conftest import FIXTURES, FakeRunner

from cloudapp import builds, dockerbuild, manifest


def plan_for(fixture, env, name):
    _, _, tools, _ = manifest.parse(FIXTURES / f"{fixture}.yml")
    return builds.enumerate_builds(tools[env], name, "acr.example.io", "sha1")


def test_shared_build_is_built_once_and_pushed_per_key():
    run = FakeRunner()
    dockerbuild.build_and_push(plan_for("full", "prod", "orders-api"), "acr.example.io", run)
    assert run.commands("az", "acr", "login") == [["az", "acr", "login", "--name", "acr"]]
    assert len(run.commands("docker", "build")) == 1
    assert len(run.commands("docker", "tag")) == 2
    assert len(run.commands("docker", "push")) == 3


def test_build_uses_entry_dockerfile_and_context():
    run = FakeRunner()
    dockerbuild.build_and_push(plan_for("multi", "dev", "billing"), "acr.example.io", run)
    (build,) = run.commands("docker", "build")
    assert "./web/Dockerfile" in build
    (push,) = run.commands("docker", "push")
    assert push[-1] == "acr.example.io/billing/gateway-web:sha1"
