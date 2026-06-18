# comptes/views.py
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

@api_view(['POST'])
@permission_classes([AllowAny])
def inscription(request):
    """Vue pour inscrire un nouvel utilisateur"""
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')

    if not username or not password or not email:
        return Response(
            {"error": "Veuillez fournir un nom d'utilisateur, un email et un mot de passe."}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(username=username).exists():
        return Response({"error": "Ce nom d'utilisateur est déjà pris."}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=email).exists():
        return Response({"error": "Cet email est déjà utilisé."}, status=status.HTTP_400_BAD_REQUEST)

    # Création de l'utilisateur avec mot de passe haché automatiquement
    user = User.objects.create_user(username=username, email=email, password=password)
    user.save()

    return Response({"message": "Utilisateur créé avec succès !"}, status=status.HTTP_201_CREATED)

@api_view(['GET'])
# Cette vue nécessite d'être connecté (Bearer Token requis dans les headers)
def exemple_route_protegee(request):
    """Exemple de route accessible uniquement si on est connecté"""
    return Response({"message": f"Bonjour {request.user.username}, vous êtes connecté !"})