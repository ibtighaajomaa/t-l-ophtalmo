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
            users_url = f"{base_url}/admin/realms/{realm}/users?q=createdBy:{created_by}&max=1000"
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
