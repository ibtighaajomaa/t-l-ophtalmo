from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ophtalmo", "0008_image_quality_assessment"),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="patient_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="exam",
            name="patient_birth_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="patient_history",
            field=models.TextField(blank=True, default=""),
        ),
    ]
