import os
import sys
import django

# Setup Django environment
sys.path.append(r"d:\Projet de recherche\web\backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError

try:
    print(f"Connecting to {settings.KEYCLOAK_SERVER_URL} as {settings.KEYCLOAK_ADMIN_USER} in master realm for realm {settings.KEYCLOAK_REALM}...")
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )
    print("Connection successful!")
    
    roles = keycloak_admin.get_realm_roles()
    print("Available roles in realm:")
    for r in roles:
        print(f"- {r['name']}")
        
except KeycloakError as e:
    print(f"KeycloakError: {e.error_message}")
    if hasattr(e, 'response_code'):
        print(f"Code: {e.response_code}")
except Exception as e:
    print(f"Exception: {str(e)}")
