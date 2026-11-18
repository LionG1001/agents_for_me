# bastion-k8s MCP 配置示例

本目录提供 `bastion-k8s-mcp` 的 Codex 和 Cursor 配置示例。

## Codex

将以下片段加入本机 `config.toml`。将脚本路径替换为已安装的 `bastion-k8s-mcp` 入口，并填写实际的堡垒机地址、用户名和允许的命名空间。

```toml
[mcp_servers.bastion-k8s]
command = "node"
args = ["/absolute/path/to/bastion-k8s-mcp/dist/index.js"]
env_vars = ["BASTION_PASSWORD"]
startup_timeout_sec = 30
tool_timeout_sec = 90

[mcp_servers.bastion-k8s.env]
BASTION_HOST = "bastion.example.com"
BASTION_PORT = "22"
BASTION_USER = "<BASTION_USER>"
ALLOWED_NAMESPACES = "<NAMESPACE1>,<NAMESPACE2>"
```

使用密码时，从本机凭据管理器向 Codex 启动环境注入 `BASTION_PASSWORD`。使用 SSH 私钥时，移除密码变量的转发，并按已安装版本的说明设置 `BASTION_PRIVATE_KEY_PATH`。

重新加载配置并调用 `bastion_check` 核验本机到堡垒机的 SSH 连通性。

## Cursor

将 [JSON 示例](bastion-k8s.example.json) 中的 `bastion-k8s` 条目加入 `~/.cursor/mcp.json` 或项目根目录的 `.cursor/mcp.json`，并在本机填充所需字段。示例使用 `3.0.1`，对应本次盘点的已安装版本。

## 字段说明

| 字段 | 说明 | 示例 |
|---|---|---|
| `BASTION_HOST` | 可执行 `kubectl` 的堡垒机 IP 或域名 | `bastion.example.com` |
| `BASTION_USER` | SSH 用户名 | `<BASTION_USER>` |
| `BASTION_PASSWORD` | SSH 密码 | 由本机环境注入 |
| `BASTION_PRIVATE_KEY_PATH` | 私钥认证使用的绝对路径 | `/absolute/path/to/ssh-key` |
| `BASTION_PORT` | SSH 端口 | `22` |
| `ALLOWED_NAMESPACES` | 允许操作的命名空间列表（逗号分隔） | `<NAMESPACE1>,<NAMESPACE2>` |

## 架构说明

```
本地 MCP 客户端
       ↓
   bastion-k8s-mcp (本地 Node 进程)
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

- 公开仓库只保存示例。连接配置和凭据存放在本机。
- `ALLOWED_NAMESPACES` 只包含当前工作所需的命名空间。
