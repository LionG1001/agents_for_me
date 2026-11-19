# Windows 安装与验证

在 Windows 本地检出仓库、安装 Codex User Skills 和可分发的 MCP 运行环境。GPU、OpenVPN/systemd 和 Linux 运维脚本仍在项目指定的 Linux 主机或容器执行。

## 安装全部 Skills

需要 Git、Python 3.11+ 和 PowerShell 5.1 或 7。先用 `python --version` 确认解释器；仓库检查另需 PyYAML（CI 使用 `6.0.3`）。以下命令在仓库根目录执行：

```powershell
./scripts/install-skills.ps1 -Update -WhatIf
./skills/publish-agent-assets/scripts/validate-repository.ps1 -RepositoryRoot .
./scripts/install-skills.ps1 -Update
```

本机执行策略禁止脚本时，可以在单次调用中使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script> ...`。脚本采用 UTF-8 BOM 以兼容 Windows PowerShell 5.1；Python 包装入口使用 `-X utf8`，Git 输出显式按 UTF-8 解码，支持中文及带空格的仓库路径。若从 PowerShell 7 启动 5.1 导致模块加载错误，使用 5.1 自己的模块路径，避免继承 Core 模块。

安装器默认使用 `$env:CODEX_HOME/skills`，未设置时使用 `%USERPROFILE%/.codex/skills`，也可传 `-Destination`。跨平台等价入口是 `python -X utf8 scripts/install_skills.py --update --dry-run`，审查后移除 `--dry-run`。

更新前检查全部源/目标文件、符号链接和 Windows junction，拒绝已知凭据文件及仓库与安装目录重叠；已有不同版本必须显式使用 `-Update`。逐个 Skill 在临时目录准备并核对 SHA256，再替换目标；完整旧目录保存在安装目录同级的 `backups/agents-for-me-<UTC时间>/`。保留目标独有文件，不改 `.system`、插件缓存和仓库未收录的其他 Skill。发布某个 Skill 失败会恢复该 Skill，之前已成功安装的 Skill 保持新版本；失败暂存目录留待核查。完成后用 `-WhatIf` 再次检查，应显示 `Unchanged`。

回滚时先核对当前内容没有后续修改，再把指定 Skill 的当前目录另存，将对应备份目录复制回安装位置；不批量删除或覆盖其他 Skill。新装或更新的 Skill 在下一轮对话中可用。

## Skill 平台范围

| Skill | Windows 安装后的执行范围 |
| --- | --- |
| k8s-multi-node-deploy | MCP 编排及离线 hostfile Python 可在 Windows；MCCL、hang、清理和故障管理 shell 在已授权 Linux GPU 环境 |
| local-remote-workflow | 工作流说明可直接使用；同步入口和源码权威遵循项目规则 |
| multi-cluster-access | 原生 list/resolve/status、两跳公钥 SSH；密码 askpass 与 VPN 管理使用 Linux 或既有 MCP，Windows TCP 探测不证明 VPN 路由 |
| musa-distributed-debugging | 本地分析材料；设备探测、复现和数值比较在项目指定的 MUSA 环境 |
| musa-training-optimization | 本地审查与方案；Trace/算子/训练性能按授权在目标设备验证 |
| organize-invoices | Python 盘点可在 Windows，需执行解释器已安装 pdfplumber；此安装器不批量改变全局 Python 依赖 |
| publish-agent-assets | PowerShell 包装和共享 Python 验证/同步，可处理中文路径 |
| training-project-delivery | 工作流说明可直接使用，按项目实际 MCP、硬件和运行环境衔接 |
| remote-container-workspace | 原生 PowerShell + Windows OpenSSH；先 dry-run，再连接指定 Linux 容器 |
| rsync-relay-transfer | 可在 Windows 编排远端 Linux rsync；只有明确选 Windows 执行时才使用 PowerShell 包装并另备兼容 rsync |

## MCP 安装和配置

```powershell
./scripts/prepare-mcp.ps1
```

此入口只准备 `siyuan`（`mcp==1.30.0`）和 `atlassian`（`mcp-atlassian==0.23.1`）的独立 venv，使用 `venv/Scripts/python.exe` 或 `venv/Scripts/mcp-atlassian.exe`。目录在 Codex 用户目录的 `mcp/<服务名>`，ACL 限制为当前用户。已有 venv 重用；思源脚本更新前备份不同文件，不复制其他服务的依赖环境。包版本按仓库已验证版本固定，未锁全部传递依赖。脚本不改 `config.toml`、不创建虚假凭据、不迁移已经工作的连接。

| MCP | 配置/检查 | 未就绪时需要什么 |
| --- | --- | --- |
| siyuan | [思源说明](mcp/siyuan-codex.md)；健康检查支持现有 HTTP 或本地 stdio | 已核验 URL、授权环境变量；需要 Host 兼容时使用 bridge |
| bastion-k8s | [配置说明](../skills/k8s-multi-node-deploy/mcp/README.md)；保留已安装版本，用 Node 的绝对路径运行预安装入口 | 堡垒机与 namespace、认证；bastion_check 只验证第一跳 |
| node_repl | Codex 桌面应用提供；运行 `nodeRepl.write(2 + 2)` | 由当前应用发现运行时；不复制其他机器的路径/浏览器变量 |
| atlassian | [Atlassian 说明](mcp/atlassian-codex.md)；运行包可安装 | 真实 Jira/Confluence URL 与仓库外受限凭据文件；分别做只读业务查询 |
| dingtalk-dws | 索引有工具名，没有可安装服务包 | 权威源码/包地址、版本、Windows 支持及本机 dws 登录 |
| huishan-cluster | 索引有工具名，没有 MCP 服务端源码 | 服务分发入口、Windows 或远程运行方式及身份/策略配置；multi-cluster-access CLI 不等同于该服务 |

最后三项的缺失配置见 [Issue #17](https://github.com/LionG1001/agents_for_me/issues/17)。不将示例域名、占位 PAT 或不存在的命令登记为已启用连接。不要将配置原文、凭据或业务结果上传到 Issue/PR。

Windows TOML 路径使用正斜杠，或单引号字面字符串；不在双引号 TOML 路径中直接放未经转义的反斜杠。Windows 子进程启动优先使用 `.exe` 绝对路径，避免把 `npm.ps1`、`npx.ps1` 当作可执行程序。

## 验证边界

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -X utf8 -m unittest discover -s tests -v
./skills/publish-agent-assets/scripts/validate-repository.ps1 -RepositoryRoot .
git diff --check
```

Windows 测试覆盖共享 Python 行为、安装备份/回滚、PowerShell 5.1 解析、远端参数预演及凭据 ACL。需要创建 symlink 的用例在无该权限时明确 skip；Linux shell/VPN 行为在 Ubuntu CI 执行，不用 Git Bash 的结果冒充 Linux 验收。CI 不连接远端集群、发送通知或运行 GPU 训练。

MCP 依次核对进程启动、初始化、工具发现与只读业务调用；安装包存在不代表上游鉴权成功。配置调整后重新加载连接，确认新对话工具可发现。当前电脑的实际结果记录在 PR，不把历史环境的测试结果作为新机器的通过证据。
