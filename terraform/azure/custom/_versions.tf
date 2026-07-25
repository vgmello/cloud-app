# Platform-owned. Deliberately declares only required_version, not
# required_providers: the latter is generated into _providers.g.tf from the
# manifest's terraform.providers, and a second required_providers block in
# this module would conflict with it (see the commit that deleted the old
# _versions.tf for the duplicate-block failure this caused).
terraform {
  required_version = ">= 1.9.0"
}
