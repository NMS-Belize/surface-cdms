import datetime
import logging
import time

import numpy as np
import pandas as pd
import psycopg2
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from psycopg2.extras import execute_values
from tempestas_api import settings
from wx.models import StationVariable, Variable, Station
from wx.quality_control.qc_check import build_qc_context, evaluate_qc_row
from wx.quality_control.helpers import get_prev_measured_bulk

logger = logging.getLogger("surface")


# This must match the tuple structure passed into insert_raw_data_daily.insert().
columns = [
    "station_id",
    "variable_id",
    "seconds",
    "datetime",
    "measured",
    "quality_flag",
    "qc_range_quality_flag",
    "qc_range_description",
    "qc_step_quality_flag",
    "qc_step_description",
    "qc_persist_quality_flag",
    "qc_persist_description",
    "manual_flag",
    "consisted",
    "is_daily",
    "remarks",
    "observer",
    "code",
]


# These are the values that get inserted into raw_data.
# The order must match the INSERT statement in insert_query().
insert_columns = [
    "station_id",
    "variable_id",
    "datetime",
    "measured",
    "quality_flag",
    "qc_range_quality_flag",
    "qc_range_description",
    "qc_step_quality_flag",
    "qc_step_description",
    "qc_persist_quality_flag",
    "qc_persist_description",
    "manual_flag",
    "consisted",
    "is_daily",
    "remarks",
    "observer",
    "code",
    "updated_at",
    "created_at",
]


# evaluate_qc_row() returns QC results in this exact order.
qc_columns = [
    "qc_step_quality_flag",
    "qc_step_description",
    "qc_range_quality_flag",
    "qc_range_description",
    "qc_persist_quality_flag",
    "qc_persist_description",
    "quality_flag",
]


##########################  Functions ##########################

def get_data(raw_data_list, utc_offset_minutes=None):
    """
    Convert decoded daily rows into raw_data insert rows.

    Main optimization:
    - Old version called qc_thresholds(...) inside df.apply(...).
    - That could repeatedly resolve thresholds and repeatedly look up previous values.
    - This version builds reusable QC context once per group.

    A group is:
        station_id + variable_id + seconds + month

    Daily records are usually fewer than high-frequency records, but the same optimization
    helps when many variables or many days are saved at once.
    """

    start_total = time.perf_counter()
    now = timezone.now()

    df = pd.DataFrame(raw_data_list, columns=columns)

    logger.info(
        "insert_raw_data_daily get_data input | raw_data_list=%s | df_rows=%s",
        len(raw_data_list),
        len(df),
    )

    if df.empty:
        logger.warning("insert_raw_data_daily get_data received empty dataframe.")
        return []

    # Normalize IDs so dataframe filtering works consistently.
    # Request/decoder values may arrive as strings.
    df["station_id"] = pd.to_numeric(df["station_id"]).astype(int)
    df["variable_id"] = pd.to_numeric(df["variable_id"]).astype(int)
    df["seconds"] = pd.to_numeric(df["seconds"]).astype(int)

    # Add audit timestamps and month for monthly/seasonal thresholds.
    df["created_at"] = now
    df["updated_at"] = now
    df["month"] = pd.to_datetime(df["datetime"]).dt.month.astype(int)

    after_df_setup = time.perf_counter()

    reads = []

    total_variable_lookup = 0
    total_station_offset_lookup = 0
    total_prev_bulk_lookup = 0
    total_data_batch = 0
    total_build_context = 0
    total_apply_qc = 0
    total_extend_reads = 0

    # Group first so each group can reuse one QC context.
    grouped = (
        df[["station_id", "variable_id", "seconds", "month"]]
        .drop_duplicates()
        .copy()
    )

    logger.info(
        "insert_raw_data_daily grouped | grouped_rows=%s",
        len(grouped),
    )

    if grouped.empty:
        logger.warning("insert_raw_data_daily get_data produced no grouped rows.")
        return []

    # Daily QC originally processed every variable except Code variables.
    # Keep that same behavior.
    t0 = time.perf_counter()

    variable_ids = set(grouped["variable_id"].tolist())

    qc_variable_ids = set(
        Variable.objects.filter(
            id__in=variable_ids,
        )
        .exclude(variable_type="Code")
        .values_list("id", flat=True)
    )

    total_variable_lookup += time.perf_counter() - t0

    logger.info(
        "insert_raw_data_daily QC vars | all_variable_ids=%s | qc_variable_ids=%s",
        len(variable_ids),
        len(qc_variable_ids),
    )

    # Load station offsets once.
    # If utc_offset_minutes was passed and this batch is for one station, use it directly.
    t0 = time.perf_counter()

    station_ids = set(grouped["station_id"].tolist())

    if utc_offset_minutes is not None and len(station_ids) == 1:
        only_station_id = next(iter(station_ids))
        station_offsets = {
            only_station_id: utc_offset_minutes,
        }
    else:
        station_offsets = dict(
            Station.objects.filter(
                id__in=station_ids,
            ).values_list("id", "utc_offset_minutes")
        )

    total_station_offset_lookup += time.perf_counter() - t0

    logger.info(
        "insert_raw_data_daily station offsets | station_ids=%s | offsets_loaded=%s",
        len(station_ids),
        len(station_offsets),
    )

    # STEP QC needs the previous valid measured value before the first row in a group.
    # Fetch those previous values in one bulk query instead of querying per row.
    t0 = time.perf_counter()

    prev_requests = []

    for _, group in grouped.iterrows():
        station_id = int(group.station_id)
        variable_id = int(group.variable_id)
        seconds = int(group.seconds)
        month = int(group.month)

        if variable_id not in qc_variable_ids:
            continue

        df_group = df.loc[
            (df.station_id == station_id)
            & (df.variable_id == variable_id)
            & (df.seconds == seconds)
            & (df.month == month)
        ]

        if df_group.empty:
            continue

        first_datetime = df_group["datetime"].min()
        group_key = f"{station_id}|{variable_id}|{seconds}|{month}"

        prev_requests.append({
            "key": group_key,
            "station_id": station_id,
            "variable_id": variable_id,
            "before_datetime": first_datetime,
        })

    logger.info(
        "insert_raw_data_daily prev_requests | count=%s",
        len(prev_requests),
    )

    # Daily values may have longer gaps than hourly values.
    # 30 days is a safer default than 7 for daily data.
    # If you want stricter STEP QC, reduce this to 7.
    previous_measured_lookup = get_prev_measured_bulk(
        prev_requests,
        lookback_days=30,
    )

    total_prev_bulk_lookup += time.perf_counter() - t0

    logger.info(
        "insert_raw_data_daily prev_lookup results | requested=%s | returned=%s",
        len(prev_requests),
        len(previous_measured_lookup),
    )

    # Process each group into insert-ready rows.
    for _, group in grouped.iterrows():
        station_id = int(group.station_id)
        variable_id = int(group.variable_id)
        seconds = int(group.seconds)
        month = int(group.month)

        group_key = f"{station_id}|{variable_id}|{seconds}|{month}"
        previous_db_record = previous_measured_lookup.get(group_key)

        df1 = df.loc[
            (df.station_id == station_id)
            & (df.variable_id == variable_id)
            & (df.seconds == seconds)
            & (df.month == month)
        ].copy()

        # QC checks depend on chronological order.
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

        process_qc = variable_id in qc_variable_ids

        if process_qc:
            station_offset = station_offsets.get(station_id)

            if station_offset is None:
                raise ValueError(
                    f"Missing utc_offset_minutes for station_id={station_id}"
                )

            # Current batch for this variable group.
            t0 = time.perf_counter()

            data_batch = df1[["datetime", "measured"]].to_dict(orient="records")

            total_data_batch += time.perf_counter() - t0

            # Build reusable QC context once for this group.
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

            # Apply QC to each row using the prebuilt context.
            t0 = time.perf_counter()

            df1[qc_columns] = df1.apply(
                lambda row: evaluate_qc_row(
                    row=row,
                    station_id=station_id,
                    variable_id=variable_id,
                    qc_context=qc_context,
                ),
                axis=1,
                result_type="expand",
            )

            total_apply_qc += time.perf_counter() - t0

            # .replace(...) needs assignment to actually update the dataframe.
            df1["qc_step_description"] = df1["qc_step_description"].replace("", None)
            df1["qc_range_description"] = df1["qc_range_description"].replace("", None)
            df1["qc_persist_description"] = df1["qc_persist_description"].replace("", None)

            # Numeric variables store measured values.
            # Code is cleared because this branch is not for Code variables.
            df1 = df1.assign(code=None)

        else:
            # Original behavior: Code variables do not run QC and measured is missing.
            # The original code preserved the code column while replacing measured.
            for qc_column in qc_columns:
                if qc_column not in df1.columns:
                    df1[qc_column] = None

            df1 = df1.assign(measured=settings.MISSING_VALUE)

        # Convert the processed dataframe group into insert-ready rows.
        # This must remain outside the process_qc block.
        t0 = time.perf_counter()

        prepared_rows = df1[insert_columns].values.tolist()
        reads.extend(prepared_rows)

        total_extend_reads += time.perf_counter() - t0

        logger.debug(
            "insert_raw_data_daily prepared group | station_id=%s | variable_id=%s | rows=%s | prepared_rows=%s | process_qc=%s",
            station_id,
            variable_id,
            len(df1),
            len(prepared_rows),
            process_qc,
        )

    end_total = time.perf_counter()

    logger.info(
        "insert_raw_data_daily get_data output | reads=%s",
        len(reads),
    )

    logger.info(
        "insert_raw_data_daily get_data timing | df_setup: %.2fs | variable_lookup: %.2fs | "
        "station_offset_lookup: %.2fs | prev_bulk_lookup: %.2fs | data_batch: %.2fs | "
        "build_context: %.2fs | apply_qc: %.2fs | extend_reads: %.2fs | total: %.2fs",
        after_df_setup - start_total,
        total_variable_lookup,
        total_station_offset_lookup,
        total_prev_bulk_lookup,
        total_data_batch,
        total_build_context,
        total_apply_qc,
        total_extend_reads,
        end_total - start_total,
    )

    return reads


def insert_query(reads, station_id, date, override_data_on_conflict):
    """
    Bulk insert/update daily raw_data rows.

    This function was already using execute_values(), which is good.
    Most of the performance work is in get_data/QC preparation.
    """

    start = time.perf_counter()

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:

            logger.info(f"Inserting into database #{len(reads)} records.")

            if override_data_on_conflict:
                on_conflict_sql = """
                    ON CONFLICT (station_id, variable_id, datetime)
                    DO UPDATE SET
                        datetime = excluded.datetime,
                        measured = excluded.measured,
                        quality_flag = excluded.quality_flag,
                        qc_range_quality_flag = excluded.qc_range_quality_flag,
                        qc_range_description = excluded.qc_range_description,
                        qc_step_quality_flag = excluded.qc_step_quality_flag,
                        qc_step_description = excluded.qc_step_description,
                        qc_persist_quality_flag = excluded.qc_persist_quality_flag,
                        qc_persist_description = excluded.qc_persist_description,
                        manual_flag = null,
                        consisted = null,
                        remarks = excluded.remarks,
                        observer = excluded.observer,
                        code = excluded.code,
                        updated_at = now()
                """
            else:
                on_conflict_sql = " ON CONFLICT DO NOTHING "

            inserted_raw_data = execute_values(cursor, f"""
                INSERT INTO raw_data (
                    station_id,
                    variable_id,
                    datetime,
                    measured,
                    quality_flag,
                    qc_range_quality_flag,
                    qc_range_description,
                    qc_step_quality_flag,
                    qc_step_description,
                    qc_persist_quality_flag,
                    qc_persist_description,
                    manual_flag,
                    consisted,
                    is_daily,
                    remarks,
                    observer,
                    code,
                    updated_at,
                    created_at
                )
                VALUES %s
                {on_conflict_sql}
                RETURNING station_id, variable_id, datetime
            """, reads, fetch=True)

            if inserted_raw_data:
                now = datetime.datetime.now()

                # One daily summary task per station/day that was inserted or updated.
                daily_summary_tasks = set(
                    map(
                        lambda raw_data: (
                            raw_data[0],
                            raw_data[2].date(),
                            now,
                            now,
                        ),
                        inserted_raw_data,
                    )
                )

                execute_values(cursor, """
                    INSERT INTO wx_dailysummarytask (
                        station_id,
                        date,
                        created_at,
                        updated_at
                    )
                    VALUES %s
                    ON CONFLICT DO NOTHING
                """, daily_summary_tasks)

        conn.commit()

    logger.info(
        "insert_raw_data_daily insert_query timing | records=%s | total=%.2fs",
        len(reads),
        time.perf_counter() - start,
    )


def update_stationvariable(reads):
    """
    Update StationVariable.last_data_* values.

    This keeps the original get_or_create/save behavior for now.
    If it becomes slow, we can bulk optimize this later.
    """

    start = time.perf_counter()

    # Reduce the batch to the latest read per station/variable.
    update_station_variable = {}

    for read in reads:
        station_id = read[0]
        variable_id = read[1]
        observation_datetime = read[2]
        observation_value = read[3]
        observation_code = read[16]

        key = (station_id, variable_id)

        if key not in update_station_variable:
            update_station_variable[key] = [
                station_id,
                variable_id,
                observation_datetime,
                observation_value,
                observation_code,
            ]
        else:
            [
                prev_station_id,
                prev_var_id,
                prev_datetime,
                prev_value,
                prev_code,
            ] = update_station_variable[key]

            if prev_datetime < observation_datetime:
                update_station_variable[key] = [
                    station_id,
                    variable_id,
                    observation_datetime,
                    observation_value,
                    observation_code,
                ]

    for read in update_station_variable.values():
        station_id = read[0]
        variable_id = read[1]
        observation_datetime = read[2]
        observation_value = read[3]
        observation_code = read[4]

        station_variable, created = StationVariable.objects.get_or_create(
            station_id=station_id,
            variable_id=variable_id,
        )

        if (
            station_variable.last_data_datetime is None
            or observation_datetime >= station_variable.last_data_datetime
        ):
            station_variable.last_data_datetime = observation_datetime
            station_variable.last_data_value = observation_value
            station_variable.last_data_code = observation_code
            station_variable.save()

            logger.info(
                f"Updating StationVariable {station_id} {variable_id} "
                f"{observation_datetime} {observation_value}"
            )

    logger.info(
        "insert_raw_data_daily update_stationvariable timing | station_variables=%s | total=%.2fs",
        len(update_station_variable),
        time.perf_counter() - start,
    )


############################# Main #############################

def insert(raw_data_list, date, station_id, override_data_on_conflict=False, utc_offset_minutes=None):
    """
    Main entrypoint for daily raw data inserts.

    Flow:
    1. Prepare rows and run QC.
    2. Bulk insert/update raw_data.
    3. Queue summary tasks.
    4. Update StationVariable.
    """

    start = time.perf_counter()

    reads = get_data(
        raw_data_list,
        utc_offset_minutes=utc_offset_minutes,
    )
    after_get_data = time.perf_counter()

    if not reads:
        logger.warning(
            "insert_raw_data_daily produced 0 reads | raw_data_list=%s | station_id=%s | date=%s",
            len(raw_data_list),
            station_id,
            date,
        )
        raise ValueError("No records were prepared for insert. Save aborted.")

    insert_query(reads, station_id, date, override_data_on_conflict)
    after_insert = time.perf_counter()

    update_stationvariable(reads)
    after_stationvariable = time.perf_counter()

    logger.info(
        "insert_raw_data_daily total timing | get_data/QC: %.2fs | insert_query: %.2fs | "
        "update_stationvariable: %.2fs | total: %.2fs",
        after_get_data - start,
        after_insert - after_get_data,
        after_stationvariable - after_insert,
        after_stationvariable - start,
    )
