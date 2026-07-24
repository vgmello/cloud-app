"""Deploy code-mode functions: terraform output -> package -> config-zip.

Runs after `terraform apply`. Re-inits Terraform so function-app names are read
from state authoritatively even on manifest-unchanged runs where the apply was
skipped. Must run on a runner with network access to the (private) SCM endpoint.
"""

import json

from . import funcpackage

INPUT_FALSE = "-input=false"


def deploy(tool, tf_dir, backend_lines, workdir, run):
    functions = funcpackage.code_functions(tool)
    if not functions:
        return []

    tf = ["terraform", f"-chdir={tf_dir}"]
    run(tf + ["init", INPUT_FALSE] + [f"-backend-config={line}" for line in backend_lines])
    result = run(tf + ["output", "-json", "names"], capture=True)
    names = json.loads(result.stdout)
    rg = names["resource_group"]
    func_names = names["functions"]

    deployed = []
    for key, fn in functions.items():
        app_name = func_names[key]
        zip_path = funcpackage.package(key, fn, workdir, run)
        run([
            "az", "functionapp", "deployment", "source", "config-zip",
            "-g", rg, "-n", app_name, "--src", zip_path,
        ])
        deployed.append(app_name)
    return deployed
