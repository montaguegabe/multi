# sync

Sync development environment and configurations.

## Usage

```bash
multi sync [--install-set NAME] [SUBCOMMAND]
```

## Description

The `sync` command ensures your workspace is up to date by cloning/updating repositories and merging configurations. Running `sync` without a subcommand performs a full sync.

## Full Sync

```bash
multi sync
```

A full sync performs all of the following:

1. Initializes root git repository if missing
2. Creates `README.md` if missing
3. Clones any missing repositories (standard mode only)
4. Installs workspace git hooks in the root and every sub-repo when `hooks.path` is configured (see [`hooks`](hooks.md))
5. Merges VS Code configurations (settings, launch, tasks, extensions)
6. Generates agent instruction files when `agentInstructions.enabled` is true
7. Syncs GitHub Actions workflows to root `.github/workflows` (monorepo mode only)

Fresh clone and symlink setup uses Multi's shared expected-branch invariant from `multi.git_helpers.expected_branch_for_repo`: repos with `fixedBranch` are checked out to that branch, and unlocked repos mirror the root workspace branch when branch mirroring is enabled.

## Install Sets

Use `--install-set NAME` or `--set NAME` to sync only repos whose `repos[].installSets` contains that name. This is useful for public installer workflows where a root workspace should clone and generate config only for public/runtime repos while private development repos remain excluded.

Repos without `installSets` are included in every selected set for backward compatibility. Running `multi sync` with no install set preserves the existing behavior and includes every repo.

## Subcommands

| Subcommand | Description |
|------------|-------------|
| [sync vscode](sync-vscode.md) | Merge VS Code configuration files |
| [sync agents](sync-agents.md) | Generate AGENTS.md and CLAUDE.md from AGENTS.parts/*.md |
| [sync github](sync-github.md) | Sync root GitHub Actions workflows for monorepo workspaces |

## Examples

```bash
# Full sync (recommended)
multi sync

# Public/runtime subset
multi sync --install-set default

# Equivalent shorter form
multi sync --set default

# Only sync VS Code configurations
multi sync vscode

# Only sync VS Code settings for the selected subset
multi sync --set default vscode settings

# Only sync VS Code settings
multi sync vscode settings

# Only sync generated agent instruction files
multi sync agents

# Only sync root GitHub Actions workflow files (monorepo mode)
multi sync github
```

## Notes

- The VS Code extension can automatically run `multi sync` when relevant files change
- Sync operations are idempotent - running them multiple times is safe
- Use `--verbose` to see detailed output during sync
- Use `--install-set` / `--set` before the subcommand name when filtering a partial sync, for example `multi sync --set default agents`
- `multi sync github` is available only when `monoRepo` is `true`
- Recommended automation path: create/edit `multi.json` and run `multi sync`
