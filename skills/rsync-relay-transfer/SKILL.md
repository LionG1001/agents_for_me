---
name: rsync-relay-transfer
description: 安全使用思源笔记 `/公网中转` 中记录的个人 rsync 中转站，主要面向远程 Linux 开发环境，提供预演、路径校验和受控凭据处理。Skill 由本机 Codex 发现，但无需在 Windows 本机安装 rsync。用于读取权威中转站笔记、连接远程 Linux、查看中转站文件、上传或下载文件，以及排查中转站工作流。
---

# Rsync 中转站安全传输

默认在远程 Linux 开发环境中执行。先连接用户指定的主机或容器，确认工作目录并检查 `rsync`，再执行中转站操作。不要仅为使用本 Skill 而在 Windows 本机安装 rsync。

将 Skill 保留在 Codex 用户 Skill 目录中供 Codex 发现；远程 Linux 无需安装 Skill 包。

## 读取权威笔记

操作前通过思源 MCP 读取 `/公网中转`（文档 ID：`20260624174820-fd6m11n`）。以其中原有的上传、下载、文件列表命令、连接字段和凭据记录为准。用户明确要求在该笔记中保留凭据；除非再次明确要求，不得删除、脱敏、轮换或改写。

凭据仅用于当前已授权操作。不得将其回显到聊天、终端日志、Skill 文件、Git 内容、提交信息或 PR。

## 处理凭据

读取凭据时不得输出其内容。远程 Linux 需要密码文件时，创建权限为 `0600` 的临时文件或用户授权的主机本地文件，并通过 rsync 的 `--password-file` 使用。除非用户授权长期保存，否则操作结束后删除临时副本。

自带 PowerShell 脚本只用于用户明确选择 Windows 作为执行主机的场景，不是远程 Linux 工作流的前置条件。

## 执行中转操作

支持笔记中记录的三类工作流：上传到中转站、从中转站下载、查看中转站文件列表。在远程 Linux 上使用原生 `rsync`，保持笔记中记录的目标目录布局。上传和下载增加 `--itemize-changes` 并默认先执行 `--dry-run`。不得将密码放入命令参数或可被环境转储的长期变量。

只有明确选择 Windows 作为执行主机时，才使用 `scripts/invoke-rsync-relay.ps1`：

```powershell
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action check
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action list -RemotePath "folder"
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action upload -LocalPath "C:\data\file" -RemotePath "folder"
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action download -RemotePath "folder/file" -LocalPath "C:\downloads"
```

上传和下载默认只预演。检查逐项变更输出后，只有在用户要求实际执行且结果合理时才添加 `-Execute`。默认禁止 `--delete`；只有用户明确要求删除并核对精确作用范围后才允许使用。

使用 `list` 进行只读连通性测试。报告诊断信息时隐藏用户名、密码和完整认证头。

## 处理传输风险

将原生 `rsync://` daemon 流量视为未加密。通过不可信网络传输敏感数据前必须警告。后续优先迁移到 WireGuard、Tailscale、其他可信 VPN，或 rsync over SSH。
