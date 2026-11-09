# 思源笔记 MCP：Codex 连接与安全配置

本文记录通过 DDNS 和端口映射连接远程思源 MCP 的配置。2026-10-20 在 Linux 上验证了本地 stdio 转接方案：Codex 通过标准 MCP stdio 接入，转接程序通过带认证的 Streamable HTTP 访问原有远程 `/mcp`。原有 HTTP 直连配置保留供能正确传递 Host、处理代理的客户端使用。

> 当前方案使用公网 HTTP。它可以工作，但请求头中的 API Token 和传输内容没有 TLS 加密，不建议作为长期方案。后续应改为带有效域名证书的 HTTPS 反向代理。

## 当前拓扑

```text
Codex
  -> 本地 stdio 转接程序（Linux 已验证方案）
  -> http://cobwebs.asuscomm.com:60106/mcp
  -> 华硕路由器 DDNS + TCP 60106 端口映射
  -> 局域网设备上的思源服务（本例为 192.168.50.166:6806）
```

该地址不是“仅局域网生效”：只要公网可以访问映射端口，知道地址和凭据的客户端就能访问它。

## 1. 保存 API Token

不要把 Token 直接写入 `config.toml` 或提交到 Git 仓库。已有 `SIYUAN_MCP_AUTHORIZATION` 时继续复用；变量保存完整的 `Authorization` 头值，转接程序不会另加认证前缀。

Windows PowerShell 中可将完整的头值保存为当前用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable(
    "SIYUAN_MCP_AUTHORIZATION",
    "token <YOUR_SIYUAN_API_TOKEN>",
    "User"
)
```

设置后需要完全退出并重新启动 Codex，现有进程不会自动获得新的用户环境变量。

Linux 临时验证时，可交互输入完整的认证头，避免把真实值写进命令历史：

```bash
read -r -s -p 'SiYuan Authorization: ' SIYUAN_MCP_AUTHORIZATION
printf '\n'
export SIYUAN_MCP_AUTHORIZATION
```

随后从同一环境启动 Codex。仅在终端中 `export` 不会让从桌面图标启动的进程自动获得变量；持久使用时应沿用桌面会话或凭据管理器的注入方式，确保 Codex 启动时能读取该变量。

以下代理设置用于 **HTTP 直连方案**；stdio 转接程序使用 `trust_env=False`，不读取进程的 HTTP 代理设置。如果使用 Clash 等系统代理，建议让此 DDNS 域名直连，同时保留已有的 `NO_PROXY` 内容：

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

### 2.1 网页可访问，MCP 仍可能失败

网页入口和 `/mcp` 使用不同的请求校验。2026-10-20 实测思源 `3.8.0` 的普通 API 正常返回，但 MCP 初始化返回 `403 Forbidden: invalid Host header`；官方 [issue #18701](https://github.com/siyuan-note/siyuan/issues/18701) 记录了相同的远程 Host 兼容问题和后续修复。

本次连接必须同时满足：认证头保持有效、远程 MCP 收到兼容的 `Host: localhost`、请求直达 URL 指定的服务。通过环境代理请求时曾返回 `502`，使用相同地址和认证并直连后初始化成功。因此不能仅凭网页能打开或 TOML 中写了 Host 覆盖，就认定 MCP 已连通。

| 现象 | 应先核对 |
| --- | --- |
| `401` / `Auth failed` | Codex 进程是否获得认证环境变量、完整头值是否有效 |
| `403` / `invalid Host header` | 服务版本、客户端是否实际发出覆盖后的 Host |
| 覆盖 Host 后 `502` | 代理或反向代理是否按覆盖后的 Host 路由；对照直连结果 |
| 配置可读取，但没有工具 | MCP 初始化、工具发现和当前聊天是否加载新配置 |

### 2.2 Linux：已验证的 stdio 转接方案

配套文件为 [bridge.py](siyuan/bridge.py)、[check_connection.py](siyuan/check_connection.py) 和 [requirements.txt](siyuan/requirements.txt)。转接程序使用官方 Python MCP SDK，不改写工具名、参数或返回内容，也不额外开放监听端口。认证仅从已有环境变量读取；`trust_env=False` 只影响这个转接程序的出站 HTTP 客户端，不改变全局代理设置。

在仓库根目录运行以下命令。本例使用已有的 `uv` 和 Python 3.11+；不复制其他 MCP 的虚拟环境或依赖目录：

如目标目录已经存在，应先备份并检查现有文件，再更新；不要覆盖正在使用的依赖环境。

```bash
siyuan_mcp_dir="$HOME/.codex/mcp/siyuan"
mkdir -p "$siyuan_mcp_dir"
cp docs/mcp/siyuan/bridge.py docs/mcp/siyuan/check_connection.py \
   docs/mcp/siyuan/requirements.txt "$siyuan_mcp_dir/"
uv venv --python python3 "$siyuan_mcp_dir/venv"
uv pip install --python "$siyuan_mcp_dir/venv/bin/python" \
   -r "$siyuan_mcp_dir/requirements.txt"
```

没有 `uv` 时，也可使用可正常运行的 `python3 -m venv` 和环境内的 `pip` 安装同一依赖文件；Debian/Ubuntu 若缺少 `ensurepip`，需先准备对应的 `python3-venv` 包。

备份 `~/.codex/config.toml`，仅替换已有 `[mcp_servers.siyuan]` 的传输配置，保留其他 MCP 和工具审批设置。把下面的 `/home/<USER>` 替换为本机实际的绝对用户目录：

```toml
[mcp_servers.siyuan]
command = "/home/<USER>/.codex/mcp/siyuan/venv/bin/python"
args = ["/home/<USER>/.codex/mcp/siyuan/bridge.py"]
env_vars = ["SIYUAN_MCP_AUTHORIZATION"]
env = { SIYUAN_MCP_URL = "http://cobwebs.asuscomm.com:60106/mcp", SIYUAN_MCP_HOST_HEADER = "localhost", PYTHONUNBUFFERED = "1" }
enabled = true
required = false
default_tools_approval_mode = "writes"
startup_timeout_sec = 30
tool_timeout_sec = 60
```

迁移后移除该条目旧的 `url`、`env_http_headers` 和 `http_headers`，避免混合两种传输配置。`env_vars` 只列需要转发的认证变量名，不把认证值写进 TOML。升级思源并确认原生远程 MCP 已修复后，可重新验证 HTTP 直连方案。

### 2.3 HTTP 直连配置

这是原有配置，适用于能够正确覆盖 Host、并让目标域名直连的客户端。Windows 用户配置文件为 `%USERPROFILE%\.codex\config.toml`，Linux 为 `~/.codex/config.toml`：

```toml
[mcp_servers.siyuan]
url = "http://cobwebs.asuscomm.com:60106/mcp"
env_http_headers = { Authorization = "SIYUAN_MCP_AUTHORIZATION" }
http_headers = { Host = "localhost" }
enabled = true
required = false
default_tools_approval_mode = "writes"
startup_timeout_sec = 30
tool_timeout_sec = 60
```

配置说明：

- `env_http_headers` 从环境变量读取认证头，避免明文 Token 进入配置文件。
- `Host = "localhost"` 是思源 3.8.0 的兼容设置；不同客户端及代理对 Host 覆盖的处理可能不同，须通过实际初始化和工具调用验证。
- `required = false` 避免家中服务暂时离线时阻止 Codex 启动。
- `default_tools_approval_mode = "writes"` 会对没有标为只读的工具请求确认。

保存任一方案后，刷新 MCP 连接；如果当前应用没有可用的刷新入口，完全退出并重新启动 Codex。配置检查通过不代表当前聊天已经加载新工具。

### 2.4 固定笔记访问约定

在 `~/.codex/AGENTS.md`（Windows 为 `%USERPROFILE%\.codex\AGENTS.md`）中合并以下规则，保留已有指令：

```markdown
## 思源笔记

- 检索、读取、整理和修改思源笔记时，直接使用 siyuan MCP；不要使用浏览器查看或操作笔记，除非用户明确另行要求。
- MCP 连接失败时先检查连接配置和工具加载，不要自动回退到浏览器。
```

## 3. Markdown、代码块与公式写入契约

SiYuan MCP 的 `document.create(markdown=...)`，以及 `block.insert`、`block.append`、`block.prepend`、`block.update` 在 `dataType="markdown"` 时，接收的都是**求值后的原始 Markdown/Kramdown 文本**。调用方不应再次转义 Markdown 分隔符。

### 3.1 正确写法

行内代码直接使用一对反引号：

```markdown
`attn_implementation: eager`
```

围栏代码块直接使用三个反引号，并填写语言标记。下面的四反引号只是为了在本文中展示三反引号代码块：

````markdown
```python
attn_weights = softmax(scores + additive_mask, dim=-1, dtype=float32)
```
````

行内公式使用 `$...$`，块级公式使用独立的 `$$...$$`：

```markdown
head dimension 为 $d_k=256$。

$$
P = \operatorname{softmax}\!\left(\frac{QK^{\mathsf T}}{\sqrt{d_k}} + M\right)
$$
```

解析成功后：

- 围栏代码块应成为 SiYuan `type=c` 的代码块；
- 块级公式应成为 `type=m` 的公式块；
- 行内代码和行内公式应保留在所属段落中，并按对应样式渲染。

### 3.2 常见错误

不要向 MCP 发送下面这种内容，除非确实想显示字面量反引号：

```text
\`inline code\`
\`\`\`python
print("not a code block")
\`\`\`
```

反斜杠会把反引号转义，SiYuan 会将其解析为普通文字，而不是行内代码或代码块。

使用 JavaScript 组织工具调用时还要区分普通模板字符串和 `String.raw`：

- 普通模板字符串中的 `\`` 用于转义 JavaScript 自身的反引号，求值结果里不会保留反斜杠；
- `String.raw` 会保留这个反斜杠，`String.raw` 与手工 `\`` 组合后会产生错误的 `\`` Markdown；
- 最终传给 MCP 的字符串应包含原始 `` `code` ``、三个原始反引号或原始 `$$` 分隔符。

### 3.3 写入后验证

创建或批量更新长文档后，应使用 `block.get_kramdown`、`block.batch_kramdown` 或 `export.md` 回读，而不能只依据写入接口返回成功判断格式正确。

至少检查：

1. 是否仍存在 `\`` 或 `\`\`\`` 等可疑转义；
2. 预期代码块是否为 `type=c`，公式块是否为 `type=m`；
3. 普通段落中是否残留三反引号；
4. 代码语言标记是否正确，例如 `python`、`bash`、`text`；
5. LaTeX 是否在 SiYuan 中实际渲染，而不是显示为普通文本。

只读 SQL 审计示例：

```sql
SELECT count(*) AS escaped_backtick_blocks
FROM blocks
WHERE root_id = '<DOCUMENT_ID>'
  AND instr(markdown, char(92) || char(96)) > 0;

SELECT type, count(*)
FROM blocks
WHERE root_id = '<DOCUMENT_ID>'
  AND type IN ('c', 'm')
GROUP BY type;
```

### 3.4 建议加入 MCP 工具描述的文本

`document` 和 `block` 工具的服务端描述建议包含以下约束：

```text
For dataType="markdown" and document.create(markdown=...), pass Markdown
delimiters unescaped in the evaluated payload. Use `code` for inline code,
fenced code blocks with a language identifier, $...$ for inline math, and
$$...$$ for block math. Do not send \` or \`\`\` unless literal backticks
are intended. After parsing, code blocks have type=c and block-math blocks
have type=m. After long or batch writes, read back Kramdown or exported
Markdown and verify the parsed block types. Return a warning when suspicious
escaped Markdown delimiters are detected.
```

服务端若实现输入检查，建议对可疑的 `\`` 和 `\`\`\`` 返回 warning，而不是自动替换。自动替换可能破坏调用方确实需要展示字面量反引号的内容。

## 4. 验证连接

先检查 Codex 是否识别配置：

```powershell
codex mcp get siyuan --json
```

该命令只说明配置被识别，不能单独证明服务可用。使用 Linux stdio 方案时，运行配套健康检查：

```bash
"$HOME/.codex/mcp/siyuan/venv/bin/python" \
  "$HOME/.codex/mcp/siyuan/check_connection.py"
```

检查从 `config.toml` 启动实际配置的转接程序，依次执行 MCP 初始化、工具发现，并发调用只读的 `system` 工具查询版本与时间。可选加上 `--document-id '<DOCUMENT_ID>'`，对自己指定的文档执行只读 `document` / `info` 验证；输出不打印笔记正文或凭据。`--config` 可用于检查单独准备的配置文件。

然后在新加载的 Codex 会话中确认 `siyuan` 工具可用，并调用 `system` 工具、参数 `{"action":"version"}`。原生工具发现和实际工具调用都成功，才算连接验证完成；不用浏览器查看笔记来代替 MCP 验证。

2026-10-20 Linux 验证结果：

- MCP 初始化成功，协商协议为 `2025-11-25`，服务端返回思源版本 `3.8.0`。
- Codex 自身的工具发现成功加载 31 个工具，无工具发现错误；独立 stdio 客户端也成功发现这些工具。
- 并发只读查询和指定文档读取通过，退出正常。缺少认证变量时启动失败，不在协议标准输出中打印诊断内容。
- 这些工具没有提供 MCP 的只读/破坏性注解，因此 `writes` 策略可能对所有工具都弹出确认，这是安全侧的预期行为。

## 5. 安全 Review

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

## 6. GitHub 凭据能否做成 MCP？

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
- [SiYuan：远程 MCP Host 兼容问题 #18701](https://github.com/siyuan-note/siyuan/issues/18701)
- [官方 Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- [GitHub：管理 Personal Access Token](https://docs.github.com/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
