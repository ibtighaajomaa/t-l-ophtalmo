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

def test_admin_login(username):
    print(f"\nTesting login for {username}...")
    token_url = f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
    payload = {
        'client_id': settings.OIDC_RP_CLIENT_ID,
        'grant_type': 'password',
        'username': username,
        'password': 'password123!', # Try a dummy password first
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
    test_admin_login("jomaa")
    test_admin_login("elle")
    test_admin_login("ibtighaa")
