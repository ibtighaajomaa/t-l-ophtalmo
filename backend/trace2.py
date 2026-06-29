import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from ophtalmo.distribution import distribuer_examens
print(distribuer_examens())
