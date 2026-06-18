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
            if 'telephone' in data:
                Profil.objects.update_or_create(
                    user=user,
                    defaults={'telephone': data['telephone'], 'role': data['role']}
                )

            # 6. Envoyer l'email de bienvenue avec les identifiants
            from django.core.mail import send_mail
            sujet = "Bienvenue sur TéléOphta - Vos identifiants"
            lien_login = "http://localhost:8081/login"
            
            message = f"""Bonjour Dr {data['prenom']} {data['nom']},
            
Votre compte TéléOphta a été créé avec succès.
            
Voici vos identifiants pour vous connecter :
Email : {data['email']}
Mot de passe provisoire : {data['password_provisoire']}
            
Vous pouvez vous connecter à cette adresse : {lien_login}
            
Cordialement,
L'équipe TéléOphta.
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
    except Exception as e:
        return Response({"error": f"Erreur avec Keycloak: {str(e)}"}, status=500)

    # 2. Créer un token dans Django
    reset_obj = PasswordResetToken.objects.create(email=email)
    
    # 3. Envoyer le mail vers REACT
    link = f"http://localhost:8081/reset-password?token={reset_obj.token}"
    send_mail(
        "Réinitialisation Mot de Passe",
        f"Cliquez ici pour réinitialiser : {link}",
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
                "createdBy": created_by_attr
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
        # Pour les statistiques, la base de données locale synchronisée est parfaite
        total = User.objects.count()
        chefs = Profil.objects.filter(role="Chef").count()
        medecins = Profil.objects.filter(role="Medecin").count()
        residents = Profil.objects.filter(role="Resident").count()
        
        return JsonResponse({
            "total": total,
            "chefs": chefs,
            "medecins": medecins,
            "residents": residents
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
