"""
Celery configuration for the Télé-rétinographielmo project.
Auto-discovers tasks from all installed Django apps.
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Load settings prefixed with CELERY_ from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py in each installed app
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Utility task to verify Celery is working."""
    print(f'Request: {self.request!r}')
