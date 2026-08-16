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
10. 优化记录模板
11. 常见负结果

## 1. 指标与 Trace 口径

### 1.1 基线指标

至少记录：

- 稳态 step time、tokens/s、samples/s、MFU；
- forward、backward、optimizer 分段时间；
- allocated、reserved、峰值显存和碎片；
- loss、梯度范数和最终精度；
- 多卡扩展效率和通信占比。

排除首步 checkpoint 加载、lazy initialization、native extension 编译、allocator 扩容、communicator 初始化、autotune 和 cache 填充。

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

融合后重新检查寄存器、shared memory、occupancy、workspace 和 backward 保存量。

### 4.3 用显存换性能

- 增大 micro-batch；
- 按层减少 activation checkpointing；
- 预取下一层 FSDP 参数；
- 保留通信 double buffer；
- 缓存静态位置编码和索引；
- 对固定 shape 使用 MUSA Graph 或编译图。

必须记录所有 rank 的峰值显存。

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

## 10. 优化记录模板

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

## 11. 常见负结果

| 方案 | 常见原因 | 处理方式 |
| --- | --- | --- |
| 合并 Q/K/V Linear | 新 GEMM shape 不适合原 kernel | 以真实 shape 端到端结果决定是否保留 |
| merged gate/up FC1 | 融合后 layout、workspace 或 kernel 变差 | 分阶段测试 projection 与 activation |
| FSDP direct copy | 目标拓扑中不在关键路径 | 检查主 stream pack/unpack 和暴露时间 |
| GroupGEMM + SwiGLU + route weight 一次性融合 | 逻辑过多，难归因且 backward 复杂 | 拆分阶段逐项验证 |
| 仅设置异步通信 | event、copy 或后续 wait 仍串行 | 用 timeline 验证实际 overlap |

记录失败配置、Trace、shape、版本、显存和误差，避免团队重复投入。
