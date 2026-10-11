import psycopg2

from psycopg2.extras import execute_values

from tempestas_api import settings

from .insert_raw_data import get_data, insert_columns


def insert_missing(
    station_id,
    variable_id,
    interval_seconds,
    missing_datetimes,
):
    """
    Run missing observations through QC and insert them
    without generating summaries or updating StationVariable.
    """

    if not missing_datetimes:
        return 0

    raw_data_list = []

    for utc_dt in missing_datetimes:
        raw_data_list.append((
            station_id,
            variable_id,
            interval_seconds,
            utc_dt,
            settings.MISSING_VALUE,
            None, None, None, None, None, None, None,
            5,       # Missing data manual flag
            None,    # Consisted
            False,   # Not daily data
        ))

    # Apply the existing QC pipeline before inserting.
    reads = get_data(raw_data_list)

    if not reads:
        return 0

    columns = ", ".join(insert_columns)

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:

            # Preserve existing observations, including those
            # inserted concurrently by another process.
            inserted = execute_values(
                cursor,
                f"""
                    INSERT INTO raw_data ({columns})
                    VALUES %s
                    ON CONFLICT (station_id, variable_id, datetime)
                    DO NOTHING
                    RETURNING 1
                """,
                reads,
                page_size=1000,
                fetch=True,
            )

    return len(inserted)