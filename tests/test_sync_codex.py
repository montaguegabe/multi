import json
import logging
from pathlib import Path

from multi.doctor import run_doctor_checks
from multi.ignore_files import update_gitignore_with_generated_files
from multi.paths import Paths
from multi.sync_codex import GENERATED_MARKER, OVERRIDE_FILENAME, sync_all_codex


def _write_workspace(workspace: Path, *repo_names: str, extra=None) -> None:
    multi_json: dict = {
        "monoRepo": True,
        "repos": [{"name": name} for name in repo_names],
    }
    multi_json.update(extra or {})
    (workspace / "multi.json").write_text(json.dumps(multi_json, indent=2))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_override_embeds_root_and_sub_repo_instructions_without_touching_agents_md(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api", "web")
    _write(workspace / "AGENTS.md", "# Root rules\n\nBe careful.\n")
    _write(workspace / "api" / "AGENTS.md", "# API rules\n\nRun pytest.\n")
    _write(workspace / "web" / "CLAUDE.md", "# Web rules\n")

    sync_all_codex(root_dir=workspace)

    override = (workspace / OVERRIDE_FILENAME).read_text(encoding="utf-8")
    assert override.splitlines()[0] == GENERATED_MARKER
    assert "# Root rules\n\nBe careful.\n" in override
    assert "## Instructions for `api/`" in override
    assert "Run pytest." in override
    assert "## Instructions for `web/`" in override
    assert "`CLAUDE.md`" in override
    assert (
        override.index("Root rules")
        < override.index("API rules")
        < override.index("Web rules")
    )
    assert (workspace / "AGENTS.md").read_text() == "# Root rules\n\nBe careful.\n"


def test_never_replaces_an_override_multi_did_not_write(tmp_path, caplog):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    _write(workspace / "api" / "AGENTS.md", "# API rules\n")
    _write(workspace / OVERRIDE_FILENAME, "# Hand-written local override\n")

    with caplog.at_level(logging.WARNING):
        sync_all_codex(root_dir=workspace)

    assert (
        workspace / OVERRIDE_FILENAME
    ).read_text() == "# Hand-written local override\n"
    assert any("did not generate" in message for message in caplog.messages)


def test_removes_generated_override_when_no_sub_repo_has_instructions(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    _write(workspace / "api" / "AGENTS.md", "# API rules\n")
    sync_all_codex(root_dir=workspace)
    assert (workspace / OVERRIDE_FILENAME).exists()

    (workspace / "api" / "AGENTS.md").unlink()
    sync_all_codex(root_dir=workspace)

    assert not (workspace / OVERRIDE_FILENAME).exists()


def test_disabled_setting_writes_nothing(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api", extra={"codexOverride": {"enabled": False}})
    _write(workspace / "api" / "AGENTS.md", "# API rules\n")

    sync_all_codex(root_dir=workspace)

    assert not (workspace / OVERRIDE_FILENAME).exists()


def test_override_is_listed_in_the_generated_files_block(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    _write(workspace / "api" / "AGENTS.md", "# API rules\n")

    update_gitignore_with_generated_files(paths=Paths(workspace))

    assert OVERRIDE_FILENAME in (workspace / ".gitignore").read_text().splitlines()


def test_doctor_warns_when_override_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr("multi.doctor.validate_repo_remote", lambda url: None)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    _write(workspace / "api" / "AGENTS.md", "# API rules\n")
    sync_all_codex(root_dir=workspace)
    assert not any(
        OVERRIDE_FILENAME in w for w in run_doctor_checks(workspace).warnings
    )

    _write(workspace / "AGENTS.md", "# New root rules\n")

    assert any(
        OVERRIDE_FILENAME in warning and "out of date" in warning
        for warning in run_doctor_checks(workspace).warnings
    )
