# Shared stacks: one stack name, several manifests ("components"), each with its
# own Terraform state. The pair below is the case that used to be impossible —
# one repo creates the database, another creates the app, and they deploy at
# different times without either apply seeing the other's resources.

mock_provider "azurerm" {
  # Unlike a mocked resource (whose computed attributes stay unknown at plan),
  # a mocked data source yields concrete values, so the generated placeholder id
  # reaches azurerm_role_assignment.scope and fails its ID validation. Give the
  # looked-up vault a well-formed id.
  mock_data "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-shared-dev/providers/Microsoft.KeyVault/vaults/kv-shared-dev"
      vault_uri = "https://kv-shared-dev.vault.azure.net/"
    }
  }
}
mock_provider "random" {}

variables {
  config = jsondecode(file("tests/fixtures/tfvars.sharedroot.dev.json")).config
}

run "root_owns_the_shared_services" {
  command = plan

  assert {
    condition     = length(module.keyvault) == 1
    error_message = "the root component (no component:) must create the stack Key Vault"
  }
  assert {
    condition     = length(data.azurerm_key_vault.shared) == 0
    error_message = "the root component creates the vault and must not also read it"
  }
  assert {
    condition     = length(module.database) == 1
    error_message = "the root component must create the database it declares"
  }
  assert {
    condition     = length(module.storage) == 1
    error_message = "the root component must create the storage account it declares"
  }
}

run "root_needs_no_compute" {
  command = plan

  assert {
    condition     = length(module.container_app) == 0 && length(module.function) == 0
    error_message = "an infra-only component must be deployable with no compute at all"
  }
  assert {
    condition     = output.names.resource_group == "rg-shop-dev"
    error_message = "the resource group is stack-scoped"
  }
  assert {
    condition     = output.names.databases["primary"] == "psql-shop-dev"
    error_message = "the root component's names carry no component suffix"
  }
}

run "component_reads_the_shared_vault_and_creates_none" {
  command = plan

  variables {
    config = jsondecode(file("tests/fixtures/tfvars.sharedapi.dev.json")).config
    image_tags = {
      "main/main" = "acrplatformdev.azurecr.io/shop/api/main-main:abc123"
    }
  }

  assert {
    condition     = length(module.keyvault) == 0
    error_message = "a named component must never create the stack's Key Vault"
  }
  assert {
    condition     = length(data.azurerm_key_vault.shared) == 1
    error_message = "a named component must read the Key Vault the root created"
  }
  assert {
    condition     = local.kv_name == "kv-shop-dev"
    error_message = "the Key Vault name is stack-scoped, so both components resolve the same vault"
  }
  assert {
    condition     = local.rg_name == "rg-shop-dev"
    error_message = "the resource group is stack-scoped, so both components deploy into it"
  }
}

run "component_does_not_manage_external_entries" {
  command = plan

  variables {
    config = jsondecode(file("tests/fixtures/tfvars.sharedapi.dev.json")).config
    image_tags = {
      "main/main" = "acrplatformdev.azurecr.io/shop/api/main-main:abc123"
    }
  }

  # This is the whole point: the database and storage are declared (so the env
  # wiring below resolves) but not created, so this component's state never
  # claims them and its apply can never plan to destroy them.
  assert {
    condition     = length(module.database) == 0
    error_message = "an external database must not be created by the component that only references it"
  }
  assert {
    condition     = length(module.storage) == 0
    error_message = "external storage must not be created by the component that only references it"
  }
  assert {
    condition     = output.names.databases == {}
    error_message = "names.databases must list only what this component owns"
  }
  assert {
    condition     = output.names.storage == null
    error_message = "names.storage must be null when another component owns it"
  }
}

run "component_app_is_wired_to_the_external_database" {
  command = plan

  variables {
    config = jsondecode(file("tests/fixtures/tfvars.sharedapi.dev.json")).config
    image_tags = {
      "main/main" = "acrplatformdev.azurecr.io/shop/api/main-main:abc123"
    }
  }

  # The env var maps to the Key Vault secret name the *owning* component writes,
  # which is derived from the declaration, not from the resource.
  assert {
    condition     = module.container_app["main"].extra_secret_env["PRIMARY_ORDERS_DATABASE_URL"] == "database-url-primary-orders"
    error_message = "an app must be wired to a database another component owns"
  }
  assert {
    condition     = contains(keys(module.container_app["main"].extra_secret_env), "STORAGE_CONNECTION")
    error_message = "external storage must still wire STORAGE_CONNECTION"
  }
}

run "component_names_never_collide_with_the_roots" {
  command = plan

  variables {
    config = jsondecode(file("tests/fixtures/tfvars.sharedapi.dev.json")).config
    image_tags = {
      "main/main" = "acrplatformdev.azurecr.io/shop/api/main-main:abc123"
    }
  }

  # Both manifests declare a single entry, so without the component suffix both
  # would dedupe to the bare stack name and fight over one Azure resource.
  assert {
    condition     = output.names.apps["main"] == "ca-shop-api-dev"
    error_message = "a component's compute names must carry the component suffix"
  }
  assert {
    condition     = output.names.component == "api"
    error_message = "names must report which component produced them"
  }
}

# The singular `database:` form injects a blanket DATABASE_URL wired to the Key
# Vault secret `database-url`. A component referencing it must use the same
# form — nothing can validate that across manifests, so pin the behaviour the
# docs promise.
run "external_legacy_database_wires_the_blanket_url" {
  command = plan

  variables {
    config = jsondecode(file("tests/fixtures/tfvars.sharedlegacy.dev.json")).config
    image_tags = {
      "worker/main" = "acrplatformdev.azurecr.io/orders-api/worker/worker-main:abc123"
    }
  }

  assert {
    condition     = length(module.database) == 0
    error_message = "an external legacy database must not be created by the referencing component"
  }
  assert {
    condition     = module.container_app["worker"].extra_secret_env["DATABASE_URL"] == "database-url"
    error_message = "the legacy blanket DATABASE_URL must resolve to the owner's secret name"
  }
}
