import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from keycloak import KeycloakAdmin
from django.conf import settings

try:
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )
    admin_token = keycloak_admin.token['access_token']
    print('Admin Token acquired successfully!')
    
    import requests
    events_url = f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/admin/realms/{settings.KEYCLOAK_REALM}/events?type=LOGIN&type=LOGOUT"
    headers = {'Authorization': f'Bearer {admin_token}'}
    events_res = requests.get(events_url, headers=headers)
    
    print(f"Status: {events_res.status_code}")
    print(f"Response: {events_res.text}")
    
except Exception as e:
    print(f"Exception: {e}")
