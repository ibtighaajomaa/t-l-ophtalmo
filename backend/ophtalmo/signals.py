from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Exam, ExamStatusHistory


@receiver(pre_save, sender=Exam)
def remember_previous_exam_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = sender.objects.filter(pk=instance.pk).values_list(
        "status", flat=True
    ).first()


@receiver(post_save, sender=Exam)
def record_exam_status_change(sender, instance, created, **kwargs):
    previous_status = getattr(instance, "_previous_status", None)
    if created or previous_status != instance.status:
        ExamStatusHistory.objects.create(exam=instance, status=instance.status)
