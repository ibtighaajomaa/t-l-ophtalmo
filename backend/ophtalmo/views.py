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
from .dicom_patient import patient_metadata
from .analysis_utils import aggregate_per_eye
from .dmi_integration import (
    audit_dmi_call,
    build_compte_rendu_payload,
    build_dicom_acquisition_payload,
    is_valid_dmi_request,
    upsert_exam_from_dmi,
)

logger = logging.getLogger(__name__)


def _mark_exam_interpreted(study_instance_uid=None, series_instance_uid=None):
    """Mark the exam linked to a saved medical report as interpreted."""
    exam = None
    if study_instance_uid:
        exam = Exam.objects.filter(study_instance_uid=study_instance_uid).first()
    if not exam and series_instance_uid:
        exam = (
            Exam.objects.filter(
                image_quality_results__series_instance_uid=series_instance_uid
            )
            .distinct()
            .first()
        )

    if not exam or exam.status != Exam.Status.EN_COURS:
        return exam

    exam.status = Exam.Status.INTERPRETE
    exam.save(update_fields=['status', 'updated_at'])

    if exam.assigned_to_id:
        try:
            profil = exam.assigned_to.profil
            profil.charge_actuelle = max(0, profil.charge_actuelle - 1)
            profil.save(update_fields=['charge_actuelle'])
        except Exception:
            logger.exception(
                "Unable to decrement doctor workload for interpreted exam %s",
                exam.pk,
            )

    return exam


@api_view(['GET', 'POST'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([AllowAny])
def exam_list(request):
    if request.method == 'GET':
        # Auto-cleanup orphaned exams
        orphaned = Exam.objects.filter(status='En cours', assigned_to__isnull=True)
        if orphaned.exists():
            orphaned.update(status='En attente')
            try:
                from .distribution import distribuer_examens
                distribuer_examens()
            except Exception as e:
                logger.error(f"Error during auto-cleanup redistribution: {e}")

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
                Q(patient_name__icontains=q) | Q(patient_id__icontains=q) | Q(id__icontains=q)
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
                roles = getattr(request, 'roles', [])
                is_admin = any(r in roles for r in ('ADMIN_SYSTEME', 'ADMIN', 'Admin'))
                if not is_admin:
                    try:
                        is_admin = request.user.profil.role in ('Admin', 'ADMIN_SYSTEME')
                    except Exception:
                        pass

                if not is_admin:
                    # Tout utilisateur non-admin (Médecin, Chef, Résident ou sans rôle spécifique)
                    # ne visualise QUE les examens qui lui sont assignés
                    exams = exams.filter(Q(assigned_to=request.user) | Q(reassigned_from=request.user))
                    
                    # ET il ne visualise QUE les examens assignés LE JOUR J (aujourd'hui)
                    from django.utils import timezone
                    today = timezone.now().date()
                    exams = exams.filter(date_assignation__date=today)
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
@authentication_classes([KeycloakAuthentication])
@permission_classes([AllowAny])
def exam_stats(request):
    # Auto-cleanup orphaned exams (e.g. if a user was hard-deleted from DB)
    orphaned = Exam.objects.filter(status='En cours', assigned_to__isnull=True)
    if orphaned.exists():
        orphaned.update(status='En attente')
        try:
            from .distribution import distribuer_examens
            distribuer_examens()
        except Exception as e:
            logger.error(f"Error during auto-cleanup redistribution: {e}")

    exams = Exam.objects.all()
    if request.user.is_authenticated:
        try:
            roles = getattr(request, 'roles', [])
            is_admin = any(r in roles for r in ('ADMIN_SYSTEME', 'ADMIN', 'Admin'))
            if not is_admin:
                try:
                    is_admin = request.user.profil.role in ('Admin', 'ADMIN_SYSTEME')
                except Exception:
                    pass

            if not is_admin:
                exams = exams.filter(Q(assigned_to=request.user) | Q(reassigned_from=request.user))
                
                # Appliquer la même restriction pour les stats (seulement le jour J)
                from django.utils import timezone
                today = timezone.now().date()
                exams = exams.filter(date_assignation__date=today)
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


def _dmi_unauthorized_response():
    return Response(
        {'error': 'Token DMI manquant ou invalide'},
        status=status.HTTP_401_UNAUTHORIZED,
    )


def _dmi_response(request, body, http_status, numero_examen="", error_message=""):
    audit_dmi_call(
        request,
        numero_examen=numero_examen,
        success=200 <= http_status < 400,
        status_code=http_status,
        error_message=error_message,
    )
    return Response(body, status=http_status)


def _get_dmi_exam_or_404(numero_examen):
    return Exam.objects.filter(dmi_exam_id=numero_examen).first()


@api_view(['POST', 'PUT', 'PATCH'])
@permission_classes([AllowAny])
def dmi_exam_upsert(request):
    """
    Endpoint consommé par le DMI pour créer ou mettre à jour un examen
    dans la worklist Télé-Ophtalmo.
    POST crée ou met à jour. PUT/PATCH sont acceptés pour les mises à jour.
    """
    if not is_valid_dmi_request(request):
        audit_dmi_call(
            request,
            numero_examen=request.data.get('numero_examen', '') if isinstance(request.data, dict) else '',
            success=False,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_message='Token DMI manquant ou invalide',
        )
        return _dmi_unauthorized_response()

    try:
        exam, created = upsert_exam_from_dmi(request.data)
    except ValueError as exc:
        return _dmi_response(
            request,
            {'error': str(exc)},
            status.HTTP_400_BAD_REQUEST,
            numero_examen=request.data.get('numero_examen', '') if isinstance(request.data, dict) else '',
            error_message=str(exc),
        )
    except Exception as exc:
        logger.exception("Erreur upsert DMI examen")
        return _dmi_response(
            request,
            {'error': 'Impossible de créer ou mettre à jour l’examen', 'details': str(exc)},
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            numero_examen=request.data.get('numero_examen', '') if isinstance(request.data, dict) else '',
            error_message=str(exc),
        )

    return _dmi_response(
        request,
        {
            'created': created,
            'exam': ExamSerializer(exam).data,
        },
        status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        numero_examen=exam.dmi_exam_id,
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def dmi_exam_acquisition_dicom(request, numero_examen):
    """Endpoint lu par le DMI pour récupérer l'acquisition DICOM et la qualité."""
    if not is_valid_dmi_request(request):
        audit_dmi_call(
            request,
            numero_examen=numero_examen,
            success=False,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_message='Token DMI manquant ou invalide',
        )
        return _dmi_unauthorized_response()

    exam = _get_dmi_exam_or_404(numero_examen)
    if not exam:
        return _dmi_response(
            request,
            {'error': 'Examen introuvable'},
            status.HTTP_404_NOT_FOUND,
            numero_examen=numero_examen,
            error_message='Examen introuvable',
        )

    return _dmi_response(
        request,
        build_dicom_acquisition_payload(exam),
        status.HTTP_200_OK,
        numero_examen=exam.dmi_exam_id,
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def dmi_exam_compte_rendu(request, numero_examen):
    """Endpoint lu par le DMI pour récupérer le compte rendu final signé."""
    if not is_valid_dmi_request(request):
        audit_dmi_call(
            request,
            numero_examen=numero_examen,
            success=False,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_message='Token DMI manquant ou invalide',
        )
        return _dmi_unauthorized_response()

    exam = _get_dmi_exam_or_404(numero_examen)
    if not exam:
        return _dmi_response(
            request,
            {'error': 'Examen introuvable'},
            status.HTTP_404_NOT_FOUND,
            numero_examen=numero_examen,
            error_message='Examen introuvable',
        )

    report_filters = Q(examination_id=exam.dmi_exam_id)
    if exam.study_instance_uid:
        report_filters |= Q(examination_id=exam.study_instance_uid)
    if exam.patient_id:
        report_filters |= Q(patient_id=exam.patient_id)

    report = (
        MedicalReport.objects.filter(report_filters, status=MedicalReport.Status.SIGNED)
        .order_by('-signed_at', '-updated_at')
        .first()
    )
    if not report:
        return _dmi_response(
            request,
            {'error': 'Compte rendu final signé non disponible'},
            status.HTTP_404_NOT_FOUND,
            numero_examen=exam.dmi_exam_id,
            error_message='Compte rendu final signé non disponible',
        )

    return _dmi_response(
        request,
        build_compte_rendu_payload(exam, report),
        status.HTTP_200_OK,
        numero_examen=exam.dmi_exam_id,
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def dmi_exam_status(request, numero_examen):
    """Endpoint lu par le DMI pour récupérer uniquement le statut local."""
    if not is_valid_dmi_request(request):
        audit_dmi_call(
            request,
            numero_examen=numero_examen,
            success=False,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_message='Token DMI manquant ou invalide',
        )
        return _dmi_unauthorized_response()

    exam = _get_dmi_exam_or_404(numero_examen)
    if not exam:
        return _dmi_response(
            request,
            {'error': 'Examen introuvable'},
            status.HTTP_404_NOT_FOUND,
            numero_examen=numero_examen,
            error_message='Examen introuvable',
        )

    return _dmi_response(
        request,
        {
            'numero_examen': exam.dmi_exam_id,
            'statut': exam.status,
            'updated_at': exam.updated_at.isoformat() if exam.updated_at else None,
        },
        status.HTTP_200_OK,
        numero_examen=exam.dmi_exam_id,
    )


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

        patient = patient_metadata(meta)

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
                if existing.patient_name != patient['patient_name']:
                    existing.patient_name = patient['patient_name']
                    changed_fields.append('patient_name')
                for field in ('patient_id', 'patient_birth_date', 'patient_age', 'patient_history'):
                    if getattr(existing, field) != patient[field]:
                        setattr(existing, field, patient[field])
                        changed_fields.append(field)
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
                **patient,
                exam_type='Rétinographie',
                date=study_date,
                priority='Normal',
                status='En attente',
                region=region,
                modality_ip='',
                notes='',
            )
            created += 1

    # New studies go through FTHNet, then segmentation and distribution.
    # With no new study, retain the normal distribution behavior.
    try:
        from .tasks import tache_auto_quality, tache_distribution
        if created:
            tache_auto_quality.delay()
        else:
            tache_distribution.delay()
    except Exception:
        if created:
            tache_auto_quality()
        else:
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

    patient = patient_metadata(meta)

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
        **patient,
        exam_type='Rétinographie',
        date=study_date,
        priority='Normal',
        status='En attente',
        region=institution if institution else '',
        modality_ip='',
        notes='',
    )

    # Évaluer d'abord la qualité; cette tâche déclenche ensuite la segmentation.
    try:
        from .tasks import tache_auto_quality
        tache_auto_quality.delay()
    except Exception:
        pass

    return Response({
        'status': 'created',
        'exam_id': exam.id,
        'patient_name': patient['patient_name'],
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

    expected_patient_id = ''
    expected_study_uid = ''
    seg_ids_before = set()

    # Inject synthetic geometry into source OP DICOMs so that the generated SEG
    # shares the same FrameOfReferenceUID and OHIF can spatially align the overlay.
    # Also makes SeriesInstanceUID unique to prevent cross-patient collisions.
    try:
        from .tasks import (
            ORTHANC_URL,
            _fix_seg_association,
            _snapshot_seg_series,
            inject_op_geometry,
        )
        monai_cache = os.environ.get('MONAI_CACHE_DIR', '/root/.cache/monailabel')
        study_resp = requests.get(f'{ORTHANC_URL}/studies/{study_uid}', timeout=10)
        if study_resp.status_code == 200:
            study_data = study_resp.json()
            expected_study_uid = (
                study_data.get('MainDicomTags', {}).get('StudyInstanceUID') or study_uid
            )
            expected_patient_id = (
                study_data.get('PatientMainDicomTags', {}).get('PatientID', '')
            )
            for sid in study_data.get('Series', []):
                sr = requests.get(f'{ORTHANC_URL}/series/{sid}', timeout=10)
                if sr.status_code == 200 and sr.json().get('MainDicomTags', {}).get('Modality') == 'OP':
                    _, new_series_uid = inject_op_geometry(ORTHANC_URL, sid, monai_cache)
                    if new_series_uid:
                        image_id = new_series_uid
                    break
            seg_ids_before = _snapshot_seg_series(ORTHANC_URL)
        else:
            logger.warning(
                "Could not resolve Orthanc study %s before manual segmentation: HTTP %s",
                study_uid,
                study_resp.status_code,
            )
    except Exception as e:
        logger.warning(f"Geometry injection skipped for study {study_uid}: {e}")

    monai_url = "http://monai-label:8000/infer/composite_seg?output=json"
    monai_params = {"device": "cuda" if os.environ.get("USE_CUDA", "false") == "true" else "cpu"}
    if expected_study_uid:
        # MONAI uses this value when writing each generated DICOM-SEG. Without
        # it, a stale cached source can make every SEG inherit another study.
        monai_params["study_uid"] = expected_study_uid
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

    # Safety net: associate only the SEG series created by this request with
    # the patient/study selected in the worklist.
    try:
        seg_ids_after = _snapshot_seg_series(ORTHANC_URL)
        new_seg_ids = seg_ids_after - seg_ids_before
        if new_seg_ids:
            _fix_seg_association(
                ORTHANC_URL,
                new_seg_ids,
                expected_patient_id,
                expected_study_uid,
            )
            logger.info(
                "Checked %s manual SEG series for patient %s, study %s",
                len(new_seg_ids),
                expected_patient_id,
                expected_study_uid,
            )
    except Exception as e:
        logger.warning(f"Manual SEG association fix failed for study {study_uid}: {e}")

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
def run_analysis(request):
    """
    Triggers MONAI Label /infer/analyze for a given study and returns
    the comprehensive AI analysis report (DR grade, lesions, optic disc/cup,
    vessels, Grad-CAM, CLAHE).
    Body: { "study_instance_uid": "..." }
    """
    study_uid = request.data.get('study_instance_uid')
    if not study_uid:
        return Response({'error': 'study_instance_uid is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Find every OP (fundus) series within the study. Right/left eyes can be
    # separate OP series, so do not stop at the first one.
    logger.info(f"Looking up OP series for study: {study_uid}")
    try:
        from .tasks import (
            _collect_op_series,
            _delete_prior_ai_seg_series,
            _fix_seg_association,
            _resolve_orthanc_id,
            _prepare_monai_series_cache,
            _snapshot_seg_series,
        )
        orthanc_study_id = _resolve_orthanc_id(study_uid)
        study_data, op_series = _collect_op_series(ORTHANC_URL, orthanc_study_id)
        study_instance_dicom_uid = study_data.get('MainDicomTags', {}).get('StudyInstanceUID')
        expected_patient_id = (
            study_data.get('PatientMainDicomTags', {}).get('PatientID', '')
        )
    except requests.exceptions.ConnectionError:
        return Response(
            {'error': 'Orthanc server unreachable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except requests.RequestException as e:
        return Response(
            {'error': f'Orthanc study lookup failed: {str(e)}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if not op_series:
        return Response(
            {'error': 'No OP (fundus) series found in this study'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    monai_url = "http://monai-label:8000/infer/analyze"
    results = {}
    errors = {}

    for op_series_item in op_series:
        op_series_uid = op_series_item['series_instance_uid']
        op_orthanc_series_id = op_series_item['orthanc_series_id']
        _delete_prior_ai_seg_series(
            ORTHANC_URL,
            orthanc_study_id,
            op_series_uid,
        )
        try:
            _prepare_monai_series_cache(
                ORTHANC_URL,
                op_orthanc_series_id,
                op_series_uid,
                study_uid,
            )
        except Exception as e:
            logger.error("Failed to pre-populate MONAI Label cache for %s: %s", op_series_uid, e)
            errors[op_series_uid] = f'Failed to download DICOM files: {str(e)}'
            continue

        logger.info("Triggering AI analysis for series: %s (study: %s)", op_series_uid, study_uid)
        seg_ids_before = _snapshot_seg_series(ORTHANC_URL)
        try:
            resp = requests.post(
                monai_url,
                json={
                    "image": op_series_uid,
                    "run_segmentation": True,
                    "study_uid": study_instance_dicom_uid or study_uid,
                },
                timeout=300,
            )
            logger.info("MONAI Label response status for %s: %s", op_series_uid, resp.status_code)
            if resp.status_code != 200:
                logger.error("MONAI Label error for %s: %s", op_series_uid, resp.text)
                errors[op_series_uid] = f'MONAI Label /infer/analyze returned {resp.status_code}'
                continue
            result = resp.json()
            logger.info(
                "MONAI Label analysis result keys for %s: %s",
                op_series_uid,
                list(result.keys()) if isinstance(result, dict) else 'not dict',
            )

            # /infer/analyze creates DICOM-SEG series. Ensure they stay with
            # this exact OP source series even if MONAI had stale cache data.
            new_seg_ids = _snapshot_seg_series(ORTHANC_URL) - seg_ids_before
            if new_seg_ids:
                _fix_seg_association(
                    ORTHANC_URL,
                    new_seg_ids,
                    expected_patient_id,
                    study_instance_dicom_uid or study_uid,
                    op_series_uid,
                )
                logger.info(
                    "Checked %s analysis SEG series for source series %s",
                    len(new_seg_ids),
                    op_series_uid,
                )

            results[op_series_uid] = result
        except requests.exceptions.ConnectionError:
            logger.error("MONAI Label server unreachable at monai-label:8000")
            return Response(
                {'error': 'MONAI Label server unreachable at monai-label:8000'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except requests.exceptions.Timeout:
            logger.error("MONAI Label analysis timed out after 300s for %s", op_series_uid)
            errors[op_series_uid] = 'MONAI Label analysis timed out after 300s'

    if not results:
        return Response(
            {'error': 'AI analysis failed for all OP series', 'series_errors': errors},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    per_eye = aggregate_per_eye(results)
    report_json = {
        "source": "monai_label_analyze",
        "status": "AI_ANALYZED",
        "study_instance_uid": study_uid,
        "series_reports": results,
        "per_eye": per_eye,
    }
    analysis_report = AnalysisReport.objects.filter(series_instance_uid=study_uid).first()
    if analysis_report:
        analysis_report.user = (
            request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        )
        analysis_report.report_json = report_json
        analysis_report.save(update_fields=["user", "report_json"])
    else:
        AnalysisReport.objects.create(
            series_instance_uid=study_uid,
            user=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
            report_json=report_json,
        )

    return Response({
        "status": "completed" if not errors else "partial",
        "study_instance_uid": study_uid,
        "series_results": results,
        "series_errors": errors,
        # Backward-compatible fields for callers that expect a single result.
        "series_instance_uid": next(iter(results.keys())),
        "analysis": per_eye or next(iter(results.values())),
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


@api_view(['GET'])
@authentication_classes([KeycloakAuthentication])
@permission_classes([IsAuthenticated])
def latest_analysis(request):
    study_uid = request.query_params.get('study_instance_uid')
    if not study_uid:
        return Response(
            {'error': 'study_instance_uid is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    lookup_uids = [study_uid]
    try:
        from .tasks import _resolve_orthanc_id

        orthanc_study_id = _resolve_orthanc_id(study_uid)
        if orthanc_study_id and orthanc_study_id not in lookup_uids:
            lookup_uids.append(orthanc_study_id)
    except Exception:
        pass

    report = AnalysisReport.objects.filter(series_instance_uid__in=lookup_uids).first()
    if not report:
        return Response({'error': 'Analysis not found'}, status=status.HTTP_404_NOT_FOUND)
    report_json = report.report_json or {}
    exam = Exam.objects.filter(study_instance_uid=study_uid).first()
    if not exam and report_json.get('study_instance_uid'):
        exam = Exam.objects.filter(study_instance_uid=report_json.get('study_instance_uid')).first()

    medical_report = None
    if exam:
        medical_report = (
            MedicalReport.objects.filter(
                examination_id=str(exam.id),
            )
            .order_by('-created_at')
            .first()
        )
    if not medical_report:
        medical_report = (
            MedicalReport.objects.filter(
                examination_id__in=lookup_uids,
            )
            .order_by('-created_at')
            .first()
        )

    medical_report_data = medical_report.ai_report_data if medical_report else {}
    if not isinstance(medical_report_data, dict):
        medical_report_data = {}
    reports_by_eye = (
        report_json.get('reports_by_eye')
        or medical_report_data.get('reports_by_eye')
        or {}
    )
    return Response({
        'status': report_json.get('status', 'AI_ANALYZED'),
        'study_instance_uid': study_uid,
        'stored_study_uid': report.series_instance_uid,
        'analysis': report_json.get('per_eye') or report_json,
        'reports_by_eye': reports_by_eye,
        'report_generation_status': (
            report_json.get('report_generation_status')
            or (exam.report_generation_status if exam else None)
        ),
        'report_generation_error': (
            report_json.get('report_generation_error')
            or (exam.report_generation_error if exam else '')
        ),
        'medical_report': (
            MedicalReportSerializer(medical_report).data if medical_report else None
        ),
        'report': AnalysisReportSerializer(report).data,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def generate_report(request):
    report_data = request.data.get('report_data')
    patient_id = request.data.get('patient_id', 'inconnu')
    study_uid = request.data.get('study_instance_uid')
    series_uid = request.data.get('series_uid')
    if not report_data:
        return Response(
            {'error': 'report_data is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    exam = None
    if request.data.get('exam_id'):
        exam = Exam.objects.filter(pk=request.data.get('exam_id')).first()
    if not exam and study_uid:
        exam = Exam.objects.filter(study_instance_uid=study_uid).first()
    if not exam and series_uid:
        exam = (
            Exam.objects.filter(image_quality_results__series_instance_uid=series_uid)
            .distinct()
            .first()
        )
    if not exam and patient_id:
        exam = Exam.objects.filter(patient_id=patient_id).order_by('-created_at').first()

    if not exam:
        return Response(
            {'error': 'Unable to find the exam for background report generation'},
            status=status.HTTP_404_NOT_FOUND,
        )

    study_uid = study_uid or exam.study_instance_uid
    if not study_uid:
        return Response(
            {'error': 'study_instance_uid is required for background report generation'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    report = AnalysisReport.objects.filter(series_instance_uid=study_uid).first()
    if not report:
        try:
            per_eye = aggregate_per_eye({'manual': report_data})
        except Exception:
            per_eye = {}
        if not per_eye and isinstance(report_data, dict):
            side = 'right' if 'right' in str(request.data.get('eye', '')).lower() else 'left'
            per_eye = {side: report_data}
        report = AnalysisReport.objects.create(
            series_instance_uid=study_uid,
            user=request.user if request.user.is_authenticated else None,
            report_json={
                'source': 'manual_report_queue',
                'status': 'AI_ANALYZED',
                'study_instance_uid': study_uid,
                'series_reports': {'manual': report_data},
                'per_eye': per_eye,
                'reports_by_eye': {},
                'report_generation_status': 'pending',
                'report_generation_error': '',
            },
        )

    exam.report_generation_status = Exam.ReportGenerationStatus.PENDING
    exam.report_generation_error = ''
    exam.report_generated_at = None
    exam.save(update_fields=[
        'report_generation_status',
        'report_generation_error',
        'report_generated_at',
        'updated_at',
    ])

    from .tasks import tache_generate_ai_report

    async_result = tache_generate_ai_report.apply_async(
        args=[exam.id, report.series_instance_uid, True],
        queue='reports',
    )
    return Response(
        {
            'status': 'queued',
            'task_id': async_result.id,
            'report_generation_status': 'pending',
            'message': 'AI report generation queued',
        },
        status=status.HTTP_202_ACCEPTED,
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
            lookup_ids = {exam_id}
            exam = Exam.objects.filter(study_instance_uid=exam_id).first()
            if exam:
                lookup_ids.add(str(exam.id))
            qs = qs.filter(examination_id__in=lookup_ids)
        limit = int(request.query_params.get('limit', 50))
        qs = qs[:limit]
        serializer = MedicalReportSerializer(qs, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        patient_id = request.data.get('patient_id')
        examination_id = request.data.get('examination_id')
        study_instance_uid = request.data.get('study_instance_uid')
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
        _mark_exam_interpreted(
            study_instance_uid=study_instance_uid,
            series_instance_uid=examination_id,
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
        study_instance_uid = request.data.get('study_instance_uid')
        if doctor_content is None:
            return Response(
                {'error': 'doctor_content is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report.doctor_content = doctor_content
        if report.status == MedicalReport.Status.AI_GENERATED:
            report.status = MedicalReport.Status.UNDER_REVIEW
        if report.status == MedicalReport.Status.SIGNED or report.final_content:
            report.final_content = doctor_content
        report.save()

        max_ver = report.versions.aggregate(m=Max('version_number'))['m'] or 0
        MedicalReportVersion.objects.create(
            report=report,
            version_number=max_ver + 1,
            content=doctor_content,
            version_type=MedicalReportVersion.VersionType.DOCTOR,
            modified_by=request.user if request.user.is_authenticated else None,
        )
        _mark_exam_interpreted(
            study_instance_uid=study_instance_uid,
            series_instance_uid=report.examination_id,
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
