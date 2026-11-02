from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ophtalmo", "0019_patientreferral_age_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="patientreferral",
            name="patient_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="patientreferral",
            name="patient_name_ar",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="patientreferral",
            name="patient_birth_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="patientreferral",
            name="patient_sex",
            field=models.CharField(blank=True, default="", max_length=1),
        ),
        migrations.AddField(
            model_name="patientreferral",
            name="ins_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
