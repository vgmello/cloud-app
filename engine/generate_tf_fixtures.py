#!/usr/bin/env python3
"""Regenerate terraform test fixtures through the real manifest pipeline."""

import json
import sys
from pathlib import Path

ENGINE = Path(__file__).parent  # engine/ — holds cloudapp + test fixtures
REPO = Path(__file__).parents[1]  # repo root — holds terraform/
sys.path.insert(0, str(ENGINE))

from cloudapp import manifest, resolve

PLATFORM = ENGINE / "tests" / "fixtures" / "environments" / "dev.yml"
OUT = REPO / "terraform" / "azure" / "tests" / "fixtures"

CASES = [("minimal", "dev"), ("full", "prod"), ("multi", "dev"), ("partial", "dev"), ("databases", "dev")]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, env in CASES:
        _, _, tools, _ = manifest.parse(ENGINE / "tests" / "fixtures" / "manifests" / f"{name}.yml")
        tfvars = resolve.resolve(tools[env], PLATFORM, env)
        path = OUT / f"tfvars.{name}.{env}.json"
        path.write_text(json.dumps(tfvars, indent=2) + "\n")
        print(f"wrote {path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
