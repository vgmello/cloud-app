import json

from conftest import ENVDIR, FIXTURES

from cloudapp import cli


def read_kv(text):
    return dict(line.split("=", 1) for line in text.splitlines())


def test_parse_manifest_writes_tools_and_outputs(tmp_path, monkeypatch):
    gh = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    out = tmp_path / "cloud-app"
    rc = cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "full.yml"),
        "--output-dir", str(out), "--app-root", str(tmp_path),
    ])
    assert rc == 0
    assert (out / "tool.dev.json").exists()
    assert (out / "tool.prod.json").exists()

    # outputs.txt and GITHUB_OUTPUT carry identical key=value lines
    file_out = read_kv((out / "outputs.txt").read_text())
    gh_out = read_kv(gh.read_text())
    assert file_out == gh_out
    assert file_out["name"] == "orders-api"
    assert file_out["environments"] == '["dev","prod"]'
    assert file_out["docker"] == "true"
    assert "type" not in file_out


def test_parse_manifest_docker_false_without_dockerfile(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    out = tmp_path / "ct"
    cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "minimal.yml"),
        "--output-dir", str(out), "--app-root", str(tmp_path),
    ])
    assert read_kv((out / "outputs.txt").read_text())["docker"] == "false"


def test_parse_manifest_cleans_stale_outputs(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    out = tmp_path / "ct"
    out.mkdir()
    (out / "tool.stale.json").write_text("{}")
    cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "minimal.yml"),
        "--output-dir", str(out), "--app-root", str(tmp_path),
    ])
    assert not (out / "tool.stale.json").exists()
    assert (out / "tool.dev.json").exists()


def test_parse_manifest_flags_code_functions(tmp_path):
    out_dir = tmp_path / "out"
    rc = cli.main([
        "parse-manifest",
        "--manifest", str(FIXTURES / "codefn.yml"),
        "--output-dir", str(out_dir),
        "--app-root", str(tmp_path),
    ])
    assert rc == 0
    outputs = (out_dir / "outputs.txt").read_text()
    assert "code_functions=true" in outputs


def test_invalid_manifest_returns_nonzero_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    out = tmp_path / "ct"
    rc = cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "invalid-legacy-type.yml"),
        "--output-dir", str(out), "--app-root", str(tmp_path),
    ])
    assert rc == 1
    assert "::error::" in capsys.readouterr().out
    assert not (out / "tool.dev.json").exists()


def test_parse_manifest_fails_fast_on_bad_terraform_dir(tmp_path, monkeypatch, capsys):
    """Caller-terraform validation runs during parse-manifest, before the
    bootstrap creates the RG/identities — a typo'd dir must fail here, not
    only later in prepare-custom-tf."""
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    out = tmp_path / "ct"
    rc = cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "terraform-bad-dir.yml"),
        "--output-dir", str(out), "--app-root", str(tmp_path),
    ])
    assert rc == 1
    assert "::error::" in capsys.readouterr().out
    assert not (out / "tool.dev.json").exists()


def test_resolve_config_writes_tfvars(tmp_path):
    tools = tmp_path / "tool.dev.json"
    cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "minimal.yml"),
        "--output-dir", str(tmp_path),
    ])
    out = tmp_path / "tfvars.json"
    rc = cli.main([
        "resolve-config", "--tool-json", str(tools),
        "--platform-file", str(ENVDIR / "dev.yml"),
        "--environment", "dev", "--out-file", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text())["config"]["environment"] == "dev"


def test_resolve_config_missing_platform_returns_nonzero(tmp_path, capsys):
    cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "minimal.yml"),
        "--output-dir", str(tmp_path),
    ])
    rc = cli.main([
        "resolve-config", "--tool-json", str(tmp_path / "tool.dev.json"),
        "--platform-file", str(ENVDIR / "nope.yml"),
        "--environment", "nope", "--out-file", str(tmp_path / "o.json"),
    ])
    assert rc == 1
    assert "platform config not found" in capsys.readouterr().out


def test_enumerate_builds_prints_plan(tmp_path, capsys):
    cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "full.yml"),
        "--output-dir", str(tmp_path),
    ])
    rc = cli.main([
        "enumerate-builds", "--tool-json", str(tmp_path / "tool.dev.json"),
        "--tool-name", "orders-api", "--registry", "acr.example.io", "--git-sha", "sha1",
    ])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert "api/main" in plan["tags"]


def test_docker_build_command_builds_and_writes_image_tags(tmp_path, monkeypatch):
    from cloudapp import runner
    calls = []
    monkeypatch.setattr(runner, "run", lambda *a, **k: calls.append(a[0]))
    gh = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "full.yml"),
        "--output-dir", str(tmp_path),
    ])
    rc = cli.main([
        "docker-build", "--tool-json", str(tmp_path / "tool.dev.json"),
        "--tool-name", "orders-api", "--registry", "acr.example.io", "--git-sha", "sha1",
    ])
    assert rc == 0
    assert any(c[:2] == ["docker", "build"] for c in calls)
    assert "image-tags=" in gh.read_text()


def test_sync_secrets_command_no_secrets(tmp_path, monkeypatch):
    from cloudapp import runner
    monkeypatch.setattr(runner, "run", lambda *a, **k: None)
    monkeypatch.setenv("ALL_SECRETS", "{}")
    gh = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    cli.main([
        "parse-manifest", "--manifest", str(FIXTURES / "minimal.yml"),
        "--output-dir", str(tmp_path),
    ])
    rc = cli.main([
        "sync-secrets", "--tool-json", str(tmp_path / "tool.dev.json"),
        "--keyvault-name", "kv-x",
    ])
    assert rc == 0
    assert "secret-count=0" in gh.read_text()



def test_login_plan_command_emits_phases(capsys):
    from conftest import ENVDIR
    rc = cli.main(["login-plan", "--event", "default_branch", "--platform-file", str(ENVDIR / "dev.yml")])
    assert rc == 0
    phases = json.loads(capsys.readouterr().out)
    assert [p["identity"] for p in phases] == ["bootstrap", "plan", "apply"]


def test_bootstrap_vars_command_delegated_federates_to_caller(capsys):
    from conftest import ENVDIR
    rc = cli.main([
        "bootstrap-vars", "--name", "orders-api", "--environment", "prod",
        "--mode", "delegated", "--app-repo", "acme/orders",
        "--central-repo", "vgmello/cloud-app", "--platform-file", str(ENVDIR / "dev.yml"),
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["plan_subjects"] == ["repo:acme/orders:pull_request", "repo:acme/orders:environment:prod"]
    assert out["apply_subjects"] == ["repo:acme/orders:environment:prod"]
    assert out["name"] == "orders-api"
    assert out["state_account_id"].endswith("/storageAccounts/sttfstatedev")
    assert out["state_container"] == "tfstate"


def test_bootstrap_vars_bad_mode_returns_nonzero(capsys):
    from conftest import ENVDIR
    rc = cli.main([
        "bootstrap-vars", "--name", "x", "--environment", "dev",
        "--mode", "trustme", "--app-repo", "a/b", "--central-repo", "c/d",
        "--platform-file", str(ENVDIR / "dev.yml"),
    ])
    assert rc == 1
    assert "::error::" in capsys.readouterr().out


def test_rotate_images_cli_invokes_az_per_image(tmp_path, monkeypatch, capsys):
    import json as _json

    from cloudapp import cli, runner

    tool = {"name": "orders-api", "apps": {"main": {}}, "functions": {}}
    (tmp_path / "tool.dev.json").write_text(_json.dumps(tool))
    (tmp_path / "dev.yml").write_text('naming_prefix: ""\nstate_backend:\n  type: azurerm\n')

    calls = []

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, check=False, capture=False):
        calls.append(cmd)
        return _R()

    monkeypatch.setattr(runner, "run", fake_run)

    cli.main([
        "rotate-images",
        "--tool-json", str(tmp_path / "tool.dev.json"),
        "--environment", "dev",
        "--platform-file", str(tmp_path / "dev.yml"),
        "--image-tags", _json.dumps({"main/main": "reg/orders-api/main-main:sha1"}),
        "--resource-group", "rg-x",
    ])

    assert calls[0][:3] == ["az", "containerapp", "update"]
    assert "ca-orders-api-dev" in calls[0]
    assert "reg/orders-api/main-main:sha1" in calls[0]


def test_prepare_custom_tf_stages_caller_files(tmp_path):
    app_root = tmp_path / "app"
    (app_root / "terraform").mkdir(parents=True)
    (app_root / "terraform" / "queue.tf").write_text('resource "random_pet" "p" {}\n')

    tool_json = tmp_path / "tool.dev.json"
    tool_json.write_text(json.dumps({
        "name": "orders",
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}],
        },
    }))

    custom = tmp_path / "custom"
    custom.mkdir()

    rc = cli.main([
        "prepare-custom-tf",
        "--tool-json", str(tool_json),
        "--app-root", str(app_root),
        "--custom-dir", str(custom),
    ])

    assert rc == 0
    assert (custom / "queue.tf").exists()
    assert "hashicorp/random" in (custom / "_providers.g.tf").read_text()


def test_prepare_custom_tf_output_true_when_declared_dir_has_no_tf_files(tmp_path, monkeypatch):
    """Regression: a caller who removes every .tf from a still-declared
    terraform.dir must still get custom_tf=true — the removal itself is a
    change that needs to apply, so the output must reflect the manifest
    declaration, not what happened to get copied."""
    app_root = tmp_path / "app"
    (app_root / "terraform").mkdir(parents=True)

    tool_json = tmp_path / "tool.dev.json"
    tool_json.write_text(json.dumps({
        "name": "orders",
        "terraform": {"dir": "./terraform"},
    }))

    custom = tmp_path / "custom"
    custom.mkdir()

    gh = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))

    rc = cli.main([
        "prepare-custom-tf",
        "--tool-json", str(tool_json),
        "--app-root", str(app_root),
        "--custom-dir", str(custom),
    ])

    assert rc == 0
    assert read_kv(gh.read_text())["custom_tf"] == "true"


def test_prepare_custom_tf_output_false_without_terraform_field(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir(parents=True)

    tool_json = tmp_path / "tool.dev.json"
    tool_json.write_text(json.dumps({"name": "orders"}))

    custom = tmp_path / "custom"
    custom.mkdir()

    gh = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))

    rc = cli.main([
        "prepare-custom-tf",
        "--tool-json", str(tool_json),
        "--app-root", str(app_root),
        "--custom-dir", str(custom),
    ])

    assert rc == 0
    assert read_kv(gh.read_text())["custom_tf"] == "false"


def test_prepare_custom_tf_reports_error_for_bad_provider(tmp_path):
    app_root = tmp_path / "app"
    (app_root / "terraform").mkdir(parents=True)
    (app_root / "terraform" / "q.tf").write_text("# empty\n")

    tool_json = tmp_path / "tool.dev.json"
    tool_json.write_text(json.dumps({
        "name": "orders",
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "aws", "source": "hashicorp/aws", "version": "~> 5"}],
        },
    }))

    custom = tmp_path / "custom"
    custom.mkdir()

    rc = cli.main([
        "prepare-custom-tf",
        "--tool-json", str(tool_json),
        "--app-root", str(app_root),
        "--custom-dir", str(custom),
    ])

    assert rc == 1
