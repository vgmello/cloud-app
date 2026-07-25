# Platform-owned. The curated context caller-supplied .tf may reference.
# Caller files are copied into this directory at deploy time; they must not
# start with "_" (reserved for these platform files).

variable "resource_group_name" {
  description = "The tool's resource group — the only RG the apply identity can write"
  type        = string
}

variable "location" {
  type = string
}

variable "environment" {
  type = string
}

variable "tool_name" {
  description = "Manifest name with the platform naming prefix applied"
  type        = string
}

variable "vnet_id" {
  type = string
}

variable "subnets" {
  description = "Landing-zone subnet ids (private_endpoints, functions)"
  type        = any
}

variable "key_vault_id" {
  type = string
}

variable "key_vault_uri" {
  type = string
}

variable "app_identity_principal_ids" {
  description = "App key -> managed identity principal id, for role assignments"
  type        = map(string)
  default     = {}
}

variable "function_identity_principal_ids" {
  description = "Function key -> managed identity principal id, for role assignments"
  type        = map(string)
  default     = {}
}

output "context" {
  description = "Echoes the received context so the platform can assert the wiring"
  value = {
    resource_group_name             = var.resource_group_name
    location                        = var.location
    environment                     = var.environment
    tool_name                       = var.tool_name
    vnet_id                         = var.vnet_id
    subnets                         = var.subnets
    key_vault_id                    = var.key_vault_id
    key_vault_uri                   = var.key_vault_uri
    app_identity_principal_ids      = var.app_identity_principal_ids
    function_identity_principal_ids = var.function_identity_principal_ids
  }
}
