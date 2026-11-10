import datetime
import logging
import os
import pyoscar
import shutil

from builtins import IndexError

import math
import matplotlib as mpl
import numpy as np
import rasterio
from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import connection
from rasterio import RasterioIOError

from wx.enums import QualityFlagEnum
from wx.models import Watershed, StationVariable

mpl.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm
import pandas as pd
import cartopy.crs as ccrs
from metpy.interpolate import interpolate_to_grid, remove_nan_observations, remove_repeat_coordinates
from io import BytesIO

from psycopg2 import sql



def generate_expected_times(start, end, interval_seconds):
    midnight = start.replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    elapsed = (start - midnight).total_seconds()

    # Round up to the next clock-aligned interval.
    first = midnight + datetime.timedelta(
        seconds=math.ceil(elapsed / interval_seconds)
        * interval_seconds
    )

    current = first

    while current <= end:
        yield current
        current += datetime.timedelta(seconds=interval_seconds)


def get_altitude(lon, lat):
    try:

        dataset = rasterio.open(os.path.join(settings.SURFACE_DATA_DIR, 'srtm_19_09.tif'))

        band1 = dataset.read(1)

        row, col = dataset.index(float(lon), float(lat))

        altitude = band1[row, col]

    except (IndexError, RasterioIOError) as e:

        logging.exception(e)

        altitude = -999

    return altitude


def get_watershed(lon, lat):
    pnt = Point(lon, lat)

    try:

        watershed = Watershed.objects.get(geom__contains=pnt)

    except Watershed.DoesNotExist as e:

        logging.exception(e)

        return 'NOT FOUND'

    return watershed.watershed


def parse_bool_value(value):
    if value is None:
        return None

    return bool(value)


def parse_float_value(value):
    if not value:
        return None

    return float(value)


def parse_int_value(value):
    if not value:
        return None

    return int(value)


def verify_none_value(first_value, second_value):
    if first_value is not None:
        return first_value
    return second_value


def get_basic_map(proj):
    """Make our basic default map for plotting"""
    fig = plt.figure(figsize=(8, 10))
    view = fig.add_axes([.05, 0, .95, .95], projection=proj)
    view.set_extent([-90, -87, 15, 19])

    view.outline_patch.set_visible(False)
    view.background_patch.set_visible(False)

    # view.add_feature(cfeature.COASTLINE)
    # view.add_feature(cfeature.BORDERS, linestyle=':')
    return fig, view


def get_interpolation_data(data):
    df = pd.DataFrame.from_records(data)

    latitude_list = df['station__latitude']
    longitude_list = df['station__longitude']
    value_list = df['value']

    latitude_list, longitude_list, value_list = remove_nan_observations(longitude_list, latitude_list, value_list)
    latitude_list, longitude_list, value_list = remove_repeat_coordinates(longitude_list, latitude_list, value_list)

    return latitude_list, longitude_list, value_list


def get_interpolation_proj(latitude_list, longitude_list, value):
    from_proj = ccrs.Geodetic()
    to_proj = ccrs.AlbersEqualArea(central_longitude=-88.429595, central_latitude=17.202212)  # Belize location

    proj_points = to_proj.transform_points(from_proj, longitude_list, latitude_list)

    return (proj_points[:, 0], proj_points[:, 1], value, to_proj)


def get_boundaries_levels(value_list):
    max_value = int(value_list.max()) + 1
    min_value = int(value_list.min()) - 1

    if max_value == min_value:
        max_value = max_value + 5
        min_value = min_value - 5

    return list(range(min_value, max_value, 1))


def get_interpolation_image(interpolation_values):
    latitude_list, longitude_list, value_list = get_interpolation_data(interpolation_values)
    latitude_list, longitude_list, value_list, to_proj = get_interpolation_proj(latitude_list, longitude_list,
                                                                                value_list)

    gx, gy, img = interpolate_to_grid(x=latitude_list, y=longitude_list, z=value_list, interp_type='linear', hres=7500)

    levels = get_boundaries_levels(value_list)
    cmap = plt.get_cmap('magma')
    norm = BoundaryNorm(levels, ncolors=cmap.N, clip=True)

    img = np.ma.masked_where(np.isnan(img), img)
    fig, view = get_basic_map(to_proj)
    mmb = view.pcolormesh(gx, gy, img, cmap=cmap, norm=norm)
    # fig.colorbar(mmb, shrink=.4, pad=0, boundaries=levels)

    figfile = BytesIO()
    plt.savefig(figfile, format='png', transparent=True)

    return figfile.getvalue()


def update_station_variables(station, in_file_station_variables):
    current_station_variables = set(
        StationVariable.objects.filter(station=station).values_list('variable_id', flat=True))
    unregistered_station_variables = in_file_station_variables - current_station_variables

    for unregistered_station_variable in unregistered_station_variables:
        StationVariable.objects.create(station=station, variable_id=unregistered_station_variable)


def get_monthly_or_yearly(search_type, station, variable, search_date_start, search_date_end, source):
    response = {
        'results': {},
        'messages': [],
    }

    day_start = search_date_start[0:10]
    day_end = search_date_end[0:10]

    date_group = 'EXTRACT(year from day) as year'
    group_by = '1, 2, 3, 4, 5, 6, 12, 13, 14, 15, 16'
    order_by = '16'
    if source == 'monthly_summary':
        date_group += ',EXTRACT(month from day) as month'
        group_by = '1, 2, 3, 4, 5, 6, 12, 13, 14, 15, 16, 17'
        order_by = '16, 17'

    if search_type == 'station':
        sql_string = f'''
            SELECT                           
                a.station_id,
                a.variable_id,           
                b.symbol,
                b.name,
                c.name,
                c.symbol,
                min(a.min_value) min_value,
                max(a.max_value) max_value,
                avg(a.avg_value) avg_value,
                sum(a.sum_value) sum_value,
                count(a.sum_value),
                d.name,
                b.color,
                b.default_representation,
                b.sampling_operation_id,
                {date_group}
                FROM daily_summary a
            INNER JOIN wx_variable b ON a.variable_id=b.id
            INNER JOIN wx_unit c ON b.unit_id=c.id
            INNER JOIN wx_measurementvariable d ON b.measurement_variable_id=d.id
                where station_id={station}
                and day > '{day_start}'
                and day <= '{day_end}'
            GROUP BY {group_by}
            ORDER BY {order_by} ASC;
        '''
    elif search_type == 'stationvariable':
        sql_string = f'''
            SELECT                       
                a.station_id,
                a.variable_id,           
                b.symbol,
                b.name,
                c.name,
                c.symbol,
                min(a.min_value) min_value,
                max(a.max_value) max_value,
                avg(a.avg_value) avg_value,
                sum(a.sum_value) sum_value,
                count(a.sum_value),
                d.name,
                b.color,
                b.default_representation,
                b.sampling_operation_id
                {date_group}
                FROM daily_summary a
            INNER JOIN wx_variable b ON a.variable_id=b.id
            INNER JOIN wx_unit c ON b.unit_id=c.id
            INNER JOIN wx_measurementvariable d ON b.measurement_variable_id=d.id
                where station_id={station}
                and variable_id={variable}
                and day > '{day_start}'
                and day <= '{day_end}'
            GROUP BY {group_by}
            ORDER BY 1,2 ASC;
        '''

    with connection.cursor() as cursor:
        cursor.execute(sql_string)
        rows = cursor.fetchall()
        for row in rows:
            if not row[11] in response['results'].keys():
                response['results'][row[11]] = {}

            if not row[2] in response['results'][row[11]].keys():
                response['results'][row[11]][row[2]] = {
                    'color': row[12],
                    'default_representation': row[13],
                    'data': [],
                    'unit': row[5],
                }

            year = int(row[15])
            obj = {
                'station': row[0],
                'year': year,
                'variable': row[1],
                'measurementvariable': row[11]
            }

            if source == 'monthly_summary':
                month = int(row[16])
                if month < 10:
                    obj['date'] = f'{year}-0{month}'
                else:
                    obj['date'] = f'{year}-{month}'
                obj['month'] = month
            else:
                obj['date'] = year

            if row[11] in [6, 7]:
                obj['value'] = round(row[9], 2)  # sum_value
            elif row[11] == 3:
                obj['value'] = round(row[6], 2)  # min_value
            elif row[11] == 4:
                obj['value'] = round(row[7], 2)  # max_value
            else:
                obj['value'] = round(row[8], 2)  # avg_value

            response['results'][row[11]][row[2]]['data'].append(obj)

    return response




def get_raw_data(search_type, search_value, search_value2, search_date_start, search_date_end, source='raw_data'):
    response = {'results': {}, 'messages': []}

    valid_sources = {
        'raw_data', 'hourly_summary', 'daily_summary',
        'monthly_summary', 'yearly_summary',
    }
    if source not in valid_sources:
        response['messages'].append('Invalid report source.')
        return response

    if search_type not in ('variable', 'station', 'stationvariable'):
        response['messages'].append('Invalid search type.')
        return response

    # Keep the request formats expected by the existing report pages.
    date_formats = (
        ('%Y-%m-%d',) if source in ('daily_summary', 'monthly_summary', 'yearly_summary')
        else ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%MZ')
    )

    def parse_date(value):
        for date_format in date_formats:
            try:
                return datetime.datetime.strptime(value, date_format)
            except (TypeError, ValueError):
                pass
        raise ValueError('Unsupported date format: {}'.format(value))

    try:
        start_date = parse_date(search_date_start)
        end_date = parse_date(search_date_end)
    except ValueError as err:
        response['messages'].append('ValueError: {}'.format(err))
        return response

    if end_date < start_date:
        response['messages'].append('End date cannot precede start date.')
        return response

    date_column = {
        'daily_summary': 'day',
        'monthly_summary': 'date',
        'yearly_summary': 'date',
    }.get(source, 'datetime')

    if source == 'raw_data':
        # A validated reading must use consisted, even if it is null.
        # Do not fall back to measured and do not use manual_flag.
        value_columns = sql.SQL(
            'CASE WHEN a.is_validated IS TRUE THEN a.consisted ELSE a.measured END'
        )
        quality_columns = sql.SQL(', q.name AS quality_flag, q.color AS flag_color')
        quality_join = sql.SQL('''
            LEFT JOIN wx_qualityflag q
              ON q.id = CASE
                WHEN a.is_validated IS TRUE THEN a.validated_flag
                ELSE a.quality_flag
              END
        ''')
    else:
        # Preserve the original column order used by the reporting views.
        value_columns = sql.SQL(', ').join(
            sql.SQL('a.{}').format(sql.Identifier(column))
            for column in ('min_value', 'max_value', 'avg_value', 'sum_value')
        )
        quality_columns = sql.SQL('')
        quality_join = sql.SQL('')

    if search_type == 'variable':
        condition = sql.SQL('d.id = %s')
        params = [search_value]
    elif search_type == 'station':
        condition = sql.SQL('a.station_id = %s')
        params = [search_value]
    else:
        condition = sql.SQL('a.station_id = %s AND a.variable_id = %s')
        params = [search_value, search_value2]

    query = sql.SQL('''
        SELECT a.station_id,
               a.variable_id,
               b.symbol,
               b.name,
               c.name,
               c.symbol,
               EXTRACT(EPOCH FROM a.{date_column}),
               d.name,
               b.color,
               b.default_representation,
               b.sampling_operation_id
               {quality_columns},
               {value_columns}
        FROM {table} a
        JOIN wx_variable b ON a.variable_id = b.id
        JOIN wx_unit c ON b.unit_id = c.id
        JOIN wx_measurementvariable d ON b.measurement_variable_id = d.id
        {quality_join}
        WHERE {condition}
          AND a.{date_column} >= %s
          AND a.{date_column} <= %s
        ORDER BY a.{date_column}
    ''').format(
        date_column=sql.Identifier(date_column),
        quality_columns=quality_columns,
        value_columns=value_columns,
        table=sql.Identifier(source),
        quality_join=quality_join,
        condition=condition,
    )
    params.extend([search_date_start, search_date_end])

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    for row in rows:
        group_name = row[7]     # Measurement variable
        series_name = row[2]    # Variable symbol

        if group_name not in response['results']:
            response['results'][group_name] = {}

        if series_name not in response['results'][group_name]:
            response['results'][group_name][series_name] = {
                'color': row[8],
                'default_representation': row[9],
                'data': [],
                'unit': row[5],
            }

        obj = {
            'station': row[0],
            'date': row[6] * 1000,
            'variable': series_name,
            'measurementvariable': group_name,
        }

        if source == 'raw_data':
            # row[13] is the CASE-selected consisted/measured value.
            value = row[13]
            obj['value'] = round(value, 2) if value is not None else None
            obj['quality_flag'] = row[11]  # Effective QC name
            obj['flag_color'] = row[12]    # Effective QC color
        else:
            # Summary columns: MIN[11], MAX[12], AVG[13], SUM[14].
            value_index = {3: 11, 4: 12, 6: 14, 7: 14}.get(row[10], 13)
            value = row[value_index]
            obj['value'] = round(value, 2) if value is not None else None

        response['results'][group_name][series_name]['data'].append(obj)

    return response


def get_station_raw_data(search_type, search_values, search_value2, search_date_start,
                         search_date_end, search_filter, source='raw_data'):
    response = {'results': {}, 'messages': []}

    valid_sources = {
        'raw_data', 'hourly_summary', 'daily_summary',
        'monthly_summary', 'yearly_summary',
    }
    if source not in valid_sources:
        response['messages'].append('Invalid report source.')
        return response

    # This function is the multi-station variable-report query.
    if search_type != 'variable':
        response['messages'].append('Invalid search type.')
        return response

    variable_ids = tuple(search_values or ())
    station_ids = tuple(search_filter or ())
    if not variable_ids or not station_ids:
        response['messages'].append('At least one variable and station are required.')
        return response

    date_formats = (
        ('%Y-%m-%d',) if source in ('daily_summary', 'monthly_summary', 'yearly_summary')
        else ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%MZ')
    )

    def parse_date(value):
        for date_format in date_formats:
            try:
                return datetime.datetime.strptime(value, date_format)
            except (TypeError, ValueError):
                pass
        raise ValueError('Unsupported date format: {}'.format(value))

    try:
        start_date = parse_date(search_date_start)
        end_date = parse_date(search_date_end)
    except ValueError as err:
        response['messages'].append('ValueError: {}'.format(err))
        return response

    if end_date < start_date:
        response['messages'].append('End date cannot precede start date.')
        return response

    max_days = {
        'raw_data': 7,
        'hourly_summary': 30,
        'daily_summary': 365,
        'monthly_summary': None,
        'yearly_summary': None,
    }[source]
    if max_days is not None and (end_date - start_date) > datetime.timedelta(days=max_days):
        response['messages'].append(
            'The maximum number of days for a {} report is {}.'.format(
                source.replace('_', ' '), max_days
            )
        )
        return response

    date_column = {
        'daily_summary': 'day',
        'monthly_summary': 'date',
        'yearly_summary': 'date',
    }.get(source, 'datetime')

    if source == 'raw_data':
        value_columns = sql.SQL(
            'CASE WHEN a.is_validated IS TRUE THEN a.consisted ELSE a.measured END'
        )
        quality_columns = sql.SQL(', q.name AS quality_flag, q.color AS flag_color')
        quality_join = sql.SQL('''
            LEFT JOIN wx_qualityflag q
              ON q.id = CASE
                WHEN a.is_validated IS TRUE THEN a.validated_flag
                ELSE a.quality_flag
              END
        ''')
    else:
        value_columns = sql.SQL(', ').join(
            sql.SQL('a.{}').format(sql.Identifier(column))
            for column in ('min_value', 'max_value', 'avg_value', 'sum_value')
        )
        quality_columns = sql.SQL('')
        quality_join = sql.SQL('')

    query = sql.SQL('''
        SELECT a.station_id,
               a.variable_id,
               s.name,
               b.name,
               c.name,
               c.symbol,
               EXTRACT(EPOCH FROM a.{date_column}),
               b.name,
               b.color,
               b.default_representation,
               b.sampling_operation_id
               {quality_columns},
               {value_columns}
        FROM {table} a
        JOIN wx_variable b ON a.variable_id = b.id
        JOIN wx_unit c ON b.unit_id = c.id
        JOIN wx_stationvariable sv
          ON sv.station_id = a.station_id AND sv.variable_id = a.variable_id
        JOIN wx_station s ON s.id = sv.station_id
        {quality_join}
        WHERE a.variable_id IN %s
          AND a.{date_column} >= %s
          AND a.{date_column} <= %s
          AND a.station_id IN %s
        ORDER BY a.{date_column}
    ''').format(
        date_column=sql.Identifier(date_column),
        quality_columns=quality_columns,
        value_columns=value_columns,
        table=sql.Identifier(source),
        quality_join=quality_join,
    )

    with connection.cursor() as cursor:
        cursor.execute(query, (variable_ids, search_date_start, search_date_end, station_ids))
        rows = cursor.fetchall()

    for row in rows:
        group_name = row[7]   # Variable name
        series_name = row[2]  # Station name

        if group_name not in response['results']:
            response['results'][group_name] = {}

        if series_name not in response['results'][group_name]:
            response['results'][group_name][series_name] = {
                'color': row[8],
                'default_representation': row[9],
                'data': [],
                'unit': row[5],
            }

        obj = {
            'station': row[0],
            'date': row[6] * 1000,
            'variable': series_name,
            'measurementvariable': group_name,
        }

        if source == 'raw_data':
            value = row[13]  # CASE-selected consisted/measured value
            obj['value'] = round(value, 2) if value is not None else None
            obj['quality_flag'] = row[11]
            obj['flag_color'] = row[12]
        else:
            value_index = {3: 11, 4: 12, 6: 14, 7: 14}.get(row[10], 13)
            value = row[value_index]
            obj['value'] = round(value, 2) if value is not None else None

        response['results'][group_name][series_name]['data'].append(obj)

    return response