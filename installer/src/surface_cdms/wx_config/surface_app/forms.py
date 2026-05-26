from django import forms
from .models import InstallType
import json

class SurfaceConfigurationForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super(SurfaceConfigurationForm, self).__init__(*args, **kwargs)
        
        install_type = InstallType.objects.last()
        
        if install_type and install_type.install_type == 'remote':
            self.fields['host'] = forms.CharField(
                label="Remote Host for SURFACE install:", 
                required=True, 
                widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(e.g. username@xxx.xxx.xxx.xxx)'})
            )
            self.fields['surface_repo_path'] = forms.CharField(
                label="Path on remote machine to clone SURFACE repository:", 
                required=True, 
                widget=forms.TextInput(attrs={'class': 'form-control',})
            )
            self.fields['remote_connect_password'] = forms.CharField(
                label="Password to connect to the remote machine:", 
                required=True, 
                widget=forms.PasswordInput(attrs={'class': 'form-control',})
            )
            self.fields['root_password'] = forms.CharField(
                label="Root password on the remote machine:", 
                required=True, 
                widget=forms.PasswordInput(attrs={'class': 'form-control',})
            )
        elif install_type and install_type.install_type == 'local':
            self.fields['surface_repo_path'] = forms.CharField(
                label="Path to clone SURFACE repository:", 
                required=True, 
                widget=forms.TextInput(attrs={'class': 'form-control',})
            )

    # SURFACE port
    surface_port = forms.IntegerField(
        label="SURFACE Port:", 
        initial=8080,
        required=True, 
        widget=forms.NumberInput(attrs={'class': 'form-control form-quarter-size'})
    )

    with_data = forms.ChoiceField(
        label="Start with Backup data:", 
        choices=[('yes', 'Yes'), ('no', 'No')], 
        required=True, 
        initial='no',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input',})
    )
    data_path = forms.CharField(
        label="Backup dump file path on host machine:", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder' : '(e.g. /path/to/backup.sql.gz)'})
    )
    admin = forms.CharField(
        label="Admin Username:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control',})
    )
    admin_email = forms.CharField(
        label="Admin Email:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control',})
    )
    admin_password = forms.CharField(
        label="Admin Password:", 
        required=True, 
        widget=forms.PasswordInput(attrs={'class': 'form-control',})
    )
    
    # New form fields
    lrgs_user = forms.CharField(
        label="LRGS User:", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control',})
    )
    lrgs_password = forms.CharField(
        label="LRGS Password:", 
        required=False, 
        widget=forms.PasswordInput(attrs={'class': 'form-control',})
    )
    timezone_name = forms.CharField(
        label="Timezone Name:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )
    timezone_offset = forms.CharField(
        label="Timezone Offset:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )
    map_latitude = forms.CharField(
        label="Map Latitude:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )
    map_longitude = forms.CharField(
        label="Map Longitude:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )
    map_zoom = forms.IntegerField(
        label="Map Zoom Level:", 
        required=True, 
        widget=forms.NumberInput(attrs={'id':'zoomField','class': 'form-control disabled-field',})
    )
    spatial_analysis_initial_latitude = forms.CharField(
        label="Spatial Analysis Initial Latitude:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )
    spatial_analysis_initial_longitude = forms.CharField(
        label="Spatial Analysis Initial Longitude:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )
    spatial_analysis_final_latitude = forms.CharField(
        label="Spatial Analysis Final Latitude:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )
    spatial_analysis_final_longitude = forms.CharField(
        label="Spatial Analysis Final Longitude:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )

    # retrieve dump via ftp forms
    dump_ftp_host = forms.GenericIPAddressField(
        label="FTP Host", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder' : '(e.g. xxx.xxx.xxx.xxx)'})
    )
    dump_ftp_port = forms.IntegerField(
        label="Port:", 
        required=False, 
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    dump_ftp_username = forms.CharField(
        label="Username:", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    dump_ftp_password = forms.CharField(
        label="Password:", 
        required=False, 
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    dump_ftp_dump_path = forms.CharField(
        label="Dump Path on FTP:", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder' : '(e.g. /path/to/FTP/backup.sql.gz)'})
    )

    # Database Password
    surface_database_password = forms.CharField(
        label="Database Password:", 
        required=True, 
        max_length=32,  # Ensures Django enforces the limit at the model/form level
        widget=forms.TextInput(attrs={'class': 'form-control form-half-size', 'maxlength': '32'})  # Limits input length in the frontend
    )

    # Surface secret key
    surface_secret_key = forms.CharField(
        label="SURFACE Secret Key:", 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control form-half-size disabled-field'})  # Limits input length in the frontend
    )

    # Wis2box options
    surface_encryption_key = forms.CharField(
        label="Encryption Key:", 
        required=True, 
        max_length=44,  # Ensures Django enforces the limit at the model/form level
        widget=forms.TextInput(attrs={'class': 'form-control form-half-size disabled-field', 'maxlength': '44'})  # Limits input length in the frontend
    )

    # The topic hierarchy
    wis2box_topic_hierarchy = forms.CharField(
        label="Topic Hierarchy:",
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control disabled-field',})
    )

    # Countries 
    # Country options
    countries_file_name = "./static/surface_app/spatial_analysis/countries.json"

    # open file containing the countries
    with open(countries_file_name, 'r', encoding='utf-8') as file:
        # Pass the file object to json.load()
        counties_info = json.load(file)

    choices_list = [('###', '--------')]
    # looping through the counties list and adding them as choices
    choices_list.extend((country['iso3'],f"{country['name']}") for country in counties_info) 

    # Country Name selector
    selected_country = forms.ChoiceField(
        label="Country:",
        choices=choices_list,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control form-half-size stripped_select'})
    )
