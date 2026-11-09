# VeOmni Qwen3.5 优化的可复用经验

适用于分析已采用的训练优化、将实验 fastpath 整理成正常训练实现、复核历史收益、审查数值边界和发布优化 PR。以下来自 2026-10 的 MUSA Qwen3.5-MoE 工作及其历史基线；卡数、版本、shape、对齐长度和开关依赖均是案例条件，不是其他模型的默认参数。复现与交付见第 1–7 节，基线优化机制见第 8 节，回退预热见第 9 节，负结果见第 10 节。

## 1. 建立能解释差距的复现记录

冻结的对象不仅是 Git commit，还包括实际加载的源码、wheel/扩展来源、编译参数、完整启动命令、缓存位置和关键 autotune 结果。保存各 rank 的实际选择，尤其是动态 shape 下可能变化的 kernel 配置。

稳态窗口在运行前确定，同时保留首步编译、预热、所有慢步和完整运行均值。报告平均值、分布及 rank 聚合方式；“窗口平均低于阈值”不等于每个 step 或全程平均都低于阈值。各 rank 的时间受分布式等待耦合，不能把它们当作独立性能重复。

本案例的 8 卡、每卡 50 步记录说明了这一点：

| 实现 | 固定第 10–50 步的各 rank 均值再平均 | 含启动的 50 步平均 |
| --- | ---: | ---: |
| 历史冻结组合，两轮 | 2.99248 / 2.99216 秒 | 约 3.60 秒 |
| 整理后正常入口，两轮 | 3.01463 / 3.01267 秒 | 3.63576 / 3.63793 秒 |

后续确认某个 rank 的 Q/K autotune 配置不同，但尚未证明它造成时间差；两个原生配置的输出也并非逐位相同。正确的下一步是明确参照与数值契约后做配对测量或 Trace，而不是直接固定“历史最快配置”，也不反复运行挑选低于阈值的结果。

要归因单项收益，尽量做时间相近的配对/交错 A/B。历史阶段差值、组合耗时、算子 microbenchmark 和启动预热分别报告；不要把它们相加或分摊为每个 PR 的提升。

## 2. 验证实际输入和分支，避免错误回退

收集代表性的真实路由：token 数、expert 数、top-k、重复 expert、空输入、dtype、stride、每 expert 计数及 metadata 生命周期。均匀随机输入可用于边界扫描，不能替代真实 shape 分布。

为关键 fastpath、回退原因和首次编译保留可观测证据。检查各 rank 应有的核心路径；若子分支仅适用于少数 token 数区间，用适用条件和全局统计验收，不能强制每个 rank 都命中。断言错误与训练失败分开记录，修正测量逻辑时保留原始报告。

案例中，特定 wheel/shape 的 Bool 路由列求和出现错误计数，导致合法请求退出 TE 路径。先用 CPU 整数结果证明计数错误，再只在已验证范围把输入转为 int64 后求和。不要由此推导所有 Bool 求和都应改写；这是限定环境的资格修复。

## 3. 数值契约决定参照和可声称的结论

| 层次 | 要验证的内容 | 不可扩大的结论 |
| --- | --- | --- |
| 路由/索引资格 | CPU 整数参照、重复/无效索引、计数总和 | 整数修复不代表后续浮点路径不变 |
| 单算子 | loss/输出、输入及参数梯度、实际累加顺序、适用边界 | 算子一致不代表完整训练轨迹一致 |
| 受控分布式更新 | reduced gradient、norm/clip、参数和 optimizer moments | 简化 fixture 不代表全模型自由训练 |
| 目标训练 | 实际模型、数据、拓扑、loss/稳定性及性能 | 短训和舍入日志不认证长期收敛或 resume |

具体检查随优化而定：

- **监督 CE：**对照完整词表投影，保留 causal shift、ignore label、归一化和 loss 的上游缩放；检查隐藏状态及输出权重梯度。只跳过无监督位置的输出层计算，前面的 Transformer 仍处理这些 token。
- **Q/K 重复与归一化融合：**省去中间搬运不代表可以交换反向的头归并与归一化顺序。保持低精度舍入/累加语义，并与相同原生配置比较；跨配置比较是另一项实验。
- **TE 整理与合并：**修复计数可能使旧 BF16 原子回退进入固定顺序 FP32 合并。说明路径切换，不能声称与旧错误回退的完整轨迹逐位相同。
- **高阶梯度：**仅在调用契约需要时验证；未支持的范围明确拒绝或走可微原生回退，不把一阶通过扩展到高阶。

## 4. 减少数据搬运，同时保住生命周期

| 优化模式 | 值得复用的做法 | 易遗漏的边界 |
| --- | --- | --- |
| 稀疏监督输出层 | 先筛有效标签，再做 lm_head/CE | 全部/没有监督、SP、shift 和梯度归一化 |
| 静态索引缓存 | 缓存布局/归并索引，避免每次重新整理 | 不缓存过期训练权重；容量、失效与跨 stream 消费 |
| layout + repeat + norm 融合 | 直接从 producer 的 stride 写 consumer 结果 | backward 保存量和低精度归并顺序 |
| MoE 概率槽位拷贝 | 已知路由地址时直接放置概率、取回梯度 | 必要稠密矩阵仍存在，不能声称所有矩阵被消除 |
| 通信长度对齐 | 对真实异常 message size 验证最小补齐 | 每 rank 分块补零/去尾，dtype、SUM/AVG 和 pack/copy 成本 |
| 延迟日志格式化 | 日志输出时再格式化 device tensor | 关闭 DEBUG 时 f-string 仍可能读取设备值并等待 |

ready-event 应覆盖最后一次实际 payload 操作，包括 contiguous 拷贝和概率 cast；消费者不能因 event 记录过早读取未完成的数据。配对保存 permute/unpermute 的 metadata，异步消费前保证 buffer 不被复用或释放，用对应 stream/event 和记录生命周期的机制保持依赖，避免引入全局同步。

把打包、清零、类型转换、workspace、重计算和反向拷贝纳入 microbenchmark。通信多补几个元素可能更快，但只在目标尺寸/栈证实；索引缓存首建和预热编译仍属于启动成本。

## 5. 依赖安装也是实现的一部分

先确认新进程中扩展可导入、设备可用，核对宿主驱动与容器 runtime/ABI；在授权范围内处理不匹配，不因可疑环境失败就同时改模型代码。

从源码安装扩展时保留完整源码、submodules、commit、构建命令和安装日志，并核对训练真正加载的包与符号。若扩展导入修改了 Torch 全局接口，明确隔离或恢复策略并验证导入前后行为；缺依赖、缺符号和不支持布局走已定义的回退。

容器 commit 不包含 bind mount 中的源码、模型、数据和缓存。交付时分别列出镜像 digest、需要部署的源码版本和外部挂载，避免把“依赖镜像已推送”当作“完整训练实现已打包”。

## 6. 从实验归档变成可审核的训练 PR

按正常执行模块和可回滚边界分组，避免一个小实验一个 PR。本案例最终整理为：

- [计算 PR #15](https://github.com/arcing-mt/VeOmni/pull/15)：监督 CE、视觉索引缓存、Q/K 融合。
- [MoE PR #16](https://github.com/arcing-mt/VeOmni/pull/16)：TE 数据整理、资格计数、概率搬运与准备顺序。
- [通信及启动 PR #17](https://github.com/arcing-mt/VeOmni/pull/17)：通信对齐、延迟日志、专用脚本默认配置。

代码应从正常模型、算子、ACE 或 FSDP 入口可达；去掉外部实验安装器、归档 JSON 和临时路径依赖。依赖库的 ABI/构建兼容修复留在其自身仓库。仅有 docs/experiment 记录的 PR 可以保留为研究归档；用户要合入训练优化时，按授权将它们整理或关闭，不自动删除历史证据。

组合后的实际部署文件与本地哈希一致，再用正常入口重新验证路径和性能。PR 描述用“原来做什么、现在省什么、已有证据”说明，区分正确性修复、算子收益、整步收益和启动准备；失败尝试的细节留在记录中。

## 7. 用户选择的默认值落实到正确配置层

区分通用库默认和专用 launcher 默认。用户明确要求专用脚本默认开启时，保留 `${FLAG:-1}` 形式的显式 `0` 覆盖，在 import 前 export，打印最终配置；不要自动扩展到其他模型或通用库。

检查开关之间的实际依赖，而非只检验每个值合法。例如本案例 native warmup 依赖 counting sort，shard padding 限定 FSDP overlap/comm 模式：非法组合应在启动训练前给出可操作的错误，关闭对应优化后允许原有模式。

用本地替身检查完整脚本能否把默认值/覆盖值传到子进程，是否保留训练参数、拒绝非法组合和忙卡；这证明 launcher 行为，不证明 GPU 性能。此前显式开启同一配置的训练数字可以作为已有记录，不能因默认值改成开启就声称新增收益或长期训练认证。

## 8. 复用已经进入基线的优化

以下五项在本轮恢复前已进入训练基础，不是 PR #15–17 首次引入。历史阶段实验支持部分方案的方向性收益，但统计口径不同，且本轮没有重新量化它们各自的贡献；不能把历史差值重新分配到最终组合成绩中。

### 8.1 GDN 后端组合：保留已快的归一化

替换 GDN 主干时，比较完整 adapter、forward、backward 及 checkpoint 重算。本案例采用 `torch_kernels` 的 TileLang GDN，同时保留 FLA Triton L2Norm。依赖里的 `use_qk_l2norm_in_kernel=True` 实际走普通 Torch 算子链；名称不证明内部融合，归一化增加的耗时可以抵消 GDN 核心 kernel 的收益。

据此选择各部分实际较快的实现，不要求整套来自同一后端。历史同负载 50 步 A/B 支持该组合的方向性收益，本轮确认安装源码与真实前反向执行。当前适配仅支持限定 packed 训练接口：`B=1`、给定 `cu_seqlens`、每段至少 128 token，其余 dtype/head/layout 条件核对当前 adapter；dense、`initial_state`、`output_final_state` 等请求明确拒绝或选择受支持后端，不能用训练结果认证推理缓存正确性。参见 [GDN adapter](https://github.com/arcing-mt/VeOmni/blob/900794f9babc57a3963880e8a87d088c5b9fa3a0/veomni/ops/kernels/gated_delta_rule/musa_tilelang.py)。

### 8.2 空模态：省整段计算前先核对分布式参与

图像单模态数据中，同步视觉参数的参与组内所有 rank 都无 VIDEO 时，可跳过该槽位的 dummy 视觉塔计算；真实图像塔仍执行。先对模态存在性做组内各 rank 一致参与的归约（当前代码使用 `fsdp_group`，不泛指整个 world），再按组内全局结果决定每个 rank 应执行的 dummy 次数。本卡缺某模态、组内其他卡存在时仍须补齐该分支，以保持 FSDP 参数通信与梯度归约顺序；不能因本卡为空跳过存在性 collective。

参与组全纯文本的批次是额外边界：当前实现仍让组内每个 rank 执行一次 dummy，保留 trainable vision 参数参与，避免 DDP 未使用参数问题。重审混合模态、数据跨 rank 不均衡和包装方式变化后的行为。本轮保留既有配置，没有新的严格单开关收益测量。参见 [空模态及 patch 投影实现](https://github.com/arcing-mt/VeOmni/blob/900794f9babc57a3963880e8a87d088c5b9fa3a0/veomni/models/transformers/qwen3_5_moe/qwen3_5_moe_musa_runtime_patch.py)。

### 8.3 Vision patch：把合适的卷积表达为 GEMM

当前输入已按不重叠 patch 排列，Conv3D 的 kernel 与 stride 相同、无 padding，每个 patch 只产生一个输出位置。因此沿原通道/时间/空间顺序展平输入与权重，用 `F.linear` 表达同一投影，省去还原小块和卷积路径的布局搬运。保留原参数形状与名字，仅在 forward 中 reshape 权重，使梯度回到原形状，保持 checkpoint 和 FSDP 参数布局。

实数代数等价不保证不同 backend 逐位相同。验证实际 dtype 的输出、输入/权重梯度（按真实调用契约）及训练误差；普通重叠、padding 或 dilation 卷积需另行推导，不能直接套用。历史分阶段 A/B 有方向性收益，本轮已属于基线，不报告新的精确独立贡献。实现同上。

### 8.4 Foreach 范数：批处理还要确认真正走快路径

大量参数逐个 `norm → pow → add` 会产生密集的小 kernel 启动。按兼容的实际设备、dtype 和布局分组调用 `_foreach_norm`，再对较小的范数数组聚合，可减少调度；FP32 内部累加还可避免逐个梯度先物化完整 FP32 副本。

当前栈只有部分范数阶数（如 1、2、inf）具有批处理 kernel，其他阶数可能仍逐 tensor 执行。检查 Trace，而不是仅凭 foreach 名称确认提速；空梯度、特殊 dtype/layout 和 offload 保留原定义或受支持的回退。DTensor 的 local shard 归约后仍须沿原分片/复制分组计算全局范数，保留 clip 系数、epsilon、非有限检查及 optimizer 更新语义。历史收益与本轮延迟日志修复分开记录。参见 [MUSA 范数适配](https://github.com/arcing-mt/VeOmni/blob/900794f9babc57a3963880e8a87d088c5b9fa3a0/veomni/ops/platform/musa/fsdp2_clip_grad_norm.py)。

### 8.5 小范围 expert ID：稳定计数分桶代替通用排序

若 expert ID 只取少量离散值，先分 block 计数，再对各 expert 的 block 计数做 exclusive prefix sum，最后结合 block 内局部顺序 scatter，即可生成 expert 连续且桶内稳定的 slot 布局。保持原 slot/token 映射及无效 slot、重复 expert、空输入行为；用 CPU 整数参照或原 stable argsort 验证映射、计数与顺序。

保留稳定顺序可避免额外改变下游低精度累加顺序，但整数映射相同不证明整个浮点路径相同。历史 metadata microbenchmark 与训练实验支持小幅方向性收益；最终冻结组合两轮各 rank 的 TE 热路径未走 native 排序（每 rank 4000 次 TE、0 次 fallback），不能再把这项历史收益叠加到 TE 上。参见 [稳定分桶实现](https://github.com/arcing-mt/VeOmni/blob/900794f9babc57a3963880e8a87d088c5b9fa3a0/veomni/ops/kernels/moe/musa_deepep_compact.py)。

## 9. 回退预热按编译特化类别设计

快路径存在也要保留正确的 native fallback；实际路由改变时可能首次进入未编译的分支。根据真实编译 key 的 dtype、stride、整数分块/整除等类别选合成输入，覆盖观测到的特化，不只是重复一个常见 shape。本案例四种 token 数 256、257、4096、4095 覆盖当前安装 Triton 的两类整除条件组合，并设置重复 expert slot 触发原 native 处理。

合成调用使用 trainer 当前设备、`no_grad` 与确定性构造，不读取真实样本、不消耗 RNG、不修改模型/optimizer、不发 collective，也不新增全局 device synchronize。预热只在首次真实 compaction 内按设备执行一次，仍位于原第 1 步计时中；保留原 50 次更新和固定稳态窗口，不能把初始化搬出计时来宣称训练加速。

该安排主要控制冷初始化出现的位置，两轮单独实验未证明稳定稳态收益。合成输入还固定 `E=32`、`top-k=8`、`hidden=2048`；这些几何和四个 token 数只覆盖当前版本观测的特化，不是通用预热模板。设备、kernel 或编译器升级后重新审查真实 fallback 与新编译。参见 [原生回退预热](https://github.com/arcing-mt/VeOmni/blob/26eaf93f43e179c4f417eca2462a85a1be5eb7d1/veomni/ops/kernels/moe/musa_deepep_warmup.py)。

## 10. 负结果改变下一步选择

| 已做尝试 | 当前观察 | 可复用的判断 |
| --- | --- | --- |
| FLA 82 组分块/warps 配置及 GDN chunk 扫描 | 未得到足以替换原配置的稳定收益 | 测完整 FW/BW，穿插热基线；微小差异不构成更换默认的依据 |
| HOST cu/vision geometry cache 与后台预取 | 缓存未证明稳定整步收益；后台预取变慢，现有实现还包含每批 state_dict/deepcopy | 先核对实际准备成本、复制和关键路径，不因“缓存/预取”名称就启用，也不把额外复制未经归因地认定为全部根因 |
| ACE 配 FSDP overlap level 2/3 | DeepEP timeout，停止对应实验 | 检查 collective 顺序、stream/event 和资源竞争；level 0 仍有 native prefetch/shared overlap，不能解释成完全无重叠 |
| 增大 MCCL buffer 或减少 CTA | 未证明整步收益，32 MiB buffer 在 step 2 OOM | 用真实尺寸及训练验证性能与内存；未完成运行不产生完整性能数字，具体参数不推广为通用默认 |

这些是目标环境的负结果，不代表方案在所有设备或模型无效；timeout/OOM 的底层原因未全部确定。收益落在波动内的尝试保持未采用状态；正确性失败不通过放宽原门禁接受。保留原始条件与报告，在软件栈或关键路径有变化时再决定是否重试。
