from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.conf import settings
from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError
from .models import Profil
from .authentication import KeycloakAuthentication
import requests

class CreerUtilisateurView(APIView):
    # Idéalement, seul un IsAdmin ou IsChefDeService peut appeler cette route
    # Mais pour tester facilement sans token depuis le frontend, on utilise AllowAny
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data

        required_fields = ['role', 'prenom', 'nom', 'email', 'password_provisoire']
        for field in required_fields:
            if field not in data:
                return Response({"error": f"Champ manquant: {field}"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 1. Connecter Django à Keycloak en tant qu'admin
            keycloak_admin = KeycloakAdmin(
                server_url=settings.KEYCLOAK_SERVER_URL,
                username=settings.KEYCLOAK_ADMIN_USER,
                password=settings.KEYCLOAK_ADMIN_PASSWORD,
                realm_name=settings.KEYCLOAK_REALM,
                user_realm_name="master",
                verify=True
            )

            # 2. Créer l'utilisateur dans Keycloak
            kc_payload = {
                "username": data['email'],
                "email": data['email'],
                "firstName": data['prenom'],
                "lastName": data['nom'],
                "enabled": True,
                "credentials": [{"value": data['password_provisoire'], "type": "password", "temporary": True}]
            }
            if data.get('createdBy') or data.get('telephone'):
                kc_payload["attributes"] = {}
                if data.get('createdBy'):
                    kc_payload["attributes"]["createdBy"] = [data['createdBy']]
                if data.get('telephone'):
                    kc_payload["attributes"]["phone"] = [data['telephone']]
                
            user_id = keycloak_admin.create_user(kc_payload)

            # 3. Assigner le Rôle dans Keycloak
            # Le nom du rôle dans la requête doit correspondre à un rôle existant dans Keycloak (ex: CHEF_SERVICE, MEDECIN)
            role = keycloak_admin.get_realm_role(data['role'])
            if role:
                keycloak_admin.assign_realm_roles(user_id, [role])
            else:
                # Si le rôle n'existe pas, on supprime l'utilisateur et on renvoie une erreur
                keycloak_admin.delete_user(user_id)
                return Response({"error": f"Le rôle '{data['role']}' n'existe pas dans Keycloak."}, status=status.HTTP_400_BAD_REQUEST)

            # 4. Créer dans Postgres (Modèle User Django)
            # On utilise try/except au cas où l'utilisateur existerait déjà côté Django
            user, created = User.objects.get_or_create(
                username=data['email'],
                defaults={'email': data['email'], 'first_name': data['prenom'], 'last_name': data['nom']}
            )

            # 5. Créer ou mettre à jour le Profil
            role_map = {
                'ADMIN_SYSTEME': 'Admin',
                'CHEF_SERVICE': 'Chef',
                'OPHTALMOLOGUE': 'Medecin',
                'RESIDENT': 'Resident'
            }
            mapped_role = role_map.get(data['role'], data['role'])

            profil_defaults = {'role': mapped_role}
            if 'telephone' in data:
                profil_defaults['telephone'] = data['telephone']

            profil, _ = Profil.objects.update_or_create(
                user=user,
                defaults=profil_defaults
            )

            creator_role = data.get('creatorRole')
            # Nous n'assignons plus d'examens automatiquement à la création
            # Les assignations se feront uniquement via les sessions de calendrier


            # 6. Envoyer l'email de bienvenue avec les identifiants
            from django.core.mail import send_mail
            sujet = "Bienvenue sur Télé-rétinographie - Vos identifiants"
            lien_login = "http://193.95.31.196/login"
            
            message = f"""Bonjour Dr {data['prenom']} {data['nom']},
            
Votre compte Télé-rétinographie a été créé avec succès.
            
Voici vos identifiants pour vous connecter :
Email : {data['email']}
Mot de passe provisoire : {data['password_provisoire']}
            
Vous pouvez vous connecter à cette adresse : {lien_login}
            
Cordialement,
L'équipe Télé-rétinographie.
"""
            try:
                send_mail(
                    sujet,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [data['email']],
                    fail_silently=False,
                )
                return Response({"message": f"{data['prenom']} {data['nom']} ajouté(e) et email envoyé !", "keycloak_id": user_id}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"message": "Utilisateur créé mais échec de l'envoi du mail", "error": str(e), "keycloak_id": user_id}, status=status.HTTP_201_CREATED)

        except KeycloakError as e:
            return Response({"error": f"Erreur Keycloak: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Erreur interne: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response({'error': 'Email et mot de passe requis.'}, status=status.HTTP_400_BAD_REQUEST)

        # URL de l'endpoint Token de Keycloak
        # On s'assure qu'il n'y a pas de double slash
        base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
        token_url = f"{base_url}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"

        payload = {
            'client_id': settings.OIDC_RP_CLIENT_ID,
            'grant_type': 'password',
            'username': email,
            'password': password,
        }
        
        # Only add client_secret if it has been properly configured
        if hasattr(settings, 'OIDC_RP_CLIENT_SECRET') and settings.OIDC_RP_CLIENT_SECRET != 'VOTRE_SECRET_KEYCLOAK':
            payload['client_secret'] = settings.OIDC_RP_CLIENT_SECRET

        try:
            # Appel à Keycloak pour récupérer le token
            response = requests.post(token_url, data=payload)
            if response.status_code == 200:
                # On renvoie les tokens (access_token, refresh_token) au frontend
                return Response(response.json(), status=status.HTTP_200_OK)
            else:
                error_data = response.json()
                error_msg = error_data.get('error_description', 'Identifiants invalides')
                error_code = error_data.get('error')
                return Response({'error': error_msg, 'error_code': error_code}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({'error': 'Impossible de joindre Keycloak.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ForcerNouveauMotPasseView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get('username')
        new_password = request.data.get('new_password')
        
        if not username or not new_password:
            return Response({"error": "Données incomplètes"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            keycloak_admin = KeycloakAdmin(
                server_url=settings.KEYCLOAK_SERVER_URL,
                username=settings.KEYCLOAK_ADMIN_USER,
                password=settings.KEYCLOAK_ADMIN_PASSWORD,
                realm_name=settings.KEYCLOAK_REALM,
                user_realm_name="master",
                verify=True
            )

            # La variable 'username' envoyée par le frontend est en fait l'email.
            # Keycloak permet de se connecter avec l'email, mais get_user_id cherche par username exact.
            # On va donc chercher l'utilisateur par email.
            users = keycloak_admin.get_users({"email": username, "exact": True})
            
            if not users:
                # Si pas trouvé par email, on tente par username exact au cas où
                user_id = keycloak_admin.get_user_id(username)
            else:
                user_id = users[0]['id']

            if not user_id:
                return Response({"error": "Utilisateur introuvable"}, status=status.HTTP_404_NOT_FOUND)

            user_info = keycloak_admin.get_user(user_id)
            if "UPDATE_PASSWORD" in user_info.get("requiredActions", []):
                user_info["requiredActions"].remove("UPDATE_PASSWORD")
                keycloak_admin.update_user(user_id, payload=user_info)

            keycloak_admin.set_user_password(user_id, new_password, temporary=False)

            return Response({"message": "Mot de passe configuré avec succès !"}, status=status.HTTP_200_OK)

        except KeycloakError as e:
            return Response({"error": f"Erreur Keycloak: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Erreur interne: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Configuration (à mettre dans settings.py normalement)
KC_URL = "http://localhost:8080"
KC_REALM = "HopitalRealm"
KC_CLIENT_ID = "django-backend"
KC_CLIENT_SECRET = "VOTRE_SECRET_COPIE_DE_KEYCLOAK"

@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def forgot_password_relay(request):
    email = request.data.get('email')
    if not email:
        return JsonResponse({"error": "Email requis"}, status=400)

    try:
        # Utiliser KeycloakAdmin comme pour les autres vues (évite les erreurs 500 dues au mauvais client_secret)
        keycloak_admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=settings.KEYCLOAK_ADMIN_USER,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True
        )

        # 1. Chercher l'ID de l'utilisateur par son email
        users = keycloak_admin.get_users({"email": email, "exact": True})

        if not users:
            # Pour la sécurité, on ne dit pas si l'email existe ou pas
            return JsonResponse({"message": "Si l'email existe, un lien a été envoyé."})

        user_id = users[0]['id']

        # 2. Demander à Keycloak d'envoyer l'email "UPDATE_PASSWORD"
        base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
        realm = settings.KEYCLOAK_REALM
        action_url = f"{base_url}/admin/realms/{realm}/users/{user_id}/execute-actions-email"
        
        # On récupère le token de l'admin
        admin_token = keycloak_admin.token['access_token']
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        params = ["UPDATE_PASSWORD"]
        
        action_res = requests.put(action_url, headers=headers, json=params)

        if action_res.status_code == 204 or action_res.status_code == 200:
            return JsonResponse({"message": "Email de réinitialisation envoyé !"})
        else:
            return JsonResponse({"error": f"Erreur Keycloak: {action_res.text}"}, status=500)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

from django.core.mail import send_mail
from .models import PasswordResetToken
from keycloak import KeycloakAdmin, KeycloakError

@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def request_password_reset(request):
    email = request.data.get('email')
    if not email:
        return Response({"error": "Email manquant"}, status=400)
    
    # 1. Vérifier si l'utilisateur existe dans Keycloak
    try:
        keycloak_admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=settings.KEYCLOAK_ADMIN_USER,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True
        )
        users = keycloak_admin.get_users({"email": email, "exact": True})
        if not users:
            return Response({"message": "Si l'email existe, un lien a été envoyé."})
        prenom_medecin = users[0].get('firstName', '')
        nom_medecin = users[0].get('lastName', '')
    except Exception as e:
        return Response({"error": f"Erreur avec Keycloak: {str(e)}"}, status=500)

    # 2. Créer un token dans Django
    reset_obj = PasswordResetToken.objects.create(email=email)
    
    # 3. Envoyer le mail vers REACT
    link = f"http://193.95.31.196/reset-password?token={reset_obj.token}"
    sujet = "[Télé-rétinographie] Demande de réinitialisation de votre mot de passe"
    message = f"""Bonjour Dr {prenom_medecin} {nom_medecin},

Nous avons reçu une demande de réinitialisation de mot de passe pour votre compte sur la plateforme Télé-rétinographie.

Pour configurer un nouveau mot de passe, veuillez cliquer sur le lien ci-dessous :
{link}

Cordialement,

L'équipe Télé-rétinographie
Plateforme de Télédépistage de la Rétinopathie
"""
    send_mail(
        sujet,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [email]
    )
    return Response({"message": "Lien envoyé à votre adresse email !"})

@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def confirm_password_reset(request):
    token = request.data.get('token')
    new_password = request.data.get('password')
    
    # 1. Valider le token Django
    try:
        reset_obj = PasswordResetToken.objects.get(token=token)
    except:
        return Response({"error": "Lien invalide"}, status=400)

    try:
        # 2. Obtenir l'ID utilisateur de Keycloak
        keycloak_admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=settings.KEYCLOAK_ADMIN_USER,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True
        )
        users = keycloak_admin.get_users({"email": reset_obj.email, "exact": True})
        if not users:
            return Response({"error": "Utilisateur introuvable dans Keycloak"}, status=404)
            
        user_id = users[0]['id']
        
        # 3. Changer le mot de passe dans Keycloak
        keycloak_admin.set_user_password(user_id, new_password, temporary=False)
        
    except Exception as e:
        return Response({"error": f"Erreur Keycloak: {str(e)}"}, status=500)

    # 4. Supprimer le token utilisé
    reset_obj.delete()
    return Response({"message": "Mot de passe mis à jour avec succès !", "email": reset_obj.email})


@api_view(['GET'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def get_keycloak_events(request):
    try:
        # 1. Connect to Keycloak as admin
        keycloak_admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=settings.KEYCLOAK_ADMIN_USER,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True
        )
        
        # Get admin token
        admin_token = keycloak_admin.token['access_token']
        
        # 2. Get events from Keycloak admin API (request up to 1000 to allow sorting/filtering in Python)
        events_url = f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/admin/realms/{settings.KEYCLOAK_REALM}/events?type=LOGIN&type=LOGOUT&max=1000"
        headers = {'Authorization': f'Bearer {admin_token}'}
        
        events_res = requests.get(events_url, headers=headers)
        if events_res.status_code != 200:
            return JsonResponse({"error": f"Failed to retrieve events from Keycloak: {events_res.text}"}, status=events_res.status_code)
            
        raw_events = events_res.json()
        
        # 3. Resolve roles locally from Postgres database to optimize performance
        from datetime import datetime
        
        # Map user role codes to frontend string names
        def map_role(kc_role):
            if not kc_role:
                return "Medecin"
            kc_role_upper = kc_role.upper()
            if kc_role_upper in ["ADMIN_SYSTEME", "ADMIN"]:
                return "Admin"
            elif kc_role_upper == "CHEF_SERVICE":
                return "Chef"
            elif kc_role_upper == "RESIDENT":
                return "Resident"
            else:
                return "Medecin"

        # Get all local user profile roles in one query
        profiles = {
            p.user.username.lower(): p.role 
            for p in Profil.objects.select_related('user').all() 
            if p.user and p.user.username
        }
        
        formatted_logs = []
        for event in raw_events:
            username = event.get('details', {}).get('username', '')
            user_role = profiles.get(username.lower())
            
            # Map role
            role_label = map_role(user_role)
            
            # Convert millisecond timestamp to ISO string for the frontend (or datetime)
            try:
                dt = datetime.fromtimestamp(event['time'] / 1000.0)
                at_iso = dt.isoformat() + "Z"
            except Exception:
                at_iso = datetime.now().isoformat() + "Z"
                
            formatted_logs.append({
                "id": event.get('id') or f"{event['time']}-{username}",
                "userName": username or "Inconnu",
                "role": role_label,
                "at": at_iso,
                "action": "login" if event['type'] == "LOGIN" else "logout"
            })
            
        # 4. Extract query params for filtering and pagination
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('size', 10))
        search = request.GET.get('search', '').lower()
        today_only = request.GET.get('todayOnly', 'false').lower() == 'true'
        allowed_emails_str = request.GET.get('allowedEmails', '')
        allowed_emails = [e.strip().lower() for e in allowed_emails_str.split(',')] if allowed_emails_str else None

        from datetime import datetime, timezone
        today_str = datetime.now().date().isoformat()
        
        filtered_logs = []
        for log in formatted_logs:
            # Search filter
            if search and search not in log['userName'].lower() and search not in log['role'].lower():
                continue
                
            # Allowed emails filter
            if allowed_emails is not None and log['userName'].lower() not in allowed_emails:
                continue
                
            # Today filter
            if today_only and log['at'][:10] != today_str:
                continue
                
            filtered_logs.append(log)
            
        # Sort by 'at' descending (newest first)
        filtered_logs.sort(key=lambda x: x['at'], reverse=True)
        
        # Paginate
        total_count = len(filtered_logs)
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
        first = (page - 1) * page_size
        paginated_logs = filtered_logs[first:first+page_size]
        
        return JsonResponse({
            "logs": paginated_logs,
            "total": total_count,
            "page": page,
            "total_pages": total_pages
        })
        
    except KeycloakError as e:
        return JsonResponse({"error": f"Keycloak error: {str(e)}"}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Internal error: {str(e)}"}, status=500)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def logout_relay(request):
    refresh_token = request.data.get('refresh_token')
    if not refresh_token:
        return Response({'error': 'Refresh token requis.'}, status=400)
        
    base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
    logout_url = f"{base_url}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/logout"
    
    payload = {
        'client_id': settings.OIDC_RP_CLIENT_ID,
        'refresh_token': refresh_token,
    }
    if hasattr(settings, 'OIDC_RP_CLIENT_SECRET') and settings.OIDC_RP_CLIENT_SECRET != 'VOTRE_SECRET_KEYCLOAK':
        payload['client_secret'] = settings.OIDC_RP_CLIENT_SECRET
        
    try:
        response = requests.post(logout_url, data=payload)
        if response.status_code == 204 or response.status_code == 200:
            return Response({'message': 'Déconnexion réussie.'}, status=200)
        else:
            return Response({'error': 'Erreur lors de la déconnexion Keycloak.', 'details': response.text}, status=response.status_code)
    except Exception as e:
        return Response({'error': str(e)}, status=500)


@api_view(['PUT'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def update_keycloak_user(request):
    try:
        data = request.data
        old_email = data.get('old_email')
        new_email = data.get('email')
        prenom = data.get('prenom')
        nom = data.get('nom')
        telephone = data.get('telephone')
        new_role_code = data.get('role') # e.g., 'ADMIN_SYSTEME', 'CHEF_SERVICE', 'OPHTALMOLOGUE', 'RESIDENT'
        
        if not old_email or not new_email:
            return Response({"error": "old_email et email sont requis"}, status=400)

        # 1. Connect to Keycloak as admin
        keycloak_admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=settings.KEYCLOAK_ADMIN_USER,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True
        )
        
        # 2. Search for Keycloak user ID using old_email
        kc_users = keycloak_admin.get_users({"email": old_email, "exact": True})
        if not kc_users:
            return Response({"error": f"Utilisateur {old_email} introuvable dans Keycloak"}, status=404)
        
        user_id = kc_users[0]['id']
        
        # 3. Update user in Keycloak
        payload = {
            "firstName": prenom,
            "lastName": nom,
            "email": new_email,
            "username": new_email,
            "attributes": kc_users[0].get('attributes', {})
        }
        if telephone:
            if not payload['attributes']:
                payload['attributes'] = {}
            payload['attributes']['phone'] = [telephone]
            
        keycloak_admin.update_user(user_id, payload)
        
        # Update password if provided
        new_password = data.get('password')
        old_password = data.get('old_password')
        
        if new_password:
            if not old_password:
                return Response({"error": "L'ancien mot de passe est requis pour le modifier."}, status=400)
            
            # Vérifier l'ancien mot de passe
            base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
            token_url = f"{base_url}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
            token_payload = {
                'client_id': settings.OIDC_RP_CLIENT_ID,
                'grant_type': 'password',
                'username': old_email,
                'password': old_password,
            }
            if hasattr(settings, 'OIDC_RP_CLIENT_SECRET') and settings.OIDC_RP_CLIENT_SECRET != 'VOTRE_SECRET_KEYCLOAK':
                token_payload['client_secret'] = settings.OIDC_RP_CLIENT_SECRET
                
            token_res = requests.post(token_url, data=token_payload)
            if token_res.status_code != 200:
                return Response({"error": "L'ancien mot de passe est incorrect."}, status=400)
                
            # Si correct, on met à jour le mot de passe
            keycloak_admin.set_user_password(user_id, new_password, temporary=False)
        
        # 3.5 Role assignment in Keycloak if role is provided
        if new_role_code:
            try:
                # Get current user roles in Keycloak
                user_roles = keycloak_admin.get_realm_roles_of_user(user_id)
                # Remove existing app roles to avoid duplicate/conflicting roles
                app_roles_to_remove = [r for r in user_roles if r['name'] in ['ADMIN_SYSTEME', 'CHEF_SERVICE', 'OPHTALMOLOGUE', 'RESIDENT']]
                if app_roles_to_remove:
                    keycloak_admin.delete_realm_roles_of_user(user_id, app_roles_to_remove)
                    
                # Get the new role object and assign it
                kc_role = keycloak_admin.get_realm_role(new_role_code)
                if kc_role:
                    keycloak_admin.assign_realm_roles(user_id, [kc_role])
            except Exception as role_err:
                print(f"Error updating Keycloak roles: {role_err}")
        
        # 4. Update local Django Database (Postgres)
        role_map = {
            'ADMIN_SYSTEME': 'Admin',
            'CHEF_SERVICE': 'Chef',
            'OPHTALMOLOGUE': 'Medecin',
            'RESIDENT': 'Resident'
        }
        mapped_role = role_map.get(new_role_code) if new_role_code else None

        try:
            django_user = User.objects.get(username=old_email)
            django_user.username = new_email
            django_user.email = new_email
            django_user.first_name = prenom
            django_user.last_name = nom
            django_user.save()
            
            defaults = {}
            if telephone:
                defaults['telephone'] = telephone
            if mapped_role:
                defaults['role'] = mapped_role
                
            if defaults:
                Profil.objects.update_or_create(
                    user=django_user,
                    defaults=defaults
                )
        except User.DoesNotExist:
            # If django user is not found, we can create it
            django_user = User.objects.create(
                username=new_email,
                email=new_email,
                first_name=prenom,
                last_name=nom
            )
            defaults = {'user': django_user}
            if telephone:
                defaults['telephone'] = telephone
            if mapped_role:
                defaults['role'] = mapped_role
            Profil.objects.create(**defaults)
            
        return Response({"status": "success", "message": "Utilisateur mis à jour avec succès"})
        
    except KeycloakError as e:
        return Response({"error": f"Erreur Keycloak: {str(e)}"}, status=400)
    except Exception as e:
        return Response({"error": f"Erreur interne: {str(e)}"}, status=500)



@api_view(['GET'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def get_paginated_users(request):
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('size', 10))
        search = request.GET.get('search', '').strip()
        role_filter = request.GET.get('role', '').strip()
        created_by = request.GET.get('createdBy', '').strip()
        
        first = (page - 1) * page_size
        
        # 1. Connect to Keycloak
        keycloak_admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=settings.KEYCLOAK_ADMIN_USER,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True
        )
        admin_token = keycloak_admin.token['access_token']
        headers = {'Authorization': f'Bearer {admin_token}'}
        base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
        realm = settings.KEYCLOAK_REALM
        
        # Determine the Keycloak role if filtering
        kc_role = None
        if role_filter == "Admin": kc_role = "ADMIN_SYSTEME"
        elif role_filter == "Chef": kc_role = "CHEF_SERVICE"
        elif role_filter == "Medecin": kc_role = "OPHTALMOLOGUE"
        elif role_filter == "Resident": kc_role = "RESIDENT"

        # Enrichir avec la base de données locale (Profil)
        profiles = {
            p.user.username.lower(): p 
            for p in Profil.objects.select_related('user').all() 
            if p.user and p.user.username
        }
        
        users_res = []
        total_count = 0
        
        if created_by:
            users_url = f"{base_url}/admin/realms/{realm}/users?q=createdBy:\"{created_by}\"&max=1000"
            all_chef_users = requests.get(users_url, headers=headers).json()
            if not isinstance(all_chef_users, list): all_chef_users = []
            
            if search:
                s = search.lower()
                all_chef_users = [u for u in all_chef_users if s in u.get('firstName', '').lower() or s in u.get('lastName', '').lower() or s in u.get('email', '').lower()]
                
            if role_filter:
                all_chef_users = [u for u in all_chef_users if profiles.get(u.get('username', u.get('email', '')).lower()) and profiles.get(u.get('username', u.get('email', '')).lower()).role == role_filter]

            total_count = len(all_chef_users)
            users_res = all_chef_users[first:first+page_size]
            
        elif kc_role:
            users_url = f"{base_url}/admin/realms/{realm}/roles/{kc_role}/users?first={first}&max={page_size}"
            users_res = requests.get(users_url, headers=headers).json()
            total_count = Profil.objects.filter(role=role_filter).count()
        else:
            query_params = []
            if search:
                query_params.append(f"search={search}")
            query_str = "&".join(query_params)
            if query_str: query_str = f"?{query_str}"
                
            count_url = f"{base_url}/admin/realms/{realm}/users/count{query_str}"
            total_count = requests.get(count_url, headers=headers).json()
            
            users_url = f"{base_url}/admin/realms/{realm}/users?first={first}&max={page_size}"
            if query_str: users_url += f"&search={search}"
            users_res = requests.get(users_url, headers=headers).json()
            
        formatted_users = []
        for u in users_res:
            email = u.get('email', '')
            username = u.get('username', email)
            prof = profiles.get(username.lower())
            
            local_role = prof.role if prof and prof.role else "Medecin"
            
            # Re-map Keycloak role names to Frontend role names if needed
            role_map_reverse = {
                'ADMIN_SYSTEME': 'Admin',
                'CHEF_SERVICE': 'Chef',
                'OPHTALMOLOGUE': 'Medecin',
                'RESIDENT': 'Resident'
            }
            local_role = role_map_reverse.get(local_role, local_role)

            telephone = prof.telephone if prof and prof.telephone else (u.get('attributes', {}).get('phone', [''])[0] if u.get('attributes') else '')
            created_by_attr = u.get('attributes', {}).get('createdBy', [''])[0] if u.get('attributes') else ''
            
            is_disponible = prof.is_disponible if prof else True
            charge_actuelle = prof.charge_actuelle if prof else 0
            
            created_at = u.get('createdTimestamp', 0)
            from datetime import datetime
            created_at_iso = datetime.fromtimestamp(created_at / 1000.0).isoformat() + "Z" if created_at else ""

            formatted_users.append({
                "id": u.get('id'),
                "email": email,
                "firstName": u.get('firstName', ''),
                "lastName": u.get('lastName', ''),
                "role": local_role,
                "phone": telephone,
                "createdAt": created_at_iso,
                "createdBy": created_by_attr,
                "is_disponible": is_disponible,
                "charge_actuelle": charge_actuelle
            })
            
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0

        return JsonResponse({
            "users": formatted_users,
            "total": total_count,
            "page": page,
            "total_pages": total_pages
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def get_user_stats(request):
    try:
        created_by = request.GET.get('createdBy', '').strip()
        
        if created_by:
            # Si le paramètre createdBy est fourni, on interroge Keycloak pour avoir les statistiques exactes de ce Chef
            keycloak_admin = KeycloakAdmin(
                server_url=settings.KEYCLOAK_SERVER_URL,
                username=settings.KEYCLOAK_ADMIN_USER,
                password=settings.KEYCLOAK_ADMIN_PASSWORD,
                realm_name=settings.KEYCLOAK_REALM,
                user_realm_name="master",
                verify=True
            )
            admin_token = keycloak_admin.token['access_token']
            headers = {'Authorization': f'Bearer {admin_token}'}
            base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
            realm = settings.KEYCLOAK_REALM
            
            users_url = f"{base_url}/admin/realms/{realm}/users?q=createdBy:\"{created_by}\"&max=1000"
            all_chef_users = requests.get(users_url, headers=headers).json()
            if not isinstance(all_chef_users, list): all_chef_users = []
            
            # Pour récupérer les rôles locaux
            profiles = {
                p.user.username.lower(): p 
                for p in Profil.objects.select_related('user').all() 
                if p.user and p.user.username
            }
            
            chefs = 0
            medecins = 0
            residents = 0
            
            for u in all_chef_users:
                username = u.get('username', u.get('email', '')).lower()
                prof = profiles.get(username)
                if prof:
                    if prof.role == "Chef": chefs += 1
                    elif prof.role == "Medecin": medecins += 1
                    elif prof.role == "Resident": residents += 1
                    
            total = len(all_chef_users)
            
            return JsonResponse({
                "total": total,
                "chefs": chefs,
                "medecins": medecins,
                "residents": residents
            })
            
        else:
            # Pour les statistiques globales (Admin), on interroge Keycloak pour avoir les bons chiffres
            keycloak_admin = KeycloakAdmin(
                server_url=settings.KEYCLOAK_SERVER_URL,
                username=settings.KEYCLOAK_ADMIN_USER,
                password=settings.KEYCLOAK_ADMIN_PASSWORD,
                realm_name=settings.KEYCLOAK_REALM,
                user_realm_name="master",
                verify=True
            )
            admin_token = keycloak_admin.token['access_token']
            headers = {'Authorization': f'Bearer {admin_token}'}
            base_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
            realm = settings.KEYCLOAK_REALM
            
            # Nombre total
            count_url = f"{base_url}/admin/realms/{realm}/users/count"
            total = requests.get(count_url, headers=headers).json()
            
            # Pour les rôles, Keycloak n'a pas de /count sur les rôles, on récupère la liste (sans limite de pagination pour avoir le compte)
            def count_role(role_name):
                url = f"{base_url}/admin/realms/{realm}/roles/{role_name}/users?max=10000"
                res = requests.get(url, headers=headers)
                if res.status_code == 200:
                    return len(res.json())
                return 0
                
            chefs = count_role("CHEF_SERVICE")
            medecins = count_role("OPHTALMOLOGUE")
            residents = count_role("RESIDENT")
            
            return JsonResponse({
                "total": total,
                "chefs": chefs,
                "medecins": medecins,
                "residents": residents
            })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([]) # Ajuster l'authentification selon vos besoins
@permission_classes([permissions.AllowAny])
def toggle_medecin_status_admin(request):
    """
    Endpoint pour l'admin : bascule la disponibilité d'un médecin.
    S'il devient indisponible, ses examens sont réassignés.
    """
    email = request.data.get('email')
    if not email:
        return Response({"error": "L'email du médecin est requis"}, status=400)
        
    try:
        # On utilise get_or_create pour éviter les erreurs 404 si le profil local n'existe pas encore
        # On essaie d'abord de trouver par email si le username est différent (comme pour admin)
        user = User.objects.filter(email=email).first()
        if not user:
            user, _ = User.objects.get_or_create(username=email, defaults={'email': email})
            
        profil, _ = Profil.objects.get_or_create(user=user, defaults={'role': 'Medecin'})
        
        # Toggle de la disponibilité
        if profil.is_disponible:
            # S'il était disponible, on le rend indisponible et on réassigne ses examens
            from ophtalmo.distribution import rendre_indisponible_et_reassigner
            reassigned_count = rendre_indisponible_et_reassigner(user.id)
            message = f"Médecin rendu indisponible. {reassigned_count} examens réassignés."
        else:
            # S'il était indisponible, on le rend disponible et on distribue de nouveaux examens
            from ophtalmo.distribution import distribuer_examens
            profil.is_disponible = True
            profil.save(update_fields=['is_disponible'])
            distribuer_examens()
            message = "Médecin de nouveau disponible et prêt à recevoir des examens."
            
        profil.refresh_from_db()
            
        return Response({
            "status": "success", 
            "message": message, 
            "is_disponible": profil.is_disponible, 
            "charge_actuelle": profil.charge_actuelle
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": f"Erreur serveur : {str(e)}"}, status=500)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def assign_session(request):
    """
    Crée N examens 'En cours' assignés au médecin ciblé,
    et met à jour sa charge_actuelle.
    """
    email = request.data.get('email')
    try:
        count = int(request.data.get('count', 1))
    except (ValueError, TypeError):
        count = 1
        
    start_hour = int(request.data.get('startHour', 8))
    end_hour = int(request.data.get('endHour', 10))
    date_str = request.data.get('date')
    
    if not email:
        return Response({'error': 'Email requis'}, status=400)
        
    try:
        from django.contrib.auth.models import User
        from ophtalmo.models import Exam, CalendarSession
        from datetime import date, datetime
        
        try:
            user = User.objects.get(username__iexact=email)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                return Response({'error': 'Utilisateur introuvable'}, status=404)

        if date_str:
            try:
                session_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                session_date = date.today()
        else:
            session_date = date.today()

        profil = user.profil
        
        a_assigner = count
        if a_assigner <= 0:
            return Response({'error': 'Le nombre d\'examens doit être supérieur à 0.'}, status=400)
            
        from django.db.models import Count
        from django.utils import timezone
        
        actual_assigned = 0
        now = timezone.now()
        today = timezone.localdate()
        
        # On n'assigne immédiatement que si la session est pour aujourd'hui
        if session_date == today:
            region_counts_qs = Exam.objects.filter(status='En cours').values('region').annotate(count=Count('id'))
            region_counts = {item['region']: item['count'] for item in region_counts_qs if item['region']}
            
            exams_attente = list(Exam.objects.filter(status='En attente', assigned_to__isnull=True))
            
            if exams_attente:
                def sort_key(exam):
                    prio = 0 if exam.priority == 'Urgent' else 1
                    age = exam.date
                    region_count = region_counts.get(exam.region, 0)
                    return (prio, age, region_count, exam.id)
                    
                exams_attente.sort(key=sort_key)
                
                exams_to_assign = exams_attente[:a_assigner]
                actual_assigned = len(exams_to_assign)
                
                for exam in exams_to_assign:
                    exam.assigned_to = user
                    exam.status = 'En cours'
                    exam.date_assignation = now
                    exam.save(update_fields=['assigned_to', 'status', 'date_assignation'])
                    
                profil.charge_actuelle += actual_assigned
                profil.save(update_fields=['charge_actuelle'])
        
        session_obj = CalendarSession.objects.create(
            doctor=user,
            date=session_date,
            start_hour=start_hour,
            end_hour=end_hour,
            count=count,
            affiliation="Assignation manuelle",
            hospital="Cabinet"
        )
        
        role = user.profil.role if hasattr(user, 'profil') else "Medecin"
        title = "Pr" if role == "Chef" else "Dr"
        
        if session_date == today:
            msg = f'{actual_assigned} examens assignés au Dr {user.last_name}.'
            if actual_assigned < a_assigner:
                msg += f' (Il ne restait que {actual_assigned} examens disponibles sur les {a_assigner} demandés).'
        else:
            msg = f"Session planifiée. Les {a_assigner} examens seront assignés automatiquement le jour J."
            
        return Response({
            'message': msg, 
            'assigned': actual_assigned,
            'session': {
                'id': session_obj.id,
                'doctorName': f"{title} {user.first_name} {user.last_name}".strip(),
                'email': user.email,
                'date': session_obj.date.isoformat(),
                'startHour': session_obj.start_hour,
                'endHour': session_obj.end_hour,
                'count': session_obj.count,
                'affiliation': session_obj.affiliation,
                'hospital': session_obj.hospital,
                'parsedDate': session_obj.date.isoformat()
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': str(e)}, status=500)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_sessions(request):
    from ophtalmo.models import CalendarSession
    sessions = CalendarSession.objects.all()
    data = []
    for s in sessions:
        role = s.doctor.profil.role if hasattr(s.doctor, 'profil') else "Medecin"
        title = "Pr" if role == "Chef" else "Dr"
        data.append({
            'id': s.id,
            'doctorName': f"{title} {s.doctor.first_name} {s.doctor.last_name}".strip(),
            'email': s.doctor.email,
            'date': s.date.isoformat(),
            'startHour': s.start_hour,
            'endHour': s.end_hour,
            'count': s.count,
            'affiliation': s.affiliation,
            'hospital': s.hospital,
            'parsedDate': s.date.isoformat()
        })
    return Response({'sessions': data})

def fill_incomplete_sessions(target_date):
    """
    Parcourt toutes les sessions du jour 'target_date' et tente d'assigner
    des examens aux sessions incomplètes (dont le quota n'est pas atteint).
    """
    from ophtalmo.models import CalendarSession, Exam
    from django.db.models import Count
    from django.utils import timezone
    
    sessions_today = CalendarSession.objects.filter(date=target_date)
    
    doctor_requests = {}
    for session in sessions_today:
        if session.doctor_id not in doctor_requests:
            doctor_requests[session.doctor_id] = {'doctor': session.doctor, 'requested': 0}
        doctor_requests[session.doctor_id]['requested'] += session.count
        
    for doc_id, data in doctor_requests.items():
        doctor = data['doctor']
        current_assigned = Exam.objects.filter(assigned_to=doctor, status='En cours').count()
        shortage = data['requested'] - current_assigned
        
        if shortage > 0:
            region_counts_qs = Exam.objects.filter(status='En cours').values('region').annotate(count=Count('id'))
            region_counts = {item['region']: item['count'] for item in region_counts_qs if item['region']}
            
            exams_attente = list(Exam.objects.filter(status='En attente', assigned_to__isnull=True))
            if not exams_attente:
                break
                
            def sort_key(exam):
                prio = 0 if exam.priority == 'Urgent' else 1
                age = exam.date.toordinal() if exam.date else 0
                region_count = region_counts.get(exam.region, 0)
                return (prio, age, region_count, exam.id)
                
            exams_attente.sort(key=sort_key)
            exams_to_assign = exams_attente[:shortage]
            
            now = timezone.now()
            actual_assigned = 0
            for exam in exams_to_assign:
                exam.assigned_to = doctor
                exam.status = 'En cours'
                exam.date_assignation = now
                exam.save(update_fields=['assigned_to', 'status', 'date_assignation'])
                actual_assigned += 1
                
            if hasattr(doctor, 'profil'):
                profil = doctor.profil
                profil.charge_actuelle += actual_assigned
                profil.save(update_fields=['charge_actuelle'])

@api_view(['DELETE'])
@permission_classes([permissions.AllowAny])
def delete_session(request, session_id):
    from ophtalmo.models import CalendarSession
    try:
        session_obj = CalendarSession.objects.get(id=session_id)
        doctor = session_obj.doctor
        count_to_remove = session_obj.count
        session_date = session_obj.date
        
        from ophtalmo.models import Exam
        exams_to_unassign = Exam.objects.filter(assigned_to=doctor, status='En cours')[:count_to_remove]
        
        unassigned_count = 0
        from django.utils import timezone
        today = timezone.localdate()
        
        if session_date == today:
            for exam in exams_to_unassign:
                exam.status = 'En attente'
                exam.assigned_to = None
                exam.date_assignation = None
                exam.save(update_fields=['status', 'assigned_to', 'date_assignation'])
                unassigned_count += 1
                
            if hasattr(doctor, 'profil'):
                profil = doctor.profil
                profil.charge_actuelle = max(0, profil.charge_actuelle - unassigned_count)
                profil.save(update_fields=['charge_actuelle'])

        session_obj.delete()
        
        if session_date == today:
            fill_incomplete_sessions(session_date)
            return Response({'message': f'Session supprimée et {unassigned_count} examens remis en attente (et potentiellement redistribués)'})
        else:
            return Response({'message': 'Session future supprimée avec succès.'})
    except CalendarSession.DoesNotExist:
        return Response({'error': 'Session introuvable'}, status=404)

@api_view(['PUT'])
@permission_classes([permissions.AllowAny])
def update_session(request, session_id):
    from ophtalmo.models import CalendarSession
    from django.contrib.auth.models import User
    try:
        session_obj = CalendarSession.objects.get(id=session_id)
        email = request.data.get('email')
        if email:
            try:
                user = User.objects.get(email__iexact=email)
                session_obj.doctor = user
            except User.DoesNotExist:
                pass
        
        old_count = session_obj.count
        new_count = int(request.data.get('count', session_obj.count))
        
        diff = new_count - old_count
        
        from django.utils import timezone
        today = timezone.localdate()
        
        # N'assigner immédiatement des examens QUE si la session est pour aujourd'hui
        if diff > 0 and session_obj.date == today:
            from django.db.models import Count
            from ophtalmo.models import Exam
            
            region_counts_qs = Exam.objects.filter(status='En cours').values('region').annotate(count=Count('id'))
            region_counts = {item['region']: item['count'] for item in region_counts_qs if item['region']}
            
            exams_attente = list(Exam.objects.filter(status='En attente', assigned_to__isnull=True))
            if exams_attente:
                def sort_key(exam):
                    prio = 0 if exam.priority == 'Urgent' else 1
                    age = exam.date
                    region_count = region_counts.get(exam.region, 0)
                    return (prio, age, region_count, exam.id)
                    
                exams_attente.sort(key=sort_key)
                exams_to_assign = exams_attente[:diff]
                actual_assigned = len(exams_to_assign)
                
                now = timezone.now()
                for exam in exams_to_assign:
                    exam.assigned_to = session_obj.doctor
                    exam.status = 'En cours'
                    exam.date_assignation = now
                    exam.save(update_fields=['assigned_to', 'status', 'date_assignation'])
                
                if hasattr(session_obj.doctor, 'profil'):
                    profil = session_obj.doctor.profil
                    profil.charge_actuelle += actual_assigned
                    profil.save(update_fields=['charge_actuelle'])
                session_obj.count = new_count
                
                if actual_assigned < diff:
                    msg = f'Session modifiée : {actual_assigned} nouveaux examens assignés. (Seulement {actual_assigned} disponibles sur {diff} demandés).'
                else:
                    msg = 'Session modifiée avec succès.'
            else:
                session_obj.count = new_count
                msg = f'Session modifiée. Aucun examen supplémentaire n\'est disponible actuellement.'
        elif diff < 0 and session_obj.date == today:
            from ophtalmo.models import Exam
            if hasattr(session_obj.doctor, 'profil'):
                profil = session_obj.doctor.profil
                exams_en_cours = list(Exam.objects.filter(status='En cours', assigned_to=session_obj.doctor))
                nb_a_retirer = max(0, len(exams_en_cours) - new_count)
                
                if nb_a_retirer > 0:
                    def sort_key_unassign(exam):
                        prio = 1 if exam.priority == 'Normal' else 0
                        age = exam.date.toordinal() if exam.date else 0
                        return (prio, age)
                        
                    exams_en_cours.sort(key=sort_key_unassign, reverse=True)
                    exams_to_unassign = exams_en_cours[:nb_a_retirer]
                    
                    for exam in exams_to_unassign:
                        exam.assigned_to = None
                        exam.status = 'En attente'
                        exam.date_assignation = None
                        exam.save(update_fields=['assigned_to', 'status', 'date_assignation'])
                        
                    profil.charge_actuelle = max(0, profil.charge_actuelle - nb_a_retirer)
                    profil.save(update_fields=['charge_actuelle'])
                    
                    session_obj.count = new_count
                    msg = f'Session modifiée : {nb_a_retirer} examens retirés et remis en attente.'
                else:
                    session_obj.count = new_count
                    msg = 'Session modifiée avec succès.'
            else:
                session_obj.count = new_count
                msg = 'Session modifiée avec succès.'
        else:
            session_obj.count = new_count
            msg = 'Session modifiée avec succès.'
            
        session_obj.start_hour = int(request.data.get('startHour', session_obj.start_hour))
        session_obj.end_hour = int(request.data.get('endHour', session_obj.end_hour))
        session_obj.save()
        
        from django.utils import timezone
        today = timezone.localdate()
        if diff < 0 and session_obj.date == today:
            fill_incomplete_sessions(session_obj.date)
        
        role = session_obj.doctor.profil.role if hasattr(session_obj.doctor, 'profil') else "Medecin"
        title = "Pr" if role == "Chef" else "Dr"
        
        return Response({'message': msg, 'session': {
            'id': session_obj.id,
            'doctorName': f"{title} {session_obj.doctor.first_name} {session_obj.doctor.last_name}".strip(),
            'email': session_obj.doctor.email,
            'date': session_obj.date.isoformat(),
            'startHour': session_obj.start_hour,
            'endHour': session_obj.end_hour,
            'count': session_obj.count,
            'affiliation': session_obj.affiliation,
            'hospital': session_obj.hospital,
            'parsedDate': session_obj.date.isoformat()
        }})
    except CalendarSession.DoesNotExist:
        return Response({'error': 'Session introuvable'}, status=404)

@api_view(['DELETE'])
@authentication_classes([KeycloakAuthentication])
def delete_user_view(request, user_id):
    is_admin = False
    try:
        roles = getattr(request, 'roles', [])
        is_admin = any(r in roles for r in ('ADMIN_SYSTEME', 'ADMIN', 'Admin'))
        if not is_admin:
            is_admin = request.user.profil.role in ('Admin', 'ADMIN_SYSTEME')
    except Exception:
        pass
        
    if not is_admin:
        return Response({'error': 'Seul un administrateur peut supprimer un utilisateur.'}, status=status.HTTP_403_FORBIDDEN)
        
    try:
        keycloak_admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=settings.KEYCLOAK_ADMIN_USER,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True
        )
        
        try:
            user_info = keycloak_admin.get_user(user_id)
            email = user_info.get('email')
            username = user_info.get('username')
            
            if email and request.user.email == email:
                return Response({'error': 'Vous ne pouvez pas supprimer votre propre compte.'}, status=status.HTTP_400_BAD_REQUEST)
                
            # Vérifier si l'utilisateur cible est un administrateur
            target_user = User.objects.filter(email=email).first()
            if not target_user and username:
                target_user = User.objects.filter(username=username).first()
                
            if target_user and hasattr(target_user, 'profil'):
                if target_user.profil.role in ('Admin', 'ADMIN_SYSTEME'):
                    return Response({'error': 'Vous ne pouvez pas supprimer un autre administrateur.'}, status=status.HTTP_403_FORBIDDEN)
                    
            if target_user:
                # Reset all pending or in-progress exams assigned to this user
                from ophtalmo.models import Exam, CalendarSession
                from datetime import date
                exams_to_reset = Exam.objects.filter(
                    assigned_to=target_user,
                    status__in=[Exam.Status.EN_ATTENTE, Exam.Status.EN_COURS]
                )
                exams_to_reset.update(
                    status=Exam.Status.EN_ATTENTE,
                    assigned_to=None
                )
                
                # Delete future CalendarSessions, keep past ones for traceability
                CalendarSession.objects.filter(
                    doctor=target_user,
                    date__gt=date.today()
                ).delete()
                
            keycloak_admin.delete_user(user_id)
            
            # Soft delete in Django DB to preserve past traceability
            if email:
                User.objects.filter(email=email).update(is_active=False)
            if username:
                User.objects.filter(username=username).update(is_active=False)
                
            # Run automatic distribution to reassign the newly pending exams
            try:
                from ophtalmo.distribution import run_automatic_distribution
                run_automatic_distribution()
            except Exception as e:
                print("Erreur lors de la redistribution:", e)
                
            return Response({'success': True})
        except Exception as kc_err:
            return Response({'error': f"Utilisateur introuvable ou erreur Keycloak: {str(kc_err)}"}, status=status.HTTP_404_NOT_FOUND)
            
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
