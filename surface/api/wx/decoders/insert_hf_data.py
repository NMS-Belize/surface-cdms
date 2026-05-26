import logging
import time

import pandas as pd
import psycopg2
from django.utils import timezone
from psycopg2.extras import execute_values

from tempestas_api import settings

logger = logging.getLogger("surface")


# This file should stay focused on:
#   1. storing high-frequency measurements
#   2. creating HF summary tasks
#
# StationVariable.last_data_* should NOT be updated here because these
# high-frequency records have not been QC-checked yet. StationVariable should
# be updated later through the normal raw_data insert path after HF summaries
# are calculated and QC is applied.


# The decoder may pass extra values, but this insert only needs these fields.
columns = [
    "station_id",
    "variable_id",
    "seconds",
    "datetime",
    "measured",
]


# These are the columns inserted into wx_highfrequencydata.
# The order must match the INSERT statement in insert_query().
insert_columns = [
    "station_id",
    "variable_id",
    "datetime",
    "measured",
    "updated_at",
    "created_at",
]


##########################  Functions ##########################

def get_data(raw_data_list):
    """
    Convert decoded high-frequency records into insert-ready rows.

    No QC is done here. QC is applied later when HF summaries are inserted
    into the normal raw_data pipeline.
    """

    start_total = time.perf_counter()
    now = timezone.now()

    df = pd.DataFrame(raw_data_list)

    logger.info(
        "insert_hf_data get_data input | raw_data_list=%s | df_rows=%s",
        len(raw_data_list),
        len(df),
    )

    if df.empty:
        logger.warning("insert_hf_data get_data received empty dataframe.")
        return []

    # Some decoders may pass extra columns. Keep only what this insert expects.
    df = df.iloc[:, :len(columns)]
    df.columns = columns

    # Normalize IDs so dataframe filters compare int-to-int.
    # This avoids silent mismatches like "4" != 4.
    df["station_id"] = pd.to_numeric(df["station_id"]).astype(int)
    df["variable_id"] = pd.to_numeric(df["variable_id"]).astype(int)
    df["seconds"] = pd.to_numeric(df["seconds"]).astype(int)

    # Add audit timestamps expected by insert_columns.
    df["created_at"] = now
    df["updated_at"] = now

    after_df_setup = time.perf_counter()

    reads = []

    total_grouping = 0
    total_extend_reads = 0

    # Keep the same grouping behavior as the original implementation.
    # This also ensures each station/variable/interval group is sorted.
    t0 = time.perf_counter()

    grouped = (
        df[["station_id", "variable_id", "seconds"]]
        .drop_duplicates()
        .copy()
    )

    total_grouping += time.perf_counter() - t0

    logger.info(
        "insert_hf_data grouped | grouped_rows=%s",
        len(grouped),
    )

    if grouped.empty:
        logger.warning("insert_hf_data get_data produced no grouped rows.")
        return []

    for _, group in grouped.iterrows():
        station_id = int(group.station_id)
        variable_id = int(group.variable_id)
        seconds = int(group.seconds)

        df1 = df.loc[
            (df.station_id == station_id)
            & (df.variable_id == variable_id)
            & (df.seconds == seconds)
        ].copy()

        # Chronological order is useful for debugging and consistent inserts.
        df1.sort_values(by="datetime", inplace=True)

        count = len(df1)

        if count == 0:
            logger.debug(
                "Skipping station_id=%s, variable_id=%s, seconds=%s because found 0 records.",
                station_id,
                variable_id,
                seconds,
            )
            continue

        logger.debug(
            "Processing station_id=%s, variable_id=%s, seconds=%s, records=%s.",
            station_id,
            variable_id,
            seconds,
            count,
        )

        t0 = time.perf_counter()

        prepared_rows = df1[insert_columns].values.tolist()
        reads.extend(prepared_rows)

        total_extend_reads += time.perf_counter() - t0

        logger.debug(
            "insert_hf_data prepared group | station_id=%s | variable_id=%s | rows=%s | prepared_rows=%s",
            station_id,
            variable_id,
            len(df1),
            len(prepared_rows),
        )

    end_total = time.perf_counter()

    logger.info(
        "insert_hf_data get_data output | reads=%s",
        len(reads),
    )

    logger.info(
        "insert_hf_data get_data timing | df_setup: %.2fs | grouping: %.2fs | "
        "extend_reads: %.2fs | total: %.2fs",
        after_df_setup - start_total,
        total_grouping,
        total_extend_reads,
        end_total - start_total,
    )

    return reads


def insert_query(reads, override_data_on_conflict):
    """
    Bulk insert high-frequency rows into wx_highfrequencydata.
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
                        updated_at = now()
                """
            else:
                on_conflict_sql = " ON CONFLICT DO NOTHING "

            inserted_hf_data = execute_values(cursor, f"""
                INSERT INTO wx_highfrequencydata (
                    station_id,
                    variable_id,
                    datetime,
                    measured,
                    updated_at,
                    created_at
                )
                VALUES %s
                {on_conflict_sql}
                RETURNING station_id, variable_id, datetime, now(), now()
            """, reads, fetch=True)

            if inserted_hf_data:
                # Build one summary task per station/variable.
                # Each task covers the min/max datetime inserted for that pair.
                df = pd.DataFrame(
                    inserted_hf_data,
                    columns=[
                        "station_id",
                        "variable_id",
                        "datetime",
                        "created_at",
                        "updated_at",
                    ],
                )

                filtered_hf_data = []

                for _, group in df[["station_id", "variable_id"]].drop_duplicates().iterrows():
                    station_id = int(group.station_id)
                    variable_id = int(group.variable_id)

                    df1 = df.loc[
                        (df.station_id == station_id)
                        & (df.variable_id == variable_id)
                    ]

                    created_at = df1.created_at.max()
                    updated_at = df1.updated_at.max()

                    filtered_hf_data.append([
                        created_at,
                        updated_at,
                        station_id,
                        variable_id,
                        df1.datetime.min(),
                        df1.datetime.max(),
                    ])

                if filtered_hf_data:
                    execute_values(cursor, """
                        INSERT INTO wx_hfsummarytask (
                            created_at,
                            updated_at,
                            station_id,
                            variable_id,
                            start_datetime,
                            end_datetime
                        )
                        VALUES %s
                        ON CONFLICT DO NOTHING
                    """, filtered_hf_data)

        conn.commit()

    logger.info(
        "insert_hf_data insert_query timing | records=%s | total=%.2fs",
        len(reads),
        time.perf_counter() - start,
    )

############################# Main #############################

def insert(raw_data_list, override_data_on_conflict=False):
    """
        Main entrypoint for high-frequency inserts.

        Flow:
        1. Prepare decoded records.
        2. Bulk insert/update wx_highfrequencydata.
        3. Queue HF summary tasks.

        NOTE:
        StationVariable.last_data_* is intentionally not updated here because
        high-frequency records have not been QC-checked yet.

        StationVariable should be updated later through the normal raw_data
        insert path after calculate_hfdata_summary(...) creates summarized values
        and insert_raw_data.insert(...) applies QC.

        NOTE:
        HighFrequencyData is a staging table for measurements that should not be
        inserted directly into raw_data immediately.
        
        CURRENT IMPLEMENTATION:
        At the moment, the only fully implemented high-frequency processing path is
        Sea Level / wave data. Sea Level HF measurements are stored here first, then
        process_wave_data(...) calculates derived wave/statistical variables and sends
        those results through insert_raw_data.insert(), where QC is applied.
        
        FUTURE USE:
        Other high-frequency variables can be added later by extending
        calculate_hfdata_summary(...). Until then, non-wave variables should not be
        routed through this pipeline unless pass-through/batch handling is explicitly
        implemented.
    """

    start = time.perf_counter()

    reads = get_data(raw_data_list)
    after_get_data = time.perf_counter()

    if not reads:
        logger.warning(
            "insert_hf_data produced 0 reads | raw_data_list=%s",
            len(raw_data_list),
        )
        return

    insert_query(reads, override_data_on_conflict)
    after_insert = time.perf_counter()

    logger.info(
        "insert_hf_data total timing | get_data: %.2fs | "
        "insert_query: %.2fs | total: %.2fs",
        after_get_data - start,
        after_insert - after_get_data,
        after_insert - start,
    )