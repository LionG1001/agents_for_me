# agents_for_me

个人 Agent、MCP 配置与 User Skills 集合。

## 目录结构

```text
agents_for_me/
├── docs/
│   └── mcp/              # MCP 配置、部署与安全 Review
└── skills/
    └── <skill-name>/     # 每个 User Skill 一个独立目录
        └── SKILL.md
```

## 内容索引

### MCP

- [Codex 用户级 MCP 配置与验证索引](docs/mcp/README.md)
- [在 Codex 中连接思源笔记 MCP：stdio 转接与 HTTP 配置](docs/mcp/siyuan-codex.md)
- [Atlassian MCP：Codex 连接内网 Jira 与 Confluence](docs/mcp/atlassian-codex.md)

### User Skills

- [User Skills 目录约定](skills/README.md)
- [Kubernetes 多机 GPU 部署](skills/k8s-multi-node-deploy/SKILL.md)
- [本地 Git 与远端执行验证](skills/local-remote-workflow/SKILL.md)
- [多集群访问](skills/multi-cluster-access/SKILL.md)
- [MUSA 分布式训练调试](skills/musa-distributed-debugging/SKILL.md)
- [MUSA 训练性能优化](skills/musa-training-optimization/SKILL.md)
- [中国差旅餐饮发票整理](skills/organize-invoices/SKILL.md)
- [发布 Agent Assets](skills/publish-agent-assets/SKILL.md)
- [训练项目交付、Jira结果/附件/工时与评测移交](skills/training-project-delivery/SKILL.md)
- [远程容器工作区](skills/remote-container-workspace/SKILL.md)
- [Rsync 公网中转安全传输](skills/rsync-relay-transfer/SKILL.md)

## 维护与验证

- [Windows 安装、平台边界与验证](docs/windows-install.md)：全部 10 个 Skill 的安装入口和 6 项 MCP 的就绪条件。
- Windows 安装预览：`./scripts/install-skills.ps1 -Update -WhatIf`；审查后去掉 `-WhatIf`，已有版本自动保留回滚副本。
- Windows MCP 运行环境：`./scripts/prepare-mcp.ps1`。服务地址和凭据按文档单独配置，保留已有可用连接。
- 离线回归：Linux 使用 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`；PowerShell 使用 `$env:PYTHONDONTWRITEBYTECODE='1'; python -X utf8 -m unittest discover -s tests -v`。
- 仓库验证：Linux 使用 `bash skills/publish-agent-assets/scripts/validate-repository.sh .`；PowerShell 使用 `./skills/publish-agent-assets/scripts/validate-repository.ps1 -RepositoryRoot .`（Python 3.10+、PyYAML）。
- CI 在 Windows 和 Ubuntu 分别执行离线回归；Windows 明确跳过 Linux shell/VPN 行为测试，Linux 跳过原生 Windows ACL 测试。
