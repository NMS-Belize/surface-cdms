from django.core.exceptions import ObjectDoesNotExist

from wx.models import QcRangeThreshold, QcStepThreshold, QcPersistThreshold, Station, Variable

# ---------------------------------------------------------------------
# STEP THRESHOLD RESOLUTION
# ---------------------------------------------------------------------
def resolve_step_thresholds(thresholds: dict, station_id: int, variable_id: int) -> dict:
    """
        Resolve and attach all STEP thresholds (custom, reference, global) for a
        given station and variable.

        This function does NOT apply downward fallback logic. Instead, it retrieves
        thresholds independently from all available layers:

            1. Custom station threshold
            2. Reference station threshold (if defined)
            3. Global variable threshold

        All successfully retrieved values are added to the provided `thresholds`
        dictionary using prefixed keys:

            cus_step_min / cus_step_max
            ref_step_min / ref_step_max
            glob_step_min / glob_step_max

        A combined description string summarizing retrieval results is stored under:
            "step_description"

        Parameters
        ----------
        thresholds : dict
            Mutable dictionary to append resolved threshold values into.
        station_id : int
            Primary key of the station.
        variable_id : int
            Primary key of the variable.

        Returns
        -------
        dict
            The updated thresholds dictionary containing resolved step thresholds
            and a descriptive summary.
    """
    descriptions = []

    # Fetch station once to avoid repeated DB queries
    try:
        station = Station.objects.get(pk=station_id)
    except ObjectDoesNotExist:
        # If station does not exist, we cannot resolve thresholds
        return thresholds

    # ------------------------------------------------------------
    # Custom station threshold
    # ------------------------------------------------------------
    # There should only every be one return or less objs return. However using .filter & .first just to be safe
    step_obj = (
        QcStepThreshold.objects
        .filter(station_id=station_id, variable_id=variable_id)
        .first()
    )

    if (step_obj and step_obj.step_min is not None and step_obj.step_max is not None):
        thresholds["cus_step_min"] = step_obj.step_min
        thresholds["cus_step_max"] = step_obj.step_max
        descriptions.append("Custom station threshold: Retrieved.")

    else:
        descriptions.append("Custom station threshold: NOT SET!")

    # ------------------------------------------------------------
    # Reference station threshold
    # ------------------------------------------------------------
    if station.reference_station_id:
        # There should only every be one return or less objs return. However using .filter & .first just to be safe
        step_obj = (
            QcStepThreshold.objects
            .filter(station_id=station.reference_station_id, variable_id=variable_id)
            .first()
        )

        if (step_obj and step_obj.step_min is not None and step_obj.step_max is not None):
            thresholds["ref_step_min"] = step_obj.step_min
            thresholds["ref_step_max"] = step_obj.step_max
            descriptions.append("Reference station threshold: Retrieved.")

        else:
            descriptions.append("Reference station threshold: NOT SET!")
    else:
        descriptions.append("Reference station threshold: NONE!")

    # ------------------------------------------------------------
    # Global threshold from Variable
    # ------------------------------------------------------------
    try:
        variable = Variable.objects.get(pk=variable_id)

        if station.is_automatic:
            if (variable and variable.step_hourly is not None):
                thresholds["glob_step_min"] = -variable.step_hourly
                thresholds["glob_step_max"] = variable.step_hourly
                descriptions.append("Global threshold (Automatic): Retrieved.")
            else:
                descriptions.append("Global threshold: NOT SET!.")
        else:
            if (variable and variable.step is not None):
                thresholds["glob_step_min"] = -variable.step
                thresholds["glob_step_max"] = variable.step
                descriptions.append("Global threshold (Manual): Retrieved.")
            else:
                descriptions.append("Global threshold: NOT SET!.")

    except ObjectDoesNotExist:
        descriptions.append("Global threshold: NOT SET!")

    # combine descriptions
    thresholds["step_description"] = " || ".join(descriptions)

    return thresholds


# ---------------------------------------------------------------------
# RANGE THRESHOLD RESOLUTION
# ---------------------------------------------------------------------
def resolve_range_thresholds(thresholds: dict, station_id: int, variable_id: int, month: int) -> dict:
    """
        Resolve and attach all RANGE thresholds (custom, reference, global) for a
        given station and variable.

        This function does NOT apply downward fallback logic. Instead, it retrieves
        thresholds independently from all available layers:

            1. Custom station threshold
            2. Reference station threshold (if defined)
            3. Global variable threshold

        All successfully retrieved values are added to the provided `thresholds`
        dictionary using prefixed keys:

            cus_range_min / cus_range_max
            ref_range_min / ref_range_max
            glob_range_min / glob_range_max

        A combined description string summarizing retrieval results is stored under:
            "range_description"

        Note
        ----
        The `month` parameter is reserved for potential seasonal threshold logic,
        but is not currently used.

        Parameters
        ----------
        thresholds : dict
            Mutable dictionary to append resolved threshold values into.
        station_id : int
            Primary key of the station.
        variable_id : int
            Primary key of the variable.
        month : int
            Month of observation (1–12). Reserved for future seasonal logic.

        Returns
        -------
        dict
            The updated thresholds dictionary containing resolved range thresholds
            and a descriptive summary.
    """

    descriptions = []

    # Fetch station once to avoid repeated DB queries
    try:
        station = Station.objects.get(pk=station_id)
    except ObjectDoesNotExist:
        return thresholds

    # ------------------------------------------------------------
    # Custom station range threshold
    # ------------------------------------------------------------
    # There should only every be one return or less objs return. However using .filter & .first just to be safe
    range_obj = (
        QcRangeThreshold.objects
        .filter(station_id=station_id, variable_id=variable_id)
        .first()
    )

    if (range_obj and range_obj.range_min is not None and range_obj.range_max is not None):
        thresholds["cus_range_min"] = range_obj.range_min
        thresholds["cus_range_max"] = range_obj.range_max
        descriptions.append("Custom station threshold: Retrieved.")

    else:
        descriptions.append("Custom station threshold: NOT SET!")

    # ------------------------------------------------------------
    # Reference station threshold
    # ------------------------------------------------------------
    if station.reference_station_id:
        # There should only every be one return or less objs return. However using .filter & .first just to be safe
        range_obj = (
            QcRangeThreshold.objects
            .filter(station_id=station.reference_station_id, variable_id=variable_id)
            .first()
        )

        if (range_obj and range_obj.range_min is not None and range_obj.range_max is not None):
            thresholds["ref_range_min"] = range_obj.range_min
            thresholds["ref_range_max"] = range_obj.range_max
            descriptions.append("Reference station threshold: Retrieved.")

        else:
            descriptions.append("Reference station threshold: NOT SET!")
    else:
        descriptions.append("Reference station threshold: NONE!")

    # ------------------------------------------------------------
    # Global variable threshold
    # ------------------------------------------------------------
    try:
        variable = Variable.objects.get(pk=variable_id)

        if station.is_automatic:
            if (variable and variable.range_min_hourly is not None and variable.range_max_hourly is not None):
                thresholds["glob_range_min"] = variable.range_min_hourly
                thresholds["glob_range_max"] = variable.range_max_hourly
                descriptions.append("Global threshold (Automatic): Retrieved.")
            else:
                descriptions.append("Global threshold: NOT SET!")
        else:
            if (variable and variable.range_min is not None and variable.range_max is not None):
                thresholds["glob_range_min"] = variable.range_min
                thresholds["glob_range_max"] = variable.range_max
                descriptions.append("Global threshold (Manual): Retrieved.")
            else:
                descriptions.append("Global threshold: NOT SET!")

    except ObjectDoesNotExist:
        descriptions.append("Global threshold: NOT SET!")

    # combine descriptions
    thresholds["range_description"] = " || ".join(descriptions)

    return thresholds


# ---------------------------------------------------------------------
# PERSISTENCE THRESHOLD RESOLUTION
# ---------------------------------------------------------------------
def resolve_persist_thresholds(thresholds: dict, station_id: int, variable_id: int) -> dict:
    """
        Resolve and attach all PERSISTENCE thresholds (custom, reference, global)
        for a given station and variable.

        This function does NOT apply downward fallback logic. Instead, it retrieves
        thresholds independently from all available layers:

            1. Custom station threshold
            2. Reference station threshold (if defined)
            3. Global variable threshold

        All successfully retrieved values are added to the provided `thresholds`
        dictionary using prefixed keys:

            cus_persist_wnd / cus_persist_min_var
            ref_persist_wnd / ref_persist_min_var
            glob_persist_wnd / glob_persist_min_var

        A combined description string summarizing retrieval results is stored under:
            "persist_description"

        Parameters
        ----------
        thresholds : dict
            Mutable dictionary to append resolved threshold values into.
        station_id : int
            Primary key of the station.
        variable_id : int
            Primary key of the variable.

        Returns
        -------
        dict
            The updated thresholds dictionary containing resolved persistence
            thresholds and a descriptive summary.
    """
    descriptions = []

    # Fetch station once to avoid repeated DB queries
    try:
        station = Station.objects.get(pk=station_id)
    except ObjectDoesNotExist:
        # If station does not exist, we cannot resolve thresholds
        return thresholds

    # ------------------------------------------------------------
    # Custom station threshold
    # ------------------------------------------------------------
    # There should only every be one return or less objs return. However using .filter & .first just to be safe
    persist_obj = (
        QcPersistThreshold.objects
        .filter(station_id=station_id, variable_id=variable_id)
        .first()
    )

    if (persist_obj and persist_obj.window is not None and persist_obj.minimum_variance is not None):
        thresholds["cus_persist_wnd"] = persist_obj.window
        thresholds["cus_persist_min_var"] = persist_obj.minimum_variance
        descriptions.append("Custom station threshold: Retrieved.")

    else:
        descriptions.append("Custom station threshold: NOT SET!")

    # ------------------------------------------------------------
    # Reference station threshold
    # ------------------------------------------------------------
    if station.reference_station_id:
        # There should only every be one return or less objs return. However using .filter & .first just to be safe
        persist_obj = (
            QcPersistThreshold.objects
            .filter(station_id=station.reference_station_id, variable_id=variable_id)
            .first()
        )            

        if (persist_obj and persist_obj.window is not None and persist_obj.minimum_variance is not None):
            thresholds["ref_persist_wnd"] = persist_obj.window
            thresholds["ref_persist_min_var"] = persist_obj.minimum_variance
            descriptions.append("Reference station threshold: Retrieved.")

        else:
            descriptions.append("Reference station threshold: NOT SET!")

    else:
        descriptions.append("Reference station threshold: NONE!")

    # ------------------------------------------------------------
    # Global threshold from Variable
    # ------------------------------------------------------------
    try:
        variable = Variable.objects.get(pk=variable_id)

        if station.is_automatic:
            if (variable and variable.persistence_hourly is not None):
                thresholds["glob_persist_wnd"] = variable.persistence_window_hourly or 1
                thresholds["glob_persist_min_var"] = variable.persistence_hourly
                descriptions.append("Global threshold (Automatic): Retrieved.")
            else:
                descriptions.append("Global threshold: NOT SET!")
        else:
            if (variable and variable.persistence is not None):
                thresholds["glob_persist_wnd"] = variable.persistence_window or 96 # 4 days
                thresholds["glob_persist_min_var"] = variable.persistence
                descriptions.append("Global threshold (Manual): Retrieved.")
            else:
                descriptions.append("Global threshold: NOT SET!")            

    except ObjectDoesNotExist:
        descriptions.append("Global threshold: NOT SET!")

    # combine descriptions
    thresholds["persist_description"] = " || ".join(descriptions)

    return thresholds