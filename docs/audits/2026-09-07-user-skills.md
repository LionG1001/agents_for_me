# 2026-09-07 User Skills 审计

已审计本机全部 9 个用户自有 Skill 的 43 个可分发输入文件，包括入口、UI metadata、引用、模板和脚本。系统 `.system`、第三方插件缓存、项目仓库自带 Skills 和 Python 缓存不属于本次 User Skills 发布范围。

目标仓库：`LionG1001/agents_for_me`（公开）。基线为 `origin/main` 的 `52fc699`；本地原有工作树干净。审计分支为 `agent/audit-user-skills-20260907`。本次不改动 Megatron 工作区或其远端测试环境，不读取/发布真实连接注册表、密钥环、MCP 客户端配置或凭据笔记。

## 全量审计结果

| Skill | 发现与改进 | 验证依据 |
| --- | --- | --- |
| k8s-multi-node-deploy | 修复 `mkdir -p` 抢锁导致存量锁可被覆盖、退出清理删除其他实例 PID 文件、MCCL 失败返回成功、复测引用节点并发争用；禁止仅凭陈旧心跳自动删锁。池级清理默认预演，实际执行须声明专用池范围，恢复次数默认上限 3；清理/netcheck 失败向上传递。GPU 活动检查覆盖全部运行节点。新增按完整 selector、owner UID、Ready、唯一节点和配额生成 hostfile 的离线工具。长操作说明移入引用，明确历史模板、危险操作和验收边界。 | 锁/PID、清理退出码/预演、MCCL 成功/失败/第二阶段、Pod JSON 回归；bash 语法检查。 |
| local-remote-workflow | 保留本地 Git 权威及单向同步约束；消除“测试原因未知就停止全部工作”、重复授权和过度固定记录长度；母版明确最新用户指令优先，受阻时只暂停受影响操作。 | 全文及模板审阅、Skill 验证、引用检查。 |
| multi-cluster-access | 本机已安装但目标仓库尚未收录，补全发布。v1 文档与实际 v2 CLI 不一致，现已对齐 auth_mode、独立 profile、严格 known_hosts、运行依赖和容器预期。有效 profile 覆盖后再次校验身份；askpass 匹配完整账户；VPN 失败停止本次 unit、秘密文件写入失败清理；stop 失败不得报告成功。 | 文档 JSON 实际加载、覆盖后身份验证、基础身份不变、askpass 账户前缀、VPN 启动失败清理与 stop 失败回归；Python 语法检查。 |
| musa-distributed-debugging | 缩短触发描述，历史 long-RoPE 案例移为按需引用；环境输出改为字段白名单；不再从“未生成 dump”直接推断不支持 Flight Recorder；监控终止进程与普通 trace 配置分开；补充授权环境和可信 pickle 边界。 | 全文/历史案例审阅、Skill 验证、引用检查；没有复验历史模型损失或后端能力。 |
| musa-training-optimization | 修正 Amdahl 的时间降幅/加速比区别、单 device 同窗口的时间并集口径；多流累计减并集不再误称 wall-time overlap；通信隐藏只与计算区间并集比较。去除固定候选数量和内部 proposal/action 编号引发的重复审批。 | 主文档与 playbook 一致性审阅、Skill 验证。 |
| organize-invoices | 删除任意 20 位数字、最后一个货币值、文件名分类的猜测；标注不明确/非正金额，使用 Decimal、带标签字段、合法日期；不可读文件不再因重复计算哈希导致全盘点崩溃；支持 `.PDF`。修正最大化金额与禁止低额日期的矛盾、跨日整数分尾差、总额度约束和历史例子授权误用。 | 字段解析、歧义/负额/日期/读失败回归；未执行真实 PDF 渲染或报销政策验收。 |
| publish-agent-assets | 合并两平台 sync/validate 到 Python 引擎，支持 Git worktree、预演、全源目标预检查、缓存排除、源/目标符号链接和 junction 拒绝；真正解析 YAML、检查尖括号 Markdown 链接、扫描无扩展名 UTF-8 文件并避免回显命中秘密。公开仓库发布前明确人工 diff 审阅和推送后 SHA 核验。 | 隔离 Git 仓库/worktree、越界 symlink、缓存/秘密文件、更新保留、YAML/链接/token 回归。 |
| remote-container-workspace | 校验 SSH 用户/主机及容器参数，阻止选项注入；PowerShell askpass 不再把密码交给 cmd 的 `echo` 解析；补充镜像/挂载核验并泛化个人路径示例。 | Bash 生成命令的真实 argv/嵌套引用回归；PowerShell 仅代码审阅。 |
| rsync-relay-transfer | 保留目录尾斜杠语义，验证实际加载的 base_path、端点和 Linux 密码文件权限；setup 默认拒绝覆盖和 symlink，创建秘密前限制权限；明确永久配置需长期保存授权，取消跨安装固定笔记 ID。 | 假 rsync argv、越界/权限拒绝、配置权限及覆盖保护回归；PowerShell 仅代码审阅。 |

UI metadata 保留原有调用策略；不因涉及敏感操作就关闭自动发现。模板中的历史环境值保留为明确标识的参考，没有改写本机正在使用的 MCP/VPN 配置。

## 验证与可复现证据

- 修改前：对输入快照执行首批同一套 38 项离线检查，6 项通过、30 项断言失败、2 项异常。异常分别来自 v1 示例无法被 v2 CLI 读取、不可读发票的错误处理再次抛出哈希读取异常。这是回归与新增能力的基线对比，不等同于 32 个独立漏洞。
- 修改后：51 项离线回归全部通过。涉及 SSH、rsync、MPI 的测试使用本地命令替身；清理预演测试屏蔽实际 kill；没有真实网络传输、VPN 启停、GPU 查询或训练。
- 全部 9 个 Skill 通过系统 `quick_validate.py`；所有 Python 源码可解析，所有 Bash 脚本通过 `bash -n`。
- 仓库通过改进后的验证器及 `git diff --check`。扫描不构成对所有凭据类型的完备证明；本次同时审阅了新增来源和完整拟发布文件。
- [测试结果](2026-09-07-test-results.json)、[输入文件 SHA256](2026-09-07-input-sha256.json)、[发布 Skill 文件 SHA256](2026-09-07-skills.sha256) 随审计记录提供；原始日志和可回退安装快照保留在本机临时审计目录，不上传本机路径和运行日志。

执行入口（在本仓库根目录）：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash skills/publish-agent-assets/scripts/validate-repository.sh .
git diff --check
```

已将改进后的 47 个可分发文件同步回本机 9 个活动 User Skills，并逐文件核对 SHA256；同步前对比输入快照，确认没有并发修改。原安装快照可用于回退。

## 行为变化与运行限制

- 发布脚本现在共同依赖 Python 3.10+；校验另需 PyYAML。PowerShell 可传 `-PythonExecutable`。本次环境没有 `pwsh`，未验证 Windows ACL、PowerShell 参数传递和 Windows askpass 运行时。
- 发票 JSON 金额现在输出精确十进制字符串；待复核/解析失败返回 1，仅重复且启用重复检查时返回 2。使用真实 PDF 前还需在具有 pdfplumber 的授权环境验证文本布局；分类结果只是候选，购销方、项目行和政策需另核对。
- 运维脚本是历史 MUSA 专用池工具，不是通用 HA 调度器。生产启用前仍需真实 MUSA/MCCL、共享文件系统锁语义、进程身份/rank 进度、stack dump 和 save/resume 验收。当前通过 GPU 活动推断恢复仍是启发式信号，不能当作训练恢复成功。
- rsync daemon 流量、VPN 重认证和凭据生命周期沿技能说明使用；没有将本次审计扩大为基础网络或认证系统改造。
- 自动故障清理的执行参数及退避行为发生变化：复用旧启动命令时需按新说明明确授权范围；不绕过失败或把陈旧锁当作无人占用。

## 外部事实核对

完整 selector 包括 matchLabels 与 matchExpressions，所有要求按 AND 组合，NotIn 允许缺少该标签；实现按 [Kubernetes 官方 selector 文档](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/) 核对。监控 watchdog 与 trace dump 的控制项参考 [PyTorch ProcessGroupNCCL 文档](https://docs.pytorch.org/docs/stable/torch_nccl_environment_variables.html)；该说明不证明某个 torch_musa 构建实现了这些变量。
