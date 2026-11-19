# Codex 用户级 MCP

以下为个人环境使用过的服务清单，并非六个可安装服务包。仓库提供思源 bridge 源码及 Atlassian/Bastion 的上游配置说明；`dingtalk-dws`、`huishan-cluster` 的分发入口尚待补齐（[Issue #17](https://github.com/LionG1001/agents_for_me/issues/17)）。`node_repl` 由 Codex 应用提供。服务可通过本机 stdio 或远程 HTTP 接入；按当前环境填写绝对路径。Windows 安装入口及平台范围见 [Windows 安装](../windows-install.md)。

| 注册名 | 启动方式 | 检查入口 |
| --- | --- | --- |
| `atlassian` | Python 虚拟环境中的 Jira / Confluence 启动器 | [Atlassian 配置](atlassian-codex.md)。分别做 Jira 和 Confluence 只读查询 |
| `bastion-k8s` | Node 运行预安装的 `bastion-k8s-mcp` | [Bastion 配置](../../skills/k8s-multi-node-deploy/mcp/README.md)。`bastion_check` 检查到堡垒机的 SSH 连接 |
| `dingtalk-dws` | 已安装的 `dingtalk-dws-mcp` 可执行文件 | `dingtalk_doctor` 分别报告本机 dws 登录和通知投递的就绪状态 |
| `huishan-cluster` | 本机 Python 启动器加载环境对应的访问策略 | `list_cluster_access` 查看当前身份可见的映射。`cluster_connection_status` 查看指定集群的连接状态 |
| `node_repl` | Codex 桌面环境提供的 `node_repl` 可执行文件 | 运行 `nodeRepl.write(2 + 2)` 并核对输出。运行时路径和浏览器集成变量由本机环境提供 |
| `siyuan` | Python stdio 转接至思源 Streamable HTTP | [思源配置](siyuan-codex.md)。通过 MCP 的 `system` 工具读取版本 |

## 盘点与验证

在 Linux 上可从 Codex 读取有效配置，再筛选为服务名和启用状态。清单也可能包含宿主提供的条目。

```bash
set -o pipefail
codex mcp list --json | python3 -c '
import json
import sys

for server in json.load(sys.stdin):
    state = "enabled" if server["enabled"] else "disabled"
    print(server["name"], state, sep="\t")
'
```

PowerShell 等价检查（不打印完整环境或凭据）：

```powershell
codex mcp list --json | ConvertFrom-Json | Select-Object name, enabled
```

配置启用后，在重新加载的会话里确认工具可发现，再按上表做只读检查。工具发现、上游鉴权与业务功能分别核验。堡垒机探测只覆盖本机到堡垒机的一跳。钉钉通知就绪情况以 `notify.ready` 为准。

共享配置时使用示例地址和路径。凭据通过本机凭据管理器、权限受限的文件或启动环境注入，按各服务配置转发需要的变量名。完整的 `config.toml`、`mcp list --json` 原始输出和连接日志可能包含凭据或环境细节。
