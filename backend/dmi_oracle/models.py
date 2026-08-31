from django.db import models


class MdExamOphtalmo(models.Model):
    """Best-guess mapping of the DMI Oracle table MD_EXAM_OPHTALMO.

    Column names/types are unverified. Before relying on this model, run
    on a host with network access to the DMI database:
        manage.py dmi_oracle_check describe --table MD_EXAM_OPHTALMO
    and correct the fields below to match.
    """

    num_resume = models.IntegerField(db_column='NUM_RESUME', primary_key=True)
    date_examen = models.DateTimeField(db_column='DATE_EXAMEN')
    cod_med = models.CharField(db_column='COD_MED', max_length=10)
    provenance = models.CharField(db_column='PROVENANCE', max_length=1)

    class Meta:
        app_label = 'dmi_oracle'
        managed = False
        db_table = 'MD_EXAM_OPHTALMO'

    def __str__(self):
        return f"Examen {self.num_resume} - {self.cod_med} - {self.provenance}"
