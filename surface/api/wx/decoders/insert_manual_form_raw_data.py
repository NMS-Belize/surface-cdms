"""Manual workbook QC preparation using the shared raw-data write operations."""

import logging
import time

import pandas as pd
import pytz
from django.utils import timezone

from tempestas_api import settings
from wx.decoders.insert_raw_data import (
    columns, insert_columns, insert_query, qc_columns, update_stationvariable,
)
from wx.models import Station, Variable
from wx.quality_control.helpers import get_prev_measured_bulk
from wx.quality_control.qc_check import build_qc_context, evaluate_qc_row

logger = logging.getLogger("surface")

# Edit the wording here to change what appears in the Range QC column.
MANUAL_RANGE_DESCRIPTIONS = {
    (0, "T"): "Trace amounts of precipitation (T) insufficient to make a reading. Recorded as 0 mm.",
    (4053, "OF"): "Observer reported evaporation pan overflow (OF), unable to make a reading. Recorded as 0.",
}

# suspicious flag code
SUSPICIOUS = 2


def evaluate_manual_row(row, station_id, variable_id, qc_context):
    description = MANUAL_RANGE_DESCRIPTIONS.get((variable_id, row["source_code"]))
    if description is not None and row["measured"] == 0:
        # Only Range and the overall QC result apply to these observer codes.
        result = dict.fromkeys(qc_columns)
        result.update(qc_range_quality_flag=SUSPICIOUS,
                      qc_range_description=description, quality_flag=SUSPICIOUS)
        return [result[column] for column in qc_columns]

    return evaluate_qc_row(row=row, station_id=station_id,
                           variable_id=variable_id, qc_context=qc_context)


def get_data(raw_data_list, source_codes=None):
    """
    Convert decoded raw tuples into rows ready for bulk insertion.
    Main optimization:
    - Older code called qc_thresholds(...) for every row.
    - That caused repeated threshold lookups, station offset lookups, and previous-value lookups.
    - This version groups the data first, then builds QC context once per group.
    A group is:
        station_id + variable_id + seconds + month
    This matters because QC thresholds and previous-value context are normally the same
    for all rows in one group.
    Additional optimization:
    - Use pandas groupby() once and reuse the grouped DataFrames.
    - This avoids repeatedly scanning/filtering the full DataFrame for each group.
    """
    start_total = time.perf_counter()
    now = timezone.now()
    df = pd.DataFrame(raw_data_list, columns=columns)
    logger.info(
        "insert_manual_form_raw_data get_data input | raw_data_list=%s | df_rows=%s",
        len(raw_data_list),
        len(df),
    )
    if df.empty:
        logger.warning("insert_manual_form_raw_data get_data received empty dataframe.")
        return []

    # Input positions distinguish even repeated station/variable/timestamp rows.
    # Attach before sorting. insert_columns excludes this transient column.
    df["source_code"] = df.index.map((source_codes or {}).get)

    # Some decoders may pass station_id / variable_id as strings.
    # We normalize them once here so all later comparisons are int-to-int.
    df["station_id"] = pd.to_numeric(df["station_id"]).astype(int)
    df["variable_id"] = pd.to_numeric(df["variable_id"]).astype(int)
    df["seconds"] = pd.to_numeric(df["seconds"]).astype(int)

    # Add insertion timestamps; QC month is calculated after loading station offsets.
    df["created_at"] = now
    df["updated_at"] = now
    after_df_setup = time.perf_counter()
    reads = []

    # Timing buckets. These logs help us see exactly where time is being spent.
    total_prev_bulk_lookup = 0
    total_station_offset_lookup = 0
    total_month_calculation = 0
    total_variable_lookup = 0
    total_data_batch = 0
    total_build_context = 0
    total_apply_qc = 0
    total_extend_reads = 0

    # Fetch offsets before grouping so QC months follow each station's local calendar.
    t0 = time.perf_counter()
    station_ids = {int(station_id) for station_id in df["station_id"].unique()}
    station_offsets = dict(
        Station.objects.filter(id__in=station_ids).values_list(
            "id", "utc_offset_minutes"
        )
    )
    total_station_offset_lookup += time.perf_counter() - t0

    missing_station_ids = station_ids - station_offsets.keys()
    if missing_station_ids:
        raise ValueError(
            "Missing station or utc_offset_minutes for station_id values: "
            f"{sorted(missing_station_ids)}"
        )

    logger.info(
        "insert_manual_form_raw_data station offsets | station_ids=%s | offsets_loaded=%s",
        len(station_ids),
        len(station_offsets),
    )

    # Cache each station's timezone rather than reconstructing it for every row.
    station_timezones = {
        station_id: pytz.FixedOffset(offset)
        for station_id, offset in station_offsets.items()
    }

    def get_station_local_month(station_id, observation_dt):
        dt = pd.Timestamp(observation_dt)
        if pd.isna(dt):
            raise ValueError("Observation datetime cannot be null.")

        # Naive decoder dates are already local; aware dates need local conversion.
        if dt.tzinfo is None:
            return dt.month
        return dt.tz_convert(station_timezones[int(station_id)]).month

    t0 = time.perf_counter()
    df["month"] = [
        get_station_local_month(station_id, observation_dt)
        for station_id, observation_dt in zip(df["station_id"], df["datetime"])
    ]
    total_month_calculation += time.perf_counter() - t0

    # Build grouped data once and reuse it.
    #
    # This replaces the older pattern where we created a grouped/drop_duplicates
    # dataframe and then repeatedly filtered the full dataframe for each group.
    grouped_data = list(
        df.groupby(
            ["station_id", "variable_id", "seconds", "month"],
            sort=False,
        )
    )
    logger.info(
        "insert_manual_form_raw_data grouped | grouped_rows=%s",
        len(grouped_data),
    )
    if not grouped_data:
        logger.warning("insert_manual_form_raw_data get_data produced no grouped rows.")
        return []

    # Load all numeric variable IDs in one query.
    # Only numeric variables go through QC.
    t0 = time.perf_counter()
    variable_ids = {
        int(variable_id)
        for (station_id, variable_id, seconds, month), df_group in grouped_data
    }

    # Safety check:
    # Every decoder must produce variable_id values that exist in wx_variable.
    # If a decoder sends a hardcoded/invalid variable_id, fail here with a clear error
    # instead of later failing with a confusing database constraint error.
    existing_variable_ids = set(
        Variable.objects.filter(
            id__in=variable_ids,
        ).values_list("id", flat=True)
    )
    missing_variable_ids = variable_ids - existing_variable_ids
    if missing_variable_ids:
        raise ValueError(
            "insert_manual_form_raw_data received variable_id values that do not exist in wx_variable: "
            f"{sorted(missing_variable_ids)}"
        )
    numeric_variable_ids = set(
        Variable.objects.filter(
            id__in=variable_ids,
            variable_type="Numeric",
        ).values_list("id", flat=True)
    )
    total_variable_lookup += time.perf_counter() - t0
    logger.info(
        "insert_manual_form_raw_data numeric vars | all_variable_ids=%s | numeric_variable_ids=%s",
        len(variable_ids),
        len(numeric_variable_ids),
    )

    # STEP QC needs the previous valid measured value before the first row in each group.
    # Instead of querying raw_data per row/group, we collect all requests and fetch them in bulk.
    t0 = time.perf_counter()
    prev_requests = []
    for (station_id, variable_id, seconds, month), df_group in grouped_data:
        station_id = int(station_id)
        variable_id = int(variable_id)
        seconds = int(seconds)
        month = int(month)
        if variable_id not in numeric_variable_ids:
            continue
        if df_group.empty:
            continue
        # We only need the previous DB value before the earliest record in this batch.
        first_datetime = df_group["datetime"].min()
        group_key = f"{station_id}|{variable_id}|{seconds}|{month}"
        prev_requests.append({
            "key": group_key,
            "station_id": station_id,
            "variable_id": variable_id,
            "before_datetime": first_datetime,
        })
    logger.info(
        "insert_manual_form_raw_data prev_requests | count=%s",
        len(prev_requests),
    )

    # The bulk STEP lookup searches up to 30 days before each group's
    # first observation. A result of (None, None) means no valid measured
    # value was found within that 30-day window. Do not fall back to one
    # database query per observation, because that can become extremely slow
    # when the database is under load. Note the default is 7
    previous_measured_lookup = get_prev_measured_bulk(
        prev_requests,
        lookback_days=30,
    )
    total_prev_bulk_lookup += time.perf_counter() - t0
    logger.info(
        "insert_manual_form_raw_data prev_lookup results | requested=%s | returned=%s",
        len(prev_requests),
        len(previous_measured_lookup),
    )

    # Process each group and build insert-ready rows.
    for (station_id, variable_id, seconds, month), df_group in grouped_data:
        station_id = int(station_id)
        variable_id = int(variable_id)
        seconds = int(seconds)
        month = int(month)
        group_key = f"{station_id}|{variable_id}|{seconds}|{month}"
        previous_db_record = previous_measured_lookup.get(group_key)
        # Important:
        # df_group is already the subset for this station/variable/seconds/month.
        # So we do not need to filter df again.
        df1 = df_group.copy()
        # Sorting is important because STEP and persistence checks depend on time order.
        df1.sort_values(by="datetime", inplace=True)
        count = len(df1)
        if count == 0:
            logger.debug(
                "Skipping station_id=%s, variable_id=%s, seconds=%s, month=%s because found 0 records.",
                station_id,
                variable_id,
                seconds,
                month,
            )
            continue
        logger.debug(
            "Processing station_id=%s, variable_id=%s, seconds=%s, month=%s, records=%s.",
            station_id,
            variable_id,
            seconds,
            month,
            count,
        )
        process_qc = variable_id in numeric_variable_ids
        if process_qc:
            station_offset = station_offsets.get(station_id)
            if station_offset is None:
                raise ValueError(
                    f"Missing utc_offset_minutes for station_id={station_id}"
                )
            # data_batch is the current batch for this specific station/variable/month.
            # It is used by STEP and persistence QC to compare against nearby rows.
            t0 = time.perf_counter()
            data_batch = df1[["datetime", "measured"]].to_dict(orient="records")
            total_data_batch += time.perf_counter() - t0
            # Build reusable QC context once for the whole group.
            t0 = time.perf_counter()
            qc_context = build_qc_context(
                station_id=station_id,
                variable_id=variable_id,
                month=month,
                data_batch=data_batch,
                station_offset=station_offset,
                previous_db_record=previous_db_record,
            )
            total_build_context += time.perf_counter() - t0
            # Apply QC to each row, but reuse the context instead of rebuilding it.
            t0 = time.perf_counter()
            df1[qc_columns] = df1.apply(
                lambda row: evaluate_manual_row(
                    row=row,
                    station_id=station_id,
                    variable_id=variable_id,
                    qc_context=qc_context,
                ),
                axis=1,
                result_type="expand",
            )
            total_apply_qc += time.perf_counter() - t0
            # .replace(...) must be assigned back; otherwise pandas does not update df1.
            df1["qc_step_description"] = df1["qc_step_description"].replace("", None)
            df1["qc_range_description"] = df1["qc_range_description"].replace("", None)
            df1["qc_persist_description"] = df1["qc_persist_description"].replace("", None)
        else:
            # Non-numeric variables keep their code in other decoders, but this insert_raw_data
            # format does not include a code column, so measured is set to MISSING_VALUE.
            for qc_column in qc_columns:
                if qc_column not in df1.columns:
                    df1[qc_column] = None
            df1 = df1.assign(measured=settings.MISSING_VALUE)
        # raw_data.quality_flag is NOT NULL.
        # If QC did not run, or a decoder left the overall quality flag empty,
        # mark the row as "Not checked".
        #
        # QualityFlag:
        # 1 = Not checked
        # 2 = Suspicious
        # 3 = Bad
        # 4 = Good
        df1["quality_flag"] = df1["quality_flag"].fillna(1)
        # Convert the dataframe group into rows matching insert_columns.
        t0 = time.perf_counter()
        prepared = df1[insert_columns].astype(object)
        # Mixed numeric flags and skipped checks can become NaN in pandas.
        # Pass Python None for unset QC fields so psycopg2 writes SQL NULL.
        prepared_rows = prepared.where(prepared.notna(), None).values.tolist()
        reads.extend(prepared_rows)
        total_extend_reads += time.perf_counter() - t0
        logger.debug(
            "insert_manual_form_raw_data prepared group | station_id=%s | variable_id=%s | rows=%s | prepared_rows=%s | process_qc=%s",
            station_id,
            variable_id,
            len(df1),
            len(prepared_rows),
            process_qc,
        )
    end_total = time.perf_counter()
    logger.info(
        "insert_manual_form_raw_data get_data output | reads=%s",
        len(reads),
    )
    logger.info(
        "insert_manual_form_raw_data get_data timing | df_setup: %.2fs | variable_lookup: %.2fs | "
        "station_offset_lookup: %.2fs | month_calc: %.2fs | prev_bulk_lookup: %.2fs | "
        "data_batch: %.2fs | build_context: %.2fs | apply_qc: %.2fs | "
        "extend_reads: %.2fs | total: %.2fs",
        after_df_setup - start_total,
        total_variable_lookup,
        total_station_offset_lookup,
        total_month_calculation,
        total_prev_bulk_lookup,
        total_data_batch,
        total_build_context,
        total_apply_qc,
        total_extend_reads,
        end_total - start_total,
    )
    return reads



def insert(raw_data_list, override_data_on_conflict=False, is_manually_reviewed=False, insert_page_size=100, *, source_codes=None):
    """
    Insert daily manual workbook observations.

    Flow:
    1. Convert decoded tuples into insert-ready rows.
    2. Bulk insert/update raw_data.
    3. Update StationVariable.last_data_*.
    """

    start = time.perf_counter()

    reads = get_data(raw_data_list, source_codes)
    after_get_data = time.perf_counter()

    if not reads:
        logger.warning(
            "insert_manual_form_raw_data produced 0 reads | raw_data_list=%s",
            len(raw_data_list),
        )
        return

    insert_query(
        reads, override_data_on_conflict, is_manually_reviewed,
        page_size=insert_page_size,
    )
    after_insert = time.perf_counter()

    update_stationvariable(reads)
    after_stationvariable = time.perf_counter()

    logger.info(
        "insert_manual_form_raw_data total timing | get_data/QC: %.2fs | insert_query: %.2fs | "
        "update_stationvariable: %.2fs | total: %.2fs",
        after_get_data - start,
        after_insert - after_get_data,
        after_stationvariable - after_insert,
        after_stationvariable - start,
    )