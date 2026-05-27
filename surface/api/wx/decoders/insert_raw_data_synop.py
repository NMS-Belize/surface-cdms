import datetime
import logging

import numpy as np
import time
import pandas as pd
import psycopg2
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.db import transaction
from psycopg2.extras import execute_values
from tempestas_api import settings
from wx.models import StationVariable, Variable, Station
from wx.quality_control.qc_check import build_qc_context, evaluate_qc_row
from wx.quality_control.helpers import get_prev_measured_bulk

logger = logging.getLogger('surface')

columns = ["station_id", "variable_id", "seconds", "datetime", "measured", "quality_flag", "qc_range_quality_flag",
           "qc_range_description", "qc_step_quality_flag", "qc_step_description", "qc_persist_quality_flag",
           "qc_persist_description", "manual_flag", "consisted", "is_daily", "remarks", "observer", "code"]

insert_columns = ["station_id", "variable_id", "datetime", "measured", "quality_flag", "qc_range_quality_flag",
                  "qc_range_description", "qc_step_quality_flag", "qc_step_description", "qc_persist_quality_flag",
                  "qc_persist_description", "manual_flag", "consisted", "is_daily", "remarks", "observer", "code",
                  "updated_at", "created_at"]

qc_columns = ["qc_step_quality_flag",
              "qc_step_description",
              "qc_range_quality_flag",
              "qc_range_description",
              "qc_persist_quality_flag",
              "qc_persist_description",
              "quality_flag"]         


##########################  Functions  ##########################


def get_data(raw_data_list, utc_offset_minutes):
    start_total = time.perf_counter()

    now = timezone.now()

    df = pd.DataFrame(raw_data_list, columns=columns)

    logger.info(
        "SYNOP get_data input | raw_data_list=%s | df_rows=%s",
        len(raw_data_list),
        len(df),
    )

    if df.empty:
        logger.warning("SYNOP get_data received empty dataframe.")
        return []

    # Important: normalize types so grouped values and df filters match.
    df["station_id"] = pd.to_numeric(df["station_id"]).astype(int)
    df["variable_id"] = pd.to_numeric(df["variable_id"]).astype(int)
    df["seconds"] = pd.to_numeric(df["seconds"]).astype(int)

    df["created_at"] = now
    df["updated_at"] = now
    df["month"] = pd.to_datetime(df["datetime"]).dt.month.astype(int)

    after_df_setup = time.perf_counter()

    reads = []

    total_prev_bulk_lookup = 0
    total_process_qc_check = 0
    total_data_batch = 0
    total_build_context = 0
    total_apply_qc = 0
    total_extend_reads = 0

    grouped = (
        df[["station_id", "variable_id", "seconds", "month"]]
        .drop_duplicates()
        .copy()
    )

    logger.info(
        "SYNOP get_data grouped | grouped_rows=%s",
        len(grouped),
    )

    variable_ids = set(grouped["variable_id"].tolist())

    # Safety check:
    # Every SYNOP row must reference a variable that exists in wx_variable.
    # If not, fail early with a clear decoder/mapping error.
    existing_variable_ids = set(
        Variable.objects.filter(
            id__in=variable_ids,
        ).values_list("id", flat=True)
    )

    missing_variable_ids = variable_ids - existing_variable_ids

    if missing_variable_ids:
        raise ValueError(
            "SYNOP insert received variable_id values that do not exist in wx_variable: "
            f"{sorted(missing_variable_ids)}"
        )

    numeric_variable_ids = set(
        Variable.objects.filter(
            id__in=variable_ids,
            variable_type="Numeric",
        ).values_list("id", flat=True)
    )

    logger.info(
        "SYNOP get_data numeric vars | all_variable_ids=%s | numeric_variable_ids=%s",
        len(variable_ids),
        len(numeric_variable_ids),
    )

    # Build previous-value requests only for numeric variables.
    t0 = time.perf_counter()

    prev_requests = []

    for _, group in grouped.iterrows():
        station_id = int(group.station_id)
        variable_id = int(group.variable_id)
        seconds = int(group.seconds)
        month = int(group.month)

        if variable_id not in numeric_variable_ids:
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
        "SYNOP get_data prev_requests | count=%s",
        len(prev_requests),
    )

    previous_measured_lookup = get_prev_measured_bulk(
        prev_requests,
        lookback_days=30,
    )

    logger.info(
        "SYNOP get_data prev_lookup results | requested=%s | returned=%s",
        len(prev_requests),
        len(previous_measured_lookup),
    )

    total_prev_bulk_lookup += time.perf_counter() - t0

    # Process groups, similar to your original get_data().
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

        df1.sort_values(by="datetime", inplace=True)

        count = len(df1)

        if count == 0:
            logger.warning(
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

        t0 = time.perf_counter()
        process_qc = variable_id in numeric_variable_ids
        total_process_qc_check += time.perf_counter() - t0

        if process_qc:
            t0 = time.perf_counter()
            data_batch = df1[["datetime", "measured"]].to_dict(orient="records")
            total_data_batch += time.perf_counter() - t0

            t0 = time.perf_counter()
            qc_context = build_qc_context(
                station_id=station_id,
                variable_id=variable_id,
                month=month,
                data_batch=data_batch,
                station_offset=utc_offset_minutes,
                previous_db_record=previous_db_record,
            )
            total_build_context += time.perf_counter() - t0

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

            df1["qc_step_description"] = df1["qc_step_description"].replace("", None)
            df1["qc_range_description"] = df1["qc_range_description"].replace("", None)
            df1["qc_persist_description"] = df1["qc_persist_description"].replace("", None)

            df1 = df1.assign(code=None)

        else:
            # Non-numeric variables keep code, but measured becomes missing value.
            for qc_column in qc_columns:
                if qc_column not in df1.columns:
                    df1[qc_column] = None

            df1 = df1.assign(measured=settings.MISSING_VALUE)

        # raw_data.quality_flag is NOT NULL.
        # If QC did not run, or the decoder left the overall quality flag empty,
        # mark the row as "Not checked".
        #
        # QualityFlag:
        # 1 = Not checked
        # 2 = Suspicious
        # 3 = Bad
        # 4 = Good
        df1["quality_flag"] = df1["quality_flag"].fillna(1)

        t0 = time.perf_counter()

        prepared_rows = df1[insert_columns].values.tolist()

        logger.info(
            "SYNOP get_data prepared group | station_id=%s | variable_id=%s | rows=%s | prepared_rows=%s | process_qc=%s",
            station_id,
            variable_id,
            len(df1),
            len(prepared_rows),
            process_qc,
        )

        reads.extend(prepared_rows)

        total_extend_reads += time.perf_counter() - t0

    end_total = time.perf_counter()

    logger.info(
        "SYNOP get_data output | reads=%s",
        len(reads),
    )

    logger.info(
        "SYNOP get_data timing | df_setup: %.2fs | prev_bulk_lookup: %.2fs | "
        "process_qc_check: %.2fs | data_batch: %.2fs | build_context: %.2fs | "
        "apply_qc: %.2fs | extend_reads: %.2fs | total: %.2fs",
        after_df_setup - start_total,
        total_prev_bulk_lookup,
        total_process_qc_check,
        total_data_batch,
        total_build_context,
        total_apply_qc,
        total_extend_reads,
        end_total - start_total,
    )

    return reads


def insert_query(reads, station_id, date, override_data_on_conflict):
    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:

            logger.info(f'Inserting into database #{len(reads)} records.')

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
                        station_id, variable_id, datetime, measured, quality_flag,
                        qc_range_quality_flag, qc_range_description,
                        qc_step_quality_flag, qc_step_description,
                        qc_persist_quality_flag, qc_persist_description,
                        manual_flag, consisted, is_daily, remarks, observer, code, updated_at, created_at)
                VALUES %s
                {on_conflict_sql}
                RETURNING station_id, variable_id, datetime
            """, reads, fetch=True)

            if inserted_raw_data:
                now = datetime.datetime.now()
                filtered_raw_data = set(map(lambda raw_data: (
                    raw_data[0], raw_data[2].replace(minute=0, second=0, microsecond=0), now, now), inserted_raw_data))

                execute_values(cursor, """
                    INSERT INTO wx_hourlysummarytask (station_id, datetime, created_at, updated_at)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                """, filtered_raw_data)

                cursor.execute("""
                    INSERT INTO wx_dailysummarytask (station_id, date, created_at, updated_at)
                    VALUES (%s, %s, now(), now())
                    ON CONFLICT DO NOTHING
                """, [station_id, date])

        conn.commit()


def update_stationvariable(reads):
    """
    Update StationVariable.last_data_* using bulk operations instead of
    get_or_create/save inside a loop.
    """

    # 1) Keep only the latest read for each (station_id, variable_id)
    latest_by_station_variable = {}

    for read in reads:
        station_id = read[0]
        variable_id = read[1]
        observation_datetime = read[2]
        observation_value = read[3]
        observation_code = read[16]

        key = (station_id, variable_id)

        existing = latest_by_station_variable.get(key)

        if existing is None or observation_datetime > existing["datetime"]:
            latest_by_station_variable[key] = {
                "station_id": station_id,
                "variable_id": variable_id,
                "datetime": observation_datetime,
                "value": observation_value,
                "code": observation_code,
            }

    if not latest_by_station_variable:
        return

    station_ids = {item["station_id"] for item in latest_by_station_variable.values()}
    variable_ids = {item["variable_id"] for item in latest_by_station_variable.values()}

    # 2) Fetch all existing StationVariable rows in one query
    existing_station_variables = StationVariable.objects.filter(
        station_id__in=station_ids,
        variable_id__in=variable_ids,
    )

    existing_map = {
        (sv.station_id, sv.variable_id): sv
        for sv in existing_station_variables
    }

    to_create = []
    to_update = []

    # 3) Decide what needs creating/updating in Python
    for key, item in latest_by_station_variable.items():
        station_id = item["station_id"]
        variable_id = item["variable_id"]
        observation_datetime = item["datetime"]
        observation_value = item["value"]
        observation_code = item["code"]

        station_variable = existing_map.get(key)

        if station_variable is None:
            to_create.append(
                StationVariable(
                    station_id=station_id,
                    variable_id=variable_id,
                    last_data_datetime=observation_datetime,
                    last_data_value=observation_value,
                    last_data_code=observation_code,
                )
            )
            continue

        if (
            station_variable.last_data_datetime is None
            or observation_datetime >= station_variable.last_data_datetime
        ):
            station_variable.last_data_datetime = observation_datetime
            station_variable.last_data_value = observation_value
            station_variable.last_data_code = observation_code
            to_update.append(station_variable)

    # 4) Write changes in bulk
    with transaction.atomic():
        if to_create:
            StationVariable.objects.bulk_create(
                to_create,
                ignore_conflicts=True,
            )

        if to_update:
            StationVariable.objects.bulk_update(
                to_update,
                [
                    "last_data_datetime",
                    "last_data_value",
                    "last_data_code",
                ],
            )

    logger.info(
        "SYNOP update_stationvariable | station_variables=%s | created=%s | updated=%s",
        len(latest_by_station_variable),
        len(to_create),
        len(to_update),
    )


############################# Main #############################

def insert(raw_data_list, date, station_id, override_data_on_conflict=False, utc_offset_minutes=None):
    if utc_offset_minutes is None:
        raise ValueError("utc_offset_minutes is required for SYNOP QC processing.")

    start = time.perf_counter()

    reads = get_data(raw_data_list, utc_offset_minutes=utc_offset_minutes)
    after_get_data = time.perf_counter()

    if not reads:
        logger.warning(
            "SYNOP save produced 0 reads | raw_data_list=%s | station_id=%s | date=%s",
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
        "SYNOP save timing | get_data/QC: %.2fs | insert_query: %.2fs | update_stationvariable: %.2fs | total: %.2fs",
        after_get_data - start,
        after_insert - after_get_data,
        after_stationvariable - after_insert,
        after_stationvariable - start,
    )