from django.db import migrations, models


INITIAL_MODALITY_SITES = [
    {
        "remote_ip": "192.168.167.116",
        "remote_aet": "Canon RC Capture",
        "institution_name": "kelibia",
    },
    {
        "remote_ip": "192.168.167.117",
        "remote_aet": "RETINO_KELIBIA",
        "institution_name": "Hôpital de Kélibia",
    },
    {
        "remote_ip": "192.168.149.10",
        "remote_aet": "",
        "institution_name": "Manzel Temim",
    },
    {
        "remote_ip": "192.168.149.6",
        "remote_aet": "",
        "institution_name": "Manzel Temim",
    },
    {
        "remote_ip": "172.22.12.232",
        "remote_aet": "",
        "institution_name": "kebili",
    },
    {
        "remote_ip": "192.168.254.44",
        "remote_aet": "",
        "institution_name": "Deguech",
    },
    {
        "remote_ip": "172.22.158.100",
        "remote_aet": "",
        "institution_name": "Mateur",
    },
    {
        "remote_ip": "192.172.35.37",
        "remote_aet": "",
        "institution_name": "Siliana",
    },
]


def seed_modality_sites(apps, schema_editor):
    DicomModalitySite = apps.get_model("ophtalmo", "DicomModalitySite")
    for site in INITIAL_MODALITY_SITES:
        DicomModalitySite.objects.update_or_create(
            remote_ip=site["remote_ip"],
            remote_aet=site["remote_aet"],
            defaults={
                "institution_name": site["institution_name"],
                "is_active": True,
            },
        )


def unseed_modality_sites(apps, schema_editor):
    DicomModalitySite = apps.get_model("ophtalmo", "DicomModalitySite")
    for site in INITIAL_MODALITY_SITES:
        DicomModalitySite.objects.filter(
            remote_ip=site["remote_ip"],
            remote_aet=site["remote_aet"],
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ophtalmo", "0012_rename_dmi_audit_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="DicomModalitySite",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "remote_ip",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        max_length=64,
                    ),
                ),
                (
                    "remote_aet",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        max_length=255,
                    ),
                ),
                ("institution_name", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["institution_name", "remote_ip", "remote_aet"],
            },
        ),
        migrations.AddIndex(
            model_name="dicommodalitysite",
            index=models.Index(
                fields=["remote_ip", "remote_aet", "is_active"],
                name="ophtalmo_dic_remote_7e878f_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="dicommodalitysite",
            constraint=models.UniqueConstraint(
                fields=("remote_ip", "remote_aet"),
                name="uniq_dicom_modality_site_source",
            ),
        ),
        migrations.RunPython(seed_modality_sites, unseed_modality_sites),
    ]
