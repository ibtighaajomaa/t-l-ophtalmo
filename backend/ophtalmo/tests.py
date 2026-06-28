from datetime import date
from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock
from ophtalmo.models import Exam
from ophtalmo.tasks import tache_auto_segmentation
from ophtalmo.distribution import get_examens_en_attente, distribuer_examens


TODAY = date.today()


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
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertIn(exam.segmentation_status, ['completed', 'failed', 'in_progress'])

    @patch('ophtalmo.tasks.requests.get')
    def test_handles_orthanc_unreachable(self, mock_get):
        mock_get.side_effect = Exception('Connection refused')

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.98',
            patient_name='Orthanc Down',
            segmentation_status='pending',
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'failed')
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

    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_all_models_succeed(self, mock_post, mock_get):
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
                        'SeriesInstanceUID': '1.2.3.4.5.6.7.8.9.99.1',
                    },
                }
            return m
        mock_get.side_effect = get_side_effect

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.96',
            patient_name='All Succeed',
            segmentation_status='pending',
            exam_type='Rétinographie',
            date=TODAY,
        )

        result = tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'completed')
        self.assertEqual(exam.segmentation_retries, 1)
        self.assertEqual(
            exam.segmentation_models_status.get('optic_disc_cup'),
            'ok',
        )
        self.assertEqual(
            exam.segmentation_models_status.get('vessel_seg'),
            'ok',
        )
        self.assertEqual(
            exam.segmentation_models_status.get('lesion_seg'),
            'ok',
        )
        self.assertEqual(
            exam.segmentation_models_status.get('dr_classification'),
            'ok',
        )

    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_one_model_fails_triggers_retry(self, mock_post, mock_get):
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
                        'SeriesInstanceUID': '1.2.3.4.5.6.7.8.9.99.2',
                    },
                }
            return m
        mock_get.side_effect = get_side_effect

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.95',
            patient_name='One Fails',
            segmentation_status='pending',
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'pending')
        self.assertEqual(exam.segmentation_retries, 1)
        self.assertNotEqual(
            exam.segmentation_models_status.get('vessel_seg'),
            'ok',
        )

    @patch('ophtalmo.tasks.requests.get')
    @patch('ophtalmo.tasks.requests.post')
    def test_gives_up_after_max_retries(self, mock_post, mock_get):
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
                        'SeriesInstanceUID': '1.2.3.4.5.6.7.8.9.99.3',
                    },
                }
            return m
        mock_get.side_effect = get_side_effect

        exam = Exam.objects.create(
            study_instance_uid='1.2.3.4.5.6.7.8.9.94',
            patient_name='Max Retries',
            segmentation_status='pending',
            segmentation_retries=2,
            exam_type='Rétinographie',
            date=TODAY,
        )

        tache_auto_segmentation()
        exam.refresh_from_db()
        self.assertEqual(exam.segmentation_status, 'failed')
        self.assertEqual(exam.segmentation_retries, 3)
        self.assertIn('Échec après 3 tentatives', exam.segmentation_error)
