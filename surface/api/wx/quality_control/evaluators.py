from datetime import datetime, timedelta
from math import isnan

from django.conf import settings

from wx.enums import QualityFlagEnum


from wx.quality_control.helpers import get_min_max_measured, get_prev_measured

# ---------------------------------------------------------------------
# Quality Flag Shortcuts
# ---------------------------------------------------------------------
# These store the integer ID values used throughout the QC system.
GOOD = QualityFlagEnum.GOOD.id
NOT_CHECKED = QualityFlagEnum.NOT_CHECKED.id
BAD = QualityFlagEnum.BAD.id
SUSPICIOUS = QualityFlagEnum.SUSPICIOUS.id


# ---------------------------------------------------------------------
# STEP QC EVALUATION
# ---------------------------------------------------------------------
def evaluate_step_qc(
    value: float,
    thresholds: dict,
    data_batch: list,
    row_datetime_utc: datetime,
    station_id: int,
    variable_id: int,
    previous_db_record=None,
):
    """
        Evaluates whether a measured value is within allowed step thresholds.

        Rules:
        - Thresholds are only valid if BOTH min and max exist
        - Half-filled thresholds are ignored
        - BAD if global fails
        - SUSPICIOUS if global passes but custom is missing or fail
        - SUSPICIOUS if global passes but reference is missing or fail
        - GOOD only if all three exist and pass

        Note:
        - The global step is mandatory or it defaults to NOT CHECKED
    """

    descriptions = [thresholds.get("step_description", "Unknown threshold")]

    if value == settings.MISSING_VALUE:
        descriptions.append(f"Missing Value, step check failed!")

        return BAD, " || ".join(descriptions)
    
    # getting the diff value
    prev_measured = None
    diff_value = None

    for data_row in data_batch:
        if data_row['datetime'] == row_datetime_utc:
            break

        if data_row['measured'] != settings.MISSING_VALUE:
            prev_measured = data_row['measured']

    # confirm that there is a valid previous number
    if prev_measured is not None:
        diff_value = float(value) - float(prev_measured)
    # retrieve required number to calculate diff_value from the DB
    else:
        # Optimized path: use preloaded previous value if provided.
        # Backwards-compatible path: query DB only if nothing was preloaded.
        if previous_db_record is not None:
            diff_value_date, prev_measured = previous_db_record
        else:
            diff_value_date, prev_measured = get_prev_measured(
                row_datetime_utc,
                station_id,
                variable_id,
            )

        if prev_measured == settings.MISSING_VALUE:
            diff_value = None
        elif prev_measured is not None:
            diff_value = round(float(value) - float(prev_measured), 3)

    # Get the threshold rande
    def get_step(prefix):
        min_key = f"{prefix}_step_min"
        max_key = f"{prefix}_step_max"
        if min_key in thresholds and max_key in thresholds:
            return thresholds[min_key], thresholds[max_key]
        return None

    glob_step = get_step("glob")
    ref_step  = get_step("ref")
    cus_step  = get_step("cus")

    # ------------------------------------------------------------
    # No thresholds at all
    # ------------------------------------------------------------
    if not any([glob_step, ref_step, cus_step]):
        descriptions.append("No Thresholds To Check!")

        return NOT_CHECKED, " || ".join(descriptions)

    descriptions.append(f"This is the diff_value: {diff_value}. This is the current measured: {value}. This is the prev measured: {prev_measured}")

    # ------------------------------------------------------------
    # No Step difference retrieved
    # ------------------------------------------------------------
    if diff_value is None or isnan(diff_value):
        descriptions.append("Unable to calculate the Step difference. No previous value found!")
        return NOT_CHECKED, " || ".join(descriptions)

    # ------------------------------------------------------------
    # Global is mandatory
    # ------------------------------------------------------------
    if not glob_step:
        descriptions.append("Global Threshold not found, therefore unable to proceed!")
        return NOT_CHECKED, " || ".join(descriptions)
    
    g_min, g_max = glob_step
    if not (g_min <= diff_value <= g_max):
        descriptions.append(f"Failed Global Threshold (Step Diff: {diff_value}), skipping custom & reference checks!")

        return BAD, " || ".join(descriptions)

    descriptions.append("Passed Global Threshold!")

    # ------------------------------------------------------------
    # Reference check
    # ------------------------------------------------------------
    if not ref_step:
        descriptions.append("Reference Threshold not found, skipping remaining checks!")
        return SUSPICIOUS, " || ".join(descriptions)

    r_min, r_max = ref_step
    if not (r_min <= diff_value <= r_max):
        descriptions.append(f"Failed Reference Threshold (Step Diff: {diff_value}), skipping custom checks!")

        return SUSPICIOUS, " || ".join(descriptions)

    descriptions.append("Passed Reference Threshold!")

    # ------------------------------------------------------------
    # Custom check
    # ------------------------------------------------------------
    if not cus_step:
        descriptions.append("Custom Threshold not found!")
        return SUSPICIOUS, " || ".join(descriptions)

    c_min, c_max = cus_step
    if not (c_min <= diff_value <= c_max):
        descriptions.append(f"Failed Custom Threshold! (Step Diff: {diff_value})")

        return SUSPICIOUS, " || ".join(descriptions)

    descriptions.append("Passed Custom Threshold!")

    # ------------------------------------------------------------
    # Passed everything
    # ------------------------------------------------------------
    descriptions.append("All Threshold Checks Passed!")
    return GOOD, " || ".join(descriptions)


# ---------------------------------------------------------------------
# RANGE QC EVALUATION
# ---------------------------------------------------------------------
def evaluate_range_qc(value: float, thresholds: dict):
    """
        Evaluates whether a measured value is within allowed range thresholds.

        Rules:
        - Thresholds are only valid if BOTH min and max exist
        - Half-filled thresholds are ignored
        - BAD if global fails
        - SUSPICIOUS if global passes but reference is missing or fail
        - SUSPICIOUS if global passes but custom is missing or fail
        - GOOD only if all three exist and pass

        Note:
        - The global range is mandatory or it defaults to NOT CHECKED
    """

    descriptions = [thresholds.get("range_description", "Unknown threshold")]

    if value == settings.MISSING_VALUE:
        descriptions.append(f"Missing Value, range check failed!")

        return BAD, " || ".join(descriptions)

    # Get the threshold rande
    def get_range(prefix):
        min_key = f"{prefix}_range_min"
        max_key = f"{prefix}_range_max"
        if min_key in thresholds and max_key in thresholds:
            return thresholds[min_key], thresholds[max_key]
        return None

    glob_range = get_range("glob")
    ref_range  = get_range("ref")
    cus_range  = get_range("cus")

    # ------------------------------------------------------------
    # No thresholds at all
    # ------------------------------------------------------------
    if not any([glob_range, ref_range, cus_range]):
        descriptions.append("No Thresholds To Check!")

        return NOT_CHECKED, " || ".join(descriptions)

    # ------------------------------------------------------------
    # Global is mandatory
    # ------------------------------------------------------------
    if not glob_range:
        descriptions.append("Global Threshold not found, therefore unable to proceed!")
        return NOT_CHECKED, " || ".join(descriptions)

    g_min, g_max = glob_range
    if not (g_min <= value <= g_max):
        descriptions.append("Failed Global Threshold, skipping custom & reference checks!")

        return BAD, " || ".join(descriptions)

    descriptions.append("Passed Global Threshold!")

    # ------------------------------------------------------------
    # Reference check
    # ------------------------------------------------------------
    if not ref_range:
        descriptions.append("Reference Threshold not found, skipping remaining checks!")
        return SUSPICIOUS, " || ".join(descriptions)

    r_min, r_max = ref_range
    if not (r_min <= value <= r_max):
        descriptions.append("Failed Reference Threshold, skipping custom checks!")

        return SUSPICIOUS, " || ".join(descriptions)

    descriptions.append("Passed Reference Threshold!")

    # ------------------------------------------------------------
    # Custom check
    # ------------------------------------------------------------
    if not cus_range:
        descriptions.append("Custom Threshold not found!")
        return SUSPICIOUS, " || ".join(descriptions)

    c_min, c_max = cus_range
    if not (c_min <= value <= c_max):
        descriptions.append("Failed Custom Threshold!")

        return SUSPICIOUS, " || ".join(descriptions)
    
    descriptions.append("Passed Custom Threshold!")

    # ------------------------------------------------------------
    # Passed everything
    # ------------------------------------------------------------
    descriptions.append("All Threshold Checks Passed!")
    return GOOD, " || ".join(descriptions)


# ---------------------------------------------------------------------
# PERSIST QC EVALUATION
# ---------------------------------------------------------------------
def evaluate_persist_qc(
    value: float,
    station_id: int,
    variable_id: int,
    thresholds: dict,
    data_batch: list,
    row_datetime_utc: datetime,
    historical_records=None,
):
    """
    Evaluate persistence quality control for a single observation.

    Persistence QC detects values that remain effectively unchanged over
    a configured time window. The check computes the variance as:

        max(all values in window) - min(all values in window)

    where the window includes (t₀ being the current observations datetime):
        • Historical values from the database in [t₀ - window, t₀)
        • Prior values from the current batch in [t₀ - window, t₀)
        • The current value at t₀ (always included)

    Window boundaries are half-open to avoid double counting:
        window_start <= datetime < window_end
    which is effectively
        (row_datetime_utc - thresholds persist window) <= datetime < row_datetime_utc

    Decision logic:
        • If no prior data exists in the window -> GOOD
        • If variance >= minimum_variance -> GOOD
        • If variance < minimum_variance -> BAD
        • We have 3 teirs of checks: Global, Reference, Persist.
        • GOOD:
            - At least one fully-defined tier exists and
            - All valid tiers pass
        • BAD:
            - Any valid tier fails
        • NOT_CHECKED:
            - No valid tiers
            - Any tier is partially defined

    Args:
        value (float):
            Current measured value at t₀.
        station_id (int):
            Station identifier.
        variable_id (int):
            Variable identifier.
        thresholds (dict):
            Resolved persistence thresholds containing:
                - persist_wnd (hours)
                - persist_min_var
                - suspicious_persist_threshold (bool)
        data_batch (list):
            Current ingest batch (UTC datetimes), excluding the current row.
        row_datetime_utc (datetime):
            Timestamp of the current observation in UTC.

    Returns:
        Tuple[int, str]:
            (quality_flag, " || ".join(descriptions))
    """

    descriptions = [thresholds.get("persist_description", "Unknown threshold")]

    if value == settings.MISSING_VALUE:
        descriptions.append(f"Missing Value, persist check failed!")

        return BAD, " || ".join(descriptions)

    def get_persist_cfg(prefix):
        wnd_key = f"{prefix}_persist_wnd"
        var_key = f"{prefix}_persist_min_var"

        wnd = thresholds.get(wnd_key)
        var = thresholds.get(var_key)

        # Missing OR partial -> treated as not configured
        if wnd is None or var is None:
            return None        # invalid
        
        return wnd, var

    tiers = {
        "Global": get_persist_cfg("glob"),
        "Reference":  get_persist_cfg("ref"),
        "Custom":  get_persist_cfg("cus"),
    }

    # ------------------------------------------------------------
    # Configuration validation
    # ------------------------------------------------------------
    # If all teirs are none then return NOT_CHECKED
    if all(v is None for v in tiers.values()):
        descriptions.append("No Thresholds To Check!")
        
        return NOT_CHECKED, " || ".join(descriptions)

    # ------------------------------------------------------------
    # Evaluate each tier
    # ------------------------------------------------------------
    for prefix, cfg in tiers.items():
        if cfg is None:
            continue
        
        p_wnd, p_min_var = cfg # threshold window and variance

        # calculate the time window for a raw data search
        window_start = row_datetime_utc - timedelta(hours=p_wnd)
        window_end = row_datetime_utc

        # get max and min from raw_data within the window
        if historical_records is not None:
            rd_wnd_min = None
            rd_wnd_max = None

            for record in historical_records:
                record_dt = record["datetime"]

                if record_dt >= window_end:
                    break

                if record_dt < window_start:
                    continue

                val = record["measured"]
                rd_wnd_min = val if rd_wnd_min is None else min(rd_wnd_min, val)
                rd_wnd_max = val if rd_wnd_max is None else max(rd_wnd_max, val)
                
        else:
            rd_wnd_min, rd_wnd_max = get_min_max_measured(
                window_start,
                window_end,
                station_id,
                variable_id,
            )

        # get min and max from data_batch within the window (Batch Window)
        batch_wnd_min = None
        batch_wnd_max = None

        for row_data in data_batch:
            row_dt = row_data["datetime"]

            # data_batch is sorted ascending, so once we reach the current row time,
            # there is nothing else before the current observation to include.
            if row_dt >= window_end:
                break

            if row_dt < window_start:
                continue

            if row_data["measured"] == settings.MISSING_VALUE:
                continue

            val = row_data["measured"]
            batch_wnd_min = val if batch_wnd_min is None else min(batch_wnd_min, val)
            batch_wnd_max = val if batch_wnd_max is None else max(batch_wnd_max, val)

        # calculate the variance
        values = []

        # DB window
        if None not in (rd_wnd_min, rd_wnd_max):
            values.extend([rd_wnd_min, rd_wnd_max])

        # Batch window (STRICTLY before current)
        if None not in (batch_wnd_min, batch_wnd_max):
            values.extend([batch_wnd_min, batch_wnd_max])

        if not values:
            descriptions.append(f"Persist Not Checked. Could not find a valid max and/or min within the persistence window.")

            return NOT_CHECKED, " || ".join(descriptions)

        # CURRENT VALUE — always include
        values.append(value)

        # rounding the calc variance as some calculation noise may throw off the checks.
        calc_variance = round(max(values) - min(values), 3)

        if calc_variance <= p_min_var:
            descriptions.append(f"Failed {prefix} Threshold, persist check failed!")
            # descriptions.append(f"Failed {prefix} Threshold, persist check failed! calc var: {calc_variance} || max: {max(values)} || min: {min(values)}")

            return BAD, " || ".join(descriptions)
        
        descriptions.append(f"Passed {prefix} Threshold!")
        # descriptions.append(f"Passed {prefix} Threshold! calc var: {calc_variance} || max: {max(values)} || min: {min(values)}")

    # ------------------------------------------------------------
    # All configured tiers passed
    # ------------------------------------------------------------
    descriptions.append(f"All Threshold Checks Passed!")
    return GOOD, " || ".join(descriptions)


# ---------------------------------------------------------------------
# FINAL QC AGGREGATION
# ---------------------------------------------------------------------
def determine_final_qc(step_flag: int, range_flag: int, persist_flag: int) -> int:
    """
        Determines the global Quality Control status based on a worst-case priority.
        
        The final flag is derived hierarchically: 
        1. BAD: If any individual check is BAD.
        2. SUSPICIOUS: If no BAD exists, but at least one check is SUSPICIOUS.
        3. GOOD: If no higher severity exists and at least one check is GOOD.
        4. NOT_CHECKED: Default fallback if no flags are set.

        Args:
            step_flag (int): Result of the step-test analysis.
            range_flag (int): Result of the range-limit analysis.
            persist_flag (int): Result of the persistence/stuck-sensor analysis.

        Returns:
            int: The most conservative QC flag applicable to the dataset.
    """

    # Case 1: There is a BAD flag in list
    if BAD in [range_flag, persist_flag, step_flag]:
        return BAD
    
    # Case 2: There is a SUSPICIOUS flag in list
    if SUSPICIOUS in [range_flag, persist_flag, step_flag]:
        return SUSPICIOUS
    
    # Case 3: There is a NOT CHECKED flag in list
    if NOT_CHECKED in [range_flag, persist_flag, step_flag]:
        return SUSPICIOUS
    
    # Case 4: There is a GOOD flag in list
    if GOOD in [range_flag, persist_flag, step_flag]:
        return GOOD

    # Case 5: Everything else
    return NOT_CHECKED