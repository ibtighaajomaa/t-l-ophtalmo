import json
from datetime import date
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock
from rest_framework.test import APIRequestFactory, force_authenticate
from ophtalmo.models import AnalysisReport, Exam, ImageQualityAssessment, MedicalReport
from ophtalmo.tasks import (
    _delete_prior_ai_seg_series,
    _run_eye_laterality,
    tache_auto_quality,
    tache_auto_segmentation,
)
from ophtalmo.views import (
    latest_analysis,
    orthanc_webhook,
    request_composite_segmentation,
    run_analysis,
    sync_orthanc,
)
from ophtalmo.distribution import get_examens_en_attente, distribuer_examens
from ophtalmo.analysis_utils import aggregate_per_eye


TODAY = date.today()


class FoveaAggregationTest(TestCase):
    def test_uses_fovea_from_best_quality_visual_source(self):
        reports = {
            'series:sop-low': {
                'eye_laterality': {'laterality': 'R'},
                'source': {'source_sop_instance_uid': 'sop-low'},
                'fovea': {'x_px': 10.0, 'y_px': 20.0},
            },
            'series:sop-high': {
                'eye_laterality': {'laterality': 'R'},
                'source': {'source_sop_instance_uid': 'sop-high'},
                'fovea': {'x_px': 30.0, 'y_px': 40.0},
            },
        }

        result = aggregate_per_eye(
            reports,
            quality_scores={'sop-low': 50.0, 'sop-high': 90.0},
        )

        self.assertEqual(result['right']['fovea'], {'x_px': 30.0, 'y_px': 40.0})


class PoorQualityAnalysisGuardTest(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    @patch('ophtalmo.tasks._collect_op_series')
    @patch('ophtalmo.tasks._resolve_orthanc_id', return_value='orthanc-study')
    @patch('ophtalmo.views.requests.post')
    def test_manual_analysis_is_rejected_when_every_image_requires_retake(
        self,
        requests_post,
        resolve_orthanc_id,
        collect_op_series,
    ):
        exam = Exam.objects.create(
            study_instance_uid='1.2.3.poor',
            patient_name='Patient qualité insuffisante',
            date=TODAY,
            quality_status='completed',
            quality_score=25,
            quality_category='bad',
        )
        ImageQualityAssessment.objects.create(
            exam=exam,
            orthanc_instance_id='instance-bad',
            study_instance_uid=exam.study_instance_uid,
            series_instance_uid='series-1',
            sop_instance_uid='sop-bad',
            score=25,
            category='bad',
        )
        collect_op_series.return_value = (
            {'MainDicomTags': {'StudyInstanceUID': exam.study_instance_uid}},
            [{
                'orthanc_series_id': 'series-id',
                'series_instance_uid': 'series-1',
                'instances': [{
                    'orthanc_instance_id': 'instance-bad',
                    'sop_instance_uid': 'sop-bad',
                }],
            }],
        )

        request = self.factory.post(
            '/api/exams/run-analysis/',
            {'study_instance_uid': '1.2.3.poor'},
            format='json',
        )
        response = run_analysis(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'all_images_require_retake')
        self.assertEqual(response.data['rejected_images'][0]['status'], 'retake_required')
        resolve_orthanc_id.assert_called_once_with(exam.study_instance_uid)
        requests_post.assert_not_called()


class SegmentationModelTest(TestCase):
    def test_new_exam_defaults_to_pending(self):
        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.1',
            patient_name='Test Patient',
            exam_type='Rétinographie',
            date=TODAY,
        )
        self.assertEqual(exam.segmentation_status, 'pending')
        self.assertEqual(exam.segmentation_retries, 0)
        self.assertEqual(exam.segmentation_error, '')
        self.assertIsNone(exam.segmentation_models_status)

    def test_segmentation_status_choices(self):
        for status_code in ['pending', 'in_progress', 'completed', 'failed']:
            exam = Exam.objects.create(
                study_instance_uid=f'1.2.3.4.5.6.7.8.9.{status_code}',
                patient_name='Test',
                segmentation_status=status_code,
                date=TODAY,
            )
            self.assertEqual(exam.segmentation_status, status_code)

    @patch('ophtalmo.tasks.requests.post')
    def test_dicom_laterality_overrides_model_laterality(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'params': {
                'laterality': 'R',
                'laterality_confidence': 0.73,
                'laterality_probabilities': {'R': 0.73, 'L': 0.27},
            }
        }

        result = _run_eye_laterality(
            'http://monai-label',
            '1.2.3.series.left',
            {},
            dicom_laterality='L',
        )

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['laterality'], 'L')
        self.assertEqual(result['laterality_source'], 'dicom')
        self.assertEqual(result['dicom_laterality'], 'L')
        self.assertEqual(result['model_laterality'], 'R')


class SegmentationCleanupTest(TestCase):
    @patch('ophtalmo.tasks.requests.delete')
    @patch('ophtalmo.tasks.requests.get')
    def test_deletes_only_prior_ai_seg_for_same_source_series(self, mock_get, mock_delete):
        source_series_uid = '1.2.3.source'
        other_source_uid = '1.2.3.other'

        def response(data, status_code=200):
            mock_response = MagicMock(status_code=status_code)
            mock_response.json.return_value = data
            mock_response.raise_for_status.return_value = None
            return mock_response

        def get_side_effect(url, **kwargs):
            if url.endswith('/studies/study-1'):
                return response({'Series': ['seg-match', 'seg-manual', 'seg-other-source', 'op-source']})
            if url.endswith('/series/seg-match'):
                return response({
                    'Instances': ['inst-match'],
                    'MainDicomTags': {
                        'Modality': 'SEG',
                        'SeriesDescription': 'vessel_seg',
                    },
                })
            if url.endswith('/series/seg-manual'):
                return response({
                    'Instances': ['inst-manual'],
                    'MainDicomTags': {
                        'Modality': 'SEG',
                        'SeriesDescription': 'manual_contour',
                    },
                })
            if url.endswith('/series/seg-other-source'):
                return response({
                    'Instances': ['inst-other'],
                    'MainDicomTags': {
                        'Modality': 'SEG',
                        'SeriesDescription': 'optic_disc_cup',
                    },
                })
            if url.endswith('/series/op-source'):
                return response({'MainDicomTags': {'Modality': 'OP'}})
            if url.endswith('/instances/inst-match/tags?simplify'):
                return response({'ReferencedSeriesSequence': [{'SeriesInstanceUID': source_series_uid}]})
            if url.endswith('/instances/inst-other/tags?simplify'):
                return response({'ReferencedSeriesSequence': [{'SeriesInstanceUID': other_source_uid}]})
            return response({})

        mock_get.side_effect = get_side_effect
        mock_delete.return_value.status_code = 200

        deleted = _delete_prior_ai_seg_series(
            'http://orthanc-container:8042',
            'study-1',
            source_series_uid,
        )

        self.assertEqual(deleted, 1)
        mock_delete.assert_called_once_with(
            'http://orthanc-container:8042/series/seg-match',
            timeout=30,
        )


class QualityAssociationTest(TestCase):
    @patch('ophtalmo.tasks.tache_auto_segmentation.delay')
    @patch('ophtalmo.tasks._get_fthnet_predictor')
    @patch('ophtalmo.tasks.requests.get')
    def test_rejects_quality_result_from_another_patient(
        self,
        mock_get,
        mock_get_predictor,
        _mock_segmentation_delay,
    ):
        exam = Exam.objects.create(
            study_instance_uid='orthanc-study-1',
            patient_name='Expected Patient',
            exam_type='Rétinographie',
            date=TODAY,
        )

        study_response = MagicMock(status_code=200)
        study_response.json.return_value = {
            'Series': ['orthanc-series-1'],
            'MainDicomTags': {'StudyInstanceUID': '1.2.3'},
            'PatientMainDicomTags': {'PatientID': 'PAT_EXPECTED'},
        }
        series_response = MagicMock(status_code=200)
        series_response.json.return_value = {
            'Instances': ['orthanc-instance-1'],
            'MainDicomTags': {'Modality': 'OP'},
        }
        mock_get.side_effect = [study_response, series_response]

        predictor = MagicMock()
        predictor.predict_orthanc_instance.return_value = {
            'study_instance_uid': '1.2.3',
            'series_instance_uid': '1.2.3.4',
            'sop_instance_uid': '1.2.3.4.5',
            'patient_id': 'PAT_OTHER',
            'score': 88.0,
            'category': 'good',
        }
        mock_get_predictor.return_value = predictor

        tache_auto_quality()

        exam.refresh_from_db()
        self.assertEqual(exam.quality_status, 'failed')
        self.assertIn('autre patient', exam.quality_error)
        self.assertFalse(
            ImageQualityAssessment.objects.filter(exam=exam).exists()
        )


class ManualSegmentationAssociationTest(TestCase):
    @patch('ophtalmo.tasks._fix_seg_association')
    @patch('ophtalmo.tasks._snapshot_seg_series')
    @patch('ophtalmo.tasks.inject_op_geometry')
    @patch('ophtalmo.views.requests.post')
    @patch('ophtalmo.views.requests.get')
    def test_passes_source_study_and_fixes_new_seg_series(
        self,
        mock_get,
        mock_post,
        mock_inject_geometry,
        mock_snapshot,
        mock_fix_association,
    ):
        source_study_uid = '1.2.840.10008.10'
        source_series_uid = '1.2.840.10008.20'
        patient_id = 'PAT_CORRECT'

        def get_side_effect(url, **kwargs):
            response = MagicMock(status_code=200)
            if '/studies/' in url:
                response.json.return_value = {
                    'Series': ['orthanc-op-series'],
                    'MainDicomTags': {'StudyInstanceUID': source_study_uid},
                    'PatientMainDicomTags': {'PatientID': patient_id},
                }
            else:
                response.json.return_value = {
                    'MainDicomTags': {
                        'Modality': 'OP',
                        'SeriesInstanceUID': source_series_uid,
                    },
                }
            return response

        mock_get.side_effect = get_side_effect
        mock_inject_geometry.return_value = (True, source_series_uid)
        mock_snapshot.side_effect = [
            {'old-seg-series'},
            {'old-seg-series', 'new-seg-1', 'new-seg-2', 'new-seg-3'},
        ]
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'overlay_base64': 'overlay',
            'analysis': {},
        }

        request = APIRequestFactory().post(
            '/api/exams/composite-segmentation/',
            {'study_instance_uid': source_study_uid},
            format='json',
        )
        response = request_composite_segmentation(request)

        self.assertEqual(response.status_code, 200)
        params = json.loads(mock_post.call_args.kwargs['data']['params'])
        self.assertEqual(params['study_uid'], source_study_uid)
        self.assertEqual(
            mock_post.call_args.kwargs['data']['image'],
            source_series_uid,
        )
        mock_fix_association.assert_called_once_with(
            'http://orthanc-container:8042',
            {'new-seg-1', 'new-seg-2', 'new-seg-3'},
            patient_id,
            source_study_uid,
        )


class OrthancStudyUidNormalizationTest(TestCase):
    def _response(self, data, status_code=200, text=''):
        response = MagicMock(status_code=status_code)
        response.json.return_value = data
        response.raise_for_status.return_value = None
        response.text = text
        return response

    def _study_meta(self, dicom_uid='1.2.3.dicom', patient_id='PAT1', institution='Hospital'):
        return {
            'Series': ['orthanc-series-op'],
            'MainDicomTags': {
                'StudyInstanceUID': dicom_uid,
                'StudyDate': '20260709',
                'InstitutionName': institution,
            },
            'PatientMainDicomTags': {
                'PatientID': patient_id,
                'PatientName': 'Patient^Dicom',
                'PatientBirthDate': '19700101',
            },
        }

    @patch('ophtalmo.tasks.tache_auto_quality.delay')
    @patch('ophtalmo.views.requests.get')
    def test_sync_stores_real_dicom_study_uid(self, mock_get, _mock_quality_delay):
        orthanc_id = 'orthanc-study-id'
        dicom_uid = '1.2.392.study'

        def get_side_effect(url, **kwargs):
            if url.endswith('/studies'):
                return self._response([orthanc_id])
            if url.endswith(f'/studies/{orthanc_id}'):
                return self._response(self._study_meta(dicom_uid=dicom_uid))
            return self._response({})

        mock_get.side_effect = get_side_effect

        request = APIRequestFactory().post('/api/exams/sync-orthanc/')
        response = sync_orthanc(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Exam.objects.filter(study_instance_uid=dicom_uid).exists())
        self.assertFalse(Exam.objects.filter(study_instance_uid=orthanc_id).exists())

    @patch('ophtalmo.tasks.tache_auto_quality.delay')
    @patch('ophtalmo.views.requests.get')
    def test_webhook_stores_real_dicom_study_uid(self, mock_get, _mock_quality_delay):
        orthanc_id = 'orthanc-study-id'
        dicom_uid = '1.2.392.webhook'

        def get_side_effect(url, **kwargs):
            if url.endswith(f'/studies/{orthanc_id}'):
                return self._response(self._study_meta(dicom_uid=dicom_uid))
            if url.endswith('/series/orthanc-series-op'):
                return self._response({'MainDicomTags': {'Modality': 'OP'}})
            return self._response({})

        mock_get.side_effect = get_side_effect

        request = APIRequestFactory().post(
            '/api/exams/orthanc-webhook/',
            {'ID': orthanc_id},
            format='json',
        )
        response = orthanc_webhook(request)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Exam.objects.filter(study_instance_uid=dicom_uid).exists())
        self.assertFalse(Exam.objects.filter(study_instance_uid=orthanc_id).exists())

    @patch('ophtalmo.tasks.tache_auto_quality.delay')
    @patch('ophtalmo.views.requests.get')
    def test_webhook_falls_back_to_remote_ip_site(self, mock_get, _mock_quality_delay):
        orthanc_id = 'orthanc-study-id'
        dicom_uid = '1.2.392.remote-ip'
        instance_id = 'orthanc-instance-op'

        def get_side_effect(url, **kwargs):
            if url.endswith(f'/studies/{orthanc_id}'):
                return self._response(self._study_meta(dicom_uid=dicom_uid, institution=''))
            if url.endswith('/series/orthanc-series-op'):
                return self._response({
                    'MainDicomTags': {'Modality': 'OP'},
                    'Instances': [instance_id],
                })
            if url.endswith(f'/instances/{instance_id}/metadata/RemoteIP'):
                return self._response({}, text='192.168.167.116')
            if url.endswith(f'/instances/{instance_id}/metadata/RemoteAET'):
                return self._response({}, text='Canon RC Capture')
            if url.endswith(f'/instances/{instance_id}/metadata/CalledAET'):
                return self._response({}, text='Orthanc')
            if url.endswith(f'/instances/{instance_id}/metadata/Origin'):
                return self._response({}, text='DicomProtocol')
            return self._response({}, status_code=404)

        mock_get.side_effect = get_side_effect

        request = APIRequestFactory().post(
            '/api/exams/orthanc-webhook/',
            {'ID': orthanc_id},
            format='json',
        )
        response = orthanc_webhook(request)

        self.assertEqual(response.status_code, 201)
        exam = Exam.objects.get(study_instance_uid=dicom_uid)
        self.assertEqual(exam.region, 'kelibia')
        self.assertEqual(exam.modality_ip, '192.168.167.116')


class LatestAnalysisReportIsolationTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='report-test',
            password='test',
        )
        self.exam = Exam.objects.create(
            study_instance_uid='1.2.392.report-isolation',
            patient_name='Report Test',
            patient_id='PAT-REPORT',
            date=TODAY,
            report_generation_status='in_progress',
        )
        self.analysis = AnalysisReport.objects.create(
            series_instance_uid=self.exam.study_instance_uid,
            report_json={
                'per_eye': {'right': {'side': 'right'}, 'left': {'side': 'left'}},
                'reports_by_eye': {},
                'report_generation_status': 'in_progress',
            },
        )
        MedicalReport.objects.create(
            patient_id=self.exam.patient_id,
            examination_id=str(self.exam.id),
            ai_content='Ancien rapport droit',
            ai_report_data={
                'reports_by_eye': {
                    'right': {'report_text': 'Ancien rapport droit'},
                },
                'summary_report': {'report_text': 'Ancienne synthese'},
            },
        )

    def _request(self):
        request = APIRequestFactory().get(
            '/api/exams/analysis/',
            {'study_instance_uid': self.exam.study_instance_uid},
        )
        force_authenticate(request, user=self.user)
        return latest_analysis(request)

    def test_in_progress_analysis_does_not_reuse_stale_medical_report(self):
        response = self._request()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reports_by_eye'], {})
        self.assertIsNone(response.data['summary_report'])

    def test_completed_analysis_returns_its_own_eye_reports_and_summary(self):
        current_reports = {
            'right': {'report_text': 'Rapport droit courant'},
            'left': {'report_text': 'Rapport gauche courant'},
        }
        current_summary = {'report_text': 'Synthese bilaterale courante'}
        self.analysis.report_json.update({
            'reports_by_eye': current_reports,
            'summary_report': current_summary,
            'report_generation_status': 'completed',
        })
        self.analysis.save(update_fields=['report_json'])

        response = self._request()

        self.assertEqual(response.data['reports_by_eye'], current_reports)
        self.assertEqual(response.data['summary_report'], current_summary)

class DistributionFilterTest(TestCase):
    def setUp(self):
        Exam.objects.create(
            study_instance_uid='1.1.1.1',
            patient_name='Pending Seg',
            segmentation_status='pending',
            exam_type='Rétinographie',
            date=TODAY,
        )
        Exam.objects.create(
            study_instance_uid='1.1.1.2',
            patient_name='In Progress Seg',
            segmentation_status='in_progress',
            exam_type='Rétinographie',
            date=TODAY,
        )
        Exam.objects.create(
            study_instance_uid='1.1.1.3',
            patient_name='Completed Seg',
            segmentation_status='completed',
            exam_type='Rétinographie',
            date=TODAY,
        )
        Exam.objects.create(
            study_instance_uid='1.1.1.4',
            patient_name='Failed Seg',
            segmentation_status='failed',
            exam_type='Rétinographie',
            date=TODAY,
        )

    def test_excludes_pending(self):
        eligible = list(get_examens_en_attente())
        uids = [e.study_instance_uid for e in eligible]
        self.assertNotIn('1.1.1.1', uids)

    def test_excludes_in_progress(self):
        eligible = list(get_examens_en_attente())
        uids = [e.study_instance_uid for e in eligible]
        self.assertNotIn('1.1.1.2', uids)

    def test_includes_completed(self):
        eligible = list(get_examens_en_attente())
        uids = [e.study_instance_uid for e in eligible]
        self.assertIn('1.1.1.3', uids)

    def test_includes_failed(self):
        eligible = list(get_examens_en_attente())
        uids = [e.study_instance_uid for e in eligible]
        self.assertIn('1.1.1.4', uids)

    def test_completed_comes_before_failed_by_date(self):
        eligible = list(get_examens_en_attente())
        if len(eligible) >= 2:
            self.assertEqual(eligible[0].segmentation_status, 'completed')

    def test_distribution_only_picks_completed_or_failed(self):
        result = distribuer_examens()
        self.assertEqual(result['distribues'], 0)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AutoSegmentationTaskTest(TestCase):
    def test_no_pending_exams_returns_early(self):
        result = tache_auto_segmentation()
        self.assertEqual(result['status'], 'no_pending_exams')

    def test_skips_exams_with_null_study_uid(self):
        Exam.objects.create(
            study_instance_uid=None,
            patient_name='No UID',
            segmentation_status='pending',
            exam_type='Rétinographie',
            date=TODAY,
        )
        result = tache_auto_segmentation()
        self.assertEqual(result['status'], 'no_pending_exams')

    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_sets_in_progress_immediately(self, mock_post, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'Series': [],
            'MainDicomTags': {'Modality': 'OP'},
        }

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.99',
            patient_name='Progress Test',
            segmentation_status='pending',
            quality_status='completed',
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertIn(exam.segmentation_status, ['completed', 'failed', 'in_progress'])

    @patch('ophtalmo.tasks._monai_label_ready', return_value=True)
    @patch('ophtalmo.tasks.requests.get')
    def test_handles_orthanc_unreachable(self, mock_get, _mock_monai_ready):
        cache.delete('ophtalmo:auto_segmentation_running')
        mock_get.side_effect = Exception('Connection refused')

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.98',
            patient_name='Orthanc Down',
            segmentation_status='pending',
            quality_status='completed',
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'pending')
        self.assertEqual(exam.segmentation_retries, 1)
        self.assertIn('Connection refused', exam.segmentation_error)

    @patch('ophtalmo.tasks.requests.get')
    def test_skips_when_no_op_series(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'Series': ['series-1'],
        }

        def series_detail(url, **kw):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {
                'MainDicomTags': {'Modality': 'CT'},
            }
            return m
        mock_get.side_effect = series_detail

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.97',
            patient_name='No OP',
            segmentation_status='pending',
            quality_status='completed',
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'completed')
        self.assertEqual(
            exam.segmentation_models_status,
            {'skipped': 'no OP series found'},
        )

    @patch('ophtalmo.tasks._fix_seg_association')
    @patch('ophtalmo.tasks._snapshot_seg_series')
    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_all_models_succeed(self, mock_post, mock_get, mock_snapshot, _mock_fix):
        series_uid = '1.2.3.4.5.6.7.8.9.99.1'
        mock_snapshot.side_effect = [set(), {'seg-series-1'}]
        mock_post.return_value.status_code = 200
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {}

        def get_side_effect(url, **kw):
            m = MagicMock()
            m.status_code = 200
            if '/studies/' in url:
                m.json.return_value = {'Series': ['series-op-1']}
            else:
                m.json.return_value = {
                    'MainDicomTags': {
                        'Modality': 'OP',
                        'SeriesInstanceUID': series_uid,
                    },
                }
            return m
        mock_get.side_effect = get_side_effect

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.96',
            patient_name='All Succeed',
            segmentation_status='pending',
            quality_status='completed',
            exam_type='Rétinographie',
            date=TODAY,
        )

        result = tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'completed')
        self.assertEqual(exam.segmentation_retries, 1)
        series_status = exam.segmentation_models_status[series_uid]
        self.assertEqual(
            series_status.get('optic_disc_cup'),
            'ok',
        )
        self.assertEqual(
            series_status.get('vessel_seg'),
            'ok',
        )
        self.assertEqual(
            series_status.get('lesion_seg'),
            'ok',
        )
        self.assertEqual(
            series_status.get('dr_classification'),
            'manual',
        )

    @patch('ophtalmo.tasks._fix_seg_association')
    @patch('ophtalmo.tasks._snapshot_seg_series')
    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_segments_all_op_series(self, mock_post, mock_get, mock_snapshot, _mock_fix):
        left_uid = '1.2.3.left'
        right_uid = '1.2.3.right'
        mock_snapshot.side_effect = [
            set(), {'seg-left-1'},
            {'seg-left-1'}, {'seg-left-1', 'seg-right-1'},
        ]
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {}

        def get_side_effect(url, **kw):
            m = MagicMock()
            m.status_code = 200
            if '/studies/' in url:
                m.json.return_value = {'Series': ['series-left', 'series-right']}
            elif url.endswith('/series/series-left'):
                m.json.return_value = {
                    'Instances': [],
                    'MainDicomTags': {
                        'Modality': 'OP',
                        'SeriesInstanceUID': left_uid,
                    },
                }
            else:
                m.json.return_value = {
                    'Instances': [],
                    'MainDicomTags': {
                        'Modality': 'OP',
                        'SeriesInstanceUID': right_uid,
                    },
                }
            return m
        mock_get.side_effect = get_side_effect

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.study',
            patient_name='Both Eyes',
            segmentation_status='pending',
            quality_status='completed',
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()

        self.assertEqual(exam.segmentation_status, 'completed')
        self.assertIn(left_uid, exam.segmentation_models_status)
        self.assertIn(right_uid, exam.segmentation_models_status)
        infer_urls = [
            call.args[0]
            for call in mock_post.call_args_list
            if call.args and '/infer/' in call.args[0]
        ]
        self.assertEqual(len(infer_urls), 8)

    @patch('ophtalmo.tasks._fix_seg_association')
    @patch('ophtalmo.tasks._snapshot_seg_series')
    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_one_model_fails_triggers_retry(self, mock_post, mock_get, mock_snapshot, _mock_fix):
        series_uid = '1.2.3.4.5.6.7.8.9.99.2'
        mock_snapshot.side_effect = [set(), {'seg-series-2'}]
        def post_side_effect(url, **kw):
            m = MagicMock()
            if 'vessel_seg' in url:
                m.status_code = 500
            else:
                m.status_code = 200
            m.json.return_value = {}
            return m
        mock_post.side_effect = post_side_effect

        def get_side_effect(url, **kw):
            m = MagicMock()
            m.status_code = 200
            if '/studies/' in url:
                m.json.return_value = {'Series': ['series-op-2']}
            else:
                m.json.return_value = {
                    'MainDicomTags': {
                        'Modality': 'OP',
                        'SeriesInstanceUID': series_uid,
                    },
                }
            return m
        mock_get.side_effect = get_side_effect

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.95',
            patient_name='One Fails',
            segmentation_status='pending',
            quality_status='completed',
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'pending')
        self.assertEqual(exam.segmentation_retries, 1)
        self.assertNotEqual(
            exam.segmentation_models_status[series_uid].get('vessel_seg'),
            'ok',
        )

    @patch('ophtalmo.tasks._fix_seg_association')
    @patch('ophtalmo.tasks._snapshot_seg_series')
    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_gives_up_after_max_retries(self, mock_post, mock_get, mock_snapshot, _mock_fix):
        series_uid = '1.2.3.4.5.6.7.8.9.99.3'
        mock_snapshot.side_effect = [set(), {'seg-series-3'}]
        mock_post.return_value.status_code = 500
        mock_post.return_value.json.return_value = {}

        def get_side_effect(url, **kw):
            m = MagicMock()
            m.status_code = 200
            if '/studies/' in url:
                m.json.return_value = {'Series': ['series-op-3']}
            else:
                m.json.return_value = {
                    'MainDicomTags': {
                        'Modality': 'OP',
                        'SeriesInstanceUID': series_uid,
                    },
                }
            return m
        mock_get.side_effect = get_side_effect

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.94',
            patient_name='Max Retries',
            segmentation_status='pending',
            quality_status='completed',
            segmentation_retries=2,
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'failed')
        self.assertEqual(exam.segmentation_retries, 3)
        self.assertIn('Échec après 3 tentatives', exam.segmentation_error)
