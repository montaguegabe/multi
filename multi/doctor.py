import json
import logging
import subprocess
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path

import click
import git as gitmodule

from multi.errors import NoRepositoriesError
from multi.git_helpers import is_git_repo_root
from multi.hooks import PROBLEM_STATES, configured_hooks_path, hooks_status
from multi.paths import Paths
from multi.repos import Repository, load_repos

logger = logging.getLogger(__name__)

REMOTE_CHECK_TIMEOUT_SECONDS = 10


@dataclass
class DoctorReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)

    def should_fail(self, strict: bool) -> bool:
        return bool(self.errors or (strict and self.warnings))

    def to_dict(self) -> dict:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos,
        }


def find_nested_git_repos_in_monorepo(paths: Paths) -> list[str]:
    if not paths.settings.is_monorepo():
        return []

    try:
        repos = load_repos(paths)
    except (NoRepositoriesError, ValueError):
        return []

    return sorted(repo.name for repo in repos if (repo.path / ".git").exists())


def find_git_repos_on_disk(root_dir: Path) -> set[str]:
    """Find immediate subdirectories of root_dir that are git repositories."""
    result = set()
    try:
        for child in root_dir.iterdir():
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and (child / ".git").is_dir()
            ):
                result.add(child.name)
    except OSError:
        pass
    return result


def find_tracked_subrepos(root_dir: Path, repos: list[Repository]) -> list[str]:
    """Find sub-repos that have files tracked in the workspace git index."""
    try:
        root_repo = gitmodule.Repo(root_dir)
    except (gitmodule.InvalidGitRepositoryError, gitmodule.NoSuchPathError):
        return []

    tracked_prefixes = set()
    for entry in root_repo.index.entries:
        # entry key is (path, stage); check if path starts with a repo name
        path = entry[0]
        for repo in repos:
            # Submodule entries (mode 160000) are handled separately
            if path == repo.name or path.startswith(repo.name + "/"):
                blob = root_repo.index.entries[entry]
                if blob.mode != 0o160000:  # not a submodule
                    tracked_prefixes.add(repo.name)
                break

    return sorted(tracked_prefixes)


def find_subrepo_submodules(root_dir: Path, repos: list[Repository]) -> list[str]:
    """Find sub-repos registered as git submodules in the workspace."""
    try:
        root_repo = gitmodule.Repo(root_dir)
    except (gitmodule.InvalidGitRepositoryError, gitmodule.NoSuchPathError):
        return []

    submodule_paths = {sm.path for sm in root_repo.submodules}
    return sorted(repo.name for repo in repos if repo.name in submodule_paths)


def validate_repo_remote(url: str) -> str | None:
    """Return None when a remote is reachable, otherwise a short failure detail."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", url],
            capture_output=True,
            text=True,
            timeout=REMOTE_CHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError as exc:
        return f"could not run git ls-remote: {exc}"
    except subprocess.TimeoutExpired:
        return f"timed out after {REMOTE_CHECK_TIMEOUT_SECONDS}s"

    if result.returncode == 0:
        return None

    output = result.stderr.strip() or result.stdout.strip()
    if output:
        return output.splitlines()[0]
    return f"git ls-remote exited with status {result.returncode}"


def warn_if_root_git_missing(report: DoctorReport, paths: Paths) -> None:
    if not is_git_repo_root(paths.root_dir):
        report.warnings.append(
            f"Workspace root is not a git repository at {paths.root_dir}. "
            "Run `multi sync` (or `git init -b main`) to initialize it."
        )


def check_mode_specific_repo_requirements(
    report: DoctorReport, paths: Paths, repos: list[Repository]
) -> None:
    if paths.settings.is_monorepo():
        nested_git_repos = find_nested_git_repos_in_monorepo(paths)
        if nested_git_repos:
            report.warnings.append(
                "monoRepo mode expects listed directories to be part of the root git repo "
                f"(no nested .git). Found nested git repos: {', '.join(nested_git_repos)}. "
                "Use standard multi-repo mode (monoRepo: false) for independent repos."
            )
        return

    missing_url_names = [repo.name for repo in repos if not repo.url]
    if missing_url_names:
        report.errors.append(
            "These repos are missing `url` and cannot be managed in standard mode: "
            f"{', '.join(missing_url_names)}."
        )


def warn_on_missing_descriptions(
    report: DoctorReport, repos: list[Repository]
) -> None:
    missing_descriptions = sorted(
        repo.name
        for repo in repos
        if not (
            isinstance(description := getattr(repo, "description", None), str)
            and description.strip()
        )
    )
    if missing_descriptions:
        report.warnings.append(
            "Repos declared in multi.json are missing a non-empty `description`: "
            f"{', '.join(missing_descriptions)}. "
            "Add descriptions so generated workspace context and diagnostics stay useful."
        )


def warn_on_unreachable_remotes(report: DoctorReport, repos: list[Repository]) -> None:
    unreachable_remotes = []
    for repo in repos:
        if not repo.url:
            continue
        remote_error = validate_repo_remote(repo.url)
        if remote_error:
            unreachable_remotes.append(f"{repo.name} ({remote_error})")
    if unreachable_remotes:
        report.warnings.append(
            "Repos declared in multi.json have unreachable remotes: "
            f"{', '.join(unreachable_remotes)}. "
            "Verify the URL, network access, and credentials."
        )


def warn_on_tracked_subrepos(
    report: DoctorReport, paths: Paths, repos: list[Repository]
) -> None:
    if not is_git_repo_root(paths.root_dir) or paths.settings.is_monorepo():
        return

    tracked = find_tracked_subrepos(paths.root_dir, repos)
    if tracked:
        report.warnings.append(
            "Sub-repos are tracked in the workspace git index "
            "(they should be .gitignored): "
            f"{', '.join(tracked)}. "
            "Add them to .gitignore and remove from the index with "
            "`git rm -r --cached <repo>`."
        )


def warn_on_subrepo_submodules(
    report: DoctorReport, paths: Paths, repos: list[Repository]
) -> None:
    if not is_git_repo_root(paths.root_dir):
        return

    as_submodules = find_subrepo_submodules(paths.root_dir, repos)
    if as_submodules:
        report.warnings.append(
            "Sub-repos are registered as git submodules "
            "(multi does not use submodules): "
            f"{', '.join(as_submodules)}. "
            "Remove them with `git rm --cached <repo>` and delete "
            "the entry from .gitmodules."
        )


def warn_on_repo_disk_mismatches(
    report: DoctorReport, paths: Paths, repos: list[Repository]
) -> None:
    declared_names = {repo.name for repo in repos}
    if paths.settings.is_monorepo():
        on_disk_git_repos = find_git_repos_on_disk(paths.root_dir)
        undeclared = sorted(on_disk_git_repos - declared_names)
        if undeclared:
            report.warnings.append(
                "Git repos found on disk but not declared in multi.json: "
                f"{', '.join(undeclared)}. Add them to multi.json or remove them."
            )

        missing_on_disk = sorted(
            repo.name for repo in repos if not repo.path.is_dir()
        )
        if missing_on_disk:
            report.warnings.append(
                "Repos declared in multi.json but not found on disk: "
                f"{', '.join(missing_on_disk)}. In monoRepo mode, create these "
                "directories in the workspace."
            )
        return

    on_disk = find_git_repos_on_disk(paths.root_dir)
    undeclared = sorted(on_disk - declared_names)
    if undeclared:
        report.warnings.append(
            "Git repos found on disk but not declared in multi.json: "
            f"{', '.join(undeclared)}. Add them to multi.json or remove them."
        )

    missing_on_disk = sorted(declared_names - on_disk)
    if missing_on_disk:
        report.warnings.append(
            "Repos declared in multi.json but not found on disk: "
            f"{', '.join(missing_on_disk)}. Run `multi sync` to clone them."
        )


def warn_on_uninstalled_hooks(report: DoctorReport, paths: Paths) -> None:
    try:
        if configured_hooks_path(paths) is None:
            return
    except ValueError as exc:
        report.errors.append(str(exc))
        return

    status = hooks_status(paths)
    if not status.hooks_dir_exists:
        report.warnings.append(
            f"Workspace hooks directory {status.hooks_dir} does not exist; "
            "git runs no hooks."
        )
    if status.non_executable:
        report.warnings.append(
            "Workspace hooks are not executable (git skips them): "
            f"{', '.join(status.non_executable)}. Run `chmod +x` on them."
        )
    uninstalled = [repo.path for repo in status.repos if repo.state in PROBLEM_STATES]
    if uninstalled:
        report.warnings.append(
            "Workspace hooks are not installed in: "
            f"{', '.join(uninstalled)}. Run `multi hooks install`."
        )


def run_doctor_checks(target_dir: Path) -> DoctorReport:
    report = DoctorReport()

    try:
        paths = Paths(target_dir)
    except FileNotFoundError:
        report.errors.append(
            "Could not find multi.json in this directory or parent directories."
        )
        return report

    report.infos.append(f"Found multi.json at {paths.multi_json_path}")

    try:
        # Access once to validate parseability.
        _ = paths.settings
    except (AssertionError, JSONDecodeError, OSError) as exc:
        report.errors.append(f"Could not parse multi.json: {exc}")
        return report

    warn_if_root_git_missing(report, paths)

    try:
        repos = load_repos(paths)
    except (NoRepositoriesError, ValueError) as exc:
        report.errors.append(str(exc))
        return report

    check_mode_specific_repo_requirements(report, paths, repos)
    warn_on_missing_descriptions(report, repos)
    warn_on_unreachable_remotes(report, repos)
    warn_on_tracked_subrepos(report, paths, repos)
    warn_on_subrepo_submodules(report, paths, repos)
    warn_on_repo_disk_mismatches(report, paths, repos)
    warn_on_uninstalled_hooks(report, paths)

    return report


def run_doctor_fixes(target_dir: Path) -> list[str]:
    """Apply safe doctor fixes and return the names of repos that were fixed."""
    paths = Paths(target_dir)
    if not is_git_repo_root(paths.root_dir):
        return []

    if paths.settings.is_monorepo():
        return []

    repos = load_repos(paths)
    tracked = find_tracked_subrepos(paths.root_dir, repos)
    if not tracked:
        return []

    root_repo = gitmodule.Repo(paths.root_dir)
    root_repo.git.rm("-r", "--cached", "--", *tracked)
    return tracked


def _print_report(report: DoctorReport) -> None:
    logger.info("Running diagnostics...")
    for info in report.infos:
        logger.info(info)
    for warning in report.warnings:
        logger.warning(warning)
    for error in report.errors:
        logger.error(error)

    if not (report.errors or report.warnings):
        logger.info("✅ No issues found.")


@click.command(name="doctor")
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Fail on warnings in addition to errors.",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output results as JSON.",
)
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Automatically apply safe fixes for tracked sub-repos in the root index.",
)
def doctor_cmd(strict: bool, output_json: bool, fix: bool) -> None:
    """Diagnose common workspace configuration issues."""
    target_dir = Path.cwd()
    report = run_doctor_checks(target_dir)

    if fix and not report.errors:
        fixed_subrepos = run_doctor_fixes(target_dir)
        if fixed_subrepos:
            report = run_doctor_checks(target_dir)
            report.infos.append(
                "Applied --fix: removed tracked sub-repos from the root git index: "
                f"{', '.join(fixed_subrepos)}."
            )
        else:
            report.infos.append(
                "No tracked sub-repos were found in the root git index to fix."
            )

    if output_json:
        click.echo(json.dumps(report.to_dict()))
    else:
        _print_report(report)
    if report.should_fail(strict=strict):
        raise click.ClickException("Doctor checks failed.")
