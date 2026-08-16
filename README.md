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

- [在 Codex 中连接思源笔记 MCP](docs/mcp/siyuan-codex.md)

### User Skills

- [User Skills 目录约定](skills/README.md)
- [Kubernetes 多机 GPU 部署](skills/k8s-multi-node-deploy/SKILL.md)
- [MUSA 分布式训练调试](skills/musa-distributed-debugging/SKILL.md)
- [MUSA 训练性能优化](skills/musa-training-optimization/SKILL.md)
- [中国差旅餐饮发票整理](skills/organize-invoices/SKILL.md)
- [发布 Agent Assets](skills/publish-agent-assets/SKILL.md)
- [远程容器工作区](skills/remote-container-workspace/SKILL.md)
- [Rsync 公网中转安全传输](skills/rsync-relay-transfer/SKILL.md)
