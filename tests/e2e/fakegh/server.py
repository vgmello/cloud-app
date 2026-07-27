#!/usr/bin/env python3
"""A GitHub REST API stand-in for the two scripts the deploy action shells out to.

`fetch_bootstrap_cache.py` reads a file from the control repo; `dispatch_and_wait.py`
dispatches the bootstrap workflow, polls it, and pulls the deployment-outputs
artifact. Those six endpoints are the whole surface.

The dispatch does NOT recursively run the control-side workflow under act. It
returns a seeded result instead, and the control side gets its own scenarios
(tests/e2e/test_deploy_stack.py) that drive `deploy-stack` directly. Nesting act
inside act would buy nothing the two halves do not already cover, at the cost of
docker-in-docker.

Every dispatch is appended to `dispatches.jsonl`, which is how the cache-hit
scenario proves no dispatch happened.
"""

import base64
import io
import json
import os
import re
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

STATE = Path(os.environ.get("FAKEGH_STATE", "/state"))
PORT = int(os.environ.get("FAKEGH_PORT", "8080"))
RUN_ID = 424242
ARTIFACT_ID = 99

CONTENTS = re.compile(r"^/repos/[^/]+/[^/]+/contents/(?P<path>.+)$")
DISPATCH = re.compile(r"^/repos/[^/]+/[^/]+/actions/workflows/(?P<wf>[^/]+)/dispatches$")
RUN = re.compile(r"^/repos/[^/]+/[^/]+/actions/runs/(?P<run>\d+)$")
JOBS = re.compile(r"^/repos/[^/]+/[^/]+/actions/runs/(?P<run>\d+)/jobs$")
ARTIFACTS = re.compile(r"^/repos/[^/]+/[^/]+/actions/runs/(?P<run>\d+)/artifacts$")
ARTIFACT_ZIP = re.compile(r"^/repos/[^/]+/[^/]+/actions/artifacts/(?P<id>\d+)/zip$")


def config():
    """Per-scenario seed, written by pytest before the run."""
    path = STATE / "fakegh.json"
    return json.loads(path.read_text()) if path.exists() else {}


def record(name, entry):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / name, "a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def results():
    """The deployment-results.json the bootstrap run would have produced."""
    seeded = config().get("deployment_results")
    if seeded is not None:
        return seeded
    return {
        "stack_name": "orders-api",
        "environment": "dev",
        "resource_group": "rg-orders-api-dev",
        "plan_client_id": "11111111-1111-1111-1111-111111111111",
        "apply_client_id": "22222222-2222-2222-2222-222222222222",
        "deployed_at": "2026-07-26T00:00:00Z",
        "status": "success",
    }


def artifact_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("deployment-results.json", json.dumps(results()))
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        record("requests.jsonl", {"line": fmt % args, "path": self.path})

    def _send(self, status, body=b"", content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's naming
        path = urlparse(self.path).path

        match = CONTENTS.match(path)
        if match:
            wanted = unquote(match.group("path"))
            body = (config().get("contents") or {}).get(wanted)
            if body is None:
                return self._send(404, {"message": "Not Found"})
            return self._send(200, {
                "path": wanted,
                "encoding": "base64",
                "content": base64.b64encode(body.encode()).decode(),
            })

        if RUN.match(path):
            return self._send(200, {
                "status": "completed",
                "conclusion": config().get("conclusion", "success"),
                "html_url": f"http://fakegh/run/{RUN_ID}",
            })

        if JOBS.match(path):
            return self._send(200, {"jobs": [{
                "id": 1,
                "name": "bootstrap",
                "steps": [
                    {"name": "Validate stack ownership", "status": "completed", "conclusion": "success"},
                    {"name": "Terraform bootstrap", "status": "completed", "conclusion": "success"},
                ],
            }]})

        if ARTIFACTS.match(path):
            if config().get("no_artifact"):
                return self._send(200, {"artifacts": []})
            return self._send(200, {"artifacts": [{
                "id": ARTIFACT_ID,
                "name": f"deployment-outputs-{RUN_ID}",
                "archive_download_url":
                    f"http://{self.headers.get('Host')}/repos/o/r/actions/artifacts/{ARTIFACT_ID}/zip",
            }]})

        if ARTIFACT_ZIP.match(path):
            return self._send(200, artifact_zip(), "application/zip")

        return self._send(404, {"message": "Not Found"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")

        match = DISPATCH.match(path)
        if not match:
            return self._send(404, {"message": "Not Found"})

        inputs = payload.get("inputs", {})
        record("dispatches.jsonl", {
            "workflow": match.group("wf"),
            "ref": payload.get("ref"),
            "inputs": inputs,
        })
        if config().get("dispatch_status"):
            return self._send(config()["dispatch_status"], {"message": "seeded failure"})

        # GitHub rejects a payload carrying inputs the target workflow does not
        # declare. Mirroring that is the whole point: a permissive fake here is
        # what let the action ship eight undeclared inputs -- including the App
        # private key -- without a single test noticing.
        declared = set(config().get("declared_inputs") or [])
        if declared:
            unexpected = sorted(set(inputs) - declared)
            if unexpected:
                return self._send(422, {
                    "message": "Unexpected inputs provided: "
                               + ", ".join(repr(name) for name in unexpected),
                    "documentation_url": "https://docs.github.com/rest",
                })
        return self._send(200, {
            "workflow_run_id": RUN_ID,
            "html_url": f"http://fakegh/run/{RUN_ID}",
        })


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"fakegh listening on {PORT}, state {STATE}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
