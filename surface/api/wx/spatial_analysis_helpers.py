"""Shared validation and database retrieval for SURFACE Spatial Analysis.

Authoritative raw-data precedence:
    is_validated IS TRUE  -> consisted / validated_flag
    otherwise             -> measured / quality_flag
manual_flag is deliberately not used.
"""

import datetime as dt
import math

from django.conf import settings
from django.db import connection


SOURCE_TABLES = {
    "raw_data": ("raw_data", "datetime"),
    "hourly": ("hourly_summary", "datetime"),
    "daily": ("daily_summary", "day"),
    "monthly": ("monthly_summary", "date"),
    "yearly": ("yearly_summary", "date"),
}
AGGREGATIONS = {"instant", "max", "min", "mean", "median", "sum"}
AGGREGATE_SQL = {
    "max": "MAX(obs.effective_value)",
    "min": "MIN(obs.effective_value)",
    "mean": "AVG(obs.effective_value)",
    "median": "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY obs.effective_value)",
    "sum": "SUM(obs.effective_value)",
}
NO_DATA_IMAGE_URL = "/static/images/no-interpolated-data.png"


def finite_float(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("{} must be a number.".format(label))
    if not math.isfinite(result):
        raise ValueError("{} must be a finite number.".format(label))
    return result


def positive_int(value, label, maximum=None):
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        raise ValueError("{} must be a whole number.".format(label))
    if result < 0:
        raise ValueError("{} must be a none negative integer.".format(label))
    if maximum is not None and result > maximum:
        raise ValueError("{} must not exceed {}.".format(label, maximum))
    return result


def quality_flag_ids(value):
    """Empty selection means all flags; non-empty IDs are safely SQL-bound."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        raw_ids = list(value)
    elif isinstance(value, str):
        raw_ids = value.split(",")
    else:
        raise ValueError("quality_flags must contain comma-separated integer IDs.")
    if len(raw_ids) > 100:
        raise ValueError("Too many quality flags were selected.")
    ids = [positive_int(item.strip() if isinstance(item, str) else item, "quality_flags") for item in raw_ids]
    return sorted(set(ids))


def normalize_period(value, source):
    if not value:
        raise ValueError("Both start_datetime and end_datetime are required.")
    value = str(value).strip()
    if source in ("raw_data", "hourly"):
        try:
            moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Expected a full ISO 8601 date/time including UTC offset.")
        if moment.tzinfo is None:
            raise ValueError("Raw and hourly dates must contain a UTC offset (for example Z).")
        return moment.astimezone(dt.timezone.utc).isoformat()

    # Summary records use calendar dates. Do NOT convert to a different timezone:
    # that can shift a day/month/year across the boundary.
    if len(value) == 7 and source in ("monthly", "yearly"):
        value += "-01"
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("Summary dates must be YYYY-MM-DD (or YYYY-MM for monthly/yearly).")


def parse_analysis_request(query):
    source = query.get("source", "raw_data")
    agg = query.get("agg", "instant")
    if source not in SOURCE_TABLES:
        raise ValueError("Unsupported data source.")
    if agg not in AGGREGATIONS:
        raise ValueError("Unsupported aggregation method.")

    variable_id = positive_int(query.get("variable_id"), "variable_id")
    start = normalize_period(query.get("start_datetime"), source)
    end = normalize_period(query.get("end_datetime") or query.get("start_datetime"), source)

    # ISO date and UTC timestamp strings are chronological after normalization.
    if end < start:
        raise ValueError("end_datetime cannot be before start_datetime.")
    if source in ("raw_data", "hourly"):
        start_dt = dt.datetime.fromisoformat(start)
        end_dt = dt.datetime.fromisoformat(end)
    else:
        start_dt = dt.date.fromisoformat(start)
        end_dt = dt.date.fromisoformat(end)

    default_limits = {
        "raw_data": 7,
        "hourly": 31,
        "daily": 366,
        "monthly": 365 * 50,
        "yearly": 365 * 100,
    }
    maximum_days = getattr(settings, "SPATIAL_ANALYSIS_MAX_{}_DAYS".format(source.upper()),
                           default_limits[source])
    if end_dt - start_dt > dt.timedelta(days=maximum_days):
        raise ValueError("The {} source is limited to {} days per request.".format(source, maximum_days))

    ids = quality_flag_ids(query.get("quality_flags"))
    return {
        "start_datetime": start,
        "end_datetime": end,
        "variable_id": variable_id,
        "agg": agg,
        "source": source,
        "quality_flags": ",".join(map(str, ids)) if ids else None,
    }


def configured_bounds():
    south = finite_float(settings.SPATIAL_ANALYSIS_INITIAL_LATITUDE, "south bound")
    west = finite_float(settings.SPATIAL_ANALYSIS_INITIAL_LONGITUDE, "west bound")
    north = finite_float(settings.SPATIAL_ANALYSIS_FINAL_LATITUDE, "north bound")
    east = finite_float(settings.SPATIAL_ANALYSIS_FINAL_LONGITUDE, "east bound")
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("Configured spatial-analysis bounds must be ordered south/north and west/east.")
    return {"south": south, "north": north, "west": west, "east": east}


def validate_image_parameters(params, bounds=None):
    bounds = bounds or configured_bounds()
    hres = finite_float(params.get("hres", 0.01), "Horizontal resolution")
    radius = finite_float(params.get("search_radius", 0.7), "Search radius")
    minimum_neighbors = positive_int(params.get("minimum_neighbors", 1),
                                     "Minimum neighbors", maximum=1000)
    vmin = finite_float(params.get("vmin", 0), "Scale minimum")
    vmax = finite_float(params.get("vmax", 30), "Scale maximum")
    cmap = params.get("cmap", "Spectral_r")
    if isinstance(cmap, dict):
        cmap = cmap.get("value")
    if not isinstance(cmap, str) or not cmap:
        raise ValueError("Select a valid color map.")
    # Keep compatibility with the Matplotlib version installed in SURFACE.
    from matplotlib import cm
    try:
        cm.get_cmap(cmap)
    except (ValueError, TypeError):
        raise ValueError("Unsupported color map.")
    if hres <= 0 or radius <= 0 or radius > 180:
        raise ValueError("Horizontal resolution and search radius must be positive; radius must be <= 180 degrees.")
    if vmax <= vmin:
        raise ValueError("Scale maximum must be greater than scale minimum.")
    width = int(math.ceil((bounds["east"] - bounds["west"]) / hres)) + 1
    height = int(math.ceil((bounds["north"] - bounds["south"]) / hres)) + 1
    max_cells = int(getattr(settings, "SPATIAL_ANALYSIS_MAX_GRID_CELLS", 750000))
    if width * height > max_cells:
        raise ValueError(
            "Grid resolution is too fine for the configured area ({} x {} cells; limit {})."
            .format(width, height, max_cells)
        )
    return {
        "hres": hres,
        "minimum_neighbors": minimum_neighbors,
        "search_radius": radius,
        "vmin": vmin,
        "vmax": vmax,
        "cmap": cmap,
    }


def fetch_station_observations(*, start_datetime, end_datetime, variable_id,
                               agg="instant", source="raw_data", quality_flags=None):
    """Return one effective numeric value per station for non-instant aggregations.

    PostgreSQL aggregates before returning results; the raw-data table is not
    loaded into Pandas, and data and image tasks call this exact same function.
    """
    if source not in SOURCE_TABLES or agg not in AGGREGATIONS:
        raise ValueError("Unsupported source or aggregation.")
    variable_id = positive_int(variable_id, "variable_id")
    flags = quality_flag_ids(quality_flags)
    table_name, date_column = SOURCE_TABLES[source]  # trusted, constant identifiers

    if source == "raw_data":
        value_expression = (
            "CASE WHEN a.is_validated IS TRUE THEN a.consisted ELSE a.measured END"
        )
        flag_expression = (
            "CASE WHEN a.is_validated IS TRUE THEN a.validated_flag ELSE a.quality_flag END"
        )
    else:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sampling_operation_id FROM wx_variable WHERE id = %s",
                [variable_id],
            )
            result = cursor.fetchone()
        if result is None:
            raise ValueError("Unknown variable_id.")
        operation = result[0]
        column = (
            "sum_value" if operation in (6, 7) else
            "min_value" if operation == 3 else
            "max_value" if operation == 4 else
            "avg_value"
        )
        value_expression = "a." + column
        flag_expression = "NULL"

    params = {
        "variable_id": variable_id,
        "missing_value": finite_float(settings.MISSING_VALUE, "Missing value"),
    }
    if agg == "instant":
        time_filter = "a.{} = %(start_datetime)s".format(date_column)
        params["start_datetime"] = start_datetime
    else:
        time_filter = "a.{} >= %(start_datetime)s AND a.{} <= %(end_datetime)s".format(
            date_column, date_column)
        params.update(start_datetime=start_datetime, end_datetime=end_datetime)

    flag_filter = ""
    if source == "raw_data" and flags:
        flag_filter = "AND obs.effective_flag = ANY(%(selected_flags)s::integer[])"
        params["selected_flags"] = flags

    common_sql = """
        WITH obs AS (
            SELECT a.station_id,
                   {value_expression} AS effective_value,
                   {flag_expression} AS effective_flag
            FROM {table_name} a
            WHERE a.variable_id = %(variable_id)s AND {time_filter}
        )
        SELECT s.id AS station_id, s.name, s.code, s.latitude, s.longitude,
               {output_value} AS measured
        FROM obs
        JOIN wx_station s ON s.id = obs.station_id
        WHERE obs.effective_value IS NOT NULL
          AND obs.effective_value <> %(missing_value)s
          AND s.latitude BETWEEN -90 AND 90
          AND s.longitude BETWEEN -180 AND 180
          {flag_filter}
        {group_by}
        ORDER BY s.name, s.id
    """
    group_by = ""
    output_value = "obs.effective_value"
    if agg != "instant":
        output_value = AGGREGATE_SQL[agg]
        group_by = "GROUP BY s.id, s.name, s.code, s.latitude, s.longitude"

    query = common_sql.format(
        value_expression=value_expression,
        flag_expression=flag_expression,
        table_name=table_name,
        time_filter=time_filter,
        output_value=output_value,
        flag_filter=flag_filter,
        group_by=group_by,
    )
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        results = cursor.fetchall()

    points = []
    for station_id, name, code, lat, lon, measured in results:
        if measured is None:
            continue
        try:
            measured = finite_float(measured, "Measurement")
            lat = finite_float(lat, "Latitude")
            lon = finite_float(lon, "Longitude")
        except ValueError:
            continue
        if measured == float(settings.MISSING_VALUE):
            continue
        points.append({
            "station_id": station_id,
            "name": name,
            "code": code,
            "latitude": lat,
            "longitude": lon,
            "measured": measured,
        })
    return points


def clean_custom_points(data):
    """Validate user-edited interpolating points before sending them to Celery."""
    if not isinstance(data, list):
        raise ValueError("data must be a list of observation points.")
    limit = int(getattr(settings, "SPATIAL_ANALYSIS_MAX_POINTS", 5000))
    if len(data) > limit:
        raise ValueError("Too many observation points (maximum {}).".format(limit))
    cleaned = []
    for i, point in enumerate(data):
        if not isinstance(point, dict):
            raise ValueError("Point {} is not an object.".format(i + 1))
        lat = finite_float(point.get("latitude"), "Point {} latitude".format(i + 1))
        lon = finite_float(point.get("longitude"), "Point {} longitude".format(i + 1))
        value = finite_float(point.get("measured"), "Point {} measurement".format(i + 1))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Point {} has coordinates outside valid ranges.".format(i + 1))
        # A missing sentinel may never influence the grid, even in edited inputs.
        if value == float(settings.MISSING_VALUE):
            continue
        cleaned.append({
            "station_id": point.get("station_id"),
            "latitude": lat,
            "longitude": lon,
            "measured": value,
        })
    return cleaned
