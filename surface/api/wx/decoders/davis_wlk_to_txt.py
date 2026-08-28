#!/usr/bin/env python3
"""Decode Davis WeatherLink monthly .wlk files to a WeatherLink-style TSV text export.

The output intentionally follows the two-line/38-column layout used by classic
WeatherLink text exports. The binary reader supports WDAT5.x monthly files with
88-byte archive records.
"""

from __future__ import annotations

import logging
import math
import os
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("surface.davis")

HEADER_SIZE = 212
RECORD_SIZE = 88
DAY_COUNT = 32

# 88-byte WeatherLink archive record, explicitly little-endian and packed.
ARCHIVE_STRUCT = struct.Struct(
    "<4B"      # dataType, archiveInterval, iconFlags, moreFlags
    "8h"       # time, out/hi/low temp, in temp, barometer, out/in humidity
    "H"        # rain (collector code in upper bits + click count)
    "3h"       # hi rain rate, wind speed, hi wind speed
    "2B"       # wind direction, hi wind direction
    "3h"       # wind samples, solar rad, hi solar rad
    "2B"       # UV, hi UV
    "4B"       # leaf temperatures
    "h"        # extra radiation
    "6h"       # new sensors
    "2B"       # forecast, ET
    "6B"       # soil temperatures
    "6B"       # soil moisture
    "4B"       # leaf wetness
    "7B"       # extra temperatures
    "7B"       # extra humidities
)
assert ARCHIVE_STRUCT.size == RECORD_SIZE

TOP_HEADER = (
    "\t\tTemp\tHi\tLow\tOut\tDew\tWind\tWind\tWind\tHi\tHi\tWind\tHeat\tTHW\tTHSW"
    "\t\t\tRain\tSolar\tSolar\tHi Solar\tUV \tUV \tHi \tHeat\tCool\tIn \tIn\tIn \tIn \tIn \tIn Air"
    "\t\tWind\tWind\tISS \tArc."
)
BOTTOM_HEADER = (
    "Date\tTime\tOut\tTemp\tTemp\tHum\tPt.\tSpeed\tDir\tRun\tSpeed\tDir\tChill\tIndex\tIndex\tIndex"
    "\tBar  \tRain\tRate\tRad.\tEnergy\tRad. \tIndex\tDose\tUV \tD-D \tD-D \tTemp\tHum\tDew\tHeat"
    "\tEMC\tDensity\tET \tSamp\tTx \tRecept\tInt."
)

WIND_DIRS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)

# Davis rain collector code -> millimetres per tip/click.
RAIN_MM_PER_CLICK = {
    0x0000: 2.54,   # 0.1 inch
    0x1000: 0.254,  # 0.01 inch
    0x2000: 0.2,    # 0.2 mm
    0x3000: 1.0,    # 1.0 mm
    0x6000: 0.1,    # 0.1 mm
}

MISSING_SHORTS = {32767, -32768}


def f_to_c(value_f: float) -> float:
    return (value_f - 32.0) * 5.0 / 9.0


def c_to_f(value_c: float) -> float:
    return value_c * 9.0 / 5.0 + 32.0


def mph_to_kmh(value_mph: float) -> float:
    return value_mph * 1.609344


def inhg_to_hpa(value_inhg: float) -> float:
    return value_inhg * 33.8638866667


def dew_point_c(temp_c: Optional[float], rh: Optional[float]) -> Optional[float]:
    if temp_c is None or rh is None or rh <= 0:
        return None
    rh = min(rh, 100.0)
    # August-Roche-Magnus approximation.
    gamma = math.log(rh / 100.0) + (17.67 * temp_c) / (243.5 + temp_c)
    return (243.5 * gamma) / (17.67 - gamma)


def heat_index_f(temp_f: Optional[float], rh: Optional[float]) -> Optional[float]:
    if temp_f is None or rh is None:
        return None

    # NOAA/NWS simple estimate first.
    simple = 0.5 * (
        temp_f + 61.0 + (temp_f - 68.0) * 1.2 + rh * 0.094
    )
    simple = (simple + temp_f) / 2.0
    if simple < 80.0:
        return simple if temp_f >= 70.0 else temp_f

    t = temp_f
    r = rh
    hi = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * r
        - 0.22475541 * t * r
        - 0.00683783 * t * t
        - 0.05481717 * r * r
        + 0.00122874 * t * t * r
        + 0.00085282 * t * r * r
        - 0.00000199 * t * t * r * r
    )

    if r < 13 and 80 <= t <= 112:
        hi -= ((13 - r) / 4) * math.sqrt((17 - abs(t - 95.0)) / 17)
    elif r > 85 and 80 <= t <= 87:
        hi += ((r - 85) / 10) * ((87 - t) / 5)
    return hi


def wind_chill_f(temp_f: Optional[float], wind_mph: Optional[float]) -> Optional[float]:
    if temp_f is None or wind_mph is None:
        return None
    if temp_f > 40.0 or wind_mph <= 3.0:
        return temp_f
    v16 = wind_mph ** 0.16
    wc = 35.74 + 0.6215 * temp_f - 35.75 * v16 + 0.4275 * temp_f * v16
    return min(temp_f, wc)


def thw_index_c(
    temp_c: Optional[float], rh: Optional[float], wind_mph: Optional[float]
) -> Optional[float]:
    """Approximate Davis THW using heat index plus wind adjustment.

    Davis' desktop software can differ slightly because some derived indices are
    proprietary/version-dependent. This gives a stable reconstruction from the
    archive values present in the .wlk file.
    """
    if temp_c is None or rh is None or wind_mph is None:
        return None
    hi_f = heat_index_f(c_to_f(temp_c), rh)
    if hi_f is None:
        return None
    # Common WeatherLink-compatible approximation.
    return f_to_c(hi_f - 1.072 * max(wind_mph, 0.0))


def thsw_index_c(
    temp_c: Optional[float], rh: Optional[float], wind_mph: Optional[float], solar_wm2: Optional[float]
) -> Optional[float]:
    if temp_c is None or rh is None or wind_mph is None or solar_wm2 is None:
        return None
    wind_ms = wind_mph * 0.44704
    e = (rh / 100.0) * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    qd = solar_wm2 * 0.25
    q2 = qd / 7.0
    q3 = solar_wm2 / 28.0
    q = q2 + q3
    return temp_c + 0.348 * e - 0.70 * wind_ms + (0.70 * q / (wind_ms + 10.0)) - 4.25


def equilibrium_moisture_content(temp_f: Optional[float], rh: Optional[float]) -> Optional[float]:
    """Hailwood-Horrobin EMC (%) used for the WeatherLink-style In EMC column."""
    if temp_f is None or rh is None:
        return None
    h = min(max(rh / 100.0, 0.0), 1.0)
    t = temp_f
    w = 330.0 + 0.452 * t + 0.00415 * t * t
    k = 0.791 + 0.000463 * t - 0.000000844 * t * t
    k1 = 6.34 + 0.000775 * t - 0.0000935 * t * t
    k2 = 1.09 + 0.0284 * t - 0.0000904 * t * t
    kh = k * h
    denom = 1.0 + k1 * kh + k1 * k2 * kh * kh
    if abs(1.0 - kh) < 1e-12 or abs(denom) < 1e-12:
        return None
    return (1800.0 / w) * (
        kh / (1.0 - kh)
        + (k1 * kh + 2.0 * k1 * k2 * kh * kh) / denom
    )


def air_density_kg_m3(
    temp_c: Optional[float], rh: Optional[float], sea_level_hpa: Optional[float], altitude_m: float
) -> Optional[float]:
    """Estimate moist-air density, optionally correcting sea-level pressure for altitude."""
    if temp_c is None or rh is None or sea_level_hpa is None or sea_level_hpa <= 0:
        return None

    # Convert WeatherLink's sea-level pressure to approximate station pressure.
    if altitude_m:
        base = 1.0 - 2.25577e-5 * altitude_m
        if base <= 0:
            return None
        pressure_hpa = sea_level_hpa * (base ** 5.25588)
    else:
        pressure_hpa = sea_level_hpa

    # Partial-pressure form of the ideal gas law for moist air.
    sat_vapor_hpa = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
    vapor_hpa = min(max(rh / 100.0, 0.0), 1.0) * sat_vapor_hpa
    dry_hpa = pressure_hpa - vapor_hpa
    tk = temp_c + 273.15
    return (dry_hpa * 100.0) / (287.05 * tk) + (vapor_hpa * 100.0) / (461.495 * tk)


def fmt(value: Optional[float], decimals: int, *, zero_as_int: bool = False) -> str:
    if value is None or not math.isfinite(value):
        return "---"
    if zero_as_int and abs(value) < 0.0000001:
        return "0"
    return f"{value:.{decimals}f}"


def fmt_int(value: Optional[float]) -> str:
    if value is None or not math.isfinite(value):
        return "---"
    return str(int(round(value)))


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%m/%d/%y")


def fmt_time(dt: datetime) -> str:
    hour = dt.hour
    suffix = "a" if hour < 12 else "p"
    h12 = hour % 12 or 12
    return f"{h12}:{dt.minute:02d} {suffix}"


def decode_temp(raw: int) -> Optional[float]:
    if raw in MISSING_SHORTS:
        return None
    return f_to_c(raw / 10.0)


def decode_humidity(raw: int) -> Optional[float]:
    if raw in MISSING_SHORTS or raw == 255 or raw < 0:
        return None
    return raw / 10.0


def decode_baro(raw: int) -> Optional[float]:
    if raw in MISSING_SHORTS or raw <= 0:
        return None
    return inhg_to_hpa(raw / 1000.0)


def decode_wind(raw: int) -> Optional[float]:
    if raw in MISSING_SHORTS or raw == 255 or raw < 0:
        return None
    return raw / 10.0  # mph


def decode_solar(raw: int) -> Optional[float]:
    if raw in MISSING_SHORTS or raw < 0:
        return None
    return float(raw)


def decode_uv(raw: int) -> Optional[float]:
    if raw == 255:
        return None
    return raw / 10.0


def decode_direction(raw: int) -> str:
    return WIND_DIRS[raw] if 0 <= raw < 16 else "---"


def decode_rain(raw: int) -> tuple[Optional[float], Optional[float]]:
    collector = raw & 0xF000
    clicks = raw & 0x0FFF
    mm_per_click = RAIN_MM_PER_CLICK.get(collector)
    if mm_per_click is None:
        return None, None
    return clicks * mm_per_click, mm_per_click


@dataclass
class ArchiveRecord:
    dt: datetime
    interval_min: int
    more_flags: int
    outside_temp_c: Optional[float]
    hi_temp_c: Optional[float]
    low_temp_c: Optional[float]
    inside_temp_c: Optional[float]
    barometer_hpa: Optional[float]
    outside_hum: Optional[float]
    inside_hum: Optional[float]
    rain_mm: Optional[float]
    rain_mm_per_click: Optional[float]
    hi_rain_rate_raw: int
    wind_mph: Optional[float]
    hi_wind_mph: Optional[float]
    wind_dir: str
    hi_wind_dir: str
    wind_samples: Optional[int]
    solar_wm2: Optional[float]
    hi_solar_wm2: Optional[float]
    uv: Optional[float]
    hi_uv: Optional[float]
    et_mm: Optional[float]

    def as_weatherlink_row(self, altitude_m: float = 0.0) -> list[str]:
        t = self.outside_temp_c
        rh = self.outside_hum
        in_t = self.inside_temp_c
        in_rh = self.inside_hum
        interval_hr = self.interval_min / 60.0

        dew = dew_point_c(t, rh)
        wind_kmh = None if self.wind_mph is None else mph_to_kmh(self.wind_mph)
        hi_wind_kmh = None if self.hi_wind_mph is None else mph_to_kmh(self.hi_wind_mph)
        wind_run_km = None if self.wind_mph is None else mph_to_kmh(self.wind_mph) * interval_hr

        wc_f = wind_chill_f(None if t is None else c_to_f(t), self.wind_mph)
        wc_c = None if wc_f is None else f_to_c(wc_f)

        hi_f = heat_index_f(None if t is None else c_to_f(t), rh)
        hi_c = None if hi_f is None else f_to_c(hi_f)
        thw_c = thw_index_c(t, rh, self.wind_mph)
        thsw_c = thsw_index_c(t, rh, self.wind_mph, self.solar_wm2)

        rain_rate = None
        if self.rain_mm_per_click is not None and self.hi_rain_rate_raw not in MISSING_SHORTS:
            rain_rate = max(0, self.hi_rain_rate_raw) * self.rain_mm_per_click

        solar_energy = None
        if self.solar_wm2 is not None:
            # W/m² * seconds -> J/m²; 1 Langley = 41,840 J/m².
            solar_energy = self.solar_wm2 * self.interval_min * 60.0 / 41840.0

        uv_dose = None
        if self.uv is not None:
            # Approximate MED dose used by classic WeatherLink exports.
            uv_dose = self.uv * interval_hr * (90.0 / 210.0)

        heat_dd = cool_dd = None
        if t is not None:
            base_c = f_to_c(65.0)
            dd = (t - base_c) * (self.interval_min / 1440.0)
            heat_dd = max(0.0, -dd)
            cool_dd = max(0.0, dd)

        in_dew = dew_point_c(in_t, in_rh)
        in_hi_f = heat_index_f(None if in_t is None else c_to_f(in_t), in_rh)
        in_hi_c = None if in_hi_f is None else f_to_c(in_hi_f)
        in_emc = equilibrium_moisture_content(None if in_t is None else c_to_f(in_t), in_rh)
        density = air_density_kg_m3(in_t, in_rh, self.barometer_hpa, altitude_m)

        tx = (self.more_flags & 0x07) + 1
        recept = None
        if self.wind_samples is not None and self.interval_min > 0:
            # WeatherLink stations send about 24 packets/min; classic exports use
            # an effective expected sample count of ~22.8/min for reception %.
            recept = min(100.0, self.wind_samples / (self.interval_min * 22.8) * 100.0)

        return [
            fmt_date(self.dt),
            fmt_time(self.dt),
            fmt(t, 1),
            fmt(self.hi_temp_c, 1),
            fmt(self.low_temp_c, 1),
            fmt_int(rh),
            fmt(dew, 1),
            fmt(wind_kmh, 1),
            self.wind_dir,
            fmt(wind_run_km, 2),
            fmt(hi_wind_kmh, 1),
            self.hi_wind_dir,
            fmt(wc_c, 1),
            fmt(hi_c, 1),
            fmt(thw_c, 1),
            fmt(thsw_c, 1),
            fmt(self.barometer_hpa, 1),
            fmt(self.rain_mm, 2),
            fmt(rain_rate, 1),
            fmt(self.solar_wm2, 0, zero_as_int=True),
            fmt(solar_energy, 2),
            fmt(self.hi_solar_wm2, 0, zero_as_int=True),
            fmt(self.uv, 1),
            fmt(uv_dose, 2),
            fmt(self.hi_uv, 1),
            fmt(heat_dd, 3),
            fmt(cool_dd, 3),
            fmt(in_t, 1),
            fmt_int(in_rh),
            fmt(in_dew, 1),
            fmt(in_hi_c, 1),
            fmt(in_emc, 2),
            fmt(density, 4),
            fmt(self.et_mm, 2),
            "---" if self.wind_samples is None else str(self.wind_samples),
            str(tx),
            fmt(recept, 1),
            str(self.interval_min),
        ]


def parse_davis_filename(file_name: str | Path) -> tuple[int, int, str]:
    """Validate and parse a Davis metadata filename.

    Expected format: ``davis_stationCode_YYYY-MM.wlk`` or
    ``davis_stationCode_YYYY-MM.txt``.

    The filename is used only to determine the station code, year, and month.
    It does not need to refer to the actual file being converted.
    """
    name = Path(file_name).name
    logger.info("Davis filename being validated: %r", name)

    match = re.fullmatch(
        r"davis_(?P<station>[A-Za-z0-9-]+)_(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])\.(?:wlk|txt)",
        name,
        re.IGNORECASE,
    )

    if not match:
        raise ValueError(
            "Invalid filename. Expected davis_code_YYYY-MM.wlk or "
            "davis_code_YYYY-MM.txt "
            "(for example: davis_321_2013-01.wlk)."
        )

    return (
        int(match.group("year")),
        int(match.group("month")),
        match.group("station"),
    )

def parse_archive(raw: bytes, base_date: datetime) -> Optional[ArchiveRecord]:
    if len(raw) != RECORD_SIZE:
        raise ValueError(f"Archive record must be {RECORD_SIZE} bytes, got {len(raw)}")
    x = ARCHIVE_STRUCT.unpack(raw)

    data_type, interval, _icon_flags, more_flags = x[0:4]
    if data_type != 1:
        return None

    packed_time = x[4]
    if packed_time < 0 or packed_time > 1440:
        return None
    dt = base_date + timedelta(minutes=packed_time)

    out_t, hi_t, low_t, in_t = map(decode_temp, x[5:9])
    baro = decode_baro(x[9])
    out_hum, in_hum = map(decode_humidity, x[10:12])

    rain_mm, mm_per_click = decode_rain(x[12])
    hi_rain_rate_raw = x[13]
    wind_mph = decode_wind(x[14])
    hi_wind_mph = decode_wind(x[15])
    wind_dir = decode_direction(x[16])
    hi_wind_dir = decode_direction(x[17])
    wind_samples = None if x[18] in MISSING_SHORTS or x[18] < 0 else x[18]
    solar = decode_solar(x[19])
    hi_solar = decode_solar(x[20])
    uv = decode_uv(x[21])
    hi_uv = decode_uv(x[22])

    # After 4 leaf temp bytes, extra radiation, 6 new sensor shorts:
    # forecast is index 34 and ET is index 35.
    et_raw = x[35]
    et_mm = None if et_raw == 255 else et_raw * 0.001 * 25.4

    return ArchiveRecord(
        dt=dt,
        interval_min=interval,
        more_flags=more_flags,
        outside_temp_c=out_t,
        hi_temp_c=hi_t,
        low_temp_c=low_t,
        inside_temp_c=in_t,
        barometer_hpa=baro,
        outside_hum=out_hum,
        inside_hum=in_hum,
        rain_mm=rain_mm,
        rain_mm_per_click=mm_per_click,
        hi_rain_rate_raw=hi_rain_rate_raw,
        wind_mph=wind_mph,
        hi_wind_mph=hi_wind_mph,
        wind_dir=wind_dir,
        hi_wind_dir=hi_wind_dir,
        wind_samples=wind_samples,
        solar_wm2=solar,
        hi_solar_wm2=hi_solar,
        uv=uv,
        hi_uv=hi_uv,
        et_mm=et_mm,
    )


def read_wlk(path: Path, year: int, month: int) -> list[ArchiveRecord]:
    blob = path.read_bytes()
    if len(blob) < HEADER_SIZE:
        raise ValueError("File is too small to be a WeatherLink .wlk database")

    id_code = blob[:16]
    if not id_code.startswith(b"WDAT"):
        raise ValueError(f"Unsupported WeatherLink header: {id_code!r}")

    total_records = struct.unpack_from("<I", blob, 16)[0]
    expected_size = HEADER_SIZE + total_records * RECORD_SIZE
    if len(blob) < expected_size:
        raise ValueError(
            f"Truncated .wlk: header says {total_records} records ({expected_size} bytes), "
            f"file has {len(blob)} bytes"
        )

    day_indexes = [
        struct.unpack_from("<hI", blob, 20 + i * 6) for i in range(DAY_COUNT)
    ]

    out: list[ArchiveRecord] = []
    for day in range(1, 32):
        count, start_pos = day_indexes[day]
        if count <= 2:
            continue
        try:
            base_date = datetime(year, month, day)
        except ValueError:
            continue

        # Every populated day starts with two 88-byte daily summary records.
        for record_index in range(start_pos + 2, start_pos + count):
            if record_index >= total_records:
                raise ValueError(
                    f"Day {day} points beyond total record count ({record_index} >= {total_records})"
                )
            offset = HEADER_SIZE + record_index * RECORD_SIZE
            rec = parse_archive(blob[offset : offset + RECORD_SIZE], base_date)
            if rec is not None:
                out.append(rec)

    out.sort(key=lambda r: r.dt)
    return out


def write_weatherlink_text(records: Iterable[ArchiveRecord], output: Path, altitude_m: float = 0.0) -> None:
    with output.open("w", encoding="utf-8", newline="\n") as f:
        f.write(TOP_HEADER + "\n")
        f.write(BOTTOM_HEADER + "\n")
        for record in records:
            row = record.as_weatherlink_row(altitude_m=altitude_m)
            if len(row) != 38:
                raise AssertionError(f"Expected 38 columns, got {len(row)}")
            f.write("\t".join(row) + "\n")


def decode_wlk_file(
    file_path: str | Path,
    file_name: str | Path | None = None,
    altitude_m: float = 0.0,
) -> bool:
    """Convert one Davis .wlk file in place and remove the source on success.

    ``file_path`` is the actual .wlk file being converted.

    ``file_name`` is optional metadata used to obtain the station code, year,
    and month. When omitted, the filename from ``file_path`` is used instead.

    The output always uses the actual ``file_path`` and changes only its
    extension from ``.wlk`` to ``.txt``.

    Example:
        file_path = /tmp/upload_123.wlk
        file_name = davis_321_2013-01.wlk

        metadata  -> station 321, January 2013
        output    -> /tmp/upload_123.txt

    Returns ``True`` on successful conversion.
    Raises an exception if validation or conversion fails.
    ## ***No longer true: The original .wlk is deleted only after the .txt has been written successfully.***
    """
    input_path = Path(file_path)

    if input_path.suffix.lower() != ".wlk":
        logger.error("Davis decoder received a non-WLK file: %s", input_path)
        raise ValueError(f"Davis decoder received a non-WLK file: {input_path}")

    if not input_path.is_file():
        logger.error("Davis WLK file does not exist: %s", input_path)
        raise FileNotFoundError(f"Davis WLK file does not exist: {input_path}")

    metadata_name = file_name if file_name is not None else input_path.name

    try:
        year, month, station_code = parse_davis_filename(metadata_name)
    except ValueError:
        logger.exception("Invalid Davis filename: %s", metadata_name)
        raise

    # The output location/name is based only on the actual input path.
    output_path = input_path.with_suffix(".txt")
    temp_output = output_path.with_name(output_path.name + ".tmp")

    try:
        records = read_wlk(input_path, year, month)
        write_weatherlink_text(records, temp_output, altitude_m=altitude_m)

        # Publish the completed text file atomically, then remove the source.
        os.replace(temp_output, output_path)

        # to remove the orginal .wlk and leave the .txt
        # input_path.unlink()

        logger.info(
            "Successfully decoded Davis WLK file for station %s: %s -> %s (%d records)",
            station_code,
            input_path,
            output_path,
            len(records),
        )
        return True

    except Exception:
        # Never leave a partial temporary export behind. The source .wlk remains.
        try:
            temp_output.unlink(missing_ok=True)
        except OSError:
            pass

        logger.exception("Failed to decode Davis WLK file: %s", input_path)
        raise


def main(file_path: str | Path, file_name: str | Path | None = None) -> bool:
    """Decode a Davis WLK file using optional filename metadata."""
    return decode_wlk_file(file_path, file_name=file_name)
