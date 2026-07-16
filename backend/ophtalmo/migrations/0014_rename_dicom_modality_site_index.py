from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ophtalmo", "0013_dicom_modality_site"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="dicommodalitysite",
            new_name="ophtalmo_di_remote__73d7e8_idx",
            old_name="ophtalmo_dic_remote_7e878f_idx",
        ),
    ]
