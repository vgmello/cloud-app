# e2e caller fixture

Stands in for an app team's repository. `conftest.py` copies these files into
the scratch workspace root, on top of the platform repo, so the composite
action sees exactly what it sees in production: a manifest, a Dockerfile, and
optionally a caller Terraform directory at the repo root.

Manifest variants are selected per scenario; `cloud-app.yml` is the baseline.
