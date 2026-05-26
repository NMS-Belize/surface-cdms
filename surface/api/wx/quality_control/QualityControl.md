# Quality Control (QC) System – Design & Flow

This module implements a **deterministic, tier-aware, auditable Quality Control (QC) pipeline** for meteorological observations.

Each observation is evaluated independently using:

- **STEP check**
- **RANGE check**
- **PERSISTENCE check**

Each check is executed independently, and results are aggregated using a strict worst-case priority model.

---

# Design Goals

- Deterministic results
- Explicit threshold provenance
- Tier-aware validation (Custom / Reference / Global)
- Strict failure semantics
- Timezone-safe persistence logic
- Zero hidden fallback behavior

---

# High-Level Architecture

```
quality_control/
│
├── qc_check.py        # Orchestration / entrypoint
├── evaluators.py      # Pure QC decision logic
├── thresholds.py      # Threshold resolution (no fallback merging)
└── helpers.py         # Time handling & DB helpers
```

Each module has a single responsibility.

---

# Execution Flow

For each observation:

1. Resolve STEP, RANGE, and PERSISTENCE thresholds
2. Normalize timestamps to UTC
3. Evaluate STEP
4. Evaluate RANGE
5. Evaluate PERSISTENCE
6. Aggregate final QC flag

All checks are independent. No check mutates another.

---

# Entry Point – `qc_thresholds()`

**File:** `qc_check.py`

```python
qc_thresholds(row, station_id, variable_id, month, data_batch)
```

## Responsibilities

- Resolve thresholds (all tiers independently)
- Normalize timestamps to UTC
- Execute evaluators
- Combine results into a final QC flag

---

## Output Contract (DO NOT CHANGE)

```python
[
    step_flag,
    step_message,
    range_flag,
    range_message,
    persist_flag,
    persist_message,
    final_flag
]
```

This structure is relied upon by downstream insert logic.

---

# Threshold Resolution

**File:** `thresholds.py`

Thresholds are resolved independently from three tiers:

1. **Custom station threshold**
2. **Reference station threshold**
3. **Global variable threshold**

⚠️ Important:

- No downward fallback logic is applied.
- All tiers are retrieved independently.
- Missing tiers do not automatically inherit from others.

Each resolver:

- Attaches prefixed keys:
  - `cus_*`
  - `ref_*`
  - `glob_*`
- Stores a combined description string.

---

# STEP Check

**File:** `evaluators.py`

## Purpose

Detect unrealistic jumps between consecutive values.

### Input

```python
diff_value = current_value - previous_value
```

---

## Tier Logic

STEP evaluation follows strict tier validation:

### 1️⃣ No thresholds exist at all

→ `NOT_CHECKED`

---

### 2️⃣ Global threshold missing

Global is mandatory.

→ `NOT_CHECKED`

---

### 3️⃣ Global fails

If:

```
diff_value < glob_min OR diff_value > glob_max
```

→ `BAD`

---

### 4️⃣ Global passes

Then:

- If reference tier missing → `SUSPICIOUS`
- If reference fails → `SUSPICIOUS`
- If custom tier missing → `SUSPICIOUS`
- If custom fails → `SUSPICIOUS`

---

### 5️⃣ All tiers exist AND pass

→ `GOOD`

---

# RANGE Check

**File:** `evaluators.py`

## Purpose

Ensure value is physically plausible.

Logic is identical to STEP, but applied to:

```
range_min ≤ value ≤ range_max
```

### Rules

- Global mandatory
- Global fail → `BAD`
- Missing or failing reference → `SUSPICIOUS`
- Missing or failing custom → `SUSPICIOUS`
- All tiers present and pass → `GOOD`
- No thresholds at all → `NOT_CHECKED`

---

# PERSISTENCE Check

**Files:** `evaluators.py`, `helpers.py`

## Purpose

Detect flatlined or frozen sensors.

---

# Persistence Window

Let `t₀` be the current observation timestamp (UTC).

For each configured tier:

```
window_start = t₀ − window_hours
window_end   = t₀
```

Half-open interval:

```
window_start ≤ datetime < window_end
```

The current value at `t₀` is always manually included.

---

# Data Sources Used

Variance is computed from:

1. Historical DB data (`raw_data`)
2. Earlier values in the current batch
3. Current observation

All timestamps are normalized to UTC.

---

# Variance Calculation

```
variance = max(values) − min(values)
```

---

# Tier Evaluation Rules

Each tier (Global, Reference, Custom) is evaluated independently.

For a tier to be valid:

- Both `window` AND `minimum_variance` must exist.
- Partial configuration → treated as not configured.

---

## Decision Logic

### 1️⃣ No valid tiers exist

→ `NOT_CHECKED`

---

### 2️⃣ For each valid tier:

If:

```
variance < minimum_variance
```

→ Immediately `BAD`

(Equality is NOT considered failure.)

---

### 3️⃣ If all valid tiers pass

→ `GOOD`

---

⚠️ Unlike STEP and RANGE:

- Global is NOT mandatory.
- Missing tiers do NOT cause `SUSPICIOUS`.
- Only failure produces `BAD`.

---

# Timezone Handling

All persistence calculations operate in UTC.

Rules:

- Station UTC offset (minutes) is retrieved.
- Naive datetimes are assumed station-local.
- Localized using station offset.
- Converted to UTC.
- Batch records are converted before evaluation.

This ensures DB and batch windows align perfectly.

---

# Final QC Aggregation

**File:** `evaluators.py`

Aggregation follows strict worst-case priority:

```
If any BAD → BAD
Else if any SUSPICIOUS → SUSPICIOUS
Else if any GOOD → GOOD
Else → NOT_CHECKED
```

Severity order:

```
BAD > SUSPICIOUS > GOOD > NOT_CHECKED
```

This guarantees conservative data validation.

---

# Key Behavioral Differences Between Checks

| Feature                | STEP | RANGE | PERSIST |
|------------------------|------|-------|---------|
| Global mandatory       | Yes  | Yes   | No      |
| Missing ref     | SUSPICIOUS | SUSPICIOUS | Ignored |
| Missing custom     | SUSPICIOUS | SUSPICIOUS | Ignored |
| Any tier failure       | BAD or SUSPICIOUS | BAD or SUSPICIOUS | BAD |
| Equality fails         | No  | No   | No (<) |
| Partial config allowed | No   | No    | No      |

---

# System Guarantees

- Deterministic: Same input → same output
- Tier-aware: Provenance always known
- No silent fallback
- No double counting in windows
- Conservative by design
- Extendable for additional QC tests

---

# Extending the QC System

To add a new QC check:

1. Create threshold resolver
2. Implement evaluator
3. Add call inside `qc_thresholds()`
4. Update final aggregation if needed

No existing logic needs modification.

---

# Summary

This QC pipeline:

- Separates resolution from evaluation
- Uses strict tier validation
- Applies conservative final aggregation
- Ensures timezone-safe persistence analysis
- Avoids implicit threshold inheritance
- Preserves a stable output contract