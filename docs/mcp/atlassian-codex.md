# Atlassian MCP：Codex 连接内网 Jira 与 Confluence

使用社区包 [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian)，在本机通过 stdio 连接公司 Jira 与 Confluence Data Center：

- Jira：`https://jira.mthreads.com`
- Confluence：`https://confluence.mthreads.com`

本方案直连两个系统，不经过 `mcp-atlassian.devops.mthreads.com` SSE 网关。MCP 进程由客户端启动，无需开放本机监听端口。

本文同步自 `agent-compose/mcp/atlassian/GUIDE.md`，补充了 Codex 配置、独立凭据文件和本次部署验证结果。同步日期：2026-10-08。

## 1. 前置条件

- 本机可访问内网 Jira / Confluence，并拥有对应账号。
- 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，确认 `uv --version` 和 `uvx --version` 可运行。
- 下文安装和文件权限命令适用于 Linux / macOS；本次实际验证环境为 Linux ARM64、Python 3.12。Windows 使用对应虚拟环境的 `Scripts/mcp-atlassian.exe`，并通过文件权限限制凭据访问。

## 2. 创建两个 PAT

两个系统分别创建 Personal Access Token，名称可用 `Codex MCP`，到期时间按使用需求设置：

| 系统 | 创建入口 |
|---|---|
| Jira | 右上角头像 → Profile → Personal Access Tokens → 创建令牌 |
| Confluence | 右上角头像 → 设置 → 个人访问令牌 → 创建令牌 |

创建后立即复制令牌，通常只显示一次。Data Center PAT 由包以 Bearer 方式处理；不要套用 Atlassian Cloud 的 email + API token 配置。

## 3. 将凭据保存在本机

创建仅当前用户可访问的目录和文件：

```bash
mkdir -p "$HOME/.codex/mcp/atlassian"
chmod 700 "$HOME/.codex/mcp/atlassian"
touch "$HOME/.codex/mcp/atlassian/credentials.env"
chmod 600 "$HOME/.codex/mcp/atlassian/credentials.env"
```

在本机编辑 `~/.codex/mcp/atlassian/credentials.env`，按下列模板填写真实 PAT：

```dotenv
JIRA_URL='https://jira.mthreads.com'
JIRA_PERSONAL_TOKEN='<JIRA_PERSONAL_TOKEN>'
CONFLUENCE_URL='https://confluence.mthreads.com'
CONFLUENCE_PERSONAL_TOKEN='<CONFLUENCE_PERSONAL_TOKEN>'
```

凭据文件放在仓库外。本文中的令牌值均为占位符，不要将真实 PAT 提交到 Git。

## 4. 安装并配置 Codex

### 4.1 固定版本的虚拟环境

```bash
uv venv --python python3 "$HOME/.codex/mcp/atlassian/venv"
uv pip install --python "$HOME/.codex/mcp/atlassian/venv/bin/python" 'mcp-atlassian==0.23.1'
"$HOME/.codex/mcp/atlassian/venv/bin/mcp-atlassian" --version
```

编辑 `~/.codex/config.toml`，加入或更新 `atlassian` 条目，保留已有 MCP 配置：

```toml
[mcp_servers.atlassian]
command = "/absolute/path/to/.codex/mcp/atlassian/venv/bin/mcp-atlassian"
args = ["--env-file", "/absolute/path/to/.codex/mcp/atlassian/credentials.env", "--transport", "stdio"]
startup_timeout_sec = 60
tool_timeout_sec = 90
enabled = true

[mcp_servers.atlassian.env]
MCP_LOGGING_STDOUT = "false"
```

将两个 `/absolute/path/to/` 路径替换为本机实际绝对路径。使用包自带的 `mcp-atlassian` 入口：本次验证的 `0.23.1` 版本不包含可执行的 `mcp_atlassian.__main__`，所以原始 guide 中的 `python -m mcp_atlassian` 备用启动方式不可用。

保留日志输出到 stderr，避免日志混入 stdio 的 MCP 协议流。配置保存后，在 MCP 设置中重新加载服务，或完全退出并重新启动 Codex。

### 4.2 使用 uvx 的替代配置

也可以保留原始 guide 的 uvx 方式。将 4.1 中 `atlassian` 条目的 `command` 和 `args` 替换为：

```toml
command = "/absolute/path/to/uvx"
args = ["--from", "mcp-atlassian==0.23.1", "mcp-atlassian", "--env-file", "/absolute/path/to/.codex/mcp/atlassian/credentials.env", "--transport", "stdio"]
```

首次启动 uvx 会下载运行包及依赖。4.1 的预安装方式已在本次部署中验证；uvx 配置基于原始 guide 和包提供的命令行参数。

### 4.3 Cursor / 其他 JSON 客户端

对于使用 `mcpServers` JSON 格式的客户端，例如 Cursor 的 `~/.cursor/mcp.json`，可以使用：

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "/absolute/path/to/uvx",
      "args": [
        "--from", "mcp-atlassian==0.23.1", "mcp-atlassian",
        "--env-file", "/absolute/path/to/.codex/mcp/atlassian/credentials.env",
        "--transport", "stdio"
      ]
    }
  }
}
```

仍需替换实际绝对路径；Windows 以实际安装的 uvx 可执行文件路径为准。使用 `agent-compose.yaml` 时可在 `mcps[]` 中配置相同的命令和参数。

## 5. 能力与使用示例

以下能力表同步自原始 guide；具体可用工具以客户端当前的 `tools/list` 返回为准。

### Jira

| 能力 | 工具 |
|------|------|
| JQL 搜 / 读 Issue | `jira_search` / `jira_get_issue` / `jira_get_project_issues` |
| 列项目 / 组件 / 版本 / 字段 | `jira_get_all_projects` / `jira_get_project_components` / `jira_get_project_versions` / `jira_search_fields` / `jira_get_field_options` |
| 创建 / 批量创建 | `jira_create_issue` / `jira_batch_create_issues` |
| 改字段 / 删 Issue | `jira_update_issue` / `jira_delete_issue` |
| 查流转 / 改状态 | `jira_get_transitions` / `jira_transition_issue` |
| 评论 | `jira_add_comment` / `jira_edit_comment` |
| 链接 / Epic / 远程链接 | `jira_get_link_types` / `jira_create_issue_link` / `jira_remove_issue_link` / `jira_link_to_epic` / `jira_create_remote_issue_link` |
| 关注者 / 工时 | `jira_get_issue_watchers` / `jira_add_watcher` / `jira_remove_watcher` / `jira_get_worklog` / `jira_add_worklog` |
| 版本 | `jira_create_version` / `jira_batch_create_versions` |
| 看板 / Sprint | `jira_get_agile_boards` / `jira_get_board_issues` / `jira_get_sprints_from_board` / `jira_get_sprint_issues` / `jira_create_sprint` / `jira_update_sprint` / `jira_add_issues_to_sprint` |
| 附件 / 图片 / 关联研发 | `jira_download_attachments` / `jira_get_issue_images` / `jira_get_issue_development_info` |
| Service Desk 队列 | `jira_get_service_desk_for_project` / `jira_get_service_desk_queues` / `jira_get_queue_issues` |
| 用户 / 日期 / SLA | `jira_get_user_profile` / `jira_get_issue_dates` / `jira_get_issue_sla` |

### Confluence

| 能力 | 工具 |
|------|------|
| 搜页面 / 用户 | `confluence_search` / `confluence_search_user` |
| 读页面 / 子页 / 空间树 | `confluence_get_page` / `confluence_get_page_children` / `confluence_get_space_page_tree` |
| 历史版本 / diff | `confluence_get_page_history` / `confluence_get_page_diff` |
| 创建 / 更新 / 移动 / 删除 | `confluence_create_page` / `confluence_update_page` / `confluence_move_page` / `confluence_delete_page` |
| 评论 | `confluence_get_comments` / `confluence_add_comment` / `confluence_reply_to_comment` |
| 标签 | `confluence_get_labels` / `confluence_add_label` |
| 附件 / 图片 | `confluence_get_attachments` / `confluence_get_page_images` / `confluence_download_attachment` / `confluence_upload_attachment` / `confluence_upload_attachments` / `confluence_delete_attachment` |

聊天中可以直接说：

- “查询分配给我的、最近更新的 Jira 工单。”
- “读取 `PROJECT-123` 的详情和可用状态流转。”
- “搜索 Confluence 中关于训练性能的页面。”
- “将已确认的内容写入指定 Confluence 页面。”

读取和搜索可用于验证连接；创建、更新、流转、评论、上传和删除会修改真实系统，需要用户明确授权。

## 6. 验证连接

先确认 Codex 已识别配置：

```bash
codex mcp get atlassian --json
```

这条命令只检查配置登记，不代表 PAT 或真实查询已经成功。重新加载客户端后，应确认 MCP 初始化和工具列表，再进行只读查询：

- Jira：调用 `jira_search`，使用 JQL `assignee = currentUser() ORDER BY updated DESC`，`limit=1`。
- Confluence：调用 `confluence_search`，使用 CQL `type=page`，`limit=1`。

2026-10-08 的本次部署验证结果：

| 检查项 | 结果 |
|---|---|
| 运行包 | `mcp-atlassian==0.23.1` |
| Jira PAT 鉴权 | `/rest/api/2/myself` 返回 HTTP 200 |
| Confluence PAT 鉴权 | `/rest/api/user/current` 返回 HTTP 200，用户类型为 `known` |
| MCP stdio 初始化 | 成功 |
| 工具发现 | 98 个工具 |
| `jira_search` / `confluence_search` | 实际查询均成功 |

该记录仅说明本次环境的验证结果；其他环境仍需用自己的 PAT 验证。没有在验证中执行写入或删除操作。

## 7. 常见问题

| 现象 | 检查方法 |
|---|---|
| HTTP 401 / 403 | 检查 PAT 是否填错、过期或被撤销，并确认对应账号具有访问目标内容的权限。 |
| MCP 工具列表为空 | 检查凭据文件路径和两个 PAT 是否为空；仅能访问登录页不代表鉴权成功。 |
| 找不到 uvx / 启动命令 | 使用实际可执行文件的绝对路径；虚拟环境方案使用 `bin/mcp-atlassian`，Windows 使用 `Scripts/mcp-atlassian.exe`。 |
| `No module named mcp_atlassian.__main__` | 改用安装包提供的 `mcp-atlassian` 命令。 |
| 首次启动超时 | 先安装运行包和依赖，再配置 MCP；检查包源网络和内网连接。 |
| SSL 证书验证失败 | 检查系统信任链或公司 CA 配置，保持证书验证开启。 |
| 配置保存后当前会话仍没有工具 | 在 MCP 设置中重新加载，或重启 Codex 后再次检查。 |

## 参考与同步来源

- [原始 Atlassian guide（agent-compose）](https://sh-code.mthreads.com/andy.wang/agent-compose/-/blob/2ad6de089f958e86ad0473e8ab106ff2c8e9abc7/mcp/atlassian/GUIDE.md)：公司内网仓库，需要对应访问权限；原文包含 PAT 入口示意图。
- [mcp-atlassian 上游](https://github.com/sooperset/mcp-atlassian)
- [uv 安装文档](https://docs.astral.sh/uv/getting-started/installation/)
- [Codex MCP 配置文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
