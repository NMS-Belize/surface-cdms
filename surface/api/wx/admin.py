from django.urls import path
from django.http import JsonResponse
from ftplib import FTP

from django.contrib import admin
from django.utils.html import format_html
from import_export.admin import ExportMixin, ImportMixin

from wx import models, forms, tasks
from simple_history.utils import update_change_reason

@admin.register(models.AdministrativeRegion)
class AdministrativeRegionAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.AdministrativeRegionType)
class AdministrativeRegionTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "notation", "description",)
    search_fields = ("name",)


@admin.register(models.DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "base_url",)
    search_fields = ("name",)


@admin.register(models.QualityFlag)
class QualityFlagAdmin(admin.ModelAdmin):
    list_display = ("name", "id",)
    search_fields = ("name",)


@admin.register(models.Station)
class StationAdmin(ExportMixin, admin.ModelAdmin):
    search_fields = ('name',)
    list_display = ("name", "country", "data_source", "code", "longitude", "latitude", "elevation", "alternative_names",)


@admin.register(models.StationCommunication)
class StationCommunicationAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.StationProfile)
class StationProfileAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.StationType)
class StationTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.StationVariable)
class StationVariableAdmin(admin.ModelAdmin):
    search_fields = ('station__name', 'variable__name',)
    list_display = ("station", "variable", "height", "first_measurement", "last_measurement", "last_value",)


@admin.register(models.Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol",)
    search_fields = ("name",)


@admin.register(models.Variable)
class VariableAdmin(ExportMixin, admin.ModelAdmin):
    search_fields = ('name',)
    list_display = ("id", "name", "symbol", "measurement_variable", "unit", "sampling_operation", "variable_type", "code_table", "range_min", "range_max",)


# @admin.register(models.VariableType)
# class VariableTypeAdmin(admin.ModelAdmin):
#     list_display = ("type",)


@admin.register(models.PhysicalQuantity)
class PhysicalQuantityAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.SamplingOperation)
class SamplingOperationAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name",)
    search_fields = ("name", "symbol",)


@admin.register(models.Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("alias", "file", "station", "processed",)
    search_fields = ("station__name",)


@admin.register(models.Decoder)
class DecoderAdmin(admin.ModelAdmin):
    list_display = ("name", "description",)
    search_fields = ("name",)


@admin.register(models.MeasurementVariable)
class MeasurementVariableAdmin(admin.ModelAdmin):
    list_display = ("name", "physical_quantity",)
    search_fields = ("name",)


@admin.register(models.CodeTable)
class CodeTableAdmin(admin.ModelAdmin):
    list_display = ("name", "description",)
    search_fields = ("name",)


@admin.register(models.Format)
class FormatAdmin(admin.ModelAdmin):
    list_display = ("name", "description",)
    search_fields = ("name",)


@admin.register(models.Interval)
class IntervalAdmin(admin.ModelAdmin):
    list_display = ("symbol", "description",)
    search_fields = ("symbol", "description",)


@admin.register(models.VariableFormat)
class VariableFormatAdmin(admin.ModelAdmin):
    search_fields = ('variable__name',)
    list_display = ("variable", "format", "interval", "lookup_key",)


@admin.register(models.PeriodicJobType)
class PeriodicJobTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "description",)
    search_fields = ("name", "description",)


@admin.register(models.PeriodicJob)
class PeriodicJobAdmin(admin.ModelAdmin):
    list_display = ("station", "periodic_job_type", "last_record", "is_running",)
    search_fields = ("station__name", "periodic_job_type__name",)

@admin.register(models.Watershed)
class WatershedAdmin(admin.ModelAdmin):
    list_display = ("watershed", "hectares",)
    search_fields = ("watershed",)


@admin.register(models.District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("district", "hectares",)
    search_fields = ("district",)


@admin.register(models.NoaaTransmissionType)
class NoaaTransmissionTypeAdmin(admin.ModelAdmin):
    list_display = ("acronym", "description",)
    search_fields = ("acronym", "description",)


@admin.register(models.NoaaTransmissionRate)
class NoaaTransmissionRateAdmin(admin.ModelAdmin):
    list_display = ("rate",)
    search_fields = ("rate",)


@admin.register(models.NoaaDcp)
class NoaaDcpAdmin(admin.ModelAdmin):
    search_fields = ("dcp_address",)
    list_display = ("dcp_address", "first_channel", "first_channel_type", "second_channel", "second_channel_type",
                    "first_transmission_time", "transmission_window", "transmission_period", "last_datetime",)


    change_form_template = "admin/noaaDcp_change_form.html"  # Custom template

    # Custom view to handle the dcp address test
    def test_dcp(self, request):
        if request.method == "POST":

            # Try to verify dcp address
            try:
                # Retrieve form data from the AJAX request
                dcp_address = request.POST.get('dcp_address')
                first_channel = request.POST.get('first_channel')

                # ensure first channel and dcp address are entered
                if not first_channel or not dcp_address:
                    raise Exception("Enter values for both the DCP Address and the First Channel!")

                dcp_info = {
                    'first_channel': first_channel,
                    'dcp_address': dcp_address,
                }

                dcp_address_test_result = tasks.test_dcp_transmit(dcp_info)

                # raise an exception if the test result is empty
                if not dcp_address_test_result:
                    raise Exception("The message is empty! Please ensure values for the DCP Address and the First Channel are correct. Also ensure that the station is transmitting.")

                return JsonResponse({"status": "success", "message": dcp_address_test_result})
            except Exception as e:
                return JsonResponse({"status": "error", "message": str(e)})

        return JsonResponse({"status": "error", "message": "Invalid request method"})

    # Add custom URL for the AJAX request
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('test-dcp/', self.admin_site.admin_view(self.test_dcp), name='test-dcp'),
        ]
        return custom_urls + urls

@admin.register(models.NoaaDcpsStation)
class NoaaDcpsStationAdmin(admin.ModelAdmin):
    search_fields = ("station__name",)
    list_display = ("station", "noaa_dcp", "decoder", "interval", "format", "start_date", "end_date",)


@admin.register(models.Flash)
class FlashAdmin(admin.ModelAdmin):
    list_display = ("datetime", "latitude", "longitude", "type", "peak_current", "ic_height", "num_sensors",)
    search_fields = ("type",)

@admin.register(models.QcRangeThreshold)
class QcRangeThresholdAdmin(ExportMixin, admin.ModelAdmin):
    list_display = ("station", "variable", "month", "range_min", "range_max",)
    search_fields = ("station__name",)


@admin.register(models.QcStepThreshold)
class QcStepThresholdAdmin(ExportMixin, admin.ModelAdmin):
    list_display = ("station", "variable", "step_min", "step_max",)
    search_fields = ("station__name",)


@admin.register(models.QcPersistThreshold)
class QcPersistThresholdAdmin(ExportMixin, admin.ModelAdmin):
    list_display = ("station", "variable", "window", "minimum_variance",)
    search_fields = ("station__name",)
    

@admin.register(models.FTPServer)
class FTPServerAdmin(admin.ModelAdmin):
    search_fields = ("name", "host",)
    list_display = ("name", "host", "port", "username",)
    form = forms.FTPServerForm

    change_form_template = "admin/ftpserver_change_form.html"  # Custom template

    # Custom view to handle the FTP connection test
    def test_ftp_connection(self, request):
        if request.method == "POST":
            # Retrieve form data from the AJAX request
            host = request.POST.get('host')
            port = request.POST.get('port')
            username = request.POST.get('username')
            password = request.POST.get('password')

            # Validate and handle empty or invalid port values
            try:
                port = int(port)
            except ValueError:
                return JsonResponse({"status": "error", "message": "Invalid port value"})

            # Try to establish an FTP connection
            try:
                ftp = FTP()
                ftp.connect(host, port, timeout=10)
                ftp.login(user=username, passwd=password)
                ftp.quit()
                return JsonResponse({"status": "success", "message": "Connection successful!"})
            except Exception as e:
                return JsonResponse({"status": "error", "message": str(e)})

        return JsonResponse({"status": "error", "message": "Invalid request method"})

    # Add custom URL for the AJAX request
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('test-ftp-connection/', self.admin_site.admin_view(self.test_ftp_connection), name='test-ftp-connection'),
        ]
        return custom_urls + urls


@admin.register(models.StationFileIngestion)
class StationFileIngestionAdmin(admin.ModelAdmin):
    search_fields = ('station__name',)
    list_display = ("ftp_server", "station", "decoder", "cron_schedule", "is_active", "is_binary_transfer",)


@admin.register(models.StationDataFile)
class StationDataFileAdmin(admin.ModelAdmin):
    search_fields = ('station__name', 'status__name',)
    # list_display = ("created_at", "updated_at", "station", "decoder", "status", "file_size", "utc_offset_minutes", "filepath_url",)
    list_display = ("created_at", "updated_at", "duration_display", "station", "decoder", "status", "file_size_kb", "utc_offset_minutes",)
    exclude = ('filepath',)
    readonly_fields = ('filepath_url',)

    def filepath_url(self, obj):
        if obj.filepath is None:
            return format_html('Not available')
        return format_html('<a href={0}>{0}</a>', obj.filepath.replace(' ', '%20'))
    
    @admin.display(description='Processing Time', ordering='updated_at')
    def duration_display(self, obj):
        if obj.created_at and obj.updated_at:
            diff = obj.updated_at - obj.created_at
            total_seconds = int(diff.total_seconds())
            
            # minutes gets the whole number, seconds gets the remainder
            minutes, seconds = divmod(total_seconds, 60)
            
            return f"{minutes} min {seconds:02d} sec"
        return "-"
    
    @admin.display(description='File Size (in KB)', ordering='file_size')
    def file_size_kb(self, obj):
        if obj.file_size:
            # Round to 2 decimal places for readability
            return f"{obj.file_size / 1024:.2f} KB"
        return "0 KB"

    filepath_url.short_description = 'File path'


@admin.register(models.StationDataFileStatus)
class StationDataFileStatusAdmin(admin.ModelAdmin):
    list_display = ("id", "name",)
    search_fields = ("name",)


@admin.register(models.HourlySummaryTask)
class HourlySummaryTaskAdmin(admin.ModelAdmin):
    list_display = ("created_at", "started_at", "finished_at", "station", "datetime",)
    search_fields = ("created_at", "started_at", "finished_at", "station__name", "datetime",)


@admin.register(models.DailySummaryTask)
class DailySummaryTaskAdmin(admin.ModelAdmin):
    list_display = ("created_at", "started_at", "finished_at", "station", "date",)
    search_fields = ("station__name",)


@admin.register(models.DcpMessages)
class DcpMessagesAdmin(admin.ModelAdmin):
    list_display = ("noaa_dcp", "datetime", "frequency_offset", "failure_code", "data_quality",)
    search_fields = ("noaa_dcp__dcp_address",)

@admin.register(models.RatingCurve)
class RatingCurveAdmin(admin.ModelAdmin):
    list_display = ("station", "start_date",)
    search_fields = ("station__name",)


@admin.register(models.RatingCurveTable)
class RatingCurveTableAdmin(admin.ModelAdmin):
    list_display = ("rating_curve", "h", "q",)
    search_fields = ("rating_curve__station__name",)


# Station images, may be used in the future.
@admin.register(models.StationImage)
class StationImageAdmin(admin.ModelAdmin):
    list_display = ("station", "name", "path",)
    search_fields = ("station__name",)


@admin.register(models.WMOStationType)
class WMOStationTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "notation", "description",)
    search_fields = ("name", "description",)


@admin.register(models.WMORegion)
class WMORegionAdmin(admin.ModelAdmin):
    list_display = ("name", "notation", "description",)
    search_fields = ("name", "description",)


@admin.register(models.WMOProgram)
class WMOProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "notation", "description", "path",)
    search_fields = ("name", "description",)


# Station files, may be used in the future.
# @admin.register(models.StationFile)
# class StationFileAdmin(admin.ModelAdmin):
#     list_display = ("name", "station",)
#     search_fields = ("name", "station__name",)


@admin.register(models.HydroMLPrediction)
class HydroMLPredictionAdmin(admin.ModelAdmin):
    list_display = ("name", "hydroml_prediction_id", "variable",)
    search_fields = ("name",)

@admin.register(models.HydroMLPredictionMapping)
class HydroMLPredictionMappingAdmin(admin.ModelAdmin):
    list_display = ("hydroml_prediction", "prediction_result", "quality_flag",)
    search_fields = ("hydroml_prediction__name",)


@admin.register(models.Neighborhood) # Machine Learning
class NeighborhoodAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.StationNeighborhood) # Machine Learning
class StationNeighborhoodAdmin(admin.ModelAdmin):
    list_display = ("neighborhood", "station",)
    search_fields = ("neighborhood__name", "station__name",)


@admin.register(models.HydroMLPredictionStation)
class HydroMLPredictionStationAdmin(admin.ModelAdmin):
    list_display = ("prediction", "neighborhood", "target_station", "data_period_in_minutes", "interval_in_minutes",)
    search_fields = ("neighborhood__name", "target_station__name", "prediction__name",)

@admin.register(models.BackupTask)
class BackupTaskAdmin(admin.ModelAdmin):
    list_display = ("name", "cron_schedule", "file_name", "retention", "ftp_server", "remote_folder", "is_active",)
    search_fields = ("name", "ftp_server__name",)

@admin.register(models.BackupLog)
class BackupLogAdmin(admin.ModelAdmin):
    search_fields = ("backup_task__name", "status",)
    list_display = ("backup_task", "started_at", "finished_at", "backup_duration", "status", "message", "file_path", "file_size",)
    readonly_fields = ("backup_task", "started_at", "finished_at", "backup_duration", "status", "message", "file_path", "file_size",)

    def backup_duration(self, obj):
        if obj.finished_at is not None:
            return obj.finished_at - obj.started_at

        return None

@admin.register(models.ElementDecoder)
class ElementDecoder(admin.ModelAdmin):
    search_fields = ("element_name", "variable__name", "decoder__name",)
    list_display = ("element_name", "variable_id", "decoder",)

@admin.register(models.VisitType)
class VisitTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

@admin.register(models.Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(models.FundingSource)
class FundingSourceAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

from simple_history.admin import SimpleHistoryAdmin

@admin.register(models.EquipmentType)
class EquipmentTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

@admin.register(models.Equipment)
class EquipmentAdmin(SimpleHistoryAdmin):
    def changed_fields(self, obj):
        if obj.prev_record:
            delta = obj.diff_against(obj.prev_record)
            return delta.changed_fields
        return None

    def list_changes(self, obj):
        fields = ""
        if obj.prev_record:
            delta = obj.diff_against(obj.prev_record)

            for change in delta.changes:
                fields += str("<strong>{}</strong> changed from <span style='background-color:#ffb5ad'>{}</span> to <span style='background-color:#b3f7ab'>{}</span> . <br/>".format(change.field, change.old, change.new))
            return format_html(fields)
        return None
    
    list_display = ("equipment_type", "manufacturer", "model", "serial_number", "acquisition_date", "first_deploy_date", "last_calibration_date", "location",)
    search_fields = ("equipment_type__name", "manufacturer__name", "model__name", "serial_number", "location__name",)
    history_list_display = ["changed_fields","list_changes"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        update_change_reason(obj, 'Source of change: Admin page')

@admin.register(models.StationProfileEquipmentType)
class StationProfileEquipmentTypeAdmin(admin.ModelAdmin):
    list_display = ("station_profile", "equipment_type", "equipment_type_order",)
    search_fields = ("station_profile__name", "equipment_type__name", "equipment_type_order",)

@admin.register(models.Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ("name", "name_spanish", "crop_type", "maturity_cd",)
    search_fields = ("name", "name_spanish",)

# @admin.register(models.Soil)
# class SoilAdmin(admin.ModelAdmin):
#     list_display = ("soil_type",)

@admin.register(models.EquipmentModel)
class EquipmentModelAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    
@admin.register(models.WxPermissionPages)
class WxPermissionPagesAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "url_name", "description",)
    search_fields = ("name", "url_name", "category__name",)

@admin.register(models.WxPermissionCategory)
class WxPermissionCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "sort_order",)
    search_fields = ("name", "description",)
    

@admin.register(models.WxGroupPageAccess)
class WxGroupPageAccessAdmin(admin.ModelAdmin):
    list_display = ("group", "page", "can_read", "can_write", "can_delete",)
    search_fields = ("group__name", "page__name", "page__url_name",)

    def save_model(self, request, obj, form, change):
        # Ensure model.clean() runs (and field validation too)
        obj.full_clean()
        super().save_model(request, obj, form, change)


@admin.register(models.StagedRawDataTask)
class StagedRawDataTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "station_data_file",
        "station",
        "variable",
        "start_datetime",
        "end_datetime",
        "started_at",
        "finished_at",
        "has_error",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "station",
        "variable",
        "started_at",
        "finished_at",
        "created_at",
    )

    search_fields = (
        "station__name",
        "variable__name",
        "station_data_file__filepath",
        "error",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "start_datetime"

    ordering = (
        "-created_at",
    )

    list_per_page = 50

    def has_error(self, obj):
        return bool(obj.error)

    has_error.boolean = True
    has_error.short_description = "Error"