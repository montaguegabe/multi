import logging
import subprocess
from pathlib import Path
from typing import List

import click

from multi.errors import GitError
from multi.git_helpers import check_all_on_same_branch
from multi.paths import Paths
from multi.repos import load_repos

logger = logging.getLogger(__name__)


def run_git_command(repo_path: Path, git_args: List[str]) -> None:
    """Run a git command in the specified repository."""
    command_str = " ".join(git_args)
    logger.info(f"Running 'git {command_str}' in {repo_path}")

    cmd = ["git"] + git_args
    try:
        outputs = subprocess.run(
            cmd,
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        logger.info(f"Output from {repo_path}:\n{outputs}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to run git command in {repo_path}")
        raise GitError(f"Failed to run git command in {repo_path}") from e


def run_git_in_all_repos(paths: Paths, git_args: List[str]) -> None:
    """Run git command across all repositories."""
    # First check if all repos are on their expected branch.
    check_all_on_same_branch(paths=paths, raise_error=True)

    # Run in root repo first
    run_git_command(paths.root_dir, git_args)

    # Then run in all sub-repos that are cloned here. A partial install set
    # (e.g. a public checkout) leaves internal-only repos absent.
    for repo in load_repos(paths):
        if not repo.is_cloned:
            logger.info(f"Skipping {repo.name}: not cloned in this workspace")
            continue
        run_git_command(repo.path, git_args)


@click.command(name="git", context_settings={"ignore_unknown_options": True})
@click.argument("git_args", nargs=-1, required=True)
def git_cmd(git_args: tuple[str, ...]) -> None:
    """Run a git command across all repositories.

    GIT_ARGS: The git command and arguments to run (e.g. 'pull' or 'checkout main')

    Example: multi git pull
             multi git checkout -b feature/new-branch
             multi git branch --show-current

    Requires all cloned repositories to be on their expected branch (working
    trees may be dirty). Repos not cloned in this workspace are skipped. To inspect branches when they mismatch, use `multi branch`.
    """
    paths = Paths(Path.cwd())
    if paths.settings.is_monorepo():
        raise click.UsageError(
            "The 'multi git' command is not available in monorepo mode. "
            "Use git directly in the root workspace."
        )
    run_git_in_all_repos(paths, list(git_args))
