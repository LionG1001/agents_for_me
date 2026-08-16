# bastion-k8s MCP 配置示例

本目录提供部署 Skill 场景下的 `bastion-k8s-mcp` 配置示例。

本 Skill 快照不包含原始工程仓库中的 MCP 源码和 `package.yaml`。可从随包提供的 [`bastion-k8s.example.json`](bastion-k8s.example.json) 开始配置；如需修改或构建 MCP 服务端，请另行取得 `bastion-k8s-mcp` 源码工程。

## 使用方法

1. 复制 `bastion-k8s.example.json`（或索引中的 `mcp.example.json`）中的内容
2. 粘贴到你的 MCP 客户端配置文件中
3. 将占位符替换为实际值

> **Cursor 用户**：通常粘贴到 `~/.cursor/mcp.json` 或项目根目录的 `.cursor/mcp.json`

## 字段说明

| 字段 | 说明 | 示例 |
|---|---|---|
| `BASTION_HOST` | 可执行 `kubectl` 的跳板机（堡垒机）IP 或域名 | `10.121.120.7` |
| `BASTION_USER` | SSH 用户名 | `mccxadmin` |
| `BASTION_PASSWORD` | SSH 密码（或改用密钥） | （敏感信息，勿提交到 git） |
| `BASTION_PORT` | SSH 端口 | `22` |
| `ALLOWED_NAMESPACES` | 允许操作的命名空间列表（逗号分隔） | `his-test,prod` |

## 架构说明

```
本地 MCP 客户端
       ↓
   bastion-k8s-mcp (本地 npx 进程)
       ↓ SSH (密码/密钥)
   堡垒机 (BASTION_HOST)
       ↓ kubectl
   Kubernetes 集群
```

**关键点**：
- 本地机器 **不直接** 访问集群
- MCP 工具通过 SSH 登录堡垒机后，在堡垒机上执行 `kubectl` 命令
- 因此本地 `ssh` 到堡垒机可能因缺少公钥或 `BatchMode` 而失败，推荐始终通过 MCP 工具操作
- `ALLOWED_NAMESPACES` 用于限制 MCP 可操作的命名空间范围，提高安全性

## 安全提示

- 不要将真实密码提交到 git
- 生产环境建议改用 SSH 密钥认证（bastion-k8s-mcp 支持 `BASTION_KEY` 等配置）
- `ALLOWED_NAMESPACES` 建议只包含当前工作所需的命名空间
