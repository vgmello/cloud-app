import pytest

from cloudapp import bootcache


def _tree(tmp_path):
    (tmp_path / "terraform/azure/bootstrap").mkdir(parents=True)
    (tmp_path / "environments").mkdir()
    (tmp_path / "engine/cloudapp").mkdir(parents=True)
    (tmp_path / ".github/actions/deploy-stack").mkdir(parents=True)
    (tmp_path / "terraform/azure/bootstrap/main.tf").write_text("resource {}\n")
    (tmp_path / "environments/dev.yml").write_text("location: eastus2\n")
    (tmp_path / "engine/cloudapp/identity.py").write_text("SUBJECT = 'repo:{}:env:{}'\n")
    (tmp_path / ".github/actions/deploy-stack/action.yml").write_text("name: deploy-stack\n")
    return tmp_path


def test_fingerprint_is_stable_and_prefixed(tmp_path):
    root = _tree(tmp_path)
    first = bootcache.fingerprint(str(root), bootcache.COVERED)
    assert first.startswith("sha256:")
    assert first == bootcache.fingerprint(str(root), bootcache.COVERED)


def test_fingerprint_changes_when_a_covered_file_changes(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / "terraform/azure/bootstrap/main.tf").write_text("resource { changed }\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) != before


def test_fingerprint_changes_when_platform_config_changes(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / "environments/dev.yml").write_text("location: westus\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) != before


def test_fingerprint_ignores_files_outside_covered_paths(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / "README.md").write_text("docs change\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) == before


def test_fingerprint_ignores_terraform_working_dirs(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    noise = root / "terraform/azure/bootstrap/.terraform/providers"
    noise.mkdir(parents=True)
    (noise / "blob.bin").write_text("downloaded provider\n")
    (root / "terraform/azure/bootstrap/terraform.tfstate").write_text("{}\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) == before


# --- Fix 1: build artefacts must never contaminate the fingerprint ---------

@pytest.mark.parametrize(
    "relpath,content",
    [
        ("terraform/azure/bootstrap/tfplan", "binary plan data\n"),
        ("terraform/azure/bootstrap/foo.tfplan", "binary plan data\n"),
        ("terraform/azure/bootstrap/crash.log", "panic: ...\n"),
        ("terraform/azure/bootstrap/.terraform.lock.hcl", 'provider "x" { hashes = ["abc"] }\n'),
        ("terraform/azure/bootstrap/tests/bootstrap.tftest.hcl", "run \"x\" {}\n"),
    ],
)
def test_fingerprint_unchanged_by_build_artefacts(tmp_path, relpath, content):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    assert bootcache.fingerprint(str(root), bootcache.COVERED) == before


def test_fingerprint_unchanged_by_terraform_provider_binary(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    blob = root / "terraform/azure/bootstrap/.terraform/providers/blob.bin"
    blob.parent.mkdir(parents=True)
    blob.write_text("downloaded provider\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) == before


# --- Fix 2: COVERED must include identity.py, the control action, a file entry,
# and the CACHE_EPOCH lever -------------------------------------------------

def test_covered_includes_identity_and_deploy_stack_action():
    assert "engine/cloudapp/identity.py" in bootcache.COVERED
    assert ".github/actions/deploy-stack/action.yml" in bootcache.COVERED


def test_fingerprint_supports_a_file_entry_in_covered(tmp_path):
    root = _tree(tmp_path)
    single_file = root / "standalone.txt"
    single_file.write_text("v1\n")
    before = bootcache.fingerprint(str(root), ("standalone.txt",))
    single_file.write_text("v2\n")
    after = bootcache.fingerprint(str(root), ("standalone.txt",))
    assert before != after


def test_fingerprint_changes_when_identity_module_changes(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / "engine/cloudapp/identity.py").write_text("SUBJECT = 'changed'\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) != before


def test_fingerprint_changes_when_deploy_stack_action_changes(tmp_path):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    (root / ".github/actions/deploy-stack/action.yml").write_text("name: deploy-stack\nchanged: true\n")
    assert bootcache.fingerprint(str(root), bootcache.COVERED) != before


def test_fingerprint_changes_when_cache_epoch_changes(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    before = bootcache.fingerprint(str(root), bootcache.COVERED)
    monkeypatch.setattr(bootcache, "CACHE_EPOCH", bootcache.CACHE_EPOCH + 1)
    assert bootcache.fingerprint(str(root), bootcache.COVERED) != before


FP = "sha256:abc"
STACK = "orders-api"
ENV = "dev"
GOOD = {
    "stack_name": STACK,
    "environment": ENV,
    "resource_group": "rg-orders-api-dev",
    "plan_client_id": "11111111-1111-1111-1111-111111111111",
    "apply_client_id": "22222222-2222-2222-2222-222222222222",
    "fingerprint": FP,
}


def test_use_cache_true_on_full_match():
    assert bootcache.use_cache(FP, GOOD, STACK, ENV) is True


def test_use_cache_false_when_absent():
    assert bootcache.use_cache(FP, None, STACK, ENV) is False


def test_use_cache_false_on_fingerprint_mismatch():
    assert bootcache.use_cache("sha256:different", GOOD, STACK, ENV) is False


def test_use_cache_false_when_any_value_missing():
    for key in ("resource_group", "plan_client_id", "apply_client_id"):
        cache = dict(GOOD)
        cache[key] = ""
        assert bootcache.use_cache(FP, cache, STACK, ENV) is False, key
        del cache[key]
        assert bootcache.use_cache(FP, cache, STACK, ENV) is False, key


def test_use_cache_false_on_malformed_document():
    assert bootcache.use_cache(FP, "not a mapping", STACK, ENV) is False
    assert bootcache.use_cache(FP, {}, STACK, ENV) is False


def test_use_cache_false_when_local_fingerprint_is_empty():
    # an unreadable local fingerprint must never match a cache
    assert bootcache.use_cache("", dict(GOOD, fingerprint=""), STACK, ENV) is False


def test_cache_values_returns_empty_strings_when_absent():
    assert bootcache.cache_values(None) == {
        "resource_group": "",
        "plan_client_id": "",
        "apply_client_id": "",
    }


def test_use_cache_false_on_whitespace_only_value():
    # " " is truthy in Python; a blank identity must not read as a match
    for key in ("resource_group", "plan_client_id", "apply_client_id"):
        cache = dict(GOOD)
        cache[key] = "   "
        assert bootcache.use_cache(FP, cache, STACK, ENV) is False, key


def test_cache_values_normalises_whitespace_and_non_strings():
    assert bootcache.cache_values({"resource_group": "  rg  "})["resource_group"] == "rg"
    assert bootcache.cache_values({"plan_client_id": None})["plan_client_id"] == ""


# --- Fix 3: a cache from a different stack/env must not be usable ----------

def test_use_cache_false_when_stack_name_differs():
    assert bootcache.use_cache(FP, GOOD, "a-different-stack", ENV) is False


def test_use_cache_false_when_environment_differs():
    assert bootcache.use_cache(FP, GOOD, STACK, "prod") is False


def test_use_cache_false_when_stack_name_field_missing():
    cache = dict(GOOD)
    del cache["stack_name"]
    assert bootcache.use_cache(FP, cache, STACK, ENV) is False


def test_use_cache_false_when_environment_field_missing():
    cache = dict(GOOD)
    del cache["environment"]
    assert bootcache.use_cache(FP, cache, STACK, ENV) is False


# --- Fix 4: values must match a conservative charset before reaching a shell -

def test_use_cache_false_on_malformed_client_id():
    cache = dict(GOOD, plan_client_id="not-a-guid; rm -rf /")
    assert bootcache.use_cache(FP, cache, STACK, ENV) is False


def test_use_cache_false_on_resource_group_with_newline():
    cache = dict(GOOD, resource_group="rg-orders-api-dev\nmalicious")
    assert bootcache.use_cache(FP, cache, STACK, ENV) is False
