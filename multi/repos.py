from pathlib import Path, PurePosixPath
from typing import Any, List

from multi.errors import NoRepositoriesError
from multi.paths import Paths


class Repository:
    """Represents a repository in the workspace.

    Attributes:
        url: The repository URL (optional in monorepo mode).
        name: Repository name derived from the URL, or provided directly.
        path: Local filesystem path where the repository is/will be cloned.
        skip: Whether to skip this repository for certain operations (default: False).
              Other attributes may be dynamically added from the config.
    """

    def __init__(self, paths: Paths, url: str | None = None, **kwargs: Any):
        """Initialize Repository, deriving name and path, and setting other attributes from kwargs."""
        self.url = url
        if self.url and self.url.endswith(".git"):
            raise ValueError(
                f"Repository URL must not end with '.git': {self.url}. "
                "Update multi.json and rerun `multi sync`."
            )
        # Derive name from URL or use provided name
        if "name" in kwargs:
            self.name = kwargs.pop("name")
        elif self.url:
            self.name = self.url.split("/")[-1]
        else:
            raise ValueError("Repository must have either 'url' or 'name'")
        self.paths = paths

        # Custom on-disk location, relative to the workspace root. Defaults to
        # the repo name (a flat layout). Allows repos to live under nested
        # directories, e.g. "path": "services/api".
        relative_path = kwargs.pop("path", None)
        if relative_path is None:
            self.relative_path = self.name
        else:
            if not isinstance(relative_path, str):
                raise ValueError(f"path for repository {self.name} must be a string.")
            raw = relative_path.strip()
            posix = PurePosixPath(raw)
            # Reject absolute paths and parent-directory escapes before
            # normalizing, so a leading '/' is an error rather than silently
            # stripped.
            if not raw or posix.is_absolute() or ".." in posix.parts:
                raise ValueError(
                    f"path for repository {self.name} must be a relative path "
                    "inside the workspace (no leading '/' and no '..')."
                )
            self.relative_path = posix.as_posix()
        self.path = self.paths.root_dir / Path(self.relative_path)

        # Set 'skip' attribute, defaulting to False if not provided in kwargs
        self.skip_vscode = kwargs.pop("skipVSCode", False)

        # Allow symlinking for this repo (default True, can be overridden per-repo)
        self.allow_symlink = kwargs.pop("allowSymlink", False)

        # Manage generated entries in this repo's .gitignore by default.
        self.manage_gitignore = kwargs.pop("manageGitignore", True)

        # Keep this repo on a fixed branch during branch synchronization.
        self.fixed_branch = kwargs.pop("fixedBranch", None)
        if self.fixed_branch is not None and not isinstance(self.fixed_branch, str):
            raise ValueError(
                f"fixedBranch for repository {self.name} must be a string."
            )

        install_sets = kwargs.pop("installSets", None)
        if install_sets is not None:
            if not isinstance(install_sets, list) or not all(
                isinstance(install_set, str) for install_set in install_sets
            ):
                raise ValueError(
                    f"installSets for repository {self.name} must be a list of strings."
                )
        self.install_sets = install_sets

        # Set any other attributes passed in kwargs (top-level keys from repo config)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __hash__(self) -> int:
        """Make Repository hashable based on its URL or name."""
        return hash(self.url or self.name)

    def __eq__(self, other: object) -> bool:
        """Make Repository equatable based on its URL or name."""
        if not isinstance(other, Repository):
            return NotImplemented
        if self.url and other.url:
            return self.url == other.url
        return self.name == other.name

    @property
    def is_python(self) -> bool:
        python_files = [
            "pyproject.toml",
            "requirements.txt",
            "Pipfile",
            "setup.py",
            "environment.yml",
            "setup.cfg",
        ]
        return any((self.path / file).exists() for file in python_files)

    @property
    def is_cloned(self) -> bool:
        """False only when the repo was never cloned into this workspace.

        A partial install set (for example a public checkout of a workspace
        whose multi.json also lists internal repos) leaves those paths absent.
        A non-empty directory without git metadata still counts as present, so
        a damaged checkout keeps failing loudly instead of being skipped.
        """
        if (self.path / ".git").exists():
            return True
        return self.path.is_dir() and any(self.path.iterdir())

    def matches_install_set(self, install_set: str | None) -> bool:
        if install_set is None:
            return True
        if self.install_sets is None:
            return True
        return install_set in self.install_sets


def load_repos(paths: Paths) -> List[Repository]:
    """Load repository information from the "repos" key in multi.json settings.

    Each repository config in the list should be an object. Example:
    {
        "repos": [
            {
                "url": "https://github.com/user/repo",
                "name": "repo", // Optional, defaults to the last part of the URL
                "skip": false, // Optional, defaults to false
                "custom_setting": "value" // Other top-level settings become attributes
            }
        ]
    }
    """
    repo_configs_list = paths.settings.get("repos", [])
    is_monorepo = paths.settings.is_monorepo()

    result = []
    for config_dict in repo_configs_list:
        if not isinstance(config_dict, dict):
            raise ValueError("Each repository config in multi.json must be an object.")

        # In monorepo mode, url is optional; name is required
        if "url" not in config_dict and "name" not in config_dict:
            raise ValueError(
                "Repository config in multi.json must contain 'url' or 'name' field."
            )

        if not is_monorepo and "url" not in config_dict:
            raise ValueError(
                "Repository config must contain 'url' field (or enable monoRepo mode)."
            )

        # Directly pass the config_dict; __init__ will handle parsing.
        repo = Repository(**config_dict, paths=paths)
        if repo.matches_install_set(paths.install_set):
            result.append(repo)

    if not result:
        if paths.install_set is not None:
            raise NoRepositoriesError(
                f"No repositories found for install set '{paths.install_set}'."
            )
        raise NoRepositoriesError("No repositories found in multi.json settings.")

    return result


def load_cloned_repos(paths: Paths) -> List[Repository]:
    """Like load_repos, minus repos that are not cloned in this workspace."""
    return [repo for repo in load_repos(paths) if repo.is_cloned]
