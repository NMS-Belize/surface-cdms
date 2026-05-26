import datetime
import io
import json
import uuid
import logging
import os
import zipfile
import shutil
import random
import pyoscar
import calendar
import wx.export_surface_oscar as exso
from datetime import datetime as datetime_constructor
from datetime import timezone, timedelta, date
from dateutil.relativedelta import relativedelta
from django.utils.dateparse import parse_date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import openpyxl
from openpyxl import Workbook
import tempfile
import psycopg2
import pytz
from wx.decorators import wx_permission_required, wx_mapped_permission_required
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from wx.mixins import WxPermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, transaction, IntegrityError
from django.utils.dateparse import parse_datetime
from django.http import HttpResponse, JsonResponse, FileResponse, HttpResponseNotAllowed, HttpResponseBadRequest, Http404
from django.utils.http import http_date
from django.template import loader
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views import View
from django.views.generic.base import TemplateView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.list import ListView
from django.db.models.deletion import ProtectedError
from geopandas import geopandas
from material import *
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.transforms import Bbox
from metpy.interpolate import interpolate_to_grid
from pandas import json_normalize
from rest_framework import viewsets, status, generics, views, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import FileUploadParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from slugify import slugify
from celery.result import AsyncResult

from tempestas_api import settings
from wx import serializers, tasks
from wx.decoders.hobo import read_file as read_file_hobo
from wx.decoders.toa5 import read_file as read_file_toa5
from wx.decoders.weatherlink_json import read_file as read_file_weatherlink_json
from wx.decoders.f2000 import validate_content as f2000_content_check
from wx.decoders.f2000 import validate_structure as f2000_structure_check
from wx.forms import StationForm
from wx.permissions import IsSuperUser
from wx.models import AdministrativeRegion, StationFile, Decoder, QualityFlag, DataFile, DataFileStation, \
    DataFileVariable, StationImage, WMOStationType, WMORegion, WMOProgram, StationCommunication, CombineDataFile, ManualStationDataFile
from wx.models import Country, Unit, Station, Variable, DataSource, StationVariable, StationDataFileStatus,\
    StationProfile, Document, Watershed, Interval, CountryISOCode, Wis2BoxPublish, Wis2PublishOffset, LocalWisCredentials, RegionalWisCredentials,  Wis2BoxPublishLogs, Crop, Soil
from wx.utils import get_altitude, get_watershed, get_district, get_interpolation_image, parse_float_value, \
    parse_int_value
from .utils import get_raw_data, get_station_raw_data
from wx.models import MaintenanceReport, VisitType, Technician
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from base64 import b64encode

from wx.models import QualityFlag, WxPermissionPages, WxGroupPageAccess
import time
from wx.models import HighFrequencyData, MeasurementVariable
from wx.tasks import fft_decompose, export_station_to_oscar, export_station_to_oscar_wigos, data_inventory_month_view, save_monthly_form, save_synop_form
import math
import numpy as np

from wx.models import Equipment, EquipmentType, EquipmentModel, Manufacturer, FundingSource, StationProfileEquipmentType
from django.core.serializers import serialize
from django.core.serializers.json import DjangoJSONEncoder
from wx.models import MaintenanceReportEquipment
from wx.models import QcRangeThreshold, QcStepThreshold, QcPersistThreshold
from simple_history.utils import update_change_reason
from django.db.models.functions import Cast
from django.db.models import IntegerField, Q, Case, When, IntegerField
from django.utils.timezone import localtime


from wx.models import WMOCodeValue
from jinja2 import Environment, FileSystemLoader

from aquacrop import Crop as AquacropCrop
from aquacrop import Soil as AquacropSoil

import tempfile

from aquacrop import AquaCropModel, InitialWaterContent, FieldMngt, GroundWater, IrrigationManagement
from aquacrop.utils import prepare_weather, get_filepath
from supabase import create_client, Client
import requests
import re

logger = logging.getLogger('surface.urls')

# get user models
User = get_user_model()

# CONSTANT to be used in datetime to milliseconds conversion
EPOCH = datetime_constructor(1970, 1, 1, tzinfo=timezone.utc)


@csrf_exempt
@wx_mapped_permission_required
def ScheduleDataExport(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    # access values from the response
    json_body = json.loads(request.body)
    station_ids = json_body['stations']  # array with station ids

    data_source = json_body['source']  # could be either raw_data, hourly_summary, daily_summary, monthly_summary or yearly_summary

    start_date = json_body['start_datetime']  # in format %Y-%m-%d %H:%M:%S

    end_date = json_body['end_datetime']  # in format %Y-%m-%d %H:%M:%S

    variable_ids = json_body['variables']  # list of obj in format {id: Int, agg: Str}

    aggregation = json_body['aggregation'] # sets which column in the db will be used when the source is a summary. 

    displayUTC = json_body['displayUTC'] # determines whether an offset will be applied based on the truthines of displayUTC

    aqc_checks = json_body['aqc_checks'] # determines whether the output should only consist of data which pass aqc checks
    
    mqc_checks = json_body['mqc_checks'] # determines whether the output should only consist of data which pass mqc checks

    # If source is raw_data, this will be set to none
    if data_source == 'raw_data':
        aggregation = None

    data_interval_seconds = None
    if data_source == 'raw_data' and 'data_interval' in json_body:  # a number with the data interval in seconds. Only required for raw_data
        data_interval_seconds = json_body['data_interval']
    elif data_source == 'raw_data':
        data_interval_seconds = 300

    created_data_file_ids = []
    start_date_utc = pytz.UTC.localize(datetime.datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S'))
    end_date_utc = pytz.UTC.localize(datetime.datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S'))
    current_utc_datetime = datetime.datetime.now(pytz.utc)

    if start_date_utc > end_date_utc:
        message = 'The initial date must be greater than final date.'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    days_interval = (end_date_utc - start_date_utc).days

    data_source_dict = {
        "raw_data": "Raw Data",
        "hourly_summary": "Hourly Summary",
        "daily_summary": "Daily Summary",
        "monthly_summary": "Monthly Summary",
        "yearly_summary": "Yearly Summary",
    }

    data_source_description = data_source_dict[data_source]

    prepared_by = None
    if request.user.first_name and request.user.last_name:
        prepared_by = f'{request.user.first_name} {request.user.last_name}'
    else:
        prepared_by = request.user.username

    for station_id in station_ids:
        if aggregation:
            for agg in aggregation:
                newfile = DataFile.objects.create(ready=False, 
                                                  initial_date=start_date_utc, 
                                                  final_date=end_date_utc,
                                                  source=data_source_description, 
                                                  prepared_by=prepared_by,
                                                  interval_in_seconds=data_interval_seconds,
                                                  aqc_checks = aqc_checks,
                                                  mqc_checks = mqc_checks)
                
                DataFileStation.objects.create(datafile=newfile, station_id=station_id)

                try:
                    for variable_id in variable_ids:
                        variable = Variable.objects.get(pk=variable_id)
                        DataFileVariable.objects.create(datafile=newfile, variable=variable)

                    tasks.export_data.delay(station_id, data_source, start_date, end_date, variable_ids, newfile.id, agg, aqc_checks, mqc_checks, displayUTC)
                    created_data_file_ids.append(newfile.id)
                except Exception as err:
                    # if an error occuers udpate the datafile ready_at option whilst leaving ready = false
                    # this shows that the operation failed
                    # the function DataExportFiles users both "ready" and "ready_at to determin whether an error occured or not"
                    # this prevents a possible error state from mascarading as a "processing" status
                    newfile.ready_at = current_utc_datetime
        else:
            newfile = DataFile.objects.create(ready=False, 
                                              initial_date=start_date_utc, 
                                              final_date=end_date_utc,
                                              source=data_source_description, 
                                              prepared_by=prepared_by,
                                              interval_in_seconds=data_interval_seconds,
                                              aqc_checks = aqc_checks,
                                              mqc_checks = mqc_checks
                                            )
            
            DataFileStation.objects.create(datafile=newfile, station_id=station_id)

            try:
                for variable_id in variable_ids:
                    variable = Variable.objects.get(pk=variable_id)
                    DataFileVariable.objects.create(datafile=newfile, variable=variable)

                tasks.export_data.delay(station_id, data_source, start_date, end_date, variable_ids, newfile.id, aggregation, aqc_checks, mqc_checks, displayUTC)
                created_data_file_ids.append(newfile.id)
            except Exception as err:
                # if an error occuers udpate the datafile ready_at option whilst leaving ready = false
                # this shows that the operation failed
                # the function DataExportFiles users both "ready" and "ready_at to determin whether an error occured or not
                # this prevents a possible error state from mascarading as a "processing" status
                newfile.ready_at = current_utc_datetime

    return JsonResponse({'data': created_data_file_ids}, status=status.HTTP_200_OK)


@api_view(('GET',))
@wx_mapped_permission_required
def DataExportFiles(request):
    files = []
    for df in DataFile.objects.all().order_by('-created_at').values()[:100:1]:
        if df['ready'] and df['ready_at']:
            file_status = {'text': "Ready", 'value': 1}
        elif df['ready_at']:
            file_status = {'text': "Error", 'value': 2}
        else:
            file_status = {'text': "Processing", 'value': 0}

        current_station_name = None
        try:
            current_data_file = DataFileStation.objects.get(datafile_id=df['id'])
            current_station = Station.objects.get(pk=current_data_file.station_id, is_reference=False)
            current_station_name = current_station.name
        except ObjectDoesNotExist:
            current_station_name = "Station not found"

        f = {
            'id': df['id'],
            'request_date': df['created_at'],
            'ready_date': df['ready_at'],
            'station': current_station_name,
            'variables': [],
            'status': file_status,
            'aqc_checks': df['aqc_checks'],
            'mqc_checks': df['mqc_checks'],
            'initial_date': df['initial_date'],
            'final_date': df['final_date'],
            'source': {'text': df['source'],
                       'value': 0 if df['source'] == 'Raw data' else (1 if df['source'] == 'Hourly summary' else 2)},
            'lines': df['lines'],
            'prepared_by': df['prepared_by'],
        }
        if f['ready_date'] is not None:
            f['ready_date'] = f['ready_date']
        for fv in DataFileVariable.objects.filter(datafile_id=df['id']).values():
            f['variables'].append(Variable.objects.filter(pk=fv['variable_id']).values()[0]['name'])
        files.append(f)

    return Response(files, status=status.HTTP_200_OK)


@wx_mapped_permission_required
def DownloadDataFile(request):
    file_id = request.GET.get('id', None)
    # for combine xlsx downloads
    if 'combine' in str(file_id):
        file_path = os.path.join('/data', 'exported_data', str(file_id) + '.xlsx')
    else:
        file_path = os.path.join('/data', 'exported_data', str(file_id) + '.csv')
    if os.path.exists(file_path):
        # with open(file_path, 'rb') as fh:
        #     response = HttpResponse(fh.read(), content_type="text/csv")
        #     response['Content-Disposition'] = 'inline; filename=' + os.path.basename(file_path)
        #     return response
        return FileResponse(open(file_path, 'rb'), as_attachment=True, filename=os.path.basename(file_path))
    return JsonResponse({}, status=status.HTTP_404_NOT_FOUND)


# download .xlsx version of the data file
@wx_mapped_permission_required
def DownloadDataFileXLSX(request):
    # file id of the csv to be converted to .xlsx
    file_id = request.GET.get('id', None)
    # path to the xlsx file
    xlsx_file_path = os.path.join('/data', 'exported_data', str(file_id) + '.xlsx')
    # path to the csv file
    file_path = os.path.join('/data', 'exported_data', str(file_id) + '.csv')

    try:
        if not os.path.exists(xlsx_file_path):
            # if the .xlsx file does not exist then create it
            tasks.convert_csv_xlsx(file_path, file_id, file_id)

        return FileResponse(open(xlsx_file_path, 'rb'), as_attachment=True, filename=os.path.basename(xlsx_file_path))
    
    except Exception as e:
        logger.error(f"An error occured while trying to download {file_id}.xlsx. Error code: {e}")
    
    # return 404 on error
    return JsonResponse({}, status=status.HTTP_404_NOT_FOUND)


# combine csv files into a .xlsx file and then download them
@csrf_exempt
@wx_mapped_permission_required
def CombineFilesXLSX(request):
    # ensure that the request method is post
    if request.method != 'POST':
        # else return the "method not allowed" error in response
        return HttpResponse(status=405)
    
    # processing the request
    try:
        # ensuring that the start date and the end date are valid
        json_body = json.loads(request.body)
        # grabbing the start and the end date
        start_date = json_body['start_datetime']  # in format %Y-%m-%d %H:%M:%S

        end_date = json_body['end_datetime']  # in format %Y-%m-%d %H:%M:%S

        start_date_utc = pytz.UTC.localize(datetime.datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S'))
        end_date_utc = pytz.UTC.localize(datetime.datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S'))
        # ensuring that the start date and the end date are valid
        if start_date_utc > end_date_utc:
            message = 'The initial date must be greater than final date.'
            return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

        station_ids = json_body['stations']  # array with station ids

        data_source = json_body['source']  # could be either raw_data, hourly_summary, daily_summary, monthly_summary or yearly_summary

        variable_ids = json_body['variables']  # list of obj in format {id: Int, agg: Str}

        aggregation = json_body['aggregation'] # sets which column in the db will be used when the source is a summary. 

        displayUTC = json_body['displayUTC'] # determins wheter an offset will be applied based on the truthines of displayUTC

        aqc_checks = json_body['aqc_checks'] # determines whether the output should only consist of data which pass aqc checks
        
        mqc_checks = json_body['mqc_checks'] # determines whether the output should only consist of data which pass mqc checks

        # If source is raw_data, aggregation will be set to none
        if data_source == 'raw_data':
            aggregation = ""

        data_interval_seconds = None
        if data_source == 'raw_data' and 'data_interval' in json_body:  # a number with the data interval in seconds. Only required for raw_data
            data_interval_seconds = json_body['data_interval']
        elif data_source == 'raw_data':
            data_interval_seconds = 300

        prepared_by = None
        if request.user.first_name and request.user.last_name:
            prepared_by = f'{request.user.first_name} {request.user.last_name}'
        else:
            prepared_by = request.user.username

        data_source_dict = {
            "raw_data": "Raw Data",
            "hourly_summary": "Hourly Summary",
            "daily_summary": "Daily Summary",
            "monthly_summary": "Monthly Summary",
            "yearly_summary": "Yearly Summary",
        }

        data_source_description = data_source_dict[data_source]

        # converting the station_ids into a string to pass to the new entry
        station_ids_string = ""
        for x in station_ids:
            station_ids_string += str(x) + "_"

        # converting the variable_ids into a string to pass to the new entry
        variable_ids_string = ""
        for y in variable_ids:
            variable_ids_string += str(y) + "_"

        # add this file entry to the combine data file model
        new_entry = CombineDataFile.objects.create(ready=False, 
                                                   initial_date=start_date_utc, 
                                                   final_date=end_date_utc,
                                                   source=data_source_description, 
                                                   prepared_by=prepared_by,
                                                   stations_ids=station_ids_string, 
                                                   variable_ids=variable_ids_string, 
                                                   aggregation="  ".join(aggregation).upper(),                                                  
                                                   aqc_checks=aqc_checks,
                                                   mqc_checks=mqc_checks)

        # send the MAIN task unto celery
        combine_task = tasks.combine_xlsx_files.delay(station_ids, data_source, start_date, end_date, variable_ids, aggregation, displayUTC, data_interval_seconds, prepared_by, data_source_description, aqc_checks, mqc_checks, new_entry.id)

        return JsonResponse({'data': new_entry.id}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'An error occured while attempting to schedule combine task. Error = {e}')
        return JsonResponse({"error": str(e)}, status=500)


# get an update on the combine files
@api_view(('GET',))
@wx_mapped_permission_required
def combineDataExportFiles(request):
    files = []
    try:
        for df in CombineDataFile.objects.all().order_by('-created_at').values()[:100:1]:
            if df['ready'] and df['ready_at']:
                file_status = {'text': "Ready", 'value': 1}
            elif df['ready_at']:
                file_status = {'text': "Error", 'value': 2}
            else:
                file_status = {'text': "Processing", 'value': 0}

            # getting the stations list
            current_station_names_list = []
            try:
                station_ids = str(df['stations_ids']).split('_')

                for x in station_ids:
                    if x:
                        current_station_names_list.append(Station.objects.get(pk=int(x)).name)

            except ObjectDoesNotExist:
                current_station_names_list = ["Stations not found"]


            # getting variables list
            variable_list = []
            try:
                variable_ids = str(df['variable_ids']).split('_')

                for y in variable_ids:
                    if y:
                        variable_list.append(Variable.objects.get(pk=int(y)).name)

            except Exception as e:
                # logger.warning(f'An warning occurd during variable list creation: {variable_ids}')
                variable_list = ["No variables"]

            f = {
                'id': df['id'],
                'request_date': df['created_at'],
                'ready_date': df['ready_at'],
                'station': current_station_names_list,
                'aqc_checks': df['aqc_checks'],
                'mqc_checks': df['mqc_checks'],
                'variables': variable_list,
                'status': file_status,
                'initial_date': df['initial_date'],
                'final_date': df['final_date'],
                'source': {'text': df['source'],
                        'value': 0 if df['source'] == 'Raw data' else (1 if df['source'] == 'Hourly summary' else 2)},
                'lines': df['lines'],
                'prepared_by': df['prepared_by'],
                'aggregation': df['aggregation'],
            }
            if f['ready_date'] is not None:
                f['ready_date'] = f['ready_date']
            files.append(f)

        return Response(files, status=status.HTTP_200_OK)

    except Exception as e:
        logger.warning(f"An error occured while attempting to update the combined .xlsx files table. Error - {e}")
        return JsonResponse({"error": str(e)}, status=500)


# to delete data file
@wx_mapped_permission_required
def DeleteDataFile(request):
    file_id = request.GET.get('id', None)

    if 'combine' in str(file_id):
        entry_id = int(str(file_id).split('-')[-1])

        CombineDataFile.objects.get(pk=entry_id).delete()

        file_path = os.path.join('/data', 'exported_data', str(file_id) + '.xlsx')

        if os.path.exists(file_path):
            os.remove(file_path)
        return JsonResponse({}, status=status.HTTP_200_OK)

    df = DataFile.objects.get(pk=file_id)
    DataFileStation.objects.filter(datafile=df).delete()
    DataFileVariable.objects.filter(datafile=df).delete()
    df.delete()
    file_path = os.path.join('/data', 'exported_data', str(file_id) + '.csv')
    if os.path.exists(file_path):
        os.remove(file_path)
    return JsonResponse({}, status=status.HTTP_200_OK)


@wx_mapped_permission_required
def GetInterpolationData(request):
    params = {
        'start_datetime': request.GET.get('start_datetime'),
        'end_datetime': request.GET.get('end_datetime'),
        'variable_id': request.GET.get('variable_id'),
        'agg': request.GET.get('agg', 'instant'),
        'source': request.GET.get('source', 'raw_data'),
        'quality_flags': request.GET.get('quality_flags'),
    }

    task = tasks.fetch_interpolation_data_task.delay(**params)

    return JsonResponse({"task_id": task.id})


@wx_mapped_permission_required
def GetInterpolationImage(request):

    params = {
        'start_datetime': request.GET.get('start_datetime', None),
        'end_datetime': request.GET.get('end_datetime', None),
        'variable_id': request.GET.get('variable_id', None),
        'cmap': request.GET.get('cmap', 'Spectral_r'),
        'hres': request.GET.get('hres', 0.01),
        'minimum_neighbors': request.GET.get('minimum_neighbors', 1),
        'search_radius': request.GET.get('search_radius', 0.7),
        'agg': request.GET.get('agg', "instant"),
        'source': request.GET.get('source', "raw_data"),
        'vmin': request.GET.get('vmin', 0),
        'vmax': request.GET.get('vmax', 30),
        'quality_flags': request.GET.get('quality_flags', None),
        'stands_llat': settings.SPATIAL_ANALYSIS_INITIAL_LATITUDE,
        'stands_llon': settings.SPATIAL_ANALYSIS_INITIAL_LONGITUDE,
        'stands_ulat': settings.SPATIAL_ANALYSIS_FINAL_LATITUDE,
        'stands_ulon': settings.SPATIAL_ANALYSIS_FINAL_LONGITUDE,
    }

    task = tasks.fetch_interpolation_img_task.delay(**params)

    return JsonResponse({"task_id": task.id})


@wx_mapped_permission_required
def GetColorMapBar(request):
    start_datetime_req = request.GET.get('start_datetime', '')
    end_datetime_req = request.GET.get('end_datetime', '')
    variable_id = request.GET.get('variable_id', '')
    cmap = request.GET.get('cmap', 'Spectral_r')
    agg = request.GET.get('agg', "instant")
    vmin = request.GET.get('vmin', 0)
    vmax = request.GET.get('vmax', 30)

    try:
        start_datetime = pytz.UTC.localize(datetime.datetime.strptime(start_datetime_req, '%Y-%m-%dT%H:%M:%S.%fZ'))
        end_datetime = pytz.UTC.localize(datetime.datetime.strptime(end_datetime_req, '%Y-%m-%dT%H:%M:%S.%fZ'))

        start_datetime = start_datetime.astimezone(pytz.timezone(settings.TIMEZONE_NAME))
        end_datetime = end_datetime.astimezone(pytz.timezone(settings.TIMEZONE_NAME))
    except ValueError:
        try:
            start_datetime = pytz.UTC.localize(datetime.datetime.strptime(start_datetime_req, '%Y-%m-%d'))
            end_datetime = pytz.UTC.localize(datetime.datetime.strptime(end_datetime_req, '%Y-%m-%d'))

        except ValueError:
            return JsonResponse({"message": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT a.name,b.symbol
            FROM wx_variable a INNER JOIN wx_unit b ON a.unit_id=b.id
            WHERE a.id=%(variable_id)s
            """,
                       params={'variable_id': variable_id}
                       )
        variable = cursor.fetchone()

    fig = plt.figure(figsize=(9, 1.5))
    plt.imshow([[2]], origin='lower', cmap=cmap, vmin=vmin, vmax=vmax)
    plt.gca().set_visible(False)
    cax = plt.axes([0.1, 0.2, 0.8, 0.2])
    title = variable[0] + ' (' + variable[1] + ') - ' + start_datetime.strftime("%d/%m/%Y %H:%M:%S")
    if agg != 'instant':
        title += ' to ' + end_datetime.strftime("%d/%m/%Y %H:%M:%S")
        title += ' (' + agg + ')'
    cax.set_title(title)
    plt.colorbar(orientation='horizontal', cax=cax)

    FigureCanvas(fig)
    buf = io.BytesIO()
    plt.savefig(buf, dpi='figure', format='png', transparent=True, bbox_inches='tight')
    plt.close(fig)
    response = HttpResponse(buf.getvalue(), content_type='image/png')

    return response


@csrf_exempt
@wx_mapped_permission_required
def InterpolatePostData(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    json_body = json.loads(request.body)

    params = {
        'stands_llat': settings.SPATIAL_ANALYSIS_INITIAL_LATITUDE,
        'stands_llon': settings.SPATIAL_ANALYSIS_INITIAL_LONGITUDE,
        'stands_ulat': settings.SPATIAL_ANALYSIS_FINAL_LATITUDE,
        'stands_ulon': settings.SPATIAL_ANALYSIS_FINAL_LONGITUDE,
        'parameters': json_body['parameters'],
        'vmin': json_body['vmin'],
        'vmax': json_body['vmax'],
        'json_body_data': json_body['data'],
    }

    task = tasks.fetch_mod_interpolation_img_task.delay(**params)

    return JsonResponse({"task_id": task.id})
    



class DataExportView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/data_export.html"

    def get_context_data(self, **kwargs):
        context =  super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.select_related('profile').exclude(is_reference=True)
        context['variable_list'] = Variable.objects.select_related('unit').all()

        context['station_profile_list'] = StationProfile.objects.all()
        context['station_watershed_list'] = Watershed.objects.all()
        context['station_district_list'] = AdministrativeRegion.objects.all()

        interval_list = Interval.objects.filter(seconds__gte=2).order_by('seconds') # exclude 1 second interval
        context['interval_list'] = interval_list

        return context


# view to display manual upload page
class ManualDataImportView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    '''view for uploading daily data for manual station (file format is xlsx)'''

    template_name = "wx/data/manual_data_import.html"
    
    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs)

    # reseting the directory which holds uploaded files before processing
    UPLOAD_DIR = '/data/documents/ingest/manual/check'

    def dispatch(self, request, *args, **kwargs):
        '''Ensure the directory exists before handling a request'''
        if os.path.exists(self.UPLOAD_DIR):  # Check if the directory exists
            shutil.rmtree(self.UPLOAD_DIR)
            logger.info(f"Directory '{self.UPLOAD_DIR}' deleted. (Prep work for Manual Import)")

        try:
            os.makedirs(self.UPLOAD_DIR, exist_ok=True)
            logger.info(f"Created directory '{self.UPLOAD_DIR}'.")
        except PermissionError as e:
            logger.error(f"Permission denied: {e}")
            return HttpResponse("Server error: Unable to create directory.", status=500)

        return super().dispatch(request, *args, **kwargs)
    

# retrieves manual data files metadata
@api_view(('GET',))
@wx_mapped_permission_required
def ManualDataFiles(request):
    files = []
    for df in ManualStationDataFile.objects.all().order_by('-created_at').values()[:100:1]:

        file_status = df['status_id']

        status_dict = {
            1:"Pending",
            2:"Processing",
            3:"Processed",
            4:"Error",
        }

        def chunk_stations(stations_str):
            stations = stations_str.split("       ")  # Split by multiple spaces
            return [",  ".join(stations[i:i+5]) for i in range(0, len(stations), 5)]

        # Example usage
        formatted_station = chunk_stations(df['stations_list'])

        f = {
            'id': df['id'],
            'upload_date': df['upload_date'],
            'file_name': df['file_name'],
            'status': status_dict[file_status],
            'stations_list': formatted_station,
            'observation': df['observation'],
            'month': df['month'],
            'override_data_on_conflict': "Yes!" if df['override_data_on_conflict'] else "No!",
        }

        files.append(f)

    return Response(files, status=status.HTTP_200_OK)


# delete manual data file
@wx_mapped_permission_required
def DeleteManualDataFile(request):
    file_id = request.GET.get('id', None)

    df = ManualStationDataFile.objects.get(pk=file_id)

    df.delete()

    return JsonResponse({}, status=status.HTTP_200_OK)


# recieve files from the manual import page, run some checks and return a success response
@csrf_exempt
@wx_mapped_permission_required
def CheckManualImportView(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=400)

    uploaded_files = {}
    unsupported_files = ""
    duplicate_files = ""
    f2000_errors = []
    non_existent_stations = []

    UPLOAD_DIR = "/data/documents/ingest/manual/check"
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    decoder_format = request.POST.get("decoder_format", "default")

    # default accepted file type
    allowed_file_types = {
        ".xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    }

    # file types for davis
    if decoder_format == "davis":
        allowed_file_types = {
            ".txt": ["text/tab-separated-values", "text/plain"],
        }

    for file_name, file_obj in request.FILES.items():
        safe_name = os.path.basename(file_name)
        ext = os.path.splitext(safe_name)[1].lower()

        if ext not in allowed_file_types:
            unsupported_files += safe_name + ", "
            continue

        if file_obj.content_type not in allowed_file_types[ext]:
            unsupported_files += safe_name + ", "
            continue

        file_path = os.path.join(UPLOAD_DIR, safe_name)

        if os.path.exists(file_path):
            duplicate_files += safe_name + ", "
            continue

        with open(file_path, "wb") as destination:
            for chunk in file_obj.chunks():
                destination.write(chunk)

        missing_stations = []

        if decoder_format == "default":
            excel_df = pd.ExcelFile(file_path)
            for sheet in excel_df.sheet_names:
                sheet = sheet.strip()

                name_count = Station.objects.filter(name=sheet, is_automatic=False).count()
                alias_count = Station.objects.filter(alias_name=sheet, is_automatic=False).count()

                if not (name_count == 1 or alias_count == 1):
                    missing_stations.append(sheet)

            if missing_stations:
                os.remove(file_path)
                non_existent_stations.append(
                    f"File [{safe_name}] has invalid/ambiguous stations: {', '.join(missing_stations)}"
                )
                continue

        elif decoder_format == "f2000":
            wb = None
            file_f2000_errors = []
            try:
                wb = openpyxl.load_workbook(file_path, data_only=True)

                for sheet in wb.sheetnames:
                    if sheet in ("F2000 Template (ml)", "Sheet 1 (mm)"):
                        continue

                    ws = wb[sheet]

                    try:
                        errors, metadata = f2000_structure_check(ws)
                        metadata = metadata or {}

                        if errors:
                            for msg in errors:
                                file_f2000_errors.append(f"{safe_name} / {sheet}: {msg}")

                        content_errors = f2000_content_check(ws, metadata)
                        if content_errors:
                            for msg in content_errors:
                                file_f2000_errors.append(f"{safe_name} / {sheet}: {msg}")

                        station_name = metadata.get("station_name")
                        if not station_name:
                            file_f2000_errors.append(f"{safe_name} / {sheet}: missing station_name in metadata")
                            continue

                        name_count = Station.objects.filter(name=station_name, is_automatic=False).count()
                        alias_count = Station.objects.filter(alias_name=station_name, is_automatic=False).count()

                        if not (name_count == 1 or alias_count == 1):
                            missing_stations.append(station_name)

                    except Exception as e:
                        file_f2000_errors.append(f"{safe_name} / {sheet}: {repr(e)}")

            except Exception as e:
                file_f2000_errors.append(f"{safe_name}: {repr(e)}")

            finally:
                if wb:
                    wb.close()

            if file_f2000_errors:
                f2000_errors.extend(file_f2000_errors)
                os.remove(file_path)
                continue

            if missing_stations:
                os.remove(file_path)
                non_existent_stations.append(
                    f"File [{safe_name}] has invalid/ambiguous stations: {', '.join(missing_stations)}"
                )
                continue

        # ✅ ONLY files that reach here are valid and still exist
        file_size = round(os.stat(file_path).st_size / (1024 * 1024), 4)
        uploaded_files[safe_name] = file_size

    return JsonResponse(
        {
            "uploaded_files": uploaded_files,
            "duplicate_files": duplicate_files,
            "unsupported_files": unsupported_files,
            "non_existent_stations": non_existent_stations,
            "f2000_errors": f2000_errors,
        },
        status=201,
    )


# remove manual data files
@csrf_exempt
@wx_mapped_permission_required
def RemoveManualDataFile(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            file_name = data.get('file')
            remaining_files = {}
            UPLOAD_DIR = '/data/documents/ingest/manual/check'  #Directory path

            # check if the request it to reset the entire folder
            if file_name == 'reset':
                if os.path.exists(UPLOAD_DIR):  # Check if the directory exists
                    shutil.rmtree(UPLOAD_DIR) # remove the directory
                    logger.info(f"Directory '{UPLOAD_DIR}' deleted. (Prep work for Manual Import)")

                try:
                    os.makedirs(UPLOAD_DIR, exist_ok=True)
                    logger.info(f"Created directory '{UPLOAD_DIR}'.")
                except PermissionError as e:
                    logger.error(f"Permission denied: {e}")
                    return JsonResponse({"error": "Unable to create directory."}, status=500)
                
                return JsonResponse({"uploaded_files": remaining_files}, status=201)

            if not file_name:  # Check if file_name was provided
                return JsonResponse({'error': 'A file name is required'}, status=400)

            file_path = os.path.join(UPLOAD_DIR, file_name)

            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"File removed: {file_path}")

                    # Get updated file list
                    # remaining_files = [f for f in os.listdir(UPLOAD_DIR ) if os.path.isfile(os.path.join(UPLOAD_DIR , f))]
                    for f in os.listdir(UPLOAD_DIR):
                        if os.path.isfile(os.path.join(UPLOAD_DIR , f)):
                            path = os.path.join(UPLOAD_DIR , f)
                            file_size = round(os.stat(path).st_size / (1024), 2)
                            remaining_files[f] = file_size # Store file name and size (size in MB)

                    return JsonResponse({"uploaded_files": remaining_files}, status=201)


                except OSError as e: # Handle potential file system errors
                    logger.error(f"Error removing file: {e}")
                    return JsonResponse({'error': f"Error removing {file_name}"}, status=500) # Internal Server Error

            else:
                return JsonResponse({'error': f'File "{file_name}" not found'}, status=404)  # Not Found

        except Exception as e:
            logger.error(f"Error: {e}")
            logger.info(f"this is the file name: {file_name}")
            # logger.info(f"this is the file name: {file_name}")
            return JsonResponse({'error': 'Invalid request data'}, status=400)

    return JsonResponse({'error': 'Invalid request method'}, status=405)


# process the uploaded manual data files
@csrf_exempt
@wx_mapped_permission_required
def UploadManualDataFile(request):
    UPLOAD_DIR = '/data/documents/ingest/manual/check'  #Upload Directory path
    PROCESS_DIR = '/data/documents/ingest/manual/process'  #Process Directory path 

    try:
        if request.method == "POST":
            data = json.loads(request.body)

            override_data = data.get('override_on_conflict')
            is_manually_validated = data.get('is_manually_validated')
            selected_decoder = data.get('selected_decoder')

            data_file_id_list=[] # holds ManualStationDataFile id's

            # create PROCESS_DIR if it does not exist
            if os.path.exists(UPLOAD_DIR):
                os.makedirs(PROCESS_DIR, exist_ok=True) # create the process dir if it does not exist

                # loop through files in the UPLOAD DIR and create a New ManualStationDataFile object and move the file to the PROCESS DIR
                for filename in os.listdir(UPLOAD_DIR):
                    source_path = os.path.join(UPLOAD_DIR, filename)

                    safe_name = os.path.basename(filename)
                    ext = os.path.splitext(safe_name)[1].lower()

                    # Check if it's a file
                    if os.path.isfile(source_path):
                        # create ManualStationDataFile object
                        new_data_file = ManualStationDataFile.objects.create(file_name=filename, status_id=1, override_data_on_conflict=override_data, is_manually_validated=is_manually_validated)

                        destination_path = os.path.join(PROCESS_DIR, str(new_data_file.id) + ext) # create the destination path based on the file id

                        new_data_file.filepath = destination_path # update the objects file path to be the destination path
                        new_data_file.save()

                        # moving (note that the file name changes)
                        shutil.move(source_path, destination_path)
                        logger.info(f"Moved for manual upload processing: {filename}")

                        data_file_id_list.append(new_data_file.id)

                # call celery task to begin file processing
                tasks.ingest_manual_station_files.delay(data_file_id_list, selected_decoder)
                

            else:
                return JsonResponse({'error': 'Error occured during file upload! There are no files to upload'}, status=400)
            

            return JsonResponse({"success": "success"}, status=202)
        else:
            raise
    except Exception as e:
        logger.error(f"Error: {e}")
        return JsonResponse({'error': 'Error occured during file upload!'}, status=400)



class CountryViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Country.objects.all().order_by("name")
    serializer_class = serializers.CountrySerializer


class UnitViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Unit.objects.all().order_by("name")
    serializer_class = serializers.UnitSerializer


class DataSourceViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = DataSource.objects.all().order_by("name")
    serializer_class = serializers.DataSourceSerializer


class VariableViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Variable.objects.all().order_by("name")
    serializer_class = serializers.VariableSerializer


class StationMetadataViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Station.objects.all()
    serializer_class = serializers.StationMetadataSerializer

    def get_serializer_class(self):
        if self.request.method in ['GET']:
            return serializers.StationSerializerRead
        return serializers.StationMetadataSerializer


class StationViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Station.objects.all()

    # queryset = Station.objects.all().select_related("country").order_by("name")
    # def put(self, request, *args, **kwargs):
    #     station_object = Station.objects.get()
    #     data = request.data

    #     station_object.save()
    # serializer = serializers.StationSerializerWrite
        

    def get_serializer_class(self):
        if self.request.method in ['GET']:
            return serializers.StationSerializerRead

        return serializers.StationSerializerWrite


class StationSimpleViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Station.objects.all()
    serializer_class = serializers.StationSimpleSerializer


class StationVariableViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = StationVariable.objects.all().order_by("variable")
    serializer_class = serializers.StationVariableSerializer

    def get_queryset(self):
        queryset = StationVariable.objects.all()

        station_id = self.request.query_params.get('station_id', None)

        if station_id is not None:
            queryset = queryset.filter(station__id=station_id)

        return queryset


class StationProfileViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = StationProfile.objects.all().order_by("name")
    serializer_class = serializers.StationProfileSerializer



# class DocumentViewSet(views.APIView):
#     permission_classes = (IsAuthenticated,)
#     parser_class = (FileUploadParser,)
#     queryset = Document.objects.all()
#     serializer_class = serializers.DocumentSerializer
#     available_decoders = {'HOBO': read_file_hobo, 'TOA5': read_file_toa5}
#     decoders = Decoder.objects.all().exclude(name='DCP TEXT').exclude(name='NESA')

#     def put(self, request, format=None):
#         selected_decoder = 'TOA5'

#         if 'decoder' in request.data.keys():
#             selected_decoder = request.data['decoder']

#         serializer = serializers.DocumentSerializer(data=request.data)

#         if serializer.is_valid():
#             document = serializer.save()
#             self.available_decoders[selected_decoder].delay(document.file.path)
#             return Response({"message": "FIle uploaded successfully!"}, status=status.HTTP_201_CREATED)

#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

#     def post(self, request, format=None):
#         return self.put(request, format=None)


class AdministrativeRegionViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = AdministrativeRegion.objects.all().order_by("name")
    serializer_class = serializers.AdministrativeRegionSerializer


@api_view(['GET'])
def station_telemetry_data(request, date):
    mock = {
        'temperature': {
            'min': 10,
            'max': 13,
            'avg': 16
        },
        'relativeHumidity': {
            'min': 10,
            'max': 13,
            'avg': 16
        },
        'precipitation': {
            'current': 123
        },
        'windDirection': {
            'current': 'SW'
        },
        'windSpeed': {
            'current': 11,
            'max': 12
        },
        'windGust': {
            'current': 12,
            'max': 11
        },
        'solarRadiation': {
            'current': 12
        },
        'atmosphericPressure': {
            'current': 11
        }
    }

    data = {
        'latest': mock,
        'last24': mock,
        'current': mock,
    }

    return Response(data)


def raw_data_list(request):
    search_type = request.GET.get('search_type', None)
    search_value = request.GET.get('search_value', None)
    search_value2 = request.GET.get('search_value2', None)
    search_date_start = request.GET.get(
        'search_date_start',
        default=(datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
    )
    search_date_end = request.GET.get(
        'search_date_end',
        default=datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    )
    sql_string = ""

    response = {
        'results': [],
        'messages': [],
    }

    try:
        start_date = datetime.datetime.strptime(search_date_start, '%Y-%m-%dT%H:%M:%SZ')
        end_date = datetime.datetime.strptime(search_date_end, '%Y-%m-%dT%H:%M:%SZ')

    except ValueError:
        message = 'Invalid date format. Expected YYYY-MM-DDTHH:MI:SSZ'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    delta = end_date - start_date

    if delta.days > 8:  # Restrict queries to max seven days
        message = 'Interval between start date and end date is greater than one week.'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    if search_type in ['station', 'stationvariable']:
        try:
            station = Station.objects.get(code=search_value)
        except ObjectDoesNotExist:
            station = Station.objects.get(pk=search_value)
        finally:
            search_value = station.id

    if search_type is not None and search_type == 'variable':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   c.name,
                   c.symbol,
                   a.measured,
                   a.datetime,
                   q.symbol as quality_flag,
                   b.variable_type,
                   a.code
            FROM raw_data a
            JOIN wx_variable b ON a.variable_id=b.id
            LEFT JOIN wx_unit c ON b.unit_id=c.id
            JOIN wx_qualityflag q ON a.quality_flag=q.id
        WHERE b.id = %s 
          AND datetime >= %s 
          AND datetime <= %s
        """

    if search_type is not None and search_type == 'station':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   c.name,
                   c.symbol,
                   a.measured,
                   a.datetime,
                   q.symbol as quality_flag,
                   b.variable_type,
                   a.code
            FROM raw_data a
            JOIN wx_variable b ON a.variable_id=b.id
            LEFT JOIN wx_unit c ON b.unit_id=c.id
            JOIN wx_qualityflag q ON a.quality_flag=q.id
            WHERE station_id=%s AND datetime >= %s AND datetime <= %s"""

    if search_type is not None and search_type == 'stationvariable':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   c.name,
                   c.symbol,
                   a.measured,
                   a.datetime,
                   q.symbol as quality_flag,
                   b.variable_type,
                   a.code
            FROM raw_data a
            JOIN wx_variable b ON a.variable_id=b.id
            LEFT JOIN wx_unit c ON b.unit_id=c.id
            JOIN wx_qualityflag q ON a.quality_flag=q.id
            WHERE station_id=%s AND variable_id=%s AND datetime >= %s AND datetime <= %s"""

    if sql_string:
        sql_string += " ORDER BY datetime"

        with connection.cursor() as cursor:

            if search_type is not None and search_type == 'stationvariable':

                cursor.execute(sql_string, [search_value, search_value2, search_date_start, search_date_end])

            else:

                cursor.execute(sql_string, [search_value, search_date_start, search_date_end])

            rows = cursor.fetchall()

            for row in rows:

                if row[9] is not None and row[9].lower() == 'code':
                    value = row[10]
                else:
                    value = round(row[6], 2)

                obj = {
                    'station': row[0],
                    'date': row[7],
                    'value': value,
                    'variable': {
                        'symbol': row[2],
                        'name': row[3],
                        'unit_name': row[4],
                        'unit_symbol': row[5]
                    }
                }

                response['results'].append(obj)

            if response['results']:
                return JsonResponse(response, status=status.HTTP_200_OK)

    return JsonResponse(data={"message": "No data found."}, status=status.HTTP_404_NOT_FOUND)


def hourly_summary_list(request):
    search_type = request.GET.get('search_type', None)
    search_value = request.GET.get('search_value', None)
    search_value2 = request.GET.get('search_value2', None)
    search_date_start = request.GET.get(
        'search_date_start',
        default=(datetime.datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    )
    search_date_end = request.GET.get(
        'search_date_end',
        default=datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    )
    sql_string = ""

    response = {
        'results': [],
        'messages': [],
    }

    try:
        start_date = datetime.datetime.strptime(search_date_start, '%Y-%m-%dT%H:%M:%SZ')
        end_date = datetime.datetime.strptime(search_date_end, '%Y-%m-%dT%H:%M:%SZ')

    except ValueError:
        message = 'Invalid date format. Expected YYYY-MM-DDTHH:MI:SSZ'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    delta = end_date - start_date

    if delta.days > 32:  # Restrict queries to max 31 days
        message = 'Interval between start date and end date is greater than one month.'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    if search_type in ['station', 'stationvariable']:
        try:
            station = Station.objects.get(code=search_value)
        except ObjectDoesNotExist:
            station = Station.objects.get(pk=search_value)
        finally:
            search_value = station.id

    if search_type is not None and search_type == 'variable':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   b.sampling_operation_id,
                   c.name,
                   c.symbol,
                   min_value,
                   max_value,
                   avg_value,
                   sum_value,
                   num_records,
                   datetime as data
              FROM hourly_summary a
        INNER JOIN wx_variable b ON a.variable_id=b.id
        INNER JOIN wx_unit c ON b.unit_id=c.id
        WHERE b.id=%s AND datetime >= %s AND datetime <= %s"""

    if search_type is not None and search_type == 'station':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   b.sampling_operation_id,
                   c.name,
                   c.symbol,
                   min_value,
                   max_value,
                   avg_value,
                   sum_value,
                   num_records,
                   datetime as data
              FROM hourly_summary a
        INNER JOIN wx_variable b ON a.variable_id=b.id
        INNER JOIN wx_unit c ON b.unit_id=c.id
             WHERE station_id=%s AND datetime >= %s AND datetime <= %s"""

    if search_type is not None and search_type == 'stationvariable':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   b.sampling_operation_id,
                   c.name,
                   c.symbol,
                   min_value,
                   max_value,
                   avg_value,
                   sum_value,
                   num_records,
                   datetime as data
              FROM hourly_summary a
        INNER JOIN wx_variable b ON a.variable_id=b.id
        INNER JOIN wx_unit c ON b.unit_id=c.id
             WHERE station_id=%s AND variable_id=%s AND datetime >= %s AND datetime <= %s"""

    if sql_string:
        sql_string += " ORDER BY datetime"

        with connection.cursor() as cursor:

            if search_type is not None and search_type == 'stationvariable':

                cursor.execute(sql_string, [search_value, search_value2, search_date_start, search_date_end])

            else:

                cursor.execute(sql_string, [search_value, search_date_start, search_date_end])

            rows = cursor.fetchall()

            for row in rows:

                value = None

                if row[4] in [1, 2]:
                    value = row[9]

                elif row[4] == 3:
                    value = row[7]

                elif row[4] == 4:
                    value = row[8]

                elif row[4] == 6:
                    value = row[10]

                else:
                    value = row[10]

                if value is None:

                    print('variable {} does not have supported sampling operation {}'.format(row[1], row[4]))

                else:

                    obj = {
                        'station': row[0],
                        'date': row[12],
                        'value': round(value, 2),
                        'min': round(row[7], 2),
                        'max': round(row[8], 2),
                        'avg': round(row[9], 2),
                        'sum': round(row[10], 2),
                        'count': round(row[11], 2),
                        'variable': {
                            'symbol': row[2],
                            'name': row[3],
                            'unit_name': row[5],
                            'unit_symbol': row[6],
                        }
                    }

                    response['results'].append(obj)

            if response['results']:
                return JsonResponse(response, status=status.HTTP_200_OK)

    return JsonResponse(data=response)


def daily_summary_list(request):
    search_type = request.GET.get('search_type', None)
    search_value = request.GET.get('search_value', None)
    search_value2 = request.GET.get('search_value2', None)
    search_date_start = request.GET.get(
        'search_date_start',
        default=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    )
    search_date_end = request.GET.get(
        'search_date_end',
        default=datetime.datetime.now().strftime('%Y-%m-%d')
    )
    sql_string = ""

    response = {
        'results': [],
        'messages': [],
    }

    try:
        start_date = datetime.datetime.strptime(search_date_start, '%Y-%m-%d')
        end_date = datetime.datetime.strptime(search_date_end, '%Y-%m-%d')

    except ValueError:
        message = 'Invalid date format. Expected YYYY-MM-DD'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    delta = end_date - start_date

    if delta.days > 400:  # Restrict queries to max 400 days
        message = 'Interval between start date and end date is greater than 13 months.'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    if search_type in ['station', 'stationvariable']:
        try:
            station = Station.objects.get(code=search_value)
        except ObjectDoesNotExist:
            station = Station.objects.get(pk=search_value)
        finally:
            search_value = station.id

    if search_type is not None and search_type == 'variable':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   b.sampling_operation_id,
                   c.name,
                   c.symbol,
                   min_value,
                   max_value,
                   avg_value,
                   sum_value,
                   day,
                   num_records
              FROM daily_summary a
        INNER JOIN wx_variable b ON a.variable_id=b.id
        INNER JOIN wx_unit c ON b.unit_id=c.id
        WHERE b.id = %s 
          AND day >= %s 
          AND day <= %s"""

    if search_type is not None and search_type == 'station':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   b.sampling_operation_id,
                   c.name,
                   c.symbol,
                   min_value,
                   max_value,
                   avg_value,
                   sum_value,
                   day,
                   num_records
              FROM daily_summary a
        INNER JOIN wx_variable b ON a.variable_id=b.id
        INNER JOIN wx_unit c ON b.unit_id=c.id
             WHERE station_id=%s AND day >= %s AND day <= %s"""

    if search_type is not None and search_type == 'stationvariable':
        sql_string = """
            SELECT station_id,
                   variable_id,
                   b.symbol,
                   b.name,
                   b.sampling_operation_id,
                   c.name,
                   c.symbol,
                   min_value,
                   max_value,
                   avg_value,
                   sum_value,
                   day,
                   num_records
              FROM daily_summary a
        INNER JOIN wx_variable b ON a.variable_id=b.id
        INNER JOIN wx_unit c ON b.unit_id=c.id
             WHERE station_id=%s AND variable_id=%s AND day >= %s AND day <= %s"""

    if sql_string:
        sql_string += " ORDER BY day"

        with connection.cursor() as cursor:

            if search_type is not None and search_type == 'stationvariable':
                cursor.execute(sql_string, [search_value, search_value2, search_date_start, search_date_end])
            else:
                cursor.execute(sql_string, [search_value, search_date_start, search_date_end])

            rows = cursor.fetchall()

            for row in rows:

                value = None

                if row[4] in [1, 2]:
                    value = row[9]

                elif row[4] == 3:
                    value = row[7]

                elif row[4] == 4:
                    value = row[8]

                elif row[4] == 6:
                    value = row[10]

                else:
                    value = row[10]

                if value is not None:

                    obj = {
                        'station': row[0],
                        'date': row[11],
                        'value': round(value, 2),
                        'min': round(row[7], 2),
                        'max': round(row[8], 2),
                        'avg': round(row[9], 2),
                        'total': round(row[10], 2),
                        'count': row[12],
                        'variable': {
                            'symbol': row[2],
                            'name': row[3],
                            'unit_name': row[5],
                            'unit_symbol': row[6],
                        }
                    }

                    response['results'].append(obj)

                else:
                    JsonResponse(data={
                        "message": 'variable {} does not have supported sampling operation {}'.format(row[1], row[4])},
                        status=status.HTTP_400_BAD_REQUEST)

            if response['results']:
                return JsonResponse(response, status=status.HTTP_200_OK)

    return JsonResponse(data=response)


def monthly_summary_list(request):
    search_type = request.GET.get('search_type', None)
    search_value = request.GET.get('search_value', None)
    search_value2 = request.GET.get('search_value2', None)
    search_date_start = request.GET.get(
        'search_date_start',
        default=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    )
    search_date_end = request.GET.get(
        'search_date_end',
        default=datetime.datetime.now().strftime('%Y-%m-%d')
    )

    sql_string = ""

    response = {
        'count': -999,
        'next': None,
        'previous': None,
        'results': []
    }

    try:
        start_date = datetime.datetime.strptime(search_date_start, '%Y-%m-%d')
        end_date = datetime.datetime.strptime(search_date_end, '%Y-%m-%d')

    except ValueError:
        message = 'Invalid date format. Expected YYYY-MM-DD'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    if search_type in ['station', 'stationvariable']:
        try:
            station = Station.objects.get(code=search_value)
        except ObjectDoesNotExist:
            station = Station.objects.get(pk=search_value)
        finally:
            search_value = station.id

    if search_type is not None and search_type == 'variable':
        sql_string = """
            SELECT  station_id,
                    variable_id,
                    b.symbol,
                    b.name,
                    b.sampling_operation_id,
                    c.name,
                    c.symbol,
                    min_value,
                    max_value,
                    avg_value,
                    sum_value,
                    date::date,
                    num_records
            FROM monthly_summary a
            JOIN wx_variable b ON a.variable_id=b.id 
            JOIN wx_unit c ON b.unit_id=c.id 
            WHERE b.id = %s
              AND date >= %s 
              AND date <= %s
        """

    if search_type is not None and search_type == 'station':
        sql_string = """
            SELECT  station_id,
                    variable_id,
                    b.symbol, 
                    b.name, 
                    b.sampling_operation_id,
                    c.name, 
                    c.symbol, 
                    min_value,
                    max_value,
                    avg_value,
                    sum_value,
                    date::date,
                    num_records
            FROM monthly_summary a 
            JOIN wx_variable b ON a.variable_id=b.id
            JOIN wx_unit c ON b.unit_id=c.id 
            WHERE station_id = %s 
              AND date >= %s AND date <= %s
        """

    if search_type is not None and search_type == 'stationvariable':
        sql_string = """
            SELECT  station_id,
                    variable_id,
                    b.symbol, 
                    b.name, 
                    b.sampling_operation_id,
                    c.name, 
                    c.symbol, 
                    min_value,
                    max_value,
                    avg_value,
                    sum_value,
                    date::date,
                    num_records
            FROM monthly_summary a 
            JOIN wx_variable b ON a.variable_id=b.id
            JOIN wx_unit c ON b.unit_id=c.id 
            WHERE station_id = %s 
              AND variable_id = %s
              AND date >= %s AND date <= %s
        """

    if sql_string:
        sql_string += " ORDER BY month"

        with connection.cursor() as cursor:

            if search_type is not None and search_type == 'stationvariable':
                cursor.execute(sql_string, [search_value, search_value2, start_date, end_date])
            else:
                cursor.execute(sql_string, [search_value, start_date, end_date])

            rows = cursor.fetchall()

            for row in rows:

                value = None

                if row[4] in [1, 2]:
                    value = row[9]

                elif row[4] == 3:
                    value = row[7]

                elif row[4] == 4:
                    value = row[8]

                elif row[4] == 6:
                    value = row[10]

                else:
                    value = row[10]

                if value is not None:

                    obj = {
                        'station': row[0],
                        'date': row[11],
                        'value': round(value, 2),
                        'min': round(row[7], 2),
                        'max': round(row[8], 2),
                        'avg': round(row[9], 2),
                        'total': round(row[10], 2),
                        'count': row[12],
                        'variable': {
                            'symbol': row[2],
                            'name': row[3],
                            'unit_name': row[5],
                            'unit_symbol': row[6],
                        }
                    }

                    response['results'].append(obj)

                else:
                    JsonResponse(data={
                        "message": 'variable {} does not have supported sampling operation {}'.format(row[1], row[4])},
                        status=status.HTTP_400_BAD_REQUEST)

            if response['results']:
                return JsonResponse(response, status=status.HTTP_200_OK)

    return JsonResponse(data=response)


def yearly_summary_list(request):
    search_type = request.GET.get('search_type', None)
    search_value = request.GET.get('search_value', None)
    search_value2 = request.GET.get('search_value2', None)
    search_date_start = request.GET.get(
        'search_date_start',
        default=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    )
    search_date_end = request.GET.get(
        'search_date_end',
        default=datetime.datetime.now().strftime('%Y-%m-%d')
    )

    sql_string = ""

    response = {
        'count': -999,
        'next': None,
        'previous': None,
        'results': []
    }

    try:
        start_date = datetime.datetime.strptime(search_date_start, '%Y-%m-%d')
        end_date = datetime.datetime.strptime(search_date_end, '%Y-%m-%d')

    except ValueError:
        message = 'Invalid date format. Expected YYYY-MM-DD'
        return JsonResponse(data={"message": message}, status=status.HTTP_400_BAD_REQUEST)

    if search_type in ['station', 'stationvariable']:
        try:
            station = Station.objects.get(code=search_value)
        except ObjectDoesNotExist:
            station = Station.objects.get(pk=search_value)
        finally:
            search_value = station.id

    if search_type is not None and search_type == 'variable':
        sql_string = """
            SELECT  station_id,
                    variable_id,
                    b.symbol,
                    b.name,
                    b.sampling_operation_id,
                    c.name,
                    c.symbol,
                    min_value,
                    max_value,
                    avg_value,
                    sum_value,
                    date::date,
                    num_records
            FROM yearly_summary a
            JOIN wx_variable b ON a.variable_id=b.id 
            JOIN wx_unit c ON b.unit_id=c.id 
            WHERE b.id = %s
              AND date >= %s 
              AND date <= %s
        """

    if search_type is not None and search_type == 'station':
        sql_string = """
            SELECT  station_id,
                    variable_id,
                    b.symbol, 
                    b.name, 
                    b.sampling_operation_id,
                    c.name, 
                    c.symbol, 
                    min_value,
                    max_value,
                    avg_value,
                    sum_value,
                    date::date,
                    num_records
            FROM yearly_summary a 
            JOIN wx_variable b ON a.variable_id=b.id
            JOIN wx_unit c ON b.unit_id=c.id 
            WHERE station_id = %s 
              AND date >= %s AND date <= %s
        """

    if search_type is not None and search_type == 'stationvariable':
        sql_string = """
            SELECT  station_id,
                    variable_id,
                    b.symbol, 
                    b.name, 
                    b.sampling_operation_id,
                    c.name, 
                    c.symbol, 
                    min_value,
                    max_value,
                    avg_value,
                    sum_value,
                    date::date,
                    num_records
            FROM yearly_summary a 
            JOIN wx_variable b ON a.variable_id=b.id
            JOIN wx_unit c ON b.unit_id=c.id 
            WHERE station_id = %s 
              AND variable_id = %s
              AND date >= %s AND date <= %s
        """

    if sql_string:
        sql_string += " ORDER BY year"

        with connection.cursor() as cursor:

            if search_type is not None and search_type == 'stationvariable':
                cursor.execute(sql_string, [search_value, search_value2, start_date, end_date])
            else:
                cursor.execute(sql_string, [search_value, start_date, end_date])

            rows = cursor.fetchall()

            for row in rows:

                value = None

                if row[4] in [1, 2]:
                    value = row[9]

                elif row[4] == 3:
                    value = row[7]

                elif row[4] == 4:
                    value = row[8]

                elif row[4] == 6:
                    value = row[10]

                else:
                    value = row[10]

                if value is not None:

                    obj = {
                        'station': row[0],
                        'date': row[11],
                        'value': round(value, 2),
                        'min': round(row[7], 2),
                        'max': round(row[8], 2),
                        'avg': round(row[9], 2),
                        'total': round(row[10], 2),
                        'count': row[12],
                        'variable': {
                            'symbol': row[2],
                            'name': row[3],
                            'unit_name': row[5],
                            'unit_symbol': row[6],
                        }
                    }

                    response['results'].append(obj)

                else:
                    JsonResponse(data={
                        "message": 'variable {} does not have supported sampling operation {}'.format(row[1], row[4])},
                        status=status.HTTP_400_BAD_REQUEST)

            if response['results']:
                return JsonResponse(response, status=status.HTTP_200_OK)

    return JsonResponse(data=response)


@api_view(['GET'])
def station_geo_features(request, lon, lat):
    longitude = float(lon)
    latitude = float(lat)

    altitude = get_altitude(longitude, latitude)

    watershed = get_watershed(longitude, latitude)

    district = get_district(longitude, latitude)

    data = {
        'elevation': altitude,
        'watershed': watershed,
        'country': 'Belize',
        'administrative_region': district,
        'longitude': longitude,
        'latitude': latitude,
    }

    return Response(data)


def get_last24_data(station_id):
    result = []
    max_date = None

    query = """
        SELECT
            last24h.datetime,
            var.name,
            var.symbol,
            var.sampling_operation_id,
            unit.name,
            unit.symbol,
            last24h.min_value,
            last24h.max_value,
            last24h.avg_value,
            last24h.sum_value,
            last24h.latest_value
        FROM
            last24h_summary last24h
        INNER JOIN
            wx_variable var ON last24h.variable_id=var.id
        INNER JOIN
            wx_unit unit ON var.unit_id=unit.id
        WHERE
            last24h.station_id=%s
        ORDER BY var.name"""

    with connection.cursor() as cursor:

        cursor.execute(query, [station_id])

        rows = cursor.fetchall()

        for row in rows:

            value = None

            if row[3] == 1:
                value = row[10]

            elif row[3] == 2:
                value = row[8]

            elif row[3] == 3:
                value = row[6]

            elif row[3] == 4:
                value = row[7]

            elif row[3] == 6:
                value = row[9]

            if value is None:
                print('variable {} does not have supported sampling operation {}'.format(row[1], row[3]))

            obj = {
                'value': value,
                'variable': {
                    'name': row[1],
                    'symbol': row[2],
                    'unit_name': row[4],
                    'unit_symbol': row[5]
                }
            }
            result.append(obj)

        max_date = cache.get('last24h_summary_last_run', None)

    return result, max_date


def get_latest_data(station_id):
    result = []
    max_date = None

    query = """
        SELECT CASE WHEN var.variable_type ilike 'code' THEN latest.last_data_code ELSE latest.last_data_value::varchar END as value,
               latest.last_data_datetime,
               var.name,
               var.symbol,
               unit.name,
               unit.symbol
        FROM wx_stationvariable latest
        INNER JOIN wx_variable var ON latest.variable_id=var.id
        LEFT JOIN wx_unit unit ON var.unit_id=unit.id
        WHERE latest.station_id=%s 
          AND latest.last_data_value is not null
          AND latest.last_data_datetime = ( SELECT MAX(most_recent.last_data_datetime)
                                            FROM wx_stationvariable most_recent
                                            WHERE most_recent.station_id=latest.station_id 
                                                AND most_recent.last_data_value is not null)
        ORDER BY var.name
        """

    with connection.cursor() as cursor:

        cursor.execute(query, [station_id])

        rows = cursor.fetchall()

        for row in rows:
            obj = {
                'value': row[0],
                'variable': {
                    'name': row[2],
                    'symbol': row[3],
                    'unit_name': row[4],
                    'unit_symbol': row[5]
                }
            }
            result.append(obj)

        if rows:
            max_date = rows[-1][1]

    return result, max_date


def get_current_data(station_id):
    result = []
    max_date = None
    parameter_timezone = pytz.timezone(settings.TIMEZONE_NAME)
    today = datetime.datetime.now().astimezone(parameter_timezone).date()

    query = """
        SELECT current.day,
               var.name,
               var.symbol,
               var.sampling_operation_id,
               unit.name,
               unit.symbol,
               current.min_value,
               current.max_value,
               current.avg_value,
               current.sum_value
        FROM daily_summary current
        INNER JOIN wx_variable var ON current.variable_id=var.id
        INNER JOIN wx_unit unit ON var.unit_id=unit.id
        WHERE current.station_id=%s and current.day=%s
        ORDER BY current.day, var.name
    """

    with connection.cursor() as cursor:

        cursor.execute(query, [station_id, today])

        rows = cursor.fetchall()

        for row in rows:

            value = None

            if row[3] in (1, 2):
                value = row[8]

            elif row[3] == 3:
                value = row[6]

            elif row[3] == 4:
                value = row[7]

            elif row[3] == 6:
                value = row[9]

            if value is None:
                print('variable {} does not have supported sampling operation {}'.format(row[1], row[3]))

            obj = {
                'value': value,
                'variable': {
                    'name': row[1],
                    'symbol': row[2],
                    'unit_name': row[4],
                    'unit_symbol': row[5]
                }
            }
            result.append(obj)

        max_date = cache.get('daily_summary_last_run', None)

    return result, max_date


@api_view(['GET'])
def livedata(request, code):
    try:
        station = Station.objects.get(code=code)
    except ObjectDoesNotExist as e:
        station = Station.objects.get(pk=code)
    finally:
        id = station.id

    past24h_data, past24h_max_date = get_last24_data(station_id=id)
    latest_data, latest_max_date = get_latest_data(station_id=id)
    current_data, current_max_date = get_current_data(station_id=id)

    station_data = serializers.StationSerializerRead(station).data

    return Response(
        {
            'station': station_data,
            'station_name': station.name,
            'station_id': station.id,
            'past24h': past24h_data,
            'past24h_last_update': past24h_max_date,
            'latest': latest_data,
            'latest_last_update': latest_max_date,
            'currentday': current_data,
            'currentday_last_update': current_max_date,
        }
        , status=status.HTTP_200_OK)


class WatershedList(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.WatershedSerializer
    queryset = Watershed.objects.all().order_by("watershed")


class StationCommunicationList(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.StationCommunicationSerializer
    queryset = StationCommunication.objects.all()


class DecoderList(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.DecoderSerializer
    queryset = Decoder.objects.all().order_by("name")


class QualityFlagList(viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.QualityFlagSerializer
    queryset = QualityFlag.objects.all().order_by("name")


@wx_mapped_permission_required
def qc_list(request):
    if request.method == 'GET':
        station_id = request.GET.get('station_id', None)
        variable_id = request.GET.get('variable_id', None)
        start_date = request.GET.get('start_date', None)
        end_date = request.GET.get('end_date', None)
        is_automatic_raw = request.GET.get('is_automatic', None)

        if station_id is None:
            return JsonResponse(data={"message": "'station_id' parameter cannot be null."}, status=status.HTTP_400_BAD_REQUEST)

        if variable_id is None:
            return JsonResponse(data={"message": "'variable_id' parameter cannot be null."},
                         status=status.HTTP_400_BAD_REQUEST)
        
        # ------------------------------------------------------------------
        # Validate is_automatic flag (controls allowed date range)
        # ------------------------------------------------------------------
        if is_automatic_raw is None:
            # Frontend must explicitly tell us whether the station is automatic
            return JsonResponse({"message": "'Automatic' parameter cannot be null."},
                                status=status.HTTP_400_BAD_REQUEST)

        # Normalize input (e.g. "True", "FALSE" -> "true"/"false")
        is_automatic = is_automatic_raw.strip().lower()

        # Only allow explicit boolean strings
        if is_automatic not in ("true", "false"):
            return JsonResponse({"message": "'Automatic' must be 'true' or 'false'."},
                                status=status.HTTP_400_BAD_REQUEST)

        # Automatic stations (AWS) → max 7 days
        # Manual stations → max 30 days
        limit_days = 7 if is_automatic == "true" else 30

        station_type = "Automatic" if is_automatic == "true" else "Manual"

        # ------------------------------------------------------------------
        # Require BOTH start_date and end_date (prevents accidental huge scans)
        # ------------------------------------------------------------------
        if (start_date and not end_date) or (end_date and not start_date):
            return JsonResponse({"message": "Both start date and end date are required."},
                                status=status.HTTP_400_BAD_REQUEST)

        # ------------------------------------------------------------------
        # Parse dates expected format: YYYY-MM-DD
        # ------------------------------------------------------------------
        start_dt = parse_datetime(start_date) if start_date else None
        end_dt = parse_datetime(end_date) if end_date else None

        # Invalid date formats
        if start_date and start_dt is None:
            return JsonResponse({"message": "Invalid start date format. Use YYYY-MM-DD."},
                                status=status.HTTP_400_BAD_REQUEST)

        if end_date and end_dt is None:
            return JsonResponse({"message": "Invalid end date format. Use YYYY-MM-DD."},
                                status=status.HTTP_400_BAD_REQUEST)


        # ------------------------------------------------------------------
        # Validate date ordering + enforce allowed range
        # ------------------------------------------------------------------
        if start_dt and end_dt:

            # End date must not be before start date
            if end_dt < start_dt:
                return JsonResponse({"message": "end date must be >= start date."},
                                    status=status.HTTP_400_BAD_REQUEST)

            # Inclusive day count (e.g. Feb 1 → Feb 7 = 7 days, not 6)
            inclusive_days = (end_dt - start_dt).days + 1

            # Enforce station-specific maximum window
            if inclusive_days > limit_days:
                return JsonResponse(
                    {
                        "message": f"Date range too large. Max allowed is {limit_days} days for {station_type} stations."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        sql_string = ""
        where_parameters = [station_id, variable_id]

        response = {
            'count': -999,
            'next': None,
            'previous': None,
            'results': []
        }

        sql_string = """SELECT value.datetime
                            ,value.measured
                            ,value.consisted
                            ,value.quality_flag
                            ,value.manual_flag
                            ,value.station_id
                            ,value.variable_id
                            ,value.remarks
                            ,value.qc_range_quality_flag
                            ,value.qc_step_quality_flag
                            ,value.qc_persist_quality_flag
                        FROM raw_data as value
                        WHERE value.station_id=%s
                        AND value.variable_id=%s
                    """

        if start_date is not None and end_date is not None:
            where_parameters.append(start_date)
            where_parameters.append(end_date)
            sql_string += " AND value.datetime >= %s AND value.datetime <= %s"

        elif start_date is not None:
            where_parameters.append(start_date)
            sql_string += " AND value.datetime >= %s"

        elif end_date is not None:
            where_parameters.append(end_date)
            sql_string += " AND value.datetime <= %s "

        sql_string += " ORDER BY value.datetime "


        task = tasks.get_qc_data.delay(sql_string, where_parameters, response)

        return JsonResponse({"task_id": task.id})

    if request.method == "PATCH":
        station_id = request.GET.get("station_id")
        variable_id = request.GET.get("variable_id")
        req_datetime = request.GET.get("datetime")

        if station_id is None:
            return JsonResponse({"message": "'station_id' parameter cannot be null."},
                                status=status.HTTP_400_BAD_REQUEST)
        if variable_id is None:
            return JsonResponse({"message": "'variable_id' parameter cannot be null."},
                                status=status.HTTP_400_BAD_REQUEST)
        if req_datetime is None:
            return JsonResponse({"message": "'datetime' parameter cannot be null."},
                                status=status.HTTP_400_BAD_REQUEST)

        try:
            station_id = int(station_id)
            variable_id = int(variable_id)
            req_datetime = datetime.datetime.strptime(req_datetime, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            return JsonResponse({"message": "Invalid parameter type."},
                                status=status.HTTP_400_BAD_REQUEST)

        body = json.loads(request.body.decode("utf-8"))
        set_parts = []
        params = []

        updates = {}

        if "manual_flag" in body:
            try:
                updates["manual_flag"] = parse_int_value(body["manual_flag"])
            except ValueError:
                return JsonResponse({"message": "Wrong manual flag value type."},
                                    status=status.HTTP_400_BAD_REQUEST)

        if "consisted" in body:
            try:
                updates["consisted"] = parse_float_value(body["consisted"])
            except ValueError:
                return JsonResponse({"message": "Wrong consisted value type. Please enter a float value."},
                                    status=status.HTTP_400_BAD_REQUEST)

        if "remarks" in body:
            updates["remarks"] = body["remarks"]

        if not updates:
            return JsonResponse({"message": "You must send 'manual_flag', 'consisted' or 'remarks' data to update."},
                                status=status.HTTP_400_BAD_REQUEST)

        task = tasks.qc_manual_checks.delay(
            station_id=station_id,
            variable_id=variable_id,
            req_datetime=req_datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
            updates=updates,
        )

        return JsonResponse({"task_id": task.id})

    return JsonResponse({'message': 'Only the GET and PATCH methods is allowed.'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@wx_mapped_permission_required
def get_qc_description(request):
    station_id = request.GET.get("station_id")
    variable_id = request.GET.get("variable_id")
    date_value = request.GET.get("datetime")

    # -------------------------
    # Validation
    # -------------------------
    if station_id is None:
        return JsonResponse(
            {"message": "'Station Id' parameter cannot be null."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if variable_id is None:
        return JsonResponse(
            {"message": "'Variable Id' parameter cannot be null."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if date_value is None:
        return JsonResponse(
            {"message": "'Datetime' parameter cannot be null."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        station_id = int(station_id)
        variable_id = int(variable_id)
        utc_dt = datetime.datetime.fromisoformat(date_value)
    except ValueError:
        return JsonResponse(
            {"message": "Invalid station_id, variable_id, or datetime format."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # reject naive datetimes as we should be recieving utc times
    if utc_dt.tzinfo is None:
        return JsonResponse(
            {"message": "Datetime must NOT be naive."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # -------------------------
    # Query (TEXT columns only)
    # -------------------------
    sql = """
        SELECT
            qc_range_description,
            qc_step_description,
            qc_persist_description
        FROM raw_data
        WHERE station_id = %s
          AND variable_id = %s
          AND datetime = %s
        LIMIT 1
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, [station_id, variable_id, utc_dt])
        row = cursor.fetchone()

    if row is None:
        return JsonResponse(
            {"message": "No QC description found for the given parameters."},
            # {"message": f"station_id: {station_id}, variable_id: {variable_id}, datetime: {utc_dt}"},
            status=status.HTTP_404_NOT_FOUND
        )

    # -------------------------
    # Response
    # -------------------------
    return JsonResponse(
        {
            "station_id": station_id,
            "variable_id": variable_id,
            "datetime": utc_dt.isoformat(),
            "qc_range_description": row[0],
            "qc_step_description": row[1],
            "qc_persist_description": row[2],
        },
        status=status.HTTP_200_OK
    )


@wx_mapped_permission_required
def qc_validate_bulk(request):
    if request.method != "PATCH":
        return JsonResponse({"message": "Only the PATCH method is allowed."},
                            status=status.HTTP_400_BAD_REQUEST)

    # get station and variable ids and check them
    station_id = request.GET.get("station_id")
    variable_id = request.GET.get("variable_id")

    if station_id is None:
        return JsonResponse({"message": "'Station Id' parameter cannot be null."},
                            status=status.HTTP_400_BAD_REQUEST)
    if variable_id is None:
        return JsonResponse({"message": "'Variable Id' parameter cannot be null."},
                            status=status.HTTP_400_BAD_REQUEST)

    try:
        station_id = int(station_id)
        variable_id = int(variable_id)
    except ValueError:
        return JsonResponse({"message": "Invalid Station Id or Variable Id."},
                            status=status.HTTP_400_BAD_REQUEST)

    # Body JSON
    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"message": "Invalid JSON body."},
                            status=status.HTTP_400_BAD_REQUEST)

    manual_flag = body.get("manual_flag")
    remarks = body.get("remarks", "")
    datetime_list = body.get("datetime_list")

    if manual_flag is None:
        return JsonResponse({"message": "'Manual Flag' cannot be null."},
                            status=status.HTTP_400_BAD_REQUEST)
    if datetime_list is None or not isinstance(datetime_list, list) or len(datetime_list) == 0:
        return JsonResponse({"message": "'Datetime List' must be a non-empty list."},
                            status=status.HTTP_400_BAD_REQUEST)

    try:
        manual_flag = int(manual_flag)
        remarks = str(remarks)
    except ValueError:
        return JsonResponse({"message": "Invalid manual_flag or remarks."},
                            status=status.HTTP_400_BAD_REQUEST)

    req_datetime_list = []

    # Normalize/validate datetimes
    for dt_str in datetime_list:
        try:
            dt = datetime.datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc
            )
            # send ISO Z back to Celery (string, not datetime)
            req_datetime_list.append(dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            return JsonResponse({"message": f"Invalid datetime format: {dt_str}"},
                                status=status.HTTP_400_BAD_REQUEST)

    task = tasks.qc_manual_checks_bulk.delay(
        station_id=station_id,
        variable_id=variable_id,
        manual_flag=manual_flag,
        remarks=remarks,
        datetime_list=req_datetime_list,
    )

    return JsonResponse({"task_id": task.id}, status=status.HTTP_200_OK)

@csrf_exempt
def interpolate_endpoint(request):
    request_date = request.GET.get('request_date', None)
    variable_id = request.GET.get('variable_id', None)
    data_type = request.GET.get('data_type', None)

    sql_string = ''
    where_parameters = [variable_id, request_date]

    if data_type == 'daily':
        sql_string = """
            SELECT station.latitude
                ,station.longitude
                ,daily.avg_value
            FROM daily_summary as daily
            INNER JOIN wx_station as station ON daily.station_id=station.id
            WHERE daily.variable_id=%s and daily.day=%s
            ORDER BY daily.day
        """

    elif data_type == 'hourly':

        sql_string = """
            SELECT station.latitude
                  ,station.longitude
                  ,hourly.avg_value
            FROM hourly_summary as hourly
            INNER JOIN wx_station as station ON hourly.station_id=station.id
            WHERE hourly.variable_id=%s and hourly.datetime=%s
            ORDER BY hourly.datetime
        """

    elif data_type == 'monthly':
        sql_string = """
            SELECT station.latitude
                  ,station.longitude
                  ,monthly.avg_value
            FROM monthly_summary as monthly
            INNER JOIN wx_station as station ON monthly.station_id=station.id
            WHERE monthly.variable_id=%s and to_date(concat(lpad(monthly.year::varchar(4),4,'0'), lpad(monthly.month::varchar(2),2,'0'), '01'), 'YYYYMMDD')=date_trunc('month',TIMESTAMP %s)
            ORDER BY monthly.year, monthly.month
        """

    if sql_string and where_parameters:
        query_result = []
        with connection.cursor() as cursor:
            cursor.execute(sql_string, where_parameters)
            rows = cursor.fetchall()

            for row in rows:
                obj = {
                    'station__latitude': row[0],
                    'station__longitude': row[1],
                    'value': row[2],
                }

                query_result.append(obj)

            if not query_result:
                return JsonResponse({'message': 'No data found.'}, status=status.HTTP_400_BAD_REQUEST)

            return HttpResponse(get_interpolation_image(query_result), content_type="image/jpeg")

    return JsonResponse({'message': 'Missing parameters.'}, status=status.HTTP_400_BAD_REQUEST)


class StationOscarExportView(WxPermissionRequiredMixin, LoginRequiredMixin, ListView):
    model = Station

    template_name = 'wx/station_oscar_export.html'

    def get_queryset(self):
        # filter out all stations which don't have a wigos, wmo_region, reporting_status, wmo_station_type
        oscar_stations = Station.objects.filter(
                                                wigos__isnull=False,
                                                wmo_region__isnull=False,
                                                reporting_status__isnull=False,
                                                wmo_station_type__isnull=False
                                            )
        
        # filter out all stations which are already in OSCAR into a list
        # export_ready_stations = [obj for obj in oscar_stations if not exso.check_station(obj.wigos, pyoscar.OSCARClient())]

        # extract primary keys of the filtered objects
        # filtered_ids = [obj.id for obj in export_ready_stations]
        filtered_ids = [obj.id for obj in oscar_stations]

        # convert filtered list back to a queryset
        filtered_queryset = Station.objects.filter(id__in=filtered_ids)

        return filtered_queryset
    

    def post(self, request, *args, **kwargs):

        try:
            # run station export task
            oscar_status_msg = export_station_to_oscar(request)

            # run slight text formating on the status messages
            for station_info in oscar_status_msg:
                if station_info.get('logs'):
                    station_info['logs'] = station_info['logs'].replace('\n', '<br/>')

                elif station_info.get('description'):
                    station_info['description'] = station_info['description'].replace('\n', '<br/>')

            # get the names of the stations with status messages
            status_station_names = list(Station.objects.filter(wigos__in=request.POST.getlist('selected_ids[]')).values_list('name', flat=True))

            response_data = {
                'success': True,
                'oscar_status_msg': oscar_status_msg,
                'status_station_names': status_station_names,
            }

        except Exception as e:
            response_data = {
                'success': False,
                'oscar_status_msg': [{'code': 406, 'description': 'An error occured when attempting to add stations to OSCAR'}],
                'message': f'An error occured when attempting to add stations to OSCAR: {e}',
            }
            
        return JsonResponse(response_data)

    
class StationListView(WxPermissionRequiredMixin, LoginRequiredMixin, ListView):
    model = Station
    queryset = Station.objects.exclude(is_reference=True)
    


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationDetailView(LoginRequiredMixin, DetailView):
    model = Station
    template_name = 'wx/station_detail.html'  # Use the appropriate template
    context_object_name = 'station'

    # Define the same layout as in the UpdateView
    layout = Layout(
        Fieldset('Station Information',
                 Row('latitude', 'longitude'),
                 Row('name', 'alias_name'),
                 Row('code', 'wigos'),
                 Row('begin_date', 'end_date', 'relocation_date'),
                 Row('wmo', 'reporting_status'),
                 Row('is_active', 'is_automatic', 'is_synoptic', 'international_exchange'),
                 Row('synoptic_code', 'synoptic_type'),
                 Row('network', 'wmo_station_type'),
                 Row('profile', 'communication_type'),
                 Row('elevation', 'country'),
                 Row('region', 'watershed'),
                 Row('wmo_region', 'utc_offset_minutes'),
                 Row('wmo_station_plataform', 'data_type'),
                 Row('observer', 'organization'),
                ),
        Fieldset('Local Environment',
                 Row('local_land_use'),
                 Row('soil_type'),
                 Row('site_description'),
                ),
        Fieldset('Instrumentation and Maintenance'),
        Fieldset('Observing Practices'),
        Fieldset('Data Processing'),
        Fieldset('Historical Events'),
        Fieldset('Other Metadata',
                 Row('hydrology_station_type', 'ground_water_province'),
                 Row('existing_gauges', 'flow_direction_at_station'),
                 Row('flow_direction_above_station', 'flow_direction_below_station'),
                 Row('bank_full_stage', 'bridge_level'),
                 Row('temporary_benchmark', 'mean_sea_level'),
                 Row('river_code', 'river_course'),
                 Row('catchment_area_station', 'river_origin'),
                 Row('easting', 'northing'),
                 Row('river_outlet', 'river_length'),
                 Row('z', 'land_surface_elevation'),
                 Row('top_casing_land_surface', 'casing_diameter'),
                 Row('screen_length', 'depth_midpoint'),
                 Row('casing_type', 'datum'),
                 Row('zone')
                 )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Disable all fields
        station_form = StationForm(instance=self.object)
        for field in station_form.fields:
            station_form.fields[field].widget.attrs['disabled'] = 'disabled'
            # Add a custom class to apply the dashed border via CSS
            station_form.fields[field].widget.attrs['class'] = 'dashed-border-field'

        context['form'] = station_form
        context['station_name'] = Station.objects.exclude(is_reference=True).values('pk', 'name')  # Fetch only pk and name
        # context['layout'] = self.layout
        return context


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationCreate(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Station

    success_message = "%(name)s was created successfully"
    # form_class = StationCreateForm(instance=self.object)
    form_class = StationForm

    layout = Layout(
        Fieldset('SURFACE Requirements',
                 Row('latitude', 'longitude'),
                 Row('name', 'code'),
                 Row('is_active', 'is_automatic', 'is_synoptic', 'international_exchange'),
                 Row('synoptic_code', 'synoptic_type'),
                 Row('region', 'elevation'),
                 Row('country', 'communication_type'),
                 Row('utc_offset_minutes', 'begin_date'),
                 ),
        Fieldset('Additional Options',
                #  Row('wigos'),
                 Row('wigos_part_1', 'wigos_part_2', 'wigos_part_3', 'wigos_part_4'),
                 Row('wmo_region'),
                 Row('wmo_station_type', 'reporting_status'),
                 ),
        Fieldset('OSCAR Specific Settings',
                #  Row(''),
                ),
        Fieldset('WIS2BOX Specific Settings',
                #  Row(''),
                )
    )

    # Override dispatch to initialize variables
    def dispatch(self, request, *args, **kwargs):
        # Initialize your instance variable oscar_error_message
        self.oscar_error_msg = ""
        self.is_oscar_error_msg = False
        
        # Call the parent class's dispatch method to ensure the default behavior is preserved
        return super().dispatch(request, *args, **kwargs)
    

    # ################
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # context['watersheds'] = Watershed.objects.all()
        # context['regions'] = AdministrativeRegion.objects.all()

        # to show station management buttons beneath the title
        context['is_create'] = True

        return context


    # form_valid function
    def form_valid(self, form):

        # retrieve api token and wigos_id
        oscar_api_token = self.request.POST.get('oscar_api_token')

        station_wigos_id = [f"{str(form.cleaned_data['wigos_part_1'])}-{str(CountryISOCode.objects.filter(name=form.cleaned_data['wigos_part_2']).values_list('notation', flat=True).first())}-{str(form.cleaned_data['wigos_part_3'])}-{str(form.cleaned_data['wigos_part_4'])}"]

        if oscar_api_token:
            try:
                # run station export task
                oscar_response_dict = export_station_to_oscar_wigos(station_wigos_id, oscar_api_token, form.cleaned_data)

                # check if station was succesfully added to OSCAR or not
                oscar_check = self.check_oscar_push(oscar_response_dict)

                # if oscar push was unsuccessful
                if not oscar_check[0]:

                    # get the error message (why the oscar push failed)
                    self.oscar_error_msg = oscar_check[1]['error_message']
                    # oscar has recieved failed and therefore recieved an error message
                    self.is_oscar_error_msg = True

                    # execute the form_invalid option
                    return self.form_invalid(form)

            except Exception as e:

                print(f"An error occured when attempting to add a station to OSCAR during station create!\nError: {e}")

                self.oscar_error_msg = 'An error occured when attempting to add a station to OSCAR during station creation!'

                self.is_oscar_error_msg = True

                return self.form_invalid(form)

        return super().form_valid(form)


    def form_invalid(self, form):
        # default behavior catches form errors
        response = super().form_invalid(form)

        response.context_data['oscar_error_msg'] = self.oscar_error_msg
        response.context_data['is_oscar_error_msg'] = self.is_oscar_error_msg

        return response


    # fxn to check if station was successfully added to oscar
    def check_oscar_push(self, oscar_response):
        oscar_response_message = {'error_message': ""}

        if oscar_response.get('code'):
            if oscar_response['code'] == 401:
                oscar_response_message['error_message'] = "Incorrect API token!\nTo be able to access OSCAR a valid API token is required.\nEnter the correct API token or please contact OSCAR service desk!"
            elif oscar_response['code'] == 412:
                oscar_response_message['error_message'] = oscar_response['description']
            else:
                oscar_response_message['error_message'] = "An error occured when attempting to add a station to OSCAR during station creation!"


        # return true is oscar push was successful
        elif oscar_response.get('xmlStatus'):

            if  oscar_response['xmlStatus'] == 'SUCCESS':
                return [True]
            else:
                oscar_response_message['error_message'] = oscar_response['logs']
        
        # otherwise return false
        return [False, oscar_response_message]



@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationUpdate(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    template_name = "wx/station_update.html"
    model = Station

    success_message = "%(name)s was updated successfully"
    form_class = StationForm

    layout = Layout(
        Fieldset('Station Information',
                 Row('latitude', 'longitude'),
                 Row('name', 'alias_name'),
                 Row('code', 'wigos'),
                 Row('begin_date', 'end_date', 'relocation_date'),
                 Row('wmo', 'reporting_status'),
                 Row('is_active', 'is_automatic', 'is_synoptic', 'international_exchange'),
                 Row('synoptic_code', 'synoptic_type'),
                 Row('network', 'wmo_station_type'),
                 Row('profile', 'communication_type'),
                 Row('elevation', 'country'),
                 Row('region', 'watershed'),
                 Row('wmo_region', 'utc_offset_minutes'),
                 Row('wmo_station_plataform', 'data_type'),
                 Row('observer', 'organization'),
                ),
        Fieldset('Local Environment',
                 Row('local_land_use'),
                 Row('soil_type'),
                 Row('site_description'),
                ),
        Fieldset('Instrumentation and Maintenance',
                #  Row(''),
                ),
        Fieldset('Observing Practices',
                #  Row(''),
                ),
        Fieldset('Data Processing',
                #  Row(''),
                ),
        Fieldset('Historical Events',
                #  Row(''),
                ),
        Fieldset('Other Metadata',
                 Row('hydrology_station_type', 'ground_water_province'),
                 Row('existing_gauges', 'flow_direction_at_station'),
                 Row('flow_direction_above_station', 'flow_direction_below_station'),
                 Row('bank_full_stage', 'bridge_level'),
                 Row('temporary_benchmark', 'mean_sea_level'),
                 Row('river_code', 'river_course'),
                 Row('catchment_area_station', 'river_origin'),
                 Row('easting', 'northing'),
                 Row('river_outlet', 'river_length'),
                 Row('z', 'land_surface_elevation'),
                 Row('top_casing_land_surface', 'casing_diameter'),
                 Row('screen_length', 'depth_midpoint'),
                 Row('casing_type', 'datum'),
                 Row('zone')
                 )
    #     Fieldset('Editing station',
    #              Row('latitude', 'longitude'),
    #              Row('name', 'is_active'),
    #              Row('alias_name', 'is_automatic'),
    #              Row('code', 'profile'),
    #              Row('wmo', 'organization'),
    #              Row('wigos', 'observer'),
    #              Row('begin_date', 'data_source'),
    #              Row('end_date', 'communication_type')
    #              ),
    #     Fieldset('Other information',
    #              Row('elevation', 'watershed'),
    #              Row('country', 'region'),
    #              Row('utc_offset_minutes', 'local_land_use'),
    #              Row('soil_type', 'station_details'),
    #              Row('site_description', 'alternative_names')
    #              ),
    #     Fieldset('Hydrology information',
    #              Row('hydrology_station_type', 'ground_water_province'),
    #              Row('existing_gauges', 'flow_direction_at_station'),
    #              Row('flow_direction_above_station', 'flow_direction_below_station'),
    #              Row('bank_full_stage', 'bridge_level'),
    #              Row('temporary_benchmark', 'mean_sea_level'),
    #              Row('river_code', 'river_course'),
    #              Row('catchment_area_station', 'river_origin'),
    #              Row('easting', 'northing'),
    #              Row('river_outlet', 'river_length'),
    #              Row('z', 'land_surface_elevation'),
    #              Row('top_casing_land_surface', 'casing_diameter'),
    #              Row('screen_length', 'depth_midpoint'),
    #              Row('casing_type', 'datum'),
    #              Row('zone')
    #              )
        )

       
    # passing context to display menu buttons beneat the title
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['is_update'] = True

        return context


@api_view(['GET'])
@wx_mapped_permission_required
def MonthlyFormLoad(request):
    try:
        start_date = datetime.datetime.strptime(request.GET['date'], '%Y-%m')
        station_id = int(request.GET['station_id'])

    except ValueError as e:
        logger.error(f"Monthly Load form error: {repr(e)}")
        return JsonResponse({}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Monthly Load form error: {repr(e)}")
        return JsonResponse({}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    station = Station.objects.get(id=station_id)

    # First day of next month
    if start_date.month == 12:
        next_month = start_date.replace(year=start_date.year + 1, month=1)
    else:
        next_month = start_date.replace(month=start_date.month + 1)

    response = get_monthly_data(
        station=station,
        start_date=start_date,
        next_month=next_month,
        utc_offset_minutes=station.utc_offset_minutes
    )

    return JsonResponse(response, status=status.HTTP_200_OK, safe=False)



def get_monthly_data(station, start_date, next_month, utc_offset_minutes=0):
    """
    Load monthly capture data using the station's local month.

    Performance note:
    Instead of filtering with:
        datetime + offset >= start_date

    We calculate the station-local month boundaries in Python and pass
    timezone-aware datetimes to PostgreSQL.

    This allows PostgreSQL/TimescaleDB to use datetime indexes and chunk pruning.
    """

    datetime_offset = pytz.FixedOffset(utc_offset_minutes)

    # Convert selected local month boundaries into timezone-aware datetimes.
    #
    # Example for Belize offset -6:
    #   local month start: 2026-05-01 00:00 -06
    #   local next month:  2026-06-01 00:00 -06
    #
    # PostgreSQL can compare these directly against timestamptz datetime.
    local_month_start = datetime_offset.localize(start_date)
    local_next_month = datetime_offset.localize(next_month)

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                    WITH monthly_rows AS (
                        SELECT
                            datetime,
                            variable_id,
                            measured,
                            remarks,
                            observer,
                            datetime + (%(utc_offset_minutes)s * interval '1 minute') AS local_datetime
                        FROM raw_data
                        WHERE station_id = %(station_id)s
                          AND datetime >= %(local_month_start)s
                          AND datetime < %(local_next_month)s
                    )
                    SELECT DISTINCT ON (local_datetime::date, variable_id)
                        EXTRACT(DAY FROM local_datetime)::int AS day_of_month,
                        variable_id,
                        measured,
                        remarks,
                        observer
                    FROM monthly_rows
                    ORDER BY local_datetime::date, variable_id, datetime DESC
                """,
                {
                    'station_id': station.id,
                    'utc_offset_minutes': utc_offset_minutes,
                    'local_month_start': local_month_start,
                    'local_next_month': local_next_month,
                }
            )

            data = cursor.fetchall()

    timezoneOffsetStr = str(datetime.timedelta(minutes=utc_offset_minutes))
    days_in_month = calendar.monthrange(start_date.year, start_date.month)[1]

    return data, utc_offset_minutes, timezoneOffsetStr, days_in_month



@api_view(['POST'])
@wx_mapped_permission_required
def MonthlyFormUpdate(request):
    try:
        date_str = request.GET.get('date')          # YYYY-MM
        station_id = request.GET.get('station_id')
        days_dict = request.data.get('table')

        if not date_str or not station_id or not days_dict:
            return JsonResponse(
                {"error": "Missing required fields"},
                status=status.HTTP_400_BAD_REQUEST
            )

        month_start = datetime.datetime.strptime(date_str, '%Y-%m')

        station = get_object_or_404(Station, id=station_id)

        variables = Variable.objects.in_bulk()

        now_utc = datetime.datetime.now().astimezone(pytz.UTC)
        datetime_offset = pytz.FixedOffset(station.utc_offset_minutes)

        # Monthly form rows are daily observations.
        seconds = 86400

        records_list = []

        days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]

        for day_number, day_data in days_dict.items():
            try:
                day_number = int(day_number)
            except (TypeError, ValueError):
                return JsonResponse(
                    {"error": f"Invalid day value: {day_number}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if day_number < 1 or day_number > days_in_month:
                return JsonResponse(
                    {"error": f"Day must be between 1 and {days_in_month}. Received: {day_number}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            data_datetime = month_start.replace(
                day=day_number,
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )

            data_datetime = datetime_offset.localize(data_datetime)

            # Prevent saving future days.
            if data_datetime > now_utc:
                continue

            if not day_data:
                continue

            remarks = day_data.pop('remarks', None)
            observer = day_data.pop('observer', None)

            # Remove frontend-only fields.
            day_data.pop('day', None)
            day_data.pop('action', None)

            for variable_id, measurement in day_data.items():
                variable = variables.get(int(variable_id))

                if measurement is None:
                    measurement_value = settings.MISSING_VALUE
                    measurement_code = settings.MISSING_VALUE_CODE
                else:
                    if variable and variable.variable_type == 'Numeric':
                        try:
                            measurement_value = float(measurement)
                            measurement_code = measurement
                        except Exception:
                            measurement_value = settings.MISSING_VALUE
                            measurement_code = settings.MISSING_VALUE_CODE
                    else:
                        measurement_value = settings.MISSING_VALUE
                        measurement_code = measurement

                records_list.append((
                    station_id,
                    variable_id,
                    seconds,
                    data_datetime,
                    measurement_value,
                    1,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,
                    remarks,
                    observer,
                    measurement_code
                ))

        if not records_list:
            return JsonResponse(
                {
                    "taskId": None,
                    "message": "No measurement records to save."
                },
                status=status.HTTP_200_OK
            )

        task = save_monthly_form.delay(
            records_list,
            date_str,
            station_id,
            True,
            station.utc_offset_minutes
        )

        return JsonResponse({"taskId": task.id}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Monthly form update error: {repr(e)}")
        return JsonResponse(
            {"error": "Failed to start monthly update task"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



@api_view(['POST'])
@wx_mapped_permission_required
def MonthlyFormDelete(request):
    """
    Delete monthly capture data for one selected day.

    IMPORTANT:
    This delete is based on the station's local day, not exact datetime equality.

    Why?
        raw_data.datetime is a full timestamp.
        The monthly form shows one row per station-local day.
        So deleting a row should delete all matching station/variable records
        within that local day.

    Performance notes:
        - Uses datetime range filtering:
              datetime >= day_start
              datetime < day_end

          This is faster than:
              (datetime + offset)::date = local_date

        - Does not use SELECT COUNT before DELETE.
        - Does not use DELETE ... RETURNING.
        - Uses cursor.rowcount to report how many rows were deleted.
    """

    request_date_str = request.GET.get('date')      # Expected format: YYYY-MM
    day = request.GET.get('day')                    # Expected: 1-31 depending on month
    station_id = request.GET.get('station_id')
    variable_id_list = request.data.get('variable_ids')

    logger.info(
        "MonthlyFormDelete called | date=%s | day=%s | station_id=%s | variable_ids=%s",
        request_date_str,
        day,
        station_id,
        variable_id_list,
    )

    # ---------------------------------------------------------------------
    # 1. Basic request validation
    # ---------------------------------------------------------------------
    if not request_date_str or day is None or not station_id or variable_id_list is None:
        message = "Invalid request. 'date', 'day', 'station_id', and 'variable_ids' must be provided."

        logger.warning("MonthlyFormDelete validation failed | %s", message)

        return JsonResponse(
            {
                "success": False,
                "message": message,
                "received": {
                    "date": request_date_str,
                    "day": day,
                    "station_id": station_id,
                    "variable_ids": variable_id_list,
                },
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------------------------------------------
    # 2. Parse selected month and selected day
    # ---------------------------------------------------------------------
    try:
        month_start = datetime.datetime.strptime(request_date_str, '%Y-%m')
        day = int(day)

    except ValueError:
        message = "Invalid date/day format. Expected date='YYYY-MM' and day as integer."

        logger.warning(
            "MonthlyFormDelete date parse failed | date=%s | day=%s",
            request_date_str,
            day,
        )

        return JsonResponse(
            {
                "success": False,
                "message": message,
                "received": {
                    "date": request_date_str,
                    "day": day,
                },
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Reject invalid dates like February 30.
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]

    if day < 1 or day > days_in_month:
        message = f"Day must be between 1 and {days_in_month}. Received: {day}"

        logger.warning("MonthlyFormDelete invalid day | %s", message)

        return JsonResponse(
            {
                "success": False,
                "message": message,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------------------------------------------
    # 3. Validate variable IDs
    # ---------------------------------------------------------------------
    try:
        variable_id_list = [int(v) for v in variable_id_list]

    except (TypeError, ValueError):
        message = "Invalid variable_ids. All variable IDs must be integers."

        logger.warning(
            "MonthlyFormDelete invalid variable_ids | variable_ids=%s",
            variable_id_list,
        )

        return JsonResponse(
            {
                "success": False,
                "message": message,
                "received_variable_ids": variable_id_list,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------------------------------------------
    # 4. Fetch station so we can use its UTC offset
    # ---------------------------------------------------------------------
    try:
        station = Station.objects.get(id=station_id)

    except Station.DoesNotExist:
        message = "Station not found"

        logger.warning(
            "MonthlyFormDelete station not found | station_id=%s",
            station_id,
        )

        return JsonResponse(
            {
                "success": False,
                "message": message,
                "station_id": station_id,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------------------------------------------
    # 5. Build station-local day range
    # ---------------------------------------------------------------------
    datetime_offset = pytz.FixedOffset(station.utc_offset_minutes)

    local_day = month_start.replace(
        day=day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    # Example:
    #   local_day = 2026-05-02 00:00
    #   station offset = -360
    #
    #   day_start = 2026-05-02 00:00:00-06:00
    #   day_end   = 2026-05-03 00:00:00-06:00
    day_start = datetime_offset.localize(local_day)
    day_end = day_start + datetime.timedelta(days=1)

    local_date = local_day.date()

    logger.info(
        "MonthlyFormDelete prepared | station_id=%s | station_offset=%s | local_date=%s | day_start=%s | day_end=%s | variable_ids=%s",
        station_id,
        station.utc_offset_minutes,
        local_date,
        day_start,
        day_end,
        variable_id_list,
    )

    queries = {
        # Delete rows matching the selected station-local day.
        #
        # We intentionally do not use:
        #   datetime = exact_datetime
        #
        # and we also avoid:
        #   (datetime + offset)::date = local_date
        #
        # because this range version is much faster.
        "delete_raw_data": """
            DELETE FROM raw_data
            WHERE station_id = %s
              AND variable_id = ANY(%s)
              AND datetime >= %s
              AND datetime < %s
        """,

        # Queue daily summary recalculation for the selected local day.
        "create_daily_summary": """
            INSERT INTO wx_dailysummarytask (
                station_id,
                date,
                created_at,
                updated_at
            )
            VALUES (%s, %s, now(), now())
            ON CONFLICT DO NOTHING
        """,
    }

    response_payload = {
        "success": True,
        "message": "",
        "station_id": station_id,
        "station_offset_minutes": station.utc_offset_minutes,
        "date": request_date_str,
        "day": day,
        "local_date": str(local_date),
        "day_start": str(day_start),
        "day_end": str(day_end),
        "variable_ids": variable_id_list,
        "deleted_rows": 0,
    }

    try:
        with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
            with conn.cursor() as cursor:

                # ---------------------------------------------------------
                # Delete matching rows
                # ---------------------------------------------------------
                cursor.execute(
                    queries["delete_raw_data"],
                    [
                        station_id,
                        variable_id_list,
                        day_start,
                        day_end,
                    ]
                )

                deleted_count = cursor.rowcount
                response_payload["deleted_rows"] = deleted_count

                if deleted_count > 0:
                    response_payload["message"] = f"Deleted {deleted_count} database row(s)."
                else:
                    response_payload["message"] = "No matching database rows were deleted."

                logger.info(
                    "MonthlyFormDelete deleted rows | deleted_rows=%s | station_id=%s | local_date=%s | day_start=%s | day_end=%s | variable_ids=%s",
                    deleted_count,
                    station_id,
                    local_date,
                    day_start,
                    day_end,
                    variable_id_list,
                )

                # ---------------------------------------------------------
                # Queue daily summary recalculation
                # ---------------------------------------------------------
                # This is queued even if deleted_count is 0.
                # That is harmless and keeps behavior simple.
                cursor.execute(
                    queries["create_daily_summary"],
                    [station_id, local_date]
                )

            conn.commit()

    except Exception as e:
        logger.error(
            "MonthlyFormDelete failed | error=%s | debug=%s",
            repr(e),
            response_payload,
        )

        return JsonResponse(
            {
                "success": False,
                "message": "Monthly delete failed",
                "error": repr(e),
                "debug": response_payload,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return Response(response_payload, status=status.HTTP_200_OK)



@api_view(['POST'])
@wx_mapped_permission_required
def monthly_capture_update_empty_col(request):
    """
    Delete cells that were cleared in the monthly capture form.

    The frontend sends data like:

        {
            "2": ["10", "16"],
            "5": ["14"]
        }

    Meaning:
        - On day 2, variables 10 and 16 were cleared.
        - On day 5, variable 14 was cleared.

    IMPORTANT:
    This function deletes by station-local day using a datetime range:

        datetime >= local day start
        datetime <  local next day start

    This is faster than:

        (datetime + offset)::date = local_date

    because PostgreSQL/Timescale can use datetime indexes and chunk pruning.
    """

    request_date_str = request.GET.get('date')      # Expected format: YYYY-MM
    station_id = request.GET.get('station_id')
    empty_cols_data = request.data.get('empty_cols_data')

    # ---------------------------------------------------------------------
    # 1. Basic request validation
    # ---------------------------------------------------------------------
    if not request_date_str or not station_id or empty_cols_data is None:
        message = "Invalid request. 'date', 'station_id', and 'empty_cols_data' must be provided."
        return JsonResponse(
            {"success": False, "message": message},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not isinstance(empty_cols_data, dict):
        message = "Invalid request. 'empty_cols_data' must be an object keyed by day."
        return JsonResponse(
            {"success": False, "message": message},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------------------------------------------
    # 2. Parse selected month
    # ---------------------------------------------------------------------
    try:
        month_start = datetime.datetime.strptime(request_date_str, '%Y-%m')
    except ValueError:
        message = "Invalid date format. The expected date format is 'YYYY-MM'"
        return JsonResponse(
            {"success": False, "message": message},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------------------------------------------------------------
    # 3. Fetch station so we can build station-local day ranges
    # ---------------------------------------------------------------------
    try:
        station = Station.objects.get(id=station_id)
    except Station.DoesNotExist:
        return JsonResponse(
            {"success": False, "message": "Station not found"},
            status=status.HTTP_400_BAD_REQUEST
        )

    datetime_offset = pytz.FixedOffset(station.utc_offset_minutes)
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]

    queries = {
        # Delete cleared variables for a station-local day.
        #
        # This intentionally does NOT use exact datetime equality because
        # old/manual records may not always be stored at the exact same time.
        "delete_raw_data": """
            DELETE FROM raw_data
            WHERE station_id = %s
              AND variable_id = ANY(%s)
              AND datetime >= %s
              AND datetime < %s
            RETURNING station_id, variable_id, datetime, measured, code
        """,

        # Queue daily summary recalculation for the affected day.
        "create_daily_summary": """
            INSERT INTO wx_dailysummarytask (
                station_id,
                date,
                created_at,
                updated_at
            )
            VALUES (%s, %s, now(), now())
            ON CONFLICT DO NOTHING
        """,

        # Check if StationVariable.last_data_datetime points to the deleted day.
        # We check this before repairing last_data_*.
        "get_affected_stationvariables": """
            SELECT variable_id
            FROM wx_stationvariable
            WHERE station_id = %s
              AND variable_id = ANY(%s)
              AND last_data_datetime IS NOT NULL
              AND last_data_datetime >= %s
              AND last_data_datetime < %s
        """,

        # Repair StationVariable.last_data_* using the latest remaining raw_data row.
        "update_last_data_from_remaining_raw_data": """
            WITH latest AS (
                SELECT DISTINCT ON (station_id, variable_id)
                    station_id,
                    variable_id,
                    measured,
                    code,
                    datetime
                FROM raw_data
                WHERE station_id = %s
                  AND variable_id = ANY(%s)
                ORDER BY station_id, variable_id, datetime DESC
            )
            UPDATE wx_stationvariable sv
            SET last_data_datetime = latest.datetime,
                last_data_value = latest.measured,
                last_data_code = latest.code
            FROM latest
            WHERE sv.station_id = latest.station_id
              AND sv.variable_id = latest.variable_id
        """,

        # If no raw_data remains for a variable, clear last_data_*.
        "clear_last_data_if_no_remaining_raw_data": """
            UPDATE wx_stationvariable sv
            SET last_data_datetime = NULL,
                last_data_value = NULL,
                last_data_code = NULL
            WHERE sv.station_id = %s
              AND sv.variable_id = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1
                  FROM raw_data rd
                  WHERE rd.station_id = sv.station_id
                    AND rd.variable_id = sv.variable_id
              )
        """
    }

    deleted_total = 0
    deleted_by_day = {}

    try:
        with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
            with conn.cursor() as cursor:

                # Loop through each day that had cleared cells.
                for day_key, variable_id_list in empty_cols_data.items():

                    # -----------------------------------------------------
                    # 4. Validate day
                    # -----------------------------------------------------
                    try:
                        day = int(day_key)
                    except (TypeError, ValueError):
                        return JsonResponse(
                            {
                                "success": False,
                                "message": f"Invalid day value: {day_key}"
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    if day < 1 or day > days_in_month:
                        return JsonResponse(
                            {
                                "success": False,
                                "message": f"Day must be between 1 and {days_in_month}. Received: {day}"
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # -----------------------------------------------------
                    # 5. Validate variable IDs for this day
                    # -----------------------------------------------------
                    if variable_id_list is None:
                        return JsonResponse(
                            {
                                "success": False,
                                "message": f"variable_ids must be provided for day {day}."
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    if not isinstance(variable_id_list, (list, tuple)):
                        return JsonResponse(
                            {
                                "success": False,
                                "message": f"variable_ids for day {day} must be a list."
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # Nothing was cleared for this day.
                    if not variable_id_list:
                        continue

                    try:
                        variable_id_list = [int(v) for v in variable_id_list]
                    except (TypeError, ValueError):
                        return JsonResponse(
                            {
                                "success": False,
                                "message": f"Invalid variable_ids for day {day}. All variable IDs must be integers."
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # -----------------------------------------------------
                    # 6. Build station-local day range
                    # -----------------------------------------------------
                    # Example:
                    #   date=2026-05, day=2, station UTC offset=-360
                    #
                    #   day_start = 2026-05-02 00:00:00-06
                    #   day_end   = 2026-05-03 00:00:00-06
                    #
                    # PostgreSQL can compare these directly to raw_data.datetime.
                    local_day = month_start.replace(
                        day=day,
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0
                    )

                    day_start = datetime_offset.localize(local_day)
                    day_end = day_start + datetime.timedelta(days=1)

                    local_date = local_day.date()

                    # -----------------------------------------------------
                    # 7. Find affected StationVariable rows before delete
                    # -----------------------------------------------------
                    cursor.execute(
                        queries["get_affected_stationvariables"],
                        [
                            station_id,
                            variable_id_list,
                            day_start,
                            day_end,
                        ]
                    )

                    affected_variable_ids = [row[0] for row in cursor.fetchall()]

                    # -----------------------------------------------------
                    # 8. Delete cleared raw_data rows
                    # -----------------------------------------------------
                    cursor.execute(
                        queries["delete_raw_data"],
                        [
                            station_id,
                            variable_id_list,
                            day_start,
                            day_end,
                        ]
                    )

                    deleted_rows = cursor.fetchall()
                    deleted_count = len(deleted_rows)

                    deleted_total += deleted_count
                    deleted_by_day[str(local_date)] = deleted_count

                    logger.info(
                        "Monthly empty-col cleanup deleted %s rows | station_id=%s | day_start=%s | day_end=%s | variable_ids=%s",
                        deleted_count,
                        station_id,
                        day_start,
                        day_end,
                        variable_id_list,
                    )

                    # -----------------------------------------------------
                    # 9. Queue daily summary recalculation
                    # -----------------------------------------------------
                    cursor.execute(
                        queries["create_daily_summary"],
                        [station_id, local_date]
                    )

                    # -----------------------------------------------------
                    # 10. Repair StationVariable.last_data_* if needed
                    # -----------------------------------------------------
                    if affected_variable_ids:
                        cursor.execute(
                            queries["update_last_data_from_remaining_raw_data"],
                            [station_id, affected_variable_ids]
                        )

                        cursor.execute(
                            queries["clear_last_data_if_no_remaining_raw_data"],
                            [station_id, affected_variable_ids]
                        )

            conn.commit()

    except Exception as e:
        logger.error(
            "monthly_capture_update_empty_col failed | error=%s | station_id=%s | date=%s | empty_cols_data=%s",
            repr(e),
            station_id,
            request_date_str,
            empty_cols_data,
        )

        return JsonResponse(
            {
                "success": False,
                "message": "Monthly empty-column cleanup failed.",
                "error": repr(e),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return Response(
        {
            "success": True,
            "deleted_rows": deleted_total,
            "deleted_by_day": deleted_by_day,
        },
        status=status.HTTP_200_OK
    )



@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationDelete(LoginRequiredMixin, DeleteView):
    model = Station
    fields = ['code', 'name', 'profile']

    def get_success_url(self):
        return reverse('stations-list')

    def post(self, request, *args, **kwargs):
        """
        Handle the delete form submission manually.

        If the station is connected to other records, stay on this same delete
        page and show a friendly error message instead of showing an
        IntegrityError page.
        """

        # Get the station being deleted
        self.object = self.get_object()

        try:
            # Try to delete the station inside a transaction.
            # If the database blocks the delete because related records exist,
            # the error will be caught below.
            with transaction.atomic():
                self.object.delete()

        except (ProtectedError, IntegrityError):
            # Re-render the same delete page with an error message
            context = self.get_context_data(
                object=self.object,
                station=self.object,
                delete_error=(
                    f'Cannot delete station "{self.object.name}" because it is '
                    f'associated with other records in the database.'
                )
            )

            return self.render_to_response(context)

        # If delete was successful, go to the stations list
        return HttpResponseRedirect(self.get_success_url())


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationFileList(LoginRequiredMixin, ListView):
    model = StationFile

    def get_queryset(self):
        queryset = StationFile.objects.filter(station__id=self.kwargs.get('pk'))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        station = Station.objects.get(pk=self.kwargs.get('pk'))  # the self.kwargs is different from **kwargs, and gives access to the named url parameters
        
        # context['station'] = station
        context['station'] = station if not station.is_reference else None

        return context


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationFileCreate(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = StationFile

    # fields = "__all__"
    fields = ('name', 'file')
    success_message = "%(name)s was created successfully"
    layout = Layout(
        Fieldset('Add file to station',
                 Row('name'),
                 Row('file')
                 )
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        station = Station.objects.get(pk=self.kwargs.get(
            'pk'))  # the self.kwargs is different from **kwargs, and gives access to the named url parameters
        # context['station'] = station

        context['station'] = station if not station.is_reference else None

        return context

    def form_valid(self, form):
        f = form.save(commit=False)
        station = Station.objects.get(pk=self.kwargs.get('pk'))
        f.station = station
        f.save()
        return super(StationFileCreate, self).form_valid(form)

    def get_success_url(self):
        return reverse('stationfiles-list', kwargs={'pk': self.kwargs.get('pk')})


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationFileDelete(LoginRequiredMixin, DeleteView):
    model = StationFile

    success_message = "%(name)s was deleted successfully"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        station = Station.objects.get(pk=self.kwargs.get(
            'pk_station'))  # the self.kwargs is different from **kwargs, and gives access to the named url parameters
        # context['station'] = station
        context['station'] = station if not station.is_reference else None
        
        return context

    def get_success_url(self):
        return reverse('stationfiles-list', kwargs={'pk': self.kwargs.get('pk_station')})


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationVariableListView(LoginRequiredMixin, ListView):
    model = StationVariable

    def get_queryset(self):
        queryset = StationVariable.objects.filter(station__id=self.kwargs.get('pk'))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        station = Station.objects.get(pk=self.kwargs.get(
            'pk'))  # the self.kwargs is different from **kwargs, and gives access to the named url parameters
        # context['station'] = station
        context['station'] = station if not station.is_reference else None

        return context


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationVariableCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = StationVariable

    fields = ('variable',)
    success_message = "%(variable)s was created successfully"
    layout = Layout(
        Fieldset('Add variable to station',
                 Row('variable')
                 )
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        station = Station.objects.get(pk=self.kwargs.get(
            'pk'))  # the self.kwargs is different from **kwargs, and gives access to the named url parameters
        # context['station'] = station

        context['station'] = station if not station.is_reference else None

        return context

    def form_valid(self, form):
        f = form.save(commit=False)
        station = Station.objects.get(pk=self.kwargs.get('pk'))
        f.station = station
        f.save()
        return super(StationVariableCreateView, self).form_valid(form)

    def get_success_url(self):
        return reverse('stationvariable-list', kwargs={'pk': self.kwargs.get('pk')})


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationVariableDeleteView(LoginRequiredMixin, DeleteView):
    model = StationVariable

    success_message = "%(action)s was deleted successfully"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        station = Station.objects.get(pk=self.kwargs.get(
            'pk_station'))  # the self.kwargs is different from **kwargs, and gives access to the named url parameters
        # context['station'] = station

        context['station'] = station if not station.is_reference else None

        return context

    def get_success_url(self):
        return reverse('stationvariable-list', kwargs={'pk': self.kwargs.get('pk_station')})


def station_report_data(request):
    station = request.GET.get('station', None)
    initial_datetime = request.GET.get('initial_datetime', None)
    final_datetime = request.GET.get('final_datetime', None)
    source = request.GET.get('source', None)

    if station and initial_datetime and final_datetime and source:
        if int(source) == 0:  # Raw data
            dataset = get_raw_data('station', station, None, initial_datetime, final_datetime, 'raw_data')
        elif int(source) == 1:  # Hourly data
            dataset = get_raw_data('station', station, None, initial_datetime, final_datetime, 'hourly_summary')
        elif int(source) == 2:  # Daily data
            dataset = get_raw_data('station', station, None, initial_datetime, final_datetime, 'daily_summary')
        elif int(source) == 3:  # Monthly data
            dataset = get_raw_data('station', station, None, initial_datetime, final_datetime, 'monthly_summary')
        elif int(source) == 4:  # Yearly data
            dataset = get_raw_data('station', station, None, initial_datetime, final_datetime, 'yearly_summary')
        else:
            return JsonResponse({}, status=status.HTTP_404_NOT_FOUND)

        charts = {

        }

        for element_name, element_data in dataset['results'].items():

            chart = {
                'chart': {
                    'type': 'pie',
                    'zoomType': 'xy'
                },
                'title': {'text': element_name},
                'xAxis': {
                    'type': 'datetime',
                    'dateTimeLabelFormats': {
                        'month': '%e. %b',
                        'year': '%b'
                    },
                    'title': {
                        'text': 'Date'
                    }
                },
                'yAxis': [],
                'exporting': {
                    'showTable': True
                },
                'series': []
            }

            opposite = False
            y_axis_unit_dict = {}
            for variable_name, variable_data in element_data.items():

                current_unit = variable_data['unit']
                if current_unit not in y_axis_unit_dict.keys():
                    chart['yAxis'].append({
                        'labels': {
                            'format': '{value} ' + variable_data['unit'],
                        },
                        'title': {
                            'text': None
                        },
                        'opposite': opposite
                    })
                    y_axis_unit_dict[current_unit] = len(chart['yAxis']) - 1
                    opposite = not opposite

                current_y_axis_index = y_axis_unit_dict[current_unit]
                data = []
                for record in variable_data['data']:
                    if int(source) == 0:
                        data.append({
                            'x': record['date'],
                            'y': record['value'],
                            'quality_flag': record['quality_flag'],
                            'flag_color': record['flag_color']
                        })
                    elif int(source) == 3:
                        data.append({
                            'x': record['date'],
                            'y': record['value']
                        })

                        chart['xAxis'] = {
                            'type': 'datetime',
                            'labels': {
                                'format': '{value:%Y-%b}',
                            },
                            'title': {
                                'text': 'Y'
                            }
                        }
                    elif int(source) == 4:
                        data.append({
                            'x': record['date'],
                            'y': record['value']
                        })

                        chart['xAxis'] = {
                            'type': 'datetime',
                            'labels': {
                                'format': '{value:%Y-%b}',
                            },
                            'title': {
                                'text': 'Reference'
                            }
                        }
                    else:
                        data.append({
                            'x': record['date'],
                            'y': record['value']
                        })

                chart['series'].append({
                    'name': variable_name,
                    'color': variable_data['color'],
                    'type': variable_data['default_representation'],
                    'unit': variable_data['unit'],
                    'data': data,
                    'yAxis': current_y_axis_index
                })
                chart['chart']['type'] = variable_data['default_representation'],

            charts[slugify(element_name)] = chart

        return JsonResponse(charts)
    else:
        return JsonResponse({}, status=status.HTTP_400_BAD_REQUEST)


def variable_report_data(request):
    variable_ids_list = request.GET.get('variable_ids', None)
    initial_datetime = request.GET.get('initial_datetime', None)
    final_datetime = request.GET.get('final_datetime', None)
    source = request.GET.get('source', None)
    station_id_list = request.GET.get('station_ids', None)

    if variable_ids_list and initial_datetime and final_datetime and source and station_id_list:
        variable_ids_list = tuple(json.loads(variable_ids_list))
        station_id_list = tuple(json.loads(station_id_list))

        if int(source) == 0:  # Raw data
            dataset = get_station_raw_data('variable', variable_ids_list, None, initial_datetime, final_datetime,
                                           station_id_list, 'raw_data')
        elif int(source) == 1:  # Hourly data
            dataset = get_station_raw_data('variable', variable_ids_list, None, initial_datetime, final_datetime,
                                           station_id_list, 'hourly_summary')
        elif int(source) == 2:  # Daily data
            dataset = get_station_raw_data('variable', variable_ids_list, None, initial_datetime, final_datetime,
                                           station_id_list, 'daily_summary')
        elif int(source) == 3:  # Monthly data
            dataset = get_station_raw_data('variable', variable_ids_list, None, initial_datetime, final_datetime,
                                           station_id_list, 'monthly_summary')
        elif int(source) == 4:  # Yearly data
            dataset = get_station_raw_data('variable', variable_ids_list, None, initial_datetime, final_datetime,
                                           station_id_list, 'yearly_summary')
        else:
            return JsonResponse({}, status=status.HTTP_404_NOT_FOUND)

        charts = {

        }

        for element_name, element_data in dataset['results'].items():

            chart = {
                'chart': {
                    'type': 'pie',
                    'zoomType': 'xy'
                },
                'title': {'text': element_name},
                'xAxis': {
                    'type': 'datetime',
                    'dateTimeLabelFormats': {
                        'month': '%e. %b',
                        'year': '%b'
                    },
                    'title': {
                        'text': 'Date'
                    }
                },
                'yAxis': [],
                'exporting': {
                    'showTable': True
                },
                'series': []
            }

            opposite = False
            y_axis_unit_dict = {}
            for variable_name, variable_data in element_data.items():

                current_unit = variable_data['unit']
                if current_unit not in y_axis_unit_dict.keys():
                    chart['yAxis'].append({
                        'labels': {
                            'format': '{value} ' + variable_data['unit'],
                        },
                        'title': {
                            'text': None
                        },
                        'opposite': opposite
                    })
                    y_axis_unit_dict[current_unit] = len(chart['yAxis']) - 1
                    opposite = not opposite

                current_y_axis_index = y_axis_unit_dict[current_unit]
                data = []
                for record in variable_data['data']:
                    if int(source) == 0:
                        data.append({
                            'x': record['date'],
                            'y': record['value'],
                            'quality_flag': record['quality_flag'],
                            'flag_color': record['flag_color']
                        })
                    elif int(source) == 3:
                        data.append({
                            'x': record['date'],
                            'y': record['value']
                        })

                        chart['xAxis'] = {
                            'type': 'datetime',
                            'labels': {
                                'format': '{value:%Y-%b}',
                            },
                            'title': {
                                'text': 'Y'
                            }
                        }
                    elif int(source) == 4:
                        data.append({
                            'x': record['date'],
                            'y': record['value']
                        })

                        chart['xAxis'] = {
                            'type': 'datetime',
                            'labels': {
                                'format': '{value:%Y-%b}',
                            },
                            'title': {
                                'text': 'Reference'
                            }
                        }
                    else:
                        data.append({
                            'x': record['date'],
                            'y': record['value']
                        })

                chart['series'].append({
                    'name': variable_name,
                    'color': "#" + ''.join([random.choice('0123456789ABCDEF') for j in range(6)]),
                    'type': variable_data['default_representation'],
                    'unit': variable_data['unit'],
                    'data': data,
                    'yAxis': current_y_axis_index
                })
                chart['chart']['type'] = variable_data['default_representation'],

            charts[slugify(element_name)] = chart

        return JsonResponse(charts)
    else:
        return JsonResponse({}, status=status.HTTP_400_BAD_REQUEST)


class StationReportView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/products/station_report.html"

    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_id'] = self.request.GET.get('station_id', 'null')

        station_list = Station.objects.exclude(is_reference=True)
        
        context['station_list'] = station_list

        quality_flag_query = QualityFlag.objects.all()
        quality_flag_colors = {}
        for quality_flag in quality_flag_query:
            quality_flag_colors[quality_flag.name.replace(' ', '_')] = quality_flag.color
        context['quality_flag_colors'] = quality_flag_colors

        selected_station = station_list.first()
        if selected_station is not None:
            selected_station_id = selected_station.id
            station_variable_list = StationVariable.objects.filter(station__id=selected_station_id)
        else:
            station_variable_list = []

        context['station_variable_list'] = station_variable_list

        return context



class VariableReportView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/products/variable_report.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        quality_flag_query = QualityFlag.objects.all()
        quality_flag_colors = {}
        for quality_flag in quality_flag_query:
            quality_flag_colors[quality_flag.name.replace(' ', '_')] = quality_flag.color

        context['quality_flag_colors'] = quality_flag_colors
        context['variable_list'] = Variable.objects.all()
        context['station_list'] = Station.objects.exclude(is_reference=True)

        return context



class ProductReportView(LoginRequiredMixin, TemplateView):
    template_name = "wx/products/report.html"


class ProductCompareView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/products/compare.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.select_related('profile').exclude(is_reference=True)
        context['variable_list'] = Variable.objects.select_related('unit').all()

        context['station_profile_list'] = StationProfile.objects.all()
        context['station_watershed_list'] = Watershed.objects.all()
        context['station_district_list'] = AdministrativeRegion.objects.all()

        return context



class ReferenceStationView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/quality_control/reference_station.html'


# helpers for referencestation
def parse_optional_float(value):
    """
    Convert a value to float.

    Empty values become None.
    Invalid values raise ValueError.
    """

    if value in ['', None, '---']:
        return None

    return float(value)

def parse_optional_int(value):
    """
    Convert a value to int.

    Empty values become None.
    Invalid values raise ValueError.
    """

    if value in ['', None, '---']:
        return None

    return int(value)


@require_http_methods(["GET"])
@wx_mapped_permission_required
def load_reference_stations(request):
    """
    Load all stations marked as reference stations.

    Also includes the variable IDs associated with each station through
    StationVariable.
    """

    reference_stations = list(
        Station.objects.filter(
            is_reference=True
        ).order_by('name')
    )

    station_ids = [station.id for station in reference_stations]

    station_variable_rows = StationVariable.objects.filter(
        station_id__in=station_ids
    ).values(
        'station_id',
        'variable_id'
    )

    station_variables_map = {}

    for row in station_variable_rows:
        station_id = row['station_id']
        variable_id = row['variable_id']

        if station_id not in station_variables_map:
            station_variables_map[station_id] = []

        station_variables_map[station_id].append(variable_id)

    data = []

    for station in reference_stations:
        data.append({
            'id': station.id,
            'code': station.code,
            'name': station.name,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'is_active': station.is_active,
            'variable_ids': station_variables_map.get(station.id, []),
        })

    return JsonResponse({
        'reference_stations': data
    })


@require_http_methods(["POST"])
@wx_mapped_permission_required
@transaction.atomic
def create_reference_station(request):
    """
    Create a new reference station.

    Required fields:
    - code
    - name
    - latitude
    - longitude

    Optional:
    - is_active
    - variable_ids

    The backend always sets:
    - is_reference=True
    - utc_offset_minutes=settings.TIMEZONE_OFFSET
    """

    data = json.loads(request.body.decode('utf-8'))

    code = data.get('code')
    name = data.get('name')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    is_active = data.get('is_active', True)
    variable_ids = data.get('variable_ids', [])

    if not code:
        return JsonResponse({
            'message': 'Code is required.'
        }, status=400)

    if not name:
        return JsonResponse({
            'message': 'Name is required.'
        }, status=400)

    if latitude in ['', None]:
        return JsonResponse({
            'message': 'Latitude is required.'
        }, status=400)

    if longitude in ['', None]:
        return JsonResponse({
            'message': 'Longitude is required.'
        }, status=400)

    try:
        latitude = float(latitude)
    except (TypeError, ValueError):
        return JsonResponse({
            'message': 'Latitude must be a valid number.'
        }, status=400)

    try:
        longitude = float(longitude)
    except (TypeError, ValueError):
        return JsonResponse({
            'message': 'Longitude must be a valid number.'
        }, status=400)

    if latitude < -90 or latitude > 90:
        return JsonResponse({
            'message': 'Latitude must be between -90 and 90.'
        }, status=400)

    if longitude < -180 or longitude > 180:
        return JsonResponse({
            'message': 'Longitude must be between -180 and 180.'
        }, status=400)

    if not isinstance(variable_ids, list):
        return JsonResponse({
            'message': 'Variables must be provided as a list.'
        }, status=400)

    try:
        variable_ids = [int(variable_id) for variable_id in variable_ids]
    except (TypeError, ValueError):
        return JsonResponse({
            'message': 'Invalid variable selection.'
        }, status=400)

    valid_variable_ids = list(
        Variable.objects.filter(
            id__in=variable_ids
        ).values_list(
            'id',
            flat=True
        )
    )

    try:
        station = Station.objects.create(
            code=code,
            name=name,
            latitude=latitude,
            longitude=longitude,
            is_active=is_active,
            is_reference=True,
            utc_offset_minutes=settings.TIMEZONE_OFFSET,
        )

    except IntegrityError:
        return JsonResponse({
            'message': f'A station with code "{code}" already exists.'
        }, status=400)

    for variable_id in valid_variable_ids:
        StationVariable.objects.get_or_create(
            station=station,
            variable_id=variable_id
        )

    return JsonResponse({
        'message': 'Reference station created successfully.',
        'station': {
            'id': station.id,
            'code': station.code,
            'name': station.name,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'is_active': station.is_active,
            'variable_ids': valid_variable_ids,
        }
    })


@require_http_methods(["PUT"])
@wx_mapped_permission_required
@transaction.atomic
def modify_reference_station(request, id):
    """
    Modify an existing reference station.

    This updates the simple station fields and syncs the selected variables
    through StationVariable.
    """

    station = get_object_or_404(
        Station,
        id=id,
        is_reference=True
    )

    data = json.loads(request.body.decode('utf-8'))

    code = data.get('code')
    name = data.get('name')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    is_active = data.get('is_active', station.is_active)
    variable_ids = data.get('variable_ids', [])

    if not code:
        return JsonResponse({
            'message': 'Code is required.'
        }, status=400)

    if not name:
        return JsonResponse({
            'message': 'Name is required.'
        }, status=400)

    if latitude in ['', None]:
        return JsonResponse({
            'message': 'Latitude is required.'
        }, status=400)

    if longitude in ['', None]:
        return JsonResponse({
            'message': 'Longitude is required.'
        }, status=400)

    try:
        latitude = float(latitude)
    except (TypeError, ValueError):
        return JsonResponse({
            'message': 'Latitude must be a valid number.'
        }, status=400)

    try:
        longitude = float(longitude)
    except (TypeError, ValueError):
        return JsonResponse({
            'message': 'Longitude must be a valid number.'
        }, status=400)

    if latitude < -90 or latitude > 90:
        return JsonResponse({
            'message': 'Latitude must be between -90 and 90.'
        }, status=400)

    if longitude < -180 or longitude > 180:
        return JsonResponse({
            'message': 'Longitude must be between -180 and 180.'
        }, status=400)

    if not isinstance(variable_ids, list):
        return JsonResponse({
            'message': 'Variables must be provided as a list.'
        }, status=400)

    try:
        variable_ids = [int(variable_id) for variable_id in variable_ids]
    except (TypeError, ValueError):
        return JsonResponse({
            'message': 'Invalid variable selection.'
        }, status=400)

    valid_variable_ids = list(
        Variable.objects.filter(
            id__in=variable_ids
        ).values_list(
            'id',
            flat=True
        )
    )

    station.code = code
    station.name = name
    station.latitude = latitude
    station.longitude = longitude
    station.is_active = is_active
    station.is_reference = True

    try:
        station.save()

    except IntegrityError:
        return JsonResponse({
            'message': f'A station with code "{code}" already exists.'
        }, status=400)

    # Find variables that are currently associated with this station.
    existing_variable_ids = set(
        StationVariable.objects.filter(
            station=station
        ).values_list(
            'variable_id',
            flat=True
        )
    )

    # Convert the newly selected variables to a set.
    new_variable_ids = set(valid_variable_ids)

    # Variables that were removed by the user.
    removed_variable_ids = existing_variable_ids - new_variable_ids

    # If variables were removed, also remove their threshold records.
    if removed_variable_ids:
        QcRangeThreshold.objects.filter(
            station=station,
            variable_id__in=removed_variable_ids
        ).delete()

        QcStepThreshold.objects.filter(
            station=station,
            variable_id__in=removed_variable_ids
        ).delete()

        QcPersistThreshold.objects.filter(
            station=station,
            variable_id__in=removed_variable_ids
        ).delete()

    # Remove StationVariable rows that are no longer selected.
    StationVariable.objects.filter(
        station=station
    ).exclude(
        variable_id__in=valid_variable_ids
    ).delete()

    # Add newly selected variables.
    for variable_id in valid_variable_ids:
        StationVariable.objects.get_or_create(
            station=station,
            variable_id=variable_id
        )

    return JsonResponse({
        'message': 'Reference station updated successfully.',
        'station': {
            'id': station.id,
            'code': station.code,
            'name': station.name,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'is_active': station.is_active,
            'variable_ids': valid_variable_ids,
        }
    })


@require_http_methods(["PUT"])
@wx_mapped_permission_required
@transaction.atomic
def toggle_reference_station_active(request, id):
    """
    Toggle a reference station between active and inactive.
    """

    station = get_object_or_404(
        Station,
        id=id,
        is_reference=True
    )

    station.is_active = not station.is_active
    station.save(update_fields=['is_active', 'updated_at'])

    return JsonResponse({
        'message': 'Reference station active status updated successfully.',
        'station': {
            'id': station.id,
            'is_active': station.is_active,
        }
    })


@require_http_methods(["DELETE"])
@wx_mapped_permission_required
@transaction.atomic
def delete_reference_station(request, id):
    """
    Delete a reference station.

    If the reference station is connected to other database records,
    return a friendly error instead of showing an IntegrityError page.
    """

    station = get_object_or_404(
        Station,
        id=id,
        is_reference=True
    )

    station_name = station.name

    try:
        station.delete()

    except (ProtectedError, IntegrityError):
        return JsonResponse({
            'message': (
                f'Cannot delete reference station "{station_name}" because it is '
                f'associated with other records in the database.'
            )
        }, status=400)

    return JsonResponse({
        'message': f'Reference station "{station_name}" deleted successfully.'
    })


@require_http_methods(["GET"])
@wx_mapped_permission_required
def load_reference_station_variables(request):
    """
    Load variables that can be associated with a reference station.
    """

    variables = Variable.objects.all().order_by('name')

    data = []

    for variable in variables:
        data.append({
            'id': variable.id,
            'name': variable.name,
            'symbol': variable.symbol,
            'display_name': f'{variable.name} ({variable.symbol})' if variable.symbol else variable.name,
        })

    return JsonResponse({
        'variables': data
    })


@require_http_methods(["GET"])
@wx_mapped_permission_required
def load_reference_station_thresholds(request, id):
    """
    Load Range, Step, and Persist thresholds for a reference station.

    Range thresholds are monthly.
    Step thresholds are one row per variable.
    Persist thresholds are one row per variable.

    Only variables associated with the reference station through
    StationVariable are returned.
    """

    station = get_object_or_404(
        Station,
        id=id,
        is_reference=True
    )

    months = get_months()

    station_variables = StationVariable.objects.filter(
        station=station
    ).select_related(
        'variable'
    ).order_by(
        'variable__name'
    )

    variables = []

    for station_variable in station_variables:
        variable = station_variable.variable

        variables.append({
            'id': variable.id,
            'name': variable.name,
            'symbol': variable.symbol,
            'display_name': f'{variable.name} ({variable.symbol})' if variable.symbol else variable.name,
        })

    variable_ids = [variable['id'] for variable in variables]

    range_thresholds = QcRangeThreshold.objects.filter(
        station=station,
        variable_id__in=variable_ids
    )

    step_thresholds = QcStepThreshold.objects.filter(
        station=station,
        variable_id__in=variable_ids
    )

    persist_thresholds = QcPersistThreshold.objects.filter(
        station=station,
        variable_id__in=variable_ids
    )

    range_threshold_map = {}

    for threshold in range_thresholds:
        range_threshold_map[
            (threshold.variable_id, threshold.month)
        ] = threshold

    step_threshold_map = {}

    for threshold in step_thresholds:
        step_threshold_map[threshold.variable_id] = threshold

    persist_threshold_map = {}

    for threshold in persist_thresholds:
        persist_threshold_map[threshold.variable_id] = threshold

    range_data = []
    step_data = []
    persist_data = []

    for variable in variables:
        variable_id = variable['id']

        # Range is monthly.
        for month_id in sorted(months.keys()):
            month_name = months[month_id]

            threshold = range_threshold_map.get(
                (variable_id, month_id)
            )

            range_data.append({
                'variable_id': variable_id,
                'variable_name': variable['name'],
                'variable_symbol': variable['symbol'],
                'month': month_id,
                'month_name': month_name,
                'range_min': threshold.range_min if threshold else None,
                'range_max': threshold.range_max if threshold else None,
            })

        # Step is one row per variable.
        step_threshold = step_threshold_map.get(variable_id)

        step_data.append({
            'variable_id': variable_id,
            'variable_name': variable['name'],
            'variable_symbol': variable['symbol'],
            'step_min': step_threshold.step_min if step_threshold else None,
            'step_max': step_threshold.step_max if step_threshold else None,
        })

        # Persist is one row per variable.
        persist_threshold = persist_threshold_map.get(variable_id)

        persist_data.append({
            'variable_id': variable_id,
            'variable_name': variable['name'],
            'variable_symbol': variable['symbol'],
            'minimum_variance': persist_threshold.minimum_variance if persist_threshold else None,
            'window': persist_threshold.window if persist_threshold else None,
        })

    response = {
        'station': {
            'id': station.id,
            'code': station.code,
            'name': station.name,
            'label': f'{station.name} - {station.code}',
        },
        'variables': variables,
        'months': [
            {
                'id': month_id,
                'name': months[month_id],
            }
            for month_id in sorted(months.keys())
        ],
        'thresholds': {
            'range': range_data,
            'step': step_data,
            'persist': persist_data,
        }
    }

    return JsonResponse(response, status=200)


@require_http_methods(["POST"])
@wx_mapped_permission_required
@transaction.atomic
def save_reference_station_thresholds(request, id):
    """
    Save Range, Step, and Persist thresholds for a reference station.

    Expected JSON body:

    {
        "range": [
            {
                "variable_id": 1,
                "month": 1,
                "range_min": 10,
                "range_max": 35
            }
        ],
        "step": [
            {
                "variable_id": 1,
                "step_min": -5,
                "step_max": 5
            }
        ],
        "persist": [
            {
                "variable_id": 1,
                "minimum_variance": 0.1,
                "window": 6
            }
        ]
    }

    Empty Range and Step values delete the existing threshold row.
    Empty Persist values delete the existing threshold row.
    If only one Persist value is provided, an error is returned because
    QcPersistThreshold requires both minimum_variance and window.
    """

    station = get_object_or_404(
        Station,
        id=id,
        is_reference=True
    )

    try:
        data = json.loads(request.body.decode('utf-8'))

    except json.JSONDecodeError:
        return JsonResponse({
            'message': 'Invalid JSON body.'
        }, status=400)

    range_rows = data.get('range', [])
    step_rows = data.get('step', [])
    persist_rows = data.get('persist', [])

    if not isinstance(range_rows, list):
        return JsonResponse({
            'message': 'Range thresholds must be provided as a list.'
        }, status=400)

    if not isinstance(step_rows, list):
        return JsonResponse({
            'message': 'Step thresholds must be provided as a list.'
        }, status=400)

    if not isinstance(persist_rows, list):
        return JsonResponse({
            'message': 'Persist thresholds must be provided as a list.'
        }, status=400)

    allowed_variable_ids = set(
        StationVariable.objects.filter(
            station=station
        ).values_list(
            'variable_id',
            flat=True
        )
    )

    months = get_months()
    valid_month_ids = set(months.keys())

    # Save Range thresholds.
    for row in range_rows:
        variable_id = row.get('variable_id')
        month_id = row.get('month')

        try:
            variable_id = int(variable_id)
            month_id = int(month_id)

        except (TypeError, ValueError):
            return JsonResponse({
                'message': 'Invalid range threshold variable or month.'
            }, status=400)

        if variable_id not in allowed_variable_ids:
            return JsonResponse({
                'message': 'One or more selected variables are not associated with this reference station.'
            }, status=400)

        if month_id not in valid_month_ids:
            return JsonResponse({
                'message': 'Invalid month selected for range threshold.'
            }, status=400)

        try:
            range_min = parse_optional_float(row.get('range_min'))
            range_max = parse_optional_float(row.get('range_max'))

        except ValueError:
            return JsonResponse({
                'message': 'Range threshold values must be valid numbers.'
            }, status=400)

        # If both are blank, delete the row if it exists.
        if range_min is None and range_max is None:
            QcRangeThreshold.objects.filter(
                station=station,
                variable_id=variable_id,
                month=month_id
            ).delete()

            continue

        threshold, created = QcRangeThreshold.objects.get_or_create(
            station=station,
            variable_id=variable_id,
            month=month_id
        )

        threshold.range_min = range_min
        threshold.range_max = range_max
        threshold.save()

    # Save Step thresholds.
    for row in step_rows:
        variable_id = row.get('variable_id')

        try:
            variable_id = int(variable_id)

        except (TypeError, ValueError):
            return JsonResponse({
                'message': 'Invalid step threshold variable.'
            }, status=400)

        if variable_id not in allowed_variable_ids:
            return JsonResponse({
                'message': 'One or more selected variables are not associated with this reference station.'
            }, status=400)

        try:
            step_min = parse_optional_float(row.get('step_min'))
            step_max = parse_optional_float(row.get('step_max'))

        except ValueError:
            return JsonResponse({
                'message': 'Step threshold values must be valid numbers.'
            }, status=400)

        # If both are blank, delete the row if it exists.
        if step_min is None and step_max is None:
            QcStepThreshold.objects.filter(
                station=station,
                variable_id=variable_id
            ).delete()

            continue

        threshold, created = QcStepThreshold.objects.get_or_create(
            station=station,
            variable_id=variable_id
        )

        threshold.step_min = step_min
        threshold.step_max = step_max
        threshold.save()

    # Save Persist thresholds.
    for row in persist_rows:
        variable_id = row.get('variable_id')

        try:
            variable_id = int(variable_id)

        except (TypeError, ValueError):
            return JsonResponse({
                'message': 'Invalid persist threshold variable.'
            }, status=400)

        if variable_id not in allowed_variable_ids:
            return JsonResponse({
                'message': 'One or more selected variables are not associated with this reference station.'
            }, status=400)

        try:
            minimum_variance = parse_optional_float(
                row.get('minimum_variance')
            )
            window = parse_optional_int(
                row.get('window')
            )

        except ValueError:
            return JsonResponse({
                'message': 'Persist threshold values must be valid numbers.'
            }, status=400)

        # If both are blank, delete the row if it exists.
        if minimum_variance is None and window is None:
            QcPersistThreshold.objects.filter(
                station=station,
                variable_id=variable_id
            ).delete()

            continue

        # Persist requires both values because the model fields are required.
        if minimum_variance is None or window is None:
            return JsonResponse({
                'message': 'Persist threshold requires both minimum variance and window.'
            }, status=400)

        threshold, created = QcPersistThreshold.objects.get_or_create(
            station=station,
            variable_id=variable_id,
            defaults={
                'minimum_variance': minimum_variance,
                'window': window,
            }
        )

        threshold.minimum_variance = minimum_variance
        threshold.window = window
        threshold.save()

    return JsonResponse({
        'message': 'Reference station thresholds saved successfully.'
    }, status=200)



class QualityControlView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/quality_control/validation.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.select_related('profile').exclude(is_reference=True)

        context['station_profile_list'] = StationProfile.objects.all()
        context['station_watershed_list'] = Watershed.objects.all()
        context['station_district_list'] = AdministrativeRegion.objects.all()

        return context



@csrf_exempt
@wx_mapped_permission_required 
def get_yearly_average(request):
    begin_date = request.GET.get('begin_date', None)
    end_date = request.GET.get('end_date', None)
    station_id = request.GET.get('station_id', None)
    variable_id = request.GET.get('variable_id', None)

    sql_string = """
        select avg(val.measured) as average, extract ('year' from month)::varchar as year, extract ('month' from month)::varchar as month, round(avg(val.measured)::decimal, 2)
        from generate_series(date_trunc('year', date %s),date_trunc('year', date %s) + interval '1 year' - interval '1 day', interval '1 month')  month
        left outer join raw_data as val on date_trunc('month', val.datetime) = date_trunc('month', month) and val.station_id = %s and val.variable_id = %s
        group by month
        order by month
    """
    where_parameters = [begin_date, end_date, station_id, variable_id]

    with connection.cursor() as cursor:
        cursor.execute(sql_string, where_parameters)
        rows = cursor.fetchall()

        years = {}
        for row in rows:
            if row[1] not in years.keys():
                years[row[1]] = {}

            if row[2] not in years[row[1]].keys():
                years[row[1]][row[2]] = row[3]

            years[row[1]][row[2]] = row[3]

        if not years:
            return JsonResponse({'message': 'No data found.'}, status=status.HTTP_400_BAD_REQUEST)

        return JsonResponse({'next': None, 'results': years}, safe=False, status=status.HTTP_200_OK)

    return JsonResponse({'message': 'Missing parameters.'}, status=status.HTTP_400_BAD_REQUEST)



class YearlyAverageReport(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/reports/yearly_average.html'
    


class StationVariableStationViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = StationVariable.objects.values('station__id', 'station__name', 'station__code').distinct('station__id')
    serializer_class = serializers.ReducedStationSerializer

    def get_queryset(self):
        queryset = StationVariable.objects.values('station__id', 'station__name', 'station__code').distinct(
            'station__id')

        variable_id = self.request.query_params.get('variable_id', None)

        if variable_id is not None:
            queryset = queryset.filter(variable__id=variable_id)

        return queryset

def last24_summary_list(request):
    search_type = request.GET.get('search_type', None)
    search_value = request.GET.get('search_value', None)

    response = {
        'results': [],
        'messages': [],
    }

    if search_type is not None and search_type == 'variable':
        query = """
            SELECT last24h.datetime,
                   var.name,
                   var.symbol,
                   var.sampling_operation_id,
                   unit.name,
                   unit.symbol,
                   last24h.min_value,
                   last24h.max_value,
                   last24h.avg_value,
                   last24h.sum_value,
                   last24h.latest_value,
                   last24h.station_id,
                   last24h.num_records
            FROM last24h_summary last24h
            JOIN wx_variable var ON last24h.variable_id=var.id
            JOIN wx_unit unit ON var.unit_id=unit.id
            WHERE last24h.variable_id=%s
        """

    with connection.cursor() as cursor:

        cursor.execute(query, [search_value])
        rows = cursor.fetchall()

        for row in rows:

            value = None

            if row[3] == 1:
                value = row[10]

            elif row[3] == 2:
                value = row[8]

            elif row[3] == 3:
                value = row[6]

            elif row[3] == 4:
                value = row[7]

            elif row[3] == 6:
                value = row[9]

            if value is None:
                print('variable {} does not have supported sampling operation {}'.format(row[1], row[3]))

            obj = {
                'station': row[11],
                'value': value,
                'min': round(row[6], 2),
                'max': round(row[7], 2),
                'avg': round(row[8], 2),
                'sum': round(row[9], 2),
                'count': row[12],
                'variable': {
                    'name': row[1],
                    'symbol': row[2],
                    'unit_name': row[4],
                    'unit_symbol': row[5]
                }
            }
            response['results'].append(obj)

        if response['results']:
            return JsonResponse(response, status=status.HTTP_200_OK)

    return JsonResponse(data={"message": "No data found."}, status=status.HTTP_404_NOT_FOUND)


def query_stationsmonintoring_chart(station_id, variable_id, data_type, datetime_picked):
    station = Station.objects.get(id=station_id)
    variable = Variable.objects.get(id=variable_id)

    date_start = str((datetime_picked - datetime.timedelta(days=6)).date())
    date_end = str(datetime_picked.date())

    if data_type=='Communication':
        query = """
            WITH
                date_range AS (
                    SELECT GENERATE_SERIES(%s::DATE - '6 day'::INTERVAL, %s::DATE, '1 day')::DATE AS date
                ),
                hs AS (
                    SELECT
                        datetime::date AS date,
                        COUNT(DISTINCT EXTRACT(hour FROM datetime)) AS amount
                    FROM
                        hourly_summary
                    WHERE
                        datetime >= %s::DATE - '7 day'::INTERVAL AND datetime < %s::DATE + '1 day'::INTERVAL
                        AND station_id = %s
                        AND variable_id = %s
                    GROUP BY 1
                )
            SELECT
                date_range.date,
                COALESCE(hs.amount, 0) AS amount,
                COALESCE((
                    SELECT color FROM wx_qualityflag
                    WHERE 
                        CASE 
                            WHEN COALESCE(hs.amount, 0) >= 20 THEN name = 'Good'
                            WHEN COALESCE(hs.amount, 0) >= 8 AND COALESCE(hs.amount, 0) <= 19 THEN name = 'Suspicious'
                            WHEN COALESCE(hs.amount, 0) >= 1 AND COALESCE(hs.amount, 0) <= 7 THEN name = 'Bad'
                            ELSE name = 'Not checked'
                        END
                ), '') AS color
            FROM
                date_range
                LEFT JOIN hs ON date_range.date = hs.date
            ORDER BY date_range.date
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (datetime_picked, datetime_picked, datetime_picked, datetime_picked, station_id, variable_id,))
            results = cursor.fetchall()

        chart_options = {
            'chart': {
                'type': 'column'
            },
            'title': {
                'text': " ".join(['Delay Data Track -',date_start,'to',date_end]) 
            },
            'subtitle': {
                'text': " ".join([station.name, station.code, '-', variable.name])
            },  
            'xAxis': {
                'categories': [r[0] for r in results]
            },
            'yAxis': {
                'title': None,
                'categories': [str(i)+'h' for i in range(25)],      
                'tickInterval': 2,
                'min': 0,
                'max': 24,
            },
            'series': [
                {
                    'name': 'Max comunication',
                    'data': [{'y': r[1], 'color': r[2]} for r in results],
                    'showInLegend': False
                }
            ],
            'plotOptions': {
                'column': {
                    'minPointLength': 10,
                    'pointPadding': 0.01,
                    'groupPadding': 0.05
                }
            }            
        }

    elif data_type=='Quality Control':
        flags = {
          'good': QualityFlag.objects.get(name='Good').color,
          'suspicious': QualityFlag.objects.get(name='Suspicious').color,
          'bad': QualityFlag.objects.get(name='Bad').color,
          'not_checked': QualityFlag.objects.get(name='Not checked').color,
        }        

        query = """
            WITH
              date_range AS (
                SELECT GENERATE_SERIES(%s::DATE - '6 day'::INTERVAL, %s::DATE, '1 day')::DATE AS date
              ),
              hs AS(              
                SELECT 
                    rd.datetime::DATE AS date
                    ,EXTRACT(hour FROM rd.datetime) AS hour
                    ,CASE
                      WHEN COUNT(CASE WHEN name='Bad' THEN 1 END) > 0 THEN('Bad')
                      WHEN COUNT(CASE WHEN name='Suspicious' THEN 1 END) > 0 THEN('Suspicious')
                      WHEN COUNT(CASE WHEN name='Good' THEN 1 END) > 0 THEN('Good')
                      ELSE ('Not checked')
                    END AS quality_flag
                FROM raw_data AS rd
                    LEFT JOIN wx_qualityflag qf ON rd.quality_flag = qf.id
                WHERE 
                    datetime >= %s::DATE - '7 day'::INTERVAL AND datetime < %s::DATE + '1 day'::INTERVAL
                    AND rd.station_id = %s
                    AND rd.variable_id = %s
                GROUP BY 1,2
                ORDER BY 1,2
              )
            SELECT
                date_range.date
                ,COUNT(CASE WHEN hs.quality_flag='Good' THEN 1 END) AS good
                ,COUNT(CASE WHEN hs.quality_flag='Suspicious' THEN 1 END) AS suspicious
                ,COUNT(CASE WHEN hs.quality_flag='Bad' THEN 1 END) AS bad
                ,COUNT(CASE WHEN hs.quality_flag='Not checked' THEN 1 END) AS not_checked
            FROM date_range
                LEFT JOIN hs ON date_range.date = hs.date
            GROUP BY 1
            ORDER BY 1
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (datetime_picked, datetime_picked, datetime_picked, datetime_picked, station_id, variable_id,))
            results = cursor.fetchall()

        series = [] 
        for i, flag in enumerate(flags):
            data = [r[i+1] for r in results]
            series.append({'name': flag.capitalize(), 'data': data, 'color': flags[flag]})

        chart_options = {
            'chart': {
                'type': 'column'
            },
            'title': {
                'text': " ".join(['Amount of Flags - ',date_start,'to',date_end]) 
            },
            'subtitle': {
                'text': " ".join([station.name, station.code, '-', variable.name])
            },            
            'xAxis': {
                'categories': [r[0] for r in results]
            },
            'yAxis': {
                'title': None,
                'categories': [str(i)+'h' for i in range(25)],      
                'tickInterval': 2,
                'min': 0,
                'max': 24,
            },
            'series': series,
            'plotOptions': {
                'column': {
                    'minPointLength': 10, 
                    'pointPadding': 0.01,
                    'groupPadding': 0.05
                }
            }            
        }            

    return chart_options


@require_http_methods(["GET"])   
@wx_mapped_permission_required 
def get_stationsmonitoring_chart_data(request, station_id, variable_id):
    time_type = request.GET.get('time_type', 'Last 24h')
    data_type = request.GET.get('data_type', 'Communication')
    date_picked = request.GET.get('date_picked', None)

    if time_type=='Last 24h':
        datetime_picked = datetime.datetime.now()
    else:
        datetime_picked = datetime.datetime.strptime(date_picked, '%Y-%m-%d')    

    # Fix a date to test
    # datetime_picked = datetime.datetime.strptime('2023-01-01', '%Y-%m-%d')

    chart_data = query_stationsmonintoring_chart(station_id, variable_id, data_type, datetime_picked)

    response = {
        "chartOptions": chart_data
    }

    return JsonResponse(response, status=status.HTTP_200_OK)


def get_station_lastupdate(station_id):
    stationvariables = StationVariable.objects.filter(station_id=station_id)
    
    last_data_datetimes = [sv.last_data_datetime for sv in stationvariables if sv.last_data_datetime is not None]

    if last_data_datetimes:
        lastupdate = max(last_data_datetimes)
        lastupdate = lastupdate.strftime("%Y-%m-%d %H:%M")
    else:
        lastupdate = None

    return lastupdate


def query_stationsmonitoring_station(data_type, time_type, date_picked, station_id):
    if time_type=='Last 24h':
        datetime_picked = datetime.datetime.now()
    else:
        datetime_picked = datetime.datetime.strptime(date_picked, '%Y-%m-%d')


    station_data = []

    if data_type=='Communication':
        query = """
            WITH hs AS (
                SELECT
                    station_id,
                    variable_id,
                    COUNT(DISTINCT EXTRACT(hour FROM datetime)) AS number_hours
                FROM
                    hourly_summary
                WHERE
                    datetime <= %s AND datetime >= %s - '24 hour'::INTERVAL AND station_id = %s
                GROUP BY 1, 2
            )
            SELECT
                v.id,
                v.name,
                hs.number_hours,
                ls.latest_value,
                u.symbol,                    
                CASE
                    WHEN hs.number_hours >= 20 THEN (
                        SELECT color FROM wx_qualityflag WHERE name = 'Good'
                    )
                    WHEN hs.number_hours >= 8 AND hs.number_hours <= 19 THEN(
                        SELECT color FROM wx_qualityflag WHERE name = 'Suspicious'
                    )
                    WHEN hs.number_hours >= 1 AND hs.number_hours <= 7 THEN(
                        SELECT color FROM wx_qualityflag WHERE name = 'Bad'
                    )
                    ELSE (
                        SELECT color FROM wx_qualityflag WHERE name = 'Not checked'
                    )
                END AS color                     
            FROM
                wx_stationvariable sv
                LEFT JOIN hs ON sv.station_id = hs.station_id AND sv.variable_id = hs.variable_id
                LEFT JOIN last24h_summary ls ON sv.station_id = ls.station_id AND sv.variable_id = ls.variable_id
                LEFT JOIN wx_variable v ON sv.variable_id = v.id
                LEFT JOIN wx_unit u ON v.unit_id = u.id
            WHERE
                sv.station_id = %s
            ORDER BY 1
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (datetime_picked, datetime_picked, station_id, station_id))
            results = cursor.fetchall()

        station_data = [{'id': r[0], 
                         'name': r[1], 
                         'amount': r[2] if r[2] is not None else 0, 
                         'latestvalue': " ".join([str(r[3]), str(r[4])]) if r[3] is not None else '---', 
                         'color': r[5]} for r in results]

    elif data_type=='Quality Control':
        query = """
            WITH h AS(
                SELECT 
                    rd.station_id
                    ,rd.variable_id
                    ,EXTRACT(hour FROM rd.datetime) AS hour
                    ,CASE
                      WHEN COUNT(CASE WHEN name='Bad' THEN 1 END) > 0 THEN('Bad')
                      WHEN COUNT(CASE WHEN name='Suspicious' THEN 1 END) > 0 THEN('Suspicious')
                      WHEN COUNT(CASE WHEN name='Good' THEN 1 END) > 0 THEN('Good')
                      ELSE ('Not checked')
                    END AS quality_flag
                FROM raw_data AS rd
                    LEFT JOIN wx_qualityflag qf ON rd.quality_flag = qf.id
                WHERE 
                    datetime <= %s
                    AND datetime >= %s - '24 hour'::INTERVAL
                    AND rd.station_id = %s
                GROUP BY 1,2,3
                ORDER BY 1,2,3
            )
            SELECT
                v.id
                ,v.name
                ,COUNT(CASE WHEN h.quality_flag='Good' THEN 1 END) AS good
                ,COUNT(CASE WHEN h.quality_flag='Suspicious' THEN 1 END) AS suspicious
                ,COUNT(CASE WHEN h.quality_flag='Bad' THEN 1 END) AS bad
                ,COUNT(CASE WHEN h.quality_flag='Not checked' THEN 1 END) AS not_checked
            FROM wx_stationvariable AS sv
                LEFT JOIN wx_variable AS v ON sv.variable_id = v.id
                LEFT JOIN h ON sv.station_id = h.station_id AND sv.variable_id = h.variable_id
            WHERE sv.station_id = %s
            GROUP BY 1,2
            ORDER BY 1,2
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (datetime_picked, datetime_picked, station_id, station_id))
            results = cursor.fetchall()

        station_data = [{'id': r[0], 
                         'name': r[1], 
                         'good': r[2],
                         'suspicious': r[3],
                         'bad': r[4],
                         'not_checked': r[5]} for r in results]
    elif data_type=='Visits':
        query = """
            WITH ordered_reports AS (
                SELECT 
                    id
                    ,station_id
                    ,visit_type_id
                    ,visit_date
                    ,initial_time
                    ,end_time
                    ,responsible_technician_id
                    ,next_visit_date
                    ,ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY visit_date DESC) AS rn
                FROM wx_maintenancereport
                WHERE status='A'AND station_id=%s
            )
            ,latest_report AS(
                SELECT 
                    *
                FROM ordered_reports
                WHERE rn=1    
            )
            SELECT 
                r.id
                ,p.name
                ,s.is_automatic
                ,r.visit_date
                ,v.name
                ,r.initial_time
                ,r.end_time
                ,t.name
                ,r.next_visit_date
            FROM latest_report r
            LEFT JOIN wx_station s ON r.station_id = s.id
            LEFT JOIN wx_stationprofile p ON p.id=s.profile_id
            LEFT JOIN wx_technician t ON r.responsible_technician_id = t.id
            LEFT JOIN wx_visittype v ON r.visit_type_id = v.id
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (station_id,))
            results = cursor.fetchall()
        
        station_data = [{'Maintenance Report ID': r[0],
                         'Station Profile': r[1],
                         'Station Type': 'Automatic' if r[2] else 'Manual',
                         'Visit Date': r[3],
                         'Visit Type': r[4],
                         'Initial Time': r[5],
                         'End Time': r[6],
                         'Responsible Technician': r[7],
                         'Next Visit Date': r[8]} for r in results]
        
        if len(station_data)>0:
            station_data = station_data[0]
        else:
            station_data = {}
    elif data_type=='Equipment':
        query = """
            WITH ordered_reports AS (
                SELECT 
                    id
                    ,ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY visit_date DESC) AS rn
                FROM wx_maintenancereport
                WHERE status='A'AND station_id=%s
            )
            ,latest_report AS(
                SELECT 
                    id
                FROM ordered_reports
                WHERE rn=1    
            )
            SELECT 
                em.name
                ,e.serial_number
                ,et.name
                ,se.classification
                ,q.color
            FROM latest_report r
            LEFT JOIN wx_maintenancereportequipment se ON se.maintenance_report_id=r.id
            LEFT JOIN wx_equipment e ON e.id = se.new_equipment_id
            LEFT JOIN wx_equipmenttype et ON et.id = se.equipment_type_id
            LEFT JOIN wx_equipmentmodel em ON e.model_id = em.id
            LEFT JOIN
                    wx_qualityflag q ON 
                    CASE
                        WHEN se.classification='N' THEN q.symbol = 'B'
                        WHEN se.classification='P' THEN q.symbol = 'S'
                        WHEN se.classification='F' THEN q.symbol = 'G'
                        ELSE q.symbol = '-'
                    END
            ORDER BY se.equipment_type_id, se.equipment_order
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (station_id,))
            results = cursor.fetchall()

        classification_dict = {
            'F':  'Fully Functional',
            'P':  'Partially Functional',
            'N':  'Not Functional'
        }
        
        station_data = [{'model': r[0],
                         'serial_number': r[1],
                         'equipment_type': r[2],
                         'classification': classification_dict[r[3]],
                         'color': r[4]} for r in results]        
    return station_data


@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_stationsmonitoring_station_data(request, id):
    data_type = request.GET.get('data_type', 'Communication')
    time_type = request.GET.get('time_type', 'Last 24h')
    date_picked = request.GET.get('date_picked', None)

    response = {
        'lastupdate': get_station_lastupdate(id),
        'station_data': query_stationsmonitoring_station(data_type, time_type, date_picked, id),
    }

    return JsonResponse(response, status=status.HTTP_200_OK)


def query_stationsmonitoring_map(data_type, time_type, date_picked):
    if time_type=='Last 24h':
        datetime_picked = datetime.datetime.now()
    else:
        datetime_picked = datetime.datetime.strptime(date_picked, '%Y-%m-%d')

    results = []

    if time_type=='Last 24h':
        if data_type=='Communication':
            query = """
                WITH hs AS (
                    SELECT
                        station_id
                        ,variable_id
                        ,COUNT(DISTINCT EXTRACT(hour FROM datetime)) AS number_hours
                    FROM
                        hourly_summary
                    WHERE
                        datetime <= %s AND datetime >= %s - '24 hour'::INTERVAL
                    GROUP BY 1, 2
                )
                SELECT
                    s.id
                    ,s.name
                    ,s.code
                    ,s.latitude
                    ,s.longitude
                    ,CASE
                        WHEN MAX(number_hours) >= 20 THEN (
                            SELECT color FROM wx_qualityflag WHERE name = 'Good'
                        )
                        WHEN MAX(number_hours) >= 8 AND MAX(number_hours) <= 19 THEN(
                            SELECT color FROM wx_qualityflag WHERE name = 'Suspicious'
                        )
                        WHEN MAX(number_hours) >= 1 AND MAX(number_hours) <= 7 THEN(
                            SELECT color FROM wx_qualityflag WHERE name = 'Bad'
                        )
                        ELSE (
                            SELECT color FROM wx_qualityflag WHERE name = 'Not checked'
                        )
                    END AS color    
                FROM wx_station AS s
                    LEFT JOIN wx_stationvariable AS sv ON s.id = sv.station_id
                    LEFT JOIN hs ON sv.station_id = hs.station_id AND sv.variable_id = hs.variable_id
                WHERE s.is_active
                GROUP BY 1, 2, 3, 4, 5
            """
        elif data_type=='Quality Control':
            query = """
                WITH qf AS (
                  SELECT
                    station_id
                    ,CASE
                      WHEN COUNT(CASE WHEN name='Bad' THEN 1 END) > 0 THEN(
                          SELECT color FROM wx_qualityflag WHERE name = 'Bad'
                      )
                      WHEN COUNT(CASE WHEN name='Suspicious' THEN 1 END) > 0 THEN(
                          SELECT color FROM wx_qualityflag WHERE name = 'Suspicious'
                      )   
                      WHEN COUNT(CASE WHEN name='Good' THEN 1 END) > 0 THEN(
                          SELECT color FROM wx_qualityflag WHERE name = 'Good'
                      )
                      ELSE (
                          SELECT color FROM wx_qualityflag WHERE name = 'Not checked'
                      )
                    END AS color
                  FROM
                    raw_data AS rd
                    LEFT JOIN wx_qualityflag AS qf ON rd.quality_flag = qf.id
                  WHERE
                        datetime <= %s AND datetime >= %s - '24 hour'::INTERVAL                
                  GROUP BY 1
                )
                SELECT
                  s.id
                  ,s.name
                  ,s.code
                  ,s.latitude
                  ,s.longitude
                  ,COALESCE(qf.color, (SELECT color FROM wx_qualityflag WHERE name = 'Not checked')) AS color
                FROM wx_station AS s
                LEFT JOIN qf ON s.id = qf.station_id
                WHERE s.is_active
            """
        elif data_type=='Visits':
            query = """
                WITH ordered_reports AS (
                    SELECT 
                        id
                        ,station_id
                        ,visit_date
                        ,next_visit_date
                        ,ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY visit_date DESC) AS rn
                    FROM wx_maintenancereport
                    WHERE status='A'
                )
                ,latest_reports AS(
                    SELECT 
                        id
                        ,station_id
                        ,visit_date
                        ,next_visit_date
                        ,rn
                    FROM ordered_reports
                    WHERE rn=1    
                )
                SELECT 
                    s.id
                    ,s.name
                    ,s.code
                    ,s.latitude
                    ,s.longitude                    
                    ,q.color AS color
                FROM wx_station s
                LEFT JOIN latest_reports l ON l.station_id = s.id
                LEFT JOIN wx_qualityflag q ON
                    CASE
                        WHEN l.next_visit_date IS NULL THEN q.symbol = '-'
                        WHEN l.next_visit_date > NOW() THEN q.symbol = 'G'
                        WHEN l.next_visit_date >= NOW() - INTERVAL '1 month' AND l.next_visit_date <= NOW() THEN q.symbol = 'S'
                        WHEN l.next_visit_date < NOW() - INTERVAL '1 month' THEN q.symbol = 'B'
                    END
                WHERE s.is_active
            """
        elif data_type == 'Equipment':
            query = """
                WITH ordered_reports AS (
                    SELECT 
                        id
                        ,station_id
                        ,visit_date
                        ,next_visit_date
                        ,ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY visit_date DESC) AS rn
                    FROM wx_maintenancereport
                    WHERE status='A'
                )
                ,latest_reports AS(
                    SELECT 
                        id
                        ,station_id
                        ,visit_date
                        ,next_visit_date
                        ,rn
                    FROM ordered_reports
                    WHERE rn=1    
                )
                ,station_equipment AS (
                    SELECT 
                        r.station_id
                        ,COUNT(*) AS count_eq
                        ,SUM(CASE WHEN re.classification = 'F' THEN 1 ELSE 0 END) AS count_f
                        ,SUM(CASE WHEN re.classification = 'P' THEN 1 ELSE 0 END) AS count_p
                        ,SUM(CASE WHEN re.classification = 'N' THEN 1 ELSE 0 END) AS count_n
                    FROM latest_reports r
                    LEFT JOIN wx_maintenancereportequipment re 
                        ON  re.maintenance_report_id = r.id
                    GROUP BY r.station_id
                )
                SELECT
                    s.id,
                    s.name,
                    s.code,
                    s.latitude,
                    s.longitude,
                    q.color AS color
                FROM
                    wx_station s
                LEFT JOIN
                    station_equipment se ON se.station_id = s.id
                LEFT JOIN
                    wx_qualityflag q ON 
                    CASE
                        WHEN se.count_eq IS NULL THEN q.symbol = '-'
                        WHEN se.count_n > 0 THEN q.symbol = 'B'
                        WHEN se.count_p > 0 THEN q.symbol = 'S'
                        ELSE q.symbol = 'G'
                    END
                WHERE
                    s.is_active
            """            
            

        if data_type in ['Communication', 'Quality Control']:
            with connection.cursor() as cursor:
                cursor.execute(query, (datetime_picked, datetime_picked, ))
                results = cursor.fetchall()
        elif data_type in ['Visits', 'Equipment']:
            with connection.cursor() as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
    else:
        if data_type=='Communication':
            query = """
                WITH hs AS (
                    SELECT
                        station_id
                        ,variable_id
                        ,COUNT(DISTINCT EXTRACT(hour FROM datetime)) AS number_hours
                    FROM
                        hourly_summary
                    WHERE
                        datetime <= %s AND datetime >= %s - '24 hour'::INTERVAL
                    GROUP BY 1, 2
                )
                SELECT
                    s.id
                    ,s.name
                    ,s.code
                    ,s.latitude
                    ,s.longitude
                    ,CASE
                        WHEN MAX(number_hours) >= 20 THEN (
                            SELECT color FROM wx_qualityflag WHERE name = 'Good'
                        )
                        WHEN MAX(number_hours) >= 8 AND MAX(number_hours) <= 19 THEN(
                            SELECT color FROM wx_qualityflag WHERE name = 'Suspicious'
                        )
                        WHEN MAX(number_hours) >= 1 AND MAX(number_hours) <= 7 THEN(
                            SELECT color FROM wx_qualityflag WHERE name = 'Bad'
                        )
                        ELSE (
                            SELECT color FROM wx_qualityflag WHERE name = 'Not checked'
                        )
                    END AS color    
                FROM wx_station AS s
                    LEFT JOIN wx_stationvariable AS sv ON s.id = sv.station_id
                    LEFT JOIN hs ON sv.station_id = hs.station_id AND sv.variable_id = hs.variable_id
                WHERE s.begin_date <= %s AND (s.end_date IS NULL OR s.end_date >= %s)
                GROUP BY 1, 2, 3, 4, 5
            """
        elif data_type=='Quality Control':
            query = """
                WITH qf AS (
                  SELECT
                    station_id
                    ,CASE
                      WHEN COUNT(CASE WHEN name='Bad' THEN 1 END) > 0 THEN(
                          SELECT color FROM wx_qualityflag WHERE name = 'Bad'
                      )
                      WHEN COUNT(CASE WHEN name='Suspicious' THEN 1 END) > 0 THEN(
                          SELECT color FROM wx_qualityflag WHERE name = 'Suspicious'
                      )   
                      WHEN COUNT(CASE WHEN name='Good' THEN 1 END) > 0 THEN(
                          SELECT color FROM wx_qualityflag WHERE name = 'Good'
                      )
                      ELSE (
                          SELECT color FROM wx_qualityflag WHERE name = 'Not checked'
                      )
                    END AS color
                  FROM
                    raw_data AS rd
                    LEFT JOIN wx_qualityflag AS qf ON rd.quality_flag = qf.id
                  WHERE
                        datetime <= %s AND datetime >= %s - '24 hour'::INTERVAL                
                  GROUP BY 1
                )
                SELECT
                  s.id
                  ,s.name
                  ,s.code
                  ,s.latitude
                  ,s.longitude
                  ,COALESCE(qf.color, (SELECT color FROM wx_qualityflag WHERE name = 'Not checked')) AS color
                FROM wx_station AS s
                LEFT JOIN qf ON s.id = qf.station_id
                WHERE s.begin_date <= %s AND (s.end_date IS NULL OR s.end_date >= %s)
            """

        if data_type in ['Communication', 'Quality Control']:
            with connection.cursor() as cursor:
                cursor.execute(query, (datetime_picked, datetime_picked, datetime_picked, datetime_picked, ))
                results = cursor.fetchall()

    return results


@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_stationsmonitoring_map_data(request):
    time_type = request.GET.get('time_type', 'Last 24h')
    data_type = request.GET.get('data_type', 'Communication')
    date_picked = request.GET.get('date_picked', None)

    results = query_stationsmonitoring_map(data_type, time_type, date_picked)

    response = {
        'stations': [{'id': r[0],
                      'name': r[1],
                      'code': r[2],
                      'position': [r[3], r[4]],
                      'color': r[5]} for r in results ],
    }

    return JsonResponse(response, status=status.HTTP_200_OK)



class stationsmonitoring_form(LoginRequiredMixin, TemplateView):
    template_name = "wx/stations/stations_monitoring.html"

    def get_context_data(self, **kwargs):
        # call the base implementation to get a context dict
        context = super().get_context_data(**kwargs)

        # add flags
        context['flags'] = {
            'good': QualityFlag.objects.get(name='Good').color,
            'suspicious': QualityFlag.objects.get(name='Suspicious').color,
            'bad': QualityFlag.objects.get(name='Bad').color,
            'not_checked': QualityFlag.objects.get(name='Not checked').color,
        }
        return context


class ComingSoonView(LoginRequiredMixin, TemplateView):
    template_name = "coming-soon.html"


class UnderMaintenanceView(TemplateView):
    template_name = "under-maintenance.html"


# not authorized view, if user fails permision checks
class NotAuthView(LoginRequiredMixin, TemplateView):
    template_name = "not_authorized.html"


class get_wave_data_analysis(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/products/wave_data.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        variable = Variable.objects.get(name="Sea Level") # Sea Level
        station_ids = HighFrequencyData.objects.filter(variable_id=variable.id).values('station_id').distinct()

        station_list = Station.objects.filter(id__in=station_ids).exclude(is_reference=True)

        context['station_list'] = station_list        

        return context



def format_wave_data_var(variable_id, data):
    variable = Variable.objects.get(id=variable_id)
    measurement_variable = MeasurementVariable.objects.get(id=variable.measurement_variable_id)
    unit = Unit.objects.get(id=variable.unit_id)

    formated_data = []
    for entry in data:
        if type(entry) is not dict:
            entry = entry.__dict__

        formated_entry = {
            "station": entry['station_id'],
            "date": entry['datetime'].timestamp()*1000,
            "measurementvariable": measurement_variable.name,
            "value": entry['measured'],
            "quality_flag": "Not checked",
            "flag_color": "#FFFFFF",            
        }
        formated_data.append(formated_entry)

    final_data = {
        "color": variable.color,
        "default_representation": variable.default_representation,
        "data": formated_data,
        "unit": unit.symbol,
    }
    return final_data

def get_wave_components(data_slice, component_number):
    wave_list = fft_decompose(data_slice)    
    wave_list.sort(key=lambda W: abs(W.height), reverse=True)
    wave_components = wave_list[:component_number]
    return wave_components

def get_wave_component_ref_variables(i):
    SYSTEM_COMPONENT_NUMBER = 5 # Number of wave components in the system

    ref_number = i % SYSTEM_COMPONENT_NUMBER
    ref_number += 1

    amp_ref_name = 'Wave Component ' + str(ref_number) + ' Amplitude'
    amp_ref = Variable.objects.get(name=amp_ref_name)

    frq_ref_name = 'Wave Component ' + str(ref_number) + ' Frequency'
    frq_ref = Variable.objects.get(name=frq_ref_name)

    pha_ref_name = 'Wave Component ' + str(ref_number) + ' Phase'
    pha_ref = Variable.objects.get(name=pha_ref_name)

    return amp_ref, frq_ref, pha_ref

def get_wave_component_name_and_symbol(i, component_type):
    if component_type=='Amplitude':
        name = 'Wave Component ' + str(i) + ' Amplitude'
        symbol = 'WV'+str(i)+'AMP'
    elif component_type=='Frequency':
        name = 'Wave Component ' + str(i) + ' Frequency'
        symbol = 'WV'+str(i)+'FRQ'
    elif component_type=='Phase':
        name = 'Wave Component ' + str(i) + ' Phase'
        symbol = 'WV'+str(i)+'PHA'
    else:
        name = 'Component Type Error'
        symbol = 'Component Type Error'

    return name, symbol

def create_aggregated_data(component_number):
    wv_amp_mv = MeasurementVariable.objects.get(name='Wave Amplitude')
    wv_frq_mv = MeasurementVariable.objects.get(name='Wave Frequency')
    wv_pha_mv = MeasurementVariable.objects.get(name='Wave Phase')
    sl_mv = MeasurementVariable.objects.get(name='Sea Level')

    sl_min = Variable.objects.get(name = 'Sea Level [MIN]')
    sl_max = Variable.objects.get(name = 'Sea Level [MAX]')
    sl_avg = Variable.objects.get(name = 'Sea Level [AVG]')
    sl_std = Variable.objects.get(name = 'Sea Level [STDV]')
    sl_swh = Variable.objects.get(name = 'Significant Wave Height')

    sl_variables = [sl_min, sl_max, sl_avg, sl_std, sl_swh]


    aggregated_data = {
        wv_amp_mv.name: {},
        wv_frq_mv.name: {},
        wv_pha_mv.name: {},
        sl_mv.name: {}
    }

    for sl_variable in sl_variables:
        aggregated_data[sl_mv.name][sl_variable.name] = {
            'ref_variable_id': sl_variable.id,         
            'symbol': sl_variable.symbol,
            'data': []    
        }    

    for i in range(component_number):
        amp_ref, frq_ref, pha_ref = get_wave_component_ref_variables(i)

        amp_name, amp_symbol = get_wave_component_name_and_symbol(i+1, 'Amplitude')
        frq_name, frq_symbol = get_wave_component_name_and_symbol(i+1, 'Frequency')
        pha_name, pha_symbol = get_wave_component_name_and_symbol(i+1, 'Phase')

        aggregated_data[wv_amp_mv.name][amp_name] = {
            'ref_variable_id': amp_ref.id,         
            'symbol': amp_symbol,
            'data': []            
        }
        aggregated_data[wv_frq_mv.name][frq_name] = {        
            'ref_variable_id': frq_ref.id,         
            'symbol': frq_symbol,
            'data': []
        }
        aggregated_data[wv_pha_mv.name][pha_name] = {
            'ref_variable_id': pha_ref.id,         
            'symbol': pha_symbol,
            'data': []            
        }

    return aggregated_data

def append_in_aggregated_data(aggregated_data, datetime, station_id, mv_name, var_name, value):
    entry = {
        'measured': value,
        'datetime': datetime,
        'station_id': station_id,
    }

    aggregated_data[mv_name][var_name]['data'].append(entry)

    return aggregated_data

def get_wave_aggregated_data(station_id, data, initial_datetime, range_interval, calc_interval, component_number):
    wv_amp_mv = MeasurementVariable.objects.get(name='Wave Amplitude')
    wv_frq_mv = MeasurementVariable.objects.get(name='Wave Frequency')
    wv_pha_mv = MeasurementVariable.objects.get(name='Wave Phase')
    sl_mv = MeasurementVariable.objects.get(name='Sea Level')

    sl_min = Variable.objects.get(name = 'Sea Level [MIN]')
    sl_max = Variable.objects.get(name = 'Sea Level [MAX]')
    sl_avg = Variable.objects.get(name = 'Sea Level [AVG]')
    sl_std = Variable.objects.get(name = 'Sea Level [STDV]')
    sl_swh = Variable.objects.get(name = 'Significant Wave Height')

    aggregated_data = create_aggregated_data(component_number)

    for i in range(math.floor(range_interval/calc_interval)):
        ini_datetime_slc = initial_datetime+datetime.timedelta(minutes=i*calc_interval)
        end_datetime_slc = initial_datetime+datetime.timedelta(minutes=(i+1)*calc_interval)

        data_slice = [entry.measured for entry in data if ini_datetime_slc < entry.datetime <= end_datetime_slc]

        if len(data_slice) > 0:
            aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, sl_mv.name, sl_min.name, np.min(data_slice))
            aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, sl_mv.name, sl_max.name, np.max(data_slice))
            aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, sl_mv.name, sl_avg.name, np.mean(data_slice))
            aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, sl_mv.name, sl_std.name, np.std(data_slice))
            aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, sl_mv.name, sl_swh.name, 4*np.std(data_slice))

            wave_components = get_wave_components(data_slice, component_number)
            for j, wave_component in enumerate(wave_components):
                amp_name, amp_symbol = get_wave_component_name_and_symbol(j+1, 'Amplitude')
                frq_name, frq_symbol = get_wave_component_name_and_symbol(j+1, 'Frequency')
                pha_name, pha_symbol = get_wave_component_name_and_symbol(j+1, 'Phase')

                amp_value = wave_component.height
                frq_value = wave_component.frequency
                pha_value = math.degrees(wave_component.phase_rad) % 360

                aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, wv_amp_mv.name, amp_name, amp_value)
                aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, wv_frq_mv.name, frq_name, frq_value)
                aggregated_data = append_in_aggregated_data(aggregated_data, end_datetime_slc, station_id, wv_pha_mv.name, pha_name, pha_value)

    return aggregated_data

def add_wave_aggregated_data(dataset, aggregated_data):
    for mv_name in aggregated_data.keys():
        dataset['results'][mv_name] = {}
        for var_name in aggregated_data[mv_name].keys():
            variable_id = aggregated_data[mv_name][var_name]['ref_variable_id']
            variable_data = aggregated_data[mv_name][var_name]['data']
            variable_symbol = aggregated_data[mv_name][var_name]['symbol']

            dataset['results'][mv_name][variable_symbol] = format_wave_data_var(variable_id, variable_data)

    return dataset    

def create_wave_dataset(station_id, sea_data, initial_datetime, range_interval, calc_interval, component_number):
    sea_level = Variable.objects.get(name='Sea Level')
    sea_level_mv = MeasurementVariable.objects.get(name='Sea Level')

    dataset  = {
        "results": {
            sea_level_mv.name+' Raw': {
                sea_level.symbol: format_wave_data_var(sea_level.id, sea_data),
            }
        },
        "messages": [],
    }

    wave_component_data = get_wave_aggregated_data(station_id,
                                                  sea_data,
                                                  initial_datetime,
                                                  range_interval,
                                                  calc_interval,
                                                  component_number)

 
    dataset = add_wave_aggregated_data(dataset, wave_component_data)

    return dataset

def create_wave_chart(dataset):
    charts = {}

    for element_name, element_data in dataset['results'].items():

        chart = {
            'chart': {
                'type': 'pie',
                'zoomType': 'xy'
            },
            'title': {'text': element_name},
            'xAxis': {
                'type': 'datetime',
                'dateTimeLabelFormats': {
                    'month': '%e. %b',
                    'year': '%b'
                },
                'title': {
                    'text': 'Date'
                }
            },
            'yAxis': [],
            'exporting': {
                'showTable': True
            },
            'series': []
        }

        opposite = False
        y_axis_unit_dict = {}
        for variable_name, variable_data in element_data.items():
            current_unit = variable_data['unit']
            if current_unit not in y_axis_unit_dict.keys():
                chart['yAxis'].append({
                    'labels': {
                        'format': '{value} ' + variable_data['unit'],
                    },
                    'title': {
                        'text': None
                    },
                    'opposite': opposite
                })
                y_axis_unit_dict[current_unit] = len(chart['yAxis']) - 1
                opposite = not opposite

            current_y_axis_index = y_axis_unit_dict[current_unit]
            data = []
            for record in variable_data['data']:
                data.append({
                    'x': record['date'],
                    'y': record['value'],
                })

            chart['series'].append({
                'name': variable_name,
                'color': variable_data['color'],
                'type': variable_data['default_representation'],
                'unit': variable_data['unit'],
                'data': data,
                'yAxis': current_y_axis_index
            })
            chart['chart']['type'] = variable_data['default_representation'],

        charts[slugify(element_name)] = chart

    return charts

@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_wave_data(request):
    station_id = request.GET.get('station_id', None)
    initial_date = request.GET.get('initial_date', None)
    initial_time = request.GET.get('initial_time', None)
    range_interval = request.GET.get('range_interval', None)
    calc_interval = request.GET.get('calc_interval', None)
    component_number = request.GET.get('component_number', None)

    tz_client = request.GET.get('tz_client', None)
    tz_settings = pytz.timezone(settings.TIMEZONE_NAME)

    initial_datetime_str = initial_date+' '+initial_time
    initial_datetime = datetime_constructor.strptime(initial_datetime_str, '%Y-%m-%d %H:%M')
    initial_datetime = pytz.timezone(tz_client).localize(initial_datetime)
    initial_datetime = initial_datetime.astimezone(tz_settings)

    range_intervals = {'30min': 30, "1h": 60, "3h": 180,}

    if range_interval in range_intervals.keys():
        range_interval = range_intervals[range_interval]
    else:
        response = {"message": "Not valid interval."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)

    calc_intervals = {'1min': 1, '5min': 5, '10min': 10, '15min': 15,}

    if calc_interval in calc_intervals.keys():
        calc_interval = calc_intervals[calc_interval]
    else:
        response = {"message": "Not valid calc interval."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)

    station_id = int(station_id)
    component_number = int(component_number)

    final_datetime = initial_datetime + datetime.timedelta(minutes=range_interval)

    variable = Variable.objects.get(name="Sea Level") # Sea Level
    sea_data = HighFrequencyData.objects.filter(variable_id=variable.id,
                                                station_id=station_id,
                                                datetime__gt=initial_datetime,
                                                datetime__lte=final_datetime).order_by('datetime')

    dataset  = {"results": {}, "messages": []}

    if len(sea_data) > 0:
        dataset = create_wave_dataset(station_id, sea_data, initial_datetime,
                                      range_interval, calc_interval, component_number)

    charts = create_wave_chart(dataset)

    return JsonResponse(charts)


class get_equipment_inventory(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/maintenance_reports/equipment_inventory.html'


def get_value(variable):
    if variable is None:
        return '---'
    return variable


def equipment_classification(classification):
    if classification == 'F':
        return 'Fully Functional'
    elif classification == 'P':
        return 'Partially Functional'
    elif classification == 'N':
        return 'Not Functional'
    return None


def is_equipment_available(equipment, station):
    new_maintenance_report_eqs = MaintenanceReportEquipment.objects.filter(new_equipment_id=equipment.id).order_by('-maintenance_report__visit_date')
    old_maintenance_report_eqs = MaintenanceReportEquipment.objects.filter(old_equipment_id=equipment.id).order_by('-maintenance_report__visit_date')

    new_maintenance_report_eq = new_maintenance_report_eqs.first()
    old_maintenance_report_eq = old_maintenance_report_eqs.first()

    new_maintenance_report = new_maintenance_report_eq.maintenance_report if new_maintenance_report_eq else None
    old_maintenance_report = old_maintenance_report_eq.maintenance_report if old_maintenance_report_eq else None

    if old_maintenance_report:
        if old_maintenance_report.status != 'A' and old_maintenance_report.station_id != station.id:
            return False
    if new_maintenance_report and old_maintenance_report:
        if new_maintenance_report.visit_date >= old_maintenance_report.visit_date:
            return False
    elif new_maintenance_report:
        return False
    return True


def get_equipment_location(equipment):
    maintenance_reports_new = MaintenanceReportEquipment.objects.filter(new_equipment_id=equipment.id).order_by('-maintenance_report__visit_date')
    maintenance_reports_old = MaintenanceReportEquipment.objects.filter(old_equipment_id=equipment.id).order_by('-maintenance_report__visit_date')
    
    new_maintenance_report = maintenance_reports_new.first()
    old_maintenance_report = maintenance_reports_old.first()

    if new_maintenance_report and old_maintenance_report:
        if new_maintenance_report.maintenance_report.visit_date >= old_maintenance_report.maintenance_report.visit_date:
            return new_maintenance_report.maintenance_report.station
    elif new_maintenance_report:
        return new_maintenance_report.maintenance_report.station
    return None


@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_equipment_inventory_data(request):
    """
    Returns all data required to render the Equipment Inventory page.

    This endpoint intentionally returns BOTH:
    1. Inventory data (actual equipment rows)
    2. Lookup / metadata tables (types, models, manufacturers, etc.)

    These are kept separate on purpose:
    - Inventory data is optimized for performance
    - Lookup data must include *unused* rows for dropdowns
    """

    # MAIN INVENTORY QUERY
    # IMPORTANT:
    # - select_related ONLY pulls related rows that are actually used
    #   by existing Equipment records.
    # - It does NOT replace separate queries for lookup tables.
    #
    equipments = (
        Equipment.objects
        .select_related(
            "equipment_type",  
            "model",           
            "manufacturer",     
            "funding_source",   
            "location",         # FK → Location (nullable)
        )
        .order_by("equipment_type__name", "serial_number")
    )

    # This list will be serialized directly to JSON.
    equipment_list = []

    # SERIALIZE EACH EQUIPMENT ROW
    for equipment in equipments:

        equipment_list.append({
            # Primary identifiers
            "equipment_id": equipment.id,

            # Equipment type (FK). equipment type can be Null / None
            "equipment_type": equipment.equipment_type.name if equipment.equipment_type else None,
            "equipment_type_id": equipment.equipment_type.id if equipment.equipment_type else None,

            # Funding source (FK). Funding source can be Null / None
            "funding_source": equipment.funding_source.name if equipment.funding_source else None,
            "funding_source_id": equipment.funding_source.id if equipment.funding_source else None,

            # Manufacturer (FK). Manufacturer can be Null / None
            "manufacturer": equipment.manufacturer.name if equipment.manufacturer else None,
            "manufacturer_id": equipment.manufacturer.id if equipment.manufacturer else None,

            # Equipment model (FK). Models can be Null / None
            "equipment_model_id": equipment.model.id if equipment.model else None,
            "equipment_model": equipment.model.name if equipment.model else None,

            # Equipment fields
            "serial_number": equipment.serial_number,
            "acquisition_date": equipment.acquisition_date,
            "first_deploy_date": equipment.first_deploy_date,
            "last_calibration_date": equipment.last_calibration_date,
            "next_calibration_date": equipment.next_calibration_date,
            "decommission_date": equipment.decommission_date,
            "last_deploy_date": equipment.last_deploy_date,

            # Location (nullable FK)
            # If no location exists, we treat the equipment as being
            # in the office.
            "location": equipment.location.name if equipment.location else "Office",
            "location_id": equipment.location_id if equipment.location else None,

            # Classification
            # classification is stored as a short code (e.g. 'F', 'P', 'N')
            # equipment_classification() converts it into a human-readable label
            "classification": equipment_classification(equipment.classification),
            "classification_id": equipment.classification,
        })

    # STATIC / ENUM-LIKE DATA
    # These classifications are not stored in a table and are used
    # primarily for UI rendering (dropdowns, labels, etc.).
    equipment_classifications = [
        {"name": "Fully Functional", "id": "F"},
        {"name": "Partially Functional", "id": "P"},
        {"name": "Not Functional", "id": "N"},
    ]

    # RESPONSE PAYLOAD
    # IMPORTANT DESIGN NOTE:
    # - Dropdowns must include unused rows
    # - New equipment may reference currently-unused models/types
    response = {
        # Inventory data (optimized via select_related)
        "equipment": equipment_list,

        # Lookup / metadata tables (complete datasets)
        "equipment_types": list(EquipmentType.objects.values()),
        "manufacturers": list(Manufacturer.objects.values()),
        "funding_sources": list(FundingSource.objects.values()),
        "equipment_models": list(EquipmentModel.objects.values()),

        # Stations formatted specifically for UI display
        "stations": [
            {"name": f"{s.name} - {s.code}", "id": s.id}
            for s in Station.objects.exclude(is_reference=True)
        ],

        # Static classification list
        "equipment_classifications": equipment_classifications,
    }

    return JsonResponse(response, status=status.HTTP_200_OK)



@require_http_methods(["POST"])
@wx_mapped_permission_required
def create_equipment(request):
    """
    Creates a new Equipment record.
    """

    # READ INPUT DATA
    equipment_type_id = request.GET.get("equipment_type")
    manufacturer_id = request.GET.get("manufacturer")
    funding_source_id = request.GET.get("funding_source")
    equipment_model_id = request.GET.get("model")
    serial_number = request.GET.get("serial_number")

    acquisition_date = request.GET.get("acquisition_date")
    first_deploy_date = request.GET.get("first_deploy_date")
    last_calibration_date = request.GET.get("last_calibration_date")
    next_calibration_date = request.GET.get("next_calibration_date")
    decommission_date = request.GET.get("decommission_date")
    last_deploy_date = request.GET.get("last_deploy_date")

    location_id = request.GET.get("location")
    classification = request.GET.get("classification")

    # BASIC VALIDATION (MINIMUM REQUIRED FIELDS)
    if not equipment_type_id or not serial_number:
        return JsonResponse(
            {"message": "equipment_type and serial_number are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # CREATE EQUIPMENT
    try:
        equipment = Equipment.objects.create(
            # ForeignKeys assigned by *_id to avoid extra queries
            equipment_type_id=equipment_type_id,
            manufacturer_id=manufacturer_id,
            funding_source_id=funding_source_id,
            model_id=equipment_model_id,
            location_id=location_id,

            # Scalar fields
            serial_number=serial_number,
            acquisition_date=acquisition_date,
            first_deploy_date=first_deploy_date,
            last_calibration_date=last_calibration_date,
            next_calibration_date=next_calibration_date,
            decommission_date=decommission_date,
            last_deploy_date=last_deploy_date,
            classification=classification,

            # Timestamps should ideally be handled by the model:
            # created_at = auto_now_add
            # updated_at = auto_now
        )

    except IntegrityError:
        # DUPLICATE EQUIPMENT HANDLING
        # If we reach here, the database rejected the insert due to a
        # uniqueness violation.
        # This is safer and faster than doing a pre-check SELECT.
        return JsonResponse(
            {
                "message": (
                    "An equipment with this equipment type and serial number "
                    "already exists."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # SUCCESS RESPONSE
    return JsonResponse(
        {"equipment_id": equipment.id},
        status=status.HTTP_201_CREATED,
    )


@require_http_methods(["POST"])
@wx_mapped_permission_required
def update_equipment(request):
    """
    Updates an existing Equipment record.
    """

    # READ INPUT DATA
    equipment_id = request.GET.get("equipment_id")
    equipment_type_id = request.GET.get("equipment_type")
    equipment_model_id = request.GET.get("model")
    manufacturer_id = request.GET.get("manufacturer")
    funding_source_id = request.GET.get("funding_source")
    serial_number = request.GET.get("serial_number")
    location_id = request.GET.get("location")

    # Optional date fields
    acquisition_date = request.GET.get("acquisition_date")
    first_deploy_date = request.GET.get("first_deploy_date")
    last_calibration_date = request.GET.get("last_calibration_date")
    next_calibration_date = request.GET.get("next_calibration_date")
    decommission_date = request.GET.get("decommission_date")
    last_deploy_date = request.GET.get("last_deploy_date")
    classification = request.GET.get("classification")

    # BASIC VALIDATION
    if not equipment_id:
        return JsonResponse(
            {"message": "equipment_id is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # FETCH EQUIPMENT ONCE
    # We retrieve the target row exactly once.
    # If it does not exist, we fail immediately.
    try:
        equipment = Equipment.objects.get(id=equipment_id)
    except Equipment.DoesNotExist:
        return JsonResponse(
            {"message": "Equipment not found"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # UPDATE FIELDS
    # IMPORTANT:
    # - We do NOT check for duplicate (equipment_type, serial_number)
    # - The database enforces this via unique_together
    # - If a conflict exists, save() will raise IntegrityError
    equipment.equipment_type_id = equipment_type_id
    equipment.manufacturer_id = manufacturer_id
    equipment.funding_source_id = funding_source_id
    equipment.model_id = equipment_model_id
    equipment.location_id = location_id

    equipment.serial_number = serial_number
    equipment.acquisition_date = acquisition_date
    equipment.first_deploy_date = first_deploy_date
    equipment.last_calibration_date = last_calibration_date
    equipment.next_calibration_date = next_calibration_date
    equipment.decommission_date = decommission_date
    equipment.last_deploy_date = last_deploy_date
    equipment.classification = classification

    # SAVE (DB ENFORCES UNIQUENESS)
    try:
        equipment.save()

        # Audit / change tracking
        update_change_reason(
            equipment,
            "Source of change: Front end"
        )

    except IntegrityError:
        # This happens if (equipment_type, serial_number)
        # violates the unique_together constraint
        return JsonResponse(
            {
                "message": (
                    "Could not update. An equipment with this equipment type "
                    "and serial number already exists."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # SUCCESS RESPONSE
    return JsonResponse(
        {},
        status=status.HTTP_200_OK,
    )


@require_http_methods(["POST"])
@wx_mapped_permission_required
def delete_equipment(request):
    """
    Deletes an Equipment record unless it is protected by related records.
    """

    # READ INPUT DATA
    equipment_id = request.GET.get("equipment_id")

    # BASIC VALIDATION
    if not equipment_id:
        return JsonResponse(
            {"message": "equipment_id is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # FETCH EQUIPMENT
    try:
        equipment = Equipment.objects.get(id=equipment_id)
    except Equipment.DoesNotExist:
        return JsonResponse(
            {"message": "Equipment not found"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # DELETE EQUIPMENT
    try:
        equipment.delete()
    except ProtectedError:
        return JsonResponse(
            {
                "message": (
                    "This equipment cannot be deleted because it is referenced "
                    "by one or more maintenance reports."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # SUCCESS RESPONSE
    return JsonResponse({}, status=status.HTTP_200_OK)


class get_maintenance_reports(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/maintenance_reports/maintenance_reports.html'


@require_http_methods(["PUT"])
@wx_mapped_permission_required
def get_maintenance_report_list(request):
    form_data = json.loads(request.body.decode())

    maintenance_reports = MaintenanceReport.objects.filter(visit_date__gte = form_data['start_date'], visit_date__lte = form_data['end_date'])

    response = {}
    response['maintenance_report_list'] = []

    for maintenance_report in maintenance_reports:
        if maintenance_report.status != '-':
            station, station_profile, technician, visit_type = get_maintenance_report_obj(maintenance_report)

            if station.is_automatic == form_data['is_automatic']:
                if maintenance_report.status == 'A':
                    maintenance_report_status = 'Approved'
                elif maintenance_report.status == 'P':
                    maintenance_report_status = 'Published'
                else:
                    maintenance_report_status = 'Draft'

                maintenance_report_object = {
                    'maintenance_report_id': maintenance_report.id,
                    'station_name': station.name,
                    'station_profile': station_profile.name,
                    'station_type': 'Automatic' if station.is_automatic else 'Manual',
                    'visit_date': maintenance_report.visit_date,
                    'next_visit_date': maintenance_report.next_visit_date,
                    'technician': technician.name,
                    'type_of_visit': visit_type.name,
                    'status': maintenance_report_status,
                }

                response['maintenance_report_list'].append(maintenance_report_object)

    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["GET"]) # Update maintenance report from existing report
@wx_mapped_permission_required
def update_maintenance_report(request, id):
    maintenance_report = MaintenanceReport.objects.get(id=id)
    if maintenance_report.status == 'A':
        response={'message': "Approved reports can not be editable."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)
    elif maintenance_report.status == '-':
        response={'message': "This report is deleated."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)

    template = loader.get_template('wx/maintenance_reports/new_report.html')

    context = {}
    context['station_list'] = Station.objects.select_related('profile').exclude(is_reference=True)

    context['visit_type_list'] = VisitType.objects.all()
    context['technician_list'] = Technician.objects.all()

    context['maintenance_report_id'] = id

    return HttpResponse(template.render(context, request))



@transaction.atomic
@require_http_methods(["PUT"])
@wx_mapped_permission_required
def delete_maintenance_report(request, id):
    maintenance_report = get_object_or_404(MaintenanceReport, id=id)

    # 1. Collect all equipment affected by this report BEFORE delete.
    affected_equipment = {}

    # Store each equipment's current last_deploy_date before the report is deleted.
    # This protects the value from being erased during recalculation.
    previous_last_deploy_dates = {}

    maintenance_report_equipments = MaintenanceReportEquipment.objects.filter(
        maintenance_report=maintenance_report
    ).select_related('new_equipment', 'old_equipment')

    for mre in maintenance_report_equipments:
        if mre.new_equipment is not None:
            affected_equipment[mre.new_equipment.id] = mre.new_equipment

            # Remember the existing last_deploy_date before delete/recalculation.
            previous_last_deploy_dates[mre.new_equipment.id] = mre.new_equipment.last_deploy_date

        if mre.old_equipment is not None:
            affected_equipment[mre.old_equipment.id] = mre.old_equipment

            # Remember the existing last_deploy_date before delete/recalculation.
            previous_last_deploy_dates[mre.old_equipment.id] = mre.old_equipment.last_deploy_date

    # 2. Delete the maintenance report.
    #    This will also cascade-delete related MaintenanceReportEquipment rows.
    maintenance_report.delete()

    # 3. Recalculate all affected equipment from remaining history.
    for equipment in affected_equipment.values():
        recalculate_equipment_from_history(equipment)

        # If recalculation erased last_deploy_date, restore the value that existed
        # before the maintenance report was deleted.
        #
        # This keeps delete from wiping out last_deploy_date.
        previous_last_deploy_date = previous_last_deploy_dates.get(equipment.id)

        if equipment.last_deploy_date is None and previous_last_deploy_date is not None:
            equipment.last_deploy_date = previous_last_deploy_date
            equipment.save(update_fields=['last_deploy_date'])

        update_change_reason(
            equipment,
            f"Source of change: Maintenance Report delete {id}"
        )

    return JsonResponse(
        {"detail": "Maintenance report deleted successfully."},
        status=status.HTTP_200_OK
    )



@require_http_methods(["PUT"])
@wx_mapped_permission_required
def approve_maintenance_report(request, id):

    maintenance_report = MaintenanceReport.objects.get(id=id)
    maintenance_report.status = 'A'
    maintenance_report.save()

    response={}
    return JsonResponse(response, status=status.HTTP_200_OK)    


@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_maintenance_report_view(request, id, source): # Maintenance report view
    template = loader.get_template('wx/maintenance_reports/view_report.html')

    maintenance_report = MaintenanceReport.objects.get(id=id)

    station = Station.objects.filter(pk=maintenance_report.station_id).exclude(is_reference=True).first()
    profile = StationProfile.objects.get(pk=station.profile_id)
    responsible_technician = Technician.objects.get(pk=maintenance_report.responsible_technician_id)
    visit_type = VisitType.objects.get(pk=maintenance_report.visit_type_id)

    maintenance_report_station_equipments = MaintenanceReportEquipment.objects.filter(maintenance_report_id=maintenance_report.id)

    maintenance_report_station_equipment_list = []

    for maintenance_report_station_equipment in maintenance_report_station_equipments:
        new_equipment_id =  maintenance_report_station_equipment.new_equipment_id

        # if the new_equipment_id is null (meaning it the equipment has been removed) skip execution
        if not new_equipment_id:
            continue

        new_equipment = Equipment.objects.get(id=new_equipment_id)

        dictionary = {'condition': maintenance_report_station_equipment.condition,
                      'component_classification': maintenance_report_station_equipment.classification,
                      'name': ' '.join([new_equipment.model.name, new_equipment.serial_number]),
                      'model': new_equipment.model.name,
                      'serial': new_equipment.serial_number,
                      'manufacturer': new_equipment.manufacturer.name,
                      'type': new_equipment.equipment_type.name
                     }
        maintenance_report_station_equipment_list.append(dictionary)

    other_technicians_ids = [maintenance_report.other_technician_1_id,
                             maintenance_report.other_technician_2_id,
                             maintenance_report.other_technician_3_id]
    other_technicians = []
    for other_technician_id in other_technicians_ids:
        if other_technician_id:
            other_technician = Technician.objects.get(id=other_technician_id)
            other_technicians.append(other_technician.name)

    other_technicians = ", ".join(other_technicians)


    context = {}

    if source == 0:
        context['source'] = 'edit'
    else:
        context['source'] = 'list'

    context['visit_summary_information'] = {
        "report_number": maintenance_report.id,
        "responsible_technician": responsible_technician.name,
        "date_of_visit": maintenance_report.visit_date,
        "date_of_next_visit": maintenance_report.next_visit_date,
        "start_time": maintenance_report.initial_time,
        "other_technicians": other_technicians,
        "end_time": maintenance_report.end_time,
        "type_of_visit": visit_type.name,
        "station_on_arrival_conditions": maintenance_report.station_on_arrival_conditions,
        "current_visit_summary": maintenance_report.current_visit_summary,
        "next_visit_summary": maintenance_report.next_visit_summary,
        "maintenance_report_status": maintenance_report.status,
    }

    context['station_information'] = {
        "station_name": station.name,
        "station_host_name": "---",
        "station_ID": station.code,
        "wigos_ID": station.wigos,
        "station_type": 'Automatic' if station.is_automatic else 'Manual',
        "station_profile": profile.name,
        "latitude": station.latitude,
        "elevation": station.elevation,
        "longitude": station.longitude,
        "district": station.region.name,
        "transmission_type": "---",
        "transmission_ID": "---",
        "transmission_interval": "---",
        "measurement_interval": "---",
        "data_of_first_operation": station.begin_date,
        "data_of_relocation": station.relocation_date,
    }

    context['contact_information'] = maintenance_report.contacts  

    context['equipment_records'] = maintenance_report_station_equipment_list

    logo_path = os.path.join(get_static_assets_dir(), "images/org_logo.png")
    context["org_logo_mtime"] = int(os.path.getmtime(logo_path)) if os.path.exists(logo_path) else 1

    return HttpResponse(template.render(context, request))


def get_ckeditor_config():
    ckeditor_config = {
        'toolbar': [
                ['Bold', 'Italic', 'Font'],
                ['Format', 'Styles', 'TextColor', 'BGColor', 'RemoveFormat'],
                ['JustifyLeft','JustifyCenter','JustifyRight','JustifyBlock', 'Indent', 'Outdent'],
                ['HorizontalRule', 'BulletedList'],
                ['Blockquote', 'Source', 'Link', 'Unlink', 'Image', 'Table', 'Print']
            ],
        'removeButtons': 'Image',
        'extraAllowedContent' : 'img(*){*}[*]',              
        'editorplaceholder': 'Description of station upon arribal:',
        'language': 'en',            
    }
    return ckeditor_config


def get_maintenance_report_obj(maintenance_report):
    station = Station.objects.get(id=maintenance_report.station_id)
    station_profile = StationProfile.objects.get(id=station.profile_id)
    technician = Technician.objects.get(id=maintenance_report.responsible_technician_id)
    visit_type = VisitType.objects.get(id=maintenance_report.visit_type_id)

    return station, station_profile, technician, visit_type


@method_decorator(wx_mapped_permission_required, name="dispatch")
class get_maintenance_report_form(LoginRequiredMixin, TemplateView):
    template_name = 'wx/maintenance_reports/new_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.select_related('profile').filter(profile__isnull=False).exclude(is_reference=True)
        context['visit_type_list'] = VisitType.objects.all()
        context['technician_list'] = Technician.objects.all()

        return context


def get_station_contacts(station_id):
    maintenance_report_list = MaintenanceReport.objects.filter(station_id=station_id).order_by('visit_date')

    for maintenance_report in maintenance_report_list:
        if maintenance_report.contacts != '':
            return maintenance_report.contacts

    return None


def get_maintenance_report_equipment_data(maintenance_report, equipment_type, equipment_order):
    equipment_data = {
        'active_tab': 0,
        'old_equipment_id': None,
        'old_equipment_name': None,
        'new_equipment_id': None,
        'new_equipment_name': None,
        'condition': equipment_type.report_template,
        'classification': "F",
        'ckeditor_config': get_ckeditor_config()
    }

    try:
        maintenancereport_equipment = MaintenanceReportEquipment.objects.get(
                                        maintenance_report_id=maintenance_report.id,
                                        equipment_type_id=equipment_type.id,
                                        equipment_order=equipment_order)

        equipment_data['old_equipment_id'] = maintenancereport_equipment.old_equipment_id
        equipment_data['new_equipment_id'] = maintenancereport_equipment.new_equipment_id
        equipment_data['condition'] = maintenancereport_equipment.condition
        equipment_data['classification'] = maintenancereport_equipment.classification

        if maintenancereport_equipment.old_equipment_id:
            equipment = Equipment.objects.get(id=maintenancereport_equipment.old_equipment_id)
            equipment_data['old_equipment_name'] = ' '.join([equipment.model.name, equipment.serial_number]) 

        if maintenancereport_equipment.new_equipment_id:
            equipment = Equipment.objects.get(id=maintenancereport_equipment.new_equipment_id)
            equipment_data['new_equipment_name'] = ' '.join([equipment.model.name, equipment.serial_number]) 
    except ObjectDoesNotExist:
        pass

    equipment_data['active_tab'] = get_acitve_tab(equipment_data['old_equipment_id'], equipment_data['new_equipment_id'])

    return equipment_data


def get_available_equipments(equipment_type_id, station):
    equipments = Equipment.objects.filter(equipment_type_id=equipment_type_id)

    available_equipments = []

    for equipment in equipments:
        if is_equipment_available(equipment, station):
            available_equipments.append({'id': equipment.id, 'name': ' '.join([equipment.model.name, equipment.serial_number])})

    return available_equipments


def get_maintenance_report_equipment_types(maintenance_report):
    station = Station.objects.get(id=maintenance_report.station_id)

    station_profile_equipment_types = StationProfileEquipmentType.objects.filter(
        station_profile=station.profile_id
    ).order_by('equipment_type_order')

    equipment_type_ids = list(
        station_profile_equipment_types.values_list('equipment_type_id', flat=True)
    )

    equipment_types = EquipmentType.objects.filter(
        id__in=equipment_type_ids
    ).order_by(
        Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(equipment_type_ids)],
            output_field=IntegerField(),
        )
    )

    equipment_type_list = []

    for equipment_type in equipment_types:
        dictionary = {'key':equipment_type.id,
                      'id':equipment_type.id,
                      'name': equipment_type.name,
                      'available_equipments': get_available_equipments(equipment_type.id, station),
                      'primary_equipment': get_maintenance_report_equipment_data(maintenance_report, equipment_type, 'P'),
                      'secondary_equipment': get_maintenance_report_equipment_data(maintenance_report, equipment_type, 'S'),
                      }

        equipment_type_list.append(dictionary)

    return equipment_type_list


def get_last_maintenance_report(maintenance_report):
    station_id = maintenance_report.station_id
    visit_date = maintenance_report.visit_date

    try:
        return MaintenanceReport.objects.filter(station_id=station_id,visit_date__lt=visit_date).latest('visit_date')
    except ObjectDoesNotExist:
        return None

    return last_maintenance_report    


def copy_last_maintenance_report_equipments(maintenance_report):
    last_maintenance_report = get_last_maintenance_report(maintenance_report)

    if last_maintenance_report:
        last_maintenance_report_equipments = MaintenanceReportEquipment.objects.filter(maintenance_report=last_maintenance_report)
        for maintenance_report_equipment in last_maintenance_report_equipments:
            now = datetime.datetime.now()

            # if no new equipment, then skip execution
            if not maintenance_report_equipment.new_equipment_id:
                continue

            equipment = Equipment.objects.get(id=maintenance_report_equipment.new_equipment_id)
            equipment_type = EquipmentType.objects.get(id=equipment.equipment_type_id)

            created_object = MaintenanceReportEquipment.objects.create(
                                created_at = now,
                                updated_at = now,                
                                maintenance_report = maintenance_report,
                                equipment_type = equipment_type,
                                equipment_order = maintenance_report_equipment.equipment_order,
                                old_equipment = equipment,
                                new_equipment = equipment,
                                condition = equipment_type.report_template,
                                classification = equipment.classification,
                            )

def get_acitve_tab(old_equipment_id, new_equipment_id):
    if old_equipment_id is None:
        return 0 #Add
    elif new_equipment_id is None:
        return 2 #Remove
    elif old_equipment_id != new_equipment_id:
        return 1 #Change
    else:
        return 0 #Update



def get_equipment_last_location(maintenance_report, equipment):
    """
    Determine the last known location of equipment BEFORE the given maintenance report.

    Logic:
    - Look at the most recent "new_equipment" event (deployment)
    - Look at the most recent "old_equipment" event (removal)
    - Whichever event is more recent determines the current state:

        - If latest event is "new_equipment" -> equipment is at that station
        - If latest event is "old_equipment" -> equipment is not currently deployed anywhere (return None)

    Note:
    - Exclude the current maintenance report to avoid self-referencing.
    """

    # Latest deployment event (equipment installed somewhere)
    latest_new = (
        MaintenanceReportEquipment.objects
        .filter(new_equipment_id=equipment.id)
        .exclude(maintenance_report_id=maintenance_report.id)
        # Order by newest first, with tie-breakers
        .order_by('-maintenance_report__visit_date', '-maintenance_report_id', '-id')
        .first()
    )

    # Latest removal event (equipment removed from somewhere)
    latest_old = (
        MaintenanceReportEquipment.objects
        .filter(old_equipment_id=equipment.id)
        .exclude(maintenance_report_id=maintenance_report.id)
        .order_by('-maintenance_report__visit_date', '-maintenance_report_id', '-id')
        .first()
    )

    # Case 1: Both deployment and removal events exist
    if latest_new and latest_old:
        new_date = latest_new.maintenance_report.visit_date
        old_date = latest_old.maintenance_report.visit_date

        # If deployment is more recent -> equipment is at that station
        if new_date > old_date:
            return latest_new.maintenance_report.station

        # If removal is more recent -> equipment is not deployed anywhere
        if old_date > new_date:
            return None

        # If same date, break tie using report ID (higher ID = later entry)
        if latest_new.maintenance_report_id > latest_old.maintenance_report_id:
            return latest_new.maintenance_report.station

        return None

    # Case 2: Only deployment exists -> equipment is at that station
    if latest_new:
        return latest_new.maintenance_report.station

    # Case 3: Only removal exists -> equipment is not deployed anywhere
    if latest_old:
        return None

    # Case 4: No history at all -> never deployed
    return None



def recalculate_equipment_from_history(equipment):
    """
    Rebuild the current Equipment state from MaintenanceReportEquipment history.

    Rules:
    - first_deploy_date:
        Sticky field. Only initialize it if currently empty.
    - last_deploy_date:
        The most recent maintenance report visit_date after the first deployment
        where this equipment was assigned again in a real deployment event.
    - location:
        Current station where the equipment is deployed, or None if not deployed.
    - classification:
        Last known classification from the latest row where this equipment is
        present as the assigned equipment.
    """

    rows = list(
        MaintenanceReportEquipment.objects
        .filter(
            Q(new_equipment_id=equipment.id) | Q(old_equipment_id=equipment.id)
        )
        .select_related('maintenance_report', 'maintenance_report__station')
        .order_by(
            'maintenance_report__visit_date',
            'maintenance_report__initial_time',
            'maintenance_report_id',
            'id',
        )
    )

    calculated_first_deploy_date = None
    calculated_last_deploy_date = None
    current_location = None
    current_classification = equipment.classification

    # This is the key fix:
    # if the equipment already has a first_deploy_date stored,
    # then any later real deployment should be allowed to set last_deploy_date
    had_prior_deployment = equipment.first_deploy_date is not None

    for row in rows:
        report = row.maintenance_report
        station = report.station

        is_old = row.old_equipment_id == equipment.id
        is_new = row.new_equipment_id == equipment.id

        # --------------------------------------------------------
        # Case A: Update row
        # old_equipment == new_equipment == this equipment
        #
        # Same equipment remains assigned. Do not treat as redeployment.
        # --------------------------------------------------------
        if is_old and is_new:
            if calculated_first_deploy_date is None:
                calculated_first_deploy_date = report.visit_date

            current_location = station

            if row.classification is not None:
                current_classification = row.classification

        # --------------------------------------------------------
        # Case B: Real deployment / reassignment row
        # new_equipment == this equipment, old_equipment is null/different
        # --------------------------------------------------------
        elif is_new:
            if calculated_first_deploy_date is None:
                calculated_first_deploy_date = report.visit_date

                # If the equipment already had a stored first_deploy_date,
                # then this is not its first-ever deployment in business terms.
                # Treat it as a later deployment and update last_deploy_date.
                if had_prior_deployment and equipment.first_deploy_date != report.visit_date:
                    calculated_last_deploy_date = report.visit_date
            else:
                # Any later real deployment in the rebuilt history updates last_deploy_date
                calculated_last_deploy_date = report.visit_date

            current_location = station

            if row.classification is not None:
                current_classification = row.classification

        # --------------------------------------------------------
        # Case C: Removal row
        # old_equipment == this equipment, new_equipment is null/different
        # --------------------------------------------------------
        elif is_old:
            if current_location == station:
                current_location = None

    update_fields = []

    # Sticky first deploy date
    if equipment.first_deploy_date is None and calculated_first_deploy_date is not None:
        equipment.first_deploy_date = calculated_first_deploy_date
        update_fields.append('first_deploy_date')

    if equipment.last_deploy_date != calculated_last_deploy_date:
        equipment.last_deploy_date = calculated_last_deploy_date
        update_fields.append('last_deploy_date')

    if equipment.location != current_location:
        equipment.location = current_location
        update_fields.append('location')

    if equipment.classification != current_classification:
        equipment.classification = current_classification
        update_fields.append('classification')

    if update_fields:
        equipment.save(update_fields=update_fields)



def update_maintenance_report_equipment_type(maintenance_report, equipment_type, equipment_order, equipment_data):
    """
    Create, update, or delete a MaintenanceReportEquipment row for a given
    maintenance report / equipment type / equipment order combination.

    Key behavior:
    - Handles create, update, and delete of the row
    - Tracks BOTH previous and new equipment involved
    - After any change, recalculates ALL affected equipment from history
      to ensure location and deployment dates are correct

    This avoids stale state when:
    - equipment is removed
    - equipment is swapped
    - a row is deleted
    """

    # 1. Resolve incoming equipment objects from IDs
    new_equipment = None
    old_equipment = None

    if equipment_data.get('new_equipment_id'):
        new_equipment = Equipment.objects.get(id=equipment_data['new_equipment_id'])

    if equipment_data.get('old_equipment_id'):
        old_equipment = Equipment.objects.get(id=equipment_data['old_equipment_id'])

    condition = equipment_data.get('condition')
    classification = equipment_data.get('classification')

    # 2. Determine if this is a delete case
    #    (no equipment provided → row should not exist)
    delete_case = old_equipment is None and new_equipment is None

    # 3. Track PREVIOUS equipment before modifying the row
    #    (important for recalculation later)
    previous_old_equipment = None
    previous_new_equipment = None

    # This will be used when the row previously had a new_equipment,
    # but the incoming update removes it by setting new_equipment to None.
    removed_new_equipment = None

    try:
        # Try to fetch existing row
        maintenance_report_equipment = MaintenanceReportEquipment.objects.get(
            maintenance_report=maintenance_report,
            equipment_type_id=equipment_type.id,
            equipment_order=equipment_order,
        )

        # Capture previous state BEFORE making changes
        previous_old_equipment = maintenance_report_equipment.old_equipment
        previous_new_equipment = maintenance_report_equipment.new_equipment

        # If the existing row had a new_equipment, but the incoming update
        # has no new_equipment, then that previous new_equipment was removed.
        #
        # Example:
        #   before update:
        #       previous_new_equipment = Equipment A
        #
        #   incoming update:
        #       new_equipment = None
        #
        #   meaning:
        #       Equipment A was removed.
        if previous_new_equipment is not None and new_equipment is None:
            removed_new_equipment = previous_new_equipment

        # 4. Handle DELETE
        if delete_case:
            # Row is no longer needed → remove it
            maintenance_report_equipment.delete()

        # 5. Handle UPDATE
        else:
            maintenance_report_equipment.condition = condition
            maintenance_report_equipment.classification = classification
            maintenance_report_equipment.old_equipment = old_equipment
            maintenance_report_equipment.new_equipment = new_equipment
            maintenance_report_equipment.save()

    except ObjectDoesNotExist:

        # 6. Handle CREATE
        if delete_case:
            # Nothing exists and nothing needs to exist → do nothing
            return

        if new_equipment is not None:
            # Create a new row
            maintenance_report_equipment = MaintenanceReportEquipment.objects.create(
                maintenance_report=maintenance_report,
                equipment_type=equipment_type,
                equipment_order=equipment_order,
                condition=condition,
                classification=classification,
                new_equipment=new_equipment,
                old_equipment=old_equipment,
            )
        else:
            # Unexpected state:
            # no existing row and no new equipment to create one
            logger.error(
                "Error updating maintenance report equipment: "
                "no existing row found and no new equipment provided. "
                f"maintenance_report_id={maintenance_report.id}, "
                f"equipment_type_id={equipment_type.id}, "
                f"equipment_order={equipment_order}, "
                f"old_equipment_id={getattr(old_equipment, 'id', None)}, "
                f"new_equipment_id={getattr(new_equipment, 'id', None)}"
            )
            return

    # 7. Collect ALL equipment affected by this change
    #    (both before and after state)
    affected_equipment = {
        eq.id: eq
        for eq in [
            previous_old_equipment,
            previous_new_equipment,
            old_equipment,
            new_equipment,
        ]
        if eq is not None
    }

    # 8. Recalculate each equipment from history
    for eq in affected_equipment.values():
        # This ensures:
        # - location is correct
        # - first_deploy_date is correct
        # - last_deploy_date is correct
        recalculate_equipment_from_history(eq)

        # If this was the previous new_equipment and it was removed,
        # force its last deployed date to this maintenance report visit date.
        #
        # Use the correct field name from your Equipment model.
        # If your model field is last_deploy_date, keep this.
        # If your model field is last_deploy_date, change it below.
        if removed_new_equipment is not None and eq.id == removed_new_equipment.id:
            eq.last_deploy_date = maintenance_report.visit_date
            eq.save(update_fields=["last_deploy_date"])

        # Record audit trail for traceability
        update_change_reason(
            eq,
            f"Source of change: Maintenance Report {maintenance_report.id}, "
            f"{maintenance_report.station.name} - {maintenance_report.visit_date}"
        )



@require_http_methods(["POST"])
@wx_mapped_permission_required
def update_maintenance_report_equipment_type_data(request):
    form_data = json.loads(request.body.decode())

    maintenance_report_id = form_data['maintenance_report_id'] 
    equipment_type_id = form_data['equipment_type_id'] 
    equipment_order = form_data['equipment_order']
    
    if isinstance(equipment_order, tuple):
        equipment_order = equipment_order[0]
    elif not isinstance(equipment_order, str):
        logger.error("Error in equipment order during maintenance report equipment update")
    equipment_data = {
        'new_equipment_id': form_data['new_equipment_id'], 
        'old_equipment_id': form_data['old_equipment_id'], 
        'condition': form_data['condition'], 
        'classification': form_data['classification'], 
    }

    maintenance_report = MaintenanceReport.objects.get(id=maintenance_report_id)
    equipment_type = EquipmentType.objects.get(id=equipment_type_id)

    update_maintenance_report_equipment_type(maintenance_report, equipment_type, equipment_order, equipment_data)
    
    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"]) # Create maintenance report from sratch
@wx_mapped_permission_required
def create_maintenance_report(request):
    now = datetime.datetime.now()
    form_data = json.loads(request.body.decode())

    station = Station.objects.get(id=form_data['station_id'])
    if not StationProfileEquipmentType.objects.filter(station_profile=station.profile):
        response = {"message": f"Station profile {station.profile.name} is not associated with any equipment type."}        
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)


    # Check if a maintenance report with status '-' exists and hard delete it
    maintenance_report = MaintenanceReport.objects.filter(station_id=form_data['station_id'], visit_date=form_data['visit_date'], status='-').first()
    if maintenance_report:
        maintenance_report.delete()

    # Check if a previous maintenance report is not approved
    maintenance_report = MaintenanceReport.objects.filter(station_id=form_data['station_id']).exclude(status__in=['A', '-']).first()
    if maintenance_report:
        response = {"message": f"Previous maintenance reports of {station.name} - {station.code} require approval to create a new one."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)

    # Check if a more recent maintenance report exists
    maintenance_report = MaintenanceReport.objects.filter(station_id=form_data['station_id'], visit_date__gt=form_data['visit_date']).first()
    if maintenance_report:
        response = {"message": "A more recent maintenance report already exists, and the new report must be the latest."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)

    # Create a new maintenance report if it doesn't already exist
    try:
        maintenance_report = MaintenanceReport.objects.get(station_id=form_data['station_id'], visit_date=form_data['visit_date'])
        response = {"message": "Maintenance report already exists for chosen station and date."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)
    except ObjectDoesNotExist:
        maintenance_report = MaintenanceReport.objects.create(
            created_at=now,
            updated_at=now,
            station_id=form_data['station_id'],
            responsible_technician_id=form_data['responsible_technician_id'],
            visit_type_id=form_data['visit_type_id'],
            visit_date=form_data['visit_date'],
            initial_time=form_data['initial_time'],
            contacts=get_station_contacts(form_data['station_id']),
        )

        copy_last_maintenance_report_equipments(maintenance_report)

        response = {"maintenance_report_id": maintenance_report.id}
        return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["GET"]) # Ok
@wx_mapped_permission_required
def get_maintenance_report(request, id):
    maintenance_report = MaintenanceReport.objects.get(id=id)

    station, station_profile, technician, visit_type = get_maintenance_report_obj(maintenance_report)

    response = {}
    response['station_information'] = {
        "station_name": station.name,
        "station_host_name": "---",
        "station_ID": station.code,
        "wigos_ID": station.wigos,
        "station_type": 'Automatic' if station.is_automatic else 'Manual',
        "station_profile": station_profile.name,
        "latitude": station.latitude,
        "elevation": station.elevation,
        "longitude": station.longitude,
        "district": station.region.name,
        "transmission_type": "---",
        "transmission_ID": "---",
        "transmission_interval": "---",
        "measurement_interval": "---",
        "data_of_first_operation": station.begin_date,
        "data_of_relocation": station.relocation_date,
    }

    response["station_id"] = station.id
    response["responsible_technician"] = technician.name
    response["responsible_technician_id"] = maintenance_report.responsible_technician_id
    response["visit_date"] = maintenance_report.visit_date
    response["next_visit_date"] = maintenance_report.next_visit_date
    response["initial_time"] = maintenance_report.initial_time
    response["end_time"] = maintenance_report.end_time
    response["visit_type"] = visit_type.name
    response["visit_type_id"] = visit_type.id
    response["station_on_arrival_conditions"] = maintenance_report.station_on_arrival_conditions
    response["current_visit_summary"] = maintenance_report.current_visit_summary
    response["next_visit_summary"] = maintenance_report.next_visit_summary
    response["other_technician_1"] = maintenance_report.other_technician_1_id
    response["other_technician_2"] = maintenance_report.other_technician_2_id
    response["other_technician_3"] = maintenance_report.other_technician_3_id

    response['contacts'] = maintenance_report.contacts  
    response['equipment_types'] = get_maintenance_report_equipment_types(maintenance_report)
    response['steps'] = len(response['equipment_types'])

    if maintenance_report.data_logger_file_name is None:
        response['data_logger_file_name'] = "Upload latest data logger program"
    else:
        response['data_logger_file_name'] = maintenance_report.data_logger_file_name

    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["PUT"]) # Ok
@wx_mapped_permission_required
def update_maintenance_report_condition(request, id):
    now = datetime.datetime.now()

    maintenance_report = MaintenanceReport.objects.get(id=id)
    
    form_data = json.loads(request.body.decode())
    
    maintenance_report.station_on_arrival_conditions = form_data['conditions']

    maintenance_report.updated_at = now
    maintenance_report.save()

    response={}

    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["PUT"]) # Ok
@wx_mapped_permission_required
def update_maintenance_report_contacts(request, id):
    now = datetime.datetime.now()

    maintenance_report = MaintenanceReport.objects.get(id=id)

    form_data = json.loads(request.body.decode())

    maintenance_report.contacts = form_data['contacts']

    maintenance_report.updated_at = now
    maintenance_report.save()

    response={}

    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"]) # Ok
@wx_mapped_permission_required
def update_maintenance_report_datalogger(request, id):
    # print(request.FILES)
    if 'data_logger_file' in request.FILES:
        maintenance_report = MaintenanceReport.objects.get(id=id)

        data_logger_file = request.FILES['data_logger_file'].file
        data_logger_file_name = str(request.FILES['data_logger_file'])
        data_logger_file_content = b64encode(data_logger_file.read()).decode('utf-8')

        maintenance_report.data_logger_file = data_logger_file_content
        maintenance_report.data_logger_file_name = data_logger_file_name
        maintenance_report.updated_at = datetime.datetime.now()
        maintenance_report.save()

        response = {'data_logger_file_name', data_logger_file_name}

        return JsonResponse(response, status=status.HTTP_200_OK)

    # print("Data logger file not uploaded.")
    response={'message': "Data logger file not uploaded."}
    return JsonResponse(response, status=status.HTTP_206_PARTIAL_CONTENT)


@require_http_methods(["PUT"]) # Ok
@wx_mapped_permission_required
def update_maintenance_report_summary(request, id):
    now = datetime.datetime.now()

    maintenance_report = MaintenanceReport.objects.get(id=id)

    form_data = json.loads(request.body.decode())

    if form_data['other_technician_1']:
        other_technician_1 = Technician.objects.get(id=form_data['other_technician_1'])
    else:
        other_technician_1 = None

    if form_data['other_technician_2']:
        other_technician_2 = Technician.objects.get(id=form_data['other_technician_2'])
    else:
        other_technician_2 = None

    if form_data['other_technician_3']:
        other_technician_3 = Technician.objects.get(id=form_data['other_technician_3'])    
    else:
        other_technician_3 = None

    maintenance_report.other_technician_1 = other_technician_1
    maintenance_report.other_technician_2 = other_technician_2
    maintenance_report.other_technician_3 = other_technician_3
    maintenance_report.next_visit_date = form_data['next_visit_date']
    maintenance_report.end_time = form_data['end_time']
    maintenance_report.current_visit_summary = form_data['current_visit_summary']
    maintenance_report.next_visit_summary = form_data['next_visit_summary']
    maintenance_report.status = form_data['status']

    maintenance_report.updated_at = now
    maintenance_report.save()

    response={}

    return JsonResponse(response, status=status.HTTP_200_OK)

class SpatialAnalysisView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/spatial_analysis.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['quality_flags'] = QualityFlag.objects.all()

        return context


@api_view(['GET'])
def raw_data_last_24h(request, station_id):
    station = Station.objects.get(pk=station_id)
    response_dict = {}

    query = f"""
        WITH data AS (
            SELECT to_char((datetime + interval '{station.utc_offset_minutes} minutes') at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS') as datetime,
                   measured,
                   variable_id
            FROM raw_data
            WHERE station_id=%s
              AND datetime >= now() - '1 day'::interval
              AND measured != {settings.MISSING_VALUE})
        SELECT datetime,
               var.name,
               var.symbol,
               unit.name,
               unit.symbol,
               measured
        FROM data
            INNER JOIN wx_variable var ON variable_id=var.id
            LEFT JOIN wx_unit unit ON var.unit_id=unit.id
        ORDER BY datetime, var.name
    """

    with connection.cursor() as cursor:

        cursor.execute(query, [station.id])

        rows = cursor.fetchall()

        for row in rows:

            if row[0] not in response_dict.keys():
                response_dict[row[0]] = []

            obj = {
                'value': row[5],
                'variable': {
                    'name': row[1],
                    'symbol': row[2],
                    'unit_name': row[3],
                    'unit_symbol': row[4]
                }
            }
            response_dict[row[0]].append(obj)

    return JsonResponse(response_dict)


class StationsMapView(LoginRequiredMixin, TemplateView):
    template_name = "wx/station_map.html"


@method_decorator(wx_mapped_permission_required, name="dispatch")
class StationMetadataView(LoginRequiredMixin, TemplateView):
    template_name = "wx/station_metadata.html"
    model = Station
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_name'] = Station.objects.exclude(is_reference=True).values('pk', 'name')  # Fetch only pk and name

        context['is_metadata'] = True

        return context

@api_view(['GET'])
def latest_data(request, variable_id):
    result = []

    query = """
        SELECT CASE WHEN var.variable_type ilike 'code' THEN latest.last_data_code ELSE latest.last_data_value::varchar END as value,
               sta.longitude,
               sta.latitude,
               unit.symbol
        FROM wx_stationvariable latest
        INNER JOIN wx_variable var ON latest.variable_id=var.id
        INNER JOIN wx_station sta ON latest.station_id=sta.id
        LEFT JOIN wx_unit unit ON var.unit_id=unit.id
        WHERE latest.variable_id=%s 
          AND latest.last_data_value is not null
          AND latest.last_data_datetime = ( SELECT MAX(most_recent.last_data_datetime)
                                            FROM wx_stationvariable most_recent
                                            WHERE most_recent.station_id=latest.station_id 
                                                AND most_recent.last_data_value is not null)
        """

    with connection.cursor() as cursor:
        cursor.execute(query, [variable_id])

        rows = cursor.fetchall()

        for row in rows:
            obj = {
                'value': row[0],
                'longitude': row[1],
                'latitude': row[2],
                'symbol': row[3],
            }

            result.append(obj)

    return Response(result, status=status.HTTP_200_OK)


class StationImageViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    parser_class = (FileUploadParser,)
    queryset = StationImage.objects.all()
    serializer_class = serializers.StationImageSerializer

    def get_queryset(self):
        station_id = self.request.query_params.get('station_id', None)

        queryset = StationImage.objects.all()

        if station_id is not None:
            queryset = queryset.filter(station__id=station_id)

        return queryset


class StationFileViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    parser_class = (FileUploadParser,)
    queryset = StationFile.objects.all()
    serializer_class = serializers.StationFileSerializer

    def get_queryset(self):
        station_id = self.request.query_params.get('station_id', None)

        queryset = StationFile.objects.all()

        if station_id is not None:
            queryset = queryset.filter(station__id=station_id)

        return queryset


class ExtremesMeansView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'wx/products/extremes_means.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.exclude(is_reference=True).values('id', 'name', 'code')

        return context



def get_months():
    months = {
      1: 'January',
      2: 'February',
      3: 'March',
      4: 'April',
      5: 'May',
      6: 'June',
      7: 'July',
      8: 'August',
      9: 'September',
      10: 'October',
      11: 'November',
      12: 'December',
    }

    return months


def get_interval_in_seconds(interval_id):
    if interval_id is None:
        return None
    interval = Interval.objects.get(id=int(interval_id))
    return interval.seconds


@require_http_methods(["POST"])
@wx_mapped_permission_required
def update_reference_station(request):
    station_id = request.GET.get('station_id', None)
    new_reference_station_id = request.GET.get('new_reference_station_id', None)

    station = Station.objects.get(id=station_id)
    station.reference_station_id = new_reference_station_id
    station.save()

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"])
@wx_mapped_permission_required
def update_global_threshold(request):
    qc_method = request.GET.get('qc_method', None)
    is_automatic = request.GET.get('is_automatic', None)
    variable_name = request.GET.get('variable_name', None)
    variable = Variable.objects.get(name=variable_name)

    is_automatic = is_automatic == "true"

    if qc_method=='range':
        range_min = request.GET.get('range_min', None)    
        range_max = request.GET.get('range_max', None)

        if is_automatic:
            variable.range_min_hourly = range_min
            variable.range_max_hourly = range_max
        else:
            variable.range_min = range_min
            variable.range_max = range_max

    elif qc_method=='step':
        step = request.GET.get('step', None)

        if is_automatic:
            variable.step_hourly = step
        else:
            variable.step = step

    elif qc_method=='persist':
        minimum_variance = request.GET.get('minimum_variance', None)    
        window = request.GET.get('window', None)

        if is_automatic:
            variable.persistence_hourly = minimum_variance
            variable.persistence_window_hourly = window
        else:
            variable.persistence = minimum_variance
            variable.persistence_window = window

    variable.save()

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)



@api_view(['GET'])
def range_threshold_view(request): # Get global ranges for synop and daily data captures
    if request.method == 'GET':

        # Query
        get_range_threshold_query = f"""
            SELECT id
                ,range_max
                ,range_min
            from wx_variable
        """

        result = {}

        with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
            with conn.cursor() as cursor:
                cursor.execute(get_range_threshold_query)

                rows = cursor.fetchall()

                for row in rows:
                    result[row[0]] = {'max': row[1], 'min': row[2]}

    return Response(result, status=status.HTTP_200_OK)


class get_range_threshold_form(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/quality_control/range_threshold.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.select_related('profile').exclude(is_reference=True)
        context['reference_station_list'] = Station.objects.filter(is_reference=True).order_by('name')
        context['station_profile_list'] = StationProfile.objects.all()
        context['station_watershed_list'] = Watershed.objects.all()
        context['station_district_list'] = AdministrativeRegion.objects.all()  

        return context


def get_range_threshold_list(station_id, variable_id, is_reference=False):
    threshold_list = []
    months = get_months()
    for month_id in sorted(months.keys()):
        month = months[month_id]
        try:
            threshold = QcRangeThreshold.objects.get(station_id=station_id, variable_id=variable_id, month=month_id)
            threshold_entry = {
                'month': month_id,
                'min': str(threshold.range_min) if threshold.range_min is not None else '---',
                'max': str(threshold.range_max) if threshold.range_max is not None else '---',
            }
        except ObjectDoesNotExist:
            if is_reference:
                try:
                    threshold = QcRangeThreshold.objects.get(station_id=station_id, variable_id=variable_id, month=month_id)
                    threshold_entry = {
                        'month': month_id,
                        'min': str(threshold.range_min)+'*' if threshold.range_min is not None else '---',
                        'max': str(threshold.range_max)+'*' if threshold.range_max is not None else '---',
                    }
                except ObjectDoesNotExist:
                    threshold_entry = {
                        'month': month_id,
                        'min': '---',
                        'max': '---',
                    }
            else:
                threshold_entry = {
                    'month': month_id,
                    'min': '---',
                    'max': '---',
                }
        threshold_list.append(threshold_entry)
    return threshold_list


def get_range_threshold_in_list(threshold_list, month_id):
    if threshold_list:
        for threshold_entry in threshold_list:
            if threshold_entry['month'] == month_id:
                return threshold_entry

    threshold_entry = {'month': month_id, 'min': '---', 'max': '---'}
    return threshold_entry


def format_range_thresholds(global_thresholds, reference_thresholds, custom_thresholds, variable_name):
    months = get_months()

    formated_thresholds = []
    for month_id in sorted(months.keys()):
        month_name = months[month_id]

        custom_entry = get_range_threshold_in_list(custom_thresholds, month_id)
        reference_entry = get_range_threshold_in_list(reference_thresholds, month_id)

        formated_threshold = {
            'variable_name': variable_name,
            'month_name': month_name,
            'global':{
                'children':{
                    'g_min': global_thresholds['min'],
                    'g_max': global_thresholds['max'],
                }
            },
            'reference':{
                'children':{
                    'r_min': reference_entry['min'],
                    'r_max': reference_entry['max'],
                }
            },
            'custom':{
                'children':{
                    'c_min': custom_entry['min'],
                    'c_max': custom_entry['max'],
                }
            }
        }
        formated_thresholds.append(formated_threshold)

    return formated_thresholds


@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_range_threshold(request):
    station_id = request.GET.get('station_id', None)
    if station_id is None:
        response = {'message': "Field Station can not be empty."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)

    
    variable_ids = request.GET.get('variable_ids', None)
    if variable_ids is None:
        response = {'message': "Field Variables can not be empty."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST) 

    station = Station.objects.get(id=int(station_id))
    variable_ids = [int(variable_id) for variable_id in variable_ids.split(",")]

    reference_station_id = station.reference_station_id
    if reference_station_id:
        reference_station = Station.objects.get(id=station.reference_station_id)
        reference_station_name = reference_station.name+' - '+reference_station.code
    else:
        reference_station = None
        reference_station_name = None

    data = {
        'reference_station_id': reference_station_id,
        'reference_station_name': reference_station_name,
        'variable_data': {},
    }

    for variable_id in variable_ids:
        variable = Variable.objects.get(id=variable_id)

        custom_thresholds = get_range_threshold_list(station.id, variable.id, is_reference=False)

        if reference_station:
            reference_thresholds = get_range_threshold_list(reference_station.id, variable.id, is_reference=True)
        else:
            reference_thresholds = None

        global_thresholds = {}
        if station.is_automatic:
            global_thresholds['min'] = variable.range_min_hourly
            global_thresholds['max'] = variable.range_max_hourly
        else:
            global_thresholds['min'] = variable.range_min
            global_thresholds['max'] = variable.range_max

        global_thresholds['min'] = '---' if global_thresholds['min'] is None else str(global_thresholds['min'])
        global_thresholds['max'] = '---' if global_thresholds['max'] is None else str(global_thresholds['max'])

        formated_thresholds = format_range_thresholds(global_thresholds, reference_thresholds, custom_thresholds, variable.name)

        data['variable_data'][variable.name] = formated_thresholds

    response = {'data': data}
    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"])
@wx_mapped_permission_required
def update_range_threshold(request):
    months = get_months()
    months_ids = {v: k for k, v in months.items()}

    new_min = request.GET.get('new_min', None)    
    new_max = request.GET.get('new_max', None)
    station_id = request.GET.get('station_id', None)    
    variable_name = request.GET.get('variable_name', None)    
    month_name = request.GET.get('month_name', None)


    station = Station.objects.get(id=station_id)
    variable = Variable.objects.get(name=variable_name)
    month_id = months_ids[month_name]

    qcrangethreshold, created = QcRangeThreshold.objects.get_or_create(station_id=station.id, variable_id=variable.id, month=month_id)

    qcrangethreshold.range_min = new_min
    qcrangethreshold.range_max = new_max

    qcrangethreshold.save()

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"])
@wx_mapped_permission_required
def delete_range_threshold(request):
    months = get_months()
    months_ids = {v: k for k, v in months.items()}

    station_id = request.GET.get('station_id', None)    
    variable_name = request.GET.get('variable_name', None)    
    month_name = request.GET.get('month_name', None)

    station = Station.objects.get(id=station_id)
    variable = Variable.objects.get(name=variable_name)
    month_id = months_ids[month_name]

    try:
        qcrangethreshold = QcRangeThreshold.objects.get(station_id=station.id, variable_id=variable.id, month=month_id)
        qcrangethreshold.delete()
    except ObjectDoesNotExist:
        pass

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)



class get_step_threshold_form(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/quality_control/step_threshold.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.select_related('profile').exclude(is_reference=True)
        context['reference_station_list'] = Station.objects.filter(is_reference=True).order_by('name')
        context['station_profile_list'] = StationProfile.objects.all()
        context['station_watershed_list'] = Watershed.objects.all()
        context['station_district_list'] = AdministrativeRegion.objects.all() 

        return context


def get_step_threshold_entry(station_id, variable_id, is_reference=False):
    try:
        threshold = QcStepThreshold.objects.get(station_id=station_id, variable_id=variable_id)
        threshold_entry = {
            'min': str(threshold.step_min) if threshold.step_min is not None else '---',
            'max': str(threshold.step_max) if threshold.step_max is not None else '---',
        }        
    except ObjectDoesNotExist:
        if is_reference:
            try:
                threshold = QcStepThreshold.objects.get(station_id=station_id, variable_id=variable_id)
                threshold_entry = {
                    'min': str(threshold.step_min)+'*' if threshold.step_min is not None else '---',
                    'max': str(threshold.step_max)+'*' if threshold.step_max is not None else '---',
                }
            except ObjectDoesNotExist:
                threshold_entry = {
                    'min': '---',
                    'max': '---',
                }
        else:
            threshold_entry = {
                'min': '---',
                'max': '---',
            }        

    return threshold_entry


def format_step_thresholds(global_thresholds, reference_thresholds, custom_thresholds, variable_name):
    formated_threshold = {
        'variable_name': variable_name,
        'global':{
            'children':{
                'g_min': global_thresholds['min'],
                'g_max': global_thresholds['max'],
            }
        },
        'reference':{
            'children':{
                'r_min': reference_thresholds['min'],
                'r_max': reference_thresholds['max'],
            }
        },
        'custom':{
            'children':{
                'c_min': custom_thresholds['min'],
                'c_max': custom_thresholds['max'],
            }
        }
    }
    return [formated_threshold]


@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_step_threshold(request):
    station_id = request.GET.get('station_id', None)
    if station_id is None:
        response = {'message': "Field Station can not be empty."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)
    
    variable_ids = request.GET.get('variable_ids', None)
    if variable_ids is None:
        response = {'message': "Field Variables can not be empty."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)   

    station = Station.objects.get(id=int(station_id))
    variable_ids = [int(variable_id) for variable_id in variable_ids.split(",")]

    reference_station_id = station.reference_station_id
    if reference_station_id:
        reference_station = Station.objects.get(id=station.reference_station_id)
        reference_station_name = reference_station.name+' - '+reference_station.code
    else:
        reference_station = None
        reference_station_name = None

    data = {
        'reference_station_id': reference_station_id,
        'reference_station_name': reference_station_name,
        'variable_data': {},
    }

    for variable_id in variable_ids:
        variable = Variable.objects.get(id=variable_id)

        custom_thresholds = get_step_threshold_entry(station.id, variable.id, is_reference=False)
        
        if reference_station:
            reference_thresholds = get_step_threshold_entry(reference_station.id, variable.id, is_reference=True)
        else:
            reference_thresholds = {'min': '---', 'max': '---'}

        global_thresholds = {}
        if station.is_automatic:
            global_thresholds['min'] = -variable.step_hourly if variable.step_hourly else variable.step_hourly
            global_thresholds['max'] = variable.step_hourly
        else:
            global_thresholds['min'] = -variable.step if variable.step else variable.step
            global_thresholds['max'] = variable.step

        global_thresholds['min'] = '---' if global_thresholds['min'] is None else str(global_thresholds['min'])
        global_thresholds['max'] = '---' if global_thresholds['max'] is None else str(global_thresholds['max'])

        formated_thresholds = format_step_thresholds(global_thresholds, reference_thresholds, custom_thresholds, variable.name)

        data['variable_data'][variable.name] = formated_thresholds

    response = {'data': data}
    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"])
@wx_mapped_permission_required
def update_step_threshold(request):
    new_min = request.GET.get('new_min', None)    
    new_max = request.GET.get('new_max', None)
    station_id = request.GET.get('station_id', None)    
    variable_name = request.GET.get('variable_name', None)    

    station = Station.objects.get(id=station_id)
    variable = Variable.objects.get(name=variable_name)

    qcstepthreshold, created = QcStepThreshold.objects.get_or_create(station_id=station.id, variable_id=variable.id)

    qcstepthreshold.step_min = new_min
    qcstepthreshold.step_max = new_max

    qcstepthreshold.save()

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"])
@wx_mapped_permission_required
def delete_step_threshold(request):
    station_id = request.GET.get('station_id', None)    
    variable_name = request.GET.get('variable_name', None)    

    station = Station.objects.get(id=station_id)
    variable = Variable.objects.get(name=variable_name)

    try:
        qcstepthreshold = QcStepThreshold.objects.get(station_id=station.id, variable_id=variable.id)        
        qcstepthreshold.delete()
    except ObjectDoesNotExist:
        pass

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)



class get_persist_threshold_form(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/quality_control/persist_threshold.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['station_list'] = Station.objects.select_related('profile').exclude(is_reference=True)
        context['reference_station_list'] = Station.objects.filter(is_reference=True).order_by('name')
        context['station_profile_list'] = StationProfile.objects.all()
        context['station_watershed_list'] = Watershed.objects.all()
        context['station_district_list'] = AdministrativeRegion.objects.all() 

        return context


def get_persist_threshold_entry(station_id, variable_id, is_reference=False):
    try:
        threshold = QcPersistThreshold.objects.get(station_id=station_id, variable_id=variable_id)
        threshold_entry = {
            'var': str(threshold.minimum_variance) if threshold.minimum_variance is not None else '---',
            'win': str(threshold.window) if threshold.window is not None else '---',
        }        
    except ObjectDoesNotExist:
        if is_reference:
            try:
                threshold = QcPersistThreshold.objects.get(station_id=station_id, variable_id=variable_id)
                threshold_entry = {
                    'var': str(threshold.minimum_variance)+'*' if threshold.minimum_variance is not None else '---',
                    'win': str(threshold.window)+'*' if threshold.window is not None else '---',
                }
            except ObjectDoesNotExist:
                threshold_entry = {
                    'var': '---',
                    'win': '---',
                }
        else:
            threshold_entry = {
                'var': '---',
                'win': '---',
            }        

    return threshold_entry


def format_persist_thresholds(global_thresholds, reference_thresholds, custom_thresholds, variable_name):
    formated_threshold = {
        'variable_name': variable_name,
        'global':{
            'children':{
                'g_var': global_thresholds['var'],
                'g_win': global_thresholds['win'],
            }
        },
        'reference':{
            'children':{
                'r_var': reference_thresholds['var'],
                'r_win': reference_thresholds['win'],
            }
        },
        'custom':{
            'children':{
                'c_var': custom_thresholds['var'],
                'c_win': custom_thresholds['win'],
            }
        }
    }
    return [formated_threshold]


@require_http_methods(["GET"])
@wx_mapped_permission_required
def get_persist_threshold(request):
    station_id = request.GET.get('station_id', None)
    if station_id is None:
        response = {'message': "Field Station can not be empty."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)
    
    variable_ids = request.GET.get('variable_ids', None)
    if variable_ids is None:
        response = {'message': "Field Variables can not be empty."}
        return JsonResponse(response, status=status.HTTP_400_BAD_REQUEST)   

    station = Station.objects.get(id=int(station_id))
    variable_ids = [int(variable_id) for variable_id in variable_ids.split(",")]

    reference_station_id = station.reference_station_id
    if reference_station_id:
        reference_station = Station.objects.get(id=station.reference_station_id)
        reference_station_name = reference_station.name+' - '+reference_station.code
    else:
        reference_station = None
        reference_station_name = None

    data = {
        'reference_station_id': reference_station_id,
        'reference_station_name': reference_station_name,
        'variable_data': {},
    }

    for variable_id in variable_ids:
        variable = Variable.objects.get(id=variable_id)

        custom_thresholds = get_persist_threshold_entry(station.id, variable.id, is_reference=False)
        
        if reference_station:
            reference_thresholds = get_persist_threshold_entry(reference_station.id, variable.id, is_reference=True)
        else:
            reference_thresholds = {'var': '---', 'win': '---'}

        global_thresholds = {}
        if station.is_automatic:
            global_thresholds['var'] = variable.persistence_hourly
            global_thresholds['win'] = variable.persistence_window_hourly
        else:
            global_thresholds['var'] = variable.persistence
            global_thresholds['win'] = variable.persistence_window

        global_thresholds['var'] = '---' if global_thresholds['var'] is None else str(global_thresholds['var'])
        global_thresholds['win'] = '---' if global_thresholds['win'] is None else str(global_thresholds['win'])

        formated_thresholds = format_persist_thresholds(global_thresholds, reference_thresholds, custom_thresholds, variable.name)

        data['variable_data'][variable.name] = formated_thresholds

    response = {'data': data}
    return JsonResponse(response, status=status.HTTP_200_OK)    


@require_http_methods(["POST"])
@wx_mapped_permission_required
def update_persist_threshold(request):
    """
    Update or create a custom persist threshold.

    This fixes the old issue where existing QcPersistThreshold rows were
    fetched but their minimum_variance and window values were not updated
    before saving.
    """

    new_var = request.GET.get('new_var', None)
    new_win = request.GET.get('new_win', None)
    station_id = request.GET.get('station_id', None)
    variable_name = request.GET.get('variable_name', None)

    if station_id is None:
        return JsonResponse({
            'detail': 'Field Station can not be empty.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if variable_name is None:
        return JsonResponse({
            'detail': 'Field Variable can not be empty.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if new_var in [None, '']:
        return JsonResponse({
            'detail': 'Minimum variance can not be empty.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if new_win in [None, '']:
        return JsonResponse({
            'detail': 'Window can not be empty.'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        new_var = float(new_var)
    except (TypeError, ValueError):
        return JsonResponse({
            'detail': 'Minimum variance must be a valid number.'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        new_win = int(new_win)
    except (TypeError, ValueError):
        return JsonResponse({
            'detail': 'Window must be a valid whole number.'
        }, status=status.HTTP_400_BAD_REQUEST)

    station = Station.objects.get(id=station_id)
    variable = Variable.objects.get(name=variable_name)

    qcpersistthreshold, created = QcPersistThreshold.objects.get_or_create(
        station_id=station.id,
        variable_id=variable.id,
        defaults={
            'minimum_variance': new_var,
            'window': new_win,
        }
    )

    # Important:
    # Even if the row already existed, update the values before saving.
    qcpersistthreshold.minimum_variance = new_var
    qcpersistthreshold.window = new_win
    qcpersistthreshold.save()

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)


@require_http_methods(["POST"])
@wx_mapped_permission_required
def delete_persist_threshold(request):
    station_id = request.GET.get('station_id', None)    
    variable_name = request.GET.get('variable_name', None)    

    station = Station.objects.get(id=station_id)
    variable = Variable.objects.get(name=variable_name)

    try:
        qcpersistthreshold = QcPersistThreshold.objects.get(station_id=station.id, variable_id=variable.id)        
        qcpersistthreshold.delete()
    except ObjectDoesNotExist:
        pass

    response = {}
    return JsonResponse(response, status=status.HTTP_200_OK)


@api_view(['GET'])
def daily_means_data_view(request):
    station_id = request.GET.get('station_id', None)
    month = request.GET.get('month', None)
    variable_id_list = request.GET.get('variable_id_list', None)
    begin_year = request.GET.get('begin_year', None)
    end_year = request.GET.get('end_year', None)
    filter_year_query = ""
    filter_year_query_avg = ""
    period = "All years"

    if station_id is None:
        JsonResponse(data={"message": "'station_id' parameter cannot be null."}, status=status.HTTP_400_BAD_REQUEST)

    if month is None:
        JsonResponse(data={"message": "'month' parameter cannot be null."}, status=status.HTTP_400_BAD_REQUEST)

    if variable_id_list is not None:
        variable_id_list = json.loads(variable_id_list)
    else:
        JsonResponse(data={"message": "'variable_id_list' parameter cannot be null."},
                     status=status.HTTP_400_BAD_REQUEST)

    if begin_year is not None and end_year is not None:
        try:
            filter_year_query = "AND EXTRACT(YEAR from day) >= %(begin_year)s AND EXTRACT(YEAR from day) <= %(end_year)s"
            period = f"{begin_year} - {end_year}"

            begin_year = int(begin_year)
            end_year = int(end_year)
        except ValueError:
            JsonResponse(data={"message": "Invalid 'begin_year' or 'end_year' parameters."},
                         status=status.HTTP_400_BAD_REQUEST)

    month = int(month)
    res = {}
    variable_dict = {}
    variable_symbol_dict = {}
    for variable_id in variable_id_list:
        query_params_dict = {"station_id": station_id, "month": month, "variable_id": variable_id,
                             "begin_year": begin_year, "end_year": end_year}
        variable = Variable.objects.get(pk=variable_id)

        variable_symbol_dict[variable.symbol] = variable.name
        aggregation_type = variable.sampling_operation.name if variable.sampling_operation is not None else None
        data_dict = {}
        summary_dict = {}
        colspan = 1
        headers = ['Average']
        columns = ['value']

        if aggregation_type == 'Accumulation':
            colspan = 3
            headers = ['Greatest', 'Year', 'Years']
            columns = ['agg_value', 'year', 'years']

            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT data.day
                          ,data.sum_value
                          ,data.year
                          ,data.years
                    FROM (SELECT EXTRACT(DAY from day) as day
                                ,sum_value
                                ,EXTRACT(YEAR from day) as year
                                ,RANK () OVER (PARTITION BY EXTRACT(DAY from day) ORDER BY sum_value DESC) as rank
                                ,count(1) OVER (PARTITION BY EXTRACT(DAY from day)) as years
                         FROM daily_summary
                         WHERE station_id  = %(station_id)s
                           AND EXTRACT(MONTH from day) = %(month)s
                           AND variable_id = %(variable_id)s
                           {filter_year_query}) data
                    WHERE data.rank = 1
                """, query_params_dict)
                rows = cursor.fetchall()

                if len(rows) > 0:
                    df = pd.DataFrame(data=rows, columns=("day", "sum_value", "year", "years"))
                    for index, row in df.iterrows():
                        data_dict[int(row['day'])] = {"agg_value": round(row['sum_value'], 2), "year": row['year'],
                                                      "years": row['years']}

                    max_row = df.loc[df["sum_value"].idxmax()]
                    summary_dict = {"agg_value": round(max_row['sum_value'], 2), "year": max_row['year']}


        elif aggregation_type == 'Maximum':
            colspan = 4
            headers = ['Average', 'Extreme', 'Year', 'Years']
            columns = ['value', 'agg_value', 'year', 'years']

            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT data.day
                          ,summary.value
                          ,data.max_value
                          ,data.year
                          ,data.years
                    FROM (SELECT EXTRACT(DAY from day) as day
                                ,max_value
                                ,EXTRACT(YEAR from day) as year
                                ,RANK () OVER (PARTITION BY EXTRACT(DAY from day) ORDER BY max_value DESC) as rank
                                ,count(1) OVER (PARTITION BY EXTRACT(DAY from day)) as years
                         FROM daily_summary
                         WHERE station_id  = %(station_id)s
                           AND EXTRACT(MONTH from day) = %(month)s
                           AND variable_id = %(variable_id)s
                           {filter_year_query}) data,
                        (SELECT EXTRACT(DAY from day) as day
                                ,avg(max_value) as value
                         FROM daily_summary
                         WHERE station_id  = %(station_id)s
                           AND EXTRACT(MONTH from day) = %(month)s
                           AND variable_id = %(variable_id)s
                           {filter_year_query}
                         GROUP BY 1) summary
                    WHERE data.rank = 1
                    AND summary.day = data.day
                """, query_params_dict)
                rows = cursor.fetchall()

                if len(rows) > 0:
                    df = pd.DataFrame(data=rows, columns=("day", "value", "max_value", "year", "years"))
                    for index, row in df.iterrows():
                        data_dict[int(row['day'])] = {"value": round(row['value'], 2),
                                                      "agg_value": round(row['max_value'], 2), "year": row['year'],
                                                      "years": row['years']}

                    max_row = df.loc[df["max_value"].idxmax()]
                    summary_dict = {"value": round(df["value"].mean(), 2), "agg_value": round(max_row['max_value'], 2),
                                    "year": max_row['year']}

        elif aggregation_type == 'Minimum':
            headers = ['Average', 'Extreme', 'Year', 'Years']
            columns = ['value', 'agg_value', 'year', 'years']
            colspan = 4
            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT data.day
                          ,summary.value
                          ,data.min_value
                          ,data.year
                          ,data.years
                    FROM (SELECT EXTRACT(DAY from day) as day
                                ,min_value
                                ,EXTRACT(YEAR from day) as year
                                ,RANK () OVER (PARTITION BY EXTRACT(DAY from day) ORDER BY min_value ASC) as rank
                                ,count(1) OVER (PARTITION BY EXTRACT(DAY from day)) as years
                         FROM daily_summary
                         WHERE station_id  = %(station_id)s
                           AND EXTRACT(MONTH from day) = %(month)s
                           AND variable_id = %(variable_id)s
                           {filter_year_query}) data,
                        (SELECT EXTRACT(DAY from day) as day
                                ,avg(min_value) as value
                         FROM daily_summary
                         WHERE station_id  = %(station_id)s
                           AND EXTRACT(MONTH from day) = %(month)s
                           AND variable_id = %(variable_id)s
                           {filter_year_query}
                         GROUP BY 1) summary
                    WHERE data.rank = 1
                    AND summary.day = data.day
                """, query_params_dict)
                rows = cursor.fetchall()

                if len(rows) > 0:
                    df = pd.DataFrame(data=rows, columns=("day", "value", "min_value", "year", "years"))
                    for index, row in df.iterrows():
                        data_dict[int(row['day'])] = {"value": round(row['value'], 2),
                                                      "agg_value": round(row['min_value'], 2), "year": row['year'],
                                                      "years": row['years']}

                    max_row = df.loc[df["min_value"].idxmin()]
                    summary_dict = {"value": round(df["value"].mean(), 2), "agg_value": round(max_row['min_value'], 2),
                                    "year": max_row['year']}

        else:
            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT EXTRACT(DAY from day)
                          ,avg(avg_value)
                    FROM daily_summary data
                    WHERE station_id = %(station_id)s
                    AND EXTRACT(MONTH from day) = %(month)s
                    AND variable_id = %(variable_id)s
                    {filter_year_query}
                    GROUP BY 1
                """, query_params_dict)
                rows = cursor.fetchall()

                if len(rows) > 0:
                    for row in rows:
                        day = int(row[0])
                        value = round(row[1], 2)
                        data_dict[day] = {"value": value}

                    df = pd.DataFrame(data=rows, columns=("day", "value"))
                    summary_dict = {"value": round(df["value"].mean(), 2)}

        variable_dict[variable_id] = {
            'metadata': {
                "name": variable.symbol,
                "id": variable.id,
                "unit": variable.unit.name if variable.unit is not None else "",
                "unit_symbol": variable.unit.symbol if variable.unit is not None else "",
                "aggregation": aggregation_type,
                "colspan": colspan,
                "headers": headers,
                "columns": columns
            },
            'data': data_dict,
            'summary': summary_dict,
        }

    res['variables'] = variable_dict
    station = Station.objects.get(pk=station_id)
    res['station'] = {
        "name": station.name,
        "district": station.region.name,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "elevation": station.elevation,
        "variables": variable_symbol_dict,
    }

    res['params'] = {
        "month": month,
        "period": period,
    }

    return JsonResponse(res, status=status.HTTP_200_OK)


class DataInventoryView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/data_inventory.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['variable_list'] = Variable.objects.all()

        return context


@api_view(['GET'])
def get_data_inventory(request):
    start_year = request.GET.get('start_date', None)
    end_year = request.GET.get('end_date', None)
    is_automatic = request.GET.get('is_automatic', None)

    result = []

    query = """
        SELECT EXTRACT('YEAR' from station_data.datetime) AS year
            ,station.id
            ,station.name
            ,station.code
            ,station.is_automatic
            ,station.begin_date
            ,region.name
            ,TRUNC(AVG(station_data.record_count_percentage)::numeric, 2) AS avg_record_count
        FROM wx_stationdataminimuminterval AS station_data
        JOIN wx_station AS station ON station.id = station_data.station_id
        JOIN wx_administrativeregion AS region ON region.id = station.region_id
        WHERE EXTRACT('YEAR' from station_data.datetime) >= %(start_year)s
        AND EXTRACT('YEAR' from station_data.datetime) <  %(end_year)s
        AND station.is_automatic = %(is_automatic)s
        GROUP BY 1, station.id, region.name
        ORDER BY region.name, station.name
    """

    with connection.cursor() as cursor:
        cursor.execute(query, {"start_year": start_year, "end_year": end_year, "is_automatic": is_automatic})
        rows = cursor.fetchall()

        for row in rows:
            obj = {
                'year': row[0],
                'station': {
                    'id': row[1],
                    'name': row[2],
                    'code': row[3],
                    'is_automatic': row[4],
                    'begin_date': row[5],
                    'region': row[6],
                },
                'percentage': row[7],
            }
            result.append(obj)

    return Response(result, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_data_inventory_by_station(request):
    start_year = request.GET.get('start_date', None)
    end_year = request.GET.get('end_date', None)
    station_id: list = request.GET.get('station_id', None)
    record_limit = request.GET.get('record_limit', None)

    if station_id is None or len(station_id) == 0:
        return JsonResponse({"message": "\"station_id\" must not be null"}, status=status.HTTP_400_BAD_REQUEST)

    record_limit_lexical = ""
    if record_limit is not None:
        record_limit_lexical = f"LIMIT {record_limit}"

    result = []
    query = f"""
       WITH variable AS (
            SELECT variable.id, variable.name 
            FROM wx_variable AS variable
            JOIN wx_stationvariable AS station_variable ON station_variable.variable_id = variable.id
            WHERE station_variable.station_id = %(station_id)s
            ORDER BY variable.name
            {record_limit_lexical}
        )
        SELECT EXTRACT('YEAR' from station_data.datetime)
              ,limited_variable.id
              ,limited_variable.name
              ,TRUNC(AVG(station_data.record_count_percentage)::numeric, 2)
        FROM wx_stationdataminimuminterval AS station_data
        JOIN variable AS limited_variable ON limited_variable.id = station_data.variable_id
        JOIN wx_station station ON station_data.station_id = station.id
        WHERE EXTRACT('YEAR' from station_data.datetime) >= %(start_year)s
          AND EXTRACT('YEAR' from station_data.datetime) <  %(end_year)s
          AND station_data.station_id = %(station_id)s
        GROUP BY 1, limited_variable.id, limited_variable.name
        ORDER BY 1, limited_variable.name
    """

    with connection.cursor() as cursor:
        cursor.execute(query, {"start_year": start_year, "end_year": end_year, "station_id": station_id})
        rows = cursor.fetchall()

        for row in rows:
            obj = {
                'year': row[0],
                'variable': {
                    'id': row[1],
                    'name': row[2],
                },
                'percentage': row[3],
            }
            result.append(obj)

    return Response(result, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_station_variable_month_data_inventory(request):
    year = request.GET.get('year', None)
    station_id = request.GET.get('station_id', None)

    if station_id is None:
        return JsonResponse({"message": "Invalid request. Station id must be provided"},
                            status=status.HTTP_400_BAD_REQUEST)

    result = []
    query = """
        SELECT EXTRACT('MONTH' FROM station_data.datetime) AS month
              ,variable.id
              ,variable.name
              ,measurementvariable.name
              ,TRUNC(AVG(station_data.record_count_percentage)::numeric, 2)
        FROM wx_stationdataminimuminterval AS station_data
        JOIN wx_variable variable ON station_data.variable_id=variable.id
        LEFT JOIN wx_measurementvariable measurementvariable ON measurementvariable.id = variable.measurement_variable_id
        WHERE EXTRACT('YEAR' from station_data.datetime) = %(year)s
          AND station_data.station_id = %(station_id)s
        GROUP BY 1, variable.id, variable.name, measurementvariable.name
    """

    with connection.cursor() as cursor:
        cursor.execute(query, {"year": year, "station_id": station_id})
        rows = cursor.fetchall()

        for row in rows:
            obj = {
                'month': row[0],
                'variable': {
                    'id': row[1],
                    'name': row[2],
                    'measurement_variable_name': row[3] if row[3] is None else row[3].lower().replace(' ', '-'),
                },
                'percentage': row[4],
            }
            result.append(obj)

    return Response(result, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_station_variable_day_data_inventory(request):
    year = request.GET.get('year', None)
    month = request.GET.get('month', None)
    station_id = request.GET.get('station_id', None)
    variable_id = request.GET.get('variable_id', None)

    # validate input
    if not (year and month and station_id and variable_id):
        return Response(
            {"error": "year, month, station_id, and variable_id must be provided"},
            status=400
        )

    # cast to int
    year = int(year)
    month = int(month)
    station_id = int(station_id)
    variable_id = int(variable_id)

    try:
        # kick off async task
        task = data_inventory_month_view.delay(int(year), int(month), int(station_id), int(variable_id))

        return Response({"task_id": task.id}, status=202)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


# check the status of celery tasks
@api_view(['GET'])
def get_task_status(request, task_id):
    result = AsyncResult(task_id)

    if result.state == "PENDING":
        return Response({"status": "pending"}, status=202)

    elif result.state == "SUCCESS":
        return Response({"status": "completed", "data": result.result}, status=200)

    elif result.state == "FAILURE":
        return Response({"status": "failed", "error": str(result.result)}, status=500)

    else:
        return Response({"status": result.state}, status=202)


class UserInfo(views.APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        username = request.user.username
        return Response({'username': username})


class AvailableDataView(views.APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        try:
            json_data = json.loads(request.body)

            initial_date = json_data['initial_date']
            final_date = json_data['final_date']
            data_source = json_data['data_source']
            sv_list = [(row['station_id'], row['variable_id']) for row in json_data['series']]

            if (data_source=="monthly_summary"):
                initial_date = initial_date[:-2]+'01'
                final_date = final_date[:-2]+'01'
            elif (data_source=="yearly_summary"):
                initial_date = initial_date[:-5]+'01-01'
                final_date = final_date[:-5]+'01-01'

            initial_datetime = datetime.datetime.strptime(initial_date, '%Y-%m-%d')
            final_datetime = datetime.datetime.strptime(final_date, '%Y-%m-%d')

            num_days = (final_datetime-initial_datetime).days + 1            

            ret_data =  {
                'initial_date': initial_date,
                'final_date': final_date,
                'data_source': data_source,
                'sv_list': sv_list
            }

            query = f"""
                WITH series AS (
                    SELECT station_id, variable_id
                    FROM UNNEST(ARRAY{sv_list}) AS t(station_id int, variable_id int)
                ),
                daily_summ AS(
                    SELECT
                        MIN(day) AS first_day
                        ,MAX(day) AS last_day
                        ,station_id
                        ,variable_id
                        ,100*COUNT(*)/{num_days}::float AS percentage
                    FROM daily_summary
                    WHERE day >= '{initial_date}'
                      AND day <= '{final_date}'
                      AND (station_id, variable_id) IN (SELECT station_id, variable_id FROM series)
                    GROUP BY station_id, variable_id
                )
                SELECT
                    daily_summ.first_day 
                    ,daily_summ.last_day
                    ,series.station_id
                    ,series.variable_id
                    ,COALESCE(daily_summ.percentage, 0)
                FROM series
                LEFT JOIN daily_summ ON daily_summ.station_id = series.station_id AND daily_summ.variable_id = series.variable_id
            """

            result = []

            with connection.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
                for row in rows:
                    new_entry = {
                        'first_date': row[0],
                        'last_date': row[1],
                        'station_id': row[2],
                        'variable_id': row[3],
                        'percentage': round(row[4], 1)
                    }

                    result.append(new_entry)

            return JsonResponse({'data': result}, status=status.HTTP_200_OK)
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON format'}, status=status.HTTP_400_BAD_REQUEST)


def DataExportQueryData(initial_datetime, final_datetime, data_source, series, interval):
    DB_NAME=os.getenv('SURFACE_DB_NAME')
    DB_USER=os.getenv('SURFACE_DB_USER')
    DB_PASSWORD=os.getenv('SURFACE_DB_PASSWORD')
    DB_HOST=os.getenv('SURFACE_DB_HOST')
    config = f"dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD} host={DB_HOST}"

    config = settings.SURFACE_CONNECTION_STRING

    series = [(row['station_id'], row['variable_id']) for row in series]

    if (data_source=='raw_data'):
      dfs = []
      ini_day = initial_datetime;
      while (ini_day <= final_datetime):
        fin_day = ini_day + datetime.timedelta(days=1)
        fin_day = fin_day.replace(hour=0, minute=0, second=0, microsecond=0) 

        fin_day = min(fin_day, final_datetime)

        query = f"""
          WITH time_series AS(
            SELECT 
              timestamp AS datetime
            FROM
              GENERATE_SERIES(
                '{ini_day}'::TIMESTAMP
                ,'{fin_day}'::TIMESTAMP
                ,'{interval} SECONDS'
              ) AS timestamp
            WHERE timestamp BETWEEN '{ini_day}' AND '{fin_day}'
          )          
          ,series AS (
              SELECT station_id, variable_id
              FROM UNNEST(ARRAY{series}) AS t(station_id int, variable_id int)
          )
          ,processed_data AS (
            SELECT datetime
                ,station_id
                ,var.id as variable_id
                ,COALESCE(CASE WHEN var.variable_type ilike 'code' THEN data.code ELSE data.measured::varchar END, '-99.9') AS value
            FROM raw_data data
            LEFT JOIN wx_variable var ON data.variable_id = var.id
            WHERE (data.datetime >= '{ini_day}')
              AND ((data.datetime < '{fin_day}') OR (data.datetime='{fin_day}' AND {fin_day > final_datetime}))
              AND (station_id, variable_id) IN (SELECT station_id, variable_id FROM series)
          )
          SELECT 
            ts.datetime AS datetime
            ,series.variable_id AS variable_id
            ,series.station_id AS station_id
            ,COALESCE(data.value, '-99.9') AS value
          FROM time_series ts
          CROSS JOIN series
          LEFT JOIN processed_data AS data
            ON data.datetime = ts.datetime
            AND data.variable_id = series.variable_id
            AND data.station_id = series.station_id;
        """
        with psycopg2.connect(config) as conn:
          with conn.cursor() as cursor:
            logging.info(query)
            cursor.execute(query)
            data = cursor.fetchall()

        dfs.append(pd.DataFrame(data))

        ini_day += datetime.timedelta(days=1)
        ini_day = ini_day.replace(hour=0, minute=0, second=0, microsecond=0)

        if ini_day == final_datetime:
          break

      df = pd.concat(dfs)
      return df
    else:
      if (data_source=='hourly_summary'):
        query = f'''
            WITH time_series AS(
              SELECT 
                timestamp AS datetime
              FROM
                GENERATE_SERIES(
                  DATE_TRUNC('HOUR', '{initial_datetime}'::TIMESTAMP)
                  ,DATE_TRUNC('HOUR', '{final_datetime}'::TIMESTAMP)
                  ,'1 HOUR'
                ) AS timestamp
              WHERE timestamp BETWEEN '{initial_datetime}' AND '{final_datetime}'
            )       
            ,series AS (
                SELECT station_id, variable_id
                FROM UNNEST(ARRAY{series}) AS t(station_id int, variable_id int)
            )
            ,processed_data AS (
              SELECT
                datetime
                ,station_id
                ,var.id as variable_id
                ,COALESCE(CASE 
                  WHEN var.sampling_operation_id in (1,2) THEN data.avg_value::real
                  WHEN var.sampling_operation_id = 3      THEN data.min_value
                  WHEN var.sampling_operation_id = 4      THEN data.max_value
                  WHEN var.sampling_operation_id = 6      THEN data.sum_value
                  ELSE data.sum_value END, '-99.9') as value
              FROM hourly_summary data
              LEFT JOIN wx_variable var ON data.variable_id = var.id
              WHERE data.datetime BETWEEN '{initial_datetime}' AND '{final_datetime}'
                AND (station_id, variable_id) IN (SELECT station_id, variable_id FROM series)
            )
            SELECT 
              ts.datetime AS datetime
              ,series.variable_id AS variable_id
              ,series.station_id AS station_id
              ,COALESCE(data.value, '-99.9') AS value
            FROM time_series ts
            CROSS JOIN series
            LEFT JOIN processed_data AS data
              ON data.datetime = ts.datetime
              AND data.variable_id = series.variable_id
              AND data.station_id = series.station_id;
        '''    
      elif (data_source=='daily_summary'):      
        query = f'''
            WITH time_series AS(
              SELECT 
                timestamp::DATE AS date
              FROM
                GENERATE_SERIES(
                  DATE_TRUNC('DAY', '{initial_datetime}'::TIMESTAMP)
                  ,DATE_TRUNC('DAY', '{final_datetime}'::TIMESTAMP)
                  ,'1 DAY'
                ) AS timestamp
              WHERE timestamp BETWEEN '{initial_datetime}' AND '{final_datetime}'
            )       
            ,series AS (
                SELECT station_id, variable_id
                FROM UNNEST(ARRAY{series}) AS t(station_id int, variable_id int)
            )
            ,processed_data AS (
              SELECT
                day
                ,station_id
                ,var.id as variable_id
                ,COALESCE(CASE 
                  WHEN var.sampling_operation_id in (1,2) THEN data.avg_value::real
                  WHEN var.sampling_operation_id = 3      THEN data.min_value
                  WHEN var.sampling_operation_id = 4      THEN data.max_value
                  WHEN var.sampling_operation_id = 6      THEN data.sum_value
                  ELSE data.sum_value END, '-99.9') as value
              FROM daily_summary data
              LEFT JOIN wx_variable var ON data.variable_id = var.id
              WHERE data.day BETWEEN '{initial_datetime}' AND '{final_datetime}'
                AND (station_id, variable_id) IN (SELECT station_id, variable_id FROM series)
            )
            SELECT 
              ts.date AS date
              ,series.variable_id AS variable_id
              ,series.station_id AS station_id
              ,COALESCE(data.value, '-99.9') AS value
            FROM time_series ts
            CROSS JOIN series
            LEFT JOIN processed_data AS data
              ON data.day = ts.date
              AND data.variable_id = series.variable_id
              AND data.station_id = series.station_id;
        '''
      elif (data_source=='monthly_summary'):
        query = f'''
            WITH time_series AS(
              SELECT 
                timestamp::DATE AS date
              FROM
                GENERATE_SERIES(
                  DATE_TRUNC('MONTH', '{initial_datetime}'::TIMESTAMP)
                  ,DATE_TRUNC('MONTH', '{final_datetime}'::TIMESTAMP)
                  ,'1 MONTH'
                ) AS timestamp
              WHERE timestamp BETWEEN '{initial_datetime}' AND '{final_datetime}'
            )       
            ,series AS (
                SELECT station_id, variable_id
                FROM UNNEST(ARRAY{series}) AS t(station_id int, variable_id int)
            )
            ,processed_data AS (
              SELECT
                date
                ,station_id
                ,var.id as variable_id
                ,COALESCE(CASE 
                  WHEN var.sampling_operation_id in (1,2) THEN data.avg_value::real
                  WHEN var.sampling_operation_id = 3      THEN data.min_value
                  WHEN var.sampling_operation_id = 4      THEN data.max_value
                  WHEN var.sampling_operation_id = 6      THEN data.sum_value
                  ELSE data.sum_value END, '-99.9') as value
              FROM monthly_summary data
              LEFT JOIN wx_variable var ON data.variable_id = var.id
              WHERE data.date BETWEEN '{initial_datetime}' AND '{final_datetime}'
                AND (station_id, variable_id) IN (SELECT station_id, variable_id FROM series)
            )
            SELECT 
              ts.date AS date
              ,series.variable_id AS variable_id
              ,series.station_id AS station_id
              ,COALESCE(data.value, '-99.9') AS value
            FROM time_series ts
            CROSS JOIN series
            LEFT JOIN processed_data AS data
              ON data.date = ts.date
              AND data.variable_id = series.variable_id
              AND data.station_id = series.station_id;        
        '''
      elif (data_source=='yearly_summary'):
        query = f'''
            WITH time_series AS(
              SELECT 
                timestamp::DATE AS date
              FROM
                GENERATE_SERIES(
                  DATE_TRUNC('YEAR', '{initial_datetime}'::TIMESTAMP)
                  ,DATE_TRUNC('YEAR', '{final_datetime}'::TIMESTAMP)
                  ,'1 YEAR'
                ) AS timestamp
              WHERE timestamp BETWEEN '{initial_datetime}' AND '{final_datetime}'
            )       
            ,series AS (
                SELECT station_id, variable_id
                FROM UNNEST(ARRAY{series}) AS t(station_id int, variable_id int)
            )
            ,processed_data AS (
              SELECT
                date
                ,station_id
                ,var.id as variable_id
                ,COALESCE(CASE 
                  WHEN var.sampling_operation_id in (1,2) THEN data.avg_value::real
                  WHEN var.sampling_operation_id = 3      THEN data.min_value
                  WHEN var.sampling_operation_id = 4      THEN data.max_value
                  WHEN var.sampling_operation_id = 6      THEN data.sum_value
                  ELSE data.sum_value END, '-99.9') as value
              FROM yearly_summary data
              LEFT JOIN wx_variable var ON data.variable_id = var.id
              WHERE data.date BETWEEN '{initial_datetime}' AND '{final_datetime}'
                AND (station_id, variable_id) IN (SELECT station_id, variable_id FROM series)
            )
            SELECT 
              ts.date AS date
              ,series.variable_id AS variable_id
              ,series.station_id AS station_id
              ,COALESCE(data.value, '-99.9') AS value
            FROM time_series ts
            CROSS JOIN series
            LEFT JOIN processed_data AS data
              ON data.date = ts.date
              AND data.variable_id = series.variable_id
              AND data.station_id = series.station_id;        
        '''               

      with psycopg2.connect(config) as conn:
        with conn.cursor() as cursor:
          logging.info(query)
          cursor.execute(query)
          data = cursor.fetchall()

      df = pd.DataFrame(data)
    return df


class AppDataExportView(views.APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        serializer = serializers.DataExportSerializer(data=request.data)
        if serializer.is_valid():
            data_dict = {
                key: [dict(item) for item in value] if key == 'series' else value
                for key, value in serializer.validated_data.items()
            }

            initial_datetime = datetime.datetime.combine(data_dict['initial_date'],  data_dict['initial_time'])
            final_datetime = datetime.datetime.combine(data_dict['final_date'],  data_dict['final_time'])

            df = DataExportQueryData(initial_datetime, final_datetime, data_dict['data_source'], data_dict['series'], data_dict['interval'])

            try:
                file_format = data_dict.get('file_format')            
                if(file_format == 'excel'):
                    output = io.BytesIO()
                    df.to_excel(output, index=False, engine='openpyxl')
                    output.seek(0)

                    return HttpResponse(
                        output,
                        content_type='application/vnd.ms-excel',
                        headers={'Content-Disposition': 'attachment; filename="data.xlsx"'}
                    )
                elif(file_format == 'csv'):
                    output = io.StringIO()
                    df.to_csv(output, index=False)
                    output.seek(0)

                    return HttpResponse(
                        output,
                        content_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="data.csv"'}
                    )                

                elif(file_format == 'rinstat'):
                    output = io.StringIO()
                    df.to_csv(output, sep='\t', index=False)
                    output.seek(0)
                    
                    return HttpResponse(
                        output,
                        content_type='text/tab-separated-values',
                        headers={'Content-Disposition': 'attachment; filename="data.tsv"'}
                    )
                else:
                    return HttpResponse('Unsupported file format', status=400)
            except Exception as e:
                return HttpResponse('An error occurred: {}'.format(e), status=500)
        else:
            return HttpResponse(
                json.dumps({'message': 'Validation failed', 'errors': serializer.errors}),
                content_type='application/json',
                status=400
            )


class IntervalViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Interval.objects.all().order_by('seconds')
    serializer_class = serializers.IntervalSerializer


@csrf_exempt
@wx_mapped_permission_required
def synop_pressure_calc(request):
    if request.method == 'POST':
        station_id = tuple([request.GET['station_id']])
        data = json.loads(request.body)  # Parse JSON data
        pressure_value = float(data.get('pressure_value')) 
        date_value = data.get('date')

        station = Station.objects.get(pk=station_id[0]) 
        # Invert the station's UTC offset (minutes) to convert its local time to UTC.
        offset = datetime.timedelta(minutes=(-1 * station.utc_offset_minutes))

        # Convert the string to a datetime object:
        dt_object = datetime.datetime.strptime(date_value, "%Y-%m-%d %H:%M")
        dt_object = dt_object + offset

        # Subtract 24 hours:
        dt_24_hours_ago = dt_object - timedelta(days=1)

        # Format the resulting datetime object back into a string:
        formatted_date_string = dt_24_hours_ago.strftime("%Y-%m-%dT%H:%MZ")

        pressure_variable_id = (61,)

        # grab the query output for the Station pressure at sea level
        dataset = get_station_raw_data('variable', pressure_variable_id, None, formatted_date_string, formatted_date_string,
                                           station_id)

        if dataset['results']:
            pressure_data = dataset['results']['Pressure at Sea Level (hPa)']

            # Since there's only one station, get the first (and only) key
            station_name = next(iter(pressure_data))

            value = pressure_data[station_name]['data'][0]['value']  

            # return the pressure difference
            # "value" is the pressure from 24 hrs ago
            # "pressure_value" is the current pressure
            pressure_difference = round((pressure_value - value), 1) if pressure_value != -99.9 and value != -99.9 else -99.9
        else:
            pressure_difference = 'no data'

        # display the error message
        if dataset['messages']:
            logger.error(f"An error occured whilst retrieving 24hr baromatric change value: {dataset['messages']}")
        
    return JsonResponse({'dataset': pressure_difference}, status=status.HTTP_200_OK)



@csrf_exempt
@wx_mapped_permission_required
def synop_precip_calc(request):
    if request.method == 'POST':
        station_id = int(request.GET['station_id'])
        data = json.loads(request.body)  # Parse JSON data
        # precip_value = float(data.get('precipitation_value')) 
        precip_24_hr = 0
        date_value = data.get('date')

        station = Station.objects.get(pk=station_id) 
        # Invert the station's UTC offset (minutes) to convert its local time to UTC.
        offset = datetime.timedelta(minutes=(-1 * station.utc_offset_minutes))

        # Convert the string to a datetime object:
        dt_object = datetime.datetime.strptime(date_value, "%Y-%m-%d %H:%M")
        dt_object = dt_object + offset

        # Subtract 24 hours:
        dt_24_hours_ago = dt_object - timedelta(days=1)

        # Format the resulting datetime object back into a string:
        formatted_dt_24_hours_ago = dt_24_hours_ago.strftime("%Y-%m-%dT%H:%MZ")

        # Format the datetime object also
        formatted_dt_object = dt_object.strftime("%Y-%m-%dT%H:%MZ")

        precipitation_variable_id = 0

        sql_string = """
            SELECT measured
            FROM raw_data
            WHERE station_id = %s
            AND variable_id = %s
            AND datetime >= %s AND datetime < %s;
        """

        if sql_string:
            with connection.cursor() as cursor:

                cursor.execute(sql_string, [station_id, precipitation_variable_id, formatted_dt_24_hours_ago, formatted_dt_object])

                rows = cursor.fetchall()
            
                # adding to get the total precipitation in 24 hours
                precip_24_hr = sum(row[0] for row in rows if row[0] != -99.9)
                # the below is leagacy code of the above
                # precip_24_hr = sum(row[0] for row in rows if row[0] != -99.9) + precip_value
        
    return JsonResponse({'dataset': precip_24_hr}, status=status.HTTP_200_OK)



@api_view(['POST'])
@wx_mapped_permission_required
def synop_update(request):
    try:
        date_str = request.GET.get('date')
        station_id = request.GET.get('station_id')
        hours_dict = request.data.get('table')

        if not date_str or not station_id or not hours_dict:
            return JsonResponse({"error": "Missing required fields"}, status=400)

        day = datetime.datetime.strptime(date_str, '%Y-%m-%d')

        station = get_object_or_404(Station, id=station_id)

        variables = Variable.objects.in_bulk()

        now_utc = datetime.datetime.now().astimezone(pytz.UTC)
        now_utc += datetime.timedelta(hours=1)

        datetime_offset = pytz.FixedOffset(station.utc_offset_minutes)
        seconds = 3600

        records_list = []

        for hour, hour_data in hours_dict.items():
            data_datetime = day.replace(hour=int(hour))
            data_datetime = datetime_offset.localize(data_datetime)

            if data_datetime <= now_utc and hour_data:
                remarks = hour_data.pop('remarks', None)

                observer = hour_data.pop('observer', None)

                hour_data.pop('action', None)

                for variable_id, measurement in hour_data.items():
                    variable = variables.get(int(variable_id))

                    if measurement is None:
                        measurement_value = settings.MISSING_VALUE
                        measurement_code = settings.MISSING_VALUE_CODE
                    else:
                        if variable and variable.variable_type == 'Numeric':
                            try:
                                measurement_value = float(measurement)
                                measurement_code = measurement
                            except Exception:
                                measurement_value = settings.MISSING_VALUE
                                measurement_code = settings.MISSING_VALUE_CODE
                        else:
                            measurement_value = settings.MISSING_VALUE
                            measurement_code = measurement

                    records_list.append((
                        station_id, variable_id, seconds, data_datetime,
                        measurement_value, 1, None, None, None, None,
                        None, None, None, None, False, remarks,
                        observer, measurement_code
                    ))

        task = save_synop_form.delay(
            records_list,
            date_str,  # safer than datetime
            station_id,
            station.utc_offset_minutes
        )

        return JsonResponse({"taskId": task.id}, status=200)

    except Exception as e:
        logger.error(repr(e))
        return JsonResponse({"error": "Failed to start task"}, status=500)


def get_synop_data(station, date, utc_offset_minutes=0):
    datetime_offset = pytz.FixedOffset(utc_offset_minutes)
    request_datetime = datetime_offset.localize(date)

    start_datetime = request_datetime
    end_datetime = request_datetime + datetime.timedelta(days=1)

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:
            query = f"""
                SELECT 
                    (datetime + INTERVAL '{utc_offset_minutes} MINUTES') AT TIME ZONE 'utc',
                    variable_id,
                    CASE WHEN var.variable_type = 'Numeric' THEN measured::VARCHAR
                        ELSE code
                    END AS value,
                    remarks,
                    observer
                FROM raw_data
                JOIN wx_variable var ON raw_data.variable_id=var.id
                WHERE station_id = {station.id}
                    AND datetime >= '{start_datetime}'
                    AND datetime < '{end_datetime}'
                """

            cursor.execute(query)
            data = cursor.fetchall()

            # passing the timezone information in the response. This will be the timezone information for each station, not the country
            timezoneOffsetStr = str(datetime.timedelta(minutes=(utc_offset_minutes)))
    
    # get station wis2publishing id and status
    wis2box_publish = (
        Wis2BoxPublish.objects
        .filter(station_id=station.id)
        .values("id", "publishing")
        .first()
    )

    if wis2box_publish is None:
        wis2box_publish = {
            "id": None,
            "publishing": False,
        }



    return data, utc_offset_minutes, timezoneOffsetStr, wis2box_publish


@api_view(['GET'])
@wx_mapped_permission_required
def synop_load(request):
    try:
        date = datetime.datetime.strptime(request.GET['date'], '%Y-%m-%d')
        station = Station.objects.get(id=request.GET['station_id'])
    except ValueError as e:
        logger.error(repr(e))
        return HttpResponse(status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(repr(e))
        return HttpResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    response = get_synop_data(station, date, station.utc_offset_minutes)

    return JsonResponse(response, status=status.HTTP_200_OK, safe=False)


@api_view(['POST'])
@wx_mapped_permission_required
def synop_delete(request):
    # Extract data from the request
    request_date_str = request.GET.get('date', None)
    hour = request.GET.get('hour', None)
    station_id = request.GET.get('station_id', None)
    
    hour = int(hour)

    variable_id_list = request.data.get('variable_ids')

    # Validate inputs
    if (None in [request_date_str, hour, station_id, variable_id_list]):
        message = "Invalid request. 'date', 'hour', 'station_id', and 'variable_ids' must be provided."
        return JsonResponse({"message": message}, status=status.HTTP_400_BAD_REQUEST)

    # Validate date format
    try:
        request_date = datetime.datetime.strptime(request_date_str, '%Y-%m-%d')
    except ValueError:
        message = "Invalid date format. The expected date format is 'YYYY-MM-DD'"
        return JsonResponse({"message": message}, status=status.HTTP_400_BAD_REQUEST)
    
    variable_id_list = [int(v) for v in tuple(variable_id_list)]
    station = Station.objects.get(id=station_id)
    datetime_offset = pytz.FixedOffset(station.utc_offset_minutes)
    request_datetime = datetime_offset.localize(request_date.replace(hour=hour))
    request_start_range_dt = request_datetime - timedelta(days=10)
    request_end_range_dt = request_datetime + timedelta(days=10)

    queries = {
        "grab_relevant_chunks": """
            SELECT 
            show_chunks('raw_data', newer_than => %s, older_than => %s)
        """,
        "delete_raw_data": """
            DELETE FROM {raw_data_chunk}
            WHERE station_id = %s
            AND variable_id = ANY(%s)
            AND datetime = %s
        """,
        "create_daily_summary": """
            INSERT INTO wx_dailysummarytask (station_id, date, created_at, updated_at)
            VALUES (%s, %s, now(), now())
            ON CONFLICT DO NOTHING
        """,
        "create_hourly_summary": """
            INSERT INTO wx_hourlysummarytask (station_id, datetime, created_at, updated_at)
            VALUES (%s, %s, now(), now())
            ON CONFLICT DO NOTHING
        """,
        "get_last_updated": """
            SELECT max(last_data_datetime)
            FROM wx_stationvariable
            WHERE station_id = %s
              AND variable_id = ANY(%s)
            ORDER BY 1 DESC
        """,
        "update_last_updated": """
            WITH rd AS (
                SELECT station_id, variable_id, measured, code, datetime,
                       RANK() OVER (PARTITION BY station_id, variable_id ORDER BY datetime DESC) AS datetime_rank
                FROM {raw_data_chunk}
                WHERE station_id = %s
                  AND variable_id = ANY(%s)
            )
            UPDATE wx_stationvariable sv
            SET last_data_datetime = rd.datetime,
                last_data_value = rd.measured,
                last_data_code = rd.code
            FROM rd
            WHERE sv.station_id = rd.station_id
              AND sv.variable_id = rd.variable_id
              AND rd.datetime_rank = 1
        """
    }

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:
            # grab relevant chunks, holding data within 10 days of the request datetime
            # this reduces the overhead of looking through the entire raw_data table
            cursor.execute(queries['grab_relevant_chunks'], [request_start_range_dt, request_end_range_dt])
            
            chunks = [row[0] for row in cursor.fetchall()]

            for chunk in chunks:
                cursor.execute(queries['delete_raw_data'].format(raw_data_chunk=chunk), [station_id, variable_id_list, request_datetime])

            # After deleting from raw_data, is necessary to update the daily and hourly summary tables.
            cursor.execute(queries["create_daily_summary"], [station_id, request_datetime])
            cursor.execute(queries["create_hourly_summary"], [station_id, request_datetime])
            
            # If succeed in inserting new data, it's necessary to update the 'last data' columns in wx_stationvariable tabl.
            cursor.execute(queries["get_last_updated"], [station_id, variable_id_list])
            
            last_data_datetime_row = cursor.fetchone()

            if last_data_datetime_row and last_data_datetime_row[0] == request_datetime:
                # loop through relevant chunks instead of the entire raw_data
                for chunk in chunks:
                    cursor.execute(queries["update_last_updated"].format(raw_data_chunk=chunk), [station_id, variable_id_list])

        conn.commit()

    return Response([], status=status.HTTP_200_OK)



class MonthlyFormView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/data/monthly_form.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # get station information
        context['station_list'] = Station.objects.filter(is_automatic=False, is_active=True, is_reference=False).values('id', 'name', 'code')

        # retrieves the ag_grid_config, the id's of columns which should be numbers and a dict of col id's mapped to wmocodevalues
        context['ag_grid_config'], context['num_validate_ids'], context['variable_ids'] = get_monthly_capture_config()

        # Get parameters from request or set default values
        station_id = self.request.GET.get('station_id', 'null')
        context['station_id'] = station_id
        # context['date'] = date

        # changing the date so that if reflects that users timezone
        offset = datetime.timedelta(minutes=(settings.TIMEZONE_OFFSET))
        dt_object = datetime.datetime.now() + offset

        # This will store it as a string like "2026-05"
        context['date'] = dt_object.strftime('%Y-%m')

        context['timezone_offset'] = offset

        return context



def get_monthly_capture_config():
    # variable symbols group in order of the physical monthly entry form
    variable_symbols = [
        'PRECIP', 'TEMPMAX', 'TEMPMIN', 'TEMPAVG', 
        'WNDMIL', 'WINDRUN', 'SUNSHNHR', 'EVAPINI', 
        'EVAPRES', 'EVAPPAN', 'TEMP', 'TEMPWB', 
        'TSOIL1', 'TSOIL4', 'DYTHND', 'DYFOG', 
        'DYHAIL', 'DYGAIL', 'TOTRAD', 'RH@TMAX', 
        'RHMAX', 'RHMIN'
    ]

    col_widths = [
        110, 110, 110, 110, 
        110, 110, 110, 110, 
        110, 110, 110, 110, 
        110, 110, 110, 110, 
        110, 110, 110, 110, 
        110, 110
    ]

    var_class_dict = {
        "temp-cols-group": ['TEMP', 'TEMPMAX', 'TEMPMIN', 'TEMPAVG', 'TEMPWB'],
        "precip-cols-group": ['PRECIP', 'EVAPRES', 'EVAPPAN', 'EVAPINI'],
        "misc-cols-group": ['DYHAIL', 'DYGAIL', 'DYTHND', 'DYFOG', 'SUNSHNHR', 'TOTRAD'],
        "hum-cols-group": ['RH@TMAX', 'RHMAX', 'RHMIN'],
        "wind-cols-group": ['WNDMIL', 'WINDRUN'],
        "soil-cols-group": ['TSOIL1', 'TSOIL4'],
    }

    # Get wmo code values to use in dropdown for code variables
    wmocodevalue_list = WMOCodeValue.objects.values('value', 'code_table_id')
    wmocodevalue_dict = {}
    for item in wmocodevalue_list:
        code_table_id = item['code_table_id']

        if code_table_id not in wmocodevalue_dict:
            wmocodevalue_dict[code_table_id] = []

        wmocodevalue_dict[code_table_id].append(item['value'])

    # Reverse mapping from symbol to class name
    symbol_to_class = {}
    for class_name, symbols in var_class_dict.items():
        for symbol in symbols:
            symbol_to_class[symbol] = class_name

    # Get a variable list using the order of variable_ids list and also check for symbols which are missing of don't exist
    variable_dict = {variable.symbol: variable for variable in Variable.objects.filter(symbol__in=variable_symbols)}
    if missing_symbols := [
        symbol for symbol in variable_symbols if symbol not in variable_dict
    ]:
        raise ValueError(f"Unable to Load the synop capture form. The following variable symbols are missing in the database: {missing_symbols}")
    
    variable_list = [variable_dict[variable_symbol] for variable_symbol in variable_symbols]

    # loadig the context with the required information to display the headers (id, name, code, col_width)
    context = [
        {
            "id": var.pk, 
            "name": var.name, 
            "synoptic_code": var.synoptic_code_form, 
            "var_type": var.variable_type.lower(),
            "col_width": col_widths[variable_list.index(var)],
            "col_class": symbol_to_class.get(var.symbol),
            "dropdown_codes": wmocodevalue_dict.get(var.code_table_id, []),
        } 
        for var in variable_list
        
    ]
    context.extend(
        (
            {
                "id": "remarks",
                "name": "Remarks",
                "synoptic_code": None,
                "col_width": 200,
                "col_class": "misc-cols-group",
            },
            {
                "id": "observer",
                "name": "Observer",
                "synoptic_code": None,
                "col_width": 250,
                "col_class": "misc-cols-group",
            },
        )
    )

    # get the id's of all variables which columns are numeric, the id's are stored as strings
    num_validate_ids = [str(var.pk) for var in variable_list if var.variable_type.lower() == "numeric"]
    # getting the id's of all variables
    variable_ids = [str(var.pk) for var in variable_list]

    return context, num_validate_ids, variable_ids



# wis2box dashboard page
class WIS2DashboardView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/wis2dashboard/wis2dashboard.html"
    
    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs)


# to grap data for the wis2 dashboard
@wx_mapped_permission_required
def wis2dashboard_records_list(request):
    try:
        search_criteria = request.GET.get('search_criteria', '').strip().lower()
        
        if search_criteria == 'all':
            queryset = Wis2BoxPublish.objects.select_related("station")
        elif search_criteria == 'publishing':
            queryset = Wis2BoxPublish.objects.filter(publishing=True).select_related("station")
        elif search_criteria == 'publish_status':
            queryset = Wis2BoxPublish.objects.filter(publishing=True).select_related("station")
        elif search_criteria == 'not publishing':
            queryset = Wis2BoxPublish.objects.filter(publishing=False).select_related("station")
        elif search_criteria == 'trans pub':
            queryset = Wis2BoxPublish.objects.filter(publishing=True, hybrid=True).select_related("station")
        elif search_criteria == 'trans nonpub':
            queryset = Wis2BoxPublish.objects.filter(publishing=False, hybrid=True).select_related("station")
        else:
            queryset = Wis2BoxPublish.objects.select_related("station")
        
        if not queryset.exists():
            logger.info("No records found!")
            return JsonResponse({"error": "No records found"}, status=204)

        records = list(queryset.values(
            "id", 
            "publishing", 
            "station__id", 
            "station__name", 
            "station__wigos", 
            "station__is_automatic", 
            "station__is_synoptic", 
            "publish_success", 
            "publish_fail",
            "hybrid",
            "add_gts",
            "hybrid_station__name"
        ))

        # calculate the total success and fails to create the graph
        publish_success_count = 0
        publish_fail_count = 0

        for record in records:
            if not record['station__wigos']:
                record['station__wigos'] = "WIGOS ID NOT FOUND"

            station_status = []
            # getting the publishing status
            if record['publishing']:
                station_status.append("Publishing")

                # hybrid status
                if record['hybrid']:
                    station_status.append("Hybrid")

                # gts status
                if record['add_gts']:
                    station_status.append("GTS")

                # getting the automatic/manual status
                if record['station__is_automatic']:
                    station_status.append("Automatic")
                else:
                    station_status.append("Manual")

                # synoptic status
                if record['station__is_synoptic']:
                    station_status.append("Synoptic")
                    
            else:
                station_status.append("Not Publishing")

                # hybrid status
                if record['hybrid']:
                    station_status.append("Hybrid")

                # gts status
                if record['add_gts']:
                    station_status.append("GTS")

                # getting the automatic/manual status
                if record['station__is_automatic']:
                    station_status.append("Automatic")
                else:
                    station_status.append("Manual")

                # getting the synoptic status
                if record['station__is_synoptic']:
                    station_status.append("Synoptic")

            # adding the Status to the record object
            record['status'] = station_status

            publish_success_count += record['publish_success']
            publish_fail_count += record['publish_fail']

        if search_criteria == 'publish_status':
            return JsonResponse({"items": records, "publish_success": publish_success_count, "publish_fail": publish_fail_count}, encoder=DjangoJSONEncoder)
        
        return JsonResponse({"items": records}, encoder=DjangoJSONEncoder)

    except Exception as e:
        logger.error(f"An error occured: {e}")
        return JsonResponse({"error": str(e)}, status=500)
    

# to fetch publishig logs information
@wx_mapped_permission_required
def publishingLogs(request, pk):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])  # Only allow GET requests

    logs = Wis2BoxPublishLogs.objects.filter(publish_station__id=pk).values(
        "id", "created_at", "last_modified", "publish_station", 
        "success_log", "log", "wis2message_exist", "wis2message"
    )

    # getting station metadata
    station_metadata = Wis2BoxPublish.objects.filter(id=pk).values("station__name", "station__wigos", "publish_success", "publish_fail", "hybrid", "hybrid_station__name")
    return JsonResponse({"logs":list(logs), "station_metadata":list(station_metadata), "timezone_offset":settings.TIMEZONE_OFFSET}, safe=False)  # Convert QuerySet to list


# download wis2 logs
@wx_mapped_permission_required
def downloadWis2Logs(request, pk):
    """
    Downloads log files associated with a specific publish station (identified by pk) as a ZIP file.
    """
    logs = Wis2BoxPublishLogs.objects.filter(publish_station__id=pk)
    
    if not logs.exists():
        return HttpResponse("No logs found", status=404)
    
    temp_dir = tempfile.mkdtemp()
    zip_filename = os.path.join(temp_dir, f"logs_{pk}.zip")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for log_entry in logs:
            # Format the timestamp for uniqueness and readability
            timestamp = localtime(log_entry.created_at).strftime("%Y-%m-%d_%H-%M-%S")
            file_name = f"{timestamp}-{log_entry.id}-logfile.txt"
            file_path = os.path.join(temp_dir, file_name)
            
            # Write log content to a temporary file
            with open(file_path, "w", encoding="utf-8") as log_file:
                log_file.write(log_entry.log)
            
            # Add the file to the ZIP archive
            zipf.write(file_path, arcname=file_name)
    
    # Read the ZIP file and prepare it for download
    with open(zip_filename, "rb") as zip_file:
        response = HttpResponse(zip_file.read(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="logs_{pk}.zip"'
    
    # Cleanup temporary files and directory
    for file in os.listdir(temp_dir):
        os.remove(os.path.join(temp_dir, file))
    os.rmdir(temp_dir)
    
    return response


# download wis2 message
@wx_mapped_permission_required
def downloadWis2Message(request, pk):
    """
    Downloads WIS2 messages associated with a specific publish station (identified by pk) as a ZIP file.
    """
    messages = Wis2BoxPublishLogs.objects.filter(publish_station__id=pk, wis2message_exist=True)
    
    if not messages.exists():
        return HttpResponse("No logs found", status=404)
    
    temp_dir = tempfile.mkdtemp()
    zip_filename = os.path.join(temp_dir, f"messages_{pk}.zip")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for message in messages:
            # Format the timestamp for uniqueness and readability
            timestamp = localtime(message.created_at).strftime("%Y-%m-%d_%H-%M-%S")
            file_name = f"{timestamp}-{message.id}-messagefile.csv"
            file_path = os.path.join(temp_dir, file_name)
            
            # Write message content to a temporary file
            with open(file_path, "w", encoding="utf-8") as msg_file:
                msg_file.write(message.wis2message)
            
            # Add the file to the ZIP archive
            zipf.write(file_path, arcname=file_name)
    
    # Read the ZIP file and prepare it for download
    with open(zip_filename, "rb") as zip_file:
        response = HttpResponse(zip_file.read(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="messages_{pk}.zip"'
    
    # Cleanup temporary files and directory
    for file in os.listdir(temp_dir):
        os.remove(os.path.join(temp_dir, file))
    os.rmdir(temp_dir)
    
    return response

# to load the form to update local wis2 credential
@method_decorator(wx_mapped_permission_required, name="dispatch")
class LocalWisCredentialsUpdateView(generics.RetrieveUpdateAPIView):
    queryset = LocalWisCredentials.objects.all()
    serializer_class = serializers.LocalWisCredentialsSerializer

    def get_object(self):
        try:
            return LocalWisCredentials.load()  # Ensures only one instance is updated
        except Exception as e:
            logger.error(f'An error occurred while fetching LocalWisCredentials: {e}')
            raise


# to load the form to update regional wis2 credential
@method_decorator(wx_mapped_permission_required, name="dispatch")
class RegionalWisCredentialsUpdateView(generics.RetrieveUpdateAPIView):
    queryset = RegionalWisCredentials.objects.all()
    serializer_class = serializers.RegionalWisCredentialsSerializer

    def get_object(self):
        try:
            return RegionalWisCredentials.load()  # Ensures only one instance is updated
        except Exception as e:
            logger.error(f'An error occurred while fetching RegionalWisCredentials: {e}')
            raise


# to load the form to update the stations publishing settings
@method_decorator(wx_mapped_permission_required, name="dispatch")
class configWis2StationUpdateView(generics.RetrieveUpdateAPIView):
    queryset = Wis2BoxPublish.objects.all()
    serializer_class = serializers.Wis2BoxPublishSerializer

    def get_object(self):
        station_id = self.kwargs.get("pk")  # Get ID from URL
        try:
            return Wis2BoxPublish.objects.get(id=station_id)  # Fetch entry by ID
        except Exception as e:
            logger.error(f'An error occurred while fetching Wis2BoxPublish stations data: {e}')
            raise


# shows all stations which are currently set to wis2 publishing
@method_decorator(wx_mapped_permission_required, name="dispatch")
class Wis2BoxPublishListView(views.APIView):
    def get(self, request):
        # Query all the Wis2BoxPublish objects where publishing is True
        queryset = Wis2BoxPublish.objects.filter(publishing=True)
        
        # Serialize the queryset
        serializer = serializers.Wis2BoxPublishSerializerReadPublishing(queryset, many=True)
        
        # Return the serialized data as a response
        return Response(serializer.data, status=status.HTTP_200_OK)


class publishingOffsetViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Wis2PublishOffset.objects.all()
        

    def get_serializer_class(self):
        return serializers.Wis2PublishOffsetSerializerRead


@csrf_exempt
@wx_mapped_permission_required
def push_to_wis2box(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            station_id = int(data.get("stationId"))

            if not station_id:
                return JsonResponse({}, status=400)

            # attempt station push to wis2box
            wis2push_task = tasks.wis2publish_task_now.delay(station_id)

            return JsonResponse({"celery_task_id":wis2push_task.id}, status=200)
        except Exception as e:
            return JsonResponse({e}, status=500)

    return JsonResponse({}, status=405)  # Method Not Allowed



# updated synop capture form view
class SynopCaptureView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/data/synop_capture_form.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # get synop station information
        context['station_list'] = Station.objects.filter(is_synoptic=True, is_reference=False).values('id', 'name', 'code')
        # retrieves the ag_grid_config, the id's of columns which should be numbers and a dict of col id's mapped to wmocodevalues
        context['ag_grid_config'], context['num_validate_ids'], context['variable_ids'] = get_synop_capture_config()

        # Get parameters from request or set default values
        station_id = self.request.GET.get('station_id', 'null')
        context['station_id'] = station_id
         # context['date'] = date

        # changing the date so that if reflects that users timezone
        offset = datetime.timedelta(minutes=(settings.TIMEZONE_OFFSET))
        dt_object = datetime.datetime.now() + offset

        context['date'] = dt_object.date()
        context['timezone_offset'] = offset

        return context    
    

def get_synop_capture_config():
    # List of variables, in order, for synoptic station input form
    # if a var is added/removed, do the same in the col_widths list

    # # variable symbols group in order of their relationship to each other
    # variable_symbols = [
    #     'RH', 'VISBY-km', 'WNDDIR', 'WNDSPD', 'TDEWPNT', 'TEMPWB', 
    #     'TEMP', 'TEMPMAX', 'TEMPMIN', 'PRESSTN', 'PRESSEA', 'BAR24C', 
    #     'PRECIND', 'PRECIP', 'PREC24H', 'PRECDUR', 'STSKY', 'PRSWX',
    #     'W1', 'W2', 'Nh', 'CLDTOT', 'LOWCLHFt', 'CL', 'CM', 'CH', 'DL', 
    #     'DM', 'DH', 'N1', 'C1', 'hhFt1', 'N2', 'C2', 'hhFt2', 'N3', 'C3', 
    #     'hhFt3', 'N4', 'C4', 'hhFt4', 'SpPhenom'
    # ]

    # # column widths in order of the variable_symbols list
    # col_widths = [
    #     200, 220, 200, 200, 200, 250, 250, 255, 250, 200, 
    #     250, 250, 200, 200, 250, 250, 200, 200, 200, 200, 
    #     250, 200, 200, 200, 200, 200, 200, 200, 200, 200, 
    #     200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 
    #     200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 
    #     500, 200
    # ]

    # variable symbols group in order of the physical synop entry form
    variable_symbols = [
        'PRECIND', 'LOWCLHFt', 'VISBY-km',
        'CLDTOT', 'WNDDIR', 'WNDSPD', 'TEMP', 'TDEWPNT', 'TEMPWB',
        'RH', 'PRESSTN', 'PRESSEA', 'BAR24C', 'PRECIP', 'PREC24H', 'PRECDUR', 'PRSWX',
        'W1', 'W2', 'Nh', 'CL', 'CM', 'CH', 'STSKY',
        'DL', 'DM', 'DH', 'TEMPMAX', 'TEMPMIN', 'N1', 'C1', 'hhFt1',
        'N2', 'C2', 'hhFt2', 'N3', 'C3', 'hhFt3', 'N4', 'C4', 'hhFt4', 'SpPhenom'
    ]

    col_widths = [
        110, 110, 110, 110, 110, 110, 110, 110, 110, 110, 
        110, 110, 110, 110, 110, 110, 110, 110, 110, 110, 
        110, 110, 110, 110, 110, 110, 110, 110, 110, 110, 
        110, 110, 110, 110, 110, 110, 110, 110, 110, 110, 
        110, 110
    ]

    var_class_dict = {
        "misc-cols-group": ['RH', 'VISBY-km', 'SpPhenom'],
        "wind-cols-group": ['WNDDIR', 'WNDSPD'],
        "temp-cols-group": ['TDEWPNT', 'TEMPWB', 'TEMP', 'TEMPMAX', 'TEMPMIN'],
        "pressure-cols-group": ['PRESSTN', 'PRESSEA', 'BAR24C'],
        "precip-cols-group": ['PRECIND', 'PRECIP', 'PREC24H', 'PRECDUR'],
        "sky-cols-group": ['STSKY', 'PRSWX', 'W1', 'W2'],
        "cloud-cols-group": ['Nh', 'CLDTOT', 'LOWCLHFt', 'CL', 'CM', 'CH', 
                            'DL', 'DM', 'DH', 'N1', 'C1', 'hhFt1', 'N2', 'C2', 
                            'hhFt2', 'N3', 'C3', 'hhFt3', 'N4', 'C4', 'hhFt4'],
    }

    # Get wmo code values to use in dropdown for code variables
    wmocodevalue_list = WMOCodeValue.objects.values('value', 'code_table_id')
    wmocodevalue_dict = {}
    for item in wmocodevalue_list:
        code_table_id = item['code_table_id']

        if code_table_id not in wmocodevalue_dict:
            wmocodevalue_dict[code_table_id] = []

        wmocodevalue_dict[code_table_id].append(item['value'])

    # Reverse mapping from symbol to class name
    symbol_to_class = {}
    for class_name, symbols in var_class_dict.items():
        for symbol in symbols:
            symbol_to_class[symbol] = class_name

    # var id's which should have a calculate action (24 hr barometric change, 24 hr precipitation)
    calc_action = [4055, 4057]

    # Get a variable list using the order of variable_ids list and also check for symbols which are missing of don't exist
    variable_dict = {variable.symbol: variable for variable in Variable.objects.filter(symbol__in=variable_symbols)}
    if missing_symbols := [
        symbol for symbol in variable_symbols if symbol not in variable_dict
    ]:
        raise ValueError(f"Unable to Load the synop capture form. The following variable symbols are missing in the database: {missing_symbols}")
    
    variable_list = [variable_dict[variable_symbol] for variable_symbol in variable_symbols]

    # loadig the context with the required information to display the headers (id, name, synoptic_code, col_width)
    context = [
        {
            "id": var.pk, 
            "name": var.name, 
            "synoptic_code": var.synoptic_code_form, 
            "var_type": var.variable_type.lower(),
            "col_width": col_widths[variable_list.index(var)],
            "col_class": symbol_to_class.get(var.symbol),
            "dropdown_codes": wmocodevalue_dict.get(var.code_table_id, []),
            "calc_action": True if var.pk in calc_action else False,
        } 
        for var in variable_list
        
    ]
    context.extend(
        (
            {
                "id": "remarks",
                "name": "Remarks",
                "synoptic_code": None,
                "col_width": 200,
                "col_class": "misc-cols-group",
            },
            {
                "id": "observer",
                "name": "Observer",
                "synoptic_code": None,
                "col_width": 250,
                "col_class": "misc-cols-group",
            },
        )
    )

    # get the id's of all variables which columns are numeric, the id's are stored as strings
    num_validate_ids = [str(var.pk) for var in variable_list if var.variable_type.lower() == "numeric"]
    # getting the id's of all variables
    variable_ids = [str(var.pk) for var in variable_list]

    return context, num_validate_ids, variable_ids


# recieve the coloumns which are empty and removes their entry from the database
# similar to synop delete, except this handles multiple hours
@api_view(['POST'])
@wx_mapped_permission_required
def synop_capture_update_empty_col(request):
    # Extract data from the request
    request_date_str = request.GET.get('date')
    station_id = request.GET.get('station_id')
    empty_cols_data = request.data.get('empty_cols_data')

    # Basic validation
    if not request_date_str or not station_id or empty_cols_data is None:
        message = "Invalid request. 'date', 'station_id', and 'empty_cols_data' must be provided."
        return JsonResponse({"message": message}, status=status.HTTP_400_BAD_REQUEST)

    if not isinstance(empty_cols_data, dict):
        message = "Invalid request. 'empty_cols_data' must be an object keyed by hour."
        return JsonResponse({"message": message}, status=status.HTTP_400_BAD_REQUEST)

    # Validate date format once
    try:
        request_date = datetime.datetime.strptime(request_date_str, '%Y-%m-%d')
    except ValueError:
        message = "Invalid date format. The expected date format is 'YYYY-MM-DD'"
        return JsonResponse({"message": message}, status=status.HTTP_400_BAD_REQUEST)

    # Fetch station once
    try:
        station = Station.objects.get(id=station_id)
    except Station.DoesNotExist:
        return JsonResponse(
            {"message": "Station not found"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    datetime_offset = pytz.FixedOffset(station.utc_offset_minutes)

    queries = {
        "grab_relevant_chunks": """
            SELECT 
            show_chunks('raw_data', newer_than => %s, older_than => %s)
        """,
        "delete_raw_data": """
            DELETE FROM {raw_data_chunk}
            WHERE station_id = %s
            AND variable_id = ANY(%s)
            AND datetime = %s
        """,
        "create_daily_summary": """
            INSERT INTO wx_dailysummarytask (station_id, date, created_at, updated_at)
            VALUES (%s, %s, now(), now())
            ON CONFLICT DO NOTHING
        """,
        "create_hourly_summary": """
            INSERT INTO wx_hourlysummarytask (station_id, datetime, created_at, updated_at)
            VALUES (%s, %s, now(), now())
            ON CONFLICT DO NOTHING
        """,
        "get_last_updated": """
            SELECT max(last_data_datetime)
            FROM wx_stationvariable
            WHERE station_id = %s
              AND variable_id = ANY(%s)
            ORDER BY 1 DESC
        """,
        "update_last_updated": """
            WITH rd AS (
                SELECT station_id, variable_id, measured, code, datetime,
                       RANK() OVER (PARTITION BY station_id, variable_id ORDER BY datetime DESC) AS datetime_rank
                FROM {raw_data_chunk}
                WHERE station_id = %s
                  AND variable_id = ANY(%s)
            )
            UPDATE wx_stationvariable sv
            SET last_data_datetime = rd.datetime,
                last_data_value = rd.measured,
                last_data_code = rd.code
            FROM rd
            WHERE sv.station_id = rd.station_id
              AND sv.variable_id = rd.variable_id
              AND rd.datetime_rank = 1
        """
    }

    with psycopg2.connect(settings.SURFACE_CONNECTION_STRING) as conn:
        with conn.cursor() as cursor:
            for col_data_key, variable_id_list in empty_cols_data.items():
                # Validate hour
                try:
                    hour = int(col_data_key)
                except (TypeError, ValueError):
                    return JsonResponse(
                        {"message": f"Invalid hour value: {col_data_key}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if hour < 0 or hour > 23:
                    return JsonResponse(
                        {"message": f"Hour must be between 0 and 23. Received: {hour}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Validate variable list
                if variable_id_list is None:
                    return JsonResponse(
                        {"message": f"Invalid request. variable_ids must be provided for hour {hour}."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if not isinstance(variable_id_list, (list, tuple)):
                    return JsonResponse(
                        {"message": f"Invalid request. variable_ids for hour {hour} must be a list."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Nothing to delete for this hour
                if not variable_id_list:
                    continue

                try:
                    variable_id_list = [int(v) for v in variable_id_list]
                except (TypeError, ValueError):
                    return JsonResponse(
                        {"message": f"Invalid variable_ids for hour {hour}. All variable IDs must be integers."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                request_datetime = datetime_offset.localize(
                    request_date.replace(hour=hour)
                )
                request_start_range_dt = request_datetime - timedelta(days=10)
                request_end_range_dt = request_datetime + timedelta(days=10)

                # Grab relevant chunks, holding data within 10 days of the request datetime
                # This reduces the overhead of looking through the entire raw_data table.
                cursor.execute(
                    queries["grab_relevant_chunks"],
                    [request_start_range_dt, request_end_range_dt]
                )
                chunks = [row[0] for row in cursor.fetchall()]

                # Delete matching raw_data rows from relevant chunks
                for chunk in chunks:
                    cursor.execute(
                        queries["delete_raw_data"].format(raw_data_chunk=chunk),
                        [station_id, variable_id_list, request_datetime]
                    )

                # After deleting from raw_data, it is necessary to update the daily and hourly summary tables.
                cursor.execute(
                    queries["create_daily_summary"],
                    [station_id, request_datetime]
                )
                cursor.execute(
                    queries["create_hourly_summary"],
                    [station_id, request_datetime]
                )

                # If the deleted datetime was the last_data_datetime for any of these variables,
                # update the last_data_* fields from the remaining raw_data.
                cursor.execute(
                    queries["get_last_updated"],
                    [station_id, variable_id_list]
                )
                last_data_datetime_row = cursor.fetchone()

                if last_data_datetime_row and last_data_datetime_row[0] == request_datetime:
                    for chunk in chunks:
                        cursor.execute(
                            queries["update_last_updated"].format(raw_data_chunk=chunk),
                            [station_id, variable_id_list]
                        )

        conn.commit()

    return Response([], status=status.HTTP_200_OK)



def get_static_assets_dir():
    """
    Determine the static folder to use for reading/writing files.
    Priority:
      1. settings.STATIC_ROOT (when set, eg. production after collectstatic)
      2. first entry of settings.STATICFILES_DIRS (if any)
      3. <BASE_DIR>/static (sane project-level default)
    """
    if getattr(settings, "STATIC_ROOT", None):
        return settings.STATIC_ROOT
    
    sfd = getattr(settings, "STATICFILES_DIRS", None)

    if sfd:
        # pick first entry if it's a string
        if isinstance(sfd, (list, tuple)) and sfd:
            return sfd[0]
        if isinstance(sfd, str):
            return sfd
    # fallback to project static folder
    return os.path.join(settings.BASE_DIR, "static")



# Mapping keys -> file names in the static folder (whitelist) - ORG LOGO
ORGANIZATION_LOGO_FILES = {
    "organization_logo": "images/org_logo.png",
}

ALLOWED_LOGO_EXTENSIONS = {".png"}

MAX_LOGO_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


@method_decorator(wx_mapped_permission_required, name="dispatch")
@method_decorator(require_http_methods(["POST"]), name="dispatch")
class UploadOrDeleteOrganizationLogoView(View):
    """
    Handles POST requests for uploading or deleting the whitelisted organization logo.
    Expected POST fields:
      - action: 'upload' or 'delete'
      - key: must be 'organization_logo'
      - file: (for upload) the uploaded file in request.FILES['file']
    """

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        key = request.POST.get("key")

        if action not in ("upload", "delete") or key not in ORGANIZATION_LOGO_FILES:
            return HttpResponseBadRequest("Invalid action or key")

        static_dir = get_static_assets_dir()
        target_filename = ORGANIZATION_LOGO_FILES[key]
        target_path = os.path.join(static_dir, target_filename)

        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        if action == "upload":
            uploaded = request.FILES.get("file")
            if not uploaded:
                return JsonResponse(
                    {"success": False, "message": "No file provided."},
                    status=400,
                )

            # Validate file size
            if uploaded.size > MAX_LOGO_SIZE_BYTES:
                return JsonResponse(
                    {
                        "success": False,
                        "message": "File exceeds the 15 MB size limit.",
                    },
                    status=400,
                )

            # Validate uploaded extension
            _, uploaded_ext = os.path.splitext(uploaded.name)
            if uploaded_ext.lower() not in ALLOWED_LOGO_EXTENSIONS:
                return JsonResponse(
                    {
                        "success": False,
                        "message": "Disallowed file extension. Only PNG is allowed.",
                    },
                    status=400,
                )

            # Validate target extension too, for safety/consistency
            _, target_ext = os.path.splitext(target_filename)
            if target_ext.lower() not in ALLOWED_LOGO_EXTENSIONS:
                return JsonResponse(
                    {
                        "success": False,
                        "message": "Configured target file extension is not allowed.",
                    },
                    status=500,
                )

            try:
                if os.path.exists(target_path):
                    try:
                        os.remove(target_path)
                    except Exception:
                        pass

                with open(target_path, "wb") as dest:
                    for chunk in uploaded.chunks():
                        dest.write(chunk)

                ts = os.path.getmtime(target_path)
                dt = datetime_constructor.fromtimestamp(ts, timezone.utc) + timedelta(
                    minutes=settings.TIMEZONE_OFFSET
                )
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")

                return JsonResponse(
                    {
                        "success": True,
                        "filename": os.path.basename(target_filename),
                        "uploadDate": formatted_time,
                        "key": key,
                    }
                )
            except Exception as exc:
                return JsonResponse(
                    {"success": False, "message": str(exc)},
                    status=500,
                )

        # action == delete
        try:
            if os.path.exists(target_path) and os.path.isfile(target_path):
                os.remove(target_path)

            return JsonResponse({"success": True})
        except Exception as exc:
            return JsonResponse(
                {"success": False, "message": str(exc)},
                status=500,
            )


@method_decorator(wx_mapped_permission_required, name="dispatch")
@method_decorator(require_http_methods(["GET"]), name="dispatch")
class DownloadOrganizationLogoView(View):
    """
    Streams the whitelisted organization logo back to the client for download.
    URL expected to pass 'key' as a path parameter.
    """

    def get(self, request, key, *args, **kwargs):
        if key not in ORGANIZATION_LOGO_FILES:
            raise Http404("Invalid key")

        static_dir = get_static_assets_dir()
        filename = ORGANIZATION_LOGO_FILES[key]
        path = os.path.join(static_dir, filename)

        if not os.path.exists(path) or not os.path.isfile(path):
            raise Http404("File not found")

        response = FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(filename))
        response["Last-Modified"] = http_date(os.path.getmtime(path))
        return response


@method_decorator(wx_mapped_permission_required, name="dispatch")
@method_decorator(require_http_methods(["GET"]), name="dispatch")
class OrganizationLogoDetailsView(View):
    """
    Returns metadata about the current organization logo.
    """

    def get(self, request, *args, **kwargs):
        key = "organization_logo"

        static_dir = get_static_assets_dir()
        target_filename = ORGANIZATION_LOGO_FILES[key]
        target_path = os.path.join(static_dir, target_filename)

        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            return JsonResponse(
                {
                    "hasFile": False,
                    "filename": "",
                    "uploadDate": "",
                    "previewUrl": "",
                    "key": key,
                }
            )

        ts = os.path.getmtime(target_path)
        dt = datetime_constructor.fromtimestamp(ts, timezone.utc) + timedelta(
            minutes=settings.TIMEZONE_OFFSET
        )
        formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")

        return JsonResponse(
            {
                "hasFile": True,
                "filename": os.path.basename(target_filename),
                "uploadDate": formatted_time,
                "previewUrl": f"{settings.STATIC_URL}{target_filename}?v={int(ts)}",
                "key": key,
            }
        )



# Mapping keys -> file names in the static folder (whitelist) - SPATIAL
SPATIAL_SHAPE_FILES = {
    "shape": "shape.png",
    "watersheds": "Watersheds.geojson",
    "national": "NationalWaters.geojson",
    "gwp": "GWP_Campur.geojson",
    "basemap": "Basemap.geojson",
}

# Allowed extensions for each target file (basic safety)
ALLOWED_EXTENSIONS = {".png", ".geojson"}


def stat_file_info(path):
    """Return dict with existence and mtime string for template use"""
    if os.path.exists(path) and os.path.isfile(path):
        ts = os.path.getmtime(path)
        dt = datetime_constructor.fromtimestamp(ts, timezone.utc) + timedelta(minutes=settings.TIMEZONE_OFFSET)
        formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")

        mtime = formatted_time
        return {"exists": True, "mtime": mtime}
    return {"exists": False, "mtime": None}


@method_decorator(require_http_methods(["GET"]), name="dispatch")
class ConfigurationSettingsView(WxPermissionRequiredMixin, LoginRequiredMixin,  TemplateView):

    template_name = "wx/configuration_settings.html"

    def get_context_data(self, **kwargs):
        static_dir = get_static_assets_dir()
        options = []
        labels = {
            "shape": "Shape (image)",
            "watersheds": "Watersheds",
            "national": "National Waters",
            "gwp": "GWP - Campur",
            "basemap": "Basemap",
        }

        for key, filename in SPATIAL_SHAPE_FILES.items():
            file_path = os.path.join(static_dir, filename)
            info = stat_file_info(file_path)
            # build a relative download URL that the Vue client can use
            download_url = f"/documents/spatial/files/download/{key}/"
            options.append(
                {
                    "key": key,
                    "label": labels.get(key, filename),
                    "description": filename,
                    "hasFile": info["exists"],
                    "filename": filename if info["exists"] else None,
                    "uploadDate": info["mtime"],
                    "downloadUrl": download_url,
                }
            )

        ctx = super().get_context_data(**kwargs)
        ctx["options_json"] = json.dumps(options)
        return ctx


@method_decorator(require_http_methods(["GET"]), name="dispatch")
class ManagePermissionsView(WxPermissionRequiredMixin, LoginRequiredMixin,  TemplateView):
    template_name = "wx/manage_permissions.html"
    

@method_decorator(wx_mapped_permission_required, name="dispatch")
@method_decorator(require_http_methods(["POST"]), name="dispatch")
class UploadOrDeleteSpatialFilesView(View):
    """
    Handles POST requests for uploading or deleting a whitelisted static file.
    Expected POST fields:
      - action: 'upload' or 'delete'
      - key: one of FILES keys
      - file: (for upload) the uploaded file in request.FILES['file']
    """

    # # This is the only “permission” string you need to supply:
    # permission_required = "Configuration Settings - Full Access"

    # # If you want a custom 403 page instead of redirecting to login again, explicitly set:
    # raise_exception = True

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        key = request.POST.get("key")
        if action not in ("upload", "delete") or key not in SPATIAL_SHAPE_FILES:
            return HttpResponseBadRequest("Invalid action or key")

        static_dir = get_static_assets_dir()
        target_filename = SPATIAL_SHAPE_FILES[key]
        target_path = os.path.join(static_dir, target_filename)

        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        if action == "upload":
            uploaded = request.FILES.get("file")
            if not uploaded:
                return JsonResponse({"success": False, "message": "No file provided."}, status=400)

            # Basic safety: ensure the target filename's extension is allowed
            _, ext = os.path.splitext(target_filename)
            if ext.lower() not in ALLOWED_EXTENSIONS:
                return JsonResponse({"success": False, "message": "Disallowed file extension."}, status=400)

            try:
                # Remove previous file if exists
                if os.path.exists(target_path):
                    try:
                        os.remove(target_path)
                    except Exception:
                        # ignore removal errors and continue to overwrite
                        pass

                # Save new file content
                with open(target_path, "wb") as dest:
                    for chunk in uploaded.chunks():
                        dest.write(chunk)

                ts = os.path.getmtime(target_path)
                dt = datetime_constructor.fromtimestamp(ts, timezone.utc) + timedelta(minutes=settings.TIMEZONE_OFFSET)
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")

                mtime = formatted_time

                return JsonResponse({"success": True, "filename": target_filename, "uploadDate": mtime})
            except Exception as exc:
                return JsonResponse({"success": False, "message": str(exc)}, status=500)

        # action == delete
        try:
            if os.path.exists(target_path) and os.path.isfile(target_path):
                os.remove(target_path)
            return JsonResponse({"success": True})
        except Exception as exc:
            return JsonResponse({"success": False, "message": str(exc)}, status=500)


@method_decorator(wx_mapped_permission_required, name="dispatch")
@method_decorator(require_http_methods(["GET"]), name="dispatch")
class DownloadSpatialFilesView(View):
    """
    Streams a whitelisted static file back to the client for download.
    URL expected to pass 'key' as a path parameter.
    """

    # # This is the only “permission” string you need to supply:
    # permission_required = "Configuration Settings - Full Access"

    # # If you want a custom 403 page instead of redirecting to login again, explicitly set:
    # raise_exception = True

    def get(self, request, key, *args, **kwargs):
        if key not in SPATIAL_SHAPE_FILES:
            raise Http404("Invalid key")

        static_dir = get_static_assets_dir()
        filename = SPATIAL_SHAPE_FILES[key]
        path = os.path.join(static_dir, filename)
        if not os.path.exists(path) or not os.path.isfile(path):
            raise Http404("File not found")

        response = FileResponse(open(path, "rb"), as_attachment=True, filename=filename)
        response["Last-Modified"] = http_date(os.path.getmtime(path))
        return response


def calculate_agromet_summary_df_statistics(df: pd.DataFrame) -> list:
    """
    Calculates summary statistics (min, max, average, and standard deviation) for numeric columns
    in the input DataFrame, grouped by 'station' and 'variable_id'. The results are appended to
    the original DataFrame as new rows.

    Args:
        df (pd.DataFrame): Input DataFrame containing the following columns:
                           - 'station': Identifier for the station.
                           - 'variable_id': Identifier for the variable.
                           - 'month': Month of the observation (optional).
                           - 'year': Year of the observation.
                           - Other columns: Numeric variables (e.g., temperature, humidity).

    Returns:
        list: A list of dictionaries, where each dictionary represents a row in the resulting DataFrame.
              The rows include the original data as well as new rows for the calculated statistics.
              Each dictionary has keys corresponding to the DataFrame columns, with additional rows
              for 'MIN', 'MAX', 'AVG', and 'STD' values. The calculated statistics symbols are present in the 'year' column. 
    """

    index = ['station', 'variable_id', 'month', 'year']
    agg_cols = [col for col in df.columns if (col not in index) and not col.endswith("(% of days)")]
    grouped = df.groupby(['station', 'variable_id'])
    
    def calculate_stats(group):
        min_values = group[agg_cols].min()
        max_values = group[agg_cols].max()
        avg_values = group[agg_cols].mean().round(1)
        std_values = group[agg_cols].std().round(1)
        sum_values = group[agg_cols].sum().round(1)

        stats_dict = {}
        for col in agg_cols:
            stats_dict[col] = [min_values[col], max_values[col], avg_values[col], std_values[col], sum_values[col]]
        
        # Add metadata for the new rows
        stats_dict['station'] = group.name[0]  # Station name from the group key
        stats_dict['variable_id'] = group.name[1]  # Variable ID from the group key
        stats_dict['year'] = ['MIN', 'MAX', 'AVG', 'STD', 'SUM']  # Labels for the new rows
        
        new_rows = pd.DataFrame(stats_dict)
        
        # Append the new rows to the original group
        return pd.concat([group, new_rows], ignore_index=True)
    
    # Apply the helper function to each group and combine the results
    result_df = grouped.apply(calculate_stats).reset_index(drop=True)
    result_df = result_df.fillna('')
    data = result_df.to_dict(orient='records')

    return data


def get_agromet_summary_df_min_max(df: pd.DataFrame) -> dict:
    """
    Generates a summary dictionary containing the minimum and maximum values for each variable
    at each station, along with the corresponding time periods (month/year or year).

    Args:
        df (pd.DataFrame): Input DataFrame containing the following columns:
                            - 'station': Identifier for the station.
                            - 'variable_id': Identifier for the variable.
                            - 'month' (optional): Month of the observation.
                            - 'year': Year of the observation.
                            - Other columns: Numeric variables (e.g., temperature, humidity).

    Returns:
        dict: A nested dictionary with the following structure:
              {
                  "station_1": {
                      "variable_id_1": {
                          "variable_name_1": {
                              "min": [{"month": X, "year": Y}, ...],  # Records for min value
                              "max": [{"month": X, "year": Y}, ...]   # Records for max value
                          },
                          ...
                      },
                      ...
                  },
                  ...
              }
              If 'month' is not present in the input DataFrame, the "month" key is omitted.
    """

    index = ['month', 'year'] if 'month' in df.columns else ['year']
    grouped = df.groupby(['station', 'variable_id'] + index)
    agg_df = grouped.agg(['min', 'max']).reset_index()
    # Flatten the MultiIndex columns
    agg_df.columns = [f"{col[0]}_{col[1]}" if col[1] else col[0] for col in agg_df.columns]
    
    # Initialize the result dictionary
    minMaxDict = {}
    for (station, variable_id), group in agg_df.groupby(['station', 'variable_id']):
        station = str(station)
        variable_id = str(variable_id)
        
        if station not in minMaxDict:
            minMaxDict[station] = {}
        if variable_id not in minMaxDict[station]:
            minMaxDict[station][variable_id] = {}
        
        # Iterate over each column (excluding index columns)
        for col in df.columns:
            if col not in ['station', 'variable_id'] + index:
                col_min = group[f"{col}_min"].min()
                col_max = group[f"{col}_max"].max()
                
                # Find records corresponding to min and max values
                min_records = group[group[f"{col}_min"] == col_min][index].to_dict('records')
                max_records = group[group[f"{col}_max"] == col_max][index].to_dict('records')
                
                # Convert numpy types to native Python types
                def convert_types(records):
                    for record in records:
                        for key, value in record.items():
                            if isinstance(value, (np.integer, np.floating)):
                                record[key] = int(value) if isinstance(value, np.integer) else float(value)
                    return records
                
                min_records = convert_types(min_records)
                max_records = convert_types(max_records)
                
                minMaxDict[station][variable_id][str(col)] = {'min': min_records, 'max': max_records}
    
    return minMaxDict


@api_view(['GET'])
@wx_mapped_permission_required
def get_agromet_summary_data(request):
    try:
        requestedData = {
            'start_year': request.GET.get('start_year'), #
            'end_year': request.GET.get('end_year'), #
            'station_id': request.GET.get('station_id'), #
            'variable_ids': request.GET.get('variable_ids'), #
            'is_daily_data': request.GET.get('is_daily_data'),
            'summary_type': request.GET.get('summary_type'),
            'months': request.GET.get('months'),
            'month': request.GET.get('month'),
            'interval': request.GET.get('interval'),
            'validate_data': request.GET.get('validate_data').lower() == 'true',
            'max_hour_pct': request.GET.get('max_hour_pct'),
            'max_day_pct': request.GET.get('max_day_pct'),
            'max_day_gap': request.GET.get('max_day_gap'),
        }
    except ValueError as e:
        logger.error(repr(e))
        return HttpResponse(status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(repr(e))
        return HttpResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if requestedData['summary_type']=='Seasonal':
        # To calculate the seasonal summary, values from January of the next year and December of the previous year are required.
        requestedData['start_date'] = f"{int(requestedData['start_year'])-1}-12-01"
        requestedData['end_date'] = f"{int(requestedData['end_year'])+1}-02-01"
    elif requestedData['summary_type']=='Monthly':
        requestedData['start_date'] = f"{int(requestedData['start_year'])}-01-01"
        requestedData['end_date'] = f"{int(requestedData['end_year'])+1}-01-01"

    timezone = pytz.timezone(settings.TIMEZONE_NAME)
    context = {
        'station_id': requestedData['station_id'],
        'variable_ids': requestedData['variable_ids'],
        'timezone': timezone,
        'start_date': requestedData['start_date'],
        'end_date': requestedData['end_date'],
        'start_year': requestedData['start_year'],
        'end_year': requestedData['end_year'],
        'months': requestedData['months'],
        'month': requestedData['month'],
        'max_hour_pct': float(requestedData['max_hour_pct']),
        'max_day_pct': float(requestedData['max_day_pct']),
        'max_day_gap': float(requestedData['max_day_gap'])

    }
    env = Environment(loader=FileSystemLoader('/surface/wx/sql/agromet/agromet_summaries'))

    pgia_code = '8858307' # Phillip Goldson Int'l Synop
    station = Station.objects.get(pk=requestedData['station_id'])
    is_hourly_summary = station.is_automatic or station.code == pgia_code

    if requestedData['is_daily_data'] == 'true':
        if requestedData['summary_type'] == 'Seasonal':
            template_name = 'seasonal_daily_valid.sql' if requestedData['validate_data'] else 'seasonal_daily_raw.sql'
        elif requestedData['summary_type'] == 'Monthly':
            if requestedData['interval'] == '7 days':
                template_name = 'monthly_7d_daily_valid.sql' if requestedData['validate_data'] else 'monthly_7d_daily_raw.sql'
            elif requestedData['interval'] == '10 days':
                template_name = 'monthly_10d_daily_valid.sql' if requestedData['validate_data'] else 'monthly_10d_daily_raw.sql'            
            elif requestedData['interval'] == '1 month':
                template_name = 'monthly_1m_daily_valid.sql' if requestedData['validate_data'] else 'monthly_1m_daily_raw.sql'            
            elif requestedData['interval'] == '3 months':
                template_name = 'monthly_3m_daily_valid.sql' if requestedData['validate_data'] else 'monthly_3m_daily_raw.sql'
            elif requestedData['interval'] == '6 months':
                template_name = 'monthly_6m_daily_valid.sql' if requestedData['validate_data'] else 'monthly_6m_daily_raw.sql'                
    else:
        if requestedData['summary_type'] == 'Seasonal':
            template_name = 'seasonal_hourly_valid.sql' if requestedData['validate_data'] else 'seasonal_hourly_raw.sql'
        elif requestedData['summary_type'] == 'Monthly':
            if requestedData['interval'] == '7 days':
                template_name = 'monthly_7d_hourly_valid.sql' if requestedData['validate_data'] else 'monthly_7d_hourly_raw.sql'
            elif requestedData['interval'] == '10 days':
                template_name = 'monthly_10d_hourly_valid.sql' if requestedData['validate_data'] else 'monthly_10d_hourly_raw.sql'            
            elif requestedData['interval'] == '1 month':
                template_name = 'monthly_1m_hourly_valid.sql' if requestedData['validate_data'] else 'monthly_1m_hourly_raw.sql'
            elif requestedData['interval'] == '3 months':
                template_name = 'monthly_3m_hourly_valid.sql' if requestedData['validate_data'] else 'monthly_3m_hourly_raw.sql'
            elif requestedData['interval'] == '6 months':
                template_name = 'monthly_6m_hourly_valid.sql' if requestedData['validate_data'] else 'monthly_6m_hourly_raw.sql'                
    template = env.get_template(template_name)
    query = template.render(context)

    config = settings.SURFACE_CONNECTION_STRING
    with psycopg2.connect(config) as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        response = []
        return JsonResponse(response, status=status.HTTP_200_OK, safe=False)

    response = {
        'tableData': calculate_agromet_summary_df_statistics(df),
        'minMaxData': get_agromet_summary_df_min_max(df)
    }

    return JsonResponse(response, status=status.HTTP_200_OK, safe=False)


class AgroMetSummariesView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/agromet/agromet_summaries.html"

    agromet_variable_symbols = [
        'TEMP',
        'TEMPAVG',
        'TEMPMAX',
        'TEMPMIN',
        'EVAPPAN',
        'PRECIP',
        'RH',
        'RHAVG',
        'RHMAX',
        'RHMIN',
        'TSOIL1',
        'TSOIL4',
        'SOLARRAD',
        'SUNSHNHR',
        'WNDDIR',
        'WNDSPD',
        'WNDSPAVG',
        'WNDSPMAX',
        'WNDSPMIN'
    ]  

    agromet_variable_ids = Variable.objects.filter(symbol__in=agromet_variable_symbols).values_list('id', flat=True)
              
    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        context['username'] = f'{request.user.first_name} {request.user.last_name}' if request.user.first_name and request.user.last_name else request.user.username

        context['station_id'] = request.GET.get('station_id', 'null')
        context['variable_ids'] = request.GET.get('variable_ids', 'null')

        station_variables = StationVariable.objects.filter(variable_id__in=self.agromet_variable_ids).values('id', 'station_id', 'variable_id')
        station_ids = station_variables.values_list('station_id', flat=True).distinct()

        context['oldest_year'] = 1900
        context['stationvariable_list'] = list(station_variables)
        context['variable_list'] = list(Variable.objects.filter(symbol__in=self.agromet_variable_symbols).values('id', 'name', 'symbol'))
        context['station_list'] = list(Station.objects.filter(id__in=station_ids, is_active=True).values('id', 'name', 'code', 'is_automatic', 'latitude', 'longitude'))

        return self.render_to_response(context)


def calculate_agromet_products_df_statistics(df: pd.DataFrame) -> list:
    """
    Calculates summary statistics (min, max, average, and standard deviation) for numeric columns
    in the input DataFrame, grouped by 'station' and 'variable_id'. The results are appended to
    the original DataFrame as new rows.

    Args:
        df (pd.DataFrame): Input DataFrame containing the following columns:
                           - 'station': Identifier for the station.
                           - 'month': Month of the observation (optional).
                           - 'year': Year of the observation.
                           - Other columns: Numeric variables (e.g., temperature, humidity).

    Returns:
        list: A list of dictionaries, where each dictionary represents a row in the resulting DataFrame.
              The rows include the original data as well as new rows for the calculated statistics.
              Each dictionary has keys corresponding to the DataFrame columns, with additional rows
              for 'MIN', 'MAX', 'AVG', and 'STD' values. The calculated statistics symbols are present in the 'year' column. 
    """

    index = ['station', 'product', 'month', 'year']
    agg_cols = [col for col in df.columns if (col not in index) and not col.endswith("(% of days)")]
    # df[agg_cols] = df[agg_cols].apply(pd.to_numeric, errors='coerce')
    # print(agg_cols)
    # agg_cols = df[agg_cols].select_dtypes(include=['number']).columns.tolist()
    # print(agg_cols)

    grouped = df.groupby(['station', 'product'])
    
    def calculate_stats(group):
        # Convert columns to numeric once and calculate the statistics
        numeric_group = group[agg_cols].apply(pd.to_numeric, errors='coerce')

        min_values = numeric_group.min()
        max_values = numeric_group.max()
        avg_values = numeric_group.mean().round(1)
        std_values = numeric_group.std().round(1)
        sum_values = numeric_group.sum().round(1)

        stats_dict = {}
        for col in agg_cols:
            stats_dict[col] = [min_values[col], max_values[col], avg_values[col], std_values[col], sum_values[col]]
        
        # Add metadata for the new rows
        stats_dict['station'] = group.name[0]  # Station name from the group key
        stats_dict['product'] = group.name[1]  # Variable symbol from the group key
        stats_dict['year'] = ['MIN', 'MAX', 'AVG', 'STD', 'SUM']  # Labels for the new rows
        
        
        new_rows = pd.DataFrame(stats_dict)
        
        # Append the new rows to the original group
        return pd.concat([group, new_rows], ignore_index=True)
    
    # Apply the helper function to each group and combine the results
    result_df = grouped.apply(calculate_stats).reset_index(drop=True)
    result_df = result_df.fillna('')
    data = result_df.to_dict(orient='records')

    return data


def get_agromet_products_df_min_max(df: pd.DataFrame) -> dict:
    """
    Generates a summary dictionary containing the minimum and maximum values for each variable
    at each station, along with the corresponding time periods (month/year or year).

    Args:
        df (pd.DataFrame): Input DataFrame containing the following columns:
                            - 'station': Identifier for the station.
                            - 'month' (optional): Month of the observation.
                            - 'year': Year of the observation.
                            - Other columns: Numeric variables (e.g., temperature, humidity).

    Returns:
        dict: A nested dictionary with the following structure:
              {
                  "station_1": {
                      "variable_id_1": {
                          "variable_name_1": {
                              "min": [{month: X, year: Y}, ...],  # Records for min value
                              "max": [{month: X, year: Y}, ...]   # Records for max value
                          },
                          ...
                      },
                      ...
                  },
                  ...
              }
              If 'month' is not present in the input DataFrame, the "month" key is omitted.
    """

    index = ['month', 'year'] if 'month' in df.columns else ['year']
    grouped = df.groupby(['station', 'product'] + index)
    agg_df = grouped.agg(['min', 'max']).reset_index()
    # Flatten the MultiIndex columns
    agg_df.columns = [f"{col[0]}_{col[1]}" if col[1] else col[0] for col in agg_df.columns]
    
    # Initialize the result dictionary
    minMaxDict = {}
    for (station, product), group in agg_df.groupby(['station', 'product']):
        station = str(station)
        product = str(product)
        
        if station not in minMaxDict: 
            minMaxDict[station] = {}
        if product not in minMaxDict[station]: 
            minMaxDict[station][product] = {}
        
        # Iterate over each column (excluding index columns)
        for col in df.columns:
            if col not in ['station', 'product'] + index:
                col_min = group[f"{col}_min"].min()
                col_max = group[f"{col}_max"].max()
                
                # Find records corresponding to min and max values
                min_records = group[group[f"{col}_min"] == col_min][index].to_dict('records')
                max_records = group[group[f"{col}_max"] == col_max][index].to_dict('records')
                
                # Convert numpy types to native Python types
                def convert_types(records):
                    for record in records:
                        for key, value in record.items():
                            if isinstance(value, (np.integer, np.floating)):
                                record[key] = int(value) if isinstance(value, np.integer) else float(value)
                    return records
                
                min_records = convert_types(min_records)
                max_records = convert_types(max_records)
                
                minMaxDict[station][product][str(col)] = {'min': min_records, 'max': max_records}
    
    return minMaxDict


def get_agromet_products_sql_context(requestedData: dict, env: Environment) -> dict:
    pgia_code = '8858307' # Phillip Goldson Int'l Synop
    station = Station.objects.get(pk=requestedData['station_id'])

    is_hourly_station = station.is_automatic or station.code==pgia_code

    element = requestedData['element']
    product = requestedData['product']

    aggregation_months_dict = {
        'JFM': '1,2,3', 
        'FMA': '2,3,4', 
        'MAM': '3,4,5', 
        'AMJ': '4,5,6', 
        'MJJ': '5,6,7', 
        'JJA': '6,7,8', 
        'JAS': '7,8,9', 
        'ASO': '8,9,10', 
        'SON': '9,10,11', 
        'OND': '10,11,12', 
        'NDJ': '11,12,1', 
        'DRY': '0,1,2,3,4,5', 
        'WET': '6,7,8,9,10,11', 
        'ANNUAL': '1,2,3,4,5,6,7,8,9,10,11,12', 
        'DJFM': '0,1,2,3' 
    }

    station = Station.objects.get(pk=requestedData['station_id'])

    timezone = pytz.timezone(settings.TIMEZONE_NAME)
    context = {
        'station_id': requestedData['station_id'],
        'timezone': timezone,
        'start_date': requestedData['start_date'],
        'end_date': requestedData['end_date'],
        'start_year': requestedData['start_year'],
        'end_year': requestedData['end_year'],
        'months': requestedData['months'],
        'max_hour_pct': float(requestedData['max_hour_pct']),
        'max_day_pct': float(requestedData['max_day_pct']),
        'max_day_gap': float(requestedData['max_day_gap'])
    }

    if product == 'Heat wave':
        if is_hourly_station:
            prev_template = env.get_template('percentile_automatic.sql')
        else:
            prev_template = env.get_template('percentile_manual.sql')

        prev_context = {
            'station_id': requestedData['station_id'],
            'percentile': requestedData['numeric_param_1']
        }
        prev_query = prev_template.render(prev_context)

        config = settings.SURFACE_CONNECTION_STRING
        with psycopg2.connect(config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(prev_query)
                result = cursor.fetchone()
                context['threshold'] = result[0] if (result and result[0] is not None) else 0
    elif product == 'Wind rose':
        aggregation = requestedData['aggregation']
        if aggregation:
            context['aggregation_months'] = aggregation_months_dict[aggregation]
        else:
            context['months'] = requestedData['months']
    elif product == 'Evapotranspiration':
        latitude = station.latitude
        aggregation = requestedData['aggregation']
        # context['aggregation_months'] = aggregation_months_dict[aggregation]
        context['aggregation_months'] = requestedData['months']
        context['latitude'] = latitude
        context['alpha'] = 0.0023 # FAO56 default coeficient value
        context['beta'] = 0.5 # FAO56 default coeficient value

    context_mapping = {
        'Air Temperature': {
            'Growing Degree Days': {'base_temp': 'numeric_param_1'},
            'Number of days above and below specified temperature': {'threshold': 'numeric_param_1'},
            'Heat wave': {'heat_wave_window': 'numeric_param_2'},
            'Growing season statistics': {'base_temp': 'numeric_param_1'}
        },
        'Rainfall': {
            'Number of days with specified rainfall': {'threshold': 'numeric_param_1'}
        },
        'Wind': {   
            'Number of hours with wind speed below specified value': {'threshold': 'numeric_param_1'}
        },
        'Relative Humidity': {
            'Sequence of days above specified humidity': {'threshold': 'numeric_param_1'},
            'Sequence of hours above specified humidity': {'threshold': 'numeric_param_1'}
        },
        'Soil Temperature': {
            'First and Last dates above specified specified temperature': {'threshold': 'numeric_param_1'}
        },  
        'Soil Moisture': {
            'Leaf area index': {'base_temp': 'numeric_param_1'}
        }
    }

    if element in context_mapping.keys():
        if product in context_mapping[element].keys():
            append_context = context_mapping[element][product]
            for key in append_context.keys():
                context[key] = requestedData[append_context[key]]

    return context


def get_agromet_products_sql_env(requestedData: dict):
    products_dir = {
        'Air Temperature': {
            'Growing Degree Days': 'air_temp/growing_degree_days',
            'Maximum and minimum statistics': 'air_temp/max_min_stats',
            'Number of days above and below specified temperature': 'air_temp/threshold_days_temp',
            'Growing season statistics': 'air_temp/growing_season_stats',
            'Heat wave': 'air_temp/heat_wave',
        },
        'Rainfall': {
            'Number of days with specified rainfall': 'rainfall/threshold_days_rain',
            'Drought indices': 'rainfall/drought_indices',
            'Flood and excess rainfall': 'rainfall/flood_and_excess_rain',
        },
        'Wind': {
            'Wind rose': 'wind/wind_rose',
            'Maximum and average wind speed': 'wind/max_avg_wind_speed',
            'Diurnal variation of wind speed': 'wind/diurnal_var_wind_speed',
            'Number of hours with wind speed below specified value': 'wind/threshold_hours_wind_speed',
        },
        'Radiation and Sunshine': {
            'Net radiation': 'radiation/net_radiation',
            'Solar radiation': 'radiation/solar_radiation',
            'Sunshine hours': 'radiation/sunshine_hours',
        },
        'Relative Humidity': {
            'Sequence of days above specified humidity': 'relative_humidity/seq_threshold_days',
            'Sequence of hours above specified humidity': 'relative_humidity/seq_threshold_hours',
        },
        'Evaporation and Evapotranspiration': {
            'Accumulative Evaporation': 'evaporation/sum_evapo',
            'Diurnal variation of evaporation': 'evaporation/diurnal_var_evapo',
            'Evapotranspiration': 'evaporation/evapotranspiration',
        },
        'Soil Temperature': {
            'Mean and standard deviation soil temperature': 'soil_temp/mean_stdv_soil_temp',
            'First and Last dates above specified specified temperature': 'soil_temp/threshold_dates_soil_temp',
        },
        'Soil Moisture': {
            'Soil Moisture at regular depths': 'soil_moisture/soil_moisture',
            'Leaf area index': 'soil_moisture/leaf_area_index',
        },
    }

    base_path = '/surface/wx/sql/agromet/agromet_products'
    sub_path = products_dir[requestedData["element"]][requestedData["product"]]
    env_path = os.path.join(base_path,sub_path)
    return Environment(loader=FileSystemLoader(env_path))
    

@api_view(["GET"])
@wx_mapped_permission_required
def get_agromet_products_data(request):
    ## Load Agromet Products Functions
    with open('/surface/wx/sql/agromet/agromet_products/agromet_products_functions.sql', 'r') as f:
        query = f.read()

    config = settings.SURFACE_CONNECTION_STRING
    with psycopg2.connect(config) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            conn.commit()

    try:
        requestedData = {
            'start_year': request.GET.get('start_year'),
            'end_year': request.GET.get('end_year'),
            'station_id': request.GET.get('station_id'),
            'element': request.GET.get('element'),
            'product': request.GET.get('product'),
            'numeric_param_1': request.GET.get('numeric_param_1'),
            'numeric_param_2': request.GET.get('numeric_param_2'),
            'aggregation': request.GET.get('aggregation'),
            'summary_type': request.GET.get('summary_type'),
            'months': request.GET.get('months'),
            'interval': request.GET.get('interval'),
            'validate_data': request.GET.get('validate_data').lower() == 'true',
            'max_hour_pct': request.GET.get('max_hour_pct'),
            'max_day_pct': request.GET.get('max_day_pct'),
            'max_day_gap': request.GET.get('max_day_gap'),
        }

    except ValueError as e:
        logger.error(repr(e))
        return HttpResponse(status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(repr(e))
        return HttpResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # To calculate the seasonal summary, values from January of the next year and December of the previous year are required.
    requestedData['start_date'] = f"{int(requestedData['start_year'])-1}-12-01"
    requestedData['end_date'] = f"{int(requestedData['end_year'])+1}-02-01"
 
    config = settings.SURFACE_CONNECTION_STRING

    if not requestedData['validate_data']:
        requestedData['max_hour_pct']=100
        requestedData['max_day_pct']=100
        requestedData['max_day_gap']=9999

    env = get_agromet_products_sql_env(requestedData)
    context = get_agromet_products_sql_context(requestedData, env)

    pgia_code = '8858307' # Phillip Goldson Int'l Synop
    station = Station.objects.get(pk=requestedData['station_id'])

    is_hourly_station = station.is_automatic or station.code==pgia_code

    if requestedData['product'] == 'Evapotranspiration':
        requestedData['summary_type']=='Monthly'

    if requestedData['summary_type']=='Monthly':
        if is_hourly_station:
            template_name = 'monthly_hourly_valid.sql'
        else:
            template_name = 'monthly_daily_valid.sql'        
    else:
        if is_hourly_station:
            template_name = 'seasonal_hourly_valid.sql'
        else:
            template_name = 'seasonal_daily_valid.sql'


    template = env.get_template(template_name)
    query = template.render(context)

    logger.debug("Agromet Products Query: %s", query)

    config = settings.SURFACE_CONNECTION_STRING
    with psycopg2.connect(config) as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        response = []
        return JsonResponse(response, status=status.HTTP_200_OK, safe=False)

    products_without_statistics = [
        'Wind rose',
        'Evapotranspiration',
        'Drought indices',
        'Growing season statistics',
        'First and Last dates above specified specified temperature'
    ]
    
    if requestedData['product'] in products_without_statistics:
        tableData = df.fillna('').to_dict('records')
        minMaxData = {station.name: {}}
    else:
        tableData =  calculate_agromet_products_df_statistics(df)
        # minMaxData =  get_agromet_products_df_min_max(df)
        minMaxData = {station.name: {}}

    filtered_context = {key: value for key, value in context.items() if key not in ['timezone']}

    response = {
        'tableData': tableData,
        'context': filtered_context,
        'minMaxData': minMaxData
    }

    return JsonResponse(response, status=status.HTTP_200_OK, safe=False)            


class AgroMetProductsView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = "wx/agromet/agromet_products.html"

    agromet_variable_symbols = [
        'TEMP',
        'TEMPAVG',
        'TEMPMAX',
        'TEMPMIN',
        'EVAPPAN',
        'PRECIP',
        'RH',
        'RHAVG',
        'RHMAX',
        'RHMIN',
        'TSOIL1',
        'TSOIL4',
        'SOLARRAD',
        'WNDDIR',
        'WNDSPD',
        'WNDSPAVG',
        'WNDSPMAX',
        'WNDSPMIN'
    ]  

    agromet_variable_ids = Variable.objects.filter(symbol__in=agromet_variable_symbols).values_list('id', flat=True)
              
    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        context['username'] = f'{request.user.first_name} {request.user.last_name}' if request.user.first_name and request.user.last_name else request.user.username

        context['station_id'] = request.GET.get('station_id', 'null')
        context['variable_ids'] = request.GET.get('variable_ids', 'null')

        station_variables = StationVariable.objects.filter(variable_id__in=self.agromet_variable_ids).values('id', 'station_id', 'variable_id')
        station_ids = station_variables.values_list('station_id', flat=True).distinct()

        context['oldest_year'] = 1900
        context['stationvariable_list'] = list(station_variables)
        context['variable_list'] = list(Variable.objects.filter(symbol__in=self.agromet_variable_symbols).values('id', 'name', 'symbol'))
        context['station_list'] = list(Station.objects.filter(id__in=station_ids, is_active=True).values('id', 'name', 'code', 'is_automatic', 'latitude', 'longitude'))

        return self.render_to_response(context)


class CropViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = Crop.objects.all()
    
    serializer_class = serializers.CropSerializer


class AquacropModelRunView(views.APIView):
    permission_classes = (IsAuthenticated,)

    FORECAST_DAYS = 16

    def post(self, request):
        try:
            json_data = json.loads(request.body)

            model_params = self._get_model_params(json_data)
            schedule_df = self._get_irrigation_history(json_data)
            # schedule_df = schedule_df[schedule_df['Date' >= model_params['plantingDatetime'].strftime('%Y/%m/%d')]]

            is_historical_simulation = model_params['startDatetimeForecast'] is None

            history_df = self._get_weather_history(
                station_id=json_data['stationId'],
                start_date_history=model_params['startDatetimeHistory'].strftime('%Y/%m/%d'),
                end_date_history=model_params['endDatetimeHistory'].strftime('%Y/%m/%d'),
                data_type='last_filled'
            )

            if not is_historical_simulation:
                forecast_df = self._get_weather_forecast(
                    station_id=json_data['stationId'],
                    start_date_forecast=model_params['startDatetimeForecast'].strftime('%Y/%m/%d'),
                    end_date_forecast=model_params['endDatetimeForecast'].strftime('%Y/%m/%d'),
                    data_type='last_filled'
                )

                weather_df = pd.concat([history_df, forecast_df])

                # Extend weather_df to harvesting date because AquaCrop can't handle some cases
                date_range = pd.date_range(weather_df['Date'].max() + pd.Timedelta(days=1), model_params['harvestDate'])
                extended_df = pd.DataFrame(date_range, columns=['Date'])
                weather_df = pd.concat([weather_df, extended_df], ignore_index=True).ffill()

            else:
                weather_df = history_df

            if weather_df.isna().any().any():
                message = self._get_missing_data_message(json_data)
                print(message)
                return JsonResponse({'message': message}, status=400)

            if is_historical_simulation:
                model_history_df_1, output_1 = self._simulation_historical(json_data, model_params, weather_df, schedule_df)
                response = {
                    'history': model_history_df_1.to_dict('list'),
                    'strategies':[{
                        'id': 1,
                        'name': 'Historical Simulation',
                        'output': output_1
                    }]
                }
            else:
                model_history_df_1, output_1 = self._simulation_strategy_1(json_data, model_params, weather_df, schedule_df)
                model_history_df_2, output_2 = self._simulation_strategy_2(json_data, model_params, weather_df, schedule_df)
                model_history_df_3, output_3 = self._simulation_strategy_3(json_data, model_params, weather_df, schedule_df)

                response = {
                    'history': model_history_df_1.to_dict('list'),
                    'strategies':[{
                        'id': 1,
                        'name': 'Rainfed',
                        'output': output_1
                    },{
                        'id': 2,
                        'name': f"Irrigate {json_data['irrStratFixedAmount']} mm/day",
                        'output': output_2
                    },{
                        'id': 3,
                        'name': f"Irrigate {json_data['irrStratWCAmount']} mm/day if water content is below {json_data['irrStratWCPct']}%",
                        'output': output_3
                    }]
                }


            return JsonResponse(response, status=status.HTTP_200_OK)
            
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON format'}, status=status.HTTP_400_BAD_REQUEST)
    
    def _get_missing_data_message(self, json_data):
        station = Station.objects.get(id=json_data['stationId'])

        pgia_code = '8858307' # Phillip Goldson Int'l Synop
        referenec_et_method = 'Penman-Monteith' if station.is_automatic or station.code==pgia_code else 'Hargreaves'

        if referenec_et_method == 'Penman-Monteith':                
            template_name = 'missing_data_penman.sql'
            variables_symbols = ['TEMP', 'PRECIP', 'PRESSTN', 'WNDSPAVG', 'SOLARRAD', 'RH']
        else:
            template_name = 'missing_data_hargreaves.sql'
            variables_symbols = ['TEMPMIN', 'TEMPMAX', 'PRECIP']

        variables = list(Variable.objects.filter(symbol__in=variables_symbols))

        station_variables = list(StationVariable.objects.filter(station_id=station.id))

        missing_variables = []
        for variable in variables:
            if variable.id not in [sv.variable_id for sv in station_variables]:
                missing_variables.append(variable.name)

        if len(missing_variables) > 0:
            message = f"Station do not variables {missing_variables}."
        else:
            env_path= '/surface/wx/sql/agromet/agromet_irrigation'
            env = Environment(loader=FileSystemLoader(env_path))
            template = env.get_template(template_name)
            query = template.render(context={'station_id': station.id})

            config = settings.SURFACE_CONNECTION_STRING
            with psycopg2.connect(config) as conn:
                df_missing = pd.read_sql(query, conn)

            
            missing_data_variables = []
            for variable in variables:
                first_date = df_missing[df_missing['symbol'] == variable.symbol]['first_date'].to_list()[0]
                last_date = df_missing[df_missing['symbol'] == variable.symbol]['last_date'].to_list()[0]
                if first_date is None:
                    missing_data_variables.append(variable.name)

            if len(missing_data_variables) > 0:
                message = f"Station do not data for variables {missing_data_variables}."
            else:
                message = f"Station do not have enough data."

        return message

    def _get_weather_history(self, station_id: int, start_date_history: str, end_date_history: str, data_type: str):
        env_path= '/surface/wx/sql/agromet/agromet_irrigation/aquacrop_data'
        env = Environment(loader=FileSystemLoader(env_path))

        context = {
            'station_id': station_id,
            'sim_start_date': start_date_history,
            'sim_end_date': end_date_history
        }

        pgia_code = '8858307' # Phillip Goldson Int'l Synop
        station = Station.objects.get(id=station_id)
        referenec_et_method = 'Penman-Monteith' if station.is_automatic or station.code==pgia_code else 'Hargreaves'
        
        if referenec_et_method == 'Penman-Monteith':
            if data_type == 'last_filled':
                template_name = 'penman_lastfilled.sql'
            else:
                template_name = 'penman_original.sql'
        else:
            template_name = 'aquacrop_data_hargreaves.sql'
            if data_type == 'last_filled':
                template_name = 'hargreaves_lastfilled.sql'
            else:
                template_name = 'hargreaves_original.sql'            
            
        template = env.get_template(template_name)
        query = template.render(context)

        logger.debug("Aquacrop Query: %s", query)

        config = settings.SURFACE_CONNECTION_STRING
        with psycopg2.connect(config) as conn:
            df = pd.read_sql(query, conn)

        if df.empty:
            return pd.DataFrame()

        return df

    def _get_weather_forecast(self, station_id: int, start_date_forecast: str, end_date_forecast: str, data_type: str):
        # response = requests.get(f"https://storage.googleapis.com/surfaceforecast/forecast_station_{station_id}.json")
        # response.raise_for_status()

        # forecast_data = response.json()

        station = Station.objects.get(id=station_id)
        latitude = station.latitude
        longitude = station.longitude

        forecast_list = []
        OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
        variables = "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration"
        timezone = "America%2FChicago" # GMT-6 same as Belize

        url = f"{OPENMETEO_URL}?latitude={latitude}&longitude={longitude}&daily={variables}&timezone={timezone}&forecast_days={self.FORECAST_DAYS}"
        forecast_response = requests.get(url, timeout=20)
        forecast_data = forecast_response.json()

        # forecast_df = pd.DataFrame(forecast_data['forecast']['daily'])
        forecast_df = pd.DataFrame(forecast_data['daily'])
        forecast_df = forecast_df.rename(columns={
            'time': 'Date',
            'temperature_2m_max': 'MaxTemp',
            'temperature_2m_min': 'MinTemp',
            'precipitation_sum': 'Precipitation',
            'et0_fao_evapotranspiration': 'ReferenceET'
        })
        forecast_df['Date'] = pd.to_datetime(forecast_df['Date'])
        columns_order = ['Date', 'MinTemp', 'MaxTemp', 'Precipitation', 'ReferenceET']  
        forecast_df = forecast_df[columns_order]

        forecast_df = forecast_df[
            (forecast_df['Date'] >= pd.to_datetime(start_date_forecast)) &
            (forecast_df['Date'] <= pd.to_datetime(end_date_forecast))
        ]

        return forecast_df

    def _get_irrigation_history(self, json_data):
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')

        supabase: Client = create_client(supabase_url, supabase_key)        

        response = supabase.table('irrigations')\
            .select('*')\
            .eq('crop_id', json_data['simulationScenarioId'])\
            .execute()

        if len(response.data) > 0:
            irrigation_schedule = response.data
        else:
            irrigation_schedule = []      

        # irrigation_schedule = [{
        #     'id': None,
        #     'simulation_scenario_id': '498c24b6-19f1-4878-b99a-f1c4b539ed90',
        #     'first_date': '2010-01-01',
        #     'last_date': '2010-02-01',
        #     'amount': '2',
        # },{
        #     'id': None,
        #     'simulation_scenario_id': '498c24b6-19f1-4878-b99a-f1c4b539ed90',
        #     'first_date': '2010-02-02',
        #     'last_date': '2010-03-31',
        #     'amount': '1',
        # }]
        
        # irrigation_schedule = [{
        #     'id': None,
        #     'simulation_scenario_id': '498c24b6-19f1-4878-b99a-f1c4b539ed90',
        #     'first_date': '2010-01-01',
        #     'last_date': '2010-04-04',
        #     'amount': '5',
        # }]

        if len(irrigation_schedule) > 0:
            schedule_dfs = []
            for entry in irrigation_schedule:
                all_days = pd.date_range(entry['start_date'], entry['end_date'])
                depths = [entry['amount']] * len(all_days)
                entry_df = pd.DataFrame({'Date': all_days,'Depth': depths})
                schedule_dfs.append(entry_df)

            schedule_df = pd.concat(schedule_dfs, ignore_index=True)
        else:
            schedule_df =  pd.DataFrame(columns=['Date', 'Depth'])

        return schedule_df

    def _prepare_output(self, model, model_params, additional_df, is_historical_simulation):
        # output_df = pd.concat([
        #     model.weather_df.reset_index(drop=True),
        #     model._outputs.water_storage,
        #     model._outputs.water_flux,
        #     model._outputs.crop_growth
        # ], axis=1)

        model_output_cols = {
            'water_storage': ['time_step_counter', 'growing_season', 'dap', 'th1', 'th2', 'th3', 'th4', 'th5', 'th6', 'th7', 'th8', 'th9', 'th10', 'th11', 'th12'],
            'water_flux': ['time_step_counter', 'season_counter', 'dap', 'Wr', 'z_gw', 'surface_storage', 'IrrDay', 'Infl', 'Runoff', 'DeepPerc', 'CR', 'GwIn', 'Es', 'EsPot', 'Tr', 'TrPot'],
            'crop_growth': ['time_step_counter', 'season_counter', 'dap', 'gdd', 'gdd_cum', 'z_root', 'canopy_cover', 'canopy_cover_ns', 'biomass', 'biomass_ns', 'harvest_index', 'harvest_index_adj', 'DryYield', 'FreshYield', 'YieldPot']
        }

        output_df = pd.concat([
            model.weather_df.reset_index(drop=True),
            pd.DataFrame(model._outputs.water_storage, columns=model_output_cols['water_storage']),
            pd.DataFrame(model._outputs.water_flux, columns=model_output_cols['water_flux']),
            pd.DataFrame(model._outputs.crop_growth, columns=model_output_cols['crop_growth'])
        ], axis=1)

        output_df = output_df[output_df['Date'] <= model_params['simEndDate']]
        output_df.loc[:, 'Date'] = output_df['Date'].dt.strftime('%Y-%m-%d')

        output_df = output_df.loc[:, ~output_df.columns.duplicated()]
        output_df = output_df.round(2)


        # Drop last simulation day as AquacropOSPy does not output last day metrics
        output_df = output_df.iloc[:-1]

        output_df = output_df.drop(columns='z_gw') # This column has NaN values

        # For some reason AquacropOSPy os calculating Yield as HI * Biomass/100 and not 1000
        # so we need to convert the biomass to t/ha dividing by 100. Furthe investigation is needed
        output_df['biomass'] = output_df['biomass']/100
        output_df['biomass_ns'] = output_df['biomass_ns']/100

        output_df = pd.concat([output_df.reset_index(drop=True), additional_df.reset_index(drop=True)], axis=1)
        output_df['Depletion'] = output_df['Depletion'].fillna(0)
        output_df['TAW'] = output_df['TAW'].fillna(0)
        output_df['WaterContent'] = output_df['WaterContent'].fillna(0)
        output_df['WaterContentPct'] = (output_df['WaterContent'] / output_df['TAW']).replace(np.inf, np.nan).fillna(0)

        # Compute statistics for growing season (after planting and before maturity)
        output_df['gdd_nonpositive'] = ((output_df['growing_season'] == 1) & (output_df['gdd'] == 0)).astype(int)
        output_df['gdd_positive'] = ((output_df['growing_season'] == 1) & (output_df['gdd'] > 0)).astype(int)
        output_df['gdd_nonpositive_count'] = output_df['gdd_nonpositive'].cumsum()
        output_df['gdd_positive_count'] = output_df['gdd_positive'].cumsum()

        output_df['wc_25'] = ((output_df['growing_season'] == 1) & (output_df['WaterContentPct'] < 0.25)).astype(int)
        output_df['wc_50'] = ((output_df['growing_season'] == 1) & (output_df['WaterContentPct'] < 0.50)).astype(int)
        output_df['wc_75'] = ((output_df['growing_season'] == 1) & (output_df['WaterContentPct'] < 0.75)).astype(int)
        
        output_df['wc_25_count'] = output_df['wc_25'].cumsum()
        output_df['wc_50_count'] = output_df['wc_50'].cumsum()
        output_df['wc_75_count'] = output_df['wc_75'].cumsum()

        output_df['growing_season_count'] = output_df['growing_season'].cumsum()
        
        if is_historical_simulation:
            history_df = output_df

            display_df = output_df.iloc[-self.FORECAST_DAYS:]
            data =  display_df.to_dict('list')
            indicators = self._compute_indicators(output_df, model_params, is_historical_simulation)

        else:
            history_df = output_df[output_df['Date'] <= model_params['endDatetimeHistory']]
            forecast_df = output_df[output_df['Date'] > model_params['endDatetimeHistory']]
            forecast_df = forecast_df.iloc[:-1] # Aquacrop does not output last day metrics

            # history_df.loc[:, 'Date'] = history_df['Date'].dt.date
            # forecast_df.loc[:, 'Date'] = forecast_df['Date'].dt.date

            history_df.loc[:, 'Date'] = history_df['Date'].dt.strftime('%Y-%m-%d')
            forecast_df.loc[:, 'Date'] = forecast_df['Date'].dt.strftime('%Y-%m-%d')            

            data = forecast_df.to_dict('list')

            indicators = self._compute_indicators(output_df, model_params)


        return history_df, {'data': data, 'indicators': indicators}

    def _simulation_strategy_1(self, json_data, model_params, weather_df, schedule_df):     
        # Rainfed the next days
        # Even if we are rainfeding the next days, we need to account for past irrigations
        model = AquaCropModel(
            sim_start_time=model_params['simStartDate'],
            sim_end_time=model_params['harvestDate'],
            weather_df=weather_df,
            soil=model_params['soil'],
            crop=model_params['crop'],
            irrigation_management=IrrigationManagement(irrigation_method=3,Schedule=schedule_df),
            initial_water_content=InitialWaterContent(value=['FC']),
        )

        additional_data = {'Depletion': [], 'TAW': [], 'WaterContent': []}
        model._initialize()
        t = datetime.datetime.strptime(model_params['simStartDate'], '%Y/%m/%d') 
        # while model._clock_struct.model_is_finished is False:
        while t < datetime.datetime.strptime(model_params['simEndDate'], '%Y/%m/%d') :
            t = model._clock_struct.step_start_time

            additional_data['Depletion'].append(model._init_cond.depletion)
            additional_data['TAW'].append(model._init_cond.taw)
            water_content = max(0, model._init_cond.taw - max(0, model._init_cond.depletion))
            additional_data['WaterContent'].append(water_content)
            model.run_model(initialize_model=False, num_steps=1)

        additional_df = pd.DataFrame(additional_data)        

        historical_data, output = self._prepare_output(model, model_params, additional_df, is_historical_simulation=False)
        
        return historical_data, output

    def _simulation_strategy_2(self, json_data, model_params, weather_df, schedule_df):
        # Apply constant irrigation for the forecast period
        all_days = pd.date_range(model_params['startDatetimeForecast'], model_params['endDatetimeForecast'])

        depths = [json_data['irrStratFixedAmount']] * len(all_days)
        schedule_forecast_df = pd.DataFrame({'Date': all_days,'Depth': depths})

        combined_schedules_df = pd.concat([schedule_df, schedule_forecast_df])

        combined_schedules_df = combined_schedules_df[
            (combined_schedules_df['Date'] >= model_params['plantingDatetime'].strftime('%Y/%m/%d'))
        ]

        model = AquaCropModel(
            sim_start_time=model_params['simStartDate'],
            sim_end_time=model_params['harvestDate'],
            weather_df=weather_df,
            soil=model_params['soil'],
            crop=model_params['crop'],
            irrigation_management=IrrigationManagement(irrigation_method=3,Schedule=combined_schedules_df),
            initial_water_content=InitialWaterContent(value=['FC']),
        )

        additional_data = {'Depletion': [], 'TAW': [], 'WaterContent': []}

        model._initialize()
        t = datetime.datetime.strptime(model_params['simStartDate'], '%Y/%m/%d') 
        # while model._clock_struct.model_is_finished is False:
        while t < datetime.datetime.strptime(model_params['simEndDate'], '%Y/%m/%d') :
            t = model._clock_struct.step_start_time

            additional_data['Depletion'].append(model._init_cond.depletion)
            additional_data['TAW'].append(model._init_cond.taw)
            water_content = max(0, model._init_cond.taw - max(0, model._init_cond.depletion))
            additional_data['WaterContent'].append(water_content)
            model.run_model(initialize_model=False, num_steps=1)

        additional_df = pd.DataFrame(additional_data)        

        historical_data, output = self._prepare_output(model, model_params, additional_df, is_historical_simulation=False)
        return historical_data, output

    def _simulation_strategy_3(self, json_data, model_params, weather_df, schedule_df):
        # Irrigate based on water content threshold for the forecast period

        model = AquaCropModel(
            sim_start_time=model_params['simStartDate'],
            sim_end_time=model_params['harvestDate'],
            weather_df=weather_df,
            soil=model_params['soil'],
            crop=model_params['crop'],
            irrigation_management=IrrigationManagement(irrigation_method=3,Schedule=schedule_df),
            initial_water_content=InitialWaterContent(value=['FC']),
        )
        
        # Custom run to modify irrigation schedule on the fly
        additional_data = {'Depletion': [], 'TAW': [], 'WaterContent': []}
        model._initialize()
        t = datetime.datetime.strptime(model_params['simStartDate'], '%Y/%m/%d') 
        # while model._clock_struct.model_is_finished is False:
        while t < datetime.datetime.strptime(model_params['simEndDate'], '%Y/%m/%d') :
            t = model._clock_struct.step_start_time
            
            additional_data['Depletion'].append(model._init_cond.depletion)
            additional_data['TAW'].append(model._init_cond.taw)
            water_content = max(0, model._init_cond.taw - max(0, model._init_cond.depletion))
            additional_data['WaterContent'].append(water_content)

            if model._clock_struct.step_start_time > model_params['endDatetimeHistory']:
                if (model._init_cond.taw > 0):
                    wc_pct = 1-max(model._init_cond.depletion, 0)/model._init_cond.taw
                    if wc_pct < json_data['irrStratWCPct']/100:
                        model._param_struct.IrrMngt.Schedule[t]=json_data['irrStratWCAmount']
                else:
                    pass # No irrigation if TAW is 0
            
            model.run_model(initialize_model=False, num_steps=1)

        additional_df = pd.DataFrame(additional_data)
        
        historical_data, output = self._prepare_output(model, model_params, additional_df, is_historical_simulation=False)

        return historical_data, output              
    
    def _simulation_historical(self, json_data, model_params, weather_df, schedule_df):     
        # Even if we are rainfeding the next days, we need to account for past irrigations
        model = AquaCropModel(
            sim_start_time=model_params['simStartDate'],
            sim_end_time=model_params['simEndDate'],
            weather_df=weather_df,
            soil=model_params['soil'],
            crop=model_params['crop'],
            irrigation_management=IrrigationManagement(irrigation_method=3,Schedule=schedule_df),
            initial_water_content=InitialWaterContent(value=['FC']),
        )

        additional_data = {'Depletion': [], 'TAW': [], 'WaterContent': []}
        model._initialize()
        while model._clock_struct.model_is_finished is False:
            additional_data['Depletion'].append(model._init_cond.depletion)
            additional_data['TAW'].append(model._init_cond.taw)
            water_content = max(0, model._init_cond.taw - max(0, model._init_cond.depletion))
            additional_data['WaterContent'].append(water_content)
            model.run_model(initialize_model=False, num_steps=1)

        additional_df = pd.DataFrame(additional_data)
        historical_data, output = self._prepare_output(model, model_params, additional_df, is_historical_simulation=True)
        
        return historical_data, output
    
    def _get_simulation_datetimes(self, planting_datetime, crop):
        # Calculate initial harvest date using the planting year
        # # Crop maturity in calendar days +30 for latest harvest date
        # harvest_datetime = planting_datetime+datetime.timedelta(days=crop.MaturityCD+30)
        
        # # Can not Irrigate after maturity
        # harvest_datetime = planting_datetime+datetime.timedelta(days=crop.MaturityCD)

        # Add 1 so that Aquacrop handle last date of simulation
        # harvest_datetime = planting_datetime+datetime.timedelta(days=crop.MaturityCD+1)

        harvest_datetime = planting_datetime+datetime.timedelta(days=min(364, crop.MaturityCD))


        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        yestday = today - datetime.timedelta(days=1)

        if (harvest_datetime > yestday):
            is_historical_simulation = False

            # Get forecast days
            delta = harvest_datetime - yestday
            forecast_days = min(self.FORECAST_DAYS, delta.days)

            start_datetime_history = planting_datetime-datetime.timedelta(days=90)
            end_datetime_history = yestday
            
            start_datetime_forecast = today
            end_datetime_forecast = end_datetime_history+datetime.timedelta(days=forecast_days)

        else:
            start_datetime_history = planting_datetime-datetime.timedelta(days=90)
            end_datetime_history = harvest_datetime
            start_datetime_forecast = None
            end_datetime_forecast = None

        
        return harvest_datetime, start_datetime_history, end_datetime_history, start_datetime_forecast, end_datetime_forecast
            
    def _get_model_params(self, json_data):
        # Get simulation scenario from supabase
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')

        supabase: Client = create_client(supabase_url, supabase_key)

        response = supabase.table('crops')\
            .select('*')\
            .eq('id', json_data['simulationScenarioId'])\
            .execute()

        if len(response.data) > 0:
            simulation_scenario = response.data[0]
        else:
            raise ValueError("No simulation scenario found with the provided ID.")
            
        planting_datetime = datetime.datetime.strptime(simulation_scenario['planting_date'], "%Y-%m-%d")
        planting_date = simulation_scenario['planting_date'].replace('-','/')[5:]       

        if simulation_scenario['is_custom']:
            crop = self._set_custom_crop(c_name=simulation_scenario['crop'], planting_date=planting_date)
        else:
            crop = AquacropCrop(c_name=simulation_scenario['crop'], planting_date=planting_date)

        soil = AquacropSoil(soil_type=simulation_scenario['soil_type'])

        sim_datetimes = self._get_simulation_datetimes(planting_datetime, crop)

        harvest_datetime = sim_datetimes[0]
        start_datetime_history = sim_datetimes[1]
        end_datetime_history = sim_datetimes[2]
        start_datetime_forecast = sim_datetimes[3]
        end_datetime_forecast = sim_datetimes[4]
                
        # Some crops require harvest datetime to work properly
        crop.harvest_date = harvest_datetime.strftime("%m/%d")

        is_historical_simulation = start_datetime_forecast is None

        sim_start_datetime = start_datetime_history
        if is_historical_simulation:
            sim_end_datetime = end_datetime_history            
        else:
            sim_end_datetime = end_datetime_forecast

        model_params = {
            'crop': crop,
            'soil': soil,
            'plantingDatetime': planting_datetime,
            'startDatetimeHistory': start_datetime_history,
            'endDatetimeHistory': end_datetime_history,
            'startDatetimeForecast': start_datetime_forecast,
            'endDatetimeForecast': end_datetime_forecast,
            'simStartDate': sim_start_datetime.strftime("%Y/%m/%d"),
            'simEndDate': sim_end_datetime.strftime('%Y/%m/%d'),
            'harvestDate': harvest_datetime.strftime('%Y/%m/%d'),
        }

        return model_params

    def _compute_indicators(self, output_df, model_params, is_historical_simulation=False):
        output_df['Tr_ind'] = output_df['Tr']/output_df['TrPot']
        output_df['Es_ind'] = output_df['Es']/output_df['EsPot']
        output_df['B_ind'] = output_df['biomass']/output_df['biomass_ns']
        output_df['CC_ind'] = output_df['canopy_cover']/output_df['canopy_cover_ns']
        output_df['Yield_ind'] = output_df['DryYield']/output_df['YieldPot']
        output_df['GDD_ind'] = output_df['gdd_positive_count']/output_df['growing_season_count']
        output_df['WC25_ind'] = 1-output_df['wc_25_count']/output_df['growing_season_count']
        output_df['WC50_ind'] = 1-output_df['wc_50_count']/output_df['growing_season_count']
        output_df['WC75_ind'] = 1-output_df['wc_75_count']/output_df['growing_season_count']

        output_df['Tr_ind'] = round(output_df['Tr_ind'].fillna(1), 2)
        output_df['Es_ind'] = round(output_df['Es_ind'].fillna(1), 2)
        output_df['B_ind'] = round(output_df['B_ind'].fillna(1), 2)
        output_df['CC_ind'] = round(output_df['CC_ind'].fillna(1), 2)
        output_df['Yield_ind'] = round(output_df['Yield_ind'].fillna(1), 2)
        output_df['GDD_ind'] = round(output_df['GDD_ind'].fillna(1), 2)
        output_df['WC25_ind'] = round(output_df['WC25_ind'].fillna(1), 2)
        output_df['WC50_ind'] = round(output_df['WC50_ind'].fillna(1), 2)
        output_df['WC75_ind'] = round(output_df['WC75_ind'].fillna(1), 2)
        output_df['WC_ind'] = round(output_df['WaterContentPct'].fillna(1), 2)
        
        indicators = {
            'Transpiration': output_df['Tr_ind'].iloc[-2],
            'Evaporation': output_df['Es_ind'].iloc[-2],
            'Biomass': output_df['B_ind'].iloc[-2],
            'Canopy cover': output_df['CC_ind'].iloc[-2],
            'Yield': output_df['Yield_ind'].iloc[-2],
            'GDD': output_df['GDD_ind'].iloc[-2],
            'WC25':output_df['WC25_ind'].iloc[-2],
            'WC50':output_df['WC50_ind'].iloc[-2],
            'WC75':output_df['WC75_ind'].iloc[-2],
            'WC':output_df['WC_ind'].iloc[-2],
        }


        return indicators

    def _set_custom_crop(self, c_name, planting_date):
        django_crop = Crop.objects.get(name=c_name)

        # We need to initializeusing a crop because aquacrop has issues defining custom crops from scratch.
        custom_crop = AquacropCrop(c_name='Tomato', planting_date=planting_date)

        # Set custom parameters
        custom_crop.CropType=django_crop.crop_type
        custom_crop.PlantMethod=django_crop.plant_method
        custom_crop.CalendarType=django_crop.calendar_type
        custom_crop.SwitchGDD=1 if django_crop.switch_gdd else 0
        custom_crop.Emergence=django_crop.emergence
        custom_crop.EmergenceCD=django_crop.emergence_cd
        custom_crop.MaxRooting=django_crop.max_rooting
        custom_crop.MaxRootingCD=django_crop.max_rooting_cd
        custom_crop.Senescence=django_crop.senescence
        custom_crop.SenescenceCD=django_crop.senescence_cd
        custom_crop.Maturity=django_crop.maturity
        custom_crop.MaturityCD=django_crop.maturity_cd
        custom_crop.HIstart=django_crop.hi_start
        custom_crop.HIstartCD=django_crop.hi_start_cd
        custom_crop.Flowering=django_crop.flowering
        custom_crop.FloweringCD=django_crop.flowering_cd
        custom_crop.YldForm=django_crop.yld_form
        custom_crop.YldFormCD=django_crop.yld_form_cd
        custom_crop.YldWC=django_crop.yld_wc
        custom_crop.GDDMethod=django_crop.gdd_method
        custom_crop.Tbase=django_crop.t_base
        custom_crop.Tupp=django_crop.t_upp
        custom_crop.PolHeatStress=1 if django_crop.pol_heat_stress else 0
        custom_crop.Tmax_up=django_crop.t_max_up
        custom_crop.Tmax_lo=django_crop.t_max_lo
        custom_crop.PolColdStress=1 if django_crop.pol_cold_stress else 0
        custom_crop.Tmin_up=django_crop.t_min_up
        custom_crop.Tmin_lo=django_crop.t_min_lo
        custom_crop.TrColdStress=1 if django_crop.tr_cold_stress else 0
        custom_crop.GDD_up=django_crop.gdd_up
        custom_crop.GDD_lo=django_crop.gdd_lo
        custom_crop.Zmin=django_crop.z_min
        custom_crop.Zmax=django_crop.z_max
        custom_crop.fshape_r=django_crop.fshape_r
        custom_crop.SxTopQ=django_crop.sx_top_q
        custom_crop.SxBotQ=django_crop.sx_bot_q
        custom_crop.SeedSize=django_crop.seed_size
        custom_crop.PlantPop=django_crop.plant_pop
        custom_crop.CCx=django_crop.ccx
        custom_crop.CDC=django_crop.cdc
        custom_crop.CDC_CD=django_crop.cdc_cd
        custom_crop.CGC=django_crop.cgc
        custom_crop.CGC_CD=django_crop.cgc_cd
        custom_crop.Kcb=django_crop.kcb
        custom_crop.fage=django_crop.fage
        custom_crop.WP=django_crop.wp
        custom_crop.WPy=django_crop.wpy
        custom_crop.fsink=django_crop.fsink
        custom_crop.HI0=django_crop.hi0
        custom_crop.dHI_pre=django_crop.dhi_pre
        custom_crop.a_HI=django_crop.a_hi
        custom_crop.b_HI=django_crop.b_hi
        custom_crop.dHI0=django_crop.dhi0
        custom_crop.Determinant=1 if django_crop.determinant else 0
        custom_crop.exc=django_crop.exc
        custom_crop.p_up1 = django_crop.p_up1
        custom_crop.p_up2 = django_crop.p_up2
        custom_crop.p_up3 = django_crop.p_up3
        custom_crop.p_up4 = django_crop.p_up4
        custom_crop.p_lo1 = django_crop.p_lo1
        custom_crop.p_lo2 = django_crop.p_lo2
        custom_crop.p_lo3 = django_crop.p_lo3
        custom_crop.p_lo4 = django_crop.p_lo4
        custom_crop.fshape_w1 = django_crop.fshape_w1
        custom_crop.fshape_w2 = django_crop.fshape_w2
        custom_crop.fshape_w3 = django_crop.fshape_w3
        custom_crop.fshape_w4 = django_crop.fshape_w4
        custom_crop.fshape_b=django_crop.fshape_b
        custom_crop.PctZmin=django_crop.pct_z_min
        custom_crop.fshape_ex=django_crop.fshape_ex
        custom_crop.ETadj=1 if django_crop.et_adj else 0
        custom_crop.Aer=django_crop.aer
        custom_crop.LagAer=django_crop.lag_aer
        custom_crop.beta=django_crop.beta
        custom_crop.a_Tr=django_crop.a_tr
        custom_crop.GermThr=django_crop.germ_thr
        custom_crop.CCmin=django_crop.cc_min
        custom_crop.MaxFlowPct=django_crop.max_flow_pct
        custom_crop.HIini=django_crop.hi_ini
        custom_crop.bsted=django_crop.bsted
        custom_crop.bface=django_crop.bface
        # Dates
        custom_crop.planting_date=planting_date

        return custom_crop


class AquacropAvailableDataView(views.APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        try:
            json_data = json.loads(request.body)

            # Get simulation scenario from supabase
            supabase_url = os.getenv('SUPABASE_URL')
            supabase_key = os.getenv('SUPABASE_ANON_KEY')

            supabase: Client = create_client(supabase_url, supabase_key)

            # json_data['simulationScenarioId'] = "bf13e656-665e-45ac-98a8-802b483c29be"

            response = supabase.table('crops')\
                .select('*')\
                .eq('id', json_data['simulationScenarioId'])\
                .execute()

            if len(response.data) > 0:
                simulation_scenario = response.data[0]
            else:
                raise ValueError("No simulation scenario found with the provided ID.")

            planting_datetime = datetime.datetime.strptime(simulation_scenario['planting_date'], "%Y-%m-%d")
            planting_date = simulation_scenario['planting_date'].replace('-','/')[5:]

            if simulation_scenario['is_custom']:
                crop = self._set_custom_crop(c_name=simulation_scenario['crop'], planting_date=planting_date)
            else:
                crop = AquacropCrop(c_name=simulation_scenario['crop'], planting_date=planting_date)

            start_datetime_history, end_datetime_history = self._get_history_datetimes(planting_datetime, crop)

            env_path= '/surface/wx/sql/agromet/agromet_irrigation'
            env = Environment(loader=FileSystemLoader(env_path))

            context = {
                'station_id': json_data['stationId'],
                'sim_start_date': start_datetime_history.strftime('%Y/%m/%d'),
                'sim_end_date': end_datetime_history.strftime('%Y/%m/%d'),
            }

            pgia_code = '8858307' # Phillip Goldson Int'l Synop
            station = Station.objects.get(id=json_data['stationId'])
            referenec_et_method = 'Penman-Monteith' if station.is_automatic or station.code==pgia_code else 'Hargreaves'
            
            if referenec_et_method == 'Penman-Monteith':
                template_name = 'available_data_penman.sql'
            else:
                template_name = 'available_data_hargreaves.sql'

            template = env.get_template(template_name)
            query = template.render(context)
            # logger.info(query)

            config = settings.SURFACE_CONNECTION_STRING
            with psycopg2.connect(config) as conn:
                df = pd.read_sql(query, conn)

            if df.empty:
                return Response({'error': 'No data'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            result = df.to_dict(orient='records')[0]

            if referenec_et_method == 'Penman-Monteith':
                variables=[
                    'MinTemp',
                    'MaxTemp',
                    'Precipitation',
                    'AtmosphericPressure',
                    'WindSpeed',
                    'SolarRadiation',
                    'RelativeHumidity'
                ]
            else:
                variables=[
                    'MinTemp',
                    'MaxTemp',
                    'Precipitation',
                ]
            
            results = [{
                    'variable': variable,
                    'percentage': f"{round(100*result[f'{variable}Count']/result['Days'], 2)}%",
                    'first_day': result[f'{variable}MinDay'],
                    'last_day': result[f'{variable}MaxDay'],
                } for variable in variables
            ]

            return JsonResponse({'data': results}, status=status.HTTP_200_OK)
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON format'}, status=status.HTTP_400_BAD_REQUEST)

    def _get_history_datetimes(self, planting_datetime, crop):
        # Calculate initial harvest date using the planting year
        # Crop maturity in calendar days +30 for latest harvest date
        # harvest_datetime = planting_datetime+datetime.timedelta(days=crop.MaturityCD+30)

        harvest_datetime = planting_datetime+datetime.timedelta(days=min(364, crop.MaturityCD))
        start_datetime_history = planting_datetime-datetime.timedelta(days=90)
        
        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        yestday = today - datetime.timedelta(days=1)
        if (harvest_datetime > yestday):
            end_datetime_history = yestday
        else:
            end_datetime_history = harvest_datetime

        return start_datetime_history, end_datetime_history


@method_decorator(wx_mapped_permission_required, name="dispatch")
class GroupsInfo(views.APIView):
    # permission_classes = (IsAuthenticated, IsSuperUser)

    def get(self, request, *args, **kwargs):
        query = "SELECT id, name FROM auth_group ORDER BY id;"

        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        # Convert tuples to JSON-safe structures
        groups_data = [
            {"id": row[0], "name": row[1]}
            for row in rows
        ]

        return Response(groups_data)


# retrive the all users info
@method_decorator(wx_mapped_permission_required, name="dispatch")
class UsersGroupsInfo(views.APIView):
    # permission_classes = (IsAuthenticated, IsSuperUser)

    def get(self, request, *args, **kwargs):
        query = """
                    SELECT
                        AU.id,
                        AU.first_name,
                        AU.last_name,
                        AU.username,
                        AU.email,
                        AU.is_superuser,
                        COALESCE(array_agg(AUG.group_id ORDER BY AUG.group_id)
                                FILTER (WHERE AUG.group_id IS NOT NULL),
                                '{}') AS all_group_ids
                    FROM auth_user AS AU
                    LEFT JOIN auth_user_groups AS AUG
                        ON AU.id = AUG.user_id
                    GROUP BY
                        AU.id,
                        AU.first_name,
                        AU.last_name,
                        AU.username,
                        AU.email
                    ORDER BY AU.id;
                """

        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        # Convert tuples to JSON-safe structures
        users_groups_data = [
            {"id": row[0], "first_name": row[1], "last_name": row[2], "username": row[3], "email": row[4], "acc_type": row[5], "roles": row[6]}
            for row in rows
        ]

        return Response(users_groups_data)

# update users info
@method_decorator(wx_mapped_permission_required, name="dispatch")
class UpdateUserRoles(views.APIView):
    # permission_classes = (IsAuthenticated, IsSuperUser)

    def patch(self, request, user_id):
        roles = request.data.get("roles", [])

        if not isinstance(roles, list) or not all(isinstance(x, int) for x in roles):
            return Response({"message": "roles must be a list of integers"}, status=400)

        # transaction atomic ensure that everything with the with block is successfull otherwise it roles back the changes made
        # this matters as we are delting all old roles and then updating
        with transaction.atomic():
            # delete existing roles
            User.groups.through.objects.filter(user_id=user_id).delete()

            # insert new roles
            through_objs = [
                User.groups.through(user_id=user_id, group_id=gid) for gid in roles
            ]
            User.groups.through.objects.bulk_create(through_objs)

        return Response({"message": "ok"})
    

@method_decorator(wx_mapped_permission_required, name="dispatch")
class PermissionPagesInfo(views.APIView):
    """
    Returns all WxPermissionPages (including category info)
    so the frontend can group permissions by category.

    Response example:
    [
      {
        "id": 1,
        "name": "Stations List",
        "url_name": "stations-list",
        "description": "View and manage stations.",
        "category": { "id": 2, "name": "Stations" }
      },
      ...
    ]
    """

    def get(self, request):
        # select_related avoids an extra query per row when reading p.category
        pages = (
            WxPermissionPages.objects
            .select_related("category")
            .all()
            .order_by("category__sort_order", "category__name", "name")
        )

        data = [
            {
                "id": p.id,
                "name": p.name,
                "url_name": p.url_name,
                "description": p.description,
                "category": {
                    "id": p.category_id,
                    "name": p.category.name if p.category_id else None,
                },
            }
            for p in pages
        ]

        return Response(data, status=status.HTTP_200_OK)


@method_decorator(wx_mapped_permission_required, name="dispatch")
class GroupPageAccessView(views.APIView):
    """
    GET  -> return the current page access matrix for a group
    PUT  -> replace the group's access matrix (bulk save)

    Storage rule (important):
    - We do NOT store rows that grant nothing (read/write/delete all False).
      "No access" is represented by the absence of a row.
    """

    def get(self, request, group_id: int):
        # Ensure the group exists (404 is nicer, but keeping style)
        Group.objects.get(id=group_id)

        rows = WxGroupPageAccess.objects.filter(group_id=group_id).select_related("page")

        access_map = {
            r.page.url_name: {
                "can_read": r.can_read,
                "can_write": r.can_write,
                "can_delete": r.can_delete,
            }
            for r in rows
        }

        return Response(access_map, status=status.HTTP_200_OK)

    def put(self, request, group_id: int):
        """
        Expected payload:
        {
          "<page_url_name>": {"can_read": true, "can_write": false, "can_delete": false},
          ...
        }

        Behavior:
        - If all flags are False -> we SKIP it (no DB row gets created).
        - If write/delete is True but read is False -> we either:
            A) reject (400), OR
            B) auto-fix (set read=True)
          Below: I chose to REJECT to match your model constraints strictly.
        """
        payload = request.data

        if not isinstance(payload, dict):
            return Response(
                {"message": "Invalid payload. Must be an object keyed by page url_name."},
                status=400
            )

        # Ensure group exists
        Group.objects.get(id=group_id)

        # Look up pages once
        pages_by_url = {p.url_name: p for p in WxPermissionPages.objects.all()}

        objs_to_create = []

        for page_url, perms in payload.items():
            page = pages_by_url.get(page_url)
            if not page:
                return Response({"message": f"Unknown page url_name: {page_url}"}, status=400)

            # Defensive reads (payload might be missing keys)
            can_read = bool((perms or {}).get("can_read", False))
            can_write = bool((perms or {}).get("can_write", False))
            can_delete = bool((perms or {}).get("can_delete", False))

            # 1) Skip rows that grant nothing (represents "no access")
            if not (can_read or can_write or can_delete):
                continue

            # 2) Enforce rule: write/delete implies read
            # Choose ONE behavior:

            # Option A (strict): reject bad payload
            if (can_write or can_delete) and not can_read:
                return Response(
                    {"message": f"{page_url}: can_read must be True if can_write or can_delete is True."},
                    status=400
                )

            # Option B (auto-fix): uncomment instead of Option A
            # if (can_write or can_delete) and not can_read:
            #     can_read = True

            objs_to_create.append(
                WxGroupPageAccess(
                    group_id=group_id,
                    page=page,
                    can_read=can_read,
                    can_write=can_write,
                    can_delete=can_delete
                )
            )

        # Bulk replace in a transaction
        with transaction.atomic():
            # Delete existing rows (fresh overwrite)
            WxGroupPageAccess.objects.filter(group_id=group_id).delete()

            # Only create valid rows (no all-false rows)
            if objs_to_create:
                WxGroupPageAccess.objects.bulk_create(objs_to_create)

        return Response({"message": "ok"}, status=status.HTTP_200_OK)