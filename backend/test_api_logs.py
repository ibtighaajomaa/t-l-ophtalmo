import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.views import get_keycloak_events
from django.test import RequestFactory

factory = RequestFactory()
request = factory.get('/api/logs/')
response = get_keycloak_events(request)
print(response.status_code)
print(response.content)
