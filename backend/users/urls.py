from django.urls import path
from .views import (
    CreerUtilisateurView, LoginView, ForcerNouveauMotPasseView,
    forgot_password_relay, request_password_reset, confirm_password_reset,
    get_keycloak_events, logout_relay, update_keycloak_user,
    get_paginated_users, get_user_stats
)

urlpatterns = [
    path('api/auth/register-user/', CreerUtilisateurView.as_view(), name='register_user'),
    path('api/auth/login/', LoginView.as_view(), name='login'),
    path('api/auth/logout/', logout_relay, name='logout'),
    path('api/auth/reset-password/', ForcerNouveauMotPasseView.as_view(), name='reset_password'),
    path('api/forgot-password/', forgot_password_relay, name='forgot_password'),
    path('api/request-reset/', request_password_reset, name='request_reset'),
    path('api/confirm-reset/', confirm_password_reset, name='confirm_reset'),
    path('api/logs/', get_keycloak_events, name='keycloak_logs'),
    path('api/users/update/', update_keycloak_user, name='update_user'),
    path('api/users/paginated/', get_paginated_users, name='paginated_users'),
    path('api/users/stats/', get_user_stats, name='user_stats'),
]
