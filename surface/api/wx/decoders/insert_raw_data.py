import datetime
import logging
import time

import pandas as pd
import psycopg2
import pytz
from django.utils import timezone
from psycopg2.extras import execute_values

from tempestas_api import settings
from wx.models import StationVariable, Variable, Station
from wx.quality_control.qc_check import build_qc_context, evaluate_qc_row
from wx.quality_control.helpers import get_prev_measured_bulk

logger = logging.getLogger("surface")


# This list must match the shape/order of the tuples produced by the decoders.
# Example: TOA5 builds tuples like:
# (station_id, variable_id, seconds, datetime, measured, quality_flag, ...)
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
]


# These are the columns that will actually be inserted into raw_data.
# The order here must match the INSERT statement in insert_query().
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
    "updated_at",
    "created_at",
]


# These are the QC result columns returned by evaluate_qc_row().
# evaluate_qc_row() returns values in this exact order.
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

def get_data(raw_data_list):
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
        "insert_raw_data get_data input | raw_data_list=%s | df_rows=%s",
        len(raw_data_list),
        len(df),
    )

    if df.empty:
        logger.warning("insert_raw_data get_data received empty dataframe.")
        return []

    # Some decoders may pass station_id / variable_id as strings.
    # We normalize them once here so all later comparisons are int-to-int.
    df["station_id"] = pd.to_numeric(df["station_id"]).astype(int)
    df["variable_id"] = pd.to_numeric(df["variable_id"]).astype(int)
    df["seconds"] = pd.to_numeric(df["seconds"]).astype(int)

    # created_at and updated_at are added before converting to insert rows.
    # month is used for seasonal/monthly QC thresholds.
    df["created_at"] = now
    df["updated_at"] = now
    df["month"] = pd.to_datetime(df["datetime"]).dt.month.astype(int)

    after_df_setup = time.perf_counter()

    reads = []

    # Timing buckets. These logs help us see exactly where time is being spent.
    total_prev_bulk_lookup = 0
    total_station_offset_lookup = 0
    total_variable_lookup = 0
    total_data_batch = 0
    total_build_context = 0
    total_apply_qc = 0
    total_extend_reads = 0

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
        "insert_raw_data grouped | grouped_rows=%s",
        len(grouped_data),
    )

    if not grouped_data:
        logger.warning("insert_raw_data get_data produced no grouped rows.")
        return []

    # Load all numeric variable IDs in one query.
    # Only numeric variables go through QC.
    t0 = time.perf_counter()

    variable_ids = {
        int(variable_id)
        for (station_id, variable_id, seconds, month), df_group in grouped_data
    }

    numeric_variable_ids = set(
        Variable.objects.filter(
            id__in=variable_ids,
            variable_type="Numeric",
        ).values_list("id", flat=True)
    )

    total_variable_lookup += time.perf_counter() - t0

    logger.info(
        "insert_raw_data numeric vars | all_variable_ids=%s | numeric_variable_ids=%s",
        len(variable_ids),
        len(numeric_variable_ids),
    )

    # Load station UTC offsets in one query.
    t0 = time.perf_counter()

    station_ids = {
        int(station_id)
        for (station_id, variable_id, seconds, month), df_group in grouped_data
    }

    station_offsets = dict(
        Station.objects.filter(
            id__in=station_ids,
        ).values_list("id", "utc_offset_minutes")
    )

    total_station_offset_lookup += time.perf_counter() - t0

    logger.info(
        "insert_raw_data station offsets | station_ids=%s | offsets_loaded=%s",
        len(station_ids),
        len(station_offsets),
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
        "insert_raw_data prev_requests | count=%s",
        len(prev_requests),
    )

    previous_measured_lookup = get_prev_measured_bulk(
        prev_requests,
        lookback_days=30,
    )

    total_prev_bulk_lookup += time.perf_counter() - t0

    logger.info(
        "insert_raw_data prev_lookup results | requested=%s | returned=%s",
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

        # Convert the dataframe group into rows matching insert_columns.
        t0 = time.perf_counter()

        prepared_rows = df1[insert_columns].values.tolist()
        reads.extend(prepared_rows)

        total_extend_reads += time.perf_counter() - t0

        logger.debug(
            "insert_raw_data prepared group | station_id=%s | variable_id=%s | rows=%s | prepared_rows=%s | process_qc=%s",
            station_id,
            variable_id,
            len(df1),
            len(prepared_rows),
            process_qc,
        )

    end_total = time.perf_counter()

    logger.info(
        "insert_raw_data get_data output | reads=%s",
        len(reads),
    )

    logger.info(
        "insert_raw_data get_data timing | df_setup: %.2fs | variable_lookup: %.2fs | "
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


def insert_query(reads, override_data_on_conflict, is_manually_validated):
    """
    Bulk insert prepared rows into raw_data.

    This is already efficient because it uses psycopg2 execute_values().
    The expensive part was previously QC preparation, not this insert.
    """

    start = time.perf_counter()

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:

            logger.info(f"Inserting into database #{len(reads)} records.")

            if override_data_on_conflict:

                if is_manually_validated:
                    # Manual validation locks in manual_flag = 4 when overwriting conflicts.
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
                            manual_flag = 4,
                            consisted = null,
                            updated_at = now()
                    """
                else:
                    # Normal overwrite resets manual/consistency flags.
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
                    updated_at,
                    created_at
                )
                VALUES %s
                {on_conflict_sql}
                RETURNING station_id, date_trunc('hour', datetime), now(), now(), is_daily
            """, reads, fetch=True)

            if inserted_raw_data:
                distinct_raw_data = set(inserted_raw_data)

                # Hourly summary task only needs station + hour.
                filtered_raw_data = set(
                    map(
                        lambda raw_data: (
                            raw_data[0],
                            raw_data[1],
                            raw_data[2],
                            raw_data[3],
                        ),
                        distinct_raw_data,
                    )
                )

                if filtered_raw_data:
                    execute_values(cursor, """
                        INSERT INTO wx_hourlysummarytask (
                            station_id,
                            datetime,
                            updated_at,
                            created_at
                        )
                        VALUES %s
                        ON CONFLICT DO NOTHING
                    """, filtered_raw_data)

                    # Daily summary dates must be based on station local time.
                    station_id = reads[0][0]
                    station_fixed_offset = pytz.FixedOffset(
                        Station.objects.get(pk=station_id).utc_offset_minutes
                    )

                    filtered_raw_data = map(
                        lambda raw_data: (
                            raw_data[0],
                            raw_data[1].astimezone(station_fixed_offset).date(),
                            raw_data[2],
                            raw_data[3],
                        ),
                        filtered_raw_data,
                    )

                    filtered_raw_data = set(filtered_raw_data)

                    execute_values(cursor, """
                        INSERT INTO wx_dailysummarytask (
                            station_id,
                            date,
                            updated_at,
                            created_at
                        )
                        VALUES %s
                        ON CONFLICT DO NOTHING
                    """, filtered_raw_data)

        conn.commit()

    logger.info(
        "insert_raw_data insert_query timing | records=%s | total=%.2fs",
        len(reads),
        time.perf_counter() - start,
    )


def update_stationvariable(reads):
    """
    Update StationVariable.last_data_* with the latest value in this batch.

    Optimized version:
    - Reduces reads to one latest observation per station/variable.
    - Fetches existing StationVariable rows in bulk.
    - Creates missing StationVariable rows in bulk.
    - Updates changed StationVariable rows in bulk.

    This avoids doing get_or_create() and save() once per variable.
    """

    start = time.perf_counter()

    # First reduce the batch to one latest observation per station/variable.
    update_station_variable = {}

    for read in reads:
        station_id = read[0]
        variable_id = read[1]
        observation_datetime = read[2]
        observation_value = read[3]

        key = (station_id, variable_id)

        if key not in update_station_variable:
            update_station_variable[key] = {
                "station_id": station_id,
                "variable_id": variable_id,
                "datetime": observation_datetime,
                "value": observation_value,
            }
        else:
            previous = update_station_variable[key]

            if previous["datetime"] < observation_datetime:
                update_station_variable[key] = {
                    "station_id": station_id,
                    "variable_id": variable_id,
                    "datetime": observation_datetime,
                    "value": observation_value,
                }

    if not update_station_variable:
        logger.info(
            "insert_raw_data update_stationvariable timing | station_variables=0 | total=%.2fs",
            time.perf_counter() - start,
        )
        return

    keys = list(update_station_variable.keys())

    station_ids = {station_id for station_id, variable_id in keys}
    variable_ids = {variable_id for station_id, variable_id in keys}

    # Fetch existing StationVariable rows in one query.
    existing_station_variables = StationVariable.objects.filter(
        station_id__in=station_ids,
        variable_id__in=variable_ids,
    )

    station_variable_by_key = {
        (sv.station_id, sv.variable_id): sv
        for sv in existing_station_variables
    }

    station_variables_to_create = []

    # Prepare missing StationVariable rows.
    for key, latest in update_station_variable.items():
        if key not in station_variable_by_key:
            station_variables_to_create.append(
                StationVariable(
                    station_id=latest["station_id"],
                    variable_id=latest["variable_id"],
                    last_data_datetime=latest["datetime"],
                    last_data_value=latest["value"],
                    last_data_code=None,
                )
            )

    if station_variables_to_create:
        StationVariable.objects.bulk_create(
            station_variables_to_create,
            ignore_conflicts=True,
        )

        # Re-fetch after bulk_create because ignore_conflicts=True does not populate
        # IDs reliably across databases, and another worker may have created the same
        # row at the same time.
        existing_station_variables = StationVariable.objects.filter(
            station_id__in=station_ids,
            variable_id__in=variable_ids,
        )

        station_variable_by_key = {
            (sv.station_id, sv.variable_id): sv
            for sv in existing_station_variables
        }

    station_variables_to_update = []

    # Prepare updates for existing rows.
    for key, latest in update_station_variable.items():
        station_variable = station_variable_by_key.get(key)

        if station_variable is None:
            continue

        if (
            station_variable.last_data_datetime is None
            or latest["datetime"] >= station_variable.last_data_datetime
        ):
            station_variable.last_data_datetime = latest["datetime"]
            station_variable.last_data_value = latest["value"]
            station_variable.last_data_code = None

            station_variables_to_update.append(station_variable)

    if station_variables_to_update:
        StationVariable.objects.bulk_update(
            station_variables_to_update,
            [
                "last_data_datetime",
                "last_data_value",
                "last_data_code",
            ],
        )

    logger.info(
        "insert_raw_data update_stationvariable timing | station_variables=%s | created=%s | updated=%s | total=%.2fs",
        len(update_station_variable),
        len(station_variables_to_create),
        len(station_variables_to_update),
        time.perf_counter() - start,
    )


############################# Main #############################

def insert(raw_data_list, override_data_on_conflict=False, is_manually_validated=False):
    """
    Main entrypoint used by decoders such as TOA5.

    Flow:
    1. Convert decoded tuples into insert-ready rows.
    2. Bulk insert/update raw_data.
    3. Update StationVariable.last_data_*.
    """

    start = time.perf_counter()

    reads = get_data(raw_data_list)
    after_get_data = time.perf_counter()

    if not reads:
        logger.warning(
            "insert_raw_data produced 0 reads | raw_data_list=%s",
            len(raw_data_list),
        )
        return

    insert_query(reads, override_data_on_conflict, is_manually_validated)
    after_insert = time.perf_counter()

    update_stationvariable(reads)
    after_stationvariable = time.perf_counter()

    logger.info(
        "insert_raw_data total timing | get_data/QC: %.2fs | insert_query: %.2fs | "
        "update_stationvariable: %.2fs | total: %.2fs",
        after_get_data - start,
        after_insert - after_get_data,
        after_stationvariable - after_insert,
        after_stationvariable - start,
    )