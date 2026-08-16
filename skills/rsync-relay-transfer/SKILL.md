---
name: rsync-relay-transfer
description: Safely use the personal rsync relay documented in the SiYuan note `/公网中转`, primarily from remote Linux development environments, with dry-run defaults, path validation, and controlled credential handling. The Codex Skill is discovered locally, but rsync does not need to be installed on the user's Windows machine. Use when Codex needs to read the authoritative relay note, connect to a remote Linux host, list relay files, upload or download files, or troubleshoot the documented relay workflow.
---

# Rsync Relay Transfer

Treat the remote Linux development environment as the default execution target. Connect to the requested host or container first, verify `rsync` there, and run relay operations there. Do not install rsync on the local Windows machine solely for this Skill.

Keep the Skill installed in Codex's user Skill directory so Codex can discover the workflow; the remote Linux host does not need the Skill package installed.

## Read the authoritative note

Use the SiYuan MCP to read `/公网中转` (document ID `20260624174820-fd6m11n`) before operating. Treat its original upload, download, list commands, connection fields, and credential record as the source of truth. The user intentionally retains the credentials in that note; do not remove, sanitize, rotate, or rewrite them unless explicitly requested.

Use credentials only for the current authorized operation. Never reproduce them in chat, terminal logs, Skill files, Git content, commit messages, or pull requests.

## Configure credentials

Read the documented credential at execution time without echoing it. When a remote Linux task requires a password file, create a temporary or host-local file with mode `0600`, pass it through rsync's `--password-file`, and remove the temporary copy after the operation unless the user authorizes persistent storage on that host.

Use the bundled PowerShell scripts only for optional Windows-side configuration or execution. They are not required for the primary remote Linux workflow.

## Operate the relay

Use the three workflows recorded in the note: upload to the relay, download from the relay, and list relay files. On remote Linux, run native `rsync` on that host. Preserve the documented destination layout, add itemized output, and use `--dry-run` for upload and download. Never place the password in an environment dump or command argument.

Use `scripts/invoke-rsync-relay.ps1` only when Windows is explicitly selected as the execution host:

```powershell
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action check
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action list -RemotePath "folder"
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action upload -LocalPath "C:\data\file" -RemotePath "folder"
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action download -RemotePath "folder/file" -LocalPath "C:\downloads"
```

Treat upload and download as dry runs unless the user explicitly requests execution. After reviewing the itemized dry-run output, repeat with `-Execute`. Never add `--delete` unless the user explicitly requests deletion and the exact scope has been verified.

Use `list` for read-only connectivity tests. Report endpoints without embedded usernames and redact all secrets from diagnostics.

## Handle transport risk

Treat raw `rsync://` daemon traffic as unencrypted. Warn before transferring sensitive data over an untrusted network. Prefer WireGuard, Tailscale, another trusted VPN, or rsync over SSH when the relay is upgraded.
