"""SURFACE LRGS management: Django 3.2, Vue 2, mapped page permissions.

Each URL performs only ONE permission action, so the existing
@wx_mapped_permission_required decorator cannot accidentally give readers
write/delete rights on a mixed-method endpoint.
"""

import datetime as dt
import json
import re

import pytz
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.generic.base import TemplateView

from wx.decorators import wx_mapped_permission_required
from wx.mixins import WxPermissionRequiredMixin
from wx.models import (Decoder, DcpMessages, Format, Interval, LRGSConfiguration,
                       LRGSIngestionRun, NoaaDcp, NoaaDcpsStation,
                       NoaaTransmissionType, Station)
from wx.lrgs_services import get_lrgs_settings


class LRGSIngestionView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    """WxPermissionRequiredMixin obtains its parent permission from URL name."""
    template_name = "wx/lrgs_ingestion.html"


def response_error(message, status=400, errors=None):
    data = {"message": message}
    if errors:
        data["errors"] = errors
    return JsonResponse(data, status=status)


def read_json(request):
    if len(request.body) > 128 * 1024:
        raise ValueError("Request exceeds 128 KB.")
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid JSON body.") from exc
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def form_errors(form):
    return response_error("Please correct the highlighted fields.", errors={
        key: list(value) for key, value in form.errors.items()
    })


def config_timezone():
    """Use SURFACE's deployment timezone, never a Belize hardcoded default."""
    zone = getattr(settings, "TIMEZONE_NAME", None) or settings.TIME_ZONE
    return pytz.timezone(zone)


def parse_user_datetime(value, name, required=True):
    """HTML datetime-local values are naive; interpret in settings.TIMEZONE_NAME.

    ISO strings containing Z/offset are already absolute and converted to UTC.
    Ambiguous or nonexistent DST times are rejected rather than guessed.
    """
    if not value:
        if required:
            raise ValueError(f"{name} is required.")
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValueError(f"{name} must be a valid date and time.")
    if timezone.is_naive(parsed):
        try:
            parsed = config_timezone().localize(parsed, is_dst=None)
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError) as exc:
            raise ValueError(f"{name} is ambiguous or invalid in the configured timezone.") from exc
    return parsed.astimezone(pytz.UTC)


def dcp_dict(dcp):
    """Exclude large config_data and avoid returning config file content in lists."""
    def tm(value):
        return value.strftime("%H:%M:%S") if value else None
    return {
        "id": dcp.pk, "dcp_address": dcp.dcp_address,
        "first_channel": dcp.first_channel,
        "first_channel_type": dcp.first_channel_type_id,
        "second_channel": dcp.second_channel,
        "second_channel_type": dcp.second_channel_type_id,
        "first_transmission_time": tm(dcp.first_transmission_time),
        "transmission_window": tm(dcp.transmission_window),
        "transmission_period": tm(dcp.transmission_period),
        "last_datetime": dcp.last_datetime.isoformat() if dcp.last_datetime else None,
        "has_config": bool(dcp.config_data),
    }


def association_dict(row):
    return {
        "id": row.pk, "station": row.station_id,
        "station_name": str(row.station), "noaa_dcp": row.noaa_dcp_id,
        "dcp_address": row.noaa_dcp.dcp_address,
        "decoder": row.decoder_id, "decoder_name": str(row.decoder),
        "interval": row.interval_id, "interval_name": str(row.interval),
        "format": row.format_id, "format_name": str(row.format),
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat() if row.end_date else None,
    }


def message_dict(row, include_payload=False):
    data = {
        "id": row.pk, "noaa_dcp": row.noaa_dcp_id,
        "dcp_address": row.noaa_dcp.dcp_address,
        "datetime": row.datetime.isoformat(),
        "failure_code": row.failure_code,
        "signal_strength": row.signal_strength,
        "frequency_offset": row.frequency_offset,
        "modulation_index": row.modulation_index,
        "data_quality": row.data_quality, "channel": row.channel,
        "spacecraft_indicator": row.spacecraft_indicator,
        "data_source": str(row.data_source),
        "message_data_length": row.message_data_length,
    }
    if include_payload:
        data["payload"] = row.payload
    return data


def run_dict(row):
    return {
        "id": row.pk, "noaa_dcp": row.noaa_dcp_id,
        "dcp_address": row.noaa_dcp.dcp_address,
        "mode": row.mode, "status": row.status,
        "since_utc": row.since_utc.isoformat(),
        "until_utc": row.until_utc.isoformat(),
        "messages_received": row.messages_received,
        "station_deliveries": row.station_deliveries,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


class DCPForm(forms.ModelForm):
    class Meta:
        model = NoaaDcp
        fields = ("dcp_address", "first_channel", "first_channel_type",
                  "second_channel", "second_channel_type",
                  "first_transmission_time", "transmission_window",
                  "transmission_period")

    def clean_dcp_address(self):
        address = self.cleaned_data["dcp_address"].strip().upper()
        if not re.fullmatch(r"[0-9A-F]{8}", address):
            raise ValidationError("Enter exactly eight hexadecimal characters.")
        existing = NoaaDcp.objects.filter(dcp_address__iexact=address)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise ValidationError("This DCP address already exists.")
        return address

    def clean(self):
        data = super().clean()
        for name in ("first", "second"):
            channel, kind = data.get(f"{name}_channel"), data.get(f"{name}_channel_type")
            if (channel is None) != (kind is None):
                self.add_error(f"{name}_channel", "Supply both channel and transmission type, or neither.")
        return data


class AssociationForm(forms.ModelForm):
    # Interpret datetime-local form inputs using SURFACE's configured timezone.
    start_date = forms.CharField()
    end_date = forms.CharField(required=False)

    class Meta:
        model = NoaaDcpsStation
        fields = ("noaa_dcp", "station", "decoder", "interval", "format",
                  "start_date", "end_date")

    def clean_start_date(self):
        return parse_user_datetime(self.cleaned_data.get("start_date"), "Start date")

    def clean_end_date(self):
        return parse_user_datetime(self.cleaned_data.get("end_date"), "End date", required=False)

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if end and start and end <= start:
            self.add_error("end_date", "End date must be later than start date.")
        station, dcp = data.get("station"), data.get("noaa_dcp")
        if start and station and dcp and not (end and end <= start):
            # Two windows for the same station+DCP must not overlap; otherwise
            # a single raw message would be decoded twice into one station.
            overlapping = NoaaDcpsStation.objects.filter(station=station, noaa_dcp=dcp)
            if self.instance.pk:
                overlapping = overlapping.exclude(pk=self.instance.pk)
            overlapping = overlapping.filter(Q(end_date__isnull=True) | Q(end_date__gt=start))
            if end:
                overlapping = overlapping.filter(start_date__lt=end)
            if overlapping.exists():
                self.add_error("start_date", "This station already has an overlapping association for the DCP.")
        return data


class LRGSConfigurationForm(forms.ModelForm):
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = LRGSConfiguration
        fields = ("server_host", "server_port", "max_interval_hours", "username", "password")

    def clean_password(self):
        supplied = self.cleaned_data.get("password")
        if supplied:
            return supplied
        # For first-time save, retain the deployment-provided password without
        # exposing it in the browser; for edits, retain the saved password.
        if self.instance.pk and self.instance.password:
            return self.instance.password
        return str(settings.LRGS_PASSWORD)

    def clean_server_host(self):
        host = self.cleaned_data["server_host"].strip()
        if not host or any(ch.isspace() for ch in host) or any(c in host for c in "/\\@?#") or "://" in host:
            raise ValidationError("Enter a hostname/IP address, without a URL scheme or path.")
        return host


@wx_mapped_permission_required
@require_GET
def lrgs_references(request):
    """List labels/IDs for dropdowns; no sensitive settings included."""
    return JsonResponse({
        "stations": [{"id": x.pk, "name": str(x)} for x in Station.objects.all().order_by("pk")],
        "decoders": [{"id": x.pk, "name": str(x)} for x in Decoder.objects.all().order_by("pk")],
        "intervals": [{"id": x.pk, "name": str(x)} for x in Interval.objects.all().order_by("pk")],
        "formats": [{"id": x.pk, "name": str(x)} for x in Format.objects.all().order_by("pk")],
        "types": [{"id": x.pk, "name": str(x), "description": x.description}
                  for x in NoaaTransmissionType.objects.all().order_by("acronym")],
    })


@wx_mapped_permission_required
@require_GET
def lrgs_dcps_list(request):
    rows = NoaaDcp.objects.all().order_by("dcp_address", "pk")
    return JsonResponse({"results": [dcp_dict(row) for row in rows]})


@wx_mapped_permission_required
@csrf_protect
@require_POST
def lrgs_dcps_create(request):
    try:
        form = DCPForm(read_json(request))
    except ValueError as exc:
        return response_error(str(exc))
    if not form.is_valid():
        return form_errors(form)
    row = form.save()
    return JsonResponse({"result": dcp_dict(row)}, status=201)


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(["PATCH"])
def lrgs_dcp_update(request, pk):
    row = get_object_or_404(NoaaDcp, pk=pk)
    try:
        payload = read_json(request)
    except ValueError as exc:
        return response_error(str(exc))
    # PATCH with full clean() retains existing data for omitted fields.
    values = {key: payload.get(key, getattr(row, key + "_id") if key.endswith("_type")
                              else getattr(row, key)) for key in DCPForm.Meta.fields}
    form = DCPForm(values, instance=row)
    if not form.is_valid():
        return form_errors(form)
    row = form.save()
    return JsonResponse({"result": dcp_dict(row)})


@wx_mapped_permission_required
@csrf_protect
@require_POST
def lrgs_dcp_ssf_upload(request, pk):
    """Read .ssf into config_data without depending on model FileField.save()."""
    row = get_object_or_404(NoaaDcp, pk=pk)
    upload = request.FILES.get("file")
    if not upload or not upload.name.lower().endswith(".ssf"):
        return response_error("Select a .ssf configuration file.")
    if upload.size > 512 * 1024:
        return response_error("SSF file must be 512 KB or smaller.")
    try:
        contents = upload.read().decode("utf-8-sig")
    except UnicodeError:
        return response_error("SSF configuration must be UTF-8 text.")
    # QuerySet.update avoids the model's side-effectful save() that deletes the
    # original FileField when its name ends with .ssf.
    NoaaDcp.objects.filter(pk=row.pk).update(config_data=contents)
    return JsonResponse({"success": True, "size": len(contents)})


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(["DELETE"])
def lrgs_dcp_delete(request, pk):
    row = get_object_or_404(NoaaDcp, pk=pk)
    associations = NoaaDcpsStation.objects.filter(noaa_dcp=row).count()
    messages = DcpMessages.objects.filter(noaa_dcp=row).count()
    runs = LRGSIngestionRun.objects.filter(noaa_dcp=row).count()
    # Do not cascade or break historical records. Remove/migrate references
    # explicitly first; deleting a DCP with historical messages is prohibited.
    if associations or messages or runs:
        return response_error(
            f"Cannot delete DCP: {associations} station associations, "
            f"{messages} messages, and {runs} run records still reference it.", 409)
    row.delete()
    return JsonResponse({"success": True})


@wx_mapped_permission_required
@require_GET
def lrgs_dcp_config(request, pk):
    row = get_object_or_404(NoaaDcp, pk=pk)
    return JsonResponse({"config_data": row.config_data or ""})


@wx_mapped_permission_required
@require_GET
def lrgs_associations_list(request):
    rows = NoaaDcpsStation.objects.select_related("station", "noaa_dcp", "decoder", "interval", "format").order_by("noaa_dcp_id", "station_id", "pk")
    return JsonResponse({"results": [association_dict(row) for row in rows]})


@wx_mapped_permission_required
@csrf_protect
@require_POST
def lrgs_associations_create(request):
    try:
        form = AssociationForm(read_json(request))
    except ValueError as exc:
        return response_error(str(exc))
    if not form.is_valid():
        return form_errors(form)
    row = form.save()
    row = NoaaDcpsStation.objects.select_related("station", "noaa_dcp", "decoder", "interval", "format").get(pk=row.pk)
    return JsonResponse({"result": association_dict(row)}, status=201)


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(["PATCH"])
def lrgs_association_update(request, pk):
    row = get_object_or_404(NoaaDcpsStation, pk=pk)
    try:
        payload = read_json(request)
    except ValueError as exc:
        return response_error(str(exc))
    values = {key: payload.get(key, getattr(row, key + "_id") if key in
                              ("noaa_dcp", "station", "decoder", "interval", "format")
                              else getattr(row, key)) for key in AssociationForm.Meta.fields}
    form = AssociationForm(values, instance=row)
    if not form.is_valid():
        return form_errors(form)
    row = form.save()
    row = NoaaDcpsStation.objects.select_related("station", "noaa_dcp", "decoder", "interval", "format").get(pk=row.pk)
    return JsonResponse({"result": association_dict(row)})


@wx_mapped_permission_required
@csrf_protect
@require_http_methods(["DELETE"])
def lrgs_association_delete(request, pk):
    get_object_or_404(NoaaDcpsStation, pk=pk).delete()
    return JsonResponse({"success": True})


@wx_mapped_permission_required
@require_GET
def lrgs_messages_list(request):
    rows = DcpMessages.objects.select_related("noaa_dcp", "data_source").order_by("-datetime", "-pk")
    if request.GET.get("dcp"):
        try:
            rows = rows.filter(noaa_dcp_id=int(request.GET["dcp"]))
        except (ValueError, TypeError):
            return response_error("Invalid DCP filter.")
    if request.GET.get("search"):
        search = request.GET["search"].strip()[:80]
        # Avoid an unindexed payload-text scan across potentially huge LRGS
        # message tables. Search by indexed/short DCP address instead.
        rows = rows.filter(noaa_dcp__dcp_address__icontains=search)
    for key, lookup in (("from", "datetime__gte"), ("to", "datetime__lt")):
        if request.GET.get(key):
            try:
                value = parse_user_datetime(request.GET[key], key)
            except ValueError as exc:
                return response_error(str(exc))
            rows = rows.filter(**{lookup: value})
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        return response_error("Invalid page number.")
    size = 25
    batch = list(rows[(page - 1)*size: page*size + 1])
    return JsonResponse({"results": [message_dict(x) for x in batch[:size]],
                         "page": page, "has_next": len(batch) > size})


@wx_mapped_permission_required
@require_GET
def lrgs_message_detail(request, pk):
    row = get_object_or_404(DcpMessages.objects.select_related("noaa_dcp", "data_source"), pk=pk)
    return JsonResponse({"result": message_dict(row, include_payload=True)})


@wx_mapped_permission_required
@require_GET
def lrgs_settings_read(request):
    config = get_lrgs_settings()
    return JsonResponse({
        "server_host": config.host, "server_port": config.port,
        "max_interval_hours": config.max_interval_hours,
        "username": config.username,
        "has_password": bool(config.password),
        "is_saved": LRGSConfiguration.objects.filter(pk=1).exists(),
        "timezone_name": str(getattr(settings, "TIMEZONE_NAME", None) or settings.TIME_ZONE),
        "timezone_offset": getattr(settings, "TIMEZONE_OFFSET", None),
    })


@wx_mapped_permission_required
@csrf_protect
@require_POST
def lrgs_settings_update(request):
    try:
        data = read_json(request)
    except ValueError as exc:
        return response_error(str(exc))
    # Separate explicit confirmation for host/port/max-interval; these rarely
    # need changing and can disable all LRGS ingestion if edited accidentally.
    current = get_lrgs_settings()
    advanced_changed = any(str(data.get(key, getattr(current, field))) != str(getattr(current, field))
                           for key, field in (("server_host", "host"),
                                              ("server_port", "port"),
                                              ("max_interval_hours", "max_interval_hours")))
    if advanced_changed and data.get("confirm_advanced") != "CHANGE LRGS SERVER":
        return response_error("Advanced changes require typing CHANGE LRGS SERVER.")
    # Protect the saved password if someone changes the destination server.
    # A write-permitted user must supply the intended server's password rather
    # than silently sending our existing credential to a new host/port.
    server_changed = (str(data.get("server_host", current.host)) != str(current.host) or
                      str(data.get("server_port", current.port)) != str(current.port))
    if server_changed and not data.get("password"):
        return response_error("Enter a new password when changing the LRGS server host or port.")
    existing = LRGSConfiguration.objects.filter(pk=1).first()
    initial = {
        "server_host": current.host,
        "server_port": current.port,
        "max_interval_hours": current.max_interval_hours,
        "username": current.username,
        "password": "",
    }
    initial.update({key: value for key, value in data.items() if key in initial})
    form = LRGSConfigurationForm(initial, instance=existing)
    if not form.is_valid():
        return form_errors(form)
    with transaction.atomic():
        instance = form.save(commit=False)
        instance.pk = 1
        instance.save()
    return JsonResponse({"success": True})


@wx_mapped_permission_required
@csrf_protect
@require_POST
def lrgs_pull_create(request):
    """Enqueue a bounded asynchronous retrieval, never run it in gunicorn."""
    try:
        data = read_json(request)
        dcp = NoaaDcp.objects.get(pk=int(data["noaa_dcp"]))
        mode = str(data.get("mode", "recent"))
        if mode == "recent":
            hours = int(data.get("hours", 3))
            cap = get_lrgs_settings().max_interval_hours
            if not 1 <= hours <= cap:
                raise ValueError(f"Recent lookback must be between 1 and {cap} hours.")
            until = timezone.now().astimezone(pytz.UTC)
            since = until - dt.timedelta(hours=hours)
        elif mode == "historical":
            since = parse_user_datetime(data.get("from"), "Start date")
            until = parse_user_datetime(data.get("to"), "End date")
            if since >= until or (until - since) > dt.timedelta(days=30):
                raise ValueError("Choose a positive historical range of at most 30 days per request.")
            if until > timezone.now() + dt.timedelta(minutes=1):
                raise ValueError("Historical end time cannot be in the future.")
        else:
            raise ValueError("Invalid retrieval mode.")
    except NoaaDcp.DoesNotExist:
        return response_error("Unknown DCP.", 404)
    except (KeyError, TypeError, ValueError) as exc:
        return response_error(str(exc))

    try:
        with transaction.atomic():
            run = LRGSIngestionRun.objects.create(
                noaa_dcp=dcp, mode=mode, since_utc=since, until_utc=until,
                requested_by=request.user,
            )
    except IntegrityError:
        return response_error("This DCP already has a queued or running pull.", 409)

    from wx.lrgs_tasks import lrgs_pull_now_task
    try:
        # Keep manual network retrieval off the default summary/API workers.
        result = lrgs_pull_now_task.apply_async(
            args=[run.pk]
        )
        LRGSIngestionRun.objects.filter(pk=run.pk).update(celery_task_id=result.id)
    except Exception:
        LRGSIngestionRun.objects.filter(pk=run.pk).update(
            status="failed", finished_at=timezone.now(),
            error_message="Unable to enqueue the LRGS worker task.")
        return response_error("Could not queue the LRGS retrieval.", 503)
    return JsonResponse({"run_id": run.pk, "status": "queued"}, status=202)


@wx_mapped_permission_required
@require_GET
def lrgs_runs_list(request):
    rows = LRGSIngestionRun.objects.select_related("noaa_dcp").order_by("-created_at", "-pk")
    if request.GET.get("dcp"):
        try:
            rows = rows.filter(noaa_dcp_id=int(request.GET["dcp"]))
        except ValueError:
            return response_error("Invalid DCP filter.")
    return JsonResponse({"results": [run_dict(row) for row in rows[:50]]})


@wx_mapped_permission_required
@require_GET
def lrgs_run_detail(request, pk):
    run = get_object_or_404(LRGSIngestionRun.objects.select_related("noaa_dcp"), pk=pk)
    return JsonResponse({"result": run_dict(run)})
