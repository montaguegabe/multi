"""Expose sub-repo Codex skills at the workspace root.

Codex discovers skills by walking *up* from the working directory: the
``.agents/skills`` folder of the current directory, of its parent, and of the
repository root. It never looks down into nested directories, so a session
started at the workspace root cannot see a skill that lives in a sub-repo.
``multi sync`` links every sub-repo ``.agents/skills/<name>`` into the root
``.agents/skills`` so Codex finds them from the workspace.

Claude Code is deliberately left alone: it already discovers nested
``.claude/skills`` directories below the start directory (lazily, when a file in
that subdirectory is first read or edited). Re-check both tools' discovery rules
now and then. If Codex gains downward discovery this module becomes redundant;
if Claude Code loses it, link ``.claude/skills`` the same way.

Links are relative so they survive moving the workspace or checking it out as
a worktree. A link is recognised as multi-managed by its shape (``../../`` into
a sub-repo's ``.agents/skills``); anything else at the root, such as a skill
checked into the workspace repo itself, is never touched.
"""

import logging
import os
from pathlib import Path

import click

from multi.cli_helpers import get_install_set_from_context
from multi.paths import Paths
from multi.repos import load_repos

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(".agents") / "skills"
SETTINGS_KEY = "skills"


def is_skills_sync_enabled(paths: Paths) -> bool:
    """Enabled unless ``multi.json`` has ``"skills": {"enabled": false}``."""
    settings = paths.settings.get(SETTINGS_KEY, {})
    if not isinstance(settings, dict):
        return True
    return bool(settings.get("enabled", True))


def _skill_dirs(skills_root: Path) -> list[Path]:
    """Skill directories (those holding a ``SKILL.md``) under ``skills_root``."""
    if not skills_root.is_dir():
        return []
    return sorted(
        (path for path in skills_root.iterdir() if (path / "SKILL.md").is_file()),
        key=lambda path: path.name,
    )


def is_managed_skill_link(path: Path) -> bool:
    """Whether ``path`` is a link ``multi`` created into a sub-repo's skills."""
    if not path.is_symlink():
        return False
    target = Path(os.readlink(path)).as_posix()
    return target.startswith("../../") and f"/{SKILLS_DIR.as_posix()}/" in target


def plan_skill_links(paths: Paths) -> dict[str, Path]:
    """Root link name → sub-repo skill directory, in ``multi.json`` order.

    The first repo to provide a name wins; later duplicates are reported and
    skipped because a skill's directory name must match the name declared in
    its ``SKILL.md``, so renaming the link is not an option.
    """
    links: dict[str, Path] = {}
    for repo in load_repos(paths=paths):
        for skill_dir in _skill_dirs(repo.path / SKILLS_DIR):
            existing = links.get(skill_dir.name)
            if existing is not None:
                logger.warning(
                    f"⚠️  Skill '{skill_dir.name}' in {repo.name} is shadowed by "
                    f"{existing}; rename one of them to expose both."
                )
                continue
            links[skill_dir.name] = skill_dir
    return links


def _can_manage(destination: Path) -> bool:
    return not (
        destination.exists() or destination.is_symlink()
    ) or is_managed_skill_link(destination)


def root_skill_link_entries(paths: Paths) -> list[str]:
    """``.gitignore`` entries for the links ``sync_all_skills`` will maintain."""
    if not is_skills_sync_enabled(paths):
        return []
    destination_dir = paths.root_dir / SKILLS_DIR
    return [
        f"/{SKILLS_DIR.as_posix()}/{name}"
        for name in plan_skill_links(paths)
        if _can_manage(destination_dir / name)
    ]


def sync_all_skills(root_dir: Path, install_set: str | None = None) -> None:
    """Link sub-repo ``.agents/skills`` entries into the root ``.agents/skills``."""
    paths = Paths(root_dir, install_set=install_set)
    if not is_skills_sync_enabled(paths):
        logger.debug("Skills sync is disabled")
        return

    destination_dir = paths.root_dir / SKILLS_DIR
    planned = plan_skill_links(paths)
    previously_managed = {
        path.name
        for path in (destination_dir.iterdir() if destination_dir.is_dir() else [])
        if is_managed_skill_link(path)
    }
    if not planned and not previously_managed:
        logger.debug("No sub-repo Codex skills to link")
        return

    logger.info("Linking sub-repo Codex skills into the workspace root...")
    destination_dir.mkdir(parents=True, exist_ok=True)

    written: set[str] = set()
    for name, source in planned.items():
        destination = destination_dir / name
        if not _can_manage(destination):
            logger.warning(
                f"⚠️  Not linking skill '{name}': the workspace has its own entry at "
                f"{destination.relative_to(paths.root_dir)}."
            )
            continue
        target = os.path.relpath(source, destination_dir)
        if destination.is_symlink() and os.readlink(destination) == target:
            written.add(name)
            continue
        if destination.is_symlink():
            destination.unlink()
        destination.symlink_to(target, target_is_directory=True)
        written.add(name)
        logger.info(f"✅ Linked skill: {name} -> {target}")

    for stale_name in sorted(previously_managed - written):
        (destination_dir / stale_name).unlink()
        logger.info(f"🗑️ Removed stale skill link: {stale_name}")

    logger.info("✅ Codex skills sync complete")


@click.command(name="skills")
def sync_skills_cmd() -> None:
    """Link sub-repo .agents/skills into the root so Codex discovers them."""
    sync_all_skills(root_dir=Path.cwd(), install_set=get_install_set_from_context())
