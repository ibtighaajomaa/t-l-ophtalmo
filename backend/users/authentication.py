from rest_framework import authentication
from rest_framework import exceptions
from django.conf import settings
from keycloak import KeycloakOpenID
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)

class KeycloakAuthentication(authentication.BaseAuthentication):
    def __init__(self):
        base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
        self.keycloak_openid = KeycloakOpenID(
            server_url=base_url + "/",
            client_id=settings.OIDC_RP_CLIENT_ID,
            realm_name=settings.KEYCLOAK_REALM,
            client_secret_key=settings.OIDC_RP_CLIENT_SECRET,
            verify=True
        )

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return None

        token = parts[1]

        try:
            KEYCLOAK_PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\n" + self.keycloak_openid.public_key() + "\n-----END PUBLIC KEY-----"
            options = {"verify_signature": True, "verify_aud": False, "exp": True}
            
            token_info = self.keycloak_openid.decode_token(
                token,
                key=KEYCLOAK_PUBLIC_KEY,
                options=options
            )
            
            email = token_info.get('email')
            if not email:
                email = token_info.get('preferred_username')
                
            if not email:
                raise exceptions.AuthenticationFailed("Le token ne contient pas d'adresse email.")

            realm_access = token_info.get('realm_access', {})
            roles = realm_access.get('roles', [])

            # Inject roles into the request for our custom permissions
            request.roles = roles

            # Mapping the authenticated Keycloak user to a Django user
            user, created = User.objects.get_or_create(username=email)
            if created:
                user.email = email
                user.first_name = token_info.get('given_name', '')
                user.last_name = token_info.get('family_name', '')
                user.save()

            return (user, token)

        except Exception as e:
            logger.error(f"Keycloak Authentication Failed: {str(e)}")
            raise exceptions.AuthenticationFailed('Token invalide ou expiré.')

    def authenticate_header(self, request):
        return 'Bearer'
