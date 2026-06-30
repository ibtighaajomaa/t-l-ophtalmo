from rest_framework import serializers
from .models import (
    Exam, ImageQualityAssessment, AnalysisReport, MedicalReport,
    MedicalReportVersion, DoctorNote,
)


class ImageQualityAssessmentSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = ImageQualityAssessment
        fields = [
            "orthanc_instance_id", "study_instance_uid", "series_instance_uid",
            "sop_instance_uid", "patient_id", "modality", "score", "category",
            "label", "analyzed_at",
        ]


class ExamSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    reassigned_from_name = serializers.SerializerMethodField()
    image_quality_results = ImageQualityAssessmentSerializer(many=True, read_only=True)

    class Meta:
        model = Exam
        fields = [
            'id', 'study_instance_uid', 'patient_name', 'patient_age',
            'exam_type', 'date', 'priority', 'status',
            'assigned_to', 'assigned_to_name',
            'created_by', 'created_by_name',
            'region', 'modality_ip', 'notes',
            'is_reassigned_24h', 'reassigned_from', 'reassigned_from_name',
            'created_at', 'updated_at',
            'quality_status', 'quality_score', 'quality_category',
            'quality_error', 'image_quality_results',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'assigned_to_name', 'created_by_name', 'reassigned_from_name']

    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            return f"Dr. {obj.assigned_to.first_name} {obj.assigned_to.last_name}"
        return None

    def get_reassigned_from_name(self, obj):
        if obj.reassigned_from:
            return f"Dr. {obj.reassigned_from.first_name} {obj.reassigned_from.last_name}"
        return None

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}"
        return None


class AnalysisReportSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisReport
        fields = [
            'id', 'series_instance_uid', 'user', 'user_name',
            'analysis_date', 'report_json',
        ]
        read_only_fields = ['id', 'user', 'analysis_date', 'user_name']

    def get_user_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
        return None


class MedicalReportSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    validated_by_name = serializers.SerializerMethodField()
    signed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MedicalReport
        fields = [
            'id', 'patient_id', 'examination_id', 'generated_by_ai',
            'status', 'ai_content', 'doctor_content', 'final_content',
            'ai_confidence', 'ai_report_data',
            'created_by', 'created_by_name',
            'validated_by', 'validated_by_name', 'validated_at',
            'signed_by', 'signed_by_name', 'signed_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'created_by', 'created_by_name',
            'validated_by', 'validated_by_name', 'validated_at',
            'signed_by', 'signed_by_name', 'signed_at',
            'created_at', 'updated_at',
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip() or obj.created_by.username
        return None

    def get_validated_by_name(self, obj):
        if obj.validated_by:
            return f"{obj.validated_by.first_name} {obj.validated_by.last_name}".strip() or obj.validated_by.username
        return None

    def get_signed_by_name(self, obj):
        if obj.signed_by:
            return f"{obj.signed_by.first_name} {obj.signed_by.last_name}".strip() or obj.signed_by.username
        return None


class MedicalReportVersionSerializer(serializers.ModelSerializer):
    modified_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MedicalReportVersion
        fields = [
            'id', 'report', 'version_number', 'content',
            'version_type', 'modified_by', 'modified_by_name', 'modified_at',
        ]
        read_only_fields = [
            'id', 'report', 'version_number', 'modified_by',
            'modified_by_name', 'modified_at',
        ]

    def get_modified_by_name(self, obj):
        if obj.modified_by:
            return f"{obj.modified_by.first_name} {obj.modified_by.last_name}".strip() or obj.modified_by.username
        return None


class DoctorNoteSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = DoctorNote
        fields = [
            'id', 'series_instance_uid', 'user', 'user_name',
            'eye', 'text', 'created_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'user_name']

    def get_user_name(self, obj):
        if obj.user:
            return f"Dr. {obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
        return None
