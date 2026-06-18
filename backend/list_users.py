import os
import sys
import django

sys.path.append(r"d:\Projet de recherche\web\backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin

try:
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )
    users = keycloak_admin.get_users({})
    print(f"Users in {settings.KEYCLOAK_REALM}:")
    for u in users:
        print(f"- {u.get('username')} ({u.get('email')})")
        
except Exception as e:
    print(f"Error: {e}")
