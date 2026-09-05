# Dynamic Engine Integration — Drop-In Instructions

These files integrate the Dynamic Multi-Objective Context Aggregation Engine
directly with the **real, original** `smart_aggregation_project_v2/main code/`
codebase (the one in `dl_legit_final.zip`), targeting **Method A only**, as
requested. Method B and Method C are untouched.

## Files in this folder

| File | Purpose |
|---|---|
| `meta_features.py` | Runtime meta-feature extraction (Q_c, H_R, D_R). Model-agnostic — no changes needed from the standalone version. |
| `dynamic_controller.py` | Softmax-over-features dynamic parameter controller. Model-agnostic — no changes needed. |
| `utility_optimizer.py` | Per-item value-density greedy knapsack selector (replaces fixed-lambda MMR). **Adapted**: imports `from models import Chunk` (the real project's dataclass) instead of the standalone reconstruction, and uses `chunk.tokens` instead of `chunk.token_count` to match the real field name. |
| `dynamic_smart_aggregation.py` | **The actual integration.** `DynamicSmartAggregation` — a drop-in replacement class for `SmartAggregation` (`smart_aggregation.py`), same constructor signature, same `retrieve(query, verbose)` → `List[Chunk]` contract, same `get_statistics()`. Step 1 (multi-strategy retrieval) and Step 3 (cross-encoder reranking) call the exact same `self.embedder` / `self.vector_store` / `self.cross_encoder` methods, unchanged. Only Step 2's dedup threshold and Step 4's selection mechanism are dynamic. |
| `run_method_a_comparison.py` | Standalone comparison script. Loads data and builds the index exactly like `demo_enhanced.py` does for Method A, then runs both `SmartAggregation` and `DynamicSmartAggregation` side by side and reports accuracy / tokens / latency / compression ratio. |
| `_mock_backends.py` | **Test-only.** TF-IDF-based mock `Embedder`/`VectorStore`/`CrossEncoderReranker` matching the real classes' interfaces, used to verify this integration's wiring in this sandbox (no internet access to download `sentence-transformers` models here). **Not needed on your machine** — use the real `embeddings.py` classes there.

## How to install

1. Copy `meta_features.py`, `dynamic_controller.py`, `utility_optimizer.py`,
   and `dynamic_smart_aggregation.py` into your `main code/` directory,
   alongside `smart_aggregation.py`, `models.py`, `embeddings.py`, etc.
2. Copy `run_method_a_comparison.py` into the project root (next to
   `demo_enhanced.py`), or wherever you want to run it from — it inserts
   `main code/` onto `sys.path` the same way `demo_enhanced.py` does, but
   you may need to adjust the `sys.path.insert` line depending on where
   you place it relative to `main code/`.
3. Ignore `_mock_backends.py` — it's only for testing without internet
   access. On your machine, the real `embeddings.py` (sentence-transformers
   + FAISS) works as-is.

## How to run

```bash
# Sample data, default settings (token_budget=3582, variable cardinality)
python run_method_a_comparison.py

# Real FinanceBench, same docs/questions count as the original paper run
python run_method_a_comparison.py --financebench /path/to/financebench \
    --max-docs 45 --max-questions 75

# Fixed-cardinality ablation: cap dynamic engine at k=10 to isolate the
# effect of dynamic WEIGHTS alone, independent of budget-driven flexibility
# (this is "Condition C" from the Task 3 ablation grid)
python run_method_a_comparison.py --financebench /path/to/financebench \
    --max-docs 45 --max-questions 75 --max-items 10

# Isolate dynamic dedup from dynamic selection (Condition B vs Condition E)
python run_method_a_comparison.py --financebench /path/to/financebench \
    --static-dedup --max-items 10
```

Results are saved to `method_a_vs_dynamic_results.json` (configurable via
`--output`), with the same shape as the project's existing
`experiment_results_financebench_*.json` files, plus an additional
`dynamic_diagnostics` field per query (meta-features, dynamic parameters,
optimizer diagnostics) for deeper analysis.

## What changed vs. the standalone Phase 2 work

The standalone `smart_agg_eval/` codebase (built in earlier phases of this
project, before this real codebase was uploaded) used a **reconstructed**
`Chunk` dataclass and a custom retriever/chunker, inferred from the paper's
prose description. That reconstruction's numbers (93.3% accuracy, 3,582
avg tokens, 3,175:1 compression, 20.76s latency) do **not** exactly match
this real codebase's actual recorded experiment
(`results/experiment_results_financebench_three_methods.json`: Method A =
94.7% accuracy, 3,331 avg tokens, 3,735:1 compression, 19.28s latency, on
45 documents / 75 questions). The files in this folder are adapted to the
real `models.Chunk` / `models.RetrievalResult` and the real
`SmartAggregation` class, so results from `run_method_a_comparison.py` on
your machine will be directly comparable to the real, published numbers —
not the earlier reconstruction's numbers.
