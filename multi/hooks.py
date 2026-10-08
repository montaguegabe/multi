"""Workspace-level git hooks.

A workspace opts in with ``"hooks": {"path": ".githooks"}`` in multi.json.
Multi then points ``core.hooksPath`` of the root repo and of every sub-repo at
that one directory, so a single workspace-level definition governs every
commit and push in the workspace, its worktrees and fresh clones.

- The root repo gets the *relative* path. Git resolves a relative
  ``core.hooksPath`` against the working tree that runs the hook, and git
  worktrees share the root repo's config, so every worktree of the root
  (including ``multi worktree add`` worktrees) uses its own checkout's hooks.
- Sub-repos get the *absolute* path of the workspace's hooks directory. Each
  workspace (and each multi worktree) clones its own sub-repos, so the value
  is per workspace, and ad-hoc ``git worktree add`` checkouts of a sub-repo
  outside the workspace still run the workspace hooks.
- Sub-repos that are symlinks to a clone owned by another workspace are left
  alone: their owning workspace manages their hooks.
"""

import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import click

from multi.errors import GitError
from multi.git_helpers import is_git_repo_root
from multi.paths import Paths
from multi.repos import load_repos

logger = logging.getLogger(__name__)

ROOT_NAME = "(root)"

# Hook names git runs from core.hooksPath; used to flag non-executable files,
# which git silently skips.
GIT_HOOK_NAMES = frozenset(
    {
        "applypatch-msg",
        "pre-applypatch",
        "post-applypatch",
        "pre-commit",
        "pre-merge-commit",
        "prepare-commit-msg",
        "commit-msg",
        "post-commit",
        "pre-rebase",
        "post-checkout",
        "post-merge",
        "pre-push",
        "pre-auto-gc",
        "post-rewrite",
        "reference-transaction",
        "push-to-checkout",
    }
)

STATE_OK = "installed"
STATE_MISSING = "missing"
STATE_MISMATCH = "mismatch"
STATE_NOT_CLONED = "not-cloned"
STATE_SYMLINKED = "symlinked"
PROBLEM_STATES = {STATE_MISSING, STATE_MISMATCH}


@dataclass(frozen=True)
class RepoHookStatus:
    name: str
    path: str
    state: str
    expected: str | None
    actual: str | None


@dataclass(frozen=True)
class HooksStatus:
    hooks_dir: str
    hooks_dir_exists: bool
    hooks: list[str]
    non_executable: list[str]
    repos: list[RepoHookStatus]

    @property
    def ok(self) -> bool:
        return (
            self.hooks_dir_exists
            and not self.non_executable
            and not any(repo.state in PROBLEM_STATES for repo in self.repos)
        )

    def to_dict(self) -> dict:
        result = asdict(self)
        result["ok"] = self.ok
        return result


def configured_hooks_path(paths: Paths) -> str | None:
    """Return the workspace-relative hooks directory from multi.json, if any."""
    hooks_settings = paths.settings.get("hooks")
    if hooks_settings is None:
        return None
    if not isinstance(hooks_settings, dict):
        raise ValueError('multi.json field "hooks" must be an object.')

    raw = hooks_settings.get("path")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('multi.json field "hooks.path" must be a non-empty string.')
    posix = PurePosixPath(raw.strip())
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError(
            'multi.json field "hooks.path" must be a relative path inside the '
            "workspace (no leading '/' and no '..')."
        )
    return posix.as_posix()


def _git_config_get(repo_path: Path, key: str) -> str | None:
    result = subprocess.run(
        ["git", "config", "--get", key],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 1:
        return None
    raise GitError(f"Could not read {key} in {repo_path}: {result.stderr.strip()}")


def _git_config(repo_path: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "config", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(
            f"Failed to run git config {' '.join(args)} in {repo_path}: "
            f"{result.stderr.strip()}"
        )


def _targets(paths: Paths) -> list[tuple[str, Path, bool]]:
    """Return (name, path, is_root) for the root and every declared sub-repo."""
    targets = [(ROOT_NAME, paths.root_dir, True)]
    if not paths.settings.is_monorepo():
        targets.extend((repo.name, repo.path, False) for repo in load_repos(paths))
    return targets


def _expected_value(paths: Paths, relative_hooks_path: str, is_root: bool) -> str:
    if is_root:
        return relative_hooks_path
    return str((paths.root_dir / relative_hooks_path).resolve())


def _require_hooks_path(paths: Paths) -> str:
    relative_hooks_path = configured_hooks_path(paths)
    if relative_hooks_path is None:
        raise click.UsageError(
            'No workspace hooks configured. Add "hooks": {"path": ".githooks"} '
            "to multi.json."
        )
    return relative_hooks_path


def _list_hooks(hooks_dir: Path) -> tuple[list[str], list[str]]:
    if not hooks_dir.is_dir():
        return [], []
    hooks = sorted(
        entry.name
        for entry in hooks_dir.iterdir()
        if entry.is_file() and entry.name in GIT_HOOK_NAMES
    )
    non_executable = [
        name for name in hooks if not os.access(hooks_dir / name, os.X_OK)
    ]
    return hooks, non_executable


def hooks_status(paths: Paths) -> HooksStatus:
    relative_hooks_path = _require_hooks_path(paths)
    hooks_dir = paths.root_dir / relative_hooks_path
    hooks, non_executable = _list_hooks(hooks_dir)

    repos: list[RepoHookStatus] = []
    for name, repo_path, is_root in _targets(paths):
        expected = _expected_value(paths, relative_hooks_path, is_root)
        display_path = "." if is_root else str(repo_path.relative_to(paths.root_dir))
        if not is_root and repo_path.is_symlink():
            state, expected, actual = STATE_SYMLINKED, None, None
        elif not is_git_repo_root(repo_path):
            state, expected, actual = STATE_NOT_CLONED, None, None
        else:
            actual = _git_config_get(repo_path, "core.hooksPath")
            if actual is None:
                state = STATE_MISSING
            elif actual == expected:
                state = STATE_OK
            else:
                state = STATE_MISMATCH
        repos.append(
            RepoHookStatus(
                name=name,
                path=display_path,
                state=state,
                expected=expected,
                actual=actual,
            )
        )

    return HooksStatus(
        hooks_dir=relative_hooks_path,
        hooks_dir_exists=hooks_dir.is_dir(),
        hooks=hooks,
        non_executable=non_executable,
        repos=repos,
    )


def install_hooks(paths: Paths) -> list[str]:
    """Point core.hooksPath of the root and every cloned sub-repo at the
    workspace hooks directory. Returns the names of repos that changed.

    A no-op when multi.json does not configure ``hooks.path``.
    """
    relative_hooks_path = configured_hooks_path(paths)
    if relative_hooks_path is None:
        return []

    hooks_dir = paths.root_dir / relative_hooks_path
    if not hooks_dir.is_dir():
        logger.warning(
            f"Workspace hooks directory {relative_hooks_path} does not exist yet; "
            "git runs no hooks until it does."
        )

    changed: list[str] = []
    for name, repo_path, is_root in _targets(paths):
        if not is_root and repo_path.is_symlink():
            logger.debug(f"Skipping hooks for symlinked repo {name}")
            continue
        if not is_git_repo_root(repo_path):
            continue
        expected = _expected_value(paths, relative_hooks_path, is_root)
        actual = _git_config_get(repo_path, "core.hooksPath")
        if actual == expected:
            continue
        if actual is not None:
            logger.warning(
                f"{name}: replacing core.hooksPath '{actual}' with the workspace "
                f"hooks. Chain repo-local hooks from the workspace hooks instead."
            )
        _git_config(repo_path, "core.hooksPath", expected)
        changed.append(name)

    if changed:
        logger.info(
            f"🪝 Installed workspace hooks ({relative_hooks_path}) in: "
            f"{', '.join(changed)}"
        )
    return changed


def uninstall_hooks(paths: Paths) -> list[str]:
    """Unset core.hooksPath wherever it points at the workspace hooks."""
    relative_hooks_path = _require_hooks_path(paths)
    removed: list[str] = []
    for name, repo_path, is_root in _targets(paths):
        if not is_root and repo_path.is_symlink():
            continue
        if not is_git_repo_root(repo_path):
            continue
        expected = _expected_value(paths, relative_hooks_path, is_root)
        if _git_config_get(repo_path, "core.hooksPath") == expected:
            _git_config(repo_path, "--unset", "core.hooksPath")
            removed.append(name)
    return removed


def _print_status(status: HooksStatus) -> None:
    dir_note = "" if status.hooks_dir_exists else "  (MISSING)"
    click.echo(f"Hooks directory: {status.hooks_dir}{dir_note}")
    click.echo(f"Hooks: {', '.join(status.hooks) or '(none)'}")
    if status.non_executable:
        click.secho(
            f"Not executable (git skips them): {', '.join(status.non_executable)}",
            fg="red",
        )

    width = max(len(repo.path) for repo in status.repos)
    colors = {STATE_OK: "green", STATE_MISSING: "red", STATE_MISMATCH: "red"}
    for repo in status.repos:
        line = f"  {repo.path:<{width}}  {repo.state}"
        if repo.state == STATE_MISMATCH:
            line += f"  (core.hooksPath={repo.actual}, expected {repo.expected})"
        click.secho(line, fg=colors.get(repo.state))

    if status.ok:
        click.secho(
            "✅ Workspace hooks are installed in every cloned repo.", fg="green"
        )
    else:
        click.secho(
            "❌ Workspace hooks are not fully installed. Run `multi hooks install`.",
            fg="red",
        )


@click.group(name="hooks")
def hooks_cmd() -> None:
    """Manage workspace-level git hooks (multi.json "hooks.path").

    One hooks directory at the workspace root governs the root repo and every
    sub-repo. `multi sync`, `multi init` and `multi worktree add` install it
    automatically.
    """


@click.command(name="install")
def hooks_install_cmd() -> None:
    """Point core.hooksPath of every repo at the workspace hooks directory."""
    paths = Paths(Path.cwd())
    _require_hooks_path(paths)
    install_hooks(paths)
    status = hooks_status(paths)
    _print_status(status)
    if not status.ok:
        raise click.ClickException("Workspace hooks are not fully installed.")


@click.command(name="status")
@click.option("--json", "output_json", is_flag=True, help="Output JSON.")
def hooks_status_cmd(output_json: bool) -> None:
    """Report whether every repo uses the workspace hooks. Exits 1 if not."""
    status = hooks_status(Paths(Path.cwd()))
    if output_json:
        click.echo(json.dumps(status.to_dict(), indent=2))
    else:
        _print_status(status)
    if not status.ok:
        raise SystemExit(1)


@click.command(name="uninstall")
def hooks_uninstall_cmd() -> None:
    """Unset core.hooksPath wherever it points at the workspace hooks."""
    removed = uninstall_hooks(Paths(Path.cwd()))
    click.echo(f"Removed workspace hooks from: {', '.join(removed) or '(none)'}")
