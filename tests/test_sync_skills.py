import json
import logging
import os
from pathlib import Path

from multi.ignore_files import update_gitignore_with_generated_files
from multi.paths import Paths
from multi.sync_skills import sync_all_skills

ROOT_SKILLS = Path(".agents") / "skills"


def _write_workspace(workspace: Path, *repo_names: str, skills_setting=None) -> None:
    multi_json: dict = {
        "monoRepo": True,
        "repos": [{"name": name} for name in repo_names],
    }
    if skills_setting is not None:
        multi_json["skills"] = skills_setting
    (workspace / "multi.json").write_text(json.dumps(multi_json, indent=2))


def _add_skill(workspace: Path, repo_name: str, skill_name: str) -> Path:
    skill_dir = workspace / repo_name / ROOT_SKILLS / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_name}\n---\n")
    return skill_dir


def test_links_sub_repo_skills_relatively(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    _add_skill(workspace, "api", "deploy")
    # A folder without SKILL.md is not a skill.
    (workspace / "api" / ROOT_SKILLS / "notes").mkdir()

    sync_all_skills(root_dir=workspace)

    link = workspace / ROOT_SKILLS / "deploy"
    assert link.is_symlink()
    assert os.readlink(link) == "../../api/.agents/skills/deploy"
    assert (link / "SKILL.md").is_file()
    assert not (workspace / ROOT_SKILLS / "notes").exists()


def test_removes_links_for_skills_that_disappeared(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    skill_dir = _add_skill(workspace, "api", "deploy")
    sync_all_skills(root_dir=workspace)
    assert (workspace / ROOT_SKILLS / "deploy").is_symlink()

    (skill_dir / "SKILL.md").unlink()
    sync_all_skills(root_dir=workspace)

    assert not (workspace / ROOT_SKILLS / "deploy").is_symlink()


def test_leaves_the_workspaces_own_skill_alone_and_warns(tmp_path, caplog):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    _add_skill(workspace, "api", "deploy")
    own_skill = workspace / ROOT_SKILLS / "deploy"
    own_skill.mkdir(parents=True)
    (own_skill / "SKILL.md").write_text("root's own\n")

    with caplog.at_level(logging.WARNING):
        sync_all_skills(root_dir=workspace)

    assert not own_skill.is_symlink()
    assert (own_skill / "SKILL.md").read_text() == "root's own\n"
    assert any("workspace has its own entry" in message for message in caplog.messages)


def test_first_repo_wins_on_duplicate_names(tmp_path, caplog):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api", "web")
    _add_skill(workspace, "api", "deploy")
    _add_skill(workspace, "web", "deploy")

    with caplog.at_level(logging.WARNING):
        sync_all_skills(root_dir=workspace)

    assert (
        os.readlink(workspace / ROOT_SKILLS / "deploy")
        == "../../api/.agents/skills/deploy"
    )
    assert any("shadowed" in message for message in caplog.messages)


def test_disabled_setting_creates_nothing(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api", skills_setting={"enabled": False})
    _add_skill(workspace, "api", "deploy")

    sync_all_skills(root_dir=workspace)

    assert not (workspace / ".agents").exists()


def test_links_are_listed_in_the_generated_files_block(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_workspace(workspace, "api")
    _add_skill(workspace, "api", "deploy")

    update_gitignore_with_generated_files(paths=Paths(workspace))

    assert (
        "/.agents/skills/deploy" in (workspace / ".gitignore").read_text().splitlines()
    )
