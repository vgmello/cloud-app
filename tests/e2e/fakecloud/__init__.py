"""A substitute Azure for the workflow e2e suite.

`blob` talks to a real Azurite. `graph` holds the JSON resource graph and call
logs that stand in for the control plane, which has no emulator. `naming`
mirrors terraform/azure/locals.tf. The executables under `bin/` go on PATH
inside the act container ahead of the real `az`, `terraform`, and `docker`.
"""
