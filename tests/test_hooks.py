import json
import os
import subprocess
from pathlib import Path

import git
import pytest
from click.testing import CliRunner

from multi.cli import main
from multi.doctor import run_doctor_checks
from multi.hooks import (
    STATE_MISMATCH,
    STATE_MISSING,
    STATE_NOT_CLONED,
    STATE_OK,
    STATE_SYMLINKED,
    configured_hooks_path,
    hooks_status,
    install_hooks,
    uninstall_hooks,
)
from multi.paths import Paths
from multi.sync import sync
from multi.worktree import add_worktree
from tests.test_worktree import _commit_all, _create_remote_repo

REFUSING_PRE_COMMIT = "#!/bin/sh\necho 'workspace pre-commit ran' >&2\nexit 1\n"


@pytest.fixture(autouse=True)
def stub_remote_validation(monkeypatch):
    monkeypatch.setattr("multi.doctor.validate_repo_remote", lambda url: None)


def _hooks_config(repo_path: Path) -> str | None:
    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _create_hooked_workspace(
    tmp_path: Path,
    repo_names: list[str],
    *,
    hooks: dict | None = None,
) -> Path:
    """A committed workspace with a refusing pre-commit hook in .githooks/.

    Sub-repos are cloned by `multi sync`, which installs the hooks.
    """
    root_path = tmp_path / "workspace"
    root_path.mkdir()
    repo_configs = [
        {"url": str(_create_remote_repo(tmp_path, name)), "name": name}
        for name in repo_names
    ]
    config = {"repos": repo_configs}
    config["hooks"] = hooks if hooks is not None else {"path": ".githooks"}
    (root_path / "multi.json").write_text(json.dumps(config, indent=2) + "\n")
    (root_path / ".gitignore").write_text(
        "".join(f"{c['name']}/\n" for c in repo_configs)
    )
    hooks_dir = root_path / ".githooks"
    hooks_dir.mkdir()
    (hooks_dir / "pre-commit").write_text(REFUSING_PRE_COMMIT)
    (hooks_dir / "pre-commit").chmod(0o755)
    (hooks_dir / "README.md").write_text("not a hook\n")

    root_repo = git.Repo.init(root_path, initial_branch="main")
    _commit_all(root_repo, "Initial commit")
    sync(root_dir=root_path, ensure_on_same_branch=False)
    return root_path


def _commit_refused(repo_path: Path) -> bool:
    (repo_path / "change.txt").write_text("change\n")
    subprocess.run(["git", "add", "change.txt"], cwd=repo_path, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", "change"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode != 0 and "workspace pre-commit ran" in result.stderr


def test_sync_installs_relative_root_and_absolute_subrepo_hooks(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0", "repo1"])

    assert _hooks_config(root_path) == ".githooks"
    expected = str((root_path / ".githooks").resolve())
    assert _hooks_config(root_path / "repo0") == expected
    assert _hooks_config(root_path / "repo1") == expected

    status = hooks_status(Paths(root_path))
    assert status.ok
    assert status.hooks == ["pre-commit"]
    assert {repo.state for repo in status.repos} == {STATE_OK}


def test_installed_hook_runs_in_root_and_subrepos(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0"])

    assert _commit_refused(root_path)
    assert _commit_refused(root_path / "repo0")


def test_worktree_add_installs_hooks_from_the_worktree_checkout(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0"])

    destination = add_worktree(root_path, name="feature-hooks")

    # Root worktrees share config with the main checkout; the relative value
    # resolves against each worktree's own checkout.
    assert _hooks_config(destination) == ".githooks"
    assert _hooks_config(destination / "repo0") == str(
        (destination / ".githooks").resolve()
    )
    assert hooks_status(Paths(destination)).ok
    assert _commit_refused(destination)
    assert _commit_refused(destination / "repo0")


def test_subrepo_hook_survives_ad_hoc_worktree_outside_workspace(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0"])
    outside = tmp_path / "outside-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "side", str(outside)],
        cwd=root_path / "repo0",
        check=True,
        capture_output=True,
    )

    assert _commit_refused(outside)


def test_install_repairs_missing_and_mismatched_values(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0", "repo1"])
    subprocess.run(
        ["git", "config", "--unset", "core.hooksPath"], cwd=root_path / "repo0"
    )
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"], cwd=root_path / "repo1"
    )

    states = {repo.name: repo.state for repo in hooks_status(Paths(root_path)).repos}
    assert states["repo0"] == STATE_MISSING
    assert states["repo1"] == STATE_MISMATCH
    assert not hooks_status(Paths(root_path)).ok

    assert install_hooks(Paths(root_path)) == ["repo0", "repo1"]
    assert hooks_status(Paths(root_path)).ok
    assert install_hooks(Paths(root_path)) == []


def test_status_skips_uncloned_and_symlinked_repos(tmp_path):
    shared_clone = tmp_path / "shared-clone"
    git.Repo.clone_from(str(_create_remote_repo(tmp_path, "shared")), shared_clone)
    root_path = _create_hooked_workspace(tmp_path, ["repo0"])
    # A repo outside the current install set, and a repo symlinked from
    # another workspace (allowSymlinks).
    os.symlink(shared_clone, root_path / "linked")
    config = json.loads((root_path / "multi.json").read_text())
    config["repos"] += [
        {"url": "https://example.invalid/never-cloned", "name": "absent"},
        {"url": "https://example.invalid/shared", "name": "linked"},
    ]
    (root_path / "multi.json").write_text(json.dumps(config))

    install_hooks(Paths(root_path))
    states = {repo.name: repo.state for repo in hooks_status(Paths(root_path)).repos}

    assert states["absent"] == STATE_NOT_CLONED
    assert states["linked"] == STATE_SYMLINKED
    assert _hooks_config(shared_clone) is None
    assert hooks_status(Paths(root_path)).ok


def test_status_flags_missing_dir_and_non_executable_hooks(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0"])
    (root_path / ".githooks" / "pre-commit").chmod(0o644)

    status = hooks_status(Paths(root_path))
    assert status.non_executable == ["pre-commit"]
    assert not status.ok

    (root_path / ".githooks" / "pre-commit").unlink()
    (root_path / ".githooks" / "README.md").unlink()
    (root_path / ".githooks").rmdir()
    assert not hooks_status(Paths(root_path)).hooks_dir_exists
    assert not hooks_status(Paths(root_path)).ok


def test_unconfigured_workspace_is_left_alone(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0"], hooks={})

    assert configured_hooks_path(Paths(root_path)) is None
    assert _hooks_config(root_path) is None
    assert _hooks_config(root_path / "repo0") is None


@pytest.mark.parametrize("bad_path", ["/abs/hooks", "../outside", "", 3])
def test_hooks_path_must_stay_inside_workspace(tmp_path, bad_path):
    root_path = tmp_path / "workspace"
    root_path.mkdir()
    (root_path / "multi.json").write_text(
        json.dumps({"repos": [], "hooks": {"path": bad_path}})
    )

    with pytest.raises(ValueError):
        configured_hooks_path(Paths(root_path))


def test_uninstall_only_removes_workspace_values(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0", "repo1"])
    subprocess.run(
        ["git", "config", "core.hooksPath", "custom"], cwd=root_path / "repo1"
    )

    assert uninstall_hooks(Paths(root_path)) == ["(root)", "repo0"]
    assert _hooks_config(root_path / "repo0") is None
    assert _hooks_config(root_path / "repo1") == "custom"


def test_doctor_warns_when_hooks_not_installed(tmp_path):
    root_path = _create_hooked_workspace(tmp_path, ["repo0"])
    assert not any("hooks" in w for w in run_doctor_checks(root_path).warnings)

    subprocess.run(
        ["git", "config", "--unset", "core.hooksPath"], cwd=root_path / "repo0"
    )
    warnings = run_doctor_checks(root_path).warnings
    assert any("not installed in: repo0" in w for w in warnings)


def test_hooks_cli_status_and_install(tmp_path, monkeypatch):
    root_path = _create_hooked_workspace(tmp_path, ["repo0"])
    monkeypatch.chdir(root_path)
    runner = CliRunner()

    result = runner.invoke(main, ["hooks", "status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert [repo["path"] for repo in payload["repos"]] == [".", "repo0"]

    subprocess.run(
        ["git", "config", "--unset", "core.hooksPath"], cwd=root_path / "repo0"
    )
    assert runner.invoke(main, ["hooks", "status"]).exit_code == 1

    result = runner.invoke(main, ["hooks", "install"])
    assert result.exit_code == 0, result.output
    assert runner.invoke(main, ["hooks", "status"]).exit_code == 0
