import os
import django
import sys

sys.path.append(r'd:\Projet de recherche\web\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin

def unlock_users():
    print("Connecting to Keycloak Admin...")
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )

    users = keycloak_admin.get_users()
    for user in users:
        print(f"Checking user: {user['username']}")
        # Remove brute force lock
        try:
            # We can use the admin API to remove brute force
            keycloak_admin.connection.raw_delete(
                f"{keycloak_admin.connection.url}admin/realms/{keycloak_admin.realm_name}/attack-detection/brute-force/users/{user['id']}"
            )
            print(f"Unlocked user {user['username']} if they were locked.")
        except Exception as e:
            print(f"Could not unlock user {user['username']}: {e}")

if __name__ == "__main__":
    unlock_users()
