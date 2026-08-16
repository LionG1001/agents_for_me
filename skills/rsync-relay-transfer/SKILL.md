---
name: rsync-relay-transfer
description: Safely configure and use a personal rsync relay primarily from remote Linux development environments, with dry-run defaults, path validation, and host-local secret storage. The Codex Skill is discovered locally, but rsync does not need to be installed on the user's Windows machine. Use when Codex needs to connect to a remote Linux host, inspect a configured relay, transfer files through it, migrate relay credentials out of notes or commands, or troubleshoot the relay workflow.
---

# Rsync Relay Transfer

Treat the remote Linux development environment as the default execution target. Connect to the requested host or container first, verify `rsync` there, and run relay operations there. Do not install rsync on the local Windows machine solely for this Skill.

Keep the Skill installed in Codex's user Skill directory so Codex can discover the workflow; the remote Linux host does not need the Skill package installed. Never reproduce, log, commit, or place relay passwords in commands, notes, Skill files, or chat responses.

## Configure credentials

Store credentials on the remote Linux host that performs the transfer. Use a host-local password file with mode `0600`, pass it through rsync's `--password-file`, and never copy it into a repository. Do not copy credentials to a remote host until the user identifies and authorizes that target.

Use the bundled PowerShell scripts only for optional Windows-side configuration or execution. They are not required for the primary remote Linux workflow.

If migrating from a note, read the secret without echoing it, write it only to the authorized execution host, restrict the password file to that host's user (`0600` on Linux or a user-only ACL on Windows), verify it, and only then replace the note's plaintext secret with a credential reference. Do not claim migration succeeded until both the host-local verification and note rewrite succeed.

## Operate the relay

On remote Linux, run native `rsync` on that host. Use `--password-file`, itemized output, and `--dry-run` for upload and download; never place the password in an environment dump or command argument.

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
