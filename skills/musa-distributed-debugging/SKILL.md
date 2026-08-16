---
name: musa-distributed-debugging
description: Debug MUSA distributed training hangs, watchdog timeouts, MCCL/NCCL-style collective desync, PyTorch torch_musa process group issues, DeepSpeed/FSDP/DDP communication stalls, and CPU/MUSA loss or operator precision divergence. Use when Codex needs to inspect MUSA or torch_musa logs, explain WorkNCCL/WorkMCCL timeout messages, enable Flight Recorder-style telemetry, collect MCCL diagnostics, compare ranks, use compare_tool to locate the first divergent operator, distinguish fused-backend selector warnings from numerical errors, or propose safe isolation experiments for multi-GPU or multi-node training.
---

# MUSA Distributed Debugging

Use this skill to diagnose MUSA distributed training failures with PyTorch, torch_musa, DeepSpeed, DDP, FSDP, ZeRO, or other collective-heavy stacks.

The mental model comes from PyTorch's NCCL watchdog and Flight Recorder guidance, adapted to MUSA/MCCL. Treat the timeout as a symptom: the first rank that reports a timeout is often not the culprit, and the collective named in the timeout is often only where the process finally noticed that ranks had diverged or stalled.

The same first-cause rule applies to numerical debugging. A different final loss does not prove that cross entropy is wrong. Compare the forward path in execution order and find the first operator whose value, index, shape, dtype, or branch decision diverges. Later differences are usually consequences.

## Translate CUDA Terms to MUSA

- Map CUDA device APIs to MUSA equivalents when reading code: `torch.cuda.*` usually becomes `torch.musa.*`; `cuda` device strings become `musa`; `nccl` process groups become `mccl` in torch_musa.
- PyTorch c10d diagnostics may still use `TORCH_NCCL_*` environment variable names and `WorkNCCL` wording, depending on the PyTorch/torch_musa version. Do not assume those variables work on every MUSA build; verify from logs or by checking whether trace files are produced.
- Map NCCL library tuning to MCCL variables where available: `NCCL_DEBUG` becomes `MCCL_DEBUG`, `NCCL_SOCKET_IFNAME` becomes `MCCL_SOCKET_IFNAME`, and so on.
- Avoid CUDA-only advice such as blindly setting `CUDA_LAUNCH_BLOCKING=1`. On MUSA, prefer MUSA/MCCL-specific diagnostics, explicit `torch.musa.synchronize()` probes, and smaller isolation runs.

## First-Pass Triage

Collect evidence before changing code:

```bash
pwd
git status --short
find . -type f \( -name '*.log' -o -name '*.out' -o -name '*.err' \) -printf '%T@ %p\n' | sort -n | tail -20
python - <<'PY'
import os, torch
print("torch", torch.__version__)
try:
    import torch_musa
    print("torch_musa", getattr(torch_musa, "__version__", "unknown"))
    print("musa available", torch.musa.is_available())
    print("musa devices", torch.musa.device_count())
except Exception as exc:
    print("torch_musa check failed:", repr(exc))
for k in sorted(os.environ):
    if k.startswith(("TORCH_", "MCCL_", "MUSA_", "MTHREADS_", "MASTER_", "LOCAL_", "RANK", "WORLD_")):
        print(f"{k}={os.environ[k]}")
PY
musaInfo 2>&1 | head -80 || true
mthreads-gmi 2>&1 | head -80 || true
```

From the latest log, extract per-rank fields:

- rank and local rank
- process group id or description
- `SeqNum` / `collective_seq_id`
- op type: `ALLREDUCE`, `ALLGATHER`, `REDUCE_SCATTER`, `BARRIER`, `COALESCED`
- input/output numel and dtype if present
- timeout value
- `last enqueued`, `last started`, `last completed`
- any earlier exception, OOM, data loader error, kernel error, or process death on another rank

## Enable Flight Recorder-Style Data

For PyTorch versions that support ProcessGroupNCCL Flight Recorder, try these variables even on MUSA if the torch_musa build routes diagnostics through the same c10d code. Keep the dump path on a local or shared path with enough space.

```bash
export TORCH_NCCL_TRACE_BUFFER_SIZE=2000
export TORCH_NCCL_DUMP_ON_TIMEOUT=1
export TORCH_NCCL_ENABLE_MONITORING=1
export TORCH_NCCL_HEARTBEAT_TIMEOUT_SEC=600
export TORCH_NCCL_TRACE_CPP_STACK=1
export TORCH_SYMBOLIZE_MODE=fast
export TORCH_NCCL_DEBUG_INFO_TEMP_FILE=/tmp/musa_fr_trace_
export TORCH_FR_DUMP_TEMP_FILE=/tmp/musa_fr_trace_
```

If the job times out, gather all rank dump files before restarting the job. If `torchfrtrace` is installed, run:

```bash
torchfrtrace --prefix musa_fr_trace_ /tmp/
```

If only raw pickle files are available, preserve them and inspect with the PyTorch version that produced them. If no files are produced, note that Flight Recorder is unsupported or disabled in that build and fall back to MCCL logs plus process stacks.

## Enable MCCL Diagnostics

Use MCCL logs for communication-layer evidence. Do not leave verbose debug settings in production runs.

```bash
export MCCL_DEBUG=INFO
export MCCL_DEBUG_SUBSYS=INIT,COLL,NET,ENV
export MCCL_DEBUG_FILE=/tmp/mccl_%h_%p.log
export MCCL_SET_THREAD_NAME=1
```

Escalate only for a short reproduction:

```bash
export MCCL_DEBUG=TRACE
export MCCL_DEBUG_SUBSYS=COLL,NET,CALL
```

For multi-node networking, record or verify:

```bash
ip -br addr
ibv_devinfo 2>/dev/null | head -80 || true
env | grep -E '^(MCCL_SOCKET_IFNAME|MCCL_IB_HCA|MCCL_NET|MCCL_NET_PLUGIN|MCCL_CROSS_NIC|MCCL_IB_)=' | sort
```

Use `MCCL_SOCKET_IFNAME` to pin the expected IP interface and `MCCL_IB_HCA` to pin RDMA devices only when the cluster topology is known. Prefer documenting the current value before changing it.

## Interpret Patterns

Use the rank comparison, not a single rank log.

- Same `last completed`, one or more ranks never enqueue the timeout collective: suspect CPU-side slowness, data loader starvation, checkpointing, compilation, or an exception path before the collective.
- Different `last enqueued` or different op types at the same sequence: suspect rank divergence, conditional collective calls, uneven dataset exhaustion, dynamic control flow, different model branches, or inconsistent process group membership.
- Same sequence and op across ranks, all started but none complete: suspect MCCL/GPU/kernel/network hang, stream dependency bug, buffer lifetime issue, or hardware instability.
- Timeout follows an earlier OOM, `SIGKILL`, Python exception, or dataloader worker death: treat the earlier failure as the primary cause and the collective timeout as fallout.
- Only some ranks are behind in compute before the collective: suspect stragglers from sequence length, vision token count, MoE routing, dynamic shape compilation, or a slow kernel. Sample Python stacks before changing collectives.

## Sample Live Stacks

When processes are still alive, collect stacks from all local ranks. Prefer non-invasive sampling first.

```bash
ps -eo pid,ppid,stat,etime,cmd | grep -E 'python|torchrun|deepspeed' | grep -v grep
py-spy dump --pid <pid>
```

If `py-spy` is unavailable, use:

```bash
python - <<'PY'
import faulthandler, os, signal, time
print("Use: kill -USR1 <pid> if the program registered faulthandler for SIGUSR1")
PY
```

Correlate stacks with ranks:

- ranks in data loading, checkpointing, compilation, or Python exception handling are CPU-side suspects;
- ranks in model forward/backward kernels while others are in collective waits indicate compute imbalance;
- ranks in `torch_musa.stream.synchronize`, DeepSpeed ZeRO reduce/partition code, or all-gather waits indicate communication/computation boundary pressure.

## Safe Isolation Experiments

Prefer one change per rerun and preserve the exact command, config diff, and log path.

- Reduce problem size: smaller `cutoff_len`, homogeneous samples, one node, fewer GPUs, or a tiny fixed dataset.
- Remove dynamic variation: freeze vision tower, disable variable image/video inputs, disable MoE routing if possible, or bucket by length.
- Reduce overlap complexity: disable DeepSpeed `overlap_comm`, reduce prefetch bucket sizes, set ZeRO-3 prefetch to zero for an A/B run, or force synchronous waits around suspected all-gather paths.
- Add targeted synchronization only around suspected MUSA stream boundaries with `torch.musa.synchronize()`, then remove it after diagnosis.
- Compare with a known-good torch/torch_musa/MUSA SDK/MCCL version if the failure appeared after an upgrade.
- Run standalone MCCL collectives or a minimal `dist.all_reduce` / `all_gather` reproduction before blaming the model.

## Numerical Precision and Loss Divergence

Use this workflow when identical checkpoints and inputs produce different initial loss values across CPU, CUDA, torch_musa versions, or MUSA machines.

### Freeze the comparison boundary

Before comparing operators, record and hold constant:

- checkpoint path and file hashes;
- exact token ids, labels, attention masks, image/video tensors, and sample order;
- model config, dtype, attention implementation, MoE expert implementation, and training/eval mode;
- random seed, dropout state, autocast state, and device;
- PyTorch, torch_musa, Transformers, DeepSpeed, MUSA driver, and SDK versions.

A fixed seed is necessary for reproducibility but cannot repair a deterministic device-specific branch difference. Different CPUs normally do not change checkpoint initialization when the loaded weights and inputs are identical; prove the first divergent operator before attributing a loss difference to CPU hardware.

### Use compare_tool to find the first divergent operator

`torch_musa.utils.compare_tool.CompareWithCPU` intercepts MUSA ATen operations, runs a CPU reference with equivalent inputs, and compares outputs. Use a stopped training workload or a dedicated device because a full model comparison can consume production-scale memory and run much slower than an ordinary forward.

```python
import torch
import torch_musa  # noqa: F401

from torch_musa.utils.compare_tool import CompareWithCPU, open_module_tracker

open_module_tracker(model)
mode = CompareWithCPU(
    atol=1e-3,
    rtol=1e-2,
    verbose=False,
    should_log_to_file=True,
    output_dir=output_dir,
)

with torch.no_grad(), mode:
    outputs = model(**fixed_inputs)

torch.musa.synchronize()
```

Recommended escalation order:

1. Run a small representative chain for embedding, attention, normalization, MoE, LM head, and loss.
2. Run the real checkpoint with a short fixed input and compare every visible operator.
3. Force an eager implementation only for observability when a fused kernel hides internal operators.
4. Test the production fused implementation separately against an explicit CPU reference using the real shape.
5. Use `target_list` and `dump_error_data=True` to capture the first failing operator input after the failing op is known.

Do not start with a broad tolerance increase. First classify the mismatch:

- floating value error;
- integer index or boolean mask difference;
- output shape or dtype difference;
- backend/algorithm selector difference;
- MUSA-only operator that cannot execute on CPU;
- later error caused by an earlier branch difference.

For tuple-returning operators such as `topk`, compare values and indices independently. Equal values do not mean equivalent model behavior when indices select different experts, tokens, or vocabulary entries.

### Validate the terminal loss independently

Some MUSA fused loss kernels cannot be replayed on CPU. A compare_tool warning such as “only supported in torch_musa” is not proof of a numerical error. If the selector returns different enum values on CPU and MUSA, compare the final value directly:

```python
shift_logits = outputs.logits[:, :-1, :].contiguous().float()
shift_labels = labels[:, 1:].contiguous()
cpu_loss = torch.nn.functional.cross_entropy(
    shift_logits.cpu().view(-1, shift_logits.shape[-1]),
    shift_labels.cpu().view(-1),
    ignore_index=-100,
)
```

Report absolute and relative error between the MUSA fused loss and this CPU reference. Keep execution-path selector differences separate from numerical result differences.

### Build a first-divergence evidence ladder

Locate numerical bugs by shrinking the comparison boundary in execution order. Do not jump directly from a different loss to a suspected operator.

1. Freeze the real inputs and verify full hashes across environments.
2. Trace module inputs and outputs to find the earliest divergent module.
3. Trace submodule boundaries only inside that module.
4. Require the suspected boundary to have equal inputs and unequal outputs. If its inputs already differ, treat it as propagation rather than the first cause.
5. Inspect the source expression and identify the dispatched ATen operator, including implicit dispatch from syntax such as `@`.
6. Replay that operator against an explicit CPU reference with the production shape, dtype, value range, strides, and device path.
7. Compare affected and known-good torch_musa versions with the same captured inputs.
8. Turn the captured case into the smallest regression UT, then verify a narrow workaround with both intermediate hashes and fixed-batch loss.

Treat numerical patterns only as clues. For example, corruption beginning near a power-of-two boundary may suggest reduced mantissa precision, but it does not prove the kernel's internal dtype. Report separately what output comparison proves and what backend implementation detail remains an inference.

For RoPE-like matrix products, preserve the real maximum position. A short random test can pass while long integer-valued positions fail. Check whether `@` dispatches to `aten.bmm`, record the contraction dimension, and test mathematically equivalent formulations only when equivalence follows from the actual dimensions.

## Case Study: Qwen3-VL-MoE Long-RoPE bmm Precision

This case compared Qwen3-VL-30B-A3B-Instruct on torch_musa 2.7.1 and 2.9.1.

### Align data before operators

Do not compare historical loss values until root inputs match. In this case, the two full dataset copies produced 36,551 versus 36,584 examples after filtering, so the same seed selected different batches. The apparent `1.73` versus `1.02` loss gap was confounded by data.

Use a dataset file whose size and content hashes match, disable shuffling, and record full hashes for `input_ids`, labels, masks, position IDs, RoPE deltas, and pixel tensors. With identical inputs, 2.7.1 still produced loss `1.183679...` while 2.9.1 produced `1.019588...`, proving a numerical issue remained.

### Narrow the first divergence hierarchically

Use module hooks first, then add operator-boundary traces only around the first divergent module:

1. The first divergent module was layer 0 self-attention.
2. Q/K/V projections and Q/K normalization had identical full hashes.
3. The o-projection input differed.
4. RoPE Q/K inputs matched, but RoPE `cos` and `sin` differed.
5. SDPA value, mask, scale, and causal settings matched; query/key differed because of RoPE.

This ordering excludes later MoE routing, top-k, expert GEMM, LM head, and loss as the first cause.

### Test the real RoPE shape

Qwen3-VL-MoE generated frequencies using:

```python
freqs = (inv_freq_expanded.float() @ position_ids_expanded.float()).transpose(2, 3)
```

The contraction dimension is one, but `@` dispatches to `aten.bmm`. Run `CompareWithCPU` on the actual long-sequence shape `[3, 1, 64, 1] @ [3, 1, 1, 8048]`:

- torch_musa 2.7.1 failed `aten.bmm` at about position 2048, with examples such as CPU 2049 becoming MUSA 2048;
- torch_musa 2.9.1 passed the same operation;
- later transpose, trigonometric, and multiply operations passed relative to their inputs and merely propagated the bad frequencies.

Do not infer long-sequence correctness from a small random tensor. Preserve the production position range, dtype, broadcast shape, and device path in the regression UT.

### Use a narrow workaround

Because the contraction dimension is one, replace only this RoPE expression with mathematically equivalent broadcast multiplication:

```python
freqs = (inv_freq_expanded.float() * position_ids_expanded.float()).transpose(2, 3)
```

Gate the patch to Qwen3-VL-MoE, MUSA, and affected 2.7.x releases; provide an opt-out such as `OPENSEARCH_MUSA_ROPE_BMM_WORKAROUND=0`. Preserve the upstream `dynamic_rope_update` and `torch.no_grad()` decorators. Prefer an upgraded torch_musa release after its production stack is validated.

Add two UTs:

1. A direct long-position bmm test that fails on affected 2.7.1 and passes on 2.9.1.
2. A broadcast-multiply test that matches the CPU reference on both releases.

After patching, require RoPE `cos`, `sin`, rotated query, and rotated key full hashes to match the reference environment, then verify the fixed-batch loss.

### Keep top-k as a separate issue

Exact ties at a MoE top-k boundary can produce equal values but different expert indices across backends. If deterministic routing is required, use stable descending sort plus slicing in only the affected Router modules and cover values and indices with a focused UT. Do not label that secondary issue as the first loss divergence when attention already differs before the Router executes.

## DeepSpeed-Specific Checklist

For ZeRO-3 hangs or timeouts:

- Inspect `overlap_comm`, `reduce_scatter`, `allgather_partitions`, `stage3_prefetch_bucket_size`, `stage3_max_live_parameters`, `stage3_max_reuse_distance`, and optimizer offload settings.
- Identify whether the failing collective is parameter all-gather, gradient reduce-scatter/all-reduce, barrier, or optimizer state communication.
- If a local DeepSpeed patch changes async all-gather or stream ordering, describe whether it changes submit order, host blocking, stream dependency, or buffer lifetime.
- Treat performance and correctness separately: a synchronization patch may improve stability while reducing overlap.
- Watch for secondary errors after step 1 such as OOM from larger live parameter windows.

## Fix Guidance

Choose the fix based on the pattern:

- CPU divergence: make every rank execute the same collective sequence; fix conditional branches, uneven iterator exhaustion, exception paths, and distributed barriers.
- Data imbalance: log per-rank sample ids, token counts, image/video counts, and batch construction; use deterministic samplers and balanced bucketing.
- Stream or buffer lifetime issue: add explicit stream waits or handle waits near the producer/consumer boundary; keep changes MUSA-gated and configurable.
- Network/MCCL issue: pin interfaces, verify RDMA device selection, reduce topology complexity, update MCCL/driver, and run standalone MCCL tests.
- Real kernel hang: isolate the exact op with synchronization probes, sanitizer/profiler tools, smaller shapes, and version comparison.

## MUSA Debugging Tools

Use MUSA SDK and Moore Perf tools when kernel or memory errors are suspected:

- `musaInfo` for runtime and device visibility.
- `mcc` for native MUSA builds and CUDA compatibility compilation checks.
- `musify` or MUSA Mapping for CUDA-to-MUSA migration issues.
- Moore Perf Compute/System for kernel and system profiling.
- MUSA Compute Sanitizer for memory errors, leaks, and API misuse.
- `muPTI`-based tooling for kernel/activity traces when available.

## Reporting Back

When reporting findings, include:

- the earliest relevant error, not only the final timeout;
- the rank comparison table for sequence/op/status;
- whether the evidence points to CPU divergence, compute straggler, communication hang, stream dependency, OOM, or hardware/network;
- for loss divergence, the first mismatching operator and whether the mismatch is in values, indices, masks, shapes, dtypes, or backend selection;
- the smallest safe next experiment and expected signal;
- any code/config changes made and whether they are diagnostic or intended as a durable fix.

## Source Basis

This skill adapts the PyTorch Flight Recorder and NCCL watchdog debugging model to MUSA/MCCL, using MUSA names and tools where available:

- PyTorch blog: "Flight Recorder: A New Lens for Understanding NCCL Watchdog Timeouts"
- PyTorch tutorial: "Flight Recorder for Debugging Stuck Jobs"
- PyTorch ProcessGroupNCCL environment variable documentation
- Moore Threads MUSA SDK, torch_musa, MCCL environment variable, and Moore Perf documentation
