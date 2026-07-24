from cloudapp import naming

# Expected values are hand-derived from terraform/azure/locals.tf and must stay
# in lockstep with it (ca_names / func_names / app_bases rules).

SINGLE = {"name": "orders-api", "apps": {"main": {}}, "functions": {}}
MULTI = {
    "name": "orders-api",
    "apps": {"api": {}, "worker": {}},
    "functions": {"processor": {}},
}


def test_container_app_name_single_app_uses_base():
    assert naming.container_app_name(SINGLE, "", "dev", "main") == "ca-orders-api-dev"


def test_container_app_name_multi_app_suffixes_key():
    assert naming.container_app_name(MULTI, "", "dev", "api") == "ca-orders-api-api-dev"
    assert naming.container_app_name(MULTI, "", "dev", "worker") == "ca-orders-api-worker-dev"


def test_container_app_name_applies_prefix():
    assert naming.container_app_name(SINGLE, "acme-", "prod", "main") == "ca-acme-orders-api-prod"


def test_container_app_name_explicit_name_override():
    tool = {"name": "orders-api", "apps": {"api": {"name": "custom-app"}, "b": {}}, "functions": {}}
    assert naming.container_app_name(tool, "", "dev", "api") == "ca-custom-app-dev"


def test_function_app_name_single_function_uses_base():
    tool = {"name": "orders-api", "apps": {}, "functions": {"processor": {}}}
    assert naming.function_app_name(tool, "", "dev", "processor") == "func-orders-api-dev"


def test_function_app_name_multi_function_suffixes_key():
    tool = {"name": "orders-api", "apps": {}, "functions": {"a": {}, "b": {}}}
    assert naming.function_app_name(tool, "", "dev", "a") == "func-orders-api-a-dev"
