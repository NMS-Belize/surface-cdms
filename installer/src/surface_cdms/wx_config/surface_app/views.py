import os
import pwd
import json
import secrets
from cryptography.fernet import Fernet
from ftplib import FTP

from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.conf import settings
from django.core.management.utils import get_random_secret_key
from .forms import SurfaceConfigurationForm
from .models import InstallType, AnsibleRun
from .tasks import install_surface, get_ansible_task_status
from .utils import process_form


# project directory and playbook name variables
project_dir = "" 
playbook_name = ""

# surface configuration view
def configure_surface(request):
    # Fetch the latest AnsibleRun and its status
    latest_ansible_run = AnsibleRun.objects.last()
    latest_status = latest_ansible_run.status if latest_ansible_run else None

    # Check if the status is valid and if any InstallType exists
    if not latest_status:
        install_type = InstallType.objects.last() # get installation type (remote or local)
    else:
        return redirect(reverse('wx_configuration')) # redirecting to the home page

    if request.method == 'POST':
        form = SurfaceConfigurationForm(request.POST)
        # Process the form data
        if form.is_valid():

            # process configuration data
            global project_dir, playbook_name 
            
            project_dir, playbook_name = process_form(form, install_type)
            
            task = install_surface.apply_async(args=[project_dir, playbook_name, install_type.install_type])

            url = reverse('config-complete', kwargs={'task_id': task.id})

            return redirect(url) # Redirect to config_complete page

    else:
        form = SurfaceConfigurationForm() # form

        # Get the current user's username
        username = os.getlogin()
        # Retrieve the home directory for the current user
        home_directory = pwd.getpwnam(username).pw_dir

        # users home directory to preload into surface_repo_path
        user_home_dir = home_directory

    return render(request, 'surface_app/configuration.html', {'form': form, 'user_home_dir': user_home_dir, 'install_type':  install_type.install_type, })


# get the status of the current task
@require_GET
def task_status(request, task_id):
    task_status = get_ansible_task_status(task_id)

    return JsonResponse(task_status)


# config_complete page view
def config_complete(request, task_id):
    # check if task id exists if not redirect to the home page (wx_configuration)
    if InstallType.objects.exists():
        return render(request, 'surface_app/config_complete.html', {'task_id': task_id})
    else:
        return redirect(reverse('wx_configuration'))
    
# generate encryption key
def gen_encrypt_key(request):
    key = Fernet.generate_key().decode('utf-8')  # 44-char Base64 key
    return JsonResponse({"key": key})

# generate encryption key
def gen_secret_key(request):
    key = get_random_secret_key()
    return JsonResponse({"key": key})

# generate encryption key
def gen_db_pwd(request):
    pwd = secrets.token_urlsafe(24)  # 32-char pwd (24 bytes...note: bytes * 3 / 4 ≈ character length)
    return JsonResponse({"pwd": pwd})

# retrieve country details
def retr_country_details(request):
    iso3_code = request.GET['iso3_code']
    # open file containing the countries details
    with open('./static/surface_app/spatial_analysis/spatial_analysis_coords.json', 'r', encoding='utf-8') as file:
        # Pass the file object to json.load()
        counties_details = json.load(file)

    for detail in counties_details:
        if detail['notation'] == iso3_code:
            # return the country's detail
            return JsonResponse(detail)
    
    # contry information not found
    return JsonResponse({''}, status=404)
    

# # retry configuration with the same env variables
# def retry_config(request):
#     task = install_surface.apply_async(args=[project_dir, playbook_name])

#     url = reverse('config-complete', kwargs={'task_id': task.id})

#     return redirect(url) # Redirect to config_complete page


# tests the ftp connection and returns the result
def test_ftp_connection(request):
    if request.method == "POST":
        # Retrieve form data from the AJAX request
        host = request.POST.get('host')
        port = request.POST.get('port')
        username = request.POST.get('username')
        password = request.POST.get('password')
        data_dump = request.POST.get('dump_path')

        if not(host and port and username and password and data_dump):
            return JsonResponse({"status": "error", "message": "Complete all fields before testing"})

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
            ftp.size(data_dump) # if the file size is gotten, then the files exists. Error otherwise
            ftp.quit()
            return JsonResponse({"status": "success", "message": "Connection successful!"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "Invalid request method"})