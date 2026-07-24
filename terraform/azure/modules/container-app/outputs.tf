output "app_name" {
  value = azurerm_container_app.this.name
}

output "fqdn" {
  value = try(azurerm_container_app.this.ingress[0].fqdn, null)
}

output "identity_principal_id" {
  value = azurerm_user_assigned_identity.this.principal_id
}

output "container_images" {
  description = "Resolved image per container, for plan assertions"
  value       = { for c in azurerm_container_app.this.template[0].container : c.name => c.image }
}

output "extra_secret_env" {
  description = "Reserved env var -> Key Vault secret name wired into every container"
  value       = var.extra_secret_env
}
