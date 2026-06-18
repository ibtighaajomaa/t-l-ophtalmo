import os
import django
import sys

sys.path.append(r'd:\Projet de recherche\web\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin

def test_search_exact():
    print("Connecting to Keycloak Admin...")
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )

    users = keycloak_admin.get_users({"email": "jomaa2026@gmail.com", "exact": True})
    print(f"Found {len(users)} users with exact=True:")
    for u in users:
        print(f"- {u.get('username')} ({u.get('email')})")

if __name__ == "__main__":
    test_search_exact()
