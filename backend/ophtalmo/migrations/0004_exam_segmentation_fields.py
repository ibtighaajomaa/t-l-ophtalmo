from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ophtalmo', '0003_exam_date_assignation_analysisreport'),
    ]

    operations = [
        migrations.AddField(
            model_name='exam',
            name='segmentation_status',
            field=models.CharField(
                choices=[
                    ('pending', 'En attente'),
                    ('in_progress', 'En cours'),
                    ('completed', 'Terminé'),
                    ('failed', 'Échec'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='exam',
            name='segmentation_retries',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='exam',
            name='segmentation_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='exam',
            name='segmentation_models_status',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
