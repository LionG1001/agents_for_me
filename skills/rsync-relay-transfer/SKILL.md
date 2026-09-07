---
name: rsync-relay-transfer
description: 安全使用思源笔记 `/公网中转` 中记录的个人 rsync 中转站，主要面向远程 Linux 开发环境，提供预演、路径校验和受控凭据处理。Skill 由本机 Codex 发现，但无需在 Windows 本机安装 rsync。用于读取权威中转站笔记、连接远程 Linux、查看中转站文件、上传或下载文件，以及排查中转站工作流。
---

# Rsync 中转站安全传输

默认在远程 Linux 开发环境中执行。先连接用户指定的主机或容器，确认工作目录并检查 `rsync`，再执行中转站操作。不要仅为使用本 Skill 而在 Windows 本机安装 rsync。

将 Skill 保留在 Codex 用户 Skill 目录中供 Codex 发现；远程 Linux 无需安装 Skill 包。

## 读取权威笔记

操作前通过思源 MCP 读取 `/公网中转`。以其中原有的上传、下载、文件列表命令、连接字段和凭据记录为准。笔记位置由用户配置或当前上下文提供；不要将历史文档 ID 视为所有安装环境的固定入口。读取笔记不授权修改笔记；按当前用户指令管理其中凭据。

凭据仅用于当前已授权操作。不得将其回显到聊天、终端日志、Skill 文件、Git 内容、提交信息或 PR。

## 处理凭据

读取凭据时不得输出其内容。远程 Linux 需要密码文件时，创建权限为 `0600` 的临时文件或用户授权的主机本地文件，并通过 rsync 的 `--password-file` 使用。除非用户授权长期保存，否则操作结束后删除临时副本。

Linux/macOS 使用自带 shell 脚本；PowerShell 脚本只用于用户明确选择 Windows 作为执行主机的场景。两者都不是远程 Linux 工作流的前置条件；如果操作已在目标 Linux 主机上，可直接使用原生 `rsync`。

## 执行中转操作

支持笔记中记录的三类工作流：上传到中转站、从中转站下载、查看中转站文件列表。在远程 Linux 上使用原生 `rsync`，保持笔记中记录的目标目录布局。上传和下载增加 `--itemize-changes` 并默认先执行 `--dry-run`。不得将密码放入命令参数或可被环境转储的长期变量。

用户已授权在执行主机长期保存凭据时，可通过安全交互提示创建本机配置（已有配置需复核后使用 `--replace`/`-Replace`；临时传输优先使用临时密码文件）：

```bash
<skill-root>/scripts/setup-relay-config.sh \
  --host <relay-host> \
  --port <port> \
  --module <module> \
  --user <user> \
  --base-path <optional-base-path>
```

然后使用 shell 版本执行：

```bash
<skill-root>/scripts/invoke-rsync-relay.sh check
<skill-root>/scripts/invoke-rsync-relay.sh list --remote-path "folder"
<skill-root>/scripts/invoke-rsync-relay.sh upload --local-path "/data/file" --remote-path "folder"
<skill-root>/scripts/invoke-rsync-relay.sh download --remote-path "folder/file" --local-path "/data/downloads"
```

只有明确选择 Windows 作为执行主机时，才使用 PowerShell 版本：

```powershell
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action check
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action list -RemotePath "folder"
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action upload -LocalPath "C:\data\file" -RemotePath "folder"
& "<skill-root>\scripts\invoke-rsync-relay.ps1" -Action download -RemotePath "folder/file" -LocalPath "C:\downloads"
```

上传和下载默认只预演。检查逐项变更输出后，只有在用户要求实际执行且结果合理时，bash 添加 `--execute`，PowerShell 添加 `-Execute`。默认禁止 `--delete`；只有用户明确要求删除并核对精确作用范围后才允许使用。

使用 `list` 进行只读连通性测试。报告诊断信息时隐藏用户名、密码和完整认证头。

## 处理传输风险

将原生 `rsync://` daemon 流量视为未加密。通过不可信网络传输敏感数据前必须警告。后续优先迁移到 WireGuard、Tailscale、其他可信 VPN，或 rsync over SSH。

上传目录时保留原生 rsync 尾部斜杠语义：`dir/` 复制内容，`dir` 复制目录本身。shell 版本要求 Bash 4+、Python 3 和 rsync；macOS 默认 Bash 3 不满足脚本要求，可直接采用同样经过预演的原生 rsync 命令。
