import os
import django
import sys
import pprint

sys.path.append(r'd:\Projet de recherche\web\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin

def list_admins():
    print("Connecting to Keycloak Admin...")
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )

    print("Fetching all users...")
    users = keycloak_admin.get_users()
    for user in users:
        print(f"User: {user.get('username')} - Email: {user.get('email')}")
        roles = keycloak_admin.get_realm_roles_of_user(user['id'])
        role_names = [r['name'] for r in roles]
        print(f"Roles: {role_names}")
        if "ADMIN_SYSTEME" in role_names or "admin" in user.get('username', '').lower():
            print(">>> This is an Admin user!")
        print("-" * 20)

if __name__ == "__main__":
    list_admins()
