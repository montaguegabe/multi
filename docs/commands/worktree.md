# worktree add

Create an isolated Git worktree for a multi workspace.

## Usage

```bash
multi worktree add NAME [--branch BRANCH]
```

## Description

The `worktree add` command creates a Git worktree at `<parent>/<workspace-dirname>-worktrees/NAME`, a sibling `-worktrees` directory next to the current workspace root (created if missing). For example, running it from `~/code/my-workspace` creates `~/code/my-workspace-worktrees/NAME`. It then runs `multi sync` in the new worktree, checks sub-repos out to the worktree branch, and transfers configured gitignored local paths from the original workspace.

If `--branch` is omitted, `NAME` is used as the branch name.

## Arguments

| Argument | Description |
|----------|-------------|
| `NAME` | Directory name for the new worktree inside the `<workspace-dirname>-worktrees` sibling directory |

## Options

| Option | Description |
|--------|-------------|
| `--branch BRANCH` | Branch name for the worktree. Defaults to `NAME` |

## Behavior

1. Creates a root worktree on the target branch inside the `<workspace-dirname>-worktrees` sibling directory, creating that directory if needed.
2. Runs `multi sync` in the new worktree to populate sub-repos and generated config, which also installs the workspace hooks (see [`hooks`](hooks.md)) so every repo in the worktree runs them.
3. Checks sub-repos out to the target branch, except repos with `fixedBranch`.
4. Symlinks or copies configured gitignored paths from the original workspace.

Dirty working trees do not block this command: the worktree branches from a commit (`HEAD` or `--base-ref`) and the source working trees are never modified.

## Examples

### Use the worktree name as the branch

```bash
multi worktree add feature-user-auth
```

### Use a custom branch name

```bash
multi worktree add user-auth --branch feature/user-auth
```

### Transfer ignored local files

```json
{
  "worktree": {
    "symlink": [".env", ".venv"],
    "copy": [".cursor/local.json"]
  },
  "repos": [
    {
      "url": "https://github.com/org/shared",
      "fixedBranch": "main"
    }
  ]
}
```

## Requirements

- The command is not available in `monoRepo` mode.
- The destination directory must not already exist.
- Transfer paths must be relative, gitignored, and inside the workspace.
- Existing transfer destinations are skipped.
