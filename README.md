# multi

`multi` is a better way to work with VS Code/Cursor on multiple Git repos at once. It is an alternative to [multi-root workspaces](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces) that offers more flexibility and control. With `multi`, you can gain control over how tasks, debug runnables, and various IDE and linter settings are combined from multiple project repos ("sub-repos") located within a root workspace folder.

**[Documentation](https://multi.bighelp.ai/)**

Features:

- Generates files in your root `.vscode` folder from sub-repo `launch.json`, `tasks.json`, and `settings.json` files.
- Supports optional `installSets` so installer scripts can sync only a public/runtime subset of repos.
- Optionally generates `CLAUDE.md` and `AGENTS.md` files from tracked `AGENTS.parts/*.md` files.
- In monorepo mode, syncs sub-repo GitHub workflows into root `.github/workflows`.
- Generates a root `AGENTS.override.md` for Codex that repeats the root `AGENTS.md` and appends every sub-repo's `AGENTS.md`, because Codex reads one instruction file per directory and never looks into sub-repos. The root `AGENTS.md` is never modified, and an override multi did not write is left alone with a warning. Claude Code ignores the override and discovers nested instruction files itself. Disable with `"codexOverride": {"enabled": false}`.
- Links sub-repo `.agents/skills` into the root `.agents/skills` so Codex, which only searches upward from the working directory, discovers them from the workspace. Claude Code already finds nested `.claude/skills` on its own, so those are left in place. Disable with `"skills": {"enabled": false}` in `multi.json`.
- Pairs with Multi Desktop for workspace diffs, branch visibility, and actionable push diagnostics.

## Installation

### Using `pipx`:

- Install [pipx](https://github.com/pypa/pipx)
- Run `pipx install multi-workspace`

### Using `uv`

- Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Run `uv tool install multi-workspace`

## Getting started

To get started, create a new workspace directory that will house all your related repos and run:

```
multi init
```

When prompted, paste in the URLs of all the repositories you want to have in your workspace. You can optionally specify descriptions of what they do, which can be included in generated agent instruction files when that feature is enabled.

For scripts, you can also initialize non-interactively:

```bash
multi init \
  --repo https://github.com/org/backend \
  --repo-description "Backend API" \
  --repo https://github.com/org/frontend \
  --repo-description "Frontend app"
```

To create GitHub repositories first, add `--github-repo` entries. This uses `gh repo create` and defaults to private visibility:

```bash
multi init \
  --github-repo org/backend \
  --github-description "Backend API" \
  --github-repo org/frontend \
  --github-description "Frontend app"
```

For `--github-repo`, the GitHub CLI (`gh`) must already be installed and authenticated.

When repository slugs are product-prefixed, `multi init` automatically writes short local directory names into `multi.json` when the slug matches the workspace name prefix. For example, in a `t-ide/` workspace, `t-ide-cli` becomes local folder `cli`.

The same naming rule applies to `multi add`, so adding `https://github.com/org/t-ide-cli` inside a `t-ide/` workspace will also default to local folder `cli`.

For public installer workflows, add `installSets` to repo entries and run a filtered sync:

```json
{
  "repos": [
    { "name": "cli", "url": "https://github.com/org/product-cli", "installSets": ["default", "dev"] },
    { "name": "ios", "url": "git@github.com:org/product-ios.git", "installSets": ["dev"] }
  ]
}
```

```bash
multi sync --install-set default
```

Running `multi sync` without `--install-set` still includes every repo. Repos without `installSets` are included in every named set.

To grant or remove GitHub collaborator access across every GitHub repo in a workspace, use:

```bash
multi collaborator add octocat --permission maintain --yes
multi collaborator add --yes
multi collaborator accept --yes
multi collaborator remove octocat --yes
multi collaborator recent-users
```

When the workspace root repository has a GitHub `origin`, `multi collaborator` applies the change there too.

The invited collaborator can run `multi collaborator accept --yes` with their own `gh` authentication to accept pending invitations for the workspace repos.

Recent collaborator usernames are saved under `~/.multi`, and `multi collaborator add` can prompt from that list when no username is supplied.

If one repo fails, `multi collaborator` continues through the rest of the workspace and reports the failures at the end.

It is recommended you also install the [VS Code Extension](https://marketplace.visualstudio.com/items?itemName=montaguegabe.multi-workspace) that automatically keeps your project synced when edits are made to synced files. To manually sync, you can run `multi sync`.
