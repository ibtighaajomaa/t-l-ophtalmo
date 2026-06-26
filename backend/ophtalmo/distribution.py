"""
Algorithme de distribution automatique des examens radiographiques.

Priorité :
  1. Urgence (Urgent > Normal)
  2. Ancienneté (date_reception la plus ancienne)
  3. Équité régionale (régions les moins servies en priorité)

Contraintes :
  - Max 30 examens par médecin
  - Médecin doit être disponible (is_disponible=True)
  - Médecin doit avoir le rôle approprié (Medecin, Resident, OPHTALMOLOGUE)
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from .models import Exam
from users.models import Profil

logger = logging.getLogger(__name__)

MAX_CHARGE_PAR_MEDECIN = 30

# Rôles éligibles pour recevoir des examens
ROLES_MEDECIN = ['Medecin', 'OPHTALMOLOGUE', 'Resident', 'RESIDENT', 'CHEF_SERVICE', 'Chef']


def get_medecins_disponibles():
    """
    Récupère les profils de médecins disponibles avec de la capacité.
    Triés par charge_actuelle croissante (le moins chargé d'abord).
    """
    return Profil.objects.filter(
        is_disponible=True,
        charge_actuelle__lt=MAX_CHARGE_PAR_MEDECIN,
        role__in=ROLES_MEDECIN,
    ).select_related('user').order_by('charge_actuelle')


def get_examens_en_attente():
    """
    Récupère les examens en attente, triés par priorité :
    1. Urgent d'abord
    2. Puis le plus ancien (created_at)
    """
    return Exam.objects.filter(
        status='En attente',
    ).order_by(
        # Urgent en premier (les valeurs "Urgent" sont triées avant "Normal" inversé)
        '-priority',
        # Le plus ancien d'abord (date de l'examen)
        'date',
    )


def calculer_score_equite_region():
    """
    Calcule un score d'équité par région.
    Retourne un dict {region: count_examens_en_cours}.
    Les régions avec le moins d'examens en cours seront prioritaires.
    """
    region_counts = Exam.objects.filter(
        status='En cours',
    ).values('region').annotate(
        total=Count('id')
    ).order_by('total')

    return {item['region']: item['total'] for item in region_counts}


def trier_avec_equite_regionale(examens):
    """
    Re-trie les examens en tenant compte de l'équité régionale.
    Les examens venant de régions sous-représentées sont priorisés
    parmi ceux de même niveau d'urgence.
    """
    region_scores = calculer_score_equite_region()

    def score_examen(exam):
        # Score de priorité : Urgent = 0 (premier), Normal = 1
        urgence_score = 0 if exam.priority == 'Urgent' else 1
        # Score de temps : plus ancien = date plus ancienne = plus petit ordinal
        temps_score = exam.date.toordinal() if exam.date else 0
        # Score régional : régions moins servies = score plus bas = priorité
        region_score = region_scores.get(exam.region, 0)
        return (urgence_score, region_score, temps_score)

    return sorted(examens, key=score_examen)


@transaction.atomic
def distribuer_examens():
    """
    Algorithme principal de distribution des examens.

    1. Récupère les examens 'En attente'
    2. Les trie par urgence > équité régionale > ancienneté
    3. Les distribue aux médecins disponibles (round-robin pondéré par charge)
    4. Max 30 examens par médecin
    """
    examens_attente = list(get_examens_en_attente())
    if not examens_attente:
        logger.info("Aucun examen en attente à distribuer.")
        return {'distribues': 0, 'restants': 0}

    medecins = list(get_medecins_disponibles())
    if not medecins:
        logger.warning("Aucun médecin disponible pour la distribution.")
        return {'distribues': 0, 'restants': len(examens_attente)}

    # Trier avec équité régionale
    examens_tries = trier_avec_equite_regionale(examens_attente)

    distribues = 0
    medecin_index = 0

    for examen in examens_tries:
        # Trouver le prochain médecin avec de la capacité (round-robin)
        tentatives = 0
        while tentatives < len(medecins):
            medecin = medecins[medecin_index % len(medecins)]
            medecin_index += 1

            if medecin.charge_actuelle < MAX_CHARGE_PAR_MEDECIN:
                # Assigner l'examen
                examen.assigned_to = medecin.user
                examen.status = 'En cours'
                examen.date_assignation = timezone.now()
                examen.save(update_fields=['assigned_to', 'status', 'date_assignation'])

                medecin.charge_actuelle += 1
                medecin.save(update_fields=['charge_actuelle'])

                distribues += 1
                logger.info(
                    f"Examen #{examen.id} ({examen.patient_name}) "
                    f"assigné à {medecin.user.get_full_name() or medecin.user.username} "
                    f"(charge: {medecin.charge_actuelle}/{MAX_CHARGE_PAR_MEDECIN})"
                )
                break

            tentatives += 1

        if tentatives >= len(medecins):
            # Plus aucun médecin disponible avec de la capacité
            logger.warning("Tous les médecins sont à pleine charge. Arrêt de la distribution.")
            break

    restants = Exam.objects.filter(status='En attente').count()
    logger.info(f"Distribution terminée : {distribues} examens distribués, {restants} restants.")
    return {'distribues': distribues, 'restants': restants}


@transaction.atomic
def reassigner_examens_en_retard():
    """
    Vérifie les examens 'En cours' assignés depuis plus de 24h et non terminés.
    - Si le médecin n'est plus disponible → remet l'examen 'En attente'
    - Si le médecin est disponible → envoie un email de rappel
    """
    seuil_24h = timezone.now() - timedelta(hours=24)

    examens_en_retard = Exam.objects.filter(
        status='En cours',
        date_assignation__isnull=False,
        date_assignation__lt=seuil_24h,
    ).select_related('assigned_to')

    remis_en_attente = 0
    rappels_envoyes = 0

    for examen in examens_en_retard:
        if not examen.assigned_to:
            # Pas de médecin assigné → remettre en attente
            examen.status = 'En attente'
            examen.date_assignation = None
            examen.save(update_fields=['status', 'date_assignation'])
            remis_en_attente += 1
            continue

        try:
            profil = examen.assigned_to.profil
        except Profil.DoesNotExist:
            # Pas de profil → remettre en attente
            examen.status = 'En attente'
            examen.assigned_to = None
            examen.date_assignation = None
            examen.save(update_fields=['status', 'assigned_to', 'date_assignation'])
            remis_en_attente += 1
            continue

        if not profil.is_disponible:
            # Médecin non disponible → réassigner
            examen.status = 'En attente'
            examen.assigned_to = None
            examen.date_assignation = None
            examen.save(update_fields=['status', 'assigned_to', 'date_assignation'])

            profil.charge_actuelle = max(0, profil.charge_actuelle - 1)
            profil.save(update_fields=['charge_actuelle'])

            remis_en_attente += 1
            logger.info(
                f"Examen #{examen.id} retiré du Dr {examen.assigned_to.get_full_name()} "
                f"(non disponible) → remis en attente."
            )
        else:
            # Médecin disponible → rappel email
            _envoyer_rappel_email(profil.user, examen)
            rappels_envoyes += 1

    logger.info(
        f"Vérification 24h : {remis_en_attente} réassignés, "
        f"{rappels_envoyes} rappels envoyés."
    )
    return {
        'remis_en_attente': remis_en_attente,
        'rappels_envoyes': rappels_envoyes,
    }


def recalculer_charges():
    """
    Recalcule la charge_actuelle de chaque médecin
    basé sur le nombre réel d'examens 'En cours' qui lui sont assignés.
    Utile pour corriger les dérives éventuelles.
    """
    profils = Profil.objects.filter(role__in=ROLES_MEDECIN)
    updated = 0

    for profil in profils:
        vraie_charge = Exam.objects.filter(
            assigned_to=profil.user,
            status='En cours',
        ).count()

        if profil.charge_actuelle != vraie_charge:
            logger.info(
                f"Correction charge {profil.user.username}: "
                f"{profil.charge_actuelle} → {vraie_charge}"
            )
            profil.charge_actuelle = vraie_charge
            profil.save(update_fields=['charge_actuelle'])
            updated += 1

    return {'profils_corriges': updated}


@transaction.atomic
def assigner_examens_nouveau_medecin(profil, max_examens=None):
    """
    Assigne immédiatement jusqu'à MAX_CHARGE_PAR_MEDECIN examens 
    les plus prioritaires à un nouveau médecin dès la création de son compte.
    """
    if profil.role not in ROLES_MEDECIN or not profil.is_disponible:
        return {'distribues': 0}

    # Ne distribuer que la capacité restante (normalement MAX_CHARGE_PAR_MEDECIN si nouveau)
    capacite = max(0, MAX_CHARGE_PAR_MEDECIN - profil.charge_actuelle)
    if max_examens is not None:
        capacite = min(capacite, max_examens)
        
    if capacite <= 0:
        return {'distribues': 0}

    examens_attente = list(get_examens_en_attente())
    if not examens_attente:
        logger.info("Aucun examen en attente à assigner au nouveau médecin.")
        return {'distribues': 0}

    examens_tries = trier_avec_equite_regionale(examens_attente)[:capacite]
    distribues = 0

    for examen in examens_tries:
        examen.assigned_to = profil.user
        examen.status = 'En cours'
        examen.date_assignation = timezone.now()
        examen.save(update_fields=['assigned_to', 'status', 'date_assignation'])
        distribues += 1

    if distribues > 0:
        profil.charge_actuelle += distribues
        profil.save(update_fields=['charge_actuelle'])
        logger.info(
            f"Initialisation rapide : {distribues} examens assignés à "
            f"au Dr {profil.user.get_full_name() or profil.user.username}"
        )

    return {'distribues': distribues}


def _envoyer_rappel_email(user, examen):
    """Envoie un email de rappel au médecin pour un examen en retard."""
    try:
        sujet = "[TéléOphta] Rappel — Examen en attente de votre interprétation"
        message = f"""Bonjour Dr {user.first_name} {user.last_name},

Nous vous rappelons que l'examen suivant vous a été assigné il y a plus de 24 heures et attend votre interprétation :

Patient : {examen.patient_name}
Type d'examen : {examen.exam_type}
Priorité : {examen.priority}
Région : {examen.region or 'Non spécifiée'}
Date de réception : {examen.created_at.strftime('%d/%m/%Y à %H:%M') if examen.created_at else 'N/A'}

Merci de vous connecter à la plateforme pour traiter cet examen dans les meilleurs délais.

Cordialement,

L'équipe TéléOphta
Plateforme de Télédépistage de la Rétinopathie
"""
        send_mail(
            sujet,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=True,
        )
        logger.info(f"Rappel envoyé à {user.email} pour l'examen #{examen.id}")
    except Exception as e:
        logger.error(f"Erreur envoi rappel à {user.email}: {e}")


@transaction.atomic
def rendre_indisponible_et_reassigner(user_id):
    """Libère les patients d'un médecin et relance la distribution."""
    try:
        profil = Profil.objects.get(user_id=user_id)
    except Profil.DoesNotExist:
        return 0

    profil.is_disponible = False
    profil.save(update_fields=['is_disponible'])

    # 1. Libérer ses examens en cours
    examens = Exam.objects.filter(assigned_to_id=user_id, status='En cours')
    count = examens.count()
    
    examens.update(status='En attente', assigned_to=None, date_assignation=None)
    
    # 2. Remettre sa charge à 0
    profil.charge_actuelle = 0
    profil.save(update_fields=['charge_actuelle'])

    # 3. Redistribuer immédiatement à TOUS les autres médecins disponibles
    distribuer_examens()
    
    return count
