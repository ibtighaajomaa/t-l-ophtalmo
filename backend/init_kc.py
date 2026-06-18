import os
import django
import sys
from keycloak import KeycloakAdmin

sys.path.append(r'd:\Projet de recherche\web2\t-l-ophtalmo-main\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings

keycloak_admin = KeycloakAdmin(
    server_url=settings.KEYCLOAK_SERVER_URL,
    username=settings.KEYCLOAK_ADMIN_USER,
    password=settings.KEYCLOAK_ADMIN_PASSWORD,
    realm_name='master',
    user_realm_name='master',
    verify=True
)

realm_name = settings.KEYCLOAK_REALM

try:
    keycloak_admin.create_realm({"realm": realm_name, "enabled": True}, skip_exists=True)
    print(f"Realm {realm_name} created or already exists.")
except Exception as e:
    print(f"Failed to create realm: {e}")

keycloak_admin.realm_name = realm_name

client_id = settings.OIDC_RP_CLIENT_ID
client_secret = getattr(settings, 'OIDC_RP_CLIENT_SECRET', 'VOTRE_SECRET_KEYCLOAK')
try:
    keycloak_admin.create_client({
        "clientId": client_id,
        "secret": client_secret,
        "enabled": True,
        "directAccessGrantsEnabled": True,
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": True,
        "redirectUris": ["http://localhost:8000/*", "http://localhost:5173/*"]
    }, skip_exists=True)
    print("Client created.")
except Exception as e:
    print(f"Failed to create client: {e}")

roles = ["ADMIN_SYSTEME", "CHEF_SERVICE", "RESIDENT", "OPHTALMOLOGUE"]
for role in roles:
    try:
        keycloak_admin.create_realm_role({"name": role}, skip_exists=True)
        print(f"Role {role} created.")
    except Exception as e:
        print(f"Failed to create role {role}: {e}")
