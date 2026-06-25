from django.db.models.signals import post_save
from django.dispatch import receiver
from ophtalmo.distribution import assigner_examens_nouveau_medecin
from .models import Profil

@receiver(post_save, sender=Profil)
def initialiser_examens_medecin(sender, instance, created, **kwargs):
    """
    Signal déclenché après la sauvegarde d'un Profil.
    Si le profil vient d'être créé et qu'il s'agit d'un médecin disponible,
    on lui assigne immédiatement des examens en attente.
    """
    if created:
        # La fonction gère la vérification du rôle (Medecin, etc.) et de la disponibilité.
        assigner_examens_nouveau_medecin(instance)
