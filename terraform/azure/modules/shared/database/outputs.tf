output "server_name" {
  value = var.name
}

output "secret_names" {
  description = "Logical db name -> Key Vault secret name"
  value       = var.dbs
}
