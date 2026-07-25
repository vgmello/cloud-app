variable "subscription_id" {
  type = string
}

variable "location" {
  type = string
}

variable "name" {
  type = string
}

variable "environment" {
  type = string
}

variable "plan_subjects" {
  description = "OIDC subjects the plan identity's federated credentials trust"
  type        = list(string)
}

variable "apply_subjects" {
  description = "OIDC subjects the apply identity's federated credentials trust"
  type        = list(string)
}

variable "acr_id" {
  description = "Resource ID of the shared ABAC-enabled ACR. Empty disables the repo-scoped push grant."
  type        = string
  default     = ""
}

variable "state_account_id" {
  description = "Resource ID of the Azure Blob tfstate storage account. Empty disables the state-container grants (e.g. s3 backend)."
  type        = string
  default     = ""
}

variable "stack_state_container" {
  description = "Per-(stack, environment) blob container holding this stack's main tfstate. Created here; the plan/apply state grants scope to it. Empty disables the container and its grants (e.g. s3 backend)."
  type        = string
  default     = ""
}
