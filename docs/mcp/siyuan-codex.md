# 思源笔记 MCP：Codex 连接与安全配置

本文记录当前已经验证可用的方案：通过华硕路由器的 DDNS 和端口映射，以 Streamable HTTP 方式让 Codex 连接家中思源笔记的 MCP 服务。

> 当前方案使用公网 HTTP。它可以工作，但请求头中的 API Token 和传输内容没有 TLS 加密，不建议作为长期方案。后续应改为带有效域名证书的 HTTPS 反向代理。

## 当前拓扑

```text
Codex
  -> http://cobwebs.asuscomm.com:60106/mcp
  -> 华硕路由器 DDNS + TCP 60106 端口映射
  -> 局域网设备上的思源服务（本例为 192.168.50.166:6806）
```

该地址不是“仅局域网生效”：只要公网可以访问映射端口，知道地址和凭据的客户端就能访问它。

## 1. 保存 API Token

不要把 Token 直接写入 `config.toml` 或提交到 Git 仓库。Windows PowerShell 中可将完整的 `Authorization` 请求头值保存为当前用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable(
    "SIYUAN_MCP_AUTHORIZATION",
    "token <YOUR_SIYUAN_API_TOKEN>",
    "User"
)
```

设置后需要完全退出并重新启动 Codex，现有进程不会自动获得新的用户环境变量。

如果使用 Clash 等系统代理，建议让此 DDNS 域名直连，同时保留已有的 `NO_PROXY` 内容：

```powershell
$siyuanNoProxyHost = "cobwebs.asuscomm.com"
$existingNoProxy = [Environment]::GetEnvironmentVariable("NO_PROXY", "User")
$noProxyEntries = @($existingNoProxy -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })

if ($siyuanNoProxyHost -notin $noProxyEntries) {
    $noProxyEntries += $siyuanNoProxyHost
}

[Environment]::SetEnvironmentVariable(
    "NO_PROXY",
    ($noProxyEntries -join ","),
    "User"
)
```

若特定代理软件仍然拦截该域名，可额外在代理软件的直连规则中加入域名。DDNS 对应的公网 IP 可能变化，不建议在文档或长期配置中写死 IP。

## 2. 配置 Codex

编辑用户配置文件 `%USERPROFILE%\.codex\config.toml`，加入：

```toml
[mcp_servers.siyuan]
url = "http://cobwebs.asuscomm.com:60106/mcp"
env_http_headers = { Authorization = "SIYUAN_MCP_AUTHORIZATION" }
http_headers = { Host = "127.0.0.1:6806" }
enabled = true
required = false
default_tools_approval_mode = "writes"
startup_timeout_sec = 30
tool_timeout_sec = 60
```

配置说明：

- `env_http_headers` 从环境变量读取认证头，避免明文 Token 进入配置文件。
- `Host = "127.0.0.1:6806"` 用于规避思源对外部 DDNS Host 的校验错误 `invalid Host header`。这是当前端口映射方案需要的兼容设置。
- `required = false` 避免家中服务暂时离线时阻止 Codex 启动。
- `default_tools_approval_mode = "writes"` 会对没有标为只读的工具请求确认。

保存配置后，完全退出并重新启动 Codex。

## 3. 验证连接

先检查 Codex 是否识别配置：

```powershell
codex mcp get siyuan --json
```

然后在新的 Codex 任务中输入 `/mcp`，确认 `siyuan` 已连接。也可以让 Codex 调用思源 MCP 的 `system.version` 工具做只读验证。

本次验证结果：

- MCP 初始化成功，HTTP 状态为 200。
- 服务端返回思源版本 `3.8.0`。
- 服务端暴露 31 个工具。
- 这些工具没有提供 MCP 的只读/破坏性注解，因此 `writes` 策略可能对所有工具都弹出确认，这是安全侧的预期行为。

## 4. 安全 Review

当前方案可用，但有以下风险：

1. 公网 HTTP 不加密。API Token、笔记内容和工具参数可能被路径上的设备观察或篡改。
2. MCP 权限较大。Token 泄露可能导致笔记读取、修改或管理操作。
3. 路由器管理页面的 HTTPS 证书只保护路由器 Web 管理界面，不会自动保护转发到思源的 `60106` 端口。
4. 思源自带证书若只包含 `localhost`、局域网 IP 等名称，就不能为 `cobwebs.asuscomm.com` 提供有效的公网 HTTPS 身份校验。

当前阶段建议：

- 只在确实需要时开放公网端口，并限制路由器防火墙来源地址（如果设备支持）。
- 定期轮换思源 API Token；曾经出现在聊天、日志或截图中的 Token 应尽快作废重建。
- 不把真实 Token 写入仓库、脚本、Issue、PR 描述或日志。
- 保持工具审批开启，尤其是修改、删除、执行 SQL 或管理类工具。
- 后续使用 Caddy、Nginx Proxy Manager 或其他反向代理，在内网服务前终止 TLS，并为 DDNS 域名申请有效证书。

## 5. GitHub 凭据能否做成 MCP？

可以做 GitHub MCP，但不应做成“读取或返回 GitHub 凭据”的 MCP。正确的边界是：凭据只保存在 MCP 服务端或操作系统凭据库中，MCP 对外只暴露受限的 GitHub 操作。

推荐顺序：

1. 优先使用现成的 GitHub MCP/连接器及 OAuth 登录。
2. 若必须使用 PAT，使用 fine-grained PAT，并只授权需要的仓库和最小权限。
3. PAT 放入环境变量、Windows Credential Manager 或专用 Secret Manager；不要放在 MCP 参数、返回值或日志里。
4. MCP 工具只提供诸如 `get_repo`、`list_issues`、`create_issue`、`get_pull_request` 等明确操作。
5. 写操作默认要求人工确认；读写工具分开授权，并记录审计日志。

不应提供以下类型的工具：

- `get_token`、`show_credentials` 等返回秘密的接口。
- 接受任意 URL 和 Header 的通用 HTTP 转发器。
- 接受任意 Shell 命令且自动附带 GitHub 凭据的接口。
- 把高权限 PAT 共用给所有仓库或所有调用者的实现。

如果需要自建，较安全的结构是：Codex 调用 MCP 的业务工具，MCP 服务在内部读取凭据并调用 GitHub API，最后只返回业务结果，绝不返回原始凭据。

## 参考

- [Codex MCP 配置文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [GitHub：管理 Personal Access Token](https://docs.github.com/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
