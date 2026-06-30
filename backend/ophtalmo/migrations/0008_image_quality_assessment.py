from django.db import migrations, models
import django.db.models.deletion


def mark_existing_exams_migrated(apps, schema_editor):
    # Automatic quality applies to exams created after this deployment.
    # Avoid unexpectedly reprocessing the entire historical Orthanc archive.
    Exam = apps.get_model("ophtalmo", "Exam")
    Exam.objects.update(quality_status="completed")


class Migration(migrations.Migration):
    dependencies = [("ophtalmo", "0007_exam_is_reassigned_24h_exam_reassigned_from")]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="quality_category",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="exam",
            name="quality_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="exam",
            name="quality_score",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="quality_status",
            field=models.CharField(
                choices=[
                    ("pending", "En attente"),
                    ("in_progress", "En cours"),
                    ("completed", "Terminé"),
                    ("failed", "Échec"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="ImageQualityAssessment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("orthanc_instance_id", models.CharField(db_index=True, max_length=255)),
                ("study_instance_uid", models.CharField(blank=True, default="", max_length=255)),
                ("series_instance_uid", models.CharField(blank=True, default="", max_length=255)),
                ("sop_instance_uid", models.CharField(max_length=255, unique=True)),
                ("patient_id", models.CharField(blank=True, default="", max_length=255)),
                ("modality", models.CharField(default="OP", max_length=16)),
                ("score", models.FloatField()),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("good", "Bonne qualité"),
                            ("acceptable", "Qualité acceptable"),
                            ("bad", "Qualité mauvaise"),
                        ],
                        max_length=20,
                    ),
                ),
                ("analyzed_at", models.DateTimeField(auto_now=True)),
                (
                    "exam",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="image_quality_results",
                        to="ophtalmo.exam",
                    ),
                ),
            ],
            options={"ordering": ["series_instance_uid", "sop_instance_uid"]},
        ),
        migrations.RunPython(mark_existing_exams_migrated, migrations.RunPython.noop),
    ]
