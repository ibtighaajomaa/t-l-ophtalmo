from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ophtalmo", "0010_exam_report_generation_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="clinical_info",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_code_ccam",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_date_episode",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_exam_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_matricule",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_medecin_referent_code",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_medecin_referent_nom",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_provenance",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_service_code",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="exam",
            name="dmi_service_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.CreateModel(
            name="DMIAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("endpoint", models.CharField(max_length=255)),
                ("method", models.CharField(max_length=10)),
                ("caller_ip", models.CharField(blank=True, default="", max_length=64)),
                ("numero_examen", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("success", models.BooleanField(default=False)),
                ("status_code", models.PositiveIntegerField(default=0)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["numero_examen", "created_at"], name="ophtalmo_dm_numero__89a2d1_idx"),
                    models.Index(fields=["success", "created_at"], name="ophtalmo_dm_success_3fd965_idx"),
                ],
            },
        ),
    ]
