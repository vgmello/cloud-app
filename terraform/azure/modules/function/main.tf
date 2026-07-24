locals {
  st_name = substr("stfn${replace(var.name, "-", "")}", 0, 24)

  secret_refs = merge(
    { for s in try(var.function.secrets, []) : s => lower(replace(s, "_", "-")) },
    var.extra_secret_env,
  )
  kv_ref_settings = {
    for env_name, secret_name in local.secret_refs :
    env_name => "@Microsoft.KeyVault(SecretUri=${var.keyvault_vault_uri}secrets/${secret_name}/)"
  }

  runtime       = try(var.function.runtime, null)
  runtime_stack = local.runtime != null ? split(":", local.runtime)[0] : null
  runtime_ver   = local.runtime != null ? split(":", local.runtime)[1] : null

  # Code functions (runtime set) never render a docker application_stack, even when
  # `image` is present — for code mode, `image` names a prebuilt BUILDER image the
  # platform runs to produce /out, not a runtime image for the function app itself.
  image = local.runtime != null ? null : (try(var.function.image, null) != null ? var.function.image : var.image_tag)

  image_first_part   = local.image != null ? split("/", local.image)[0] : ""
  image_has_registry = local.image != null ? (length(split("/", local.image)) > 1 ? (strcontains(local.image_first_part, ".") || strcontains(local.image_first_part, ":") || local.image_first_part == "localhost") : false) : false
  image_registry     = local.image_has_registry ? local.image_first_part : "docker.io"
  image_repo_tag     = local.image_has_registry ? join("/", slice(split("/", local.image), 1, length(split("/", local.image)))) : local.image
  image_repo         = local.image != null ? split(":", local.image_repo_tag)[0] : null
  image_tag_part     = local.image != null ? (length(split(":", local.image_repo_tag)) > 1 ? split(":", local.image_repo_tag)[1] : "latest") : null

  native_dotnet_version              = local.runtime_stack == "dotnet-isolated" ? local.runtime_ver : null
  native_use_dotnet_isolated_runtime = local.runtime_stack == "dotnet-isolated" ? true : null
  native_node_version                = local.runtime_stack == "node" ? local.runtime_ver : null
  native_python_version              = local.runtime_stack == "python" ? local.runtime_ver : null
  native_java_version                = local.runtime_stack == "java" ? local.runtime_ver : null
  native_powershell_core_version     = local.runtime_stack == "powershell" ? local.runtime_ver : null
}

resource "azurerm_user_assigned_identity" "this" {
  name                = "id-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
}

resource "azurerm_role_assignment" "keyvault" {
  scope                = var.keyvault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}

resource "azurerm_role_assignment" "acr" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}

resource "azurerm_storage_account" "functions" {
  name                     = local.st_name
  location                 = var.location
  resource_group_name      = var.resource_group_name
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_service_plan" "this" {
  name                = "asp-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  sku_name            = "EP1"
}

resource "azurerm_linux_function_app" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  service_plan_id     = azurerm_service_plan.this.id

  storage_account_name       = azurerm_storage_account.functions.name
  storage_account_access_key = azurerm_storage_account.functions.primary_access_key

  virtual_network_subnet_id       = var.functions_subnet_id
  key_vault_reference_identity_id = azurerm_user_assigned_identity.this.id
  https_only                      = true

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }

  site_config {
    container_registry_use_managed_identity       = local.image != null
    container_registry_managed_identity_client_id = local.image != null ? azurerm_user_assigned_identity.this.client_id : null

    dynamic "application_stack" {
      for_each = local.image != null ? [1] : []
      content {
        docker {
          registry_url = "https://${local.image_registry}"
          image_name   = local.image_repo
          image_tag    = local.image_tag_part
        }
      }
    }

    dynamic "application_stack" {
      for_each = local.runtime != null ? [1] : []
      content {
        dotnet_version              = local.native_dotnet_version
        use_dotnet_isolated_runtime = local.native_use_dotnet_isolated_runtime
        node_version                = local.native_node_version
        python_version              = local.native_python_version
        java_version                = local.native_java_version
        powershell_core_version     = local.native_powershell_core_version
      }
    }
  }

  app_settings = merge(try(var.function.env, {}), local.kv_ref_settings)

  lifecycle {
    precondition {
      condition     = local.image != null || local.runtime != null
      error_message = "function has no image and no runtime: set a container image (or docker build) for container mode, or a runtime for code mode"
    }
  }
}
