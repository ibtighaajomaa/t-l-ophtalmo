import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from keycloak import KeycloakAdmin
import requests

keycloak_admin = KeycloakAdmin(
    server_url=settings.KEYCLOAK_SERVER_URL,
    username=settings.KEYCLOAK_ADMIN_USER,
    password=settings.KEYCLOAK_ADMIN_PASSWORD,
    realm_name=settings.KEYCLOAK_REALM,
    user_realm_name='master',
    verify=True
)
admin_token = keycloak_admin.token['access_token']
headers = {'Authorization': f'Bearer {admin_token}'}
base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
realm = settings.KEYCLOAK_REALM

# Let's search for lll
res = requests.get(f'{base_url}/admin/realms/{realm}/users', headers=headers)
users = res.json()
print('Total users:', len(users))
for u in users:
    if 'attributes' in u and 'createdBy' in u['attributes']:
        print(f"User: {u['username']}, createdBy: {u['attributes']['createdBy']}")

# Let's try q with quotes
res_q = requests.get(f'{base_url}/admin/realms/{realm}/users?q=createdBy:"lll lll"', headers=headers)
print('Query with quotes returned:', len(res_q.json()))

res_q2 = requests.get(f'{base_url}/admin/realms/{realm}/users?q=createdBy:lll lll', headers=headers)
print('Query without quotes returned:', len(res_q2.json()))
