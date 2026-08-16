---
name: k8s-multi-node-deploy
description: >-
  Kubernetes multi-node GPU ops: PVC, assigment label, hostNetwork+hostPort,
  plan/runtime hostfile, MCCL netcheck, fault manager, hang detection.
  Use for K8s 多机环境准备, Deployment, hostfile, MCCL, auto_fault_manager, Pending.
---

# K8s 多机环境部署

面向 **Kubernetes 多机 GPU Pod 池** 的部署、运维与文件同步。命名空间、PVC、堡垒机因集群而异；**先判断场景，再选路径**。

## 场景选择（先读）


| 场景                     | 何时用                           | Agent 路径                         |
| ---------------------- | ----------------------------- | -------------------------------- |
| **A. 仅文件同步**           | Pod 已在跑，只需 `kubectl cp` / 读文件 | → [§仅文件同步](#仅文件同步)               |
| **B. 计划 hostfile**     | apply 前，选定目标节点并打 label        | → [§计划 hostfile](#计划-hostfile)   |
| **C. 新建/改 Deployment** | 推理、服务、训练池（常接在 B 之后）           | → [§部署流程](#部署流程)                 |
| **D. 运行时 hostfile**    | apply 后，业务启动依赖节点列表            | → [§运行时 hostfile](#运行时-hostfile) |


典型顺序：**B → C**（多机池）；若业务要 hostfile 再 **→ D**。仅 cp 文件走 **A**。格式见 [§hostfile 格式](#hostfile-格式)。

**YAML 来源优先级：** 集群已有类似 Deployment → `kubectl get deploy <APP> -n <NS> -o yaml` 为准；**从零新建** → 复制 `templates/multi-node-gpu-deployment.yaml` 或 `templates/examples/` 中示例。

远程集群优先经跳板 MCP / bastion 执行 kubectl（`bastion_exec`、`k8s_exec`、`k8s_list_pods`、`remote_read_file`）。

**架构**：本地 MCP 客户端 → bastion-k8s-mcp（本地 npx 进程）→ SSH 登录堡垒机 → 在堡垒机上执行 `kubectl`。因此本地直接 `ssh` 到堡垒机常因缺少公钥或 `BatchMode` 而失败，推荐始终通过 MCP 工具操作。配置示例见本 Skill 下的 [`mcp/bastion-k8s.example.json`](mcp/bastion-k8s.example.json)；Cursor 用户通常粘贴到 `~/.cursor/mcp.json`。

---

## 使用前确认

| 变量 | 说明 | 示例值 |
|---|---|---|
| `NS` | namespace | `prod-gpu` |
| `APP` | Deployment 名 | `my-train-pool` |
| `LABEL` | `nodeSelector.assigment` | `gpu_pool_a` |
| `MOUNT` | PVC 挂载点 | `/mnt` 或 `/home/jd` |
| `PROJECT` | 项目子目录（相对挂载点） | `llm_pretrain` |
| `SLOTS_PER_NODE` | hostfile 每行 slots | `8` |

**存储：** PVC 名 ≠ 容器路径；RWX PVC 多 Pod 共享；`emptyDir`（如 `/dev/shm`）每 Pod 独立。

**注意**：Skill 内部统一使用 `assigment` 作为 node label key（注意拼写）。若目标集群使用不同拼写，请在 YAML 和脚本中相应修改。

**集群硬模式：** `assigment` label + `hostNetwork: true` + `hostPort: 62216` → 必须 `podAntiAffinity`；多机共享数据 **禁止** hostPath。

---

## hostfile 格式

**纯文本，不是 YAML。** 业务启动器（如 Megatron `--hostfile`、多机 SSH 脚本）按行读取；`templates/` 里 Deployment 用 `.yaml`，hostfile 用无扩展名或 `.example` 文本。

结构示例：`templates/hostfile.example`（仅示意行格式，说明见本节）。

**行格式（计划与运行时相同）：**

```text
<IPv4> slots=<N>
```


| 规则       | 说明                                              |
| -------- | ----------------------------------------------- |
| 每行一台节点   | 第一列为 **宿主机 IP**（`status.hostIP` / 计划 IP）        |
| `slots=` | 该节点参与业务的槽位数，通常 = 每 Pod GPU 数（`SLOTS_PER_NODE`）  |
| 注释       | 工作副本可用 `#` 开头行作备注；核对行数时与空行忽略。模板文件保持无注释          |
| 顺序       | 运行时生成后 `sort -V`；第一行常为 master/rank0，需固定时可生成后改首行 |


**两套 hostfile 区别（勿混用）：**


| 类型            | 何时      | IP 来源                  | 行数等于                   |
| ------------- | ------- | ---------------------- | ---------------------- |
| **计划**（场景 B）  | apply 前 | 人工选定目标节点               | `replicas` = label 节点数 |
| **运行时**（场景 D） | apply 后 | Running Pod 的 `hostIP` | 业务参与节点数（可 < replicas）  |


典型推理/Service **不需要 D**；分布式训练、多机 SSH 编排 **需要 D**（若启动命令要求 `--hostfile`）。

---

## 仅文件同步

**跳过** B/C/D。前提：已知 `NS`、`APP`，且至少一个 Running Pod。

```bash
NS=<namespace>
APP=<deployment-name>
POD=$(kubectl get po -n $NS -l app=$APP --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

kubectl get deploy $APP -n $NS -o yaml | grep -E 'claimName:|mountPath:'
kubectl cp -n $NS ./local $NS/$POD:<MOUNT_DATA>/...
```

---

## 计划 hostfile

复制 `templates/hostfile.example`，填入目标节点 IP。

```bash
LABEL=<label> HOSTFILE=hostfile.plan
while read -r ip _; do
  [[ -z "$ip" || "$ip" == \#* ]] && continue
  nodename=$(kubectl get nodes -o jsonpath="{.items[?(@.status.addresses[?(@.type=='InternalIP')].address=='$ip')].metadata.name}")
  [[ -n "$nodename" ]] && kubectl label node "$nodename" assigment=$LABEL --overwrite
done < "$HOSTFILE"
```

硬约束：`grep -vc` 有效行数 = label 节点数 = YAML `replicas`（在场景 C apply 前核对）。

```bash
NS=<namespace> LABEL=<label> APP=<app> HOSTFILE=hostfile.plan
echo "plan: $(grep -vc '^#\|^$' $HOSTFILE)  label: $(kubectl get nodes -l assigment=$LABEL --no-headers | wc -l)  replicas: $(kubectl get deploy $APP -n $NS -o jsonpath='{.spec.replicas}')"
```

**B 完成后通常直接进入场景 C（部署流程）** 进行 `kubectl apply`。

---

## 部署流程

**推理 / 服务 / 训练池（场景 C，常接 B 之后）：**

```text
确认 NS / APP / LABEL / PVC
→ （可选）场景 B：计划 hostfile + label
→ 改 YAML（get -o yaml 或复制 templates/ 下 Deployment 模板）
→ kubectl apply -f <yaml>
→ kubectl cp 上传脚本/模型
→ 容器内启动业务（推理/服务通常到此结束；要 hostfile 则继续 D）
→ Pending 见下文
```

### YAML 检查清单

- [ ] `metadata.namespace` = `$NS`
- [ ] `app` 在 name / labels / selector / podAntiAffinity **一致**
- [ ] `spec.replicas` = 计划 hostfile 有效行数（若用了 B）
- [ ] `nodeSelector.assigment` = `$LABEL`
- [ ] hostPort 62216 → podAntiAffinity
- [ ] PVC claimName / mountPath 与 `$NS` 内实际 PVC 一致

---

## 运行时 hostfile

**场景 D**：业务启动命令或编排器要求 hostfile。**典型推理不需要。**

```text
运行时有效行数 = 参与节点数（训练常称 worldsize；replicas 可更大）
```

```bash
NS=<namespace> APP=<app> NODE_COUNT=<N> SLOTS_PER_NODE=8 POD=<Running Pod>
kubectl get po -n $NS -l app=$APP --field-selector=status.phase=Running \
  -o jsonpath="{range .items[*]}{.status.hostIP}{\" slots=${SLOTS_PER_NODE}\n\"}{end}" \
  | sort -V | head -n $NODE_COUNT > hostfile.runtime

kubectl cp hostfile.runtime $NS/$POD:<MOUNT_DATA>/<project>/hostfile
```

运行时文件通常由上方命令生成，勿手填 IP；`--worldsize` 等启动参数由具体业务定义。格式参考 `templates/hostfile.example`。

---

## 多机网络健康检查（mccl_bench.sh）

**适用场景**：训练池或推理池（含小规模如 4 机推理）在 Pod Running 后、正式启动业务前，验证节点间网络连通性与带宽。

脚本位置：`scripts/mccl_bench.sh`（MUSA 环境专用，依赖 MCCL / MUSA 栈）。

**推荐在以下时机执行**：

- 新建多机池（场景 C）后
- 运行时 hostfile 生成后（场景 D 前）
- 怀疑存在坏节点/坏链路时

**执行方式**（以 4 机推理池为例）：

```bash
NS=<namespace>
APP=<deployment-name>
POD=<任意 Running Pod>
MOUNT=<MOUNT_DATA 或 MOUNT_CODE>

# 1. 生成/准备目标 hostfile（可截取计划 hostfile，或从 Running Pod 生成 4 行）
#    例如只测当前推理池的 4 个节点
kubectl get po -n $NS -l app=$APP --field-selector=status.phase=Running \
  -o jsonpath="{range .items[*]}{.status.hostIP}{\" slots=8\n\"}{end}" \
  | sort -V | head -n 4 > hostfile_4node

# 2. 拷贝脚本与 hostfile 到 PVC
kubectl cp scripts/mccl_bench.sh $NS/$POD:$MOUNT/<project>/
kubectl cp hostfile_4node $NS/$POD:$MOUNT/<project>/

# 3. 在 Pod 内执行（推荐用 --netcheck 快速定位问题节点）
kubectl exec -it -n $NS $POD -- bash -c "
  cd $MOUNT/<project>
  chmod +x mccl_bench.sh
  ./mccl_bench.sh hostfile_4node --netcheck
"
```

**--netcheck 模式特点**：

- Phase 1：两两配对并发测试
- Phase 2：对 Phase 1 失败节点用通过节点交叉验证，精确定位 problematic IP
- 自动输出总结与坏节点列表
- 可通过环境变量 `NETCHECK_AVG_BW_MIN` 调整带宽阈值（默认 170 GB/s）

无 `--netcheck` 时支持 `--worldsize N` 分组并行测试，适合大规模训练池。

**注意**：脚本为 MUSA/MCCL 环境定制，路径与环境变量已针对本集群优化。如需在其他环境使用，需相应调整 `mpirun` 参数与 `MCCL_`* 变量。

---

## 多机训练编排（auto_fault_manager.sh）

**说明**：本章节提供的 `auto_fault_manager.sh` 是 MUSA 集群多机训练的一种**可选启动与运维框架**。用户也可以直接使用 `dist_run_xxx.sh` 或自行编写启动脚本，不一定需要通过本脚本。

**适用场景**：MUSA 集群多机训练（≥2 机）。支持从双机验证到 128 机及更大规模的生产训练。

### 脚本位置与依赖

- 主脚本：`scripts/auto_fault_manager.sh`
- 配套脚本（位于同一 `scripts/` 目录，由 manager 集成调用或用户手动触发）：
  - `mccl_bench.sh`：网络健康检查（`--netcheck` 模式）
  - `hang_detect.sh`：Hang 检测与远程堆栈 dump
  - `stop_all.sh`：清理 GPU 进程

### 核心能力

`auto_fault_manager.sh` 是一个训练编排与故障管理框架，主要职责包括：

- **训练启动**：通过 `--dist-run` 参数调用用户指定的 per-node 启动脚本（不同训练任务的差异点）
- **故障恢复**：监控训练进程、dmesg XID、OOM、日志错误模式，自动重启训练
- **告警**：支持钉钉/微信 webhook，异常时推送告警
- **守护进程与 HA**：`--daemon` 模式、cluster lock、PID 文件管理、多实例互斥

网络健康检查与 Hang 检测通过集成调用 `mccl_bench.sh` 和 `hang_detect.sh` 实现。

### hostfile 与 worldsize 的关系

- `--hostfile`：计划 hostfile，行数 = label 节点数 = YAML `replicas`（Pod 池大小）
- `--worldsize`：实际参与训练的节点数（从 Running Pod 中选取）

**Pod 池可以大于训练规模**。例如：

- 计划 hostfile 132 行 → 打 label 132 个节点 → Deployment `replicas=132`
- 实际训练 `--worldsize 128` → manager 从 132 个 Running Pod 中选取 128 个生成运行时 hostfile

多出的节点作为池冗余或热备。训练 hostfile 行数始终等于 `--worldsize`。

### 典型用法（MUSA 集群）

```bash
# 1. 健康检查（推荐在启动前）
./mccl_bench.sh hostfile.128 --netcheck

# 2. 拉起训练（示例）
LOG_NAME=<name>_YYYYMMDD bash auto_fault_manager.sh \
  --hostfile hostfile.128 \
  --worldsize 128 \
  --dist-run <dist_run_script> \
  --output-dir /home/jd/.../outputs/<name>_... \
  --startup-grace 1800 \
  --hang-minutes 60 \
  --daemon
```

常用参数：

- `--dist-run`：指定 per-node 启动脚本（不同训练任务的差异点）
- `--daemon`：后台守护模式
- `--hang-minutes`：hang 阈值（默认 10 分钟无 step/loss 则触发 dump）
- `--startup-grace`：训练启动宽限期（避免 init 阶段被误杀）

### 停止与清理

```bash
# 停止 manager（不杀训练）
bash auto_fault_manager.sh --hostfile hostfile.128 --worldsize 128 --stop

# 清理残留 GPU 进程
bash stop_all.sh hostfile.128
```

---

## 清理 GPU 进程（stop_all.sh）

**适用场景**：

- 训练或推理任务异常退出后
- 重新部署多机池（场景 B/C）前
- 怀疑节点上有残留进程占用 GPU 时

**MUSA 环境说明**：脚本通过 `mthreads-gmi` 获取 GPU 上的 PID 并远程 kill。在 MUSA 集群上这是清理 GPU 进程的标准方式，依赖 `mthreads-gmi` 是合理的。

脚本位置：`scripts/stop_all.sh`。

**执行方式**（示例）：

```bash
NS=<namespace>
APP=<deployment-name>
POD=<任意 Running Pod>
MOUNT=<MOUNT_DATA 或 MOUNT_CODE>

# 准备 hostfile（可使用计划 hostfile，或从当前 Running Pod 生成）
# 例如清理整个训练池
kubectl get po -n $NS -l app=$APP --field-selector=status.phase=Running \
  -o jsonpath="{range .items[*]}{.status.hostIP}{\" slots=8\n\"}{end}" \
  | sort -V > hostfile_all

# 拷贝脚本与 hostfile
kubectl cp scripts/stop_all.sh $NS/$POD:$MOUNT/<project>/
kubectl cp hostfile_all $NS/$POD:$MOUNT/<project>/

# 执行（并行度默认 32，可通过第二个参数调整）
kubectl exec -it -n $NS $POD -- bash -c "
  cd $MOUNT/<project>
  chmod +x stop_all.sh
  ./stop_all.sh hostfile_all 64
"
```

**输出说明**：

- `killed: pid1,pid2`：成功 kill 的进程
- `no_gpu_process`：该节点上没有 GPU 进程
- `FAILED: pid`：kill 失败的进程
- `SSH_FAILED`：无法通过 SSH 连接到该节点

脚本内部使用 `ssh -o BatchMode=yes`，因此要求目标节点已配置免密登录（或通过堡垒机中转）。

---

## Pending 速查

```bash
kubectl describe pod -n $NS <Pod> | grep -E 'FailedScheduling|port|Insufficient'
```


| 原因                   | 处理                  |
| -------------------- | ------------------- |
| hostPort 62216 占用    | 下线冲突 Pod 或换节点       |
| label 节点数 < replicas | 补 label 或减 replicas |
| 改 label 不驱逐旧 Pod     | 需人工协调               |


Pending 在 **label + replicas + apply** 后可见；写 PVC 须 **Running Pod 存在**。
