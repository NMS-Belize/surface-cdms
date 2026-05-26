import os
import signal

from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpResponse, JsonResponse
from .forms import InstallTypeForm
from surface_app.models import InstallType, AnsibleRun
from wx_config.celery import app


def index(request):
    if request.method == 'POST':
        surface_form = InstallTypeForm(request.POST)
        if surface_form.is_valid():
            surface_form.save()
            return redirect(reverse('configure_surface')) # Redirect to surfacae configuration site after saving
    else:
        surface_form = InstallTypeForm()

        # Fetch the latest AnsibleRun and its status
        latest_ansible_run = AnsibleRun.objects.last()
        latest_status = latest_ansible_run.status if latest_ansible_run else None

        # capture task id if the task is already running
        # Check if the status is valid and if any InstallType exists
        if latest_status and latest_status in ['RUNNING', 'STARTED']:
            allow_surface_install = False
            surface_task_id = AnsibleRun.objects.last().task_id
        else:
            allow_surface_install = True
            surface_task_id = None

    return render(request, 'config_app/index.html', {'surface_form': surface_form, 'allow_surface_install': allow_surface_install, 'surface_task_id': surface_task_id})


# terminate a running celery task given the task id
def terminate_task(request, celery_task_id):
    if request.method == 'GET':
        try:
            app.control.revoke(celery_task_id, terminate=True)
        except Exception as e:
            print(f"Error revoking task: {e}")

    else:
        print("Invalid Request Method")

    return redirect('config-complete', task_id=celery_task_id)
  

# shutdown view
def shutdown(request):
    # Send termination signal to the current process
    os.kill(os.getpid(), signal.SIGINT)

    return HttpResponse('Server shutting down...')