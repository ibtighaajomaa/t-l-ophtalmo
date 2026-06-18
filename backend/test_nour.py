import os
import django
import sys
import json
import urllib.request
import urllib.parse

sys.path.append(r'd:\Projet de recherche\web\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin

def test_nour():
    email = "nour@gmail.com"
    new_password = "password123!"

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
    print(f"User found: {user_id}")

    print("Resetting password and removing required actions...")
    user_info = keycloak_admin.get_user(user_id)
    if "UPDATE_PASSWORD" in user_info.get("requiredActions", []):
        user_info["requiredActions"].remove("UPDATE_PASSWORD")
        keycloak_admin.update_user(user_id, payload=user_info)

    keycloak_admin.set_user_password(user_id, new_password, temporary=False)

    print("Trying to login...")
    token_url = f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
    payload = {
        'client_id': settings.OIDC_RP_CLIENT_ID,
        'grant_type': 'password',
        'username': email,
        'password': new_password,
    }
    if hasattr(settings, 'OIDC_RP_CLIENT_SECRET') and settings.OIDC_RP_CLIENT_SECRET != 'VOTRE_SECRET_KEYCLOAK':
        payload['client_secret'] = settings.OIDC_RP_CLIENT_SECRET

    data = urllib.parse.urlencode(payload).encode('ascii')
    req = urllib.request.Request(token_url, data=data)
    try:
        with urllib.request.urlopen(req) as res:
            print("Login Status:", res.status)
            print("Login Body:", json.loads(res.read().decode('utf-8')))
    except urllib.error.HTTPError as e:
        print("Login Status:", e.code)
        print("Login Body:", json.loads(e.read().decode('utf-8')))

if __name__ == "__main__":
    test_nour()
