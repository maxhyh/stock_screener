# Raw-Model ODS Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, read-only ODS data-source mode to the raw-model walk-forward diagnostic while preserving legacy data as the default evidence path.

**Architecture:** Keep feature engineering, indicator calculation, labels, and model training source-agnostic. Add one small source resolver at the data-frame boundary: legacy mode reads the existing parquet file, while ODS mode loads 252 prior trading sessions for long-window features and `max(horizon)+1` following sessions for labels before calling `AShareOdsLoader.load_daily_panel`. Put source identity into the cache request and emitted JSON so frames and artifacts cannot cross-contaminate.

**Tech Stack:** Python 3, pandas, pytest, existing `core.data.ashare_ods_loader`, LightGBM diagnostic script.

---

### Task 1: Define source-aware raw-panel loading

**Files:**
- Modify: `scripts/quant_raw_model_walkforward_diagnosis.py:25-35,214-247,623-672`
- Test: `tests/test_quant_raw_model_walkforward_diagnosis.py`

- [ ] **Step 1: Write the failing tests**

Append tests that express the public loading boundary without invoking indicators:

```python
def test_load_raw_market_panel_defaults_to_legacy_parquet(monkeypatch, tmp_path):
    data_file = tmp_path / "daily.parquet"
    expected = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["2026-01-02"]})
    calls = {}

    def fake_read_parquet(path, columns):
        calls["path"] = path
        calls["columns"] = columns
        return expected.copy()

    monkeypatch.setattr(diag.pd, "read_parquet", fake_read_parquet)

    out, meta = diag.load_raw_market_panel(
        data_file=data_file, data_source="legacy", start="2026-01-02", end="2026-01-02", include_bj9=False
    )

    pd.testing.assert_frame_equal(out, expected)
    assert calls["path"] == data_file
    assert meta["data_source"] == "legacy"


def test_load_raw_market_panel_routes_ods_through_loader(monkeypatch, tmp_path):
    expected = pd.DataFrame({
        "ts_code": ["000001.SZ"], "trade_date": [pd.Timestamp("2026-01-02")],
        "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
        "vol": [100.0], "amount": [1000.0], "pct_chg": [1.0],
    })
    calls = {}

    class FakeLoader:
        def __init__(self, root=None):
            calls["root"] = root

        def load_daily_panel(self, start, end, include_bj9):
            calls.update(start=start, end=end, include_bj9=include_bj9)
            return expected.copy()

    monkeypatch.setattr(diag, "AShareOdsLoader", FakeLoader)

    out, meta = diag.load_raw_market_panel(
        data_file=tmp_path / "unused.parquet", data_source="ashare_ods", start="2026-01-02", end="2026-01-03", include_bj9=True,
        ashare_data_root="/shared/ods",
    )

    pd.testing.assert_frame_equal(out, expected)
    assert calls == {"root": "/shared/ods", "start": "2026-01-02", "end": "2026-01-03", "include_bj9": True}
    assert meta["data_source"] == "ashare_ods"
    assert meta["snapshot_policy"] == "latest_snapshot_per_trade_date"
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
python -m pytest -q tests/test_quant_raw_model_walkforward_diagnosis.py -k raw_market_panel
```

Expected: FAIL because `load_raw_market_panel` does not exist.

- [ ] **Step 3: Implement the smallest source boundary**

Add imports and one helper near `DATA_FILE`:

```python
from core.data.ashare_ods_loader import AShareOdsLoader

RAW_PANEL_COLUMNS = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"]


def load_raw_market_panel(*, data_file, data_source, start, end, include_bj9, ashare_data_root=""):
    source = str(data_source or "legacy").strip().lower()
    if source == "legacy":
        return pd.read_parquet(data_file, columns=RAW_PANEL_COLUMNS), {"data_source": "legacy", "data_file": str(data_file)}
    if source != "ashare_ods":
        raise ValueError(f"Unsupported data source: {data_source}")
    loader = AShareOdsLoader(ashare_data_root or None)
    raw = loader.load_daily_panel(start, end, include_bj9=bool(include_bj9))
    missing = [col for col in RAW_PANEL_COLUMNS if col not in raw.columns]
    if missing:
        raise RuntimeError(f"ODS daily panel is missing required columns: {','.join(missing)}")
    if raw.empty:
        raise RuntimeError(f"ODS daily_bars has no rows for {start}..{end}")
    return raw.loc[:, RAW_PANEL_COLUMNS].copy(), {
        "data_source": "ashare_ods",
        "ashare_data_root": str(loader.data_root),
        "snapshot_policy": "latest_snapshot_per_trade_date",
    }
```

Update `load_raw_model_frame` to accept `data_source` and `ashare_data_root`, invoke this helper, then retain the existing normalization, filter, indicator, and label sequence. Add CLI flags:

```python
p.add_argument("--data-source", choices=["legacy", "ashare_ods"], default="legacy")
p.add_argument("--ashare-data-root", default="", help="optional shared ODS root; otherwise uses ASHARE_DATA_ROOT")
```

- [ ] **Step 4: Run the source-boundary tests and existing diagnostic tests**

Run:

```bash
python -m pytest -q tests/test_quant_raw_model_walkforward_diagnosis.py
```

Expected: PASS.

### Task 2: Bind cache and output evidence to the selected source

**Files:**
- Modify: `scripts/quant_raw_model_walkforward_diagnosis.py:249-355,660-675,824-863`
- Test: `tests/test_quant_raw_model_walkforward_diagnosis.py`

- [ ] **Step 1: Write the failing cache-lineage test**

Add:

```python
def test_raw_model_frame_cache_request_differs_between_legacy_and_ods(tmp_path):
    data_file = tmp_path / "daily.parquet"
    data_file.write_bytes(b"legacy")

    legacy = diag._raw_model_frame_cache_request(
        data_file=data_file, data_source="legacy", ashare_data_root="", features=["x"], horizons=[8],
        start="2026-01-01", end="2026-01-31", exclude_bj9=True,
    )
    ods = diag._raw_model_frame_cache_request(
        data_file=data_file, data_source="ashare_ods", ashare_data_root="/shared/ods", features=["x"], horizons=[8],
        start="2026-01-01", end="2026-01-31", exclude_bj9=True,
    )

    assert legacy["data_source"] == "legacy"
    assert ods["data_source"] == "ashare_ods"
    assert legacy != ods
```

- [ ] **Step 2: Run the cache-lineage test and verify it fails**

Run:

```bash
python -m pytest -q tests/test_quant_raw_model_walkforward_diagnosis.py -k cache_request_differs
```

Expected: FAIL because the cache request has no source identity arguments.

- [ ] **Step 3: Add source lineage to the cache request and final payload**

Extend `_raw_model_frame_cache_request`, `load_raw_model_frame_cached`, and its builder call with `data_source` and `ashare_data_root`. Add this request portion:

```python
"data_source": str(data_source or "legacy").strip().lower(),
"ashare_data_root": str(Path(ashare_data_root).expanduser().resolve()) if str(ashare_data_root).strip() else "",
"ods_snapshot_policy": "latest_snapshot_per_trade_date" if str(data_source).strip().lower() == "ashare_ods" else "",
```

Pass the CLI values into the cached loader. Add `"data_source": str(args.data_source)` and `"ashare_data_root": str(args.ashare_data_root)` to the emitted JSON payload, retaining `frame_cache` as the authoritative cache request record.

- [ ] **Step 4: Run focused cache and diagnostic tests**

Run:

```bash
python -m pytest -q tests/test_quant_raw_model_walkforward_diagnosis.py
```

Expected: PASS.

### Task 3: Produce bounded parity evidence and document invocation

**Files:**
- Modify: `scripts/quant_raw_model_walkforward_diagnosis.py:623-675`
- Modify: `scripts/README.md`
- Modify: `docs/PROJECT_INDEX.md`
- Test: `tests/test_quant_raw_model_walkforward_diagnosis.py`

- [ ] **Step 1: Write the failing source-parity summary test**

Add a pure helper test:

```python
def test_summarize_raw_panel_reports_date_code_and_required_column_coverage():
    frame = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": pd.to_datetime(["2026-01-02", "2026-01-02"]),
        "open": [10.0, 20.0], "high": [11.0, 21.0], "low": [9.0, 19.0],
        "close": [10.5, 20.5], "vol": [100.0, 200.0], "amount": [1000.0, 2000.0], "pct_chg": [1.0, 2.0],
    })

    out = diag.summarize_raw_panel(frame)

    assert out["rows"] == 2
    assert out["trade_dates"] == 1
    assert out["unique_codes"] == 2
    assert out["required_column_null_rows"] == 0
```

- [ ] **Step 2: Run the parity-summary test and verify it fails**

Run:

```bash
python -m pytest -q tests/test_quant_raw_model_walkforward_diagnosis.py -k summarize_raw_panel
```

Expected: FAIL because `summarize_raw_panel` does not exist.

- [ ] **Step 3: Add the source-panel evidence helper and CLI output**

Implement:

```python
def summarize_raw_panel(frame):
    required = RAW_PANEL_COLUMNS
    missing = [col for col in required if col not in frame.columns]
    work = frame.copy()
    dates = pd.to_datetime(work.get("trade_date", pd.Series(dtype=object)), errors="coerce")
    codes = work.get("ts_code", pd.Series(dtype=object)).astype(str).str.strip()
    null_rows = int(work[required].isna().any(axis=1).sum()) if not missing else int(len(work))
    return {
        "rows": int(len(work)), "trade_dates": int(dates.dt.normalize().nunique()), "unique_codes": int(codes.ne("").sum() and codes.nunique()),
        "date_min": str(dates.min().date()) if dates.notna().any() else "", "date_max": str(dates.max().date()) if dates.notna().any() else "",
        "missing_required_columns": missing, "required_column_null_rows": null_rows,
    }
```

After the cached feature frame is returned, derive `source_panel_summary` from
its retained raw-panel columns, include it in the JSON, and print it once
before the existing `prepared_rows` line. Document both safe commands:

```bash
python scripts/quant_raw_model_walkforward_diagnosis.py --data-source legacy --start 2026-01-02 --end 2026-01-31
ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data python scripts/quant_raw_model_walkforward_diagnosis.py --data-source ashare_ods --start 2026-01-02 --end 2026-01-31
```

Clarify that these are separate diagnostic artifacts, not directly comparable promotion evidence until coverage and unit parity are reviewed.

- [ ] **Step 4: Run targeted tests and a bounded real-data ODS smoke**

Run:

```bash
python -m pytest -q tests/test_quant_raw_model_walkforward_diagnosis.py tests/test_ashare_ods_loader.py tests/test_market_data_units.py
ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data python - <<'PY'
import scripts.quant_raw_model_walkforward_diagnosis as diag

raw, meta = diag.load_raw_market_panel(
    data_file=diag.DATA_FILE,
    data_source="ashare_ods",
    start="2026-07-01",
    end="2026-07-15",
    include_bj9=False,
)
print(meta)
print(diag.summarize_raw_panel(raw))
PY
```

Expected: all tests pass; the smoke prints `data_source=ashare_ods` and a nonzero source-panel row count with no missing required columns. Do not treat this short smoke as alpha evidence.

- [ ] **Step 5: Review scope and commit only intentional files**

Run:

```bash
git diff -- scripts/quant_raw_model_walkforward_diagnosis.py tests/test_quant_raw_model_walkforward_diagnosis.py scripts/README.md docs/PROJECT_INDEX.md docs/superpowers/specs/2026-07-16-raw-model-ods-entry-design.md docs/superpowers/plans/2026-07-16-raw-model-ods-entry.md
git status --short
```

Expected: only planned files are reviewed; do not stage unrelated existing worktree changes. If the user requests a commit, stage only these intentional files and include the verification result in the commit message/body.
