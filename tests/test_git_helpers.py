import json

import pytest
from click.testing import CliRunner

from multi.cli import main
from multi.errors import GitError
from multi.git_helpers import (
    check_all_on_same_branch,
    check_all_repos_are_clean,
    check_branch_existence,
    check_repo_is_clean,
    get_current_branch,
    is_git_repo_root,
)
from multi.paths import Paths


def test_is_git_repo_root(setup_git_repos):
    """Test is_git_repo_root returns True for git repos and False otherwise."""
    root_repo, sub_repos = setup_git_repos

    # Root repo should be a git repo
    assert is_git_repo_root(root_repo) is True

    # Sub repos should be git repos
    for sub_repo in sub_repos:
        assert is_git_repo_root(sub_repo) is True

    # A non-git directory should return False
    non_git_dir = root_repo / "not_a_repo"
    non_git_dir.mkdir(exist_ok=True)
    assert is_git_repo_root(non_git_dir) is False


def test_get_current_branch(setup_git_repos):
    """Test get_current_branch returns the correct branch name."""
    root_repo, sub_repos = setup_git_repos

    # All repos should be on 'main' branch after setup
    assert get_current_branch(root_repo) == "main"
    for sub_repo in sub_repos:
        assert get_current_branch(sub_repo) == "main"


def test_check_all_on_same_branch(setup_git_repos):
    """Test check_all_on_same_branch validates all repos are on the same branch."""
    root_repo, _ = setup_git_repos
    paths = Paths(root_repo)

    # All repos should be on the same branch after setup
    assert check_all_on_same_branch(paths) is True


def test_check_repo_is_clean(setup_git_repos):
    """Test check_repo_is_clean correctly detects clean and dirty repos."""
    root_repo, sub_repos = setup_git_repos

    # Repos should be clean after setup
    assert check_repo_is_clean(root_repo) is True
    assert check_repo_is_clean(sub_repos[0]) is True

    # Make a repo dirty by creating an untracked file
    dirty_file = sub_repos[0] / "dirty.txt"
    dirty_file.write_text("dirty")
    assert check_repo_is_clean(sub_repos[0], raise_error=False) is False


def test_check_all_repos_are_clean(setup_git_repos):
    """Test check_all_repos_are_clean validates all repos are clean."""
    root_repo, _ = setup_git_repos
    paths = Paths(root_repo)

    # All repos should be clean after setup
    assert check_all_repos_are_clean(paths) is True


def test_check_branch_existence(setup_git_repos_with_remotes):
    """Test check_branch_existence correctly detects local and remote branches."""
    root_repo, _ = setup_git_repos_with_remotes

    # 'main' branch should exist both locally and remotely
    exists_locally, exists_remotely = check_branch_existence(root_repo, "main")
    assert exists_locally is True
    assert exists_remotely is True

    # A non-existent branch should not exist
    exists_locally, exists_remotely = check_branch_existence(
        root_repo, "nonexistent-branch"
    )
    assert exists_locally is False
    assert exists_remotely is False


def test_get_current_branch_gives_actionable_message(tmp_path):
    """Test get_current_branch returns a useful error for non-git directories."""
    with pytest.raises(GitError) as exc_info:
        get_current_branch(tmp_path)

    message = str(exc_info.value)
    assert "Could not determine current branch" in message
    assert "multi sync" in message
    # The repo name alone identifies the repo; no absolute paths, and no
    # `git init` advice (that would create an unrelated empty repo).
    assert str(tmp_path) not in message
    assert "git init" not in message


def _add_repo_to_multi_json(root_repo, name):
    multi_json = root_repo / "multi.json"
    config = json.loads(multi_json.read_text())
    config["repos"].append({"url": f"https://example.invalid/{name}", "name": name})
    multi_json.write_text(json.dumps(config))


def test_multi_git_skips_repos_not_cloned_in_this_workspace(
    setup_git_repos, monkeypatch
):
    """A partial install set (public checkout) must not abort `multi git`."""
    root_repo, _ = setup_git_repos
    _add_repo_to_multi_json(root_repo, "internal-only")
    (root_repo / "empty-leftover").mkdir()
    _add_repo_to_multi_json(root_repo, "empty-leftover")
    monkeypatch.chdir(root_repo)

    assert check_all_on_same_branch(Paths(root_repo)) is True
    result = CliRunner().invoke(main, ["git", "status", "--short"])

    assert result.exit_code == 0, result.output
    assert "Could not determine current branch" not in result.output


def test_multi_git_still_fails_on_a_damaged_checkout(setup_git_repos):
    """A non-empty directory without git metadata is not silently skipped."""
    root_repo, _ = setup_git_repos
    damaged = root_repo / "damaged"
    damaged.mkdir()
    (damaged / "README.md").write_text("files but no .git")
    _add_repo_to_multi_json(root_repo, "damaged")

    with pytest.raises(GitError, match="Could not determine current branch"):
        check_all_on_same_branch(Paths(root_repo))
