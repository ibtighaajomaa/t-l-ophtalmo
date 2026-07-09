from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ophtalmo", "0009_exam_patient_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="report_generation_status",
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
        migrations.AddField(
            model_name="exam",
            name="report_generation_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="exam",
            name="report_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
