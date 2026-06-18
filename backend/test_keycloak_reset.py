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

def test_flow():
    email = "testuser_reset@example.com"
    temp_password = "tempPassword123!"
    new_password = "newPassword123!"

    print("Connecting to Keycloak Admin...")
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )

    print("Creating user...")
    users = keycloak_admin.get_users({"email": email})
    if users:
        keycloak_admin.delete_user(users[0]['id'])

    user_id = keycloak_admin.create_user({
        "username": email,
        "email": email,
        "enabled": True,
        "credentials": [{"value": temp_password, "type": "password", "temporary": True}]
    })

    print(f"User created: {user_id}")

    print("1. Trying to login with temp password...")
    token_url = f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
    payload = {
        'client_id': settings.OIDC_RP_CLIENT_ID,
        'grant_type': 'password',
        'username': email,
        'password': temp_password,
    }
    if hasattr(settings, 'OIDC_RP_CLIENT_SECRET') and settings.OIDC_RP_CLIENT_SECRET != 'VOTRE_SECRET_KEYCLOAK':
        payload['client_secret'] = settings.OIDC_RP_CLIENT_SECRET

    data = urllib.parse.urlencode(payload).encode('ascii')
    req = urllib.request.Request(token_url, data=data)
    try:
        with urllib.request.urlopen(req) as res:
            print("Login 1 Status:", res.status)
            print("Login 1 Body:", json.loads(res.read().decode('utf-8')))
    except urllib.error.HTTPError as e:
        print("Login 1 Status:", e.code)
        print("Login 1 Body:", json.loads(e.read().decode('utf-8')))

    print("2. Resetting password...")
    keycloak_admin.set_user_password(user_id, new_password, temporary=False)
    
    user_info = keycloak_admin.get_user(user_id)
    user_info["requiredActions"] = []
    keycloak_admin.update_user(user_id, payload=user_info)

    print("Password reset and required actions cleared.")

    print("3. Trying to login with NEW password...")
    payload['password'] = new_password
    data = urllib.parse.urlencode(payload).encode('ascii')
    req = urllib.request.Request(token_url, data=data)
    try:
        with urllib.request.urlopen(req) as res:
            print("Login 2 Status:", res.status)
            print("Login 2 Body:", json.loads(res.read().decode('utf-8')))
    except urllib.error.HTTPError as e:
        print("Login 2 Status:", e.code)
        print("Login 2 Body:", json.loads(e.read().decode('utf-8')))

if __name__ == "__main__":
    test_flow()
