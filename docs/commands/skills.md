# skills

Install the Multi agent skills for Codex and Claude Code.

## Usage

```bash
multi skills install                 # copy the published skills with npx skills add
multi skills install --dev           # symlink a local multi-skills checkout
multi skills install --dev --source ~/path/to/multi-skills
multi skills install --skill multi-workspace
```

## Behavior

- Without `--dev`, the command runs `npx skills add montaguegabe/multi-skills --skill <name> -g -a codex -a claude-code -y` for each published skill. This is the install for people who use Multi but do not edit its skills.
- With `--dev`, the command finds the `multi-skills` checkout and runs its `scripts/install-dev.sh`. That script symlinks each skill into `~/.agents/skills` (read by Codex) and adds a relative link in `~/.claude/skills` (read by Claude Code), so edits to the checkout are live immediately. The symlink logic lives in the skills repo, which gets it from the BoilerSync `skills` template.
- The checkout is found by looking for a `multi-skills` directory next to the current directory or any parent (the workspace layout), then next to the CLI's own source checkout. Pass `--source` to point at it directly.
- `--skill` narrows either mode to the named skills. It is repeatable.

## Rationale

A copied skill drifts from its source the moment the source is edited. Linking is the right install for a skills repo you develop; copying is the right install for one you only consume.
