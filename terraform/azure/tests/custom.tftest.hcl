mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.partial.dev.json")).config
  image_tags = { "main/main" = "acrplatformdev.azurecr.io/partial:abc123" }
}

run "custom_module_receives_context" {
  command = plan

  assert {
    condition     = module.custom.context.resource_group_name == "rg-partial-dev"
    error_message = "custom module must receive the tool's resource group"
  }
  assert {
    condition     = module.custom.context.environment == "dev"
    error_message = "custom module must receive the environment"
  }
  assert {
    condition     = module.custom.context.tool_name == "partial"
    error_message = "custom module must receive the tool base name"
  }
  assert {
    condition     = module.custom.context.subnets.functions != ""
    error_message = "custom module must receive the functions subnet id"
  }
  assert {
    condition     = contains(keys(module.custom.context.app_identity_principal_ids), "main")
    error_message = "custom module must receive per-app identity principal ids"
  }
  assert {
    condition     = contains(keys(module.custom.context.function_identity_principal_ids), "relay")
    error_message = "custom module must receive per-function identity principal ids"
  }
}
