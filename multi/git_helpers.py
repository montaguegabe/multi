import logging
from pathlib import Path
from typing import Any, Tuple

import git
from git.exc import InvalidGitRepositoryError, NoSuchPathError

from multi.errors import GitError, RepoNotCleanError
from multi.paths import Paths

logger = logging.getLogger(__name__)


def expected_branch_for_repo(repo: Any, workspace_branch: str | None) -> str | None:
    """Return the branch a sub-repo should be on.

    This is the fixed-branch invariant for Multi workspaces: a repo's
    ``fixedBranch`` config wins, otherwise it follows the workspace branch.
    Commands that need branch expectations should use this helper instead of
    reading ``repo.fixed_branch`` directly.
    """
    fixed_branch = getattr(repo, "fixed_branch", None)
    if fixed_branch is not None:
        return fixed_branch
    return workspace_branch


def repo_uses_fixed_branch(repo: Any) -> bool:
    return getattr(repo, "fixed_branch", None) is not None


def expected_branch_description(repo: Any, workspace_branch: str | None) -> str:
    expected_branch = expected_branch_for_repo(repo, workspace_branch)
    if repo_uses_fixed_branch(repo):
        return f"fixed branch {expected_branch}"
    return f"root branch {workspace_branch}"


def is_git_repo_root(repo_path: Path) -> bool:
    git_metadata_path = repo_path / ".git"
    if not git_metadata_path.exists():
        return False

    try:
        repo = git.Repo(repo_path)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return False

    return Path(repo.working_tree_dir or "").resolve() == repo_path.resolve()


def _open_repo_for_branch_lookup(repo_path: Path) -> git.Repo:
    try:
        return git.Repo(repo_path)
    except (InvalidGitRepositoryError, NoSuchPathError) as e:
        # No logging here: callers (or the CLI error wrapper) report the
        # error exactly once.
        raise GitError(
            f"Could not determine current branch for {repo_path.name}: not a git "
            "repository. Run `multi sync` from the workspace root."
        ) from e


def get_current_branch(repo_path: Path) -> str:
    """Get the current branch name of a git repository."""
    repo = _open_repo_for_branch_lookup(repo_path)
    if repo.head.is_detached:
        # Detached HEAD state has no branch name.
        return "HEAD"
    return repo.active_branch.name


def describe_head(repo_path: Path) -> str:
    """Return the current branch name, or a detached-HEAD description.

    Read-only: works with dirty working trees and in linked worktrees
    (where ``.git`` is a file). A detached HEAD is reported as
    ``(detached at <short-sha>)`` instead of failing.
    """
    repo = _open_repo_for_branch_lookup(repo_path)
    if repo.head.is_detached:
        return f"(detached at {repo.git.rev_parse('--short', 'HEAD')})"
    return repo.active_branch.name


def check_all_on_same_branch(paths: Paths, raise_error: bool = True) -> bool:
    """Validate that all repositories are on the expected branch.

    Read-only: does not require clean working trees. Repos that were never
    cloned into this workspace are skipped. Detached HEADs are
    reported as ``(detached at <short-sha>)`` and never match an expected
    branch name.
    """
    from multi.repos import load_cloned_repos

    root_branch = describe_head(paths.root_dir)
    # Uncloned repos (outside this checkout's install set) have no branch.
    repo_branches = [
        (repo, describe_head(repo.path)) for repo in load_cloned_repos(paths)
    ]
    for repo, branch in repo_branches:
        expected_branch = expected_branch_for_repo(repo, root_branch)
        if branch != expected_branch:
            if raise_error:
                expectation = expected_branch_description(repo, root_branch)
                raise GitError(
                    f"Repository {repo.name} is not on the expected branch. "
                    f"Please fix. {repo.name}: {branch}, Expected: {expectation}"
                )
            return False
    return True


def check_repo_is_clean(repo_path: Path, raise_error: bool = True) -> bool:
    # Check if this is a git repository
    if not is_git_repo_root(repo_path):
        raise GitError(
            f"{repo_path} is not a git repository or has not been initialized properly (no .git folder)"
        )

    # Make sure we have a clean working directory
    try:
        repo = git.Repo(repo_path)
        # is_dirty checks for modified/staged files, untracked_files checks for new files
        is_clean = not repo.is_dirty(untracked_files=True)
    except InvalidGitRepositoryError as e:
        logger.error("Failed to check working directory status")
        raise GitError("Failed to check working directory status") from e

    if not is_clean:
        if raise_error:
            raise RepoNotCleanError(
                f"Working directory is not clean in {repo_path}. Please commit or stash changes first."
            )
        return False
    return True


def check_all_repos_are_clean(paths: Paths, raise_error: bool = True) -> bool:
    """Check if all repositories are clean."""
    from multi.repos import load_repos

    # Check root repo
    if not check_repo_is_clean(paths.root_dir, raise_error):
        return False

    # Check sub-repos
    return all(
        check_repo_is_clean(repo.path, raise_error) for repo in load_repos(paths)
    )


def check_branch_existence(repo_path: Path, branch_name: str) -> Tuple[bool, bool]:
    try:
        repo = git.Repo(repo_path)
    except InvalidGitRepositoryError as e:
        logger.error("Failed to check if branch exists")
        raise GitError("Failed to check if branch exists") from e

    # Check if branch exists locally
    exists_locally = branch_name in [head.name for head in repo.heads]

    # Check if branch exists remotely
    try:
        remote_refs = [ref.name for ref in repo.remotes.origin.refs]
        exists_remotely = f"origin/{branch_name}" in remote_refs
    except Exception:
        logger.debug(
            f"Could not check remote branches in {repo_path}, assuming branch doesn't exist remotely"
        )
        exists_remotely = False

    return exists_locally, exists_remotely
