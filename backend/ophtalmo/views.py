import os
from datetime import date
from django.db.models import Q
import requests
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Exam
from .serializers import ExamSerializer


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def exam_list(request):
    if request.method == 'GET':
        exams = Exam.objects.all().order_by('-date', '-id')

        status_param = request.query_params.get('status')
        if status_param and status_param != 'Tous':
            exams = exams.filter(status=status_param)

        q = request.query_params.get('q', '')
        if q:
            exams = exams.filter(
                Q(patient_name__icontains=q) | Q(id__icontains=q)
            )

        region = request.query_params.get('region', '')
        if region:
            exams = exams.filter(region__icontains=region)

        doctor = request.query_params.get('doctor', '')
        if doctor:
            exams = exams.filter(
                Q(assigned_to__first_name__icontains=doctor) |
                Q(assigned_to__last_name__icontains=doctor)
            )

        today_only = request.query_params.get('today_only')
        if today_only and today_only.lower() in ('true', '1'):
            exams = exams.filter(date=date.today())

        if request.user.is_authenticated:
            try:
                profil = request.user.profil
                if profil.role in ('Medecin', 'Resident'):
                    exams = exams.filter(
                        Q(assigned_to=request.user) | Q(created_by=request.user)
                    )
            except Exam.profil.RelatedObjectDoesNotExist:
                pass

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = exams.count()
        start = (page - 1) * page_size
        end = start + page_size
        serializer = ExamSerializer(exams[start:end], many=True)

        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'results': serializer.data,
        })

    elif request.method == 'POST':
        serializer = ExamSerializer(data=request.data)
        if serializer.is_valid():
            if request.user.is_authenticated:
                serializer.save(created_by=request.user)
            else:
                serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def exam_detail(request, pk):
    try:
        exam = Exam.objects.get(pk=pk)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ExamSerializer(exam)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ExamSerializer(exam, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        exam.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([AllowAny])
def exam_stats(request):
    total = Exam.objects.count()
    attente = Exam.objects.filter(status='En attente').count()
    cours = Exam.objects.filter(status='En cours').count()
    interprete = Exam.objects.filter(status='Interprété').count()
    urgent = Exam.objects.filter(priority='Urgent').count()
    return Response({
        'total': total,
        'En attente': attente,
        'En cours': cours,
        'Interprété': interprete,
        'Urgent': urgent,
    })


ORTHANC_URL = os.environ.get('ORTHANC_URL', 'http://orthanc-container:8042')


@api_view(['POST'])
@permission_classes([AllowAny])
def sync_orthanc(request):
    try:
        resp = requests.get(f'{ORTHANC_URL}/studies', timeout=30)
        resp.raise_for_status()
        study_ids = resp.json()
    except requests.RequestException as e:
        return Response(
            {'error': f'Cannot reach Orthanc: {str(e)}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    created = 0
    skipped = 0
    for study_id in study_ids:
        if Exam.objects.filter(study_instance_uid=study_id).exists():
            skipped += 1
            continue

        try:
            detail = requests.get(
                f'{ORTHANC_URL}/studies/{study_id}',
                timeout=15,
            )
            detail.raise_for_status()
            meta = detail.json()
        except requests.RequestException:
            skipped += 1
            continue

        main_patient = meta.get('PatientMainDicomTags', {})
        patient_name = main_patient.get('PatientName', 'Unknown')
        patient_age = None
        age_str = main_patient.get('PatientAge', '')
        if age_str and age_str.rstrip('Y').isdigit():
            patient_age = int(age_str.rstrip('Y'))

        study_date_str = meta.get('MainDicomTags', {}).get('StudyDate', '')
        study_date = date.today()
        if study_date_str and len(study_date_str) == 8:
            try:
                study_date = date(
                    int(study_date_str[:4]),
                    int(study_date_str[4:6]),
                    int(study_date_str[6:8]),
                )
            except ValueError:
                pass

        Exam.objects.create(
            study_instance_uid=study_id,
            patient_name=patient_name,
            patient_age=patient_age,
            exam_type='Rétinographie',
            date=study_date,
            priority='Normal',
            status='En attente',
            region='',
            modality_ip='',
            notes='',
        )
        created += 1

    return Response({
        'created': created,
        'skipped': skipped,
        'total': len(study_ids),
    })
