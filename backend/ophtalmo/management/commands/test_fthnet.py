import json
import os
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from ophtalmo.fthnet_cpu import FTHNetCPU, MODEL_ROOT


class Command(BaseCommand):
    help = "Run FTHNet CPU on an OP DICOM, an Orthanc instance, or a study."

    def add_arguments(self, parser):
        parser.add_argument(
            "image",
            nargs="?",
            help="Local OP DICOM/image path",
        )
        parser.add_argument("--orthanc-instance", help="Orthanc instance ID")
        parser.add_argument(
            "--orthanc-study",
            help="Orthanc study ID or StudyInstanceUID; analyzes every OP instance",
        )
        parser.add_argument(
            "--orthanc-url",
            default=os.environ.get("ORTHANC_URL", "http://orthanc-container:8042"),
        )

    def handle(self, *args, **options):
        try:
            predictor = FTHNetCPU()
            if options["orthanc_instance"]:
                result = predictor.predict_orthanc_instance(
                    options["orthanc_instance"], options["orthanc_url"]
                )
                self.stdout.write(json.dumps(result, ensure_ascii=False))
                return

            if options["orthanc_study"]:
                base = options["orthanc_url"].rstrip("/")
                response = requests.get(
                    f"{base}/studies/{options['orthanc_study']}", timeout=30
                )
                response.raise_for_status()
                results = []
                for series_id in response.json().get("Series", []):
                    series_response = requests.get(
                        f"{base}/series/{series_id}", timeout=30
                    )
                    series_response.raise_for_status()
                    series = series_response.json()
                    if (
                        str(series.get("MainDicomTags", {}).get("Modality", "")).upper()
                        != "OP"
                    ):
                        continue
                    for instance_id in series.get("Instances", []):
                        results.append(
                            predictor.predict_orthanc_instance(instance_id, base)
                        )
                if not results:
                    raise CommandError("No OP instances found in this Orthanc study")
                self.stdout.write(
                    json.dumps(
                        {"study": options["orthanc_study"], "images": results},
                        ensure_ascii=False,
                    )
                )
                return

            image_value = options["image"]
            if not image_value:
                image_value = str(
                    MODEL_ROOT
                    / "datasets"
                    / "sample_dataset"
                    / "images"
                    / "00000.PNG"
                )
            image = Path(image_value)
            if not image.is_file():
                raise CommandError(f"Image not found: {image}")
            result = predictor.predict_file(image)
            self.stdout.write(json.dumps(result, ensure_ascii=False))
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(str(exc)) from exc
