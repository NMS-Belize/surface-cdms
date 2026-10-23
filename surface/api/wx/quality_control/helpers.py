import pytz
import psycopg2

from tempestas_api import settings

from psycopg2.extras import execute_values

from datetime import datetime, timedelta, timezone, date


from contextlib import contextmanager
from contextvars import ContextVar
import logging
import time

_qc_scope = ContextVar("qc_connection_scope", default=None)
_qc_logger = logging.getLogger("surface")


@contextmanager
def reuse_qc_connection():
    """Reuse one lazy QC connection during a synchronous import only."""
    if _qc_scope.get() is not None:
        # Nested scopes borrow the outer scope; only its owner closes it.
        yield
        return

    state = {
        "connection": None,
        "connect_seconds": 0.0,
        "calls": {},
        "seconds": {},
        "evaluation_seconds": {},
    }
    token = _qc_scope.set(state)
    try:
        yield
    finally:
        _qc_scope.reset(token)
        conn = state["connection"]
        try:
            if conn is not None:
                conn.close()
        finally:
            _qc_logger.info(
                "QC database scope | connections=%s | connect=%.3fs | "
                "calls=%s | lookup_seconds=%s",
                int(conn is not None), state["connect_seconds"],
                state["calls"],
                {key: round(value, 3) for key, value in state["seconds"].items()},
            )
            _qc_logger.info(
                "QC evaluation totals | step=%.3fs | range=%.3fs | persist=%.3fs",
                state["evaluation_seconds"].get("step", 0.0),
                state["evaluation_seconds"].get("range", 0.0),
                state["evaluation_seconds"].get("persist", 0.0),
            )


def record_qc_timing(kind, seconds):
    """Accumulate timings without logging once per observation."""
    state = _qc_scope.get()
    if state is not None:
        totals = state["evaluation_seconds"]
        totals[kind] = totals.get(kind, 0.0) + seconds


@contextmanager
def _qc_connection(kind):
    state = _qc_scope.get()
    start = time.perf_counter()
    conn = None
    try:
        if state is None:
            conn = get_connection()
        else:
            state["calls"][kind] = state["calls"].get(kind, 0) + 1
            conn = state["connection"]
            if conn is None:
                connect_start = time.perf_counter()
                conn = get_connection()
                state["connection"] = conn
                state["connect_seconds"] += time.perf_counter() - connect_start

        # Keep each helper's own commit/rollback boundary, as before.
        with conn:
            yield conn
    finally:
        if state is None:
            if conn is not None:
                conn.close()
        else:
            totals = state["seconds"]
            totals[kind] = totals.get(kind, 0.0) + time.perf_counter() - start


def get_connection():
    return psycopg2.connect(settings.SURFACE_CONNECTION_STRING)

# Expanded sentinel check handling float precision, None, and strings
MISSING_SENTINELS = {settings.MISSING_VALUE, -999, -9999, -99.9, -999.0, -9999.0}

# ---------------------------------------------------------------------
# HELPER FXN's
# ---------------------------------------------------------------------
def is_missing(val):
    if val is None or val == "":
        return True
    try:
        # Cast to float to catch precision quirks (e.g., -999.00 vs -999)
        return float(val) in MISSING_SENTINELS
    except (ValueError, TypeError):
        return False

def convert_records_to_utc(records, utc_offset_minutes):
    """
    records: list of dicts with keys:
        - 'datetime'
        - 'measured'

    utc_offset_minutes: integer (e.g. -360 for UTC-6)

    Returns:
        list of dicts with UTC datetimes
    """

    offset = pytz.FixedOffset(utc_offset_minutes)
    converted = []

    for record in records:
        dt = record['datetime']

        # If naive -> localize using provided offset
        if dt.tzinfo is None:
            dt = offset.localize(dt)

        # Convert to UTC if already timezone aware
        utc_dt = dt.astimezone(pytz.UTC)

        converted.append({
            'datetime': utc_dt,
            'measured': record['measured']
        })

    return converted


def get_min_max_measured(window_start, window_end, station_id, variable_id):
    """
    Returns (min_measured, max_measured) from raw_data for a station/variable
    within the given time window.
    """

    sql = '''
        SELECT
            MIN(measured) AS min_measured,
            MAX(measured) AS max_measured
        FROM raw_data
        WHERE datetime >= %s
          AND datetime < %s
          AND station_id = %s
          AND variable_id = %s
          AND measured != -99.9
    '''

    params = (
        window_start,
        window_end,
        station_id,
        variable_id,
    )

    with _qc_connection("min_max") as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone()

    # result is a tuple: (min_measured, max_measured)
    if result is None or result[0] is None:
        return None, None

    return result


def get_prev_measured(datetime, station_id, variable_id):
    """
    Returns prev_measured (the immediate previous measured data) from raw_data for a station/variable
    given a time.
    """

    sql = '''
        SELECT
            datetime,
            measured
        FROM raw_data
        WHERE datetime < %s
          AND station_id = %s
          AND variable_id = %s
          AND measured > -99.9
        order by datetime desc
        LIMIT 1
    '''

    params = (
        datetime,
        station_id,
        variable_id,
    )

    with _qc_connection("previous") as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone()

    # result is a tuple: (datetime, prev_measured)
    if result is None or result[0] is None:
        return None, None

    return result


def get_historical_measured_records(window_start, window_end, station_id, variable_id):
    """
    Returns historical raw_data records for one station/variable in a time range.
    Used by QC so we do not query the DB once per row.
    """

    sql = """
        SELECT datetime, measured
        FROM raw_data
        WHERE datetime >= %s
          AND datetime < %s
          AND station_id = %s
          AND variable_id = %s
          AND measured != -99.9
        ORDER BY datetime
    """

    params = (
        window_start,
        window_end,
        station_id,
        variable_id,
    )

    with _qc_connection("history") as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            results = cur.fetchall()

    return [
        {
            "datetime": row[0],
            "measured": row[1],
        }
        for row in results
    ]


def get_prev_measured_bulk(requests, lookback_days=7):
    """
    Bulk fetch previous measured values for many station/variable/datetime groups.

    The caller may override the lookback window. The default is 7 days,
    while the default manual-data import currently passes 30 days.

    This uses:
      1. A batch-wide fixed datetime range so Timescale can exclude old chunks.
      2. A per-request datetime range so each row still gets the correct previous value.
      3. measured > -99.9 so Postgres can use the partial valid-value index.

    requests should be a list of dicts:
        {
            "key": "4|4062|3600|5",
            "station_id": 4,
            "variable_id": 4062,
            "before_datetime": datetime_obj,
        }

    Return value:
        {
            "4|4062|3600|5": (datetime, measured),
            ...
        }

    A value of (None, None) means no valid measured value was found
    within the requested lookback window.

    Important:
        Callers that provide this result should treat (None, None) as
        an intentional "not found" result. They should not issue one
        fallback query per observation, because that can cause severe
        delays when the database is under load.
    """

    if not requests:
        return {}

    lookback_days = int(lookback_days)

    values = [
        (
            req["key"],
            int(req["station_id"]),
            int(req["variable_id"]),
            req["before_datetime"],
        )
        for req in requests
    ]

    before_datetimes = [req["before_datetime"] for req in requests]

    batch_start = min(before_datetimes) - timedelta(days=lookback_days)
    batch_end = max(before_datetimes)

    with _qc_connection("previous_bulk") as conn:
        with conn.cursor() as cur:
            # Safely quote the datetime constants for the SQL string.
            # execute_values requires the main SQL to contain only one %s placeholder,
            # so we cannot pass batch_start and batch_end as normal %s params here.
            batch_start_sql = cur.mogrify("%s::timestamptz", (batch_start,)).decode("utf-8")
            batch_end_sql = cur.mogrify("%s::timestamptz", (batch_end,)).decode("utf-8")

            sql = f"""
                WITH requests(group_key, station_id, variable_id, before_datetime) AS (
                    VALUES %s
                )
                SELECT
                    r.group_key,
                    prev.datetime,
                    prev.measured
                FROM requests r
                LEFT JOIN LATERAL (
                    SELECT
                        rd.datetime,
                        rd.measured
                    FROM raw_data rd
                    WHERE rd.station_id = r.station_id::integer
                      AND rd.variable_id = r.variable_id::integer

                      -- Batch-wide fixed range.
                      -- This gives Timescale/Postgres a constant datetime window
                      -- so it can avoid considering old chunks.
                      AND rd.datetime >= {batch_start_sql}
                      AND rd.datetime <  {batch_end_sql}

                      -- Per-request range.
                      -- This preserves the original lookup behavior for each row.
                      AND rd.datetime >= r.before_datetime::timestamptz - interval '{lookback_days} days'
                      AND rd.datetime <  r.before_datetime::timestamptz

                      -- Needed to use the existing partial index:
                      -- raw_data_station_variable_datetime_desc_valid_idx
                      AND rd.measured > -99.9

                    ORDER BY rd.datetime DESC
                    LIMIT 1
                ) prev ON TRUE
            """

            # Keep the earlier fix: collect results from every page.
            results = execute_values(
                cur,
                sql,
                values,
                template="(%s, %s, %s, %s)",
                fetch=True,
            )

    return {
        row[0]: (row[1], row[2])
        for row in results
    }