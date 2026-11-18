"""SURFACE Automated QC evaluations with explanatory, audit-friendly descriptions.

The return contract remains ``(quality_flag_id, description_string)``.
Descriptions use plain text/newlines so existing database fields and the
Vue/Vuetify ``white-space: pre-line`` display remain compatible.

Changes:
  * Range and Step: more informative description text only; same evaluations.
  * Persistence: no early GOOD when a tier lacks prior observations; recognize
    partially configured tiers; omit missing measurements from history extrema.
  * Final aggregation: unchanged.

No unit symbol is supplied to these functions: the measurements and threshold
values in a description therefore share the variable's configured units, but
we deliberately do not invent a unit label.
"""

from datetime import datetime, timedelta
from math import isnan

from wx.enums import QualityFlagEnum
from wx.quality_control.helpers import get_min_max_measured, get_prev_measured, is_missing


# ---------------------------------------------------------------------
# Quality flag shortcuts
# ---------------------------------------------------------------------
GOOD = QualityFlagEnum.GOOD.id
NOT_CHECKED = QualityFlagEnum.NOT_CHECKED.id
BAD = QualityFlagEnum.BAD.id
SUSPICIOUS = QualityFlagEnum.SUSPICIOUS.id
MISSING = QualityFlagEnum.MISSING.id

_FLAG_LABELS = {
    GOOD: "GOOD",
    NOT_CHECKED: "NOT CHECKED",
    BAD: "BAD",
    SUSPICIOUS: "SUSPICIOUS",
    MISSING: "MISSING",
}

_TIER_CONFIGS = (("Global", "glob"), ("Reference", "ref"), ("Custom", "cus"))


def _description_header(method, configured_description):
    """Create a consistent, readable beginning for all three QC methods."""
    lines = [f"{method.upper()} QUALITY CONTROL"]
    if configured_description:
        lines.extend(["", f"Configured description: {configured_description}"])
    return lines


def _description_result(lines, flag, explanation):
    """Preserve the original (flag, plain-text-description) return contract."""
    lines.extend([
        "",
        "FINAL ASSESSMENT",
        f"QC flag: {_FLAG_LABELS.get(flag, flag)}",
        f"Reason: {explanation}",
    ])
    return flag, "\n".join(lines)


def _configured_bound_snapshot(lines, thresholds, method):
    """Show all configured bounds, including tiers skipped by early exits."""
    lines.extend(["", "CONFIGURED THRESHOLDS (as evaluated)"])
    for label, prefix in _TIER_CONFIGS:
        minimum = thresholds.get(f"{prefix}_{method}_min")
        maximum = thresholds.get(f"{prefix}_{method}_max")
        if minimum is None and maximum is None:
            lines.append(f"{label}: not configured")
        elif minimum is None or maximum is None:
            lines.append(
                f"{label}: incomplete (minimum={minimum}, maximum={maximum})"
            )
        else:
            lines.append(
                f"{label}: minimum={minimum}; maximum={maximum} "
                "(inclusive limits)"
            )


def _bounds_result(lines, tier, measured, lower, upper):
    """Append the actual comparison and explain which bound failed."""
    lines.extend([
        f"{tier} threshold:",
        f"  Comparison: {lower} <= {measured} <= {upper}",
    ])

    if lower <= measured <= upper:
        lines.append("  Result: PASSED — within the inclusive limits.")
        return True

    if measured < lower:
        distance = float(lower) - float(measured)
        lines.append(
            f"  Result: FAILED — below the minimum by {distance:.6g}."
        )
    elif measured > upper:
        distance = float(measured) - float(upper)
        lines.append(
            f"  Result: FAILED — above the maximum by {distance:.6g}."
        )
    else:
        lines.append("  Result: FAILED — the value is not within the permitted interval.")
    return False


def _skipped_tiers(lines, labels, reason):
    for label in labels:
        lines.append(f"{label} threshold: NOT EVALUATED — {reason}.")


# ---------------------------------------------------------------------
# STEP QC EVALUATION
# ---------------------------------------------------------------------
def evaluate_step_qc(
    value: float,
    thresholds: dict,
    data_batch: list,
    row_datetime_utc: datetime,
    station_id: int,
    variable_id: int,
    previous_db_record=None,
):
    """Evaluate a *signed* step change against Global, Reference, Custom bounds.

    The original Step arithmetic, comparison order, and flag rules
    have been preserved. A negative difference represents a drop and can fail
    a negative minimum; a positive difference represents an increase.
    """
    lines = _description_header("Step", thresholds.get("step_description"))
    lines.extend([
        "",
        f"Observation time (UTC): {row_datetime_utc.isoformat()}",
        f"Current measured value: {value}",
    ])
    _configured_bound_snapshot(lines, thresholds, "step")

    if is_missing(value):
        lines.extend(["", "EVALUATION", "All Step thresholds: NOT EVALUATED — current value is missing."])
        return _description_result(lines, MISSING, "The current observation is missing; Step QC was skipped.")

    # Keep the original search for the most recent usable value in this batch.
    prev_measured = None
    previous_timestamp = None
    previous_source = None
    diff_value = None

    for data_row in data_batch:
        if data_row['datetime'] == row_datetime_utc:
            break
        if not is_missing(data_row['measured']):
            prev_measured = data_row['measured']
            previous_timestamp = data_row['datetime']
            previous_source = "current ingest batch"

    if prev_measured is not None:
        # Intentionally signed and unrounded, as in the original batch path.
        diff_value = float(value) - float(prev_measured)
    else:
        diff_value_date = None
        if previous_db_record is not None:
            diff_value_date, prev_measured = previous_db_record
        else:
            diff_value_date, prev_measured = get_prev_measured(
                row_datetime_utc, station_id, variable_id,
            )

        previous_timestamp = diff_value_date
        previous_source = "database history"
        if is_missing(prev_measured):
            diff_value = None
        elif prev_measured is not None:
            # Preserve the original DB branch's 3-decimal rounding.
            diff_value = round(float(value) - float(prev_measured), 3)

    # The original rule considers a tier usable when both keys are present.
    # We intentionally don't change Step tier/flag semantics in this update.
    def get_step(prefix):
        min_key = f"{prefix}_step_min"
        max_key = f"{prefix}_step_max"
        if min_key in thresholds and max_key in thresholds:
            return thresholds[min_key], thresholds[max_key]
        return None

    glob_step = get_step("glob")
    ref_step = get_step("ref")
    cus_step = get_step("cus")

    lines.extend([
        "",
        "STEP DIFFERENCE",
        f"Previous measured value: {prev_measured if prev_measured is not None else 'not available'}",
        f"Previous observation time (UTC): {previous_timestamp.isoformat() if isinstance(previous_timestamp, datetime) else (previous_timestamp if previous_timestamp is not None else 'not available')}",
        f"Previous value source: {previous_source or 'not available'}",
        "Formula: current measured value - previous measured value",
        f"Signed difference used for comparison: {diff_value if diff_value is not None else 'not available'}",
        "A positive difference is an increase; a negative difference is a decrease.",
        "",
        "EVALUATION",
    ])

    if not any([glob_step, ref_step, cus_step]):
        _skipped_tiers(lines, ["Global", "Reference", "Custom"], "no complete thresholds were found")
        return _description_result(lines, NOT_CHECKED, "No Step thresholds are configured for evaluation.")

    if diff_value is None or isnan(diff_value):
        _skipped_tiers(lines, ["Global", "Reference", "Custom"], "no usable previous value was available to calculate the step difference")
        return _description_result(lines, NOT_CHECKED, "The Step difference could not be calculated from a previous observation.")

    if not glob_step:
        _skipped_tiers(lines, ["Global", "Reference", "Custom"], "the mandatory Global Step threshold is missing")
        return _description_result(lines, NOT_CHECKED, "The mandatory Global Step threshold is not configured.")

    g_min, g_max = glob_step
    if not _bounds_result(lines, "Global", diff_value, g_min, g_max):
        _skipped_tiers(lines, ["Reference", "Custom"], "Global Step threshold failed")
        return _description_result(lines, BAD, "The signed step difference is outside the Global Step limits.")

    if not ref_step:
        _skipped_tiers(lines, ["Reference", "Custom"], "the Reference Step threshold is missing")
        return _description_result(lines, SUSPICIOUS, "Global passed, but the required Reference Step threshold was not available.")

    r_min, r_max = ref_step
    if not _bounds_result(lines, "Reference", diff_value, r_min, r_max):
        _skipped_tiers(lines, ["Custom"], "Reference Step threshold failed")
        return _description_result(lines, SUSPICIOUS, "Global passed, but the Reference Step limits were exceeded.")

    if not cus_step:
        _skipped_tiers(lines, ["Custom"], "the Custom Step threshold is missing")
        return _description_result(lines, SUSPICIOUS, "Global and Reference passed, but the Custom Step threshold was not available.")

    c_min, c_max = cus_step
    if not _bounds_result(lines, "Custom", diff_value, c_min, c_max):
        return _description_result(lines, SUSPICIOUS, "Global and Reference passed, but the Custom Step limits were exceeded.")

    return _description_result(lines, GOOD, "The signed step difference passed Global, Reference, and Custom limits.")


# ---------------------------------------------------------------------
# RANGE QC EVALUATION
# ---------------------------------------------------------------------
def evaluate_range_qc(value: float, thresholds: dict):
    """Evaluate the observed value against Global, Reference, Custom bounds.

    QC decisions and tier precedence match the original Range evaluator;
    only the explanation text has been expanded.
    """
    lines = _description_header("Range", thresholds.get("range_description"))
    lines.extend(["", f"Current measured value: {value}"])
    _configured_bound_snapshot(lines, thresholds, "range")

    if is_missing(value):
        lines.extend(["", "EVALUATION", "All Range thresholds: NOT EVALUATED — current value is missing."])
        return _description_result(lines, MISSING, "The current observation is missing; Range QC was skipped.")

    def get_range(prefix):
        min_key = f"{prefix}_range_min"
        max_key = f"{prefix}_range_max"
        if min_key in thresholds and max_key in thresholds:
            return thresholds[min_key], thresholds[max_key]
        return None

    glob_range = get_range("glob")
    ref_range = get_range("ref")
    cus_range = get_range("cus")

    lines.extend(["", "EVALUATION"])

    if not any([glob_range, ref_range, cus_range]):
        _skipped_tiers(lines, ["Global", "Reference", "Custom"], "no complete thresholds were found")
        return _description_result(lines, NOT_CHECKED, "No Range thresholds are configured for evaluation.")

    if not glob_range:
        _skipped_tiers(lines, ["Global", "Reference", "Custom"], "the mandatory Global Range threshold is missing")
        return _description_result(lines, NOT_CHECKED, "The mandatory Global Range threshold is not configured.")

    g_min, g_max = glob_range
    if not _bounds_result(lines, "Global", value, g_min, g_max):
        _skipped_tiers(lines, ["Reference", "Custom"], "Global Range threshold failed")
        return _description_result(lines, BAD, "The measured value is outside the Global Range limits.")

    if not ref_range:
        _skipped_tiers(lines, ["Reference", "Custom"], "the Reference Range threshold is missing")
        return _description_result(lines, SUSPICIOUS, "Global passed, but the Reference Range threshold is unavailable.")

    r_min, r_max = ref_range
    if not _bounds_result(lines, "Reference", value, r_min, r_max):
        _skipped_tiers(lines, ["Custom"], "Reference Range threshold failed")
        return _description_result(lines, SUSPICIOUS, "Global passed, but the measured value is outside the Reference Range limits.")

    if not cus_range:
        _skipped_tiers(lines, ["Custom"], "the Custom Range threshold is missing")
        return _description_result(lines, SUSPICIOUS, "Global and Reference passed, but the Custom Range threshold is unavailable.")

    c_min, c_max = cus_range
    if not _bounds_result(lines, "Custom", value, c_min, c_max):
        return _description_result(lines, SUSPICIOUS, "Global and Reference passed, but the measured value is outside the Custom Range limits.")

    return _description_result(lines, GOOD, "The measured value passed Global, Reference, and Custom Range limits.")


# ---------------------------------------------------------------------
# PERSISTENCE QC EVALUATION
# ---------------------------------------------------------------------
def evaluate_persist_qc(
    value: float,
    station_id: int,
    variable_id: int,
    thresholds: dict,
    data_batch: list,
    row_datetime_utc: datetime,
    historical_records=None,
):
    """Evaluate whether a reading remained too constant over a time window.

    Previous valid observations are taken from the historical database and
    batch inside [row_datetime_utc - window, row_datetime_utc). The current
    observation is added for the variance check. Variance is max - min,
    rounded to three decimal places, as in the original implementation.

    Policy intentionally preserved: no prior values in a tier's window ->
    that tier passes. But *all* complete tiers must still be checked.

    BAD: any complete tier fails (takes precedence over incomplete configs).
    NOT CHECKED: no complete tiers, or incomplete tier(s) with no BAD.
    GOOD: at least one complete tier exists and all configured tiers pass.
    """
    lines = _description_header("Persistence", thresholds.get("persist_description"))
    lines.extend([
        "",
        f"Observation time (UTC): {row_datetime_utc.isoformat()}",
        f"Current measured value: {value}",
        "Calculation: variance = maximum value - minimum value, including current observation.",
        "History window: start inclusive, current observation time exclusive.",
    ])

    # Snapshot *all* configured limits before evaluation. This records the
    # precise settings available at QC time, including missing/partial tiers.
    lines.extend(["", "CONFIGURED THRESHOLDS (as evaluated)"])
    partial_tiers = []
    tiers = {}
    for label, prefix in _TIER_CONFIGS:
        wnd = thresholds.get(f"{prefix}_persist_wnd")
        minimum_variance = thresholds.get(f"{prefix}_persist_min_var")

        if wnd is None and minimum_variance is None:
            tiers[label] = None
            lines.append(f"{label}: not configured")
        elif wnd is None or minimum_variance is None:
            tiers[label] = None
            missing_field = "window duration" if wnd is None else "minimum required variance"
            partial_tiers.append(label)
            lines.append(
                f"{label}: INCOMPLETE — window={wnd} hour(s); "
                f"minimum required variance={minimum_variance}; "
                f"missing {missing_field}"
            )
        else:
            tiers[label] = (wnd, minimum_variance)
            lines.append(
                f"{label}: window={wnd} hour(s); "
                f"minimum required variance={minimum_variance}"
            )

    lines.extend(["", "EVALUATION"])

    if is_missing(value):
        lines.append("All Persistence tiers: NOT EVALUATED — current observation is missing.")
        return _description_result(lines, MISSING, "The current observation is missing; Persistence QC was skipped.")

    # A partially configured tier is not silently treated as absent. Record
    # it and return NOT CHECKED unless another complete tier proves BAD.
    for label, cfg in tiers.items():
        if cfg is None:
            status = "INCOMPLETE" if label in partial_tiers else "NOT CONFIGURED"
            lines.append(f"{label} threshold: {status} — not evaluated.")

    if all(cfg is None for cfg in tiers.values()):
        if partial_tiers:
            reason = (
                "No complete Persistence tier is available; the following tiers "
                f"are partially configured: {', '.join(partial_tiers)}."
            )
        else:
            reason = "No Persistence thresholds are configured."
        return _description_result(lines, NOT_CHECKED, reason)

    # ---------------------------------------------------------------
    # Evaluate each fully configured tier in order (Global/Ref/Custom).
    # ---------------------------------------------------------------
    for label, cfg in tiers.items():
        if cfg is None:
            continue

        window_hours, minimum_variance = cfg
        window_start = row_datetime_utc - timedelta(hours=window_hours)
        window_end = row_datetime_utc

        # Get the extrema from valid historical observations. The preloaded
        # path historically omitted the missing-value check: fix that here.
        if historical_records is not None:
            history_min = None
            history_max = None
            for record in historical_records:
                record_dt = record["datetime"]
                if record_dt >= window_end:
                    break
                if record_dt < window_start:
                    continue

                historical_value = record["measured"]
                if historical_value is None or is_missing(historical_value):
                    continue

                history_min = historical_value if history_min is None else min(history_min, historical_value)
                history_max = historical_value if history_max is None else max(history_max, historical_value)
        else:
            history_min, history_max = get_min_max_measured(
                window_start, window_end, station_id, variable_id,
            )
            # A missing sentinel returned as an extremum must never produce
            # artificial variation (e.g. -99.9 alongside a real reading).
            if history_min is not None and is_missing(history_min):
                history_min = None
            if history_max is not None and is_missing(history_max):
                history_max = None

        # Keep the existing sorted-batch traversal. Ignore missing readings.
        batch_min = None
        batch_max = None
        for row_data in data_batch:
            row_dt = row_data["datetime"]
            if row_dt >= window_end:
                break
            if row_dt < window_start:
                continue
            if is_missing(row_data["measured"]):
                continue

            batch_value = row_data["measured"]
            batch_min = batch_value if batch_min is None else min(batch_min, batch_value)
            batch_max = batch_value if batch_max is None else max(batch_max, batch_value)

        previous_extrema = []
        if None not in (history_min, history_max):
            previous_extrema.extend([history_min, history_max])
        if None not in (batch_min, batch_max):
            previous_extrema.extend([batch_min, batch_max])

        lines.extend([
            "",
            f"{label.upper()} PERSISTENCE THRESHOLD",
            f"Window duration: {window_hours} hour(s)",
            f"Window start (UTC, inclusive): {window_start.isoformat()}",
            f"Window end (UTC, exclusive): {window_end.isoformat()}",
            f"Historical observations source: {'preloaded history' if historical_records is not None else 'database query'}",
            f"Historical minimum / maximum: {history_min} / {history_max}",
            f"Batch minimum / maximum: {batch_min} / {batch_max}",
            f"Required minimum variance: {minimum_variance}",
        ])

        if not previous_extrema:
            # FIX 1: This tier passes under existing policy, but a longer
            # Reference/Custom window may still contain valid observations.
            lines.append(
                "Result: PASSED (no valid previous observations in this "
                "window; variance was not calculated). Continuing to "
                "the next configured tier."
            )
            continue

        # Include the current measured value just as the original evaluator
        # did. Maintain the 3-decimal rounding used for its QC comparison.
        values = previous_extrema + [value]
        minimum_observed = min(values)
        maximum_observed = max(values)
        calculated_variance = round(maximum_observed - minimum_observed, 3)

        lines.extend([
            f"Minimum in window (including current): {minimum_observed}",
            f"Maximum in window (including current): {maximum_observed}",
            f"Calculated variance (rounded to 3 decimals): {calculated_variance}",
            f"Comparison: {calculated_variance} >= {minimum_variance}",
        ])

        if calculated_variance < minimum_variance:
            deficit = float(minimum_variance) - float(calculated_variance)
            lines.append(
                f"Result: FAILED — variance is below the required minimum "
                f"by {deficit:.6g}."
            )
            # Preserve original BAD precedence and stop after first failure.
            # Only complete later tiers need a skipped-evaluation message.
            # Absent or partial tiers were already identified above.
            tier_names = list(tiers)
            remaining = [
                name for name in tier_names[tier_names.index(label) + 1:]
                if tiers[name] is not None
            ]
            _skipped_tiers(lines, remaining, "an earlier Persistence tier failed")
            if partial_tiers:
                lines.append(f"Configuration warning: incomplete tiers: {', '.join(partial_tiers)}.")
            return _description_result(
                lines, BAD,
                f"The {label} Persistence threshold failed (observed variance "
                f"{calculated_variance} is below minimum {minimum_variance}).",
            )

        lines.append("Result: PASSED — variance meets or exceeds the required minimum.")

    # FIX 2: A partial configuration is NOT CHECKED if none of the complete
    # tiers proved BAD. Previously partial tiers were silently skipped.
    if partial_tiers:
        return _description_result(
            lines, NOT_CHECKED,
            "Fully configured Persistence tiers did not fail, but "
            f"the following tiers are incomplete: {', '.join(partial_tiers)}.",
        )

    return _description_result(
        lines, GOOD,
        "All fully configured Persistence thresholds passed. "
        "Tiers with no previous observations are treated as passes "
        "under the existing SURFACE QC policy.",
    )


# ---------------------------------------------------------------------
# FINAL QC AGGREGATION (UNCHANGED)
# ---------------------------------------------------------------------
def determine_final_qc(step_flag: int, range_flag: int, persist_flag: int) -> int:
    """
        Determines the global Quality Control status based on a worst-case priority.

        The final flag is derived hierarchically:
        1. BAD: If any individual check is BAD.
        2. SUSPICIOUS: If no BAD exists, but at least one check is SUSPICIOUS.
        3. MISSING: If no SUSPICIOUS exists, but at least one check is MISSING.
        4. GOOD: If no higher severity exists and at least one check is GOOD.
        5. NOT_CHECKED: Default fallback if no flags are set.

        Args:
            step_flag (int): Result of the step-test analysis.
            range_flag (int): Result of the range-limit analysis.
            persist_flag (int): Result of the persistence/stuck-sensor analysis.

        Returns:
            int: The most conservative QC flag applicable to the dataset.
    """

    if BAD in [range_flag, persist_flag, step_flag]:
        return BAD
    if SUSPICIOUS in [range_flag, persist_flag, step_flag]:
        return SUSPICIOUS
    if MISSING in [range_flag, persist_flag, step_flag]:
        return MISSING
    if GOOD in [range_flag, persist_flag, step_flag]:
        return GOOD
    return NOT_CHECKED