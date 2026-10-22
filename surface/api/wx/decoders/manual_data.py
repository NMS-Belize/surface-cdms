import calendar
import datetime
import logging
import time

import pandas as pd
import pytz
from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db.models import Value
from django.db.models.functions import Concat
from contextlib import nullcontext

from wx.quality_control.thresholds import preload_qc_thresholds
from wx.quality_control.helpers import reuse_qc_connection

from tempestas_api import settings
from wx.decoders.insert_raw_data import insert
from wx.decoders.insert_hf_data import insert as insert_hf
from wx.decoders.insert_staged_raw_data import insert as insert_staged
from wx.models import Station

logger = logging.getLogger('surface.manual_data')
db_logger = logging.getLogger('db')

column_names = [
    'day',
    'PRECIP',
    'TEMPMAX',
    'TEMPMIN',
    'TEMPAVG',
    'WNDMIL',
    'WINDRUN',
    'SUNSHNHR',
    'EVAPINI',
    'EVAPRES',
    'EVAPPAN',
    'TEMP',
    'TEMPWB',
    'TSOIL1',
    'TSOIL4',
    'DYTHND',
    'DYFOG',
    'DYHAIL',
    'DYGAIL',
    'TOTRAD',
    'RH@TMAX',
    'RHMAX',
    'RHMIN',
]

variable_dict = {
    'PRECIP': 0,
    'TEMPMAX': 16,
    'TEMPMIN': 14,
    'TEMPAVG': 12,
    'SUNSHNHR': 77,
    'WNDMIL': 102,
    'WINDRUN': 103,
    'EVAPINI': 4053,
    'EVAPRES': 4054,
    'EVAPPAN': 40,
    'TEMP': 10,
    'TEMPWB': 18,
    'TSOIL1': 21,
    'TSOIL4': 23,
    'DYTHND': 104,
    'DYHAIL': 105,
    'DYFOG': 106,
    'DYGAIL': 4052,
    'TOTRAD': 70,
    'RH@TMAX': 34,
    'RHMAX': 33,
    'RHMIN': 32,
}

def parse_date(month_datetime, day, utc_offset):
    datetime_offset = pytz.FixedOffset(utc_offset)
    date = month_datetime.replace(day=day)
    return datetime_offset.localize(date)

def is_integer_num(num):
    if isinstance(num, int):
        return True
    if isinstance(num, float):
        return num.is_integer()
    return False

def parse_line(line, station_id, month_datetime, utc_offset):
    """Parse a manual data row"""

    records_list = []
    day = line['day']
    if is_integer_num(day):
        day = int(day)
    parsed_date = parse_date(month_datetime, day, utc_offset)
    seconds = 86400

    for variable in variable_dict.keys():
        variable_id = variable_dict[variable]
        measurement = line[variable]
        if measurement is None or type(measurement) == str:
            measurement = settings.MISSING_VALUE

        records_list.append((station_id, variable_id, seconds, parsed_date, measurement, None, None, None, None, None,
                             None, None, None, None, True))

    return records_list

def find_station_by_name(station_name):
    station = None  
    
    station_name = station_name.strip() # removing any trailing or leading whitespace

    try:
        station = Station.objects.get(name=station_name, is_automatic=False)
    except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
        try:
            station = Station.objects.get(alias_name=station_name, is_automatic=False)
        except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
            try:
                station_name_for_query = station_name + ','
                station = Station.objects.annotate(names=Concat('alternative_names', Value(','))).get(
                            names=station_name_for_query, is_automatic=False)
            except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
                raise Exception(f"Failed to find station by name '{station_name}' or station is automatic, stations must be manual. {repr(e)}")

    return station


@shared_task
def read_file(
    filename,
    highfrequency_data=False,
    process_in_chunks=False,
    station_data_file=None,
    station_object=None,
    utc_offset=settings.TIMEZONE_OFFSET,
    override_data_on_conflict=False,
    is_manually_reviewed=False,
    excel_source=None,
):
    """Decode a manual workbook and insert its observations."""

    logger.info("Processing manual data file: %s", filename)

    start = time.perf_counter()
    reads = []
    month_datetime = None
    last_month_day = None

    # Resolve column positions once rather than looking up names per observation.
    variable_columns = tuple(
        (column_names.index(name), variable_id)
        for name, variable_id in variable_dict.items()
    )

    # Preserve the existing use of the supplied decoder timezone offset.
    station_timezone = pytz.FixedOffset(utc_offset)

    try:
        # The caller closes a supplied workbook; otherwise we close it here.
        workbook_context = (
            nullcontext(excel_source)
            if excel_source is not None
            else pd.ExcelFile(filename)
        )

        with workbook_context as source:
            for sheet_name in source.sheet_names:
                sheet_raw_data = source.parse(
                    sheet_name,
                    skipfooter=2,
                    na_filter=False,
                    names=column_names,
                    usecols="A:W",
                )

                if sheet_raw_data.empty:
                    continue

                station = find_station_by_name(sheet_name.strip())
                station_id = station.id

                # Preserve the workbook-wide month/year from the first nonempty sheet.
                if month_datetime is None:
                    header = sheet_raw_data.iloc[0]

                    sheet_month = (
                        header["WINDRUN"]
                        .replace("MONTH: ", "")
                        .strip()
                    )
                    sheet_year = (
                        header["EVAPRES"]
                        .replace("YEAR: ", "")
                        .strip()
                    )

                    month_datetime = datetime.datetime.strptime(
                        f"{sheet_month} {sheet_year}",
                        "%B %Y",
                    )

                    _, last_month_day = calendar.monthrange(
                        month_datetime.year,
                        month_datetime.month,
                    )

                sheet_data = sheet_raw_data.iloc[7:]

                day_numbers = pd.to_numeric(
                    sheet_data["day"],
                    errors="coerce",
                )

                # Keep only whole-number days that exist in this month.
                valid_days = (
                    day_numbers.between(1, last_month_day)
                    & day_numbers.mod(1).eq(0)
                )

                valid_rows = sheet_data.loc[valid_days, column_names]
                days = day_numbers.loc[valid_days].astype(int)

                # Tuples avoid constructing a pandas Series for every row.
                for day, row in zip(
                    days,
                    valid_rows.itertuples(index=False, name=None),
                ):
                    parsed_date = station_timezone.localize(
                        month_datetime.replace(day=int(day))
                    )

                    for column_index, variable_id in variable_columns:
                        measurement = row[column_index]

                        # Text and empty numeric cells represent missing data.
                        if (
                            isinstance(measurement, str)
                            or pd.isna(measurement)
                        ):
                            measurement = settings.MISSING_VALUE

                        reads.append((
                            station_id,
                            variable_id,
                            86400,
                            parsed_date,
                            measurement,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            True,
                        ))

    except Exception:
        logger.exception(
            "Failed decoding manual data file: %s",
            filename,
        )
        raise

    decode_finished = time.perf_counter()

    logger.info(
        "Manual decoder | file=%s | records=%s | decode=%.2fs",
        filename,
        len(reads),
        decode_finished - start,
    )

    # Keep the existing high-frequency and staged insertion routes.
    if highfrequency_data:
        insert_hf(
            reads,
            override_data_on_conflict,
        )

    elif process_in_chunks:
        insert_staged(
            reads,
            station_data_file,
        )

    else:
        station_ids = {record[0] for record in reads}
        variable_ids = {record[1] for record in reads}

        if reads:
            # Preload thresholds and reuse the QC lookup connection.
            with preload_qc_thresholds(station_ids, variable_ids):
                with reuse_qc_connection():
                    insert(
                        reads,
                        override_data_on_conflict,
                        is_manually_reviewed,
                        insert_page_size=1000,
                    )
        else:
            insert(
                reads,
                override_data_on_conflict,
                is_manually_reviewed,
            )

    finished = time.perf_counter()

    logger.info(
        "Manual decoder | file=%s | records=%s | "
        "decode=%.2fs | insert_pipeline=%.2fs | total=%.2fs",
        filename,
        len(reads),
        decode_finished - start,
        finished - decode_finished,
        finished - start,
    )

    return reads