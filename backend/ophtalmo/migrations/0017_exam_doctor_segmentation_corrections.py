from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ophtalmo", "0016_exam_task_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="doctor_segmentation_corrections",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
