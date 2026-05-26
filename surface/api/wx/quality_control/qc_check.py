import time
import pytz
import logging
from datetime import timedelta

from wx.quality_control.thresholds import (
    resolve_range_thresholds,
    resolve_step_thresholds,
    resolve_persist_thresholds,
)
from wx.quality_control.evaluators import (
    evaluate_range_qc,
    evaluate_step_qc,
    evaluate_persist_qc,
    determine_final_qc,
)

from wx.quality_control.helpers import convert_records_to_utc, get_historical_measured_records


logger = logging.getLogger("surface")


# ---------------------------------------------------------------------
# QC CONTEXT BUILDER
# ---------------------------------------------------------------------
def build_qc_context(
    station_id,
    variable_id,
    month,
    data_batch,
    station_offset,
    previous_db_record=None,
):
    """
    Prepare reusable QC data for a station/variable/month group.

    This should be called once per group, not once per observation.
    It resolves thresholds once and converts the batch datetimes to UTC once.

    Args:
        station_id (int):
            Station identifier.
        variable_id (int):
            Variable identifier.
        month (int):
            Month number, 1-12.
        data_batch (list):
            Current ingest batch containing dictionaries with:
                - 'datetime'
                - 'measured'
        station_offset (int):
            Station UTC offset in minutes.

    Returns:
        dict:
            Reusable QC context for evaluate_qc_row().
    """

    thresholds = {
        "suspicious_step_threshold": False,
        "suspicious_range_threshold": False,
        "suspicious_persist_threshold": False,
    }

    thresholds = resolve_step_thresholds(
        thresholds=thresholds,
        station_id=station_id,
        variable_id=variable_id,
    )

    thresholds = resolve_range_thresholds(
        thresholds=thresholds,
        station_id=station_id,
        variable_id=variable_id,
        month=month,
    )

    thresholds = resolve_persist_thresholds(
        thresholds=thresholds,
        station_id=station_id,
        variable_id=variable_id,
    )

    data_batch_utc = convert_records_to_utc(data_batch, station_offset)

    persist_windows = []

    for prefix in ["glob", "ref", "cus"]:
        wnd = thresholds.get(f"{prefix}_persist_wnd")
        min_var = thresholds.get(f"{prefix}_persist_min_var")

        if wnd is not None and min_var is not None:
            persist_windows.append(wnd)

    historical_records_utc = []

    if persist_windows and data_batch_utc:
        max_persist_window = max(persist_windows)

        batch_datetimes = [
            record["datetime"]
            for record in data_batch_utc
        ]

        earliest_batch_datetime = min(batch_datetimes)
        latest_batch_datetime = max(batch_datetimes)

        historical_window_start = earliest_batch_datetime - timedelta(hours=max_persist_window)
        historical_window_end = latest_batch_datetime

        historical_records_utc = get_historical_measured_records(
            window_start=historical_window_start,
            window_end=historical_window_end,
            station_id=station_id,
            variable_id=variable_id,
        )

    offset = pytz.FixedOffset(station_offset)

    return {
        "thresholds": thresholds,
        "station_offset": station_offset,
        "station_offset_tz": offset,
        "data_batch_utc": data_batch_utc,
        "historical_records_utc": historical_records_utc,
        "timing": {
            "step": 0.0,
            "range": 0.0,
            "persist": 0.0,
        },
        "previous_db_record": previous_db_record,
    }


# ---------------------------------------------------------------------
# ROW QC EVALUATOR
# ---------------------------------------------------------------------
def evaluate_qc_row(row, station_id, variable_id, qc_context):
    """
    Evaluate QC for one observation using a pre-built QC context.

    This function does not query the Station table and does not resolve
    thresholds. Those expensive operations should happen once in
    build_qc_context().
    """

    thresholds = qc_context["thresholds"]
    station_offset = qc_context["station_offset"]
    data_batch_utc = qc_context["data_batch_utc"]

    value = row.measured
    dt = row.datetime

    offset = qc_context["station_offset_tz"]

    if dt.tzinfo:
        row_datetime_utc = dt.astimezone(pytz.UTC)
    else:
        row_datetime_utc = offset.localize(dt).astimezone(pytz.UTC)

    result_step, msg_step = evaluate_step_qc(
        value=value,
        thresholds=thresholds,
        data_batch=data_batch_utc,
        row_datetime_utc=row_datetime_utc,
        station_id=station_id,
        variable_id=variable_id,
        previous_db_record=qc_context.get("previous_db_record"),
    )

    result_range, msg_range = evaluate_range_qc(
        value,
        thresholds,
    )

    result_persist, msg_persist = evaluate_persist_qc(
        value=value,
        station_id=station_id,
        variable_id=variable_id,
        thresholds=thresholds,
        data_batch=data_batch_utc,
        row_datetime_utc=row_datetime_utc,
        historical_records=qc_context.get("historical_records_utc"),
    )

    result_final = determine_final_qc(
        result_step,
        result_range,
        result_persist,
    )

    return [
        result_step,
        msg_step,
        result_range,
        msg_range,
        result_persist,
        msg_persist,
        result_final,
    ]


# ---------------------------------------------------------------------
# BACKWARDS-COMPATIBLE QC ENTRYPOINT
# ---------------------------------------------------------------------
def qc_thresholds(row, station_id, variable_id, month, data_batch, station_offset=None):
    """
    Backwards-compatible QC entrypoint.

    Existing code can still call:
        qc_thresholds(row, station_id, variable_id, month, data_batch)

    Optimized code should pass station_offset or use:
        build_qc_context(...)
        evaluate_qc_row(...)

    ================================================================================================================================================

    Execute all Quality Control (QC) checks for a single observation.

    This function acts as the orchestration layer for QC evaluation. It
    resolves applicable thresholds, evaluates each QC test independently
    (STEP, RANGE, PERSISTENCE), and then combines the individual results
    into a final QC flag.

    QC checks performed:
        1. STEP        - Detects unrealistic jumps between consecutive values
        2. RANGE       - Ensures the value lies within physically valid bounds
        3. PERSISTENCE - Detects values that remain effectively unchanged over time

    Threshold resolution follows this priority order:
        • Station-specific threshold
        • Reference-station threshold
        • Global variable threshold

    Global thresholds never return GOOD; they downgrade passing results
    to SUSPICIOUS to reflect lower confidence.

    Time handling:
        • Input datetimes may be naive or timezone-aware
        • All persistence calculations are performed in UTC
        • Batch records are converted to UTC before evaluation

    IMPORTANT:
        The return structure is relied upon by downstream database inserts
        and MUST NOT be modified.

    Args:
        row:
            ORM row or record containing:
                - measured value
                - datetime
                - diff_value (current - previous)
        station_id (int):
            Station identifier.
        variable_id (int):
            Variable identifier.
        month (int):
            Month (1 - 12) used for seasonal range thresholds.
        data_batch (list):
            Current ingest batch containing dictionaries with:
                - 'datetime'
                - 'measured'

    Returns:
        list:
            [
                step_flag,
                step_message,
                range_flag,
                range_message,
                persist_flag,
                persist_message,
                final_flag
            ]
    """

    if station_offset is None:
        from wx.models import Station

        station_offset = Station.objects.values_list(
            "utc_offset_minutes",
            flat=True,
        ).get(id=station_id)

    qc_context = build_qc_context(
        station_id=station_id,
        variable_id=variable_id,
        month=month,
        data_batch=data_batch,
        station_offset=station_offset,
    )

    return evaluate_qc_row(
        row=row,
        station_id=station_id,
        variable_id=variable_id,
        qc_context=qc_context,
    )