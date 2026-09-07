---
name: publish-agent-assets
description: Validate, organize, synchronize, and publish personal Codex Skills and MCP documentation to the agents_for_me GitHub repository. Use when the user asks to upload, back up, collect, update, review, or publish User Skills, SKILL.md packages, MCP setup guides, or related reusable agent assets.
---

# Publish Agent Assets

Publish reusable agent assets without exposing credentials or mixing system/plugin files into the personal repository.

## Scope assets

Classify each input before changing files:

- User Skill: a user-owned directory whose root contains `SKILL.md`.
- MCP document: a Markdown guide describing MCP setup, operation, or review.
- Exclude system Skills, plugin caches, generated logs, credentials, virtual environments, and repository metadata.

Treat `%USERPROFILE%\.codex\skills\.system`, `$HOME/.codex/skills/.system`, and plugin cache directories as out of scope unless the user explicitly requests third-party code vendoring.

## Synchronize assets

Both wrappers use `scripts/assets.py` (Python 3.10+; validation also requires PyYAML in that interpreter). PowerShell defaults to `python` and accepts `-PythonExecutable`; bash uses `python3`. Resolve dependencies in the authorized environment, without silently installing packages.

Inspect the destination checkout root, branch, HEAD, dirty paths and remote before copying; use an isolated worktree if needed. Choose the script for the local platform and copy inputs into the repository's canonical layout.

Linux/macOS with bash:

```bash
<skill-root>/scripts/sync-assets.sh \
  --type skill \
  --source <path-to-skill> \
  --repository-root <path-to-agents_for_me>
```

Windows with PowerShell:

```powershell
& "<skill-root>\scripts\sync-assets.ps1" `
  -Type Skill `
  -Source "<path-to-skill>" `
  -RepositoryRoot "<path-to-agents_for_me>"
```

Preview with `--dry-run` / `-DryRun` (`-WhatIf` is also supported). The shared implementation rejects source/destination symlinks and junctions, overlapping paths and credential filenames; it skips system/VCS/build/cache material. It supports normal checkouts and Git worktrees. Review destination-only files rather than deleting them automatically.

Pass repeated `--source` arguments in bash or multiple paths to `-Source` in PowerShell when collecting several Skills. Use `--update`/`-Update` only when the destination already exists and the user requested an update. The update mode overwrites matching files but does not delete destination-only files; review stale files manually.

For MCP documents, use `--type mcp-doc` in bash or `-Type McpDoc` in PowerShell. The scripts place them under `docs/mcp/`.

## Validate before Git operations

Run the platform-appropriate validator.

Linux/macOS with bash:

```bash
<skill-root>/scripts/validate-repository.sh <path-to-agents_for_me>
```

Windows with PowerShell:

```powershell
& "<skill-root>\scripts\validate-repository.ps1" `
  -RepositoryRoot "<path-to-agents_for_me>"
```

Stop if validation reports missing `SKILL.md`, invalid frontmatter, name mismatches, unresolved relative Markdown links, TODO placeholders, symbolic links, or likely credentials. The scanner checks UTF-8 files regardless of extension or size and reports binary assets for manual handling. Pattern checks cannot certify absence of every secret; review newly published scripts, examples and references as well. Inspect findings without printing matched secret values.

Also inspect `git status -sb`, the complete intended diff, and `git diff --check`. Stage explicit paths only.

## Publish safely

1. Verify `gh auth status` succeeds without retrieving or printing the token itself.
2. Fetch the verified target remote and confirm the default/intended base branch; preserve unrelated local work and commits.
3. Start `agent/<short-description>` from the verified remote base; reuse a suitable existing task branch when appropriate.
4. Stage only the validated asset directories and index files.
5. Commit with a terse description.
6. Push with upstream tracking.
7. For a review workflow, open a draft pull request. If the user requests direct publication, follow that authorized destination; do not add a new approval round. Repository permissions and user intent determine the flow.
8. Verify the remote branch SHA matches the local commit after push, then report branch, commit, validation limits and PR URL (if created). Synchronize approved improvements back to the active user skill installation and compare file hashes; preserve a rollback copy and avoid overwriting concurrent edits.

Never place GitHub credentials, API tokens, SSH private keys, passwords, or full authorization headers in repository files, commit messages, command arguments, or PR text. Keep GitHub authentication in `gh` and the operating-system credential store.

## Maintain indexes

Keep the root `README.md` links accurate. Store distributable Skill sources at `skills/<skill-name>/`; installation may copy them into the active user Skill directory. Keep MCP material under `docs/mcp/`.
