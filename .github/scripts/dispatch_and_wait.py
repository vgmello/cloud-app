"""Dispatch a workflow_dispatch in a target repo and wait for the run.

The pure helpers (input collection, header building, artifact/output handling,
step and status rendering, poll-error classification) are importable and
unit-tested. The network stages (`dispatch_run`, `wait_for_completion`,
`expose_deployment_outputs`) are tested with urllib.urlopen monkeypatched;
`main()` just wires them together.
"""

import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile

# GitHub Actions sets GITHUB_API_URL on every runner (to https://api.github.com
# on github.com, to the instance API on GHES), so reading it is the idiomatic
# form and also lets the e2e suite point this at a local server.
API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")

# The workflow-dispatch API accepts a branch or tag only (HTTP 422 on a commit
# SHA). A caller who pins this action at `@<sha>` previously fed `main`
# through here (github.action_ref resolves to the tag/branch pin, not a SHA
# pin); with control-ref falling back to github.action_ref, a SHA pin now
# flows straight into TARGET_BRANCH, so it must be caught and swapped back.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

# Give up polling after this many consecutive failures (~1 min at 10s each) so a
# persistent 404 (wrong run id) or expired token does not loop until the job's
# own timeout.
MAX_POLL_FAILURES = 6

POLL_INTERVAL = 10


# --- Pure helpers (unit-tested) ---

def collect_target_inputs(environ):
    """Map INPUT_* env vars to workflow_dispatch inputs (INPUT_STACK_FILE ->
    stack_file)."""
    return {
        key[len("INPUT_"):].lower(): value
        for key, value in environ.items()
        if key.startswith("INPUT_")
    }


def build_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def pick_artifact(artifacts, run_id):
    """The deployment-outputs artifact for this run, or None."""
    name = f"deployment-outputs-{run_id}"
    return next((a for a in artifacts if a.get("name") == name), None)


def extract_results(zip_bytes):
    """Read deployment-results.json out of the artifact zip."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf, zf.open("deployment-results.json") as f:
        return json.load(f)


def format_output_lines(results):
    """key=value lines for $GITHUB_OUTPUT, one per result field."""
    return "".join(f"{key}={value}\n" for key, value in results.items())


def render_step(step):
    """Display line for a target step transition, or None if not worth printing."""
    if step["status"] == "in_progress":
        return f"  Running step: {step['name']}..."
    if step["status"] == "completed":
        mark = "ok" if step.get("conclusion") == "success" else "FAILED"
        return f"  [{mark}] {step['name']}"
    return None


def step_key(job, step):
    return f"{job['id']}_{step['name']}_{step['status']}"


def collect_step_lines(jobs_data, seen):
    """Printable lines for step transitions not yet in `seen`; records each key
    in `seen` so a transition prints once across polls."""
    lines = []
    for job in jobs_data.get("jobs", []):
        for step in job.get("steps", []):
            key = step_key(job, step)
            if key in seen:
                continue
            seen.add(key)
            line = render_step(step)
            if line:
                lines.append(line)
    return lines


def status_line(status):
    if status == "queued":
        return "Status: queued (waiting for concurrent deployment lock)..."
    return f"Status: {status}..."


def resolve_ref(value):
    """The workflow-dispatch API takes a branch or tag, not a commit SHA. A
    full 40-hex SHA (e.g. from a caller pinning this action at `@<sha>`) is
    swapped for `main` with a warning; anything else passes through."""
    if _SHA_RE.match(value):
        print(f"::warning::TARGET_BRANCH '{value}' looks like a commit SHA, which the "
              "workflow-dispatch API cannot accept (branch or tag only); using 'main' instead")
        return "main"
    return value


def poll_error_action(code, failures, max_failures):
    """What to do after a failed status poll: 'auth' (fatal, bad token),
    'giveup' (too many consecutive failures), or 'retry'."""
    if code in (401, 403):
        return "auth"
    if failures >= max_failures:
        return "giveup"
    return "retry"


# --- Network primitives ---

def _download(url, headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as resp:
        return resp.read()


def _get_json(url, headers):
    return json.loads(_download(url, headers).decode("utf-8"))


# --- Network stages ---

def dispatch_run(repo_api, workflow_id, branch, inputs, headers):
    """POST the workflow_dispatch and return (run_id, html_url). Exit on error."""
    req = urllib.request.Request(
        f"{repo_api}/actions/workflows/{workflow_id}/dispatches",
        data=json.dumps({"ref": branch, "inputs": inputs, "return_run_details": True}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"::error::HTTP Error {e.code}: {e.read().decode('utf-8')}")
        sys.exit(1)
    return data["workflow_run_id"], data.get("html_url", "")


def record_run_url(run_html_url):
    """Expose the target run URL to later steps via $GITHUB_ENV."""
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as fh:
            fh.write(f"TARGET_RUN_URL={run_html_url}\n")


def expose_deployment_outputs(run_api, run_id, headers):
    """Copy the target run's deployment-results.json into $GITHUB_OUTPUT. Best
    effort: any missing artifact or fetch failure warns and returns."""
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if not gh_output:
        return
    try:
        artifacts = _get_json(f"{run_api}/artifacts", headers).get("artifacts", [])
    except Exception as exc:
        print(f"::warning::could not list artifacts for run {run_id}: {exc}")
        return
    target = pick_artifact(artifacts, run_id)
    if not target:
        print("::warning::no deployment-outputs artifact on the target run")
        return
    try:
        results = extract_results(_download(target["archive_download_url"], headers))
    except Exception as exc:
        print(f"::warning::could not download/parse deployment outputs: {exc}")
        return
    with open(gh_output, "a") as out:
        out.write(format_output_lines(results))
    print(f"Exposed deployment outputs: {results}")


def _poll_once(poll_req, run_id, failures):
    """Fetch run status. Returns (run_data, failures) on success. On an HTTP
    error, applies poll_error_action: exits on auth/give-up, or sleeps and
    returns (None, incremented failures) to retry."""
    try:
        with urllib.request.urlopen(poll_req) as resp:
            return json.loads(resp.read().decode("utf-8")), 0
    except urllib.error.HTTPError as e:
        failures += 1
        action = poll_error_action(e.code, failures, MAX_POLL_FAILURES)
        if action == "auth":
            print(f"::error::Auth failed polling run {run_id} ({e.code}); token invalid or lacks access")
            sys.exit(1)
        if action == "giveup":
            print(f"::error::Gave up polling run {run_id} after {failures} consecutive failures (last {e.code})")
            sys.exit(1)
        print(f"Status poll warning ({e.code}), retry {failures}/{MAX_POLL_FAILURES} in {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)
        return None, failures


def _fetch_jobs(run_api, headers):
    """Jobs for the run, or {} if the listing fails (step streaming is best
    effort and must not abort the poll loop)."""
    try:
        return _get_json(f"{run_api}/jobs", headers)
    except Exception:
        return {}


def wait_for_completion(repo_api, run_id, headers):
    """Poll the run until it completes, streaming step transitions. Returns the
    final conclusion; exposes deployment outputs on completion."""
    run_api = f"{repo_api}/actions/runs/{run_id}"
    poll_req = urllib.request.Request(run_api, headers=headers)
    last_status = None
    failures = 0
    seen_steps = set()
    while True:
        run_data, failures = _poll_once(poll_req, run_id, failures)
        if run_data is None:
            continue

        status = run_data["status"]
        if status != last_status:
            print(status_line(status))
            last_status = status

        for line in collect_step_lines(_fetch_jobs(run_api, headers), seen_steps):
            print(line)

        if status == "completed":
            conclusion = run_data.get("conclusion")
            print(f"\nTarget workflow complete: {(conclusion or 'unknown').upper()}")
            print(f"View logs: {run_data.get('html_url', '')}")
            expose_deployment_outputs(run_api, run_id, headers)
            return conclusion

        time.sleep(POLL_INTERVAL)


def main():
    owner = os.environ["TARGET_OWNER"]
    repo = os.environ["TARGET_REPO"]
    workflow_id = os.environ["TARGET_WORKFLOW"]
    branch = resolve_ref(os.environ.get("TARGET_BRANCH", "main"))
    headers = build_headers(os.environ["GH_TOKEN"])

    repo_api = f"{API}/repos/{owner}/{repo}"

    inputs = collect_target_inputs(os.environ)
    print(f"Target: {owner}/{repo} -> {workflow_id} (Branch: {branch})")
    print(f"Workflow Inputs: {inputs}")

    run_id, run_html_url = dispatch_run(repo_api, workflow_id, branch, inputs, headers)
    print(f"\nDispatched successfully! Run ID: {run_id}")
    print(f"Run URL: {run_html_url}")
    record_run_url(run_html_url)

    if wait_for_completion(repo_api, run_id, headers) != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
