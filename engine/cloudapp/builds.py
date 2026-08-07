"""Docker build enumeration: which images to build, and the image_tags contract.

Keys: "<app_key>/<container_key>" for apps, "<function_key>" for functions.
Entries with image: are skipped; entries without docker: default to
./Dockerfile + "."; identical (file, context) pairs share one build.
Code-mode functions (see manifest.function_mode) are skipped entirely: they
run from source, so there is no image to build or push to ACR.

Image repositories are `<stack>/[<component>/]<key>`. The stack name stays the
first path segment because the apply identity's ACR push grant is an ABAC
condition on exactly that prefix (see terraform/azure/bootstrap/main.tf); the
component segment keeps two components of one stack from pushing different
images to the same repository.
"""

from .manifest import function_mode

DEFAULT_FILE = "./Dockerfile"
DEFAULT_CONTEXT = "."


def image_repo_prefix(tool, name):
    component = (tool or {}).get("component")
    return f"{name}/{component}" if component else name


def enumerate_builds(tool, name, registry, sha):
    entries = []
    for app_key, app in (tool.get("apps") or {}).items():
        for container_key, container in app["containers"].items():
            if "image" not in container:
                docker = container.get("docker", {})
                entries.append((f"{app_key}/{container_key}", docker))
    for function_key, function in (tool.get("functions") or {}).items():
        if function_mode(function) == "code":
            continue
        if "image" not in function:
            entries.append((function_key, function.get("docker", {})))

    grouped = {}
    for key, docker in entries:
        source = (docker.get("file", DEFAULT_FILE), docker.get("context", DEFAULT_CONTEXT))
        grouped.setdefault(source, []).append(key)

    repo = image_repo_prefix(tool, name)
    return {
        "builds": [
            {"file": file, "context": context, "keys": sorted(keys)}
            for (file, context), keys in sorted(grouped.items())
        ],
        "tags": {
            key: f"{registry}/{repo}/{key.replace('/', '-')}:{sha}"
            for key, _ in entries
        },
    }
