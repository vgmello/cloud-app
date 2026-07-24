locals {
  manifest_secrets = distinct(flatten([for ck, c in var.app.containers : try(c.secrets, [])]))
  secret_refs = merge(
    { for s in local.manifest_secrets : s => lower(replace(s, "_", "-")) },
    var.extra_secret_env,
  )
  ingress = try(var.app.ingress, null)
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

resource "azurerm_container_app" "this" {
  depends_on = [azurerm_role_assignment.keyvault, azurerm_role_assignment.acr]

  name                         = var.name
  container_app_environment_id = var.container_apps_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }

  registry {
    server   = var.acr_login_server
    identity = azurerm_user_assigned_identity.this.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secret_refs))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.this.id
      key_vault_secret_id = "${var.keyvault_vault_uri}secrets/${secret.value}"
    }
  }

  dynamic "ingress" {
    for_each = local.ingress != null ? [local.ingress] : []
    content {
      external_enabled           = ingress.value.external
      target_port                = ingress.value.target_port
      exposed_port               = try(ingress.value.exposed_port, null)
      transport                  = ingress.value.transport
      allow_insecure_connections = ingress.value.allow_insecure

      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }

  template {
    min_replicas = var.app.replicas.min
    max_replicas = var.app.replicas.max

    dynamic "container" {
      for_each = var.app.containers
      content {
        name   = container.key
        image  = try(container.value.image, null) != null ? container.value.image : var.image_tags[container.key]
        cpu    = container.value.cpu
        memory = container.value.memory

        dynamic "env" {
          for_each = try(container.value.env, {})
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = toset(try(container.value.secrets, []))
          content {
            name        = env.value
            secret_name = lower(replace(env.value, "_", "-"))
          }
        }

        dynamic "env" {
          for_each = var.extra_secret_env
          content {
            name        = env.key
            secret_name = env.value
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition = alltrue([
        for ck, c in var.app.containers :
        length(setintersection(keys(try(c.env, {})), concat(try(c.secrets, []), keys(var.extra_secret_env)))) == 0
      ])
      error_message = "container env keys must not collide with secret names or reserved env vars (per-database *_DATABASE_URL, STORAGE_CONNECTION)"
    }
  }
}
