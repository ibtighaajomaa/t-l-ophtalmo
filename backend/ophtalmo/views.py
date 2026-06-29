import json
import logging
import os
from datetime import date, datetime
from django.db.models import Q, Max
import requests
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.http import FileResponse
from .models import Exam, AnalysisReport, MedicalReport, MedicalReportVersion, DoctorNote
from .serializers import (
    ExamSerializer,
    AnalysisReportSerializer,
    MedicalReportSerializer,
    MedicalReportVersionSerializer,
    DoctorNoteSerializer,
)
from users.authentication import KeycloakAuthentication
from .report_generator import ReportGenerator

logger = logging.getLogger(__name__)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def exam_list(request):
    if request.method == 'GET':
        exams = Exam.objects.all().order_by('-date', '-id')

        status_param = request.query_params.get('status')
        if status_param and status_param != 'Tous':
            exams = exams.filter(status=status_param)

        study_uid = request.query_params.get('study_instance_uid')
        if study_uid:
            exams = exams.filter(study_instance_uid=study_uid)

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

        date_param = request.query_params.get('date')
        if date_param:
            try:
                exams = exams.filter(date=date_param)
            except ValueError:
                pass

        if request.user.is_authenticated:
            try:
                profil = request.user.profil
                if profil.role in ('Medecin', 'Resident', 'RESIDENT', 'OPHTALMOLOGUE', 'CHEF_SERVICE', 'Chef'):
                    # Tous les rôles médicaux ne voient QUE les examens qui leur sont assignés (ou qu'ils ont perdu)
                    exams = exams.filter(Q(assigned_to=request.user) | Q(reassigned_from=request.user))
                # Admin : pas de filtre, voit tout
            except Exception:
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
        if exam.status == 'En cours' and exam.assigned_to:
            try:
                profil = exam.assigned_to.profil
                profil.charge_actuelle = max(0, profil.charge_actuelle - 1)
                profil.save(update_fields=['charge_actuelle'])
            except Exception:
                pass
                
        exam.status = 'En attente'
        exam.assigned_to = None
        exam.date_assignation = None
        exam.save(update_fields=['status', 'assigned_to', 'date_assignation'])
        
        from .distribution import distribuer_examens
        distribuer_examens()
        
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([AllowAny])
def exam_stats(request):
    exams = Exam.objects.all()
    if request.user.is_authenticated:
        try:
            profil = request.user.profil
            if profil.role in ('Medecin', 'Resident', 'RESIDENT', 'OPHTALMOLOGUE', 'CHEF_SERVICE', 'Chef'):
                exams = exams.filter(Q(assigned_to=request.user) | Q(reassigned_from=request.user))
        except Exception:
            pass

    study_uid = request.query_params.get('study_instance_uid')
    if study_uid:
        exams = exams.filter(study_instance_uid=study_uid)

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

    date_param = request.query_params.get('date')
    if date_param:
        try:
            exams = exams.filter(date=date_param)
        except ValueError:
            pass

    total = exams.count()
    attente = exams.filter(status='En attente').count()
    cours = exams.filter(status='En cours').count()
    interprete = exams.filter(status='Interprété').count()
    urgent = exams.filter(priority='Urgent').count()
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

    force_refresh = request.query_params.get('force_refresh', '').lower() in ('true', '1')

    # Récupérer les UIDs déjà présents en base en une seule requête SQL
    existing_uids = set(
        Exam.objects.filter(study_instance_uid__in=study_ids)
        .values_list('study_instance_uid', flat=True)
    )

    created = 0
    updated = 0
    errors = 0

    for study_id in study_ids:
        already_exists = study_id in existing_uids

        # Chemin rapide : l'étude existe et on ne force pas le rafraîchissement
        if already_exists and not force_refresh:
            updated += 1
            continue

        # Appel Orthanc uniquement pour les nouvelles études
        # (ou toutes si force_refresh=true)
        try:
            detail = requests.get(
                f'{ORTHANC_URL}/studies/{study_id}',
                timeout=15,
            )
            detail.raise_for_status()
            meta = detail.json()
        except requests.RequestException:
            errors += 1
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

        # Extraire la région depuis InstitutionName (tag DICOM)
        main_dicom = meta.get('MainDicomTags', {})
        institution = main_dicom.get('InstitutionName', '')
        region = institution if institution else ''

        if already_exists:
            # force_refresh=true : mettre à jour les métadonnées DICOM
            # sans écraser le statut ni l'assignation
            existing = Exam.objects.filter(study_instance_uid=study_id).first()
            if existing:
                changed_fields = []
                if existing.patient_name != patient_name:
                    existing.patient_name = patient_name
                    changed_fields.append('patient_name')
                if existing.patient_age != patient_age:
                    existing.patient_age = patient_age
                    changed_fields.append('patient_age')
                if existing.date != study_date:
                    existing.date = study_date
                    changed_fields.append('date')
                if existing.region != region:
                    existing.region = region
                    changed_fields.append('region')
                if changed_fields:
                    existing.save(update_fields=changed_fields)
            updated += 1
        else:
            Exam.objects.create(
                study_instance_uid=study_id,
                patient_name=patient_name,
                patient_age=patient_age,
                exam_type='Rétinographie',
                date=study_date,
                priority='Normal',
                status='En attente',
                region=region,
                modality_ip='',
                notes='',
            )
            created += 1

    # Déclencher la distribution automatique après la sync
    # Toujours distribuer pour assigner les examens en attente
    try:
        from .tasks import tache_distribution
        tache_distribution.delay()
    except Exception:
        # Si Celery n'est pas dispo, distribuer en synchrone
        from .distribution import distribuer_examens
        distribuer_examens()

    # Nettoyage : supprimer les Exam dont l'étude n'existe plus dans Orthanc
    orthanc_study_ids = set(study_ids)
    db_study_uids = set(
        Exam.objects.filter(study_instance_uid__isnull=False)
        .exclude(study_instance_uid='')
        .values_list('study_instance_uid', flat=True)
    )
    stale_uids = db_study_uids - orthanc_study_ids
    deleted_count = 0
    if stale_uids:
        AnalysisReport.objects.filter(series_instance_uid__in=stale_uids).delete()
        deleted_count = Exam.objects.filter(study_instance_uid__in=stale_uids).delete()[0]

    return Response({
        'created': created,
        'updated': updated,
        'deleted': deleted_count,
        'errors': errors,
        'total': len(study_ids),
        'force_refresh': force_refresh,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def orthanc_webhook(request):
    """
    Webhook appelé par Orthanc (Lua/Python plugin) quand une Study est stable.
    Attendu : POST avec {"ID": "<orthanc_study_id>", ...}
    """
    study_id = request.data.get('ID')
    if not study_id:
        return Response(
            {'error': 'ID de study manquant'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Vérifier si déjà traité
    if Exam.objects.filter(study_instance_uid=study_id).exists():
        return Response({'status': 'already_exists', 'study_id': study_id})

    # Récupérer les métadonnées depuis Orthanc
    try:
        detail = requests.get(f'{ORTHANC_URL}/studies/{study_id}', timeout=15)
        detail.raise_for_status()
        meta = detail.json()
    except requests.RequestException as e:
        return Response(
            {'error': f'Cannot reach Orthanc: {str(e)}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

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

    # Vérifier que l'étude contient au moins une série OP (fundus)
    # pour éviter la boucle de rétroaction : SEG poussé → webhook → nouveau Exam → nouvelle seg
    series_ids = meta.get('Series', [])
    has_op = False
    for sid in series_ids[:5]:
        try:
            sr = requests.get(f'{ORTHANC_URL}/series/{sid}', timeout=5)
            if sr.status_code == 200 and sr.json().get('MainDicomTags', {}).get('Modality') == 'OP':
                has_op = True
                break
        except Exception:
            continue
    if not has_op:
        return Response({'status': 'skipped_no_op', 'study_id': study_id})

    # Extraire la région depuis InstitutionName
    main_dicom = meta.get('MainDicomTags', {})
    institution = main_dicom.get('InstitutionName', '')

    exam = Exam.objects.create(
        study_instance_uid=study_id,
        patient_name=patient_name,
        patient_age=patient_age,
        exam_type='Rétinographie',
        date=study_date,
        priority='Normal',
        status='En attente',
        region=institution if institution else '',
        modality_ip='',
        notes='',
    )

    # Déclencher la segmentation automatique via MONAI Label
    # (la distribution sera déclenchée après la segmentation terminée)
    try:
        from .tasks import tache_auto_segmentation
        tache_auto_segmentation.delay()
    except Exception:
        pass

    return Response({
        'status': 'created',
        'exam_id': exam.id,
        'patient_name': patient_name,
        'study_id': study_id,
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def monai_inference_webhook(request):
    """
    Webhook appelé par MONAI Label après une inférence réussie.
    Met à jour l'examen correspondant dans la worklist avec les résultats IA.
    Body attendu: {
        "study_instance_uid": "...",
        "status": "AI_ANALYZED" | "AI_FAILED",
        "analysis": { ... }  // optionnel, résultats d'analyse
    }
    """
    study_uid = request.data.get('study_instance_uid')
    if not study_uid:
        return Response(
            {'error': 'study_instance_uid is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    ai_status = request.data.get('status', 'AI_ANALYZED')
    analysis_data = request.data.get('analysis')

    try:
        exam = Exam.objects.get(study_instance_uid=study_uid)
    except Exam.DoesNotExist:
        return Response(
            {'error': 'No exam found for this study UID'},
            status=status.HTTP_404_NOT_FOUND,
        )

    # On ne passe plus le statut à 'En cours' ici, l'examen reste 'En attente' jusqu'à son assignation.

    if analysis_data:
        AnalysisReport.objects.create(
            series_instance_uid=study_uid,
            user=None,
            report_json={
                'source': 'monai_label',
                'status': ai_status,
                'data': analysis_data,
            },
        )

    return Response({
        'status': 'updated',
        'exam_id': exam.id,
        'study_instance_uid': study_uid,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def request_composite_segmentation(request):
    """
    Appelle MONAI Label pour la segmentation composite (OD/OC + lésions + vaisseaux)
    et retourne l'overlay + résultats d'analyse.
    Body: { "study_instance_uid": "...", "image_id": "..." }
    """
    study_uid = request.data.get('study_instance_uid')
    image_id = request.data.get('image_id') or study_uid
    if not study_uid:
        return Response({'error': 'study_instance_uid is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Inject synthetic geometry into source OP DICOMs so that the generated SEG
    # shares the same FrameOfReferenceUID and OHIF can spatially align the overlay.
    # Also makes SeriesInstanceUID unique to prevent cross-patient collisions.
    try:
        from .tasks import inject_op_geometry, ORTHANC_URL
        monai_cache = os.environ.get('MONAI_CACHE_DIR', '/root/.cache/monailabel')
        study_resp = requests.get(f'{ORTHANC_URL}/studies/{study_uid}', timeout=10)
        if study_resp.status_code == 200:
            for sid in study_resp.json().get('Series', []):
                sr = requests.get(f'{ORTHANC_URL}/series/{sid}', timeout=10)
                if sr.status_code == 200 and sr.json().get('MainDicomTags', {}).get('Modality') == 'OP':
                    _, new_series_uid = inject_op_geometry(ORTHANC_URL, sid, monai_cache)
                    if new_series_uid:
                        image_id = new_series_uid
                    break
    except Exception as e:
        logger.warning(f"Geometry injection skipped for study {study_uid}: {e}")

    monai_url = "http://monai-label:8000/infer/composite_seg?output=json"
    monai_params = {"device": "cuda" if os.environ.get("USE_CUDA", "false") == "true" else "cpu"}
    try:
        resp = requests.post(
            monai_url,
            data={"image": image_id, "params": json.dumps(monai_params)},
            timeout=120,
        )
        if resp.status_code != 200:
            return Response(
                {'error': f'MONAI Label inference failed: {resp.status_code}', 'detail': resp.text},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        result = resp.json()
    except requests.exceptions.ConnectionError:
        return Response(
            {'error': 'MONAI Label server unreachable at monai-label:8000'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except requests.exceptions.Timeout:
        return Response(
            {'error': 'MONAI Label inference timed out after 120s'},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )

    overlay_base64 = result.get("overlay_base64") or result.get("params", {}).get("overlay_base64")
    payload = result if "overlay_base64" in result else result.get("params", {})
    overlay_base64 = payload.get("overlay_base64")
    analysis = {
        k: v for k, v in payload.items() if k != "overlay_base64"
    }

    AnalysisReport.objects.create(
        series_instance_uid=study_uid,
        user=None,
        report_json={
            "source": "monai_label_composite",
            "status": "AI_ANALYZED",
            "data": analysis,
        },
    )

    exam = Exam.objects.filter(study_instance_uid=study_uid).first()
    # On ne passe plus le statut à 'En cours' ici. L'assignation gère le passage à 'En cours'.

    return Response({
        "status": "completed",
        "overlay_base64": overlay_base64,
        "overlay_format": result.get("overlay_format", "png"),
        "overlay_width": result.get("overlay_width"),
        "overlay_height": result.get("overlay_height"),
        "analysis": analysis,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def distribuer_manuellement(request):
    """Déclenche manuellement la distribution des examens en attente."""
    try:
        from .tasks import tache_distribution
        tache_distribution.delay()
        return Response({'status': 'distribution lancée en arrière-plan'})
    except Exception:
        from .distribution import distribuer_examens
        result = distribuer_examens()
        return Response({'status': 'distribution synchrone terminée', **result})


@api_view(['GET'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def mes_examens(request):
    """
    Retourne les examens assignés au médecin connecté.
    Filtres optionnels : ?status=En cours&priority=Urgent
    """
    exams = Exam.objects.filter(
        Q(assigned_to=request.user) | Q(reassigned_from=request.user)
    ).order_by('-priority', 'created_at')

    status_param = request.query_params.get('status')
    if status_param:
        exams = exams.filter(status=status_param)

    priority_param = request.query_params.get('priority')
    if priority_param:
        exams = exams.filter(priority=priority_param)

    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 30))
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


@api_view(['POST'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def terminer_examen(request, pk):
    """
    Le médecin marque un examen comme 'Interprété' (terminé).
    Décrémente sa charge_actuelle.
    """
    try:
        exam = Exam.objects.get(pk=pk)
    except Exam.DoesNotExist:
        return Response({'error': 'Examen non trouvé'}, status=status.HTTP_404_NOT_FOUND)

    # Vérifier que l'examen est bien assigné à ce médecin
    if exam.assigned_to != request.user:
        return Response(
            {'error': 'Cet examen ne vous est pas assigné.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if exam.status == 'Interprété':
        return Response({'error': 'Cet examen est déjà terminé.'}, status=status.HTTP_400_BAD_REQUEST)

    # Marquer comme terminé
    exam.status = 'Interprété'
    exam.save(update_fields=['status'])

    # Décrémenter la charge du médecin
    try:
        profil = request.user.profil
        profil.charge_actuelle = max(0, profil.charge_actuelle - 1)
        profil.save(update_fields=['charge_actuelle'])
    except Exception:
        pass

    serializer = ExamSerializer(exam)
    return Response({
        'message': 'Examen marqué comme terminé.',
        'exam': serializer.data,
    })


@api_view(['PUT'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def toggle_disponibilite(request):
    """
    Le médecin toggle sa disponibilité.
    Body optionnel : {"is_disponible": true/false}
    Si pas de body, on inverse l'état actuel.
    """
    try:
        profil = request.user.profil
    except Exception:
        return Response(
            {'error': 'Profil non trouvé'},
            status=status.HTTP_404_NOT_FOUND,
        )

    new_value = request.data.get('is_disponible')
    if new_value is not None:
        profil.is_disponible = bool(new_value)
    else:
        profil.is_disponible = not profil.is_disponible

    profil.save(update_fields=['is_disponible'])

    return Response({
        'is_disponible': profil.is_disponible,
        'message': f"Disponibilité {'activée' if profil.is_disponible else 'désactivée'}.",
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
def doctor_notes(request):
    if request.method == 'GET':
        series_uid = request.query_params.get('series_instance_uid')
        if not series_uid:
            return Response(
                {'error': 'series_instance_uid is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        notes = DoctorNote.objects.filter(
            series_instance_uid=series_uid,
        )
        serializer = DoctorNoteSerializer(notes, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        series_uid = request.data.get('series_instance_uid')
        if not series_uid:
            return Response(
                {'error': 'series_instance_uid is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        text = request.data.get('text', '')
        eye = request.data.get('eye', 'both')
        note = DoctorNote.objects.create(
            series_instance_uid=series_uid,
            user=request.user if request.user.is_authenticated else None,
            eye=eye,
            text=text,
        )
        serializer = DoctorNoteSerializer(note)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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

