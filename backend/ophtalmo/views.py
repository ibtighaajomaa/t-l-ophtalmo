import os
from datetime import date, datetime
from django.db.models import Q, Max
import requests
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.http import FileResponse
from .models import Exam, AnalysisReport, MedicalReport, MedicalReportVersion
from .serializers import (
    ExamSerializer,
    AnalysisReportSerializer,
    MedicalReportSerializer,
    MedicalReportVersionSerializer,
)
from users.authentication import KeycloakAuthentication
from .report_generator import ReportGenerator


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


@api_view(['POST'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def save_analysis(request):
    series_uid = request.data.get('series_instance_uid')
    report_json = request.data.get('report_json')
    if not series_uid or not report_json:
        return Response(
            {'error': 'series_instance_uid and report_json are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    report = AnalysisReport.objects.create(
        series_instance_uid=series_uid,
        user=request.user,
        report_json=report_json,
    )
    serializer = AnalysisReportSerializer(report)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def list_analysis_reports(request):
    series_uid = request.query_params.get('series')
    reports = AnalysisReport.objects.all()
    if series_uid:
        reports = reports.filter(series_instance_uid=series_uid)
    limit = int(request.query_params.get('limit', 50))
    if request.query_params.get('mine') in ('true', '1'):
        reports = reports.filter(user=request.user)
    reports = reports[:limit]
    serializer = AnalysisReportSerializer(reports, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def generate_report(request):
    report_data = request.data.get('report_data')
    patient_id = request.data.get('patient_id', 'inconnu')
    if not report_data:
        return Response(
            {'error': 'report_data is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        api_key = os.environ.get('OPENROUTER_API_KEY')
        if not api_key:
            return Response(
                {'error': 'OPENROUTER_API_KEY not configured'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        generator = ReportGenerator(api_key=api_key)
        result = generator.generate_report(
            report_data=report_data,
            patient_id=patient_id,
        )
        return Response({
            'report_text': result['report_text'],
            'report_html': result['report_html'],
            'report_json': result['report_json'],
        })
    except RuntimeError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(['GET', 'POST'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def medical_report_list(request):
    if request.method == 'GET':
        qs = MedicalReport.objects.all()
        exam_id = request.query_params.get('examination_id')
        if exam_id:
            qs = qs.filter(examination_id=exam_id)
        limit = int(request.query_params.get('limit', 50))
        qs = qs[:limit]
        serializer = MedicalReportSerializer(qs, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        patient_id = request.data.get('patient_id')
        examination_id = request.data.get('examination_id')
        ai_content = request.data.get('ai_content', '')
        ai_confidence = request.data.get('ai_confidence')
        ai_report_data = request.data.get('ai_report_data')
        if not patient_id or not examination_id:
            return Response(
                {'error': 'patient_id and examination_id are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report = MedicalReport.objects.create(
            patient_id=patient_id,
            examination_id=examination_id,
            generated_by_ai=True,
            status=MedicalReport.Status.AI_GENERATED,
            ai_content=ai_content,
            ai_confidence=ai_confidence,
            ai_report_data=ai_report_data,
            created_by=request.user if request.user.is_authenticated else None,
        )
        MedicalReportVersion.objects.create(
            report=report,
            version_number=1,
            content=ai_content,
            version_type=MedicalReportVersion.VersionType.AI,
            modified_by=request.user if request.user.is_authenticated else None,
        )
        serializer = MedicalReportSerializer(report)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def medical_report_detail(request, pk):
    try:
        report = MedicalReport.objects.get(pk=pk)
    except MedicalReport.DoesNotExist:
        return Response({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = MedicalReportSerializer(report)
        return Response(serializer.data)

    elif request.method == 'PUT':
        doctor_content = request.data.get('doctor_content')
        if doctor_content is None:
            return Response(
                {'error': 'doctor_content is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report.doctor_content = doctor_content
        if report.status == MedicalReport.Status.AI_GENERATED:
            report.status = MedicalReport.Status.UNDER_REVIEW
        report.save()

        max_ver = report.versions.aggregate(m=Max('version_number'))['m'] or 0
        MedicalReportVersion.objects.create(
            report=report,
            version_number=max_ver + 1,
            content=doctor_content,
            version_type=MedicalReportVersion.VersionType.DOCTOR,
            modified_by=request.user if request.user.is_authenticated else None,
        )

        serializer = MedicalReportSerializer(report)
        return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def sign_medical_report(request, pk):
    try:
        report = MedicalReport.objects.get(pk=pk)
    except MedicalReport.DoesNotExist:
        return Response({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)

    if report.status == MedicalReport.Status.SIGNED:
        return Response({'error': 'Report already signed'}, status=status.HTTP_400_BAD_REQUEST)

    content_to_sign = report.doctor_content or report.ai_content
    report.final_content = content_to_sign
    report.validated_by = request.user if request.user.is_authenticated else None
    report.validated_at = datetime.now()
    report.signed_by = request.user if request.user.is_authenticated else None
    report.signed_at = datetime.now()
    report.status = MedicalReport.Status.SIGNED
    report.save()

    max_ver = report.versions.aggregate(m=Max('version_number'))['m'] or 0
    MedicalReportVersion.objects.create(
        report=report,
        version_number=max_ver + 1,
        content=content_to_sign,
        version_type=MedicalReportVersion.VersionType.SIGNED,
        modified_by=request.user if request.user.is_authenticated else None,
    )

    serializer = MedicalReportSerializer(report)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def list_report_versions(request, pk):
    try:
        report = MedicalReport.objects.get(pk=pk)
    except MedicalReport.DoesNotExist:
        return Response({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
    versions = report.versions.all()
    serializer = MedicalReportVersionSerializer(versions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def export_report_docx(request, pk):
    try:
        report = MedicalReport.objects.get(pk=pk)
    except MedicalReport.DoesNotExist:
        return Response({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)

    from .docx_export import export_report_to_docx
    buffer = export_report_to_docx(report)
    filename = f"rapport-{report.patient_id}-{report.pk}.docx"
    return FileResponse(buffer, as_attachment=True, filename=filename)
