"""
Decoder for WeatherLink-style JSON payloads.

Expected layout
===============
{
    "station_id": 2502,
    "station_id_uuid": "...",
    "sensors": [
        {
            "lsid": 11398,
            "sensor_type": 24,
            "data_structure_type": 2,
            "data": [
                {
                    "ts": 1731991504,
                    "tz_offset": -18000,
                    "temp_out": 71.4,
                    "hum_out": 94,
                    ...
                }
            ]
        }
    ],
    "generated_at": 1731992401
}

Important
=========
This decoder uses wx.models.VariableFormat.lookup_key to map JSON keys to
SURFACE variables.

Example:
    JSON key: temp_out

You need a VariableFormat row where:
    lookup_key = "temp_out"
    variable = the SURFACE Variable this key should insert into
    interval = the interval that should be stored in raw_data.seconds

Any JSON key without a matching VariableFormat.lookup_key is skipped and logged.
"""

import json
import logging
import os
import time
from datetime import datetime

import pytz
from celery import shared_task

from wx.decoders.insert_raw_data import insert
from wx.decoders.insert_hf_data import insert as insert_hf
from wx.decoders.insert_staged_raw_data import insert as insert_staged
from wx.models import VariableFormat, Station
from wx.utils import update_station_variables


logger = logging.getLogger('surface.weatherlink_json')
db_logger = logging.getLogger('db')

FORMAT = "WEATHERLINK_JSON"

# These fields describe the record or contain text/date values.
# They are not direct numeric observations to insert into raw_data.
NON_OBSERVATION_KEYS = {
    "ts",
    "tz_offset",
    "forecast_desc",
    "rain_storm_start_date",
}


class WeatherLinkJSONValidationError(Exception):
    """Raised when the WeatherLink JSON file has an invalid structure."""


def _to_float(value):
    """
    Convert a JSON value to float.

    Returns None for null, blank strings, booleans, and non-numeric values.
    Booleans are skipped because bool is a subclass of int in Python.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_to_datetime(timestamp, tz_offset_seconds=None, utc_offset_minutes=None):
    """
    Convert the WeatherLink epoch timestamp into a timezone-aware datetime.

    The file gives:
        ts: epoch timestamp
        tz_offset: offset in seconds, for example -18000 for UTC-5

    SURFACE station.utc_offset_minutes uses minutes, for example -300.
    """
    if timestamp is None:
        raise WeatherLinkJSONValidationError("Observation is missing required 'ts' field.")

    # Prefer the row-level offset from the file.
    if tz_offset_seconds is not None:
        offset_minutes = int(tz_offset_seconds / 60)

    # Fall back to the decoder/station offset.
    elif utc_offset_minutes is not None:
        offset_minutes = int(utc_offset_minutes)

    else:
        offset_minutes = 0

    datetime_offset = pytz.FixedOffset(offset_minutes)

    # fromtimestamp(..., tz=...) returns the local date/time in that fixed offset.
    return datetime.fromtimestamp(int(timestamp), tz=datetime_offset)


def _get_station_from_payload(payload, filename, station_object=None):
    """
    Resolve the Station.

    Priority:
    1. station_object passed by SURFACE
    2. payload["station_id"] as Station.code
    3. first part of filename before "_" as Station.code
    """
    if station_object is not None:
        return station_object

    station_code = payload.get("station_id")

    if station_code is None:
        station_code = os.path.basename(filename).split("_")[0]

    return Station.objects.get(code=str(station_code))


def _build_lookup_table():
    """
    Build a dictionary from VariableFormat.lookup_key to variable metadata.

    This follows the same pattern as the TOA5 decoder: the file's column/key name
    is matched against VariableFormat.lookup_key.
    """
    lookup_table = {}

    for variable_format in VariableFormat.objects.select_related("variable", "interval").all():
        lookup_key = variable_format.lookup_key

        if lookup_key in lookup_table:
            db_logger.warning(
                f"VariableFormat lookup_key '{lookup_key}' is duplicated. "
                f"Using the latest value seen: {variable_format}"
            )

        lookup_table[lookup_key] = {
            "variable_id": variable_format.variable.id,
            "seconds": variable_format.interval.seconds,
        }

    return lookup_table


def _validate_payload(payload):
    """Basic structure validation before parsing."""
    if not isinstance(payload, dict):
        raise WeatherLinkJSONValidationError("JSON root must be an object.")

    if "sensors" not in payload:
        raise WeatherLinkJSONValidationError("JSON file is missing required 'sensors' list.")

    if not isinstance(payload["sensors"], list):
        raise WeatherLinkJSONValidationError("'sensors' must be a list.")


def parse_observation(observation, station, lookup_table, utc_offset=None, missing_keys=None):
    """
    Parse one observation object into raw_data tuples.

    Returns:
        list of tuples accepted by insert(), insert_hf(), or insert_staged()
    """
    if missing_keys is None:
        missing_keys = set()

    date_info = _timestamp_to_datetime(
        observation.get("ts"),
        tz_offset_seconds=observation.get("tz_offset"),
        utc_offset_minutes=utc_offset,
    )

    line_data = []

    for key, value in observation.items():
        if key in NON_OBSERVATION_KEYS:
            continue

        variable_info = lookup_table.get(key)

        if variable_info is None:
            # Log each unknown key once per file to avoid noisy logs.
            if key not in missing_keys:
                db_logger.warning(
                    f"VariableFormat lookup_key '{key}' not found while parsing "
                    f"WeatherLink JSON for station {station.name}. This key will be skipped."
                )
                missing_keys.add(key)
            continue

        measured = _to_float(value)

        if measured is None:
            continue

        line_data.append((
            station.id,
            variable_info["variable_id"],
            variable_info["seconds"],
            date_info,
            measured,
            1,
            None, None, None, None,
            None, None, None, None,
            False,
        ))

    return line_data


def parse_payload(payload, station, utc_offset=None):
    """
    Parse the full WeatherLink JSON payload into raw_data tuples.

    Also updates StationVariable records for variables found in the file.
    """
    _validate_payload(payload)

    lookup_table = _build_lookup_table()
    reads = []
    in_file_station_variables = set()
    missing_keys = set()

    for sensor in payload.get("sensors", []):
        sensor_data = sensor.get("data", [])

        if not isinstance(sensor_data, list):
            db_logger.warning(
                f"Skipping sensor for station {station.name} because 'data' is not a list."
            )
            continue

        for observation in sensor_data:
            if not isinstance(observation, dict):
                db_logger.warning(
                    f"Skipping observation for station {station.name} because it is not an object."
                )
                continue

            parsed_rows = parse_observation(
                observation=observation,
                station=station,
                lookup_table=lookup_table,
                utc_offset=utc_offset,
                missing_keys=missing_keys,
            )

            for row in parsed_rows:
                reads.append(row)
                in_file_station_variables.add(row[1])

    update_station_variables(station, in_file_station_variables)

    return reads


@shared_task
def read_file(
    filename,
    highfrequency_data=False,
    process_in_chunks=False,
    station_data_file=None,
    station_object=None,
    utc_offset=None,
    override_data_on_conflict=False,
):
    """Read a WeatherLink-style JSON file and insert observations into SURFACE."""
    logger.info(f"processing {filename}")

    start = time.time()
    reads = []

    try:
        with open(filename, "r", encoding="UTF-8") as source:
            payload = json.load(source)

        station = _get_station_from_payload(
            payload=payload,
            filename=filename,
            station_object=station_object,
        )

        # If not explicitly passed, use the station offset.
        # Individual rows may still override this with row["tz_offset"].
        if utc_offset is None:
            utc_offset = station.utc_offset_minutes

        reads = parse_payload(
            payload=payload,
            station=station,
            utc_offset=utc_offset,
        )

    except FileNotFoundError as fnf:
        logger.error(repr(fnf))
        print(f"No such file or directory {filename}.")
        raise
    except Exception as e:
        logger.error(repr(e))
        raise

    try:
        # Insert data based on the type: high frequency, staged, or standard.
        if highfrequency_data:
            insert_hf(reads, override_data_on_conflict)

        elif process_in_chunks:
            insert_staged(
                reads,
                station_data_file,
            )

        else:
            insert(reads, override_data_on_conflict)

    except Exception as e:
        logger.error(repr(e))
        raise

    end = time.time()

    logger.info(
        f"Processing file {filename} in {end - start} seconds, "
        f"returning #reads={len(reads)}."
    )

    return reads