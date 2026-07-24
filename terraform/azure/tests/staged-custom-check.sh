#!/usr/bin/env bash
# Stage the sample caller .tf into the custom module, run the terraform tests,
# then always unstage. Proves a real caller file compiles and plans against the
# platform context; the repo itself always ships an empty custom/ module.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tf_dir="$(dirname "$here")"
staged="$tf_dir/custom/queue.tf"

cleanup() { rm -f "$staged"; }
trap cleanup EXIT

cp "$here/fixtures/custom/queue.tf" "$staged"
terraform -chdir="$tf_dir" test -filter=tests/custom.tftest.hcl
echo "staged custom check: OK"
