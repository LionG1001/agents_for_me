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

Choose the script for the local platform and copy inputs into the repository's canonical layout.

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

Stop if validation reports missing `SKILL.md`, invalid frontmatter, name mismatches, unresolved relative Markdown links, TODO placeholders, symbolic links, or likely credentials. Inspect every finding rather than suppressing it broadly.

Also inspect `git status -sb`, the complete intended diff, and `git diff --check`. Stage explicit paths only.

## Publish safely

1. Verify `gh auth status` succeeds without printing a token.
2. Pull or fetch the remote state and confirm the intended base branch.
3. From the default branch, create `agent/<short-description>`.
4. Stage only the validated asset directories and index files.
5. Commit with a terse description.
6. Push with upstream tracking.
7. Open a draft pull request unless the user explicitly requests direct publication or a ready PR.
8. Report the branch, commit, validation result, and PR URL.

Never place GitHub credentials, API tokens, SSH private keys, passwords, or full authorization headers in repository files, commit messages, command arguments, or PR text. Keep GitHub authentication in `gh` and the operating-system credential store.

## Maintain indexes

Keep the root `README.md` links accurate. Store distributable Skill sources at `skills/<skill-name>/`; installation may copy them into the active user Skill directory. Keep MCP material under `docs/mcp/`.
