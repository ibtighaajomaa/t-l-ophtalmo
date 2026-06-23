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


class AnalysisReport(models.Model):
    series_instance_uid = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    analysis_date = models.DateTimeField(auto_now_add=True)
    report_json = models.JSONField()

    class Meta:
        ordering = ['-analysis_date']

    def __str__(self):
        return f"{self.series_instance_uid} — {self.analysis_date:%Y-%m-%d %H:%M}"


class MedicalReport(models.Model):

    class Status(models.TextChoices):
        AI_GENERATED = "AI_GENERATED", "AI Generated"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        SIGNED = "SIGNED", "Signed"

    patient_id = models.CharField(max_length=255)
    examination_id = models.CharField(max_length=255, db_index=True)
    generated_by_ai = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AI_GENERATED,
    )
    ai_content = models.TextField(blank=True, default="")
    doctor_content = models.TextField(blank=True, default="")
    final_content = models.TextField(blank=True, default="")
    ai_confidence = models.FloatField(null=True, blank=True)
    ai_report_data = models.JSONField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="validated_medical_reports",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="signed_medical_reports",
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Report {self.patient_id} — {self.examination_id} ({self.status})"


class MedicalReportVersion(models.Model):

    class VersionType(models.TextChoices):
        AI = "AI", "AI Generated"
        DOCTOR = "DOCTOR", "Doctor Edit"
        SIGNED = "SIGNED", "Signed"

    report = models.ForeignKey(
        MedicalReport,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.IntegerField()
    content = models.TextField(blank=True, default="")
    version_type = models.CharField(
        max_length=10,
        choices=VersionType.choices,
    )
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    modified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_number"]
        unique_together = [("report", "version_number")]

    def __str__(self):
        return f"v{self.version_number} ({self.version_type}) — {self.report}"
