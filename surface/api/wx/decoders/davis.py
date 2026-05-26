import datetime
import logging
import os
import time

import pandas as pd
import pytz
from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist

from tempestas_api import settings
from wx.decoders.insert_raw_data import insert
from wx.decoders.insert_hf_data import insert as insert_hf
from wx.decoders.insert_staged_raw_data import insert as insert_staged
from wx.models import Station

logger = logging.getLogger('surface.davis')
db_logger = logging.getLogger('db')

column_names = [
    'date',
    'time',
    'temp_out', #
    'hi_temp', #
    'low_temp', #
    'out_hum', #
    'dew_pt', #
    'wind_speed', #
    'wind_dir', #
    'wind_run', #
    'hi_speed', #
    'hi_dir',
    'wind_chill', #
    'heat_index', #
    'thw_index',
    'thsw_index',
    'bar', #
    'rain', #
    'rain_rate',
    'solar_rad', #
    'solar_energy',
    'hi_solar_rad', #
    'uv_index',
    'uv_dose',
    'hi_uv',
    'heat_dd',
    'cool_dd',
    'in_temp',
    'in_hum',
    'in_dew',
    'in_heat',
    'in_emc',
    'in_density',
    'et',
    'wind_samp',
    'wind_tx',
    'iss_recept',
    'arc_int',
]

# Compass direction columns — values are strings (ENE, NNW, etc.) that must be
# converted to degrees before ingestion.
COMPASS_COLUMNS = {'wind_dir', 'hi_dir'}

COMPASS_DEGREES = {
    'N':   0.0,   'NNE': 22.5,  'NE':  45.0,  'ENE': 67.5,
    'E':   90.0,  'ESE': 112.5, 'SE':  135.0,  'SSE': 157.5,
    'S':   180.0, 'SSW': 202.5, 'SW':  225.0,  'WSW': 247.5,
    'W':   270.0, 'WNW': 292.5, 'NW':  315.0,  'NNW': 337.5,
}

variable_dict = {
    'temp_out':    12,   # TEMPAVG
    'hi_temp':     16,   # TEMPMAX
    'low_temp':    14,   # TEMPMIN
    'out_hum':     31,   # RHAVG
    'dew_pt':      4064, # TDEWPNTAVG
    'wind_speed':  50,   # WNDSPD
    'wind_dir':    55,   # WNDDIR
    'wind_run':    103,  # WINDRUN
    'hi_speed':    53,   # WNDSPMAX
    'wind_chill':  4065, # WNDCHILLAVG
    'heat_index':  27,   # HEATIDXAVG
    'bar':         4066, # PRESSTNAVG
    'rain':        0,    # PRECIP
    'solar_rad':   73,   # SOLARRADAVG
    'hi_solar_rad': 75,  # SOLRDMAX
}


def station_code_from_filename(filename):
    """Extract station code from filename.
    Expected format: davis_{code}[_date].txt
    e.g. davis_17137013.txt or davis_17137013_2017-09.txt
    """
    basename = os.path.basename(filename)
    code = basename.split('_')[1]

    if '.' in code:
        code = code.split('.')[0]
    return code


def parse_datetime(date_str, time_str, utc_offset):
    """Parse Davis date and time columns into a timezone-aware datetime.

    Date format: MM/DD/YY
    Time format: H:MM a / H:MM p  (12-hour with bare 'a'/'p' suffix)
    """
    time_str = time_str.strip()
    if time_str.endswith(' a'):
        time_str = time_str[:-1] + 'AM'
    elif time_str.endswith(' p'):
        time_str = time_str[:-1] + 'PM'
    datetime_offset = pytz.FixedOffset(utc_offset)
    dt = datetime.datetime.strptime(f'{date_str} {time_str}', '%m/%d/%y %I:%M %p')
    return datetime_offset.localize(dt)


def parse_line(row, station_id, utc_offset):
    """Parse a single data row into a list of raw_data tuples."""
    parsed_date = parse_datetime(str(row['date']), str(row['time']), utc_offset)
    records_list = []
    try:
        seconds = int(float(row['arc_int'])) * 60
    except (ValueError, TypeError) as e:
        logger.error(f"Could not determine archive interval at {row['date']} {row['time']}: {repr(e)}")
        return records_list

    for variable, variable_id in variable_dict.items():
        measurement = row[variable]
        if pd.isna(measurement):
            measurement = settings.MISSING_VALUE
        elif isinstance(measurement, str):
            if variable in COMPASS_COLUMNS:
                # Convert compass point to degrees (e.g. ENE -> 67.5)
                measurement = COMPASS_DEGREES.get(measurement.strip().upper(), settings.MISSING_VALUE)
            else:
                # All other strings: attempt numeric conversion, else missing
                try:
                    measurement = float(measurement)
                except (ValueError, TypeError):
                    measurement = settings.MISSING_VALUE

        records_list.append((station_id, variable_id, seconds, parsed_date, measurement, None, None, None, None, None,
                             None, None, None, None, False))

    return records_list


@shared_task
def read_file(
    filename, 
    highfrequency_data=False, 
    process_in_chunks=False, 
    station_data_file=None, 
    station_object=None, 
    utc_offset=settings.TIMEZONE_OFFSET, 
    override_data_on_conflict=False, 
    origin_file_name=None
    ):
    """Read a Davis WeatherLink text file and ingest minute-interval observations."""

    logger.info('processing %s' % filename)

    start = time.time()
    reads = []

    try:
        if station_object is None:

            if origin_file_name:
                station_code = station_code_from_filename(origin_file_name)
            else:
                station_code = station_code_from_filename(filename)

            try:
                station_object = Station.objects.get(code=station_code)
            except ObjectDoesNotExist:
                raise Exception(f"Station with code '{station_code}' not found.")
        station_id = station_object.id

        df = pd.read_csv(
            filename,
            sep='\t',
            skiprows=2,
            names=column_names,
            na_values=['---'],
        )

        # Drop rows with no date or time
        df = df[df['date'].notna() & df['time'].notna()]

        for index, row in df.iterrows():
            for line_data in parse_line(row, station_id, utc_offset):
                reads.append(line_data)

    except FileNotFoundError as fnf:
        logger.error(repr(fnf))
        print('No such file or directory {}.'.format(filename))
        raise

    except Exception as e:
        logger.error(repr(e))
        raise

    # insert data based on the type (high frequency, staged, standard)
    if highfrequency_data:
        insert_hf(reads, override_data_on_conflict)

    elif process_in_chunks:
        insert_staged(
            reads,
            station_data_file
        )

    else:
        insert(reads, override_data_on_conflict)

    end = time.time()

    logger.info(f'Processing file {filename} in {end - start} seconds, '
                f'returning #reads={len(reads)}.')

    return reads
