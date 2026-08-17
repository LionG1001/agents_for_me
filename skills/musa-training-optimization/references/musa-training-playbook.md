# MUSA 大模型训练优化手册

## 目录

1. 指标与 Trace 口径
2. 瓶颈决策表
3. MUSA fastpath 检查清单
4. 高价值优化候选
5. FSDP/HSDP 与通信重叠
6. MoE 优化清单
7. lm_head、loss 与 optimizer
8. MUSA/MCCL 环境变量候选
9. 验收矩阵
10. Runtime path 与提案契约
11. 数据流、layout 与 materialization
12. Flat-buffer optimizer 与 bucket 流水
13. Launcher contract
14. 优化记录模板
15. 常见负结果

## 1. 指标与 Trace 口径

### 1.1 基线指标

至少记录：

- 稳态 step time、tokens/s、samples/s、MFU；
- forward、backward、optimizer 分段时间；
- allocated、reserved、峰值显存和碎片；
- loss、梯度范数和最终精度；
- 多卡扩展效率和通信占比。

排除首步 checkpoint 加载、lazy initialization、native extension 编译、allocator 扩容、communicator 初始化、autotune 和 cache 填充。

若报告相对另一类设备的性能折算比，分子和分母必须使用相同模型、精度、batch、shape、卡数、数据、训练阶段和计时边界，并同时报告绝对吞吐与峰值显存。跨设备折算用于描述工程目标，不替代本设备上的 A/B Trace。

### 1.2 GPU 时间口径

```text
跨 stream overlap = kernel 累计时间 - GPU active union
GPU idle          = GPU kernel span - GPU active union
GPU 活跃率         = GPU active union / step wall time
近似暴露通信       = 通信 GPU 时间 - 与其他 stream 的重叠时间
```

Kernel 累计时间允许大于 wall time，因为多个 stream 可以并发。Inclusive 模块可能嵌套，不得直接求和。

### 1.3 Trace 归因顺序

1. 用 correlation id 关联 GPU kernel 与 runtime launch；
2. 在相同 CPU 线程和时间戳附近定位最内层 CPU op；
3. 向外查找 annotation、自定义 autograd 和 Python 模块；
4. 同时输出 exclusive 与 inclusive GPU 时间；
5. 按真实 shape、dtype、stream 和调用次数聚合。

## 2. 瓶颈决策表

| 证据 | 瓶颈 | 优先动作 |
| --- | --- | --- |
| GEMM、GroupGEMM、Attention 占主导，GPU 活跃率高 | 计算 | 更优 kernel、低精度、shape/layout、减少重计算 |
| Add/Mul/Cast/Copy/Zero/Cat/Norm 大 tensor 链占比高 | 显存带宽 | epilogue fusion、multi-tensor、减少中间 tensor 与搬运 |
| 大量短 kernel，timeline 有碎片空隙 | Launch/latency | foreach、融合、graph/compile、减少 Python 循环 |
| Collective 位于关键路径，扩展效率下降 | 通信 | 链路 benchmark、bucket/coalesce、prefetch、拓扑和 overlap |
| OOM 导致小 batch、更多 recompute 或 offload | 显存容量 | 分层重计算、packing、chunked loss、sharding、低精度 |

优先检查异常：同 shape kernel 慢数倍、错误 Triton/MATE/muDNN 选择、意外 fallback、反复编译、`.item()` 同步、通信带宽明显偏低。

## 3. MUSA fastpath 检查清单

接入 RoPE、RMSNorm、SwiGLU、GroupGEMM、FlashAttention、fused optimizer 等路径时检查：

- `torch`、`torch_musa`、MATE、muDNN 和 Transformers 版本；
- MUSA device availability；
- dtype、layout、stride、contiguous 和 shape 限制；
- forward、backward 和 gradient accumulation；
- GQA/MQA 的 Q/K head 数差异；
- 动态 shape、空 tensor、零 token expert 和长序列边界；
- 新增的 permute、transpose、cast、contiguous 和 workspace；
- runtime patch 是否只影响目标模型和目标后端；
- 不支持场景是否走 eager fallback；
- 首次真实 kernel 成功是否单独记录；
- 首次 kernel 异常后是否避免反复尝试；
- CPU/CUDA 环境导入是否仍安全。

优先修改项目自有适配层，不直接修改安装目录中的 Transformers。

## 4. 高价值优化候选

### 4.1 去除冗余计算

- 缓存冻结权重生成的 RoPE、位置编码、mask、index 和 offset；
- 单 group Router 跳过无意义的 group top-k、mask 和 scatter；
- 避免 `argsort().argsort()` 等重复排序；
- 不为不会使用的输出计算完整 logits 或梯度；
- 在 CPU 侧准备 shape 元数据，减少 device scalar 同步。

缓存 key 至少覆盖 shape、device、dtype、配置和权重版本。

### 4.2 减少完整 tensor 搬运

- 合并 GEMM + bias/scale/add；
- 合并 GEMM + activation + multiply；
- 合并 residual add + normalization；
- 合并 RoPE + layout transform；
- 合并 optimizer 的 momentum、weight decay、cast 和参数更新；
- 合并 token permute、sorting 和 index preparation；
- 复用通信和 optimizer 临时 buffer。

优先采用 consumer-first layout：从消费方所需的最终 layout 反推 producer 的 output descriptor，让 GEMM、GroupGEMM 或融合 kernel 直接写出目标 stride。先生成中间 layout 再执行 `permute().contiguous()`，常会用一次完整 tensor 读写抵消融合收益。

融合后重新检查寄存器、shared memory、occupancy、workspace 和 backward 保存量。

### 4.3 用显存换性能

- 增大 micro-batch；
- 按层减少 activation checkpointing；
- 预取下一层 FSDP 参数；
- 保留通信 double buffer；
- 缓存静态位置编码和索引；
- 对固定 shape 使用 MUSA Graph 或编译图。

必须记录所有 rank 的峰值显存。

### 4.4 复用 forward materialization

逐项检查 backward 是否重复构造 forward 已经存在的：

- BF16/FP16 权重视图；
- transpose/contiguous 权重副本；
- token index、sort/permute 结果；
- mask、offset、position 和 shape 元数据；
- grouped operation descriptor 或 workspace 元数据。

复用前必须证明对象在 backward 消费前仍有效，并把 parameter version、shape、device、dtype、layout 和训练阶段纳入失效条件。可训练参数更新后不得跨 step 复用旧的低精度副本。比较节省的 cast/materialization 时间与额外保存显存。

## 5. FSDP/HSDP 与通信重叠

拆开统计：

```text
all-gather copy-in
    -> all-gather
        -> split/copy-out
            -> layer compute

gradient ready
    -> reduce-scatter pack/copy-in
        -> reduce-scatter
            -> optional HSDP all-reduce
```

检查通信本体之外的 pack、copy-in、split、copy-out 和 `_chunk_cat`。通信本体即使已经隐藏，主 stream 上的搬运仍可能是关键路径。

实现 overlap 时保证：

- producer 完成后通过 event 通知 consumer；
- consumer 只等待对应 buffer，不做全局同步；
- buffer 在异步工作结束前不释放、不复用；
- allocator record-stream/lifetime 与 runtime 配置一致；
- Lazy HSDP 只用于确实存在 replicate all-reduce 的拓扑；
- 比较 overlap 前后等待点，防止只移动等待。

先用真实 message size 执行 all-reduce、reduce-scatter、all-gather 和 All-to-All benchmark，确认 rank/GPU/NIC/NUMA 映射与网卡选择。

### 5.1 从 compute-communication 到 communication-update

先验证普通 backward-compute 与 bucket collective 的重叠，再考虑把已完成 bucket 的参数更新提前，不能一步跳到通信—更新流水。

bucket 级流水需要额外证明：

- collective 的 SUM/AVG 与 gradient scale 语义只执行一次；
- bucket、flat gradient segment、参数和 optimizer state 一一对应；
- gradient accumulation、no-sync、ZeRO/FSDP/DDP wrapper 不会重复更新；
- device Future/event 只建立必要依赖，不引入 host synchronize；
- checkpoint/save、梯度裁剪和全局 norm 在语义正确的时点读取数据；
- 每个 bucket 使用独立或严格分代的 buffer，下一次写入不会覆盖在途数据。

ACE 或其他 native communicator 是高风险候选。普通 MCCL process group 初始化、unique ID 交换、独立 stream、对称 window 和 buffer 生命周期都必须有最小复现与 fallback。

## 6. MoE 优化清单

分别统计并检查：

- Router 和 load balance；
- token sort/permute；
- dispatch/combine All-to-All；
- GroupGEMM 的 token 粒度与 shape；
- SwiGLU 和 route weight；
- shared expert；
- wgrad 的 zero、accumulate 和 cast。

All-to-All 必须等待 Router 输出。路由完成后再考虑与 shared expert、local expert bypass 或分块 GroupGEMM 重叠。

2-chunk A2A/GroupGEMM pipeline 必须为每个 chunk 定义独立输入、通信和输出 buffer 生命周期。

可优先尝试：

- 平台 GroupGEMM 替换异常实现；
- MUSA token permute/sorting 融合；
- SwiGLU fastpath；
- 小 MoE bias 或 balance tensor coalesce；
- 连续内存上的 gradient norm；
- 避免完整 wgrad FP32 zero 后再 BF16 cast。

## 7. lm_head、loss 与 optimizer

### 7.1 lm_head/loss

大词表优先评估：

- vocab parallel；
- chunked lm_head/loss；
- fused linear cross entropy；
- 只对有效监督 token 计算 lm_head；
- sequence packing 减少 padding。

稀疏监督 token 路径必须保护：

- 原始输出 shape；
- 评估和生成；
- `return_outputs=True`；
- label smoother；
- ASFT/DFT/EAFT 和自定义 loss；
- `num_items_in_batch` 为 Python int 或 tensor；
- dense/sparse loss 与梯度一致性。

### 7.2 Optimizer

逐项审计参数、master weight、gradient、momentum、variance、其他状态、sharding/offload 和临时 tensor，不使用固定“参数倍数”估算。

接入 fused optimizer 时不得覆盖用户选择的 GaLore、APOLLO、LoRA+、BAdam、Adam-mini、Muon 或其他 optimizer。限定支持的 optimizer 名称，并在不兼容时回到原选择。

Muon 候选：同 shape 参数 mega-batch、multi-tensor momentum/Nesterov、BF16 cast 融合、Newton-Schulz epilogue、weight decay/参数回写融合和 buffer 复用。

### 7.3 Flat-buffer update

当 Trace 证明 optimizer 存在大量逐参数 launch 和分散 state 访问时，可评估 flat-buffer 或 multi-tensor update。实施前建立参数映射表，至少覆盖：

- parameter group、学习率、beta、eps、weight decay 和 step；
- master parameter、gradient、momentum、variance 和其他状态 dtype；
- contiguous 条件、空梯度、稀疏梯度和共享参数；
- ZeRO/sharding/offload 的本 rank 所有权；
- pack、copy-back、foreach copy 和 checkpoint 序列化成本。

局部 optimizer kernel 变快但端到端 step 不变，通常意味着 pack/copy、通信或前后同步吞掉了收益。只有目标训练 gate 通过才保留。

## 8. MUSA/MCCL 环境变量候选

以下配置只作为同类环境的 A/B 起点，不是通用最优值。升级驱动、torch_musa 或 MCCL 后重新回归。

### 8.1 内存与通信生命周期

```bash
export PYTORCH_MUSA_ALLOC_CONF=expandable_segments:True
export TORCH_MCCL_AVOID_RECORD_STREAMS=1
```

验证动态 shape 的碎片情况，以及异步通信 tensor 是否可能过早释放。

### 8.2 MCCL buffer 和 channel

```bash
export MCCL_BUFFSIZE=20971520
export MCCL_MIN_NCHANNELS=16
```

使用真实 message size 比较 `MCCL_MIN_NCHANNELS=4/8/16/32`，同时记录单机、双机同 rank 和全卡并发带宽。

### 8.3 MUSA runtime 调度

```bash
export MUSA_DEVICE_PAGE_SIZE=0x200000
export MUSA_BLOCK_DISTRIBUTION_GRANULARITY=1
export MUSA_EXECUTE_COUNT=1
```

把这组参数作为候选组合进行 A/B，并在版本升级后重新验证。

环境变量应进入用户指定的配置层。不要擅自写入启动脚本；若项目已有变量管理约定，遵循项目约定。

## 9. 验收矩阵

| 类别 | 最低验收项 |
| --- | --- |
| 数值 | forward、backward、参数更新、max_abs/max_rel、特殊值、空输入、短训 loss |
| 性能 | 真实 shape microbenchmark、稳定 step A/B、多步波动、目标拓扑 |
| 显存 | allocated/reserved/峰值、workspace、缓存、所有 rank、长时碎片 |
| 稳定性 | 开关、fallback、后端隔离、多机传播、save/load、resume、长时间训练 |

数值阈值按 dtype 和任务定义。FP32 是否要求 bitwise 一致、BF16 是否允许量化范围差异，需要明确写入实验记录。

验收按三个 gate 逐层放大：

1. correctness：固定输入的 forward、backward、参数更新、特殊值和边界 shape；
2. local/operator：observed shape microbenchmark，包含新增 layout、cast、pack 和 copy；
3. target training：目标 batch、数据、拓扑和稳态窗口的端到端 A/B。

只有前一 gate 通过才进入下一 gate。默认采纳阈值应高于基线噪声；无统一百分比时，用至少三次独立稳态测量估计噪声带。

## 10. Runtime path 与提案契约

### 10.1 五态事实矩阵

| 路径 | imported | reachable | default-on | observed | fallback |
| --- | --- | --- | --- | --- | --- |
| `<candidate>` | 版本/导入证据 | 模型、dtype、shape、layout 条件 | 默认值和配置源 | 日志、hook、Trace、kernel | 回退路径与首次失败行为 |

不要把 imported 当成 observed，也不要把配置默认打开当成 kernel 成功执行。对 import-time 环境变量，必须在 import 前设置并在启动日志中打印最终值。

### 10.2 Proposal contract

每轮默认给 2–3 个 action，按低、中、高风险分层：

```markdown
proposal_id: PERF-YYYYMMDD-NN
baseline_id: <immutable baseline>

action_id: A1
hypothesis_source: trace | code-audit | platform-doc | user-reference
evidence: <kernel/module/shape/count/time/source location>
amdahl_bound: <target share and theoretical upper bound>
implementation_boundary: <files/modules/topology>
fallback: <flag and eager/reference path>
gates: correctness -> local/operator -> target-training
adopt_when: <threshold above noise, memory and stability limits>
rollback_when: <precision/perf/OOM/stability condition>
```

用户只要求建议、计划或 review 时停在 proposal；没有已经授权的实现范围，不提前占用 GPU 或修改代码。实施阶段一次只执行一个 action，避免收益和回归无法归因。

### 10.3 GPU availability preflight

每条 MUSA/GPU 命令前检查进程、显存、设备健康和任务归属。目标卡忙时，只有在实验条件等价且用户范围允许时才换卡；否则停止并报告。不得以性能测试为由清理未知进程。

## 11. 数据流、layout 与 materialization

优化一个模块前画出：

```text
producer output
  -> dtype/layout transform
  -> consumer input
  -> backward saved tensors
  -> gradient output/layout
```

对每条边记录 shape、stride、dtype、device、调用次数和 tensor 字节数。优先级通常是：

1. 让 producer 直接写 consumer layout；
2. 删除重复 contiguous/transpose/cast；
3. 安全复用 forward 已 materialize 的视图；
4. 再融合 elementwise 和 bias epilogue；
5. 最后才考虑重写底层 GEMM。

GroupedMatMul/GroupGEMM 必须用真实 group 数、每组 M/N/K、bias、空组和 stride 测试。小矩阵或不规则 group 可能因 descriptor、workspace 和调度开销反而更慢。

## 12. Flat-buffer optimizer 与 bucket 流水

分三档推进，逐档验收：

1. foreach/multi-tensor：保持原 optimizer 和 state 结构，仅减少 launch；
2. flat-buffer optimizer：参数、梯度和 state 建立稳定 segment 映射，一次或少量 kernel 更新；
3. communication-update pipeline：bucket collective 完成后，提前更新对应 segment。

第三档必须具备第二档的稳定映射，并与 gradient clipping、accumulation、ZeRO/sharding 和 checkpoint 语义对齐。任何档位都要把 pack/copy-in、kernel、copy-back 和同步计入局部及端到端结果。

## 13. Launcher contract

性能路径不仅是 Python 分支，还包括启动契约：

- argparse、YAML、命令行和环境变量的优先级唯一且有文档；
- 默认值、`=0` opt-out、`auto` 和强制模式语义明确；
- launcher 只转发其职责范围内的变量，不跨层覆盖模型配置；
- import-time 环境变量在导入前设置，并打印最终生效值；
- `run.sh`、profile launcher、README 和测试保持一致；
- runtime 日志打印路径是 fastpath、fallback 还是 disabled；
- 多机所有 rank 获得相同设置。

## 14. 优化记录模板

```markdown
## 优化名称

### 背景
- 模型、commit、设备和软件版本
- batch、sequence、shape 和并行拓扑

### 基线
- 稳态 step time / tokens/s
- 目标模块 GPU 时间
- 峰值显存、loss 和梯度

### Trace 证据
- kernel、次数、累计时间和真实 shape
- stream、overlap 和对应代码位置

### 假设
- 根因和理论收益上限

### 实现
- 修改、fastpath 条件、fallback 和环境变量

### 验证
- 数值、microbenchmark、端到端 A/B、显存和多机结果

### 结论
- 保留或回滚、适用范围和后续工作
```

## 15. 常见负结果

| 方案 | 常见原因 | 处理方式 |
| --- | --- | --- |
| 合并 Q/K/V Linear | 新 GEMM shape 不适合原 kernel | 以真实 shape 端到端结果决定是否保留 |
| merged gate/up FC1 | 融合后 layout、workspace 或 kernel 变差 | 分阶段测试 projection 与 activation |
| FSDP direct copy | 目标拓扑中不在关键路径 | 检查主 stream pack/unpack 和暴露时间 |
| GroupGEMM + SwiGLU + route weight 一次性融合 | 逻辑过多，难归因且 backward 复杂 | 拆分阶段逐项验证 |
| 仅设置异步通信 | event、copy 或后续 wait 仍串行 | 用 timeline 验证实际 overlap |
| 只安装 extension 或设置开关 | 路径未 reachable、未 observed 或静默 fallback | 建立 imported/reachable/default-on/observed/fallback 矩阵 |
| producer 后再做 layout conversion | 完整 tensor copy 抵消融合收益 | 让 producer 直接写 consumer layout |
| backward 重做低精度权重 materialization | 重复 cast、分配和写回 | 在正确生命周期内复用 forward 视图 |
| flat-buffer optimizer | pack/copy-back、ZeRO 映射或 checkpoint 成本过高 | 分档实施并计算完整数据搬运 |
| communication-update pipeline | SUM/AVG、梯度裁剪或更新时序改变 | 先冻结语义，再做 bucket 级依赖验证 |

记录失败配置、Trace、shape、版本、显存和误差，避免团队重复投入。
