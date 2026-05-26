from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction
from .models import AnsibleRun, AnsibleEvent, InstallType
import ansible_runner

import os
import shutil
import click


@shared_task(bind=True, soft_time_limit=3000, time_limit=3600)  # Set soft time limit of 50 min and a hard time limit of 1 hour
def install_surface(self, project_dir, playbook_name, install_type):
    ansible_run = AnsibleRun.objects.create(task_id=self.request.id, status='STARTED')

    # fxn handling playbook events
    def event_handler(event):
        if event.get('event'):
            AnsibleEvent.objects.create(
                run=ansible_run,
                event_type=event['event'],
                host=event.get('host'),
                task=event.get('task'),
                stdout=event.get('stdout')
            )
            ansible_run.status = 'RUNNING'
            ansible_run.save()

    # Cleanup artifacts directory
    artifacts_dir = os.path.join(project_dir, 'artifacts')
    if os.path.exists(artifacts_dir):
        shutil.rmtree(artifacts_dir)

    try:
        # execute playbook
        playbook_run = ansible_runner.run(
            private_data_dir=project_dir,
            playbook=playbook_name,
            event_handler=event_handler
        )

        # captures playbook return code and updates the task status accordingly
        if playbook_run.status == 'successful':
            ansible_run.status = 'SUCCESS'
            click.launch("http://0.0.0.0:8080") # start surface on success
        else:
            ansible_run.status = 'FAILURE'

    except SoftTimeLimitExceeded:
        # set the status to failure if the task exceeds the time limit
        ansible_run.status = 'FAILURE'

    # save ansible_run entry
    ansible_run.save()

    return ansible_run.status


# get ansible task status
def get_ansible_task_status(task_id):
    try:
        ansible_run = AnsibleRun.objects.get(task_id=task_id)
        events = ansible_run.events.all()
        events_data = [{'event_type': e.event_type, 'host': e.host, 'task': e.task, 'stdout': e.stdout} for e in events]

        # deleting tasks entries from the model on failure and success
        if ansible_run.status in ['FAILURE', 'SUCCESS']:
            remove_all_tasks()

        return {
            'task_id': ansible_run.task_id,
            'status': ansible_run.status,
            'events': events_data,
        }
    except AnsibleRun.DoesNotExist:
        return {'status': 'NOT_FOUND'}


# remove all task entries
def remove_all_tasks():
    try:
        with transaction.atomic():
            AnsibleEvent.objects.all().delete()
            AnsibleRun.objects.all().delete()
            InstallType.objects.all().delete()
    except Exception as e:
        print(f"Error during deletion: {e}")
        
