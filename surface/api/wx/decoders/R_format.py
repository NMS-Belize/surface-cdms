import datetime
import logging
import time

import pandas as pd
import pytz
from celery import shared_task

from tempestas_api import settings
from wx.decoders.insert_raw_data import insert
from wx.decoders.insert_hf_data import insert as insert_hf
from wx.decoders.insert_staged_raw_data import insert as insert_staged
from wx.decoders.manual_data import find_station_by_name

logger = logging.getLogger('surface.r_format')
db_logger = logging.getLogger('db')

# Maps all known R-format variable column names to database variable IDs.
# Columns present in a sheet but absent from this dict are treated as metadata
# and ignored.
variable_dict = {
    'Rain':             0,    # PRECIP
    'Max_Temp':         16,   # TEMPMAX
    'Min_Temp':         14,   # TEMPMIN
    '24_Hour_Wind_Run': 103,  # WINDRUN
    'Total_Sunshine':   77,   # SUNSHNHR
    '24_Hour_Evapn':    40,   # EVAPPAN
    'Thunder_Heard':    104,  # DYTHND
}

# Station name column candidates, checked in priority order
STATION_NAME_COLUMNS = ['station_name', 'station']

# Date verification columns — only checked when present in the sheet
DATE_VERIFY_COLUMNS = {'year', 'month_val', 'day_in_month'}


def parse_date(date_val, utc_offset):
    """Parse date from the date column (US format MM/DD/YYYY), return timezone-aware datetime."""
    datetime_offset = pytz.FixedOffset(utc_offset)
    if isinstance(date_val, datetime.datetime):
        date = date_val
    else:
        date = datetime.datetime.strptime(str(date_val), '%m/%d/%Y')
    return datetime_offset.localize(date)


def verify_date_fields(row, parsed_date, available_columns):
    """
    Verify year, month_val and day_in_month are consistent with the parsed date
    field. Only checks columns that are actually present in the sheet.
    Returns a list of error strings (empty if all fields match).
    """
    errors = []
    try:
        if 'year' in available_columns and row['year'] != '':
            if int(row['year']) != parsed_date.year:
                errors.append(f"year={row['year']} does not match date {parsed_date.date()}")
        if 'month_val' in available_columns and row['month_val'] != '':
            if int(row['month_val']) != parsed_date.month:
                errors.append(f"month_val={row['month_val']} does not match date {parsed_date.date()}")
        if 'day_in_month' in available_columns and row['day_in_month'] != '':
            if int(row['day_in_month']) != parsed_date.day:
                errors.append(f"day_in_month={row['day_in_month']} does not match date {parsed_date.date()}")
    except (ValueError, TypeError) as e:
        errors.append(f"Could not verify date fields: {repr(e)}")
    return errors


def parse_line(row, station_id, utc_offset, active_variables, available_columns):
    """Parse a single data row into a list of raw_data tuples."""
    parsed_date = parse_date(row['date'], utc_offset)

    date_errors = verify_date_fields(row, parsed_date, available_columns)
    if date_errors:
        raise ValueError(f"Date field mismatch at date={row['date']}: {'; '.join(date_errors)}")

    records_list = []
    seconds = 86400

    for variable, variable_id in active_variables.items():
        measurement = row[variable]
        if measurement is None or type(measurement) == str:
            measurement = settings.MISSING_VALUE

        records_list.append((station_id, variable_id, seconds, parsed_date, measurement, None, None, None, None, None,
                             None, None, None, None, True))

    return records_list


@shared_task
def read_file(
    filename, 
    highfrequency_data=False, 
    process_in_chunks=False, 
    station_data_file=None, 
    station_object=None, 
    utc_offset=settings.TIMEZONE_OFFSET, 
    override_data_on_conflict=False
    ):
    """Read an R-format xlsx file and ingest daily weather observations.

    Column layout is auto-detected per sheet. Sheets are skipped if they
    contain no date column, no recognisable station column, or no variable
    columns that map to known variable IDs.
    """

    logger.info('processing %s' % filename)

    start = time.time()
    reads = []
    try:
        source = pd.ExcelFile(filename)

        for sheet_name in source.sheet_names:
            sheet_raw_data = source.parse(
                sheet_name,
                header=0,
                na_filter=False,
            )

            if sheet_raw_data.empty:
                logger.warning(f"Skipping sheet '{sheet_name}': empty")
                continue

            # Normalise column names
            sheet_raw_data.columns = [str(c).strip() for c in sheet_raw_data.columns]
            available_columns = set(sheet_raw_data.columns)

            # Require a date column
            if 'date' not in available_columns:
                logger.warning(f"Skipping sheet '{sheet_name}': no 'date' column found")
                continue

            # Find station name column
            station_col = next((c for c in STATION_NAME_COLUMNS if c in available_columns), None)
            if station_col is None:
                logger.warning(f"Skipping sheet '{sheet_name}': no station name column found "
                               f"(looked for {STATION_NAME_COLUMNS})")
                continue

            # Determine which variable columns are present in this sheet
            active_variables = {col: variable_dict[col] for col in sheet_raw_data.columns
                                if col in variable_dict}
            if not active_variables:
                logger.warning(f"Skipping sheet '{sheet_name}': no recognised variable columns")
                continue

            logger.info(f"Sheet '{sheet_name}': station_col='{station_col}', "
                        f"variables={list(active_variables.keys())}")

            # Drop rows with no date value
            sheet_data = sheet_raw_data[sheet_raw_data['date'].astype(str).str.strip() != '']

            for station_name, station_group in sheet_data.groupby(station_col):
                station = find_station_by_name(str(station_name).strip())
                station_id = station.id

                for index, row in station_group.iterrows():
                    for line_data in parse_line(row, station_id, utc_offset,
                                                active_variables, available_columns):
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
