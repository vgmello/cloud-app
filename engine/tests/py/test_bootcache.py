from cloudapp import bootcache


def _tree(tmp_path):
    (tmp_path / "terraform/azure/bootstrap").mkdir(parents=True)
    (tmp_path / "environments").mkdir()
    (tmp_path / "terraform/azure/bootstrap/main.tf").write_text("resource {}\n")
    (tmp_path / "environments/dev.yml").write_text("location: eastus2\n")
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


FP = "sha256:abc"
GOOD = {
    "resource_group": "rg-orders-api-dev",
    "plan_client_id": "11111111-1111-1111-1111-111111111111",
    "apply_client_id": "22222222-2222-2222-2222-222222222222",
    "fingerprint": FP,
}


def test_use_cache_true_on_full_match():
    assert bootcache.use_cache(FP, GOOD) is True


def test_use_cache_false_when_absent():
    assert bootcache.use_cache(FP, None) is False


def test_use_cache_false_on_fingerprint_mismatch():
    assert bootcache.use_cache("sha256:different", GOOD) is False


def test_use_cache_false_when_any_value_missing():
    for key in ("resource_group", "plan_client_id", "apply_client_id"):
        cache = dict(GOOD)
        cache[key] = ""
        assert bootcache.use_cache(FP, cache) is False, key
        del cache[key]
        assert bootcache.use_cache(FP, cache) is False, key


def test_use_cache_false_on_malformed_document():
    assert bootcache.use_cache(FP, "not a mapping") is False
    assert bootcache.use_cache(FP, {}) is False


def test_use_cache_false_when_local_fingerprint_is_empty():
    # an unreadable local fingerprint must never match a cache
    assert bootcache.use_cache("", dict(GOOD, fingerprint="")) is False


def test_cache_values_returns_empty_strings_when_absent():
    assert bootcache.cache_values(None) == {
        "resource_group": "",
        "plan_client_id": "",
        "apply_client_id": "",
    }
