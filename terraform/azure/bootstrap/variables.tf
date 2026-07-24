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
