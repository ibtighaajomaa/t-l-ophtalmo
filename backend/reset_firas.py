import os
import django
import sys
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin

def reset_firas():
    email = "firas@gmail.com"
    new_password = "firas123"

    print("Connecting to Keycloak Admin...")
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )

    print("Finding user...")
    users = keycloak_admin.get_users({"email": email})
    if not users:
        print("User not found!")
        return

    user_id = users[0]['id']
    print(f"Resetting password for user: {user_id}")
    
    keycloak_admin.set_user_password(user_id, new_password, temporary=False)
    
    user_info = keycloak_admin.get_user(user_id)
    if "UPDATE_PASSWORD" in user_info.get("requiredActions", []):
        user_info["requiredActions"].remove("UPDATE_PASSWORD")
        keycloak_admin.update_user(user_id, payload=user_info)

    print("Password reset and required actions cleared.")

if __name__ == "__main__":
    reset_firas()
