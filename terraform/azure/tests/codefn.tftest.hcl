mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.codefn.dev.json")).config
  image_tags = {}
}

run "code_function_uses_runtime_stack" {
  command = plan

  assert {
    condition     = module.function["worker"].runtime_stack == "python:3.11"
    error_message = "python code function must surface its runtime stack"
  }
  assert {
    condition     = module.function["worker"].docker_image == null
    error_message = "code function must not render a docker application stack"
  }
  assert {
    condition     = module.function["builder"].runtime_stack == "dotnet-isolated:8.0"
    error_message = "dotnet builder function must surface its runtime stack"
  }
  assert {
    condition     = module.function["builder"].docker_image == null
    error_message = "builder-mode function must not render a docker application stack"
  }
  assert {
    condition     = module.function["legacy"].runtime_stack == null
    error_message = "container function must have no runtime stack"
  }
  assert {
    condition     = module.function["legacy"].docker_image != null
    error_message = "container function must still render a docker application stack"
  }
  assert {
    condition     = module.function["worker"].plan_sku == "EP1"
    error_message = "code function must still run on EP1"
  }
}
