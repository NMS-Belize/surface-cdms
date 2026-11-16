"""Manual and scheduled LRGS task adapters.

Import this module at the END of wx/tasks.py so Celery discovers the shared_task
and existing read_data_nesa/read_data_sat_tx325 implementations remain intact.
"""

import datetime as dt
import logging

import pytz
from celery import shared_task
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from wx.models import LRGSIngestionRun, NoaaDcpsStation
from wx.lrgs_services import (dcp_advisory_lock, get_lrgs_settings,
                              run_retrieval_for_dcp)

logger = logging.getLogger(__name__)


def _decoder_map():
    """Import lazily to avoid circular imports with wx.tasks at startup."""
    from wx import tasks
    return {"NESA": tasks.read_data_nesa, "SAT_TX325": tasks.read_data_sat_tx325}


def process_lrgs_run(run_id):
    run = LRGSIngestionRun.objects.select_related("noaa_dcp").get(pk=run_id)
    dcp = run.noaa_dcp
    with dcp_advisory_lock(dcp.pk) as locked:
        if not locked:
            LRGSIngestionRun.objects.filter(pk=run.pk).update(
                status="skipped", finished_at=timezone.now(),
                error_message="Another pull is already using this DCP.")
            return
        LRGSIngestionRun.objects.filter(pk=run.pk).update(
            status="running", started_at=timezone.now(), error_message="")
        try:
            messages, deliveries, failures = run_retrieval_for_dcp(
                dcp, run.since_utc, run.until_utc, _decoder_map()
            )
        except Exception as exc:
            # Never log the shell argv (contains password) or raw payload. The
            # service raises intentionally sanitized operational errors.
            logger.error("LRGS pull failed for run id=%s, DCP id=%s (%s)",
                         run.pk, dcp.pk, type(exc).__name__)
            LRGSIngestionRun.objects.filter(pk=run.pk).update(
                status="failed", finished_at=timezone.now(),
                error_message="LRGS retrieval failed; check worker logs.")
            return
        status = "partial" if failures else "success"
        LRGSIngestionRun.objects.filter(pk=run.pk).update(
            status=status, finished_at=timezone.now(),
            messages_received=messages, station_deliveries=deliveries,
            error_message=" ".join(failures)[:2000]
        )


@shared_task(name="wx.tasks.lrgs_pull_now_task")
def lrgs_pull_now_task(run_id):
    """Executed asynchronously by the existing Celery worker."""
    process_lrgs_run(run_id)


def retrieve_dcp_messages_updated(noaa_dict):
    """Drop-in replacement for the old synchronous retrieve_dcp_messages().

    Keep the current dcp_tasks_scheduler() and its beat interval unchanged.
    This adapter computes its established 3h minimum / configured maximum
    automatic window. It uses exactly the same fan-out and database lock as
    manual Pull Now, preventing collisions and shared criteria-file races.

    NoaaDcp.last_datetime remains 'last scheduled ATTEMPT' in the existing
    scheduler. Successful versus failed retrievals are tracked in Run History.
    """
    dcp = noaa_dict["noaa_object"]
    last = noaa_dict.get("last_execution")
    now = timezone.now().astimezone(pytz.UTC)
    # start_date/end_date control whether automated ingestion should run NOW.
    # Historical manual pulls intentionally ignore this 'current activity' test
    # and instead route each message by its original receive timestamp.
    active = NoaaDcpsStation.objects.filter(
        noaa_dcp=dcp, start_date__lte=now
    ).filter(Q(end_date__isnull=True) | Q(end_date__gt=now)).exists()
    if not active:
        logger.info("Skipping scheduled LRGS pull for DCP id=%s: no currently active station association", dcp.pk)
        return
    cap = get_lrgs_settings().max_interval_hours
    if last is None:
        hours = cap
    else:
        hours = max(3, min(int((now - last).total_seconds() / 3600), cap))
    try:
        with transaction.atomic():
            run = LRGSIngestionRun.objects.create(
                noaa_dcp=dcp, mode="scheduled",
                since_utc=now - dt.timedelta(hours=hours), until_utc=now,
            )
    except IntegrityError:
        logger.info("Skipping scheduled pull for DCP id=%s: pull already pending", dcp.pk)
        return
    process_lrgs_run(run.pk)
