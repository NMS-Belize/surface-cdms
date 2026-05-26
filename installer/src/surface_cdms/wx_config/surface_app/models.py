from django.db import models

class InstallType(models.Model):
    INSTALL_CHOICES = [
        # ('remote', 'Remote'),
        ('local', 'Local'),
    ]
    install_type = models.CharField(max_length=6, choices=INSTALL_CHOICES)

    def __str__(self):
        return self.install_type
    
class AnsibleRun(models.Model):
    task_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=50, default='PENDING')
    output = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AnsibleEvent(models.Model):
    run = models.ForeignKey(AnsibleRun, related_name='events', on_delete=models.CASCADE)
    event_type = models.CharField(max_length=50)
    host = models.CharField(max_length=255, blank=True, null=True)
    task = models.CharField(max_length=255, blank=True, null=True)
    stdout = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)