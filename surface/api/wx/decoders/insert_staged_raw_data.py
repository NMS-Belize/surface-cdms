import logging
import time

import pandas as pd
import psycopg2
from django.utils import timezone
from psycopg2.extras import execute_values

from tempestas_api import settings

logger = logging.getLogger("surface")


# The decoder sends rows in the same shape expected by insert_raw_data.
#
# For staging, we only need the first five fields:
#   station_id
#   variable_id
#   seconds
#   datetime
#   measured
#
# QC is intentionally NOT done here.
# QC will happen later when staged rows are passed into insert_raw_data.insert(...).
columns = [
    "station_id",
    "variable_id",
    "seconds",
    "datetime",
    "measured",
]


# These are the columns inserted into wx_stagedrawdata.
#
# The order must match the INSERT statement inside insert_query().
insert_columns = [
    "station_data_file_id",
    "station_id",
    "variable_id",
    "seconds",
    "datetime",
    "measured",
    "updated_at",
    "created_at",
]


def get_data(raw_data_list, station_data_file):
    """
    Convert decoded raw-data rows into staged insert rows.

    This function does not run QC and does not prepare rows for raw_data.

    Its only job is to take the decoded rows and prepare them for insertion
    into wx_stagedrawdata.

    Later, process_staged_raw_data_tasks() will read from wx_stagedrawdata,
    rebuild raw_data_list rows, and pass them into insert_raw_data.insert(...)
    so normal QC can run in smaller batches.
    """

    start_total = time.perf_counter()
    now = timezone.now()

    df = pd.DataFrame(raw_data_list)

    logger.info(
        "insert_staged_raw_data get_data input | station_data_file_id=%s | raw_data_list=%s | df_rows=%s",
        station_data_file.id,
        len(raw_data_list),
        len(df),
    )

    if df.empty:
        logger.warning(
            "insert_staged_raw_data get_data received empty dataframe | station_data_file_id=%s",
            station_data_file.id,
        )
        return []

    # Some decoders pass extra columns because they are shaped for insert_raw_data.
    # Staging only needs the first five values.
    df = df.iloc[:, :len(columns)]
    df.columns = columns

    # Normalize IDs so filtering/grouping compares int-to-int.
    df["station_id"] = pd.to_numeric(df["station_id"]).astype(int)
    df["variable_id"] = pd.to_numeric(df["variable_id"]).astype(int)
    df["seconds"] = pd.to_numeric(df["seconds"]).astype(int)

    # Add metadata needed for the staged table.
    df["station_data_file_id"] = station_data_file.id
    df["created_at"] = now
    df["updated_at"] = now

    reads = []

    # Keep the same general grouping style as insert_hf_data.
    #
    # This is not for QC. It is only to keep rows organized and sorted
    # consistently before inserting into the staging table.
    grouped = (
        df[["station_id", "variable_id", "seconds"]]
        .drop_duplicates()
        .copy()
    )

    logger.info(
        "insert_staged_raw_data grouped | station_data_file_id=%s | grouped_rows=%s",
        station_data_file.id,
        len(grouped),
    )

    if grouped.empty:
        logger.warning(
            "insert_staged_raw_data get_data produced no grouped rows | station_data_file_id=%s",
            station_data_file.id,
        )
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

        # Chronological order makes the staging table easier to inspect
        # and makes later processing predictable.
        df1.sort_values(by="datetime", inplace=True)

        count = len(df1)

        if count == 0:
            logger.debug(
                "Skipping staged group because found 0 records | station_data_file_id=%s | station_id=%s | variable_id=%s | seconds=%s",
                station_data_file.id,
                station_id,
                variable_id,
                seconds,
            )
            continue

        prepared_rows = df1[insert_columns].values.tolist()
        reads.extend(prepared_rows)

        logger.debug(
            "insert_staged_raw_data prepared group | station_data_file_id=%s | station_id=%s | variable_id=%s | seconds=%s | rows=%s",
            station_data_file.id,
            station_id,
            variable_id,
            seconds,
            len(prepared_rows),
        )

    logger.info(
        "insert_staged_raw_data get_data output | station_data_file_id=%s | reads=%s | total=%.2fs",
        station_data_file.id,
        len(reads),
        time.perf_counter() - start_total,
    )

    return reads


def insert_query(reads, station_data_file, override_data_on_conflict):
    """
    Bulk insert decoded rows into wx_stagedrawdata.

    This function also creates StagedRawDataTask records, but only for
    Numeric variables.

    Non-numeric variables are staged if they appear in the decoded file,
    but no processing task is created for them. That means they will not be
    passed into insert_raw_data, which avoids the quality_flag NOT NULL issue
    for non-numeric variables.
    """

    start = time.perf_counter()

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:

            logger.info(
                "insert_staged_raw_data inserting staged rows | station_data_file_id=%s | records=%s",
                station_data_file.id,
                len(reads),
            )

            if override_data_on_conflict:
                on_conflict_sql = """
                    ON CONFLICT (station_data_file_id, datetime, station_id, variable_id)
                    DO UPDATE SET
                        seconds = excluded.seconds,
                        measured = excluded.measured,
                        updated_at = now()
                """
            else:
                on_conflict_sql = " ON CONFLICT DO NOTHING "

            inserted_staged_data = execute_values(cursor, f"""
                INSERT INTO wx_stagedrawdata (
                    station_data_file_id,
                    station_id,
                    variable_id,
                    seconds,
                    datetime,
                    measured,
                    updated_at,
                    created_at
                )
                VALUES %s
                {on_conflict_sql}
                RETURNING
                    station_data_file_id,
                    station_id,
                    variable_id,
                    datetime,
                    now(),
                    now()
            """, reads, fetch=True)

            if inserted_staged_data:
                df = pd.DataFrame(
                    inserted_staged_data,
                    columns=[
                        "station_data_file_id",
                        "station_id",
                        "variable_id",
                        "datetime",
                        "created_at",
                        "updated_at",
                    ],
                )

                # Only create staged processing tasks for Numeric variables.
                #
                # insert_raw_data only applies QC to Numeric variables. For
                # non-numeric variables, QC is skipped and quality_flag is kept
                # from the incoming row. Since this staged pipeline intentionally
                # stores only datetime/measured-style data, non-numeric variables
                # are not passed forward to raw_data.
                variable_ids = {
                    int(variable_id)
                    for variable_id in df["variable_id"].dropna().unique()
                }

                if variable_ids:
                    cursor.execute(
                        """
                        SELECT id
                        FROM wx_variable
                        WHERE id = ANY(%s)
                          AND variable_type = 'Numeric'
                        """,
                        (list(variable_ids),),
                    )

                    numeric_variable_ids = {
                        row[0]
                        for row in cursor.fetchall()
                    }
                else:
                    numeric_variable_ids = set()

                logger.info(
                    "insert_staged_raw_data numeric variable filter | station_data_file_id=%s | all_variables=%s | numeric_variables=%s",
                    station_data_file.id,
                    len(variable_ids),
                    len(numeric_variable_ids),
                )

                staged_tasks = []

                for _, group in df[
                    ["station_data_file_id", "station_id", "variable_id"]
                ].drop_duplicates().iterrows():

                    station_data_file_id = int(group.station_data_file_id)
                    station_id = int(group.station_id)
                    variable_id = int(group.variable_id)

                    # Do not create processing tasks for non-numeric variables.
                    if variable_id not in numeric_variable_ids:
                        logger.info(
                            "Skipping StagedRawDataTask creation for non-numeric variable | station_data_file_id=%s | station_id=%s | variable_id=%s",
                            station_data_file_id,
                            station_id,
                            variable_id,
                        )
                        continue

                    df1 = df.loc[
                        (df.station_data_file_id == station_data_file_id)
                        & (df.station_id == station_id)
                        & (df.variable_id == variable_id)
                    ]

                    if df1.empty:
                        continue

                    staged_tasks.append([
                        df1.created_at.max(),
                        df1.updated_at.max(),
                        station_data_file_id,
                        station_id,
                        variable_id,
                        df1.datetime.min(),
                        df1.datetime.max(),
                    ])

                if staged_tasks:
                    execute_values(cursor, """
                        INSERT INTO wx_stagedrawdatatask (
                            created_at,
                            updated_at,
                            station_data_file_id,
                            station_id,
                            variable_id,
                            start_datetime,
                            end_datetime
                        )
                        VALUES %s
                        ON CONFLICT DO NOTHING
                    """, staged_tasks)

                    logger.info(
                        "insert_staged_raw_data created staged tasks | station_data_file_id=%s | tasks=%s",
                        station_data_file.id,
                        len(staged_tasks),
                    )
                else:
                    logger.warning(
                        "insert_staged_raw_data created 0 staged tasks | station_data_file_id=%s | reason=no numeric variables inserted",
                        station_data_file.id,
                    )

        conn.commit()

    logger.info(
        "insert_staged_raw_data insert_query timing | station_data_file_id=%s | records=%s | total=%.2fs",
        station_data_file.id,
        len(reads),
        time.perf_counter() - start,
    )


def insert(raw_data_list, station_data_file, override_data_on_conflict=False):
    """
    Main entrypoint for staged/chunked raw-data inserts.

    Flow:
    1. Receive decoded rows from the decoder.
    2. Store the rows in wx_stagedrawdata without QC.
    3. Create wx_stagedrawdatatask rows only for Numeric variables.
    4. Later, process_staged_raw_data_tasks() passes staged numeric rows into
       insert_raw_data.insert(...), where QC is applied.

    This allows large files to be decoded/staged first, then QC'd in smaller
    batches later.
    """

    start = time.perf_counter()

    reads = get_data(
        raw_data_list=raw_data_list,
        station_data_file=station_data_file,
    )

    after_get_data = time.perf_counter()

    if not reads:
        logger.warning(
            "insert_staged_raw_data produced 0 reads | station_data_file_id=%s | raw_data_list=%s",
            station_data_file.id,
            len(raw_data_list),
        )
        return

    insert_query(
        reads=reads,
        station_data_file=station_data_file,
        override_data_on_conflict=override_data_on_conflict,
    )

    after_insert = time.perf_counter()

    logger.info(
        "insert_staged_raw_data total timing | station_data_file_id=%s | get_data: %.2fs | insert_query: %.2fs | total: %.2fs",
        station_data_file.id,
        after_get_data - start,
        after_insert - after_get_data,
        after_insert - start,
    )