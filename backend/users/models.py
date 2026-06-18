from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.fields.Field):
    pass

class Profil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profil')
    telephone = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"Profil de {self.user.username}"

import uuid

class PasswordResetToken(models.Model):
    email = models.EmailField()
    token = models.CharField(max_length=255, unique=True, default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
