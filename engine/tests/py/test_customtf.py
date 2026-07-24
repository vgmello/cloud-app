import pytest

from cloudapp import customtf


def _tool(dir_, providers=None):
    return {"terraform": {"dir": dir_, "providers": providers or []}}


def test_collect_returns_empty_without_terraform(tmp_path):
    assert customtf.collect({"name": "x"}, str(tmp_path)) == []


def test_collect_accepts_tf_files(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "queue.tf").write_text('resource "random_pet" "p" {}\n')
    (src / "notes.md").write_text("ignored\n")
    files = customtf.collect(_tool("./terraform"), str(tmp_path))
    assert [f.name for f in files] == ["queue.tf"]


def test_collect_rejects_missing_dir(tmp_path):
    with pytest.raises(customtf.CustomTfError, match="not found"):
        customtf.collect(_tool("./nope"), str(tmp_path))


def test_collect_rejects_parent_escape(tmp_path):
    with pytest.raises(customtf.CustomTfError):
        customtf.collect(_tool("../outside"), str(tmp_path))


def test_collect_rejects_reserved_underscore_name(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "_context.tf").write_text("variable \"x\" {}\n")
    with pytest.raises(customtf.CustomTfError, match="reserved"):
        customtf.collect(_tool("./terraform"), str(tmp_path))


def test_collect_rejects_provider_block(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "bad.tf").write_text('provider "azurerm" {\n  features {}\n}\n')
    with pytest.raises(customtf.CustomTfError, match="provider"):
        customtf.collect(_tool("./terraform"), str(tmp_path))


def test_collect_rejects_terraform_block(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "bad.tf").write_text('terraform {\n  backend "local" {}\n}\n')
    with pytest.raises(customtf.CustomTfError):
        customtf.collect(_tool("./terraform"), str(tmp_path))


def test_collect_allows_local_exec(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "ok.tf").write_text(
        'resource "null_resource" "r" {\n  provisioner "local-exec" {\n    command = "echo hi"\n  }\n}\n'
    )
    assert [f.name for f in customtf.collect(_tool("./terraform"), str(tmp_path))] == ["ok.tf"]


def test_render_providers_empty_is_none():
    assert customtf.render_providers([]) is None


def test_render_providers_emits_required_providers():
    body = customtf.render_providers(
        [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}]
    )
    assert "required_providers" in body
    assert 'random = {' in body
    assert 'source  = "hashicorp/random"' in body
    assert 'version = "~> 3"' in body


def test_render_providers_rejects_non_allowlisted():
    with pytest.raises(customtf.CustomTfError, match="not allowed"):
        customtf.render_providers([{"name": "aws", "source": "hashicorp/aws", "version": "~> 5"}])


def test_render_providers_rejects_source_mismatch():
    with pytest.raises(customtf.CustomTfError, match="source"):
        customtf.render_providers(
            [{"name": "random", "source": "evil/random", "version": "~> 3"}]
        )


def test_prepare_copies_files_and_writes_providers(tmp_path):
    src = tmp_path / "terraform"
    src.mkdir()
    (src / "queue.tf").write_text('resource "random_pet" "p" {}\n')
    custom = tmp_path / "custom"
    custom.mkdir()

    copied = customtf.prepare(
        _tool("./terraform", [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}]),
        str(tmp_path),
        str(custom),
    )

    assert copied == ["queue.tf"]
    assert (custom / "queue.tf").read_text() == 'resource "random_pet" "p" {}\n'
    assert "hashicorp/random" in (custom / "_providers.g.tf").read_text()


def test_prepare_noop_without_terraform(tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    assert customtf.prepare({"name": "x"}, str(tmp_path), str(custom)) == []
    assert not (custom / "_providers.g.tf").exists()
