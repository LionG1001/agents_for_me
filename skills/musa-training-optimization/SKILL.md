---
name: musa-training-optimization
description: 面向 MUSA、torch_musa、MCCL 环境的大模型训练性能分析与工程优化。用于建立可信性能基线、分析 PyTorch/MUSA Trace、定位计算/访存/启动/通信/显存瓶颈，评估 fused kernel、MoE、FSDP/HSDP、优化器、重计算、lm_head/loss 和通信重叠方案，以及实施带数值验证、环境开关和 eager fallback 的优化。用户要求审查训练性能、解释 step time、比较 A/B Trace、移植 CUDA 优化到 MUSA、设计或验收训练优化时使用。
---

# MUSA 训练性能优化

## 目标

以端到端训练收益为目标，执行“基线—证据—假设—实现—验收—保留或回滚”的闭环。同时保护数值精度、峰值显存、分布式稳定性和回退能力。

不要把单个 kernel 变快、API 名称带 `fused`、`async_op=True` 或补丁成功安装，直接当作训练已经变快的证据。

## 执行原则

1. 先确认用户授权范围。诊断或审查只执行只读检查；只有用户明确要求修改时才改代码、环境或远端任务。
2. 固定实验条件后建立稳态基线，排除首步编译、通信初始化、allocator 扩容和 profiler 开销。
3. 一次只验证一个主要变量，保留可复现的基线和回退开关。
4. 优先修复异常 kernel、错误 fallback 和全局同步，再处理低占比的小算子。
5. 同时报告 step time、目标模块 GPU 时间、峰值显存、loss/梯度和适用边界。
6. 没有目标 MUSA 设备上的运行结果时，只能声称“静态检查通过”或“方案已接入”，不得声称性能或精度已验证。
7. 每条 MUSA/GPU 命令前先检查目标卡上的活跃进程、显存占用和任务归属；不得抢占或停止未获授权的任务。
8. 将假设来源标成 Trace 驱动、代码审计、平台文档或用户提供经验；来源不同不改变验收门槛。
9. 先证明优化路径 imported、reachable、default-on、observed 和 fallback，再讨论收益；配置存在不等于 kernel 已执行。
10. 高风险或高成本优化先形成带 `proposal_id`、`action_id` 的提案。用户尚未授权实现时，只输出提案；实现时一次只落地一个已批准 action。

## 工作流

### 1. 明确目标和实验边界

先收集并记录：

- 优先目标：step latency、tokens/s、MFU、显存容量或扩展效率；
- 模型、代码版本、数据切片、随机种子和动态 shape 分布；
- batch、sequence length、梯度累积和 activation checkpointing；
- DP、TP、PP、EP、CP、FSDP/HSDP 拓扑；
- 参数、梯度、优化器状态和计算 dtype；
- 驱动、PyTorch、torch_musa、MCCL、MATE、muDNN 和 Transformers 版本；
- 所有节点的容器、代码、依赖和环境变量一致性。

信息缺失但仍可安全分析时，明确假设并继续；缺失项会改变实现或实验结论时，先向用户确认。

### 2. 审计实际执行路径

对 kernel、optimizer、precision、环境变量、extension 和 fused path 建立五态矩阵：

| 状态 | 要回答的问题 |
| --- | --- |
| imported | 依赖和扩展是否成功加载，版本是否符合预期？ |
| reachable | 当前模型、dtype、shape、layout 和 device 是否能进入该分支？ |
| default-on | 不额外设置开关时，默认是否启用？ |
| observed | 日志、hook、Trace 或 profiler 是否证明真实 kernel 已执行？ |
| fallback | 不支持或失败时回到哪里，是否会每 step 重试或静默改变语义？ |

同时追踪配置源头和优先级：YAML、launcher、命令行、环境变量、框架默认值和 import-time 读取。默认值、显式 opt-out、日志和文档必须一致。发现配置写了但执行路径未命中时，先修正事实链，不做无效 A/B。

### 3. 建立可信基线

执行以下动作：

- 预热若干 step，只统计稳定区间；
- 记录多个 step 的平均值、中位数和波动范围；
- 同时记录 tokens/s、峰值 allocated/reserved memory、loss 和梯度范数；
- 对比 profiler 开启和关闭时的 step time；
- 多机训练先验证每个 rank 的版本、代码和拓扑一致。
- 跨设备对比时可记录相对参考设备的归一化吞吐和显存，但必须对齐模型、精度、batch、shape、卡数和软件栈，不用未对齐 QPS 宣称平台优劣。

不得使用单个冷启动 step 判断收益。

### 4. 从 Trace 建立证据链

优先计算四个时间指标：

- Step wall time；
- GPU kernel 累计时间；
- 跨 stream 区间合并后的 GPU active union；
- 第一个到最后一个 kernel 的 GPU kernel span。

使用以下关系判断重叠和空闲：

```text
跨 stream overlap = kernel 累计时间 - GPU active union
GPU idle          = GPU kernel span - GPU active union
GPU 活跃率         = GPU active union / step wall time
```

通过 correlation id 将 GPU kernel 映射到 runtime launch，再定位到最内层 CPU op、外层 annotation、自定义 autograd function 和 Python 模块。分别统计 exclusive 与 inclusive GPU 时间，避免重复累加嵌套模块。

按以下模块汇总后再下钻：

1. 数据与视觉/VQ 前处理；
2. Attention/MLA；
3. Dense MLP 或 MoE Router、permute、GroupGEMM；
4. lm_head/loss；
5. backward 和重计算；
6. FSDP/HSDP 与 collective；
7. optimizer；
8. 数据加载、CPU launch 和同步。

### 5. 判断瓶颈类型

根据证据选择主瓶颈，不要只看调用次数：

- 大型 GEMM、GroupGEMM、Attention 占主导且 GPU 活跃率高：计算瓶颈；
- Add、Mul、Cast、Copy、Zero、Cat、Norm 等完整 tensor 操作占比高：显存带宽瓶颈；
- 大量短 kernel 和 timeline 碎片空隙：launch/latency 瓶颈；
- collective 暴露在关键路径且扩展效率下降：通信瓶颈；
- OOM 迫使更多重计算、更小 batch 或 offload：显存容量瓶颈。

需要更细的决策表、环境参数和候选优化时，读取 [references/musa-training-playbook.md](references/musa-training-playbook.md)。

### 6. 形成提案、估算收益并排序

使用 Amdahl 思路估算端到端上限：目标模块占 step 的比例，就是完全消除该模块时的理论收益上限。

按以下顺序优先处理：

1. 明显异常的 kernel、错误实现选择和意外 fallback；
2. `.item()`、`.tolist()`、device tensor 条件判断等同步；
3. 已有成熟 MUSA/MATE/muDNN fused fastpath；
4. 冗余计算、cast、copy、cat、contiguous、zero 和静态结果重复生成；
5. batch、重计算和显存换性能；
6. optimizer、lm_head/loss 和 MoE 数据搬运；
7. 真正暴露的通信与 overlap；
8. 高占比 elementwise 链融合；
9. 复杂分布式 pipeline 或底层 GEMM/Attention kernel。

若 Trace 明确显示其他模块占主导，以 Trace 为准调整顺序。

每轮提案默认给 2–3 个候选，并分成低风险配置/路径优化、中风险数据流或融合、高风险 native kernel 或分布式流水。每个 action 至少写明：

- `proposal_id`、`action_id` 和假设来源；
- Trace/代码证据、真实 shape、调用次数和目标代码位置；
- 目标模块占 step 的比例、Amdahl 理论上限和预期信号；
- 实现边界、依赖、回退开关和风险；
- correctness、局部算子、目标训练吞吐三道门禁；
- 采纳、继续试验或回滚的判定标准。

如果用户只要求计划或 review，到此停止，不提前修改代码或占用 GPU。

### 7. 设计 MUSA 优化实现

优先复用 PyTorch、torch_musa、MATE、muDNN 和平台已有算子，包括 RoPE、RMSNorm、SwiGLU、GroupGEMM、FlashAttention、fused cross entropy、fused optimizer 和 token permute。

接入 fastpath 时必须：

- 明确支持的模型、MUSA/PyTorch/Transformers 版本、dtype、device、shape、layout 和 contiguous 条件；
- 同时检查 forward 和 backward；
- 避免为了 fused kernel 新增更昂贵的 cast、permute、contiguous 或 workspace；
- 为 unsupported case 保留语义等价的 eager fallback；
- 使用默认安全的环境变量开关支持 A/B 和紧急回滚；
- 延迟导入 MUSA 专用依赖，避免破坏 CPU/CUDA 或无 MUSA 环境；
- 将“补丁已安装”和“首次真实 fastpath 成功”分开记录；
- kernel 首次失败后采用明确的降级策略，避免训练每步重复抛异常；
- 不吞掉 OOM、数据损坏或会破坏训练正确性的严重错误。

从真实数据流设计融合，而不是只按算子名称设计：

- 先写清 producer 输出 layout、consumer 需要的 layout 和 backward 需要保存的状态；
- 优先让 GEMM/融合算子直接写出 consumer 所需 layout，避免事后 `permute().contiguous()`；
- 检查 forward 已经 materialize 的低精度权重视图、索引、mask 和 layout 是否能由 backward 安全复用；
- 复用必须定义生命周期、版本和失效条件，不能复用可训练权重的过期副本；
- grouped operation 必须使用 observed shape 验证组数、bias、stride 和空组，不因 API 支持就默认更快；
- optimizer flat buffer 必须保持参数组、weight decay、step、state、ZeRO/sharding 和 checkpoint 语义，并计算 pack/copy 成本。

缓存静态结果时，将 shape、device、dtype、配置和权重版本纳入 cache key。权重可训练或动态变化时禁用缓存或主动失效。

### 8. 验证计算、通信与更新重叠

不要只检查 `async_op=True`。在 timeline 中验证：

- 通信和计算是否位于不同 stream/engine；
- pack/copy-in、collective、unpack/copy-out 分别在哪里执行；
- event/wait 是否过早；
- 目标通信与其他 stream 的时间交集；
- buffer 是否在异步操作完成前被释放或复用；
- allocator 的 record-stream 语义是否与配置一致。

使用下式估算暴露通信：

```text
近似暴露时间 = 目标通信 GPU 时间 - 与其他 stream 的重叠时间
```

若 overlap 后 step 没变快，定位等待是否只是移动到了后续同步点。

若进一步尝试 bucket 级 communication-update pipeline，还必须证明：

- 每个 bucket 的梯度归一化语义与原实现一致，SUM/AVG 的位置没有重复或遗漏；
- bucket 到 flat-buffer segment 的映射稳定，参数更新不会早于梯度完成；
- optimizer state 和参数不会被下一 bucket、下一 micro-step 或 checkpoint 并发读写；
- device-aware Future/event 保留正确 stream 依赖，没有退化成 host/global synchronize；
- DeepSpeed/DDP/FSDP wrapper 没有在后续再次执行同一参数更新。

MCCL channel、buffer 和 ACE 等参数先做真实 message size 的小范围 sweep；平台案例中的最优值不能直接设为通用默认。

### 9. 执行三级门禁和四类验收

按顺序执行，前一门失败就停止扩大实验：

1. correctness gate：固定输入的 forward、backward、参数更新和边界条件；
2. local/operator gate：真实 shape microbenchmark，确认目标模块本身变快且新增搬运没有吞掉收益；
3. target-training gate：目标 batch、数据、拓扑下的稳态端到端 A/B。

每项优化至少覆盖：

1. 数值：forward、backward、参数更新、误差统计、特殊值、空 tensor/零 token 和短训练 loss；
2. 性能：真实 shape microbenchmark、稳定 step A/B、多 shape、多拓扑和端到端收益；
3. 显存：所有 rank 的 allocated、reserved、峰值、workspace、缓存和长时碎片；
4. 稳定性：fallback、环境隔离、多机变量传播、checkpoint/resume 和长时间训练。

只有四类验收满足用户目标后，才能建议默认启用。性能变慢、收益在噪声内、精度超界或显存风险过高时，保留负结果并回滚默认路径。

实现完成后同步检查 launcher contract：参数解析、YAML/命令行/环境变量优先级、默认值、`=0` opt-out、日志和 README。优化默认开启前必须保留快速回滚路径。

## 特定任务处理

### 审查优化代码

重点检查：

- 是否覆盖了所有真实调用路径；
- 是否错误改变输出 shape、loss 语义或 optimizer 选择；
- 自定义 loss、评估、`return_outputs`、label smoother 和分布式 wrapper 是否仍兼容；
- fastpath 失败是否可观测且不会反复重试；
- 环境变量是否放在正确配置层，是否默认安全；
- 测试是否覆盖 dense/fused 数值与梯度、边界 shape 和 fallback。

按严重程度先报告正确性和稳定性问题，再报告性能问题。

### 从 CUDA 优化迁移到 MUSA

先提取算法语义和 fastpath 前置条件，再映射到 torch_musa、MATE 或 muDNN 能力。不要机械替换 `cuda` 为 `musa`。重新验证 dtype、layout、stream、autograd、编译方式、环境变量和不支持场景。

### 输出优化建议

按“proposal/action—证据—瓶颈—理论上限—实现—风险—三级门禁—预期优先级”组织建议。区分 Trace 驱动与外部经验驱动；证据不足时先给采集方案，不编造收益百分比。

### 修改训练代码

保持改动最小，避免修改安装目录中的 Transformers；优先使用项目自有 runtime patch 或适配层。修改后运行静态检查、目标单测和 MUSA 设备训练 A/B。未经用户明确授权，不同步远端、不停止任务、不启动训练。

## 资源路由

读取 [references/musa-training-playbook.md](references/musa-training-playbook.md) 获取：

- 瓶颈类型与优化动作对照表；
- MUSA/MCCL 候选环境变量及使用边界；
- FSDP/HSDP、MoE、optimizer、lm_head/loss 的检查清单；
- 数值、性能、显存和稳定性验收矩阵；
- runtime path 五态矩阵、提案/实现契约和 launcher contract；
- consumer-first layout、forward/backward materialization 复用；
- flat-buffer optimizer 与 bucket 级 communication-update pipeline；
- 统一优化记录模板和常见负结果。
