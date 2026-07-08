from pathlib import Path


INFER = Path("/usr/local/lib/python3.10/dist-packages/monailabel/endpoints/infer.py")
MARKER = "OHIF OP SEG: preserve single-instance cache"

old = '''            if os.path.isdir(_study_cache_dir):
                shutil.rmtree(_study_cache_dir, ignore_errors=True)
            if os.path.isfile(_study_cache_nifti):
                os.unlink(_study_cache_nifti)
            logger.info(
                f"Cleared series-only cache for study-specific inference: "
                f"{str(study_uid_hint)[:40]}..."
            )'''

new = '''            _source_sop_uid = p.get("source_sop_instance_uid") or request.get("source_sop_instance_uid")
            if _source_sop_uid:
                # OHIF OP SEG: preserve single-instance cache
                # Backend already populated _study_cache_dir with one DICOM.
                # Remove stale derived files/index entries only.
                if os.path.isfile(_study_cache_nifti):
                    os.unlink(_study_cache_nifti)
                try:
                    if hasattr(ds._datastore, "_images"):
                        ds._datastore._images.pop(_study_cache_image, None)
                except Exception:
                    pass
                logger.info(
                    f"Preserved single-instance cache for SOP {_source_sop_uid}; "
                    f"cleared derived NIfTI for {str(study_uid_hint)[:40]}..."
                )
            else:
                if os.path.isdir(_study_cache_dir):
                    shutil.rmtree(_study_cache_dir, ignore_errors=True)
                if os.path.isfile(_study_cache_nifti):
                    os.unlink(_study_cache_nifti)
                logger.info(
                    f"Cleared series-only cache for study-specific inference: "
                    f"{str(study_uid_hint)[:40]}..."
                )'''


content = INFER.read_text()
if MARKER in content:
    print("already patched")
elif old not in content:
    raise SystemExit("study cache clear block not found")
else:
    INFER.write_text(content.replace(old, new, 1))
    print("patched")
