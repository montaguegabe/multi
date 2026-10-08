# hooks

Manage workspace-level git hooks: one hooks directory at the workspace root governs the root repo and every sub-repo.

## Usage

```bash
multi hooks install
multi hooks status [--json]
multi hooks uninstall
```

## Configuration

Opt in with a `hooks` section in `multi.json`, pointing at a directory inside the workspace:

```json
{
  "hooks": { "path": ".githooks" },
  "repos": [...]
}
```

Put ordinary git hook scripts (`pre-commit`, `pre-push`, ...) in that directory and make them executable. Multi never writes hook content; it only points every repo at the directory.

## Behavior

- `multi sync`, `multi init` and `multi worktree add` install the hooks automatically, so fresh clones and new worktrees are covered without a separate step.
- The root repo gets the relative `core.hooksPath` (for example `.githooks`). Git resolves it against the working tree running the hook, and root worktrees share the root repo's config, so every worktree of the root uses the hooks from its own checkout.
- Each sub-repo gets the absolute path of the workspace hooks directory. Each workspace and each `multi worktree add` worktree clones its own sub-repos, so every one of them points at its own workspace's hooks. Ad-hoc `git worktree add` checkouts of a sub-repo outside the workspace still run the workspace hooks.
- Sub-repos symlinked from another workspace (`allowSymlinks`) are skipped; their owning workspace manages their hooks.
- Installing replaces any other `core.hooksPath` a sub-repo had, with a warning. To keep a repo's own hooks (for example a `pre-push` guard that ships with the repo for standalone clones), have the workspace hook chain to it.
- `.git/hooks/` of each repo is ignored once `core.hooksPath` is set; that is how git works.

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `install` | Set `core.hooksPath` in the root and every cloned sub-repo, then print the status. Exits 1 if anything is still not installed. |
| `status` | Show the hooks found and each repo's state: `installed`, `missing`, `mismatch`, `not-cloned` (outside the current install set) or `symlinked`. Exits 1 when a cloned repo is not installed, the directory is missing, or a hook is not executable. `--json` prints the same as JSON. |
| `uninstall` | Unset `core.hooksPath` wherever it points at the workspace hooks. Other values are left alone. |

`multi doctor` also warns when configured hooks are not installed. To see the raw values, run `multi git config --get core.hooksPath`.

## Bypassing a hook

Hooks are plain git hooks, so `git commit --no-verify` and `git push --no-verify` skip them. Workspaces can also document their own bypass variable inside their hook scripts.
