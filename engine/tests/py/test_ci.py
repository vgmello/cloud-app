"""The CI provider adapter: selection, dispatch, and per-provider I/O.

Provider tests call the provider modules directly rather than through the
package-level functions, so that a real GITHUB_ACTIONS in the ambient
environment cannot change what they exercise.
"""

import pytest

from cloudapp import ci
from cloudapp.ci import base, github

PROTOCOL = ("write_outputs", "append_summary", "notice", "warning", "error")


@pytest.fixture(autouse=True)
def reset_impl():
    """No test may leak a selected implementation into the next one."""
    ci.use(None)
    yield
    ci.use(None)


class FakeCI:
    def __init__(self):
        self.outputs = []
        self.summaries = []
        self.messages = []

    def write_outputs(self, outputs, fallback_file=None):
        self.outputs.append((outputs, fallback_file))

    def append_summary(self, markdown):
        self.summaries.append(markdown)

    def notice(self, msg):
        self.messages.append(("notice", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


def test_detect_defaults_to_base_outside_ci():
    assert ci.detect({}) is base


def test_unknown_provider_is_an_error_not_a_silent_fallback():
    with pytest.raises(ValueError, match="unknown CI provider 'jenkins'"):
        ci.detect({"CLOUDAPP_CI": "jenkins"})


def test_use_substitutes_the_implementation():
    fake = FakeCI()
    ci.use(fake)

    ci.write_outputs({"a": "1"})
    ci.append_summary("# hi")
    ci.notice("n")
    ci.warning("w")
    ci.error("e")

    assert fake.outputs == [({"a": "1"}, None)]
    assert fake.summaries == ["# hi"]
    assert fake.messages == [("notice", "n"), ("warning", "w"), ("error", "e")]


def test_use_none_restores_autodetection(monkeypatch):
    ci.use(FakeCI())
    ci.use(None)
    monkeypatch.delenv("CLOUDAPP_CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    assert ci.detect() is base


def test_dispatch_resolves_the_provider_on_first_use(monkeypatch, capsys):
    monkeypatch.delenv("CLOUDAPP_CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    ci.use(None)

    ci.notice("x")

    assert capsys.readouterr().out == "notice: x\n"


def test_base_writes_outputs_to_the_fallback_file(tmp_path):
    out = tmp_path / "outputs.txt"
    base.write_outputs({"name": "orders", "docker": "true"}, fallback_file=out)
    assert out.read_text() == "name=orders\ndocker=true\n"


def test_base_without_a_fallback_file_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base.write_outputs({"name": "orders"})
    assert list(tmp_path.iterdir()) == []


def test_base_summary_goes_to_stdout(capsys):
    base.append_summary("### plan")
    assert capsys.readouterr().out == "### plan\n"


def test_base_diagnostics_split_across_streams(capsys):
    base.notice("n")
    base.warning("w")
    base.error("e")
    captured = capsys.readouterr()
    assert captured.out == "notice: n\n"
    assert captured.err == "warning: w\nerror: e\n"


def test_detect_recognises_github():
    assert ci.detect({"GITHUB_ACTIONS": "true"}) is github


def test_explicit_override_beats_github_autodetection():
    assert ci.detect({"CLOUDAPP_CI": "base", "GITHUB_ACTIONS": "true"}) is base


def test_github_appends_outputs_to_github_output(tmp_path, monkeypatch):
    gh = tmp_path / "gh-output"
    gh.write_text("existing=1\n")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    github.write_outputs({"image-tags": "{}"})
    assert gh.read_text() == "existing=1\nimage-tags={}\n"


def test_github_writes_both_the_fallback_file_and_github_output(tmp_path, monkeypatch):
    gh = tmp_path / "gh-output"
    fallback = tmp_path / "outputs.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    github.write_outputs({"name": "orders"}, fallback_file=fallback)
    assert gh.read_text() == "name=orders\n"
    assert fallback.read_text() == "name=orders\n"


def test_github_outputs_are_a_no_op_off_ci(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.chdir(tmp_path)

    github.write_outputs({"name": "orders"})

    assert list(tmp_path.iterdir()) == []


def test_github_appends_to_the_step_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    github.append_summary("### plan")
    assert summary.read_text() == "### plan\n"


def test_github_summary_is_a_no_op_off_ci(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(tmp_path)

    github.append_summary("### plan")

    assert list(tmp_path.iterdir()) == []


def test_github_annotations_use_the_workflow_command_syntax(capsys):
    github.notice("n")
    github.warning("w")
    github.error("e")
    assert capsys.readouterr().out == "::notice::n\n::warning::w\n::error::e\n"
