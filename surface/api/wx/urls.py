from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from rest_framework import routers

from django.contrib.auth.decorators import login_required

from wx import views

router = routers.DefaultRouter()
router.register(r'station_images', views.StationImageViewSet)
router.register(r'station_files', views.StationFileViewSet)
router.register(r'quality_flags', views.QualityFlagList)
router.register(r'stations_metadata', views.StationMetadataViewSet)

urlpatterns = [
    # DRF router include (API endpoints). Must stay above routes to override them.
    path('api/stations/metadata', include(router.urls)),

    # Fetches task status
    path("api/task/<str:task_id>/", views.get_task_status, name="task_status"),

    # DRF router endpoints (API-only: returns raw JSON responses) separated by the "api/" router
    path('api/administrative_regions/', views.AdministrativeRegionViewSet.as_view({'get': 'list'})),
    path('api/variables/', views.VariableViewSet.as_view({'get': 'list'})),
    path('api/watersheds/', views.WatershedList.as_view()),
    path('api/station_communications/', views.StationCommunicationList.as_view()),
    path('api/livedata/<code>/', views.livedata),
    path('api/rawdata/', views.raw_data_list),
    path('api/hourlysummaries/', views.hourly_summary_list),
    path('api/dailysummaries/', views.daily_summary_list),
    path('api/monthlysummaries/', views.monthly_summary_list),
    path('api/yearlysummaries/', views.yearly_summary_list),
    path('api/last24hrsummaries/', views.last24_summary_list),
    path('api/station_telemetry_data/<str:date>', views.station_telemetry_data),
    path('api/stations/', views.StationViewSet.as_view({'get': 'list', 'post': 'create', 'put': 'update'})),
    path('api/stations_simple/', views.StationSimpleViewSet.as_view({'get': 'list'})),
    path('api/station_profiles/', views.StationProfileViewSet.as_view({'get': 'list'})),
    path('api/stations_variables/', views.StationVariableViewSet.as_view({'get': 'list'})),
    path('api/stations_variables/stations/', views.StationVariableStationViewSet.as_view({'get': 'list'})),
    path('api/range_threshold/', views.range_threshold_view), # For synop and daily data capture
    path('api/available_data/', views.AvailableDataView.as_view()),
    path('api/user_info/', views.UserInfo.as_view()),
    path('api/data_export/', views.AppDataExportView.as_view()),
    path('api/intervals/', views.IntervalViewSet.as_view({'get': 'list'})),
    path('api/station_report/', views.station_report_data, name='station_report_data'), # Station Report
    path('api/variable-report/', views.variable_report_data, name='variable-report-data'), # Variable Report
    path('api/raw_data_last_24h/<station_id>/', views.raw_data_last_24h),
    path('api/latest_data/<variable_id>/', views.latest_data),
    path('api/daily_means/', views.daily_means_data_view), # Extremes and Means
    path("api/publishing_offsets/", views.publishingOffsetViewSet.as_view({'get': 'list'}), name='api-publishing-offsets'),
    path('api/agromet/aquacrop/run/', views.AquacropModelRunView.as_view()),
    path('api/agromet/aquacrop/available/', views.AquacropAvailableDataView.as_view()),
    path('api/crops/', views.CropViewSet.as_view({'get': 'list'})),
    path('station_geo_features/<str:lon>/<str:lat>', views.station_geo_features), # country hard coded to Belize...fix this
    path('decoders/', views.DecoderList.as_view()),
    # ----------- #
    path('api/', include(router.urls)),
    # ----------- #
    # Django views (template-rendered pages for human users)
    
    # Permission Management Page
    path('wx/permissions/', views.ManagePermissionsView.as_view(), name='manage-permissions'),
    path('api/groups/', views.GroupsInfo.as_view(), name="groups-info"),
    path('api/users_groups/', views.UsersGroupsInfo.as_view(), name="users-groups-info"),
    path("api/users/<int:user_id>/roles/", views.UpdateUserRoles.as_view(), name="users-groups-update"),
    path("api/permission_pages/", views.PermissionPagesInfo.as_view(), name="permission-pages-info"),
    path("api/groups/<int:group_id>/page_access/", views.GroupPageAccessView.as_view(), name="group-page-access"),
    
    # Configuration / Settings Page
    path('wx/settings/', views.ConfigurationSettingsView.as_view(), name='configuration-settings'),
    path('wx/settings/spatial/files/', views.UploadOrDeleteSpatialFilesView.as_view(), name='upload-document'),
    path('wx/settings/spatial/files/download/<str:key>/', views.DownloadSpatialFilesView.as_view(), name='download-document'),
    path("wx/settings/organization-logo/", views.OrganizationLogoDetailsView.as_view(),name="organization_logo_details",),
    path("wx/settings/organization-logo/update/", views.UploadOrDeleteOrganizationLogoView.as_view(),name="upload_or_delete_organization_logo",),
    path("wx/settings/organization-logo/download/<str:key>/", views.DownloadOrganizationLogoView.as_view(), name="download_organization_logo",),


    # Station Map Pages (default page)
    path('', views.StationsMapView.as_view(), name='stations-map'),
    path('wx/stations/map/', views.StationsMapView.as_view(), name='stations-map'),
    

    # Placeholder pages
    path('under-maintenance', views.UnderMaintenanceView.as_view(), name='under-maintenance'),
    path('coming-soon', views.ComingSoonView.as_view(), name='coming-soon'),
    path('not-auth', views.NotAuthView.as_view(), name='not-auth'),


    # Station Create Page
    path('wx/stations/', views.StationListView.as_view(), name='stations-list'),
    path('wx/stations/create/', views.StationCreate.as_view(), name='station-create'),
    path('wx/stations/<int:pk>/', views.StationDetailView.as_view(), name='station-detail'),
    path('wx/stations/metadata/', views.StationMetadataView.as_view(), name='station-metadata'),
    path('wx/stations/<int:pk>/update/', views.StationUpdate.as_view(), name='station-update'),
    path('wx/stations/<int:pk>/delete/', views.StationDelete.as_view(), name='station-delete'),
    path('wx/stations/<int:pk>/files/', views.StationFileList.as_view(), name='stationfiles-list'),
    path('wx/stations/<int:pk>/files/create/', views.StationFileCreate.as_view(), name='stationfile-create'),
    path('wx/stations/<int:pk_station>/files/<int:pk>/delete/', views.StationFileDelete.as_view(), name='stationfile-delete'),
    path('wx/stations/<int:pk>/variables/', views.StationVariableListView.as_view(), name='stationvariable-list'),
    path('wx/stations/<int:pk>/variables/create/', views.StationVariableCreateView.as_view(), name='stationvariable-create'),
    path('wx/stations/<int:pk_station>/variables/<int:pk>/delete/', views.StationVariableDeleteView.as_view(), name='stationvariable-delete'),
    

    # Oscar Export Page
    path('wx/stations/oscar_export/', views.StationOscarExportView.as_view(), name='station-oscar-export'),


    # Station Monitoring Page
    path('wx/stations/stations_monitoring/', views.stationsmonitoring_form.as_view(), name="stations-monitoring"),
    path('wx/stations/stations_monitoring/get/', views.get_stationsmonitoring_map_data, name="monitoring-map-data"),
    path('wx/stations/stations_monitoring/get/<int:id>/', views.get_stationsmonitoring_station_data, name="monitoring-station-data"),
    path('wx/stations/stations_monitoring/get/<int:station_id>/<int:variable_id>/', views.get_stationsmonitoring_chart_data, name="monitoring-chart-data"),


    # Manual Data Import Page
    path('wx/data/manual-import/', views.ManualDataImportView.as_view(), name='manual-data-import'),
    path('wx/data/manual-import/delete/',views.DeleteManualDataFile, name='data-import-manual-delete'),
    path('wx/data/manual-import/check/', views.CheckManualImportView, name='check-manual-import'),
    path('wx/data/manual-import/remove-file/', views.RemoveManualDataFile, name='remove-manual-data-file'),
    path('wx/data/manual-import/upload-files/', views.UploadManualDataFile, name='upload-manual-data-file'),
    path('wx/data/manual-import/data-files/', views.ManualDataFiles, name='manual-data-files'),
    

    # Data Export Page
    path('wx/data/export/', views.DataExportView.as_view(), name='data-export'),
    path('wx/data/export/files/', views.DataExportFiles, name='data-export-files'),
    path('wx/data/export/download/', views.DownloadDataFile, name='data-export-download'),
    path('wx/data/export/download_xlsx/', views.DownloadDataFileXLSX, name='data-export-download-xlsx'),
    path('wx/data/export/combine_xlsx/', views.CombineFilesXLSX, name='combine-xlsx'),
    path('wx/data/export/delete/', views.DeleteDataFile, name='data-export-delete'),
    path('wx/data/export/schedule/', views.ScheduleDataExport, name='data-export-schedule'),
    path('wx/data/export/combine_files/', views.combineDataExportFiles, name='combine-files'),


    # Data Inventory Page
    path('wx/data/inventory/', views.DataInventoryView.as_view(), name='data-inventory'),
    path('api/data_inventory/', views.get_data_inventory),
    path('api/data_inventory_by_station/', views.get_data_inventory_by_station),
    path('api/station_variable_data_month_inventory/', views.get_station_variable_month_data_inventory),
    path('api/station_variable_data_day_inventory/', views.get_station_variable_day_data_inventory),
    

    # Maintenance Report Page
    path('wx/maintenance_report/', views.get_maintenance_reports.as_view(), name='maintenance-reports'),
    path('wx/maintenance_report/get_reports/', login_required(views.get_maintenance_report_list), name='get-maint-report-list'),
    path('wx/maintenance_report/<int:id>/delete/', login_required(views.delete_maintenance_report), name='delete-maint-report'),
    path('wx/maintenance_report/<int:id>/update/', login_required(views.update_maintenance_report), name='update-maint-report'),
    path('wx/maintenance_report/<int:id>/view/<int:source>/', login_required(views.get_maintenance_report_view), name='view-maintenance-report'),
    path('wx/maintenance_report/<int:id>/approve/', login_required(views.approve_maintenance_report), name='approve-maint-report'),
    path('wx/maintenance_report/create/', login_required(views.create_maintenance_report), name='create-maint-report'),
    path('wx/maintenance_report/equipmenttype_data/update/', views.update_maintenance_report_equipment_type_data, name='update-maint-report-equip-type'),
    path('wx/maintenance_report/<int:id>/update/condition/', login_required(views.update_maintenance_report_condition), name='update-maint-report-condition'),
    path('wx/maintenance_report/<int:id>/update/contacts/', login_required(views.update_maintenance_report_contacts), name='update-maint-report-contacts'),
    path('wx/maintenance_report/<int:id>/update/datalogger/', login_required(views.update_maintenance_report_datalogger), name='update-maint-report-datalogger'),    
    path('wx/maintenance_report/<int:id>/update/summary/', login_required(views.update_maintenance_report_summary), name='update-maint-report-summary'),
    path('wx/maintenance_report/<int:id>/get/', login_required(views.get_maintenance_report), name='get-maint-report'),
    path('wx/maintenance_report/new_report/', views.get_maintenance_report_form.as_view(), name='new-maintenance-report'),


    # Equipment Inventory Page
    path('wx/maintenance_reports/equipment_inventory/', views.get_equipment_inventory.as_view(), name="equipment-inventory"),
    path('wx/maintenance_reports/equipment_inventory/get/', views.get_equipment_inventory_data, name="get-equipment-inventory"),
    path('wx/maintenance_reports/equipment_inventory/create/', views.create_equipment, name="create-equipment-inventory"),
    path('wx/maintenance_reports/equipment_inventory/delete/', views.delete_equipment, name="delete-equipment-inventory"),
    path('wx/maintenance_reports/equipment_inventory/update/', views.update_equipment, name="update-equipment-inventory"),
    

    # Synop Capture Page
    path('wx/reports/synop/capture', views.SynopCaptureView.as_view(), name='synop-capture-form'),
    path('wx/reports/synop/load/', views.synop_load, name='load-synop-report'),
    path('wx/reports/synop/update/', views.synop_update, name='update-synop-report'),
    path('wx/reports/synop/calc-pressure/', views.synop_pressure_calc, name='calculate-pressure-difference'),
    path('wx/reports/synop/calc-precip/', views.synop_precip_calc, name='calculate-24-hr-precipitation'),
    path('wx/reports/synop/delete/', views.synop_delete, name='delete-synop-report-row'),
    path("wx/reports/synop/push_to_wis2box/",views.push_to_wis2box, name="synop-push-to-wis2box"),
    path('wx/reports/synop/capture/update/empty_cols', views.synop_capture_update_empty_col, name='update-empty-col-synop-capture-report'),


    # Monthly Capture Form
    path('wx/data/capture/monthly/', views.MonthlyFormView.as_view(), name='monthly-form'),
    path('wx/data/capture/monthly/load/', views.MonthlyFormLoad, name='load-monthly-form'),
    path('wx/data/capture/monthly/update/', views.MonthlyFormUpdate, name='update-monthly-form'), 
    path('wx/data/capture/monthly/delete/', views.MonthlyFormDelete, name='delete-monthly-form-row'),
    path('wx/data/capture/monthly/update/empty_cols', views.monthly_capture_update_empty_col, name='update-empty-col-monthly-capture-form'),


    # WIS2 Dashboard Page
    path('wx/wis2dashboard/', views.WIS2DashboardView.as_view(), name='wis2-dashboard'), 
    path("wx/wis2dashboard/records", views.wis2dashboard_records_list, name="wis2dashboard_records_list"), # for the wis2dashboard to grab data
    path("wx/wis2dashboard/publishing_logs/<int:pk>/", views.publishingLogs, name='wis2-publishing-logs'), # for the wis2dashboard to grab log data
    path("wx/wis2dashboard/download-logs/<int:pk>/", views.downloadWis2Logs, name='wis2-download-logs'), # for the wis2dashboard to dowload log data
    path("wx/wis2dashboard/download-messages/<int:pk>/", views.downloadWis2Message, name='wis2-download-Message'), # for the wis2dashboard to dowload log data
    path("wx/wis2dashboard/push_to_wis2box/",views.push_to_wis2box, name="push-to-wis2box"),
    path('api/wis2box-publishing/', views.Wis2BoxPublishListView.as_view(), name='wis2box-publish-list'),
    path("api/local_wis_credentials/", views.LocalWisCredentialsUpdateView.as_view(), name='local-wis-credentials'),
    path("api/regional_wis_credentials/", views.RegionalWisCredentialsUpdateView.as_view(), name='regional-wis-credentials'),
    path("api/config_wis_station/<int:pk>/", views.configWis2StationUpdateView.as_view(), name='config-wis-stations'),


    # Reference Station Page
    path('wx/quality_control/reference_station/', views.ReferenceStationView.as_view(), name='reference-station'),
    path('wx/quality_control/reference_station/load/',views.load_reference_stations,name='load-reference-stations'), # Load reference stations
    path('wx/quality_control/reference_station/create/',views.create_reference_station,name='create-reference-station'), # Create reference station
    path('wx/quality_control/reference_station/update/<int:id>/',views.modify_reference_station,name='modify-reference-station'), # Update reference station
    path('wx/quality_control/reference_station/toggle-active/<int:id>/',views.toggle_reference_station_active,name='toggle-reference-station-active'), # Toggle active/inactive
    path('wx/quality_control/reference_station/delete/<int:id>/', views.delete_reference_station, name='delete-reference-station'),
    path('wx/quality_control/reference_station/variables/load/', views.load_reference_station_variables, name='load-reference-station-variables'),
    path('wx/quality_control/reference_station/<int:id>/thresholds/load/', views.load_reference_station_thresholds, name='load-reference-station-thresholds'),
    path('wx/quality_control/reference_station/<int:id>/thresholds/save/', views.save_reference_station_thresholds, name='save-reference-station-thresholds'),



    # Data Validation Page
    path('wx/quality_control/validation/', views.QualityControlView.as_view(), name='quality-control'),
    path('api/quality_control/description/', views.get_qc_description, name='get-qc-description'),
    path('api/quality_control/', views.qc_list, name='get-update-quality-control'),
    path('api/quality_control/bulksave/', views.qc_validate_bulk, name='bulk-update-quality-control'),
    path('wx/quality_control/update_reference_station/', views.update_reference_station, name='update-threshold-reference-station'), # this is used for Range, Step & Persist Threshold   
    path('wx/quality_control/global_threshold/update/', views.update_global_threshold, name='update-global-threshold'), # this is used for Range, Step & Persist Threshold  


    # Range Threshold Page
    path('wx/quality_control/range_threshold/', views.get_range_threshold_form.as_view(), name='range-threshold'),
    path('wx/quality_control/range_threshold/get/', views.get_range_threshold, name='range-threshold-get'),
    path('wx/quality_control/range_threshold/update/', views.update_range_threshold, name='range-threshold-update'),    
    path('wx/quality_control/range_threshold/delete/', views.delete_range_threshold, name='range-threshold-delete'),

    # Step Threshold Page
    path('wx/quality_control/step_threshold/', views.get_step_threshold_form.as_view(), name='step-threshold'),
    path('wx/quality_control/step_threshold/get/', views.get_step_threshold, name='step-threshold-get'),
    path('wx/quality_control/step_threshold/update/', views.update_step_threshold, name='step-threshold-update'),
    path('wx/quality_control/step_threshold/delete/', views.delete_step_threshold, name='step-threshold-delete'),


    # Persist Threshold Page
    path('wx/quality_control/persist_threshold/', views.get_persist_threshold_form.as_view(), name='persist-threshold'),
    path('wx/quality_control/persist_threshold/get/', views.get_persist_threshold, name='persist-threshold-get'),
    path('wx/quality_control/persist_threshold/update/', views.update_persist_threshold, name='persist-threshold-update'),
    path('wx/quality_control/persist_threshold/delete/', views.delete_persist_threshold, name='persist-threshold-delete'),


    # Station Report Page
    path('wx/products/station_report/', views.StationReportView.as_view(), name='station-report'),


    # Variable Report Page
    path('wx/variablereport/', views.VariableReportView.as_view(), name='variable-report'),


    # Product Compare Page
    path('wx/product/compare/', views.ProductCompareView.as_view(), name='product-compare'),


    # Yearly Average Page
    path('wx/reports/yearly_average/', views.YearlyAverageReport.as_view(), name='yearly-average'),
    path('get_yearly_average/', views.get_yearly_average, name="get-yearly-average"),


    # Spatial Analysis Page
    path('wx/spatial_analysis/', views.SpatialAnalysisView.as_view(), name='spatial-analysis'),
    path('wx/spatial_analysis/image', views.GetInterpolationImage, name='spatial-analysis-image'),
    path('wx/spatial_analysis/data', views.GetInterpolationData, name='spatial-analysis-data'),
    path('wx/spatial_analysis/interpolate_data', views.InterpolatePostData, name='spatial-analysis-interpolate-data'),
    path('wx/spatial_analysis/color_bar', views.GetColorMapBar, name='spatial-analysis-color-bar'),
    # path('interpolation/', views.interpolate_endpoint), #unprotected, unsure what this does...seemingly nothing.


    # Extremes and Means Page
    path('wx/product/extremes_means/', views.ExtremesMeansView.as_view(), name='extremes-means'),


    # Wave Data Analysis Page
    path('wx/products/wave_data/', views.get_wave_data_analysis.as_view(), name='wave-data'),
    path('wx/products/wave_data/get/', views.get_wave_data, name="get-wave-data"),


    # Agrometeorology: Monthly & Seasonal Page
    path('wx/agromet/summaries/', views.AgroMetSummariesView.as_view(), name='agromet-summaries'),
    path('wx/agromet/summaries/get/', views.get_agromet_summary_data, name='get-agromet-summaries-data'),


    # Agrometeorology: Calculated Products Page
    path('wx/agromet/products/', views.AgroMetProductsView.as_view(), name='agromet-products'),    
    path('wx/agromet/products/get/', views.get_agromet_products_data, name='get-agromet-products-data'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.DOCUMENTS_URL, document_root=settings.DOCUMENTS_ROOT)
