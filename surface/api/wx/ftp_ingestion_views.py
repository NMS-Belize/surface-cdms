"""SURFACE FTP Data Ingestion UI + JSON endpoints (Django 3.2).


Security posture:
- Passwords never appear in API JSON; blank password on edit preserves the old value.
- Server deletion requires a fresh dependent-job count and the server name.
- FTP test resolves a host once and connects to the resolved IP to avoid DNS rebinding.
"""

import fnmatch
import ipaddress
import json
import re
import socket
from ftplib import FTP, error_perm, all_errors
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.base import TemplateView

from wx.decorators import wx_permission_required, wx_mapped_permission_required

from wx.mixins import WxPermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils.module_loading import import_string
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from wx.models import FTPServer, StationFileIngestion, StationDataFile, StationDataFileStatus, Station, Decoder


def _json(request):
    if len(request.body) > 64 * 1024:
        raise ValueError('Request is too large.')
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Invalid JSON request.')
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object.')
    return data


def _invalid_form(form):
    return JsonResponse({'message': 'Please correct the highlighted fields.',
                         'errors': {key: list(errors) for key, errors in form.errors.items()}},
                        status=400)


def _server_dict(obj):
    return {'id': obj.pk, 'name': obj.name, 'host': obj.host, 'port': obj.port,
            'username': obj.username, 'is_active_mode': obj.is_active_mode,
            'jobs_count': getattr(obj, 'jobs_count', None)}


def _job_dict(obj):
    return {
        'id': obj.pk, 'ftp_server': obj.ftp_server_id,
        'ftp_server_name': obj.ftp_server.name,
        'remote_folder': obj.remote_folder, 'station': obj.station_id,
        'station_name': str(obj.station), 'file_pattern': obj.file_pattern,
        'decoder': obj.decoder_id, 'decoder_name': str(obj.decoder),
        'cron_schedule': obj.cron_schedule,
        'utc_offset_minutes': obj.utc_offset_minutes,
        'delete_from_server': obj.delete_from_server,
        'is_active': obj.is_active, 'is_binary_transfer': obj.is_binary_transfer,
        'process_in_chunks': obj.process_in_chunks,
        'is_highfrequency_data': obj.is_highfrequency_data,
        'override_data_on_conflict': obj.override_data_on_conflict,
    }


def _file_dict(obj):
    # Use the same elapsed-time definition as StationDataFileAdmin:
    # the time between creation and the most recent update. A later edit to
    # the record will change this value; it is not a separate Celery runtime.
    created_at = getattr(obj, 'created_at', None)
    updated_at = getattr(obj, 'updated_at', None)
    processing_duration_seconds = None

    if created_at is not None and updated_at is not None:
        # Whole seconds match the minute/second calculation in Django Admin.
        # Clamp negative durations caused by inconsistent timestamps to zero.
        processing_duration_seconds = max(
            0, int((updated_at - created_at).total_seconds())
        )

    return {
        'id': obj.pk, 'station': obj.station_id, 'station_name': str(obj.station),
        'decoder': obj.decoder_id, 'decoder_name': str(obj.decoder),
        'status': obj.status_id, 'status_name': str(obj.status),
        'filename': Path(obj.filepath).name, 'filepath': obj.filepath,
        'file_hash': obj.file_hash, 'file_size': obj.file_size,
        'utc_offset_minutes': obj.utc_offset_minutes,
        'observation': obj.observation,
        'process_in_chunks': obj.process_in_chunks,
        'is_highfrequency_data': obj.is_highfrequency_data,
        'override_data_on_conflict': obj.override_data_on_conflict,
        'created_at': created_at.isoformat() if created_at else None,
        'updated_at': updated_at.isoformat() if updated_at else None,
        # Numeric seconds let the frontend format both table and dialog alike.
        'processing_duration_seconds': processing_duration_seconds,
    }


class FTPServerForm(forms.ModelForm):
    password = forms.CharField(max_length=128, required=False,
                               widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = FTPServer
        fields = ('name', 'host', 'port', 'username', 'password', 'is_active_mode')

    def clean_password(self):
        supplied = self.cleaned_data.get('password', '')
        if supplied:
            return supplied
        if self.instance.pk:
            return self.instance.password
        raise ValidationError('Password is required for a new server.')

    def clean_host(self):
        host = self.cleaned_data['host'].strip()
        if not host or any(c in host for c in '/\\@?#') or '://' in host or any(c.isspace() for c in host):
            raise ValidationError('Enter a hostname or IP address, without a URL scheme or path.')
        return host

    def clean_port(self):
        port = self.cleaned_data['port']
        if not (1 <= port <= 65535):
            raise ValidationError('Port must be between 1 and 65535.')
        return port


class StationFileIngestionForm(forms.ModelForm):
    class Meta:
        model = StationFileIngestion
        fields = (
            'ftp_server', 'remote_folder', 'station', 'file_pattern', 'decoder',
            'cron_schedule', 'utc_offset_minutes', 'delete_from_server',
            'is_active', 'is_binary_transfer', 'process_in_chunks',
            'is_highfrequency_data', 'override_data_on_conflict',
        )

    def clean_cron_schedule(self):
        expression = self.cleaned_data['cron_schedule'].strip()
        fields = expression.split()
        if len(fields) != 5 or any(not re.fullmatch(r'[A-Za-z0-9*/,-]+', field) for field in fields):
            raise ValidationError('Enter a standard five-field cron expression using valid cron characters.')
        return expression

    def clean_utc_offset_minutes(self):
        minutes = self.cleaned_data['utc_offset_minutes']
        if not (-840 <= minutes <= 840):
            raise ValidationError('UTC offset must be between -840 and +840 minutes.')
        return minutes

    def clean(self):
        values = super().clean()
        if values.get('process_in_chunks') and values.get('is_highfrequency_data'):
            raise ValidationError('High-frequency data and processing in chunks cannot both be enabled.')
        return values


def _instance_data(instance, fields, payload):
    """Create complete form data for a PATCH, retaining fields not supplied."""
    data = {}
    for field in fields:
        if field == 'password':
            data[field] = payload.get(field, '')
        elif field in ('ftp_server', 'station', 'decoder'):
            data[field] = payload.get(field, getattr(instance, f'{field}_id'))
        else:
            data[field] = payload.get(field, getattr(instance, field))
    return data


class FTPDataIngestionView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    """Render the FTP ingestion workspace using SURFACE's existing view pattern.

    The JSON endpoints below retain their individual server-side permission checks.
    Configure this class's feature-permission attribute exactly as in your
    existing DataExportView / WxPermissionRequiredMixin implementation.
    """

    template_name = 'wx/ftp_ingestion.html'


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(['GET', 'POST'])
def ftp_server_collection(request):
    if request.method == 'GET':
        from django.db.models import Count
        rows = FTPServer.objects.annotate(jobs_count=Count('stationfileingestion')).order_by('name', 'id')
        return JsonResponse({'results': [_server_dict(row) for row in rows]})

    try:
        payload = _json(request)
    except ValueError as exc:
        return JsonResponse({'message': str(exc)}, status=400)
    form = FTPServerForm(payload)
    if not form.is_valid():
        return _invalid_form(form)
    try:
        row = form.save()
    except IntegrityError:
        return JsonResponse({'message': 'A server with these details already exists.'}, status=409)
    return JsonResponse({'result': _server_dict(row)}, status=201)


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(['GET', 'PATCH', 'DELETE'])
def ftp_server_detail(request, pk):
    row = get_object_or_404(FTPServer, pk=pk)
    if request.method == 'GET':
        return JsonResponse({'result': _server_dict(row)})
    if request.method == 'PATCH':
        try:
            payload = _json(request)
        except ValueError as exc:
            return JsonResponse({'message': str(exc)}, status=400)
        form = FTPServerForm(_instance_data(row, FTPServerForm.Meta.fields, payload), instance=row)
        if not form.is_valid():
            return _invalid_form(form)
        try:
            row = form.save()
        except IntegrityError:
            return JsonResponse({'message': 'A server with these details already exists.'}, status=409)
        return JsonResponse({'result': _server_dict(row)})

    try:
        payload = _json(request)
    except ValueError as exc:
        return JsonResponse({'message': str(exc)}, status=400)
    with transaction.atomic():
        row = FTPServer.objects.select_for_update().filter(pk=pk).first()
        if row is None:
            return JsonResponse({'message': 'Server no longer exists.'}, status=404)
        # Parent lock prevents new referencing rows being inserted concurrently on PostgreSQL.
        count = StationFileIngestion.objects.filter(ftp_server_id=pk).count()
        if payload.get('confirm_name') != row.name:
            return JsonResponse({'message': 'Type the exact server name to confirm deletion.'}, status=400)
        try:
            expected = int(payload.get('expected_job_count'))
        except (TypeError, ValueError):
            expected = -1
        if expected != count:
            return JsonResponse({'message': f'This server now has {count} ingestion job(s). Review and confirm again.',
                                 'jobs_count': count}, status=409)
        row.delete()  # Django CASCADE removes exactly the linked StationFileIngestion rows.
    return JsonResponse({'success': True, 'deleted_jobs': count})


@wx_mapped_permission_required
@require_http_methods(['GET'])
def ftp_server_delete_preview(request, pk):
    row = get_object_or_404(FTPServer, pk=pk)
    return JsonResponse({'id': row.pk, 'name': row.name,
                         'jobs_count': StationFileIngestion.objects.filter(ftp_server_id=pk).count()})


def _ftp_test_target(payload, saved=None):
    host = str(payload.get('host') or (saved.host if saved else '')).strip()
    username = str(payload.get('username') if payload.get('username') is not None
                   else (saved.username if saved else '')).strip()
    password = payload.get('password') or (saved.password if saved else '')
    port = payload.get('port') if payload.get('port') not in (None, '') else (saved.port if saved else None)
    active = payload.get('is_active_mode') if 'is_active_mode' in payload else (saved.is_active_mode if saved else False)
    if not host or not username or not password:
        raise ValueError('Host, username and password are required to test a connection.')
    if any(c in host for c in '/\\@?#') or '://' in host or any(c.isspace() for c in host):
        raise ValueError('Host must be a hostname or IP address, not a URL.')
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError('Enter a valid FTP port.')
    if not 1 <= port <= 65535:
        raise ValueError('FTP port must be between 1 and 65535.')
    if not isinstance(active, bool):
        raise ValueError('Transfer mode must be a boolean.')
    return host, port, username, password, active


def _resolved_ftp_ip(host, port):
    try:
        endpoints = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError('Unable to resolve the FTP hostname.')
    approved = []
    for family, _kind, _proto, _canonical, sockaddr in endpoints:
        ip = ipaddress.ip_address(sockaddr[0])
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            continue
        approved.append(str(ip))
    if not approved:
        raise ValueError('The FTP host resolves only to prohibited network addresses.')
    return approved[0]


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(['POST'])
def ftp_server_test(request):
    try:
        payload = _json(request)
        saved = None
        if payload.get('id'):
            saved = get_object_or_404(FTPServer, pk=payload['id'])

        host, port, username, password, active = _ftp_test_target(payload, saved)
        ip = _resolved_ftp_ip(host, port)
    except ValueError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)

    timeout = max(2, min(int(getattr(settings, 'SURFACE_FTP_TEST_TIMEOUT', 8)), 30))
    try:
        with FTP(timeout=timeout) as ftp:
            ftp.connect(ip, port, timeout=timeout)
            ftp.login(user=username, passwd=password)
            ftp.set_pasv(not active)
            ftp.pwd()  # Verifies an authenticated FTP command succeeds.
        return JsonResponse({'success': True, 'message': 'Connected and authenticated successfully.'})
    except error_perm as exc:
        # Do not expose raw FTP responses: they can contain account details.
        message = ('FTP authentication failed. Check username and password.'
                   if str(exc).startswith('530') else 'FTP server rejected the test command.')
    except (TimeoutError, socket.timeout):
        message = 'The FTP connection timed out.'
    except (ConnectionError, OSError):
        message = 'Could not reach the FTP server.'
    except all_errors:
        message = 'The FTP server did not complete the connection test.'
    return JsonResponse({'success': False, 'message': message}, status=422)


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(['GET', 'POST'])
def ftp_job_collection(request):
    if request.method == 'GET':
        rows = StationFileIngestion.objects.select_related('ftp_server', 'station', 'decoder').order_by('pk')
        return JsonResponse({'results': [_job_dict(row) for row in rows]})
    try:
        payload = _json(request)
    except ValueError as exc:
        return JsonResponse({'message': str(exc)}, status=400)
    form = StationFileIngestionForm(payload)
    if not form.is_valid():
        return _invalid_form(form)
    try:
        row = form.save()
    except IntegrityError:
        return JsonResponse({'message': 'Could not create this ingestion job.'}, status=409)
    row = StationFileIngestion.objects.select_related('ftp_server', 'station', 'decoder').get(pk=row.pk)
    return JsonResponse({'result': _job_dict(row)}, status=201)


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(['GET', 'PATCH', 'DELETE'])
def ftp_job_detail(request, pk):
    row = get_object_or_404(StationFileIngestion.objects.select_related('ftp_server', 'station', 'decoder'), pk=pk)
    if request.method == 'GET':
        return JsonResponse({'result': _job_dict(row)})
    if request.method == 'DELETE':
        row.delete()
        return JsonResponse({'success': True})
    try:
        payload = _json(request)
    except ValueError as exc:
        return JsonResponse({'message': str(exc)}, status=400)
    form = StationFileIngestionForm(_instance_data(row, StationFileIngestionForm.Meta.fields, payload), instance=row)
    if not form.is_valid():
        return _invalid_form(form)
    try:
        row = form.save()
    except IntegrityError:
        return JsonResponse({'message': 'Could not update this ingestion job.'}, status=409)
    row = StationFileIngestion.objects.select_related('ftp_server', 'station', 'decoder').get(pk=row.pk)
    return JsonResponse({'result': _job_dict(row)})


@wx_mapped_permission_required
@require_http_methods(['GET'])
def ftp_references(request):
    return JsonResponse({
        'ftp_servers': ([{'id': f.pk, 'name': f.name} for f in FTPServer.objects.all().order_by('name', 'pk')]),
        'stations': [{'id': s.pk, 'name': str(s)} for s in Station.objects.all().order_by('pk')],
        'decoders': [{'id': d.pk, 'name': str(d)} for d in Decoder.objects.all().order_by('pk')],
        'statuses': [{'id': st.pk, 'name': str(st)} for st in StationDataFileStatus.objects.all().order_by('pk')],
    })


@wx_mapped_permission_required
@require_http_methods(['GET'])
def ftp_file_collection(request):
    rows = StationDataFile.objects.select_related('station', 'decoder', 'status')
    for key, lookup in [('station', 'station_id'), ('decoder', 'decoder_id'), ('status', 'status_id')]:
        value = request.GET.get(key)
        if value:
            try:
                rows = rows.filter(**{lookup: int(value)})
            except ValueError:
                return JsonResponse({'message': f'Invalid {key} ID.'}, status=400)
    search = request.GET.get('search', '').strip()[:256]
    if search:
        rows = rows.filter(Q(filepath__icontains=search) | Q(file_hash__icontains=search))
    field_names = {field.name for field in StationDataFile._meta.fields}
    if 'created_at' in field_names:
        for key, suffix in [('from', 'gte'), ('to', 'lte')]:
            raw = request.GET.get(key)
            if raw:
                parsed = parse_date(raw)
                if parsed is None:
                    return JsonResponse({'message': f'Invalid {key} date.'}, status=400)
                rows = rows.filter(**{f'created_at__date__{suffix}': parsed})
        rows = rows.order_by('-created_at', '-pk')
    else:
        rows = rows.order_by('-pk')
    try:
        page = max(1, int(request.GET.get('page', 1)))
        size = max(10, min(100, int(request.GET.get('page_size', 25))))
    except ValueError:
        return JsonResponse({'message': 'Invalid pagination parameters.'}, status=400)
    start = (page - 1) * size
    batch = list(rows[start:start + size + 1])
    return JsonResponse({'results': [_file_dict(row) for row in batch[:size]],
                         'page': page, 'page_size': size, 'has_next': len(batch) > size})


def _local_file_for_download(record):
    # The deployment defines which local directories are safe for downloads.
    # No download roots configured means downloads are disabled.
    roots = getattr(settings, "SURFACE_INGESTION_DOWNLOAD_ROOTS", [])

    if not roots:
        return None, 'File downloads are not configured on this SURFACE instance.'
    stored = Path(record.filepath)
    for configured in roots:
        try:
            root = Path(configured).resolve(strict=True)
            # Absolute DB paths stay absolute; relative DB paths are relative to
            # each configured ingestion root (never relative to arbitrary cwd).
            candidate = stored if stored.is_absolute() else root / stored
            resolved = candidate.resolve(strict=True)
            if not resolved.is_file():
                continue
            try:
                resolved.relative_to(root)
                return resolved, None
            except ValueError:
                continue
        except (FileNotFoundError, NotADirectoryError, OSError):
            continue
    return None, 'File unavailable or outside the approved ingestion directories.'


@wx_mapped_permission_required
@require_http_methods(['GET'])
def ftp_file_availability(request, pk):
    row = get_object_or_404(StationDataFile, pk=pk)
    path, error = _local_file_for_download(row)
    if error:
        return JsonResponse({'available': False, 'message': error}, status=404)
    return JsonResponse({'available': True, 'filename': path.name})


@wx_mapped_permission_required
@require_http_methods(['GET'])
def ftp_file_download(request, pk):
    row = get_object_or_404(StationDataFile, pk=pk)
    path, error = _local_file_for_download(row)
    if error:
        return JsonResponse({'message': error}, status=404)
    try:
        response = FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name,
                                content_type='application/octet-stream')
    except OSError:
        return JsonResponse({'message': 'File unavailable.'}, status=404)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response