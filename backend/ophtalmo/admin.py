from django.contrib import admin
from .models import (
    AnalysisReport,
    DicomModalitySite,
    Exam,
    MedicalReport,
    MedicalReportVersion,
)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['patient_name', 'exam_type', 'date', 'priority', 'status', 'assigned_to', 'region']
    list_filter = ['status', 'priority', 'exam_type', 'date']
    search_fields = ['patient_name', 'study_instance_uid']


@admin.register(AnalysisReport)
class AnalysisReportAdmin(admin.ModelAdmin):
    list_display = ['series_instance_uid', 'user', 'analysis_date']
    list_filter = ['analysis_date', 'user']
    search_fields = ['series_instance_uid']


@admin.register(DicomModalitySite)
class DicomModalitySiteAdmin(admin.ModelAdmin):
    list_display = ['institution_name', 'remote_ip', 'remote_aet', 'is_active']
    list_filter = ['is_active', 'institution_name']
    search_fields = ['institution_name', 'remote_ip', 'remote_aet']


@admin.register(MedicalReport)
class MedicalReportAdmin(admin.ModelAdmin):
    list_display = ['patient_id', 'examination_id', 'status', 'created_by', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['patient_id', 'examination_id']


@admin.register(MedicalReportVersion)
class MedicalReportVersionAdmin(admin.ModelAdmin):
    list_display = ['report', 'version_number', 'version_type', 'modified_by', 'modified_at']
    list_filter = ['version_type', 'modified_at']
