from django.contrib import admin
from .models import Exam


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['patient_name', 'exam_type', 'date', 'priority', 'status', 'assigned_to', 'region']
    list_filter = ['status', 'priority', 'exam_type', 'date']
    search_fields = ['patient_name', 'study_instance_uid']
