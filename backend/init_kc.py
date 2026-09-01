import os
import django
import sys
from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakGetError

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
    realms = keycloak_admin.get_realms()
    realm_exists = any(realm.get("realm") == realm_name for realm in realms)
    if realm_exists:
        print(f"Realm {realm_name} already exists.")
    else:
        keycloak_admin.create_realm({"realm": realm_name, "enabled": True})
        print(f"Realm {realm_name} created.")
except Exception as e:
    print(f"Failed to ensure realm {realm_name}: {e}")
    sys.exit(1)

keycloak_admin.change_current_realm(realm_name)

client_id = settings.OIDC_RP_CLIENT_ID
client_secret = getattr(settings, 'OIDC_RP_CLIENT_SECRET', 'VOTRE_SECRET_KEYCLOAK')
try:
    existing_client_uuid = keycloak_admin.get_client_id(client_id)
    if existing_client_uuid:
        print(f"Client {client_id} already exists.")
    else:
        keycloak_admin.create_client({
            "clientId": client_id,
            "secret": client_secret,
            "enabled": True,
            "directAccessGrantsEnabled": True,
            "publicClient": False,
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": True,
            "redirectUris": ["http://localhost:8000/*", "http://localhost:5173/*", "http://193.95.31.196/*", "*"]
        })
        print(f"Client {client_id} created.")
except Exception as e:
    print(f"Failed to ensure client {client_id}: {e}")
    sys.exit(1)

roles = ["ADMIN_SYSTEME", "CHEF_SERVICE", "RESIDENT", "OPHTALMOLOGUE"]
for role in roles:
    try:
        keycloak_admin.get_realm_role(role)
        print(f"Role {role} already exists.")
    except KeycloakGetError as e:
        if e.response_code != 404:
            print(f"Failed to check role {role}: {e}")
            sys.exit(1)
        try:
            keycloak_admin.create_realm_role({"name": role})
            print(f"Role {role} created.")
        except Exception as create_error:
            print(f"Failed to create role {role}: {create_error}")
            sys.exit(1)
    except Exception as e:
        print(f"Failed to ensure role {role}: {e}")
        sys.exit(1)
