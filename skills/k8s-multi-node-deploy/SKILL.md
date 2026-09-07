---
name: k8s-multi-node-deploy
description: Prepare Kubernetes multi-node MUSA GPU pools, verify Pod ownership and shared storage, generate hostfiles, and diagnose Pending or MCCL network failures. Use for Deployment, PVC, hostfile, and dedicated-pool operations; simple SSH/Docker connections use the existing connection workflow.
---

# Kubernetes 多机 MUSA 工作区

先区分文件同步、部署修改、hostfile 生成、网络检查和故障恢复。只做用户请求的阶段，沿用当前会话已授权范围。已有 Pod 的文件同步不需要重新打标签、apply 或启动训练。

## 确认执行身份

- 优先使用当前集群已配置的 `bastion-k8s` MCP；kubectl 可在堡垒机运行，本机没有 kubectl 不构成阻塞。
- 从现场确认 context、namespace、Deployment、容器、镜像 digest、节点和 PVC/挂载。不要把示例集群、端口、版本或路径当作当前值。
- 每次重新读取 Deployment 的 `.spec.selector`（含 matchExpressions），按 owner UID 验证 Deployment → ReplicaSet → Pod，要求 Running、Ready 且未终止；标签相同不等于属于目标部署。完整 selector 规则见 [Kubernetes 官方说明](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/)。
- `hostNetwork`、`hostPID`、特权模式和 hostPort 仅按目标环境需要采用。所附 `assigment` 拼写及 62216 端口属于历史集群约定；共享多机数据使用已核验的共享存储，不能把节点本地 hostPath 当作共享 PVC。
- 节点标签写入、apply、重启、GPU benchmark、stack attach 和进程清理分别按当前任务授权执行。部署准备本身不授权清理既有任务或发送 webhook 告警。

## 文件同步与 hostfile

同步前确认源/目标文件、现有修改和容器；共享 PVC 一次复制即可。显式指定 `kubectl cp/exec -n <namespace> -c <container>`。

计划 hostfile 来自已选择节点，运行时 hostfile 来自实际参与的 Ready Pod。`slots` 是每节点进程槽位；节点数、GPU 数、分布式 rank world size 按 launcher 定义区分。只在已验证 hostNetwork/SSH 拓扑下采用宿主机 IP。

在同一次只读会话中通过 MCP 或 kubectl 采集：

```bash
kubectl get deployment "$APP" -n "$NS" -o json > deployment.json
kubectl get replicasets -n "$NS" -o json > replicasets.json
kubectl get pods -n "$NS" -o json > pods.json
python3 <skill-root>/scripts/hostfile_from_pods.py \
  --deployment deployment.json --replicasets replicasets.json --pods pods.json \
  --container "$CONTAINER" --nodes "$NODE_COUNT" --slots "$SLOTS_PER_NODE" > hostfile.candidate
```

脚本只读快照，拒绝归属/Ready 不符、节点不足、重复节点或槽位超过 GPU 配额的情况；生成顺序按 IPv4 排序。还需人工核对镜像、挂载、通信端口和 master 选择。采集后发生 rollout 时重新采集；脚本不验证 GPU 健康，不代表训练验收。成功后审查 candidate，再复制到已核验目标，不能直接重定向覆盖活动 hostfile。

## 按需深入

- 部署/计划 hostfile/Pending：阅读 [操作参考](references/operations.md)，优先以当前类似 Deployment 为基线，核对差异后 apply。
- 新建 YAML：使用 [模板](templates/multi-node-gpu-deployment.yaml)；[历史示例](templates/examples/jd_llm_pretrain_test.yaml) 仅展示结构，不能原样部署。
- MCP 配置：阅读 [配置说明](mcp/README.md)，保留当前已核验版本，不因示例版本升级或降级客户端。
- MCCL：`scripts/mccl_bench.sh` 需要 Bash 4+、GNU 工具、OpenMPI 和目标 MUSA/MCCL 栈。路径、bond0、message size 和 170 GB/s 阈值为历史环境设置，先适配再在授权资源内测试。`MPIEXEC` 可指定启动器。非零结果停止扩大实验，不把可疑 IP 判定为硬件故障。
- 故障管理：`scripts/auto_fault_manager.sh` 只用于整个 hostfile 均可清理的专用池；启动需 `--allow-pool-cleanup`，`--max-restarts` 默认 3。`--no-start` 仍会检查/清理，并非只读。未知锁 owner 或陈旧心跳须核验进程身份后人工恢复，不能自动删锁。配置文件为可信 shell 代码；勿加载来源不明配置。
- 清理：`scripts/stop_all.sh HOSTFILE [MAX_PARALLEL]` 默认只列候选；只有已授权清理所列节点全部 GPU 进程时加 `--execute --all-gpu-processes`。hostPID 可能暴露其他 Pod 进程，共享节点禁止采用这种池级清理。
- Hang：`scripts/hang_detect.sh` 的堆栈工具可能暂停进程，仅在授权内使用；默认写入日志目录的 `stack-dumps/`。GPU 显存和日志静默是线索，须结合训练进程身份与 rank 进度确认故障。

交付时列明已修改、已同步、实际执行命令和退出码，以及 GPU/通信/HA/恢复尚未验收项。
