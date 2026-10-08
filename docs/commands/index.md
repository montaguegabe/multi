# Commands Overview

Multi provides commands for managing your multi-repo workspace.

## Available Commands

| Command | Description |
|---------|-------------|
| [`add`](add.md) | Add a repository to an existing workspace |
| [`collaborator`](collaborator.md) | Add, accept, remove, and list recent GitHub collaborators across workspace repos |
| [`init`](init.md) | Initialize a new multi workspace |
| [`sync`](sync.md) | Sync configurations and repositories |
| [`sync github`](sync-github.md) | Sync root GitHub Actions workflows (monorepo mode) |
| [`branch check`](branch.md) | Check expected branch alignment (read-only, works with dirty trees) |
| [`set-branch`](set-branch.md) | Switch repos to their expected branches |
| [`worktree add`](worktree.md) | Create a git worktree in the sibling `<workspace>-worktrees` directory |
| [`git`](git.md) | Run git commands across all repos |
| [`hooks`](hooks.md) | Install and check workspace-level git hooks in every repo |
| [`doctor`](doctor.md) | Diagnose common workspace configuration issues |

## Global Options

All commands support:

- `--version` - Show version and exit
- `--verbose` - Enable detailed logging output

## Command Structure

```bash
multi [OPTIONS] COMMAND [ARGS]
```

### Examples

```bash
# Initialize a new workspace
multi init

# Add another repo to the workspace
multi add https://github.com/org/t-ide-cli

# Add a collaborator to every workspace repo
multi collaborator add octocat --yes

# Accept pending invitations for the authenticated GitHub user
multi collaborator accept --yes

# Choose a recent collaborator username
multi collaborator add --yes

# Sync all configurations
multi sync

# Check expected branch alignment (works with dirty trees)
multi branch check

# Switch to a feature branch
multi set-branch feature/new-feature

# Create an isolated worktree under <workspace>-worktrees/
multi worktree add new-feature --branch feature/new-feature

# Pull latest changes in all repos
multi git pull

# Check status across all repos
multi git status
```

## Getting Help

Get help for any command:

```bash
multi --help
multi sync --help
multi sync vscode --help
```
