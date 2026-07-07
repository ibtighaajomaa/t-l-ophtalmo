from django.core.management.base import BaseCommand

from ophtalmo.models import Exam


class Command(BaseCommand):
    help = "Reset failed or in-progress segmentation exams back to pending."

    def add_arguments(self, parser):
        parser.add_argument(
            "--study",
            dest="study_uid",
            help="Reset only this StudyInstanceUID or stored Orthanc study ID.",
        )
        parser.add_argument(
            "--all-failed",
            action="store_true",
            help="Reset every failed segmentation exam.",
        )

    def handle(self, *args, **options):
        qs = Exam.objects.filter(exam_type="Rétinographie")
        study_uid = options.get("study_uid")
        if study_uid:
            qs = qs.filter(study_instance_uid=study_uid)
        elif options.get("all_failed"):
            qs = qs.filter(segmentation_status="failed")
        else:
            self.stderr.write("Use --study <uid> or --all-failed.")
            return

        updated = qs.update(
            segmentation_status="pending",
            segmentation_retries=0,
            segmentation_error="",
            segmentation_models_status={},
        )
        self.stdout.write(self.style.SUCCESS(f"Reset {updated} exam(s) to pending."))
