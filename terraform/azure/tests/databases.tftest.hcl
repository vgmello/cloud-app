mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config = jsondecode(file("tests/fixtures/tfvars.databases.dev.json")).config
  image_tags = {
    "api/main"    = "acrplatformdev.azurecr.io/shop-api:abc123"
    "worker/main" = "acrplatformdev.azurecr.io/shop-worker:abc123"
  }
}

run "server_naming" {
  command = plan

  assert {
    condition     = output.names.databases["primary"] == "psql-shop-primary-dev"
    error_message = "multiple servers must append the server key"
  }
  assert {
    condition     = output.names.databases["reporting"] == "sql-shop-reporting-dev"
    error_message = "sqlserver server must use sql- prefix and append key"
  }
}

run "logical_databases" {
  command = plan

  assert {
    condition     = length(module.database["primary"].secret_names) == 2
    error_message = "primary must expose two logical-db secrets (orders + billing)"
  }
  assert {
    condition     = length(module.database["reporting"].secret_names) == 1
    error_message = "reporting must expose one logical-db secret (main)"
  }
}

run "secret_names" {
  command = plan

  assert {
    condition     = module.database["primary"].secret_names["orders"] == "database-url-primary-orders"
    error_message = "non-legacy secret name must be database-url-<server>-<db>"
  }
}

run "app_opt_in_env" {
  command = plan

  # api opts into primary/orders + reporting/main -> two db env vars, no billing
  assert {
    condition = length(setintersection(
      keys(module.container_app["api"].extra_secret_env),
      ["PRIMARY_ORDERS_DATABASE_URL", "REPORTING_MAIN_DATABASE_URL"]
    )) == 2
    error_message = "api must receive exactly its two opted-in database env vars"
  }
  assert {
    condition     = !contains(keys(module.container_app["api"].extra_secret_env), "PRIMARY_BILLING_DATABASE_URL")
    error_message = "api did not opt into primary/billing and must not receive it"
  }
}
