# Case Study: Qwen3-VL-MoE Long-RoPE bmm Precision

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


This is a historical local observation, not a release-wide guarantee. Reproduce on the installed build before applying the workaround.
