from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ophtalmo", "0015_examstatushistory")]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="segmentation_task_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="exam",
            name="segmentation_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="segmentation_heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="segmentation_current_step",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="exam",
            name="report_generation_task_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="exam",
            name="report_generation_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="report_generation_heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exam",
            name="report_generation_current_step",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
