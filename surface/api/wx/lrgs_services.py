"""LRGS retrieval helpers. No Celery imports here, so services are unit-testable."""

import contextlib
import datetime as dt
import ipaddress
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytz
from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from wx.models import LRGSConfiguration, NoaaDcpsStation

log = logging.getLogger(__name__)
UTC = pytz.UTC
HEADER_RE = re.compile(rb"^[0-9a-fA-F]{8}[0-9]{11}.{13}[0-9]{5}$", re.DOTALL)
DCP_RE = re.compile(r"^[0-9a-fA-F]{8}$")
# Limit the size of one LRGS subprocess result so a large backfill cannot exhaust
# the Celery worker. Adjust for the actual operational message volume if needed.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class LRGSSettings:
    host: str
    port: int
    username: str
    password: str
    max_interval_hours: int


def get_lrgs_settings():
    """Read settings from DB each call so Celery workers need no restart.

    Initially use the existing settings / environment variables. A saved singleton
    overrides *all* fields; a partially populated configuration is not allowed.
    """
    item = LRGSConfiguration.objects.filter(pk=1).first()
    if item:
        return LRGSSettings(item.server_host, item.server_port, item.username,
                            item.password, item.max_interval_hours)
    return LRGSSettings(
        host=str(settings.LRGS_SERVER_HOST),
        port=int(settings.LRGS_SERVER_PORT),
        username=str(settings.LRGS_USER),
        password=str(settings.LRGS_PASSWORD),
        max_interval_hours=int(settings.LRGS_MAX_INTERVAL),
    )


def lrgs_abs_time(value):
    """The LRGS absolute GMT format is YYYY/DDD HH:MM:SS (DDD=day-of-year)."""
    value = value.astimezone(UTC)
    return value.strftime("%Y/%j %H:%M:%S")


def search_criteria(dcp_address, start, end, first_channel=None):
    """Build a bounded UTC query with validated DCP/channel parameters."""
    if not DCP_RE.fullmatch(dcp_address):
        raise ValueError("DCP address must contain exactly eight hexadecimal characters.")
    if not (timezone.is_aware(start) and timezone.is_aware(end) and start < end):
        raise ValueError("Invalid UTC retrieval window.")
    lines = [f"DRS_SINCE: {lrgs_abs_time(start)}",
             f"DRS_UNTIL: {lrgs_abs_time(end)}",
             f"DCP_ADDRESS: {dcp_address.upper()}"]
    if first_channel is not None:
        channel = int(first_channel)
        if channel < 0 or channel > 999:
            raise ValueError("Invalid DCP receive channel.")
        # Match the channel syntax already used by SURFACE; if you find that
        # a specific LRGS version expects only 'CHANNEL: 123', adjust here.
        lines.append(f"CHANNEL: |{channel}")
    return "\n".join(lines) + "\n"


def iter_utc_windows(start, end, max_hours):
    """Small windows keep memory/response sizes bounded for historical pulls."""
    chunk = dt.timedelta(hours=min(max(1, int(max_hours)), 24))
    while start < end:
        next_end = min(start + chunk, end)
        yield start, next_end
        start = next_end


@dataclass(frozen=True)
class ReceivedMessage:
    timestamp: dt.datetime
    raw: bytes


def split_lrgs_messages(output: bytes) -> Iterator[ReceivedMessage]:
    """Decode LRGS 37-byte headers + length-delimited payloads.

    The default getDcpMessages output consists of consecutive messages. Each
    header carries a five-digit byte length at positions 32..36. Do not guess
    a boundary by splitting on newlines: payloads may contain newlines.

    Fail CLOSED if the output is malformed instead of sending unfiltered data
    to station decoders; doing otherwise could violate association date rules.
    Confirm against sample output from the deployed LRGS client before rollout.
    """
    pos = 0
    while pos < len(output):
        # A CR/LF separator is allowed between records, but never removed
        # from within a payload because we skip only at a header boundary.
        while pos < len(output) and output[pos:pos+1] in (b"\n", b"\r"):
            pos += 1
        if pos == len(output):
            break
        header = output[pos:pos+37]
        if len(header) != 37 or not HEADER_RE.fullmatch(header):
            raise ValueError(f"Invalid LRGS message header at byte {pos}.")
        try:
            received = UTC.localize(dt.datetime.strptime(
                header[8:19].decode("ascii"), "%y%j%H%M%S"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Invalid received timestamp in LRGS header.") from exc
        length = int(header[32:37])
        payload_end = pos + 37 + length
        if payload_end > len(output):
            raise ValueError("Truncated LRGS payload; refusing partial routing.")
        yield ReceivedMessage(timestamp=received, raw=output[pos:payload_end])
        pos = payload_end


def applicable_associations(dcp, received):
    """Route by *message receive time* rather than worker execution time."""
    from django.db.models import Q
    return list(NoaaDcpsStation.objects.select_related("station", "decoder").filter(
        noaa_dcp=dcp, start_date__lte=received
    ).filter(Q(end_date__isnull=True) | Q(end_date__gt=received)))


@contextlib.contextmanager
def dcp_advisory_lock(dcp_id):
    """Session-level PostgreSQL lock excludes concurrent scheduled/manual pulls.

    Do not hold a DB transaction open during the network call. The lock uses a
    reserved integer namespace and is always released before a worker exits.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [82611, dcp_id])
        locked = cursor.fetchone()[0]
    try:
        yield bool(locked)
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [82611, dcp_id])


def retrieve_raw_messages(dcp, start, end):
    """Use an isolated .sc file; never share LRGS_CS_FILE_PATH across tasks.

    The password is a command-line argument because that is how the existing
    LRGS client is invoked. Never log argv, stdout/stderr or the password.
    Operators should restrict who can inspect process command lines.
    """
    config = get_lrgs_settings()
    criteria = search_criteria(dcp.dcp_address, start, end, dcp.first_channel)
    exe = str(settings.LRGS_EXECUTABLE_PATH)
    timeout_seconds = int(getattr(settings, "LRGS_PULL_TIMEOUT_SECONDS", 180))

    with tempfile.TemporaryDirectory(prefix="surface_lrgs_") as directory:
        criteria_file = Path(directory) / "request.sc"
        criteria_file.write_text(criteria, encoding="ascii")
        # Sensitive downloaded data is stored on disk only for this request.
        output_file = Path(directory) / "output.bin"
        args = [exe, "-h", config.host, "-p", str(config.port), "-u",
                config.username, "-P", config.password, "-f", str(criteria_file)]
        try:
            with output_file.open("wb") as out:
                result = subprocess.run(args, shell=False, stdout=out,
                                        stderr=subprocess.PIPE,
                                        timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("LRGS pull timed out.") from exc
        except OSError as exc:
            raise RuntimeError("LRGS client executable could not be started.") from exc
        if result.returncode != 0:
            # Do not show raw stderr: the external program may echo credentials.
            raise RuntimeError(f"LRGS client exited with code {result.returncode}.")
        if output_file.stat().st_size > MAX_RESPONSE_BYTES:
            raise RuntimeError("LRGS response exceeded the configured 64 MB safety limit.")
        return output_file.read_bytes()


def run_retrieval_for_dcp(dcp, since_utc, until_utc, decoder_lookup):
    """Pull each DCP once and fan out messages to all matching stations.

    decoder_lookup maps decoder names to the existing SURFACE decoding funcs
    (read_data_nesa, read_data_sat_tx325). Their existing five-argument
    signatures are retained. A station receives only the concatenated original
    records whose *receive times* fall within its association date window.

    WARNING: Verify those decoding funcs are idempotent about inserting
    DcpMessages when called for multiple stations. If they insert one raw
    message per station, move raw persistence outside the decoder first.
    """
    message_count = 0
    deliveries = 0
    failures = []
    # Load candidate associations ONCE for the entire retrieval; one database
    # query per message would be prohibitively slow for large 30-day backfills.
    associations = list(NoaaDcpsStation.objects.select_related("station", "decoder").filter(
        noaa_dcp=dcp, start_date__lt=until_utc
    ).filter(Q(end_date__isnull=True) | Q(end_date__gt=since_utc)))

    for start, end in iter_utc_windows(
        since_utc, until_utc, get_lrgs_settings().max_interval_hours
    ):
        raw = retrieve_raw_messages(dcp, start, end)
        # Parse each entire chunk before invoking any decoder. A malformed
        # header must never lead to partial or misrouted data processing.
        messages = list(split_lrgs_messages(raw))
        message_count += len(messages)

        # Scope aggregated decoder input to ONE 24-hour-or-smaller chunk, not
        # the full historical period. This prevents 30-day backfills from
        # holding all downloaded data in worker RAM at once.
        by_association = {}
        for message in messages:
            for association in associations:
                if not (association.start_date <= message.timestamp and
                        (association.end_date is None or message.timestamp < association.end_date)):
                    continue
                if association.pk not in by_association:
                    by_association[association.pk] = [association, bytearray(), 0]
                by_association[association.pk][1].extend(message.raw)
                by_association[association.pk][2] += 1

        for association, payload, matching_messages in by_association.values():
            decoder = decoder_lookup.get(association.decoder.name)
            if decoder is None:
                failures.append(f"No supported decoder: {association.decoder.name} (association {association.pk}).")
                continue
            try:
                # Existing decoder API expects ASCII response + stderr bytes.
                decoder(association.station_id, dcp.dcp_address, dcp.config_data or "",
                        bytes(payload).decode("ascii"), b"")
                # Count the messages delivered to station decoders, NOT the
                # number of raw DCP messages (which is counted separately).
                deliveries += matching_messages
            except Exception as exc:
                # Deliberately do not log exception text: decoder exceptions
                # may contain raw payload data or embedded credentials.
                log.error("LRGS decoder failed for association id=%s (%s)",
                          association.pk, type(exc).__name__)
                failures.append(f"Decoder failed for association {association.pk}.")
    return message_count, deliveries, failures
