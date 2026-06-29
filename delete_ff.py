import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from keycloak import KeycloakAdmin
from django.conf import settings
from django.core.cache import cache

email = "ff@gmail.com"
print(f"Deleting {email}...")

keycloak_admin = KeycloakAdmin(
    server_url=settings.KEYCLOAK_SERVER_URL,
    username=settings.KEYCLOAK_ADMIN_USER,
    password=settings.KEYCLOAK_ADMIN_PASSWORD,
    realm_name=settings.KEYCLOAK_REALM,
    user_realm_name="master",
    verify=True
)

# 1. Delete from Keycloak
try:
    users = keycloak_admin.get_users({"email": email})
    for u in users:
        keycloak_admin.delete_user(u['id'])
        print(f"Deleted from Keycloak: {u['id']}")
except Exception as e:
    print("Error deleting from Keycloak:", e)

# 2. Delete from Django DB (Hard delete)
users_db = User.objects.filter(email=email)
count = users_db.count()
users_db.delete()
print(f"Deleted {count} users from Django DB.")

# 3. Clear Cache
cache.clear()
print("Django cache cleared.")

