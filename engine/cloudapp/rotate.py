"""Lane B: update running Azure images in place, no Terraform.

For each entry in the docker-build image_tags map, roll the image on the
existing container app / function app so a code-only change ships without a
Terraform run. Only reached when the manifest is unchanged and state exists
(the action gate guarantees the resources already exist).
"""

from . import naming


class RotateError(Exception):
    pass


def rotate(tool, prefix, env, image_tags, resource_group, run):
    rotated = 0
    for key, image in image_tags.items():
        if "/" in key:
            app_key, container_key = key.split("/", 1)
            name = naming.container_app_name(tool, prefix, env, app_key)
            cmd = [
                "az", "containerapp", "update",
                "--name", name,
                "--resource-group", resource_group,
                "--container-name", container_key,
                "--image", image,
            ]
        else:
            name = naming.function_app_name(tool, prefix, env, key)
            cmd = [
                "az", "functionapp", "config", "container", "set",
                "--name", name,
                "--resource-group", resource_group,
                "--image", image,
            ]
        result = run(cmd, check=False, capture=True)
        if result.returncode != 0:
            raise RotateError(f"failed to rotate image for {key} ({name}):\n{result.stderr}")
        print(f"rotated {key} -> {image} on {name}")
        rotated += 1
    print(f"rotated {rotated} image(s)")
    return rotated
