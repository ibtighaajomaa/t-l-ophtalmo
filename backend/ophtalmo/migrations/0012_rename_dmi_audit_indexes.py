from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ophtalmo", "0011_dmi_integration"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="dmiauditlog",
            old_name="ophtalmo_dm_numero__89a2d1_idx",
            new_name="ophtalmo_dm_numero__dc1ae6_idx",
        ),
        migrations.RenameIndex(
            model_name="dmiauditlog",
            old_name="ophtalmo_dm_success_3fd965_idx",
            new_name="ophtalmo_dm_success_5ee529_idx",
        ),
    ]
