mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.multi.dev.json")).config
  image_tags = { "gateway/web" = "acrplatformdev.azurecr.io/billing-web:abc123" }
}

run "naming" {
  command = plan

  assert {
    condition     = output.names.apps["gateway"] == "ca-billing-dev"
    error_message = "single app must dedupe to the manifest name"
  }
  assert {
    condition     = output.names.databases["main"] == "sql-billing-dev"
    error_message = "sqlserver database must use the sql- prefix"
  }
}

run "sqlserver" {
  command = plan

  assert {
    condition     = module.database["main"].server_name == "sql-billing-dev"
    error_message = "sqlserver module must receive the sql- name"
  }
}

run "containers" {
  command = plan

  assert {
    condition     = module.container_app["gateway"].container_images["proxy"] == "nginx:1.27"
    error_message = "prebuilt image must pass through untouched"
  }
  assert {
    condition     = module.container_app["gateway"].container_images["web"] == "acrplatformdev.azurecr.io/billing-web:abc123"
    error_message = "docker container must resolve from image_tags"
  }
}
