# Faster & Fully Data-Agnostic Analysis Pipeline

Status: approved (design), pending implementation plan
Date: 2026-08-25
Owner: harsh@rubikxstores.com

## Problem

Two goals, discovered to share a root cause in one area:

1. **Data agnosticism.** The core pipeline (`FastPlanner`, both AI
   providers) is already schema-driven — it works off
   `metadata["columns"]` roles (`metric`/`dimension`/`time`), not
   hardcoded column names. `clean_walmart_data()` in
   `data_engine/cleaner.py` is the one truly hardcoded-schema
   function, but it is dead code in production (only
   `scripts/test_*.py` call it) — no action needed there. What
   remains are five specific correctness bugs, found by an earlier
   full-codebase review, that make the system silently wrong for
   dataset shapes other than the ones it happened to be tested
   against (multi-column grouping, non-`sum` aggregations, non-time
   groupings, and a weaker default AI provider).
2. **Analysis speed.** A real `/api/analyze` run measured
   `ai_planning` at ~29,432ms against single-digit-millisecond costs
   for every other stage. Root cause: `claude_provider.py` sends the
   same ~500 lines of instructions **twice** per call (once as
   `system=SYSTEM_PROMPT`, duplicated inline in the `user` message)
   plus the full dataset metadata JSON, with no prompt caching.

One fix (Section 3) serves both goals: today `FastPlanner` detects a
valid two-dimension grouping (time + category) and silently discards
the category, both giving a wrong answer *and* needlessly falling
back to the slow AI path for a pattern it could handle deterministically
once two downstream bugs are fixed.

## Non-goals

- No new chart types (multi-dimension charts still fall back to
  table, reusing the existing fallback path).
- No change to the AI provider selection mechanism (`AI_PROVIDER` env
  var) itself — only to what each provider validates.
- No semantic/fuzzy question caching — the plan cache in Section 2 is
  exact-string match only.

## Section 1 — Prompt de-duplication + Anthropic prompt caching

**File:** `ai/providers/claude_provider.py`

- Remove the duplicated instructional text from the `user_prompt`
  built in `create_analysis_plan()`. The `user` message becomes just
  the `DATASET METADATA` block + `USER QUESTION` block. All stable
  reasoning rules live only in `SYSTEM_PROMPT` (`ai/prompts.py`,
  unchanged).
- Add `cache_control: {"type": "ephemeral"}` to the Anthropic API call
  at two breakpoints:
  1. On the `system` block (100% static across all requests).
  2. On the metadata portion of the `user` message content (static
     per uploaded dataset — changes only on a new upload).
- `messages.create(...)` moves from a single string `system=` /
  single string `content=` to the block-list form required to attach
  `cache_control` (see Anthropic SDK docs for exact shape — content
  becomes a list of `{"type": "text", "text": ..., "cache_control":
  ...}` blocks).
- No change to `max_tokens=2000` or model selection.

**File:** `ai/providers/openai_provider.py`

- Apply the same prompt de-duplication (if it independently repeats
  instructions — verify during implementation). OpenAI's prompt
  caching is automatic for prefixes over ~1024 tokens; no explicit
  `cache_control` equivalent needed.

**Verification:** timing captured in the existing `measure(...)`
blocks in `backend/routes/analysis.py` (`ai_planning` timing) should
drop substantially on the *second* call for the same dataset (cache
hit), even for a different question. Confirm via the existing
`performance` field in the API response — no new instrumentation
needed.

## Section 2 — Exact-question plan cache

**File:** `data_engine/dataset_manager.py`

- Add a method mirroring the existing `get_cached(key, builder)`
  pattern but keyed by an arbitrary sub-key so it can hold multiple
  cached plans per dataset, e.g.:
  `get_cached_question_plan(question: str, builder: Callable[[], AnalysisPlan]) -> AnalysisPlan`.
  Internally this can just call `get_cached(f"plan::{question}",
  builder)` — `get_cached` already accepts an arbitrary string key
  and already clears on new dataset load, so this may not need new
  `DatasetManager` code at all beyond confirming the key-namespacing
  doesn't collide with `"metadata"/"profile"/"quality"`.
- Cache key = the question string exactly as it arrives at the AI
  fallback step (post control-char-stripping and `.strip()` from
  `backend/routes/analysis.py`) — **no** case-folding or internal
  whitespace normalization, to avoid a normalization bug returning a
  plan built for a different literal filter value (e.g. `region =
  'India'` vs `region = 'india'`).
- Only wraps the AI-planner fallback branch (Section 5 of
  `analyze_dataset()` in `backend/routes/analysis.py`) — the fast
  planner is not cached (already ~50ms, not worth the complexity).
- On a cache hit, skip the `create_analysis_plan()` call entirely.

**File:** `backend/routes/analysis.py`

- `planner` response object gains a `"cached": bool` field so a hit
  is visible in the API response (useful for both testing and
  frontend transparency, e.g. a "cached" badge).
- Cache errors/exceptions are never stored — only a successfully
  returned `AnalysisPlan` is cached, matching `get_cached`'s existing
  behavior of only storing on success.

## Section 3 — Multi-dimension grouping (time + category)

**File:** `data_engine/visualization.py`

- `create_visualization_spec()` gains a required way to know which
  column is the metric — pass `metric_column: str` explicitly from
  `backend/routes/analysis.py` (which already computes
  `f"{plan.aggregation}_{plan.metric}"` for insight-building; reuse
  that same value) instead of assuming `columns[1]`.
- `x_column` = the group-by/dimension columns (everything in
  `result.columns` that isn't `metric_column`).
- Exactly 1 dimension column → unchanged behavior (`x=dimension,
  y=metric`).
- 2+ dimension columns for a non-table `visualization_type` → raise
  the same `ValueError` already raised for "requires at least two
  columns". `backend/routes/analysis.py` already catches this
  `ValueError` and falls back to `visualization_type="table"` — no
  new error handling needed there.

**File:** `data_engine/query_engine.py`

- `analyze()`'s `sort_by == "time"` branch currently scans `group_by`
  for the first datetime-dtype column. Change it to accept the time
  column explicitly (new `time_column: str | None = None` parameter)
  and use it directly instead of guessing. Caller
  (`backend/routes/analysis.py` → wherever `execute_plan`/`analyze`
  is invoked) passes `plan.time_column`.

**File:** `ai/fast_planner.py`

- In `create_plan()`, when both `time_column` is detected (Section 5
  today) **and** `grouping_columns` has exactly one entry that is not
  the time column itself, build:
  ```python
  AnalysisPlan(
      filters=filters,
      group_by=[time_column, grouping_columns[0]],
      metric=metric,
      aggregation=aggregation,
      sort="asc",
      sort_by="time",
      visualization="line",   # will safely fall back to table via Section 3's fix
      time_granularity=time_granularity,
      time_column=time_column,
  )
  ```
  instead of discarding `grouping_columns[0]`. Both dimensions were
  matched explicitly by column name via regex against real columns —
  this is not a new guess, it's using detection the planner already
  performs and previously threw away.

**File:** `data_engine/plan_executor.py` / wherever `execute_plan`
calls `query_engine.analyze()` — thread `plan.time_column` through
(see query_engine change above).

## Section 4 — Remaining correctness fixes

**File:** `data_engine/plan_validator.py`

- Require the time column to be present in `group_by` whenever
  `plan.time_granularity` is set (today only enforced when
  `plan.sort_by == "time"`), raising the existing `ValueError` /
  400 path.
- Check via `metadata["columns"][plan.metric]["role"] == "metric"`
  before allowing the plan through; raise `ValueError` (→ existing
  400 handling in `backend/routes/analysis.py`) if not, instead of
  letting `query_engine.analyze()` raise an unhandled `TypeError` (→
  500) deep in pandas.

**File:** `data_engine/insight_engine.py`

- `build_deterministic_insights()` (or `_add_trend` directly) takes
  an explicit signal for "is this grouping time-based" — derive it in
  `backend/routes/analysis.py` from `plan.time_column is not None and
  plan.time_column in plan.group_by`, pass it in, and skip the trend
  insight entirely when `False` instead of inferring a trend from row
  order.

**File:** `data_engine/insight_generator.py`

- `_humanize_metric` strips any of the six known aggregation prefixes
  (`sum_`, `mean_`, `median_`, `min_`, `max_`, `count_`) via a single
  regex, not just `sum_`.

**File:** `ai/providers/openai_provider.py`

- Port `claude_provider.py`'s semantic sanity checks: a `"success"`
  plan must include `metric`; `time_granularity` set requires
  `time_column` set; invalid/inconsistent combinations get the same
  treatment `claude_provider.py` gives them (check its exact behavior
  during implementation and mirror it, rather than reinvent it).

## Data flow (unchanged at a high level)

`upload → dataset_manager (singleton, unchanged)` →
`/api/analyze` → `FastPlanner` (now handles one more pattern) → AI
fallback (now cached at two levels: Anthropic prompt cache +
exact-question plan cache) → `plan_validator` (two new checks) →
`query_engine.analyze` (explicit time_column) → `insight_engine`
(time-aware trend) → `visualization` (metric-aware column selection)
→ response (`planner.cached` field added).

## Testing

- Existing `scripts/test_*.py` scripts are plain assert-based scripts
  run via `PYTHONPATH=. .venv/Scripts/python.exe scripts/test_X.py`
  (not pytest — confirmed pytest isn't installed in `.venv`). Extend
  the relevant ones (`test_fast_planner.py`, `test_query_engine.py`,
  `test_visualization.py`, `test_insight_engine.py`,
  `test_insight_generator.py`, `test_ai_planner.py`) rather than
  adding a new framework.
- New cases needed:
  - FastPlanner: "monthly sales by region"-shaped question →
    `group_by == [time_column, category_column]`.
  - visualization: 2-dimension result + `visualization_type="bar"` →
    raises `ValueError`; caller falls back to table (integration-level
    check via the smoke-test pattern already used in this
    conversation, i.e. a `TestClient` round trip).
  - query_engine: `sort_by="time"` with an explicit `time_column` that
    is *not* the first datetime column in `group_by` order → sorts by
    the right one.
  - plan_validator: `time_granularity` set with time column missing
    from `group_by` → rejected; non-metric-role column as `metric` →
    rejected.
  - insight_engine: non-time grouping → no trend insight present.
  - insight_generator: `mean_`/`min_`/`max_` columns humanize
    correctly.
  - openai_provider: mirrors whatever `test_ai_planner.py` /
    `test_ai_adapter.py` already assert for the Claude path.
  - Plan cache: same question asked twice against the same dataset →
    second response has `planner.cached == true` and no
    `ai_planning` timing entry (or a near-zero one).
- Manual/smoke verification: re-run the `TestClient`-based smoke
  script used earlier in this session (upload → analyze) to confirm
  nothing regresses end-to-end, plus one run with a "monthly X by Y"
  question to see the new FastPlanner path and the cache fields live.

## Risks / open questions for the implementer

- Anthropic SDK's exact `cache_control` block shape depends on the
  installed `anthropic` SDK version (`requirements.txt` pins
  `anthropic>=0.18.0`, a floor not a ceiling) — confirm the block
  syntax against the installed version before wiring it in.
- `plan_executor.py` wasn't read in detail during design; confirm
  exactly where `query_engine.analyze()` is invoked and thread
  `time_column` through cleanly rather than guessing its call site.
