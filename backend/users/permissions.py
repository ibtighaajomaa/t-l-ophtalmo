from rest_framework import permissions

class HasRolePermission(permissions.BasePermission):
    required_role = None

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Récupération des rôles depuis l'authentification Keycloak (stocké dans request.roles)
        roles = getattr(request, 'roles', [])
        return self.required_role in roles

class IsAdmin(HasRolePermission):
    required_role = 'ADMIN'

class IsChefDeService(HasRolePermission):
    required_role = 'CHEF_SERVICE'

class IsOphtalmologue(HasRolePermission):
    required_role = 'MEDECIN'

class IsResident(HasRolePermission):
    required_role = 'RESIDENT'
