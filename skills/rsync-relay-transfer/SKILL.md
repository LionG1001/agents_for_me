---
name: rsync-relay-transfer
description: Safely configure and use a personal rsync relay to list, upload, or download files with dry-run defaults, path validation, and local secret storage. Use when Codex needs to inspect a configured rsync relay, transfer files through it, migrate relay credentials out of notes or commands, or troubleshoot the user's rsync relay workflow.
---

# Rsync Relay Transfer

Use the bundled PowerShell scripts. Never reproduce, log, commit, or place relay passwords in commands, notes, Skill files, or chat responses.

## Configure credentials

Run `scripts/setup-relay-config.ps1` when configuration is absent or credentials must be rotated. Pass only non-secret connection fields as parameters and let the script prompt interactively for the password. Store configuration under `%USERPROFILE%\.config\rsync-relay-transfer\`; never copy that directory into a repository.

If migrating from a note, read the secret without echoing it, write it to the password file, restrict the file ACL to the current Windows identity, verify the configuration, and only then replace the note's plaintext secret with a reference to the local credential location. Do not claim migration succeeded until both the local verification and note rewrite succeed.

## Operate the relay

Run `scripts/invoke-rsync-relay.ps1`:

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
