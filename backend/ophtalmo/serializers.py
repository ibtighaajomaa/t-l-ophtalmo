from rest_framework import serializers
from .models import Exam


class ExamSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            'id', 'study_instance_uid', 'patient_name', 'patient_age',
            'exam_type', 'date', 'priority', 'status',
            'assigned_to', 'assigned_to_name',
            'created_by', 'created_by_name',
            'region', 'modality_ip', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'assigned_to_name', 'created_by_name']

    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            return f"Dr. {obj.assigned_to.first_name} {obj.assigned_to.last_name}"
        return None

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}"
        return None
