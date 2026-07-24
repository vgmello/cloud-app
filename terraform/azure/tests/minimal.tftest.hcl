mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.minimal.dev.json")).config
  image_tags = { "main/main" = "acrplatformdev.azurecr.io/orders-api:abc123" }
}

run "naming" {
  command = plan

  assert {
    condition     = output.names.resource_group == "rg-orders-api-dev"
    error_message = "wrong resource group name"
  }
  assert {
    condition     = output.names.keyvault == "kv-orders-api-dev"
    error_message = "wrong key vault name"
  }
  assert {
    condition     = output.names.apps["main"] == "ca-orders-api-dev"
    error_message = "single app must dedupe to the manifest name"
  }
  assert {
    condition     = length(output.names.databases) == 0 && output.names.storage == null
    error_message = "no database/storage section means no names"
  }
}

run "keyvault" {
  command = plan

  assert {
    condition     = module.keyvault.name == "kv-orders-api-dev"
    error_message = "key vault module must use the computed kv name"
  }
}

run "container_app" {
  command = plan

  assert {
    condition     = module.container_app["main"].app_name == "ca-orders-api-dev"
    error_message = "container app must use the deduped name"
  }
  assert {
    condition     = module.container_app["main"].container_images["main"] == "acrplatformdev.azurecr.io/orders-api:abc123"
    error_message = "docker-built container must resolve image from image_tags"
  }
}
