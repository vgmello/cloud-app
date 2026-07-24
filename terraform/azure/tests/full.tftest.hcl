mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config = jsondecode(file("tests/fixtures/tfvars.full.prod.json")).config
  image_tags = {
    "api/main"    = "acrplatformdev.azurecr.io/orders-api-api:abc123"
    "worker/main" = "acrplatformdev.azurecr.io/orders-api-worker:abc123"
    "processor"   = "acrplatformdev.azurecr.io/orders-api-processor:abc123"
  }
}

run "naming" {
  command = plan

  assert {
    condition     = output.names.apps["api"] == "ca-orders-api-api-prod" && output.names.apps["worker"] == "ca-orders-api-worker-prod"
    error_message = "multi-app entries must suffix the entry key"
  }
  assert {
    condition     = output.names.functions["processor"] == "func-orders-api-prod"
    error_message = "single function must dedupe to the manifest name"
  }
  assert {
    condition     = output.names.databases["main"] == "psql-orders-api-prod"
    error_message = "postgres database must use the psql- prefix"
  }
  assert {
    condition     = output.names.storage == "stordersapiprod"
    error_message = "storage account name must be alphanumeric"
  }
}

run "postgres_and_storage" {
  command = plan

  assert {
    condition     = module.database["main"].server_name == "psql-orders-api-prod"
    error_message = "postgres module must receive the psql- name"
  }
  assert {
    condition     = module.database["main"].secret_names["main"] == "database-url"
    error_message = "legacy database must expose the reserved database-url secret wiring"
  }
  assert {
    condition     = module.storage[0].secret_env.STORAGE_CONNECTION == "storage-connection"
    error_message = "storage must expose the reserved storage-connection secret wiring"
  }
}
