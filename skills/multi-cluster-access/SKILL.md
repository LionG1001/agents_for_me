---
name: multi-cluster-access
description: 管理多个研发集群的 VPN、堡垒机、目标服务器和容器任务映射，并安全执行状态检查、SSH、远端命令或容器连接。用户提到连接集群、堡垒机、worker、远端容器，或不同任务需要不同远端身份时使用。
---

# 多集群访问

已有适用 MCP 或连接工具时优先复用；Linux 本机也可用 `scripts/clusterctl.py` 解析 v2 注册表、从密钥环或集中代理取凭据并连接。不要仅为读取已有集群状态而迁移连接配置。CLI 的依赖与 schema 见 [注册表格式](references/registry.md)。

## 工作流

1. 运行 `clusterctl.py list` 查看已登记的集群、目标和任务。
2. 用户按任务名操作时先运行 `clusterctl.py resolve <任务名>`，确认其集群、目标、容器和工作目录。
3. 连接前运行 `clusterctl.py status <集群或任务>`；需要时用 `start` 建立 VPN。
4. 使用 `ssh`、`exec`、`container-shell` 或 `container-exec` 完成用户请求。
5. 涉及远端修改时遵循用户授权范围；连接成功不扩大对远端文件、服务、GPU 或作业的操作权限。

常用入口：

```bash
python3 ~/.codex/skills/multi-cluster-access/scripts/clusterctl.py list
python3 ~/.codex/skills/multi-cluster-access/scripts/clusterctl.py status <cluster-or-task>
python3 ~/.codex/skills/multi-cluster-access/scripts/clusterctl.py ssh <target-or-task>
python3 ~/.codex/skills/multi-cluster-access/scripts/clusterctl.py container-shell <task>
```

## 凭据和主机身份

- 注册表只保存非敏感拓扑及 `secret_ref`，实际密码存入 Python keyring 后端。
- 不在回答、命令行参数、日志、脚本、注册表、Git 或临时补丁中输出密码。
- 临时 VPN 认证文件必须为 `0600`，并在启动结果确定后删除。
- CLI 对堡垒机和目标机均使用严格主机密钥校验；首次连接前核验指纹并预置 known_hosts。其他连接工具按其已核验的主机身份配置执行，不得关闭校验。
- 自动认证只用于注册表明确选择的 VPN、堡垒机和目标机，不尝试未登记账户。

## 更新配置

新增集群、目标或任务时，先读取 [注册表格式](references/registry.md)。只修改非敏感注册表；用 `clusterctl.py set-secret <secret_ref>` 交互式写入密钥环。账号不同就使用不同的 `secret_ref`，不要按“同一集群共用密码”做假设。

如果用户需要跨机器共享注册表、集中凭据代理、统一审计或面向多客户端提供结构化连接 API，再建议把凭据代理和连接控制实现为 MCP 服务；本 Skill 保留为工作流编排层。

## 团队 MCP 模式

- MCP 工具参数只接受已登记的集群、目标、任务和命令，不接受密码、私钥或 token。
- 任务通过注册表中的 `access_profile` 选择堡垒机和目标机身份；每个身份使用独立 `secret_ref`。
- 服务端每次连接时解析 `secret_ref`，不得缓存长期凭据。集中部署通过 `CLUSTER_ACCESS_SECRET_COMMAND` 接入 Vault、KMS 或内部凭据代理；本机开发才回退到桌面 keyring。
- Streamable HTTP 服务必须置于公司身份代理/API Gateway 后并保留操作者审计；不得把无认证端口直接暴露到团队网络。
- MCP 负责 Agent 的状态检查和非交互命令。人类交互终端继续使用 SSH/Electerm，不通过 MCP 返回凭据。
