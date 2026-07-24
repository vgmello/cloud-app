mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.partial.dev.json")).config
  image_tags = { "main/main" = "acrplatformdev.azurecr.io/partial:abc123" }
}

run "naming" {
  command = plan

  assert {
    condition     = output.names.apps["main"] == "ca-partial-dev"
    error_message = "app shorthand entry must dedupe to the manifest name"
  }
  assert {
    condition     = output.names.functions["relay"] == "func-partial-dev"
    error_message = "single function must dedupe to the manifest name"
  }
  assert {
    condition     = output.names.static_sites["docs"] == "swa-partial-dev"
    error_message = "single static site must dedupe to the manifest name"
  }
  assert {
    condition     = output.names.databases["main"] == "psql-partial-dev"
    error_message = "legacy database defaulting to postgres must use psql- prefix"
  }
}

run "compute" {
  command = plan

  assert {
    condition     = module.function["relay"].function_name == "func-partial-dev"
    error_message = "function must use the deduped name"
  }
  assert {
    condition     = module.function["relay"].plan_sku == "EP1"
    error_message = "functions must run on an EP1 plan for VNet integration"
  }
  assert {
    condition     = module.static_site["docs"].site_name == "swa-partial-dev"
    error_message = "static site must use the deduped name"
  }
}

run "function_docker_parsing" {
  command = plan

  assert {
    condition     = module.function["relay"].docker_image.registry_url == "https://myacr.azurecr.io"
    error_message = "registry with a dot must be parsed as registry_url"
  }
  assert {
    condition     = module.function["relay"].docker_image.image_name == "relay"
    error_message = "image repo must strip registry"
  }
  assert {
    condition     = module.function["relay"].docker_image.image_tag == "2.0"
    error_message = "image tag must be parsed"
  }
}
