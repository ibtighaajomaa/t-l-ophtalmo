from django.db import models
from django.conf import settings


class Exam(models.Model):

    class ExamType(models.TextChoices):
        RETINOGRAPHIE = "Rétinographie", "Rétinographie"
        OCT = "OCT", "OCT"
        CHAMP_VISUEL = "Champ visuel", "Champ visuel"
        ANGIOGRAPHIE = "Angiographie", "Angiographie"

    class Priority(models.TextChoices):
        URGENT = "Urgent", "Urgent"
        NORMAL = "Normal", "Normal"

    class Status(models.TextChoices):
        EN_ATTENTE = "En attente", "En attente"
        EN_COURS = "En cours", "En cours"
        INTERPRETE = "Interprété", "Interprété"

    study_instance_uid = models.CharField(max_length=255, unique=True, blank=True, null=True)
    patient_name = models.CharField(max_length=255)
    patient_age = models.IntegerField(blank=True, null=True)
    exam_type = models.CharField(max_length=50, choices=ExamType.choices, default=ExamType.RETINOGRAPHIE)
    date = models.DateField()
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.EN_ATTENTE)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_exams",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_exams",
    )
    region = models.CharField(max_length=255, blank=True, default="")
    modality_ip = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient_name} — {self.exam_type} ({self.date})"
