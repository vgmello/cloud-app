"""Produce a deployable zip for each code-mode function.

Zip mode (`package:`): archive the directory as-is.
Builder mode (`docker:`/`image:`): run a throwaway builder container with a
host dir mounted at /out; the builder writes its build output there; zip /out.
"""

import shutil
import tempfile
from pathlib import Path

from .manifest import function_mode

OUT_MOUNT = "/out"


def code_functions(tool):
    return {
        k: fn
        for k, fn in (tool.get("functions") or {}).items()
        if function_mode(fn) == "code"
    }


def _zip_dir(src_dir, dest_base):
    # make_archive appends ".zip"; return the actual path.
    return shutil.make_archive(str(dest_base), "zip", root_dir=str(src_dir))


def package(key, fn, workdir, run):
    """Return the path to a zip of the function's deployable content."""
    workdir = Path(workdir)
    dest_base = workdir / key

    if "package" in fn:
        return _zip_dir(fn["package"], dest_base)

    out_dir = Path(tempfile.mkdtemp(prefix=f"out-{key}-", dir=str(workdir)))

    if "docker" in fn:
        docker = fn["docker"]
        image = f"cloudapp-builder-{key}"
        run(["docker", "build", "-f", docker.get("file", "./Dockerfile"),
             "-t", image, docker.get("context", ".")])
    else:
        image = fn["image"]

    run(["docker", "run", "--rm", "-v", f"{out_dir}:{OUT_MOUNT}", image])
    return _zip_dir(out_dir, dest_base)
