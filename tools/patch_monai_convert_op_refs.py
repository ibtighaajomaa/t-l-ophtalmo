from pathlib import Path


CONVERT = Path("/usr/local/lib/python3.10/dist-packages/monailabel/datastore/utils/convert.py")
MARKER = "OHIF OP SEG: force all SEG frame refs to selected source"

old = '''            if hasattr(_p11_seg, "PerFrameFunctionalGroupsSequence"):
                for fi, fg in enumerate(_p11_seg.PerFrameFunctionalGroupsSequence):
                    _p11_uid = _p11_all_sops[fi] if fi < len(_p11_all_sops) else (_p11_expected or _p11_all_sops[0] if _p11_all_sops else None)
                    if _p11_uid:
                        _p11_total += _p11_force(fg, _p11_uid)'''

new = '''            # OHIF OP SEG: force all SEG frame refs to selected source.
            # Retinal OP models emit 2D segment frames for one selected source
            # image.  Do not spread multi-segment frames across the cached OP
            # capture series.
            if _p11_all_sops:
                try:
                    _p11_src_mod = str(getattr(_p11_src, "Modality", "")) if "_p11_src" in locals() else ""
                    if _p11_src_mod == "OP":
                        _p11_all_sops = [_p11_all_sops[0]]
                        _p11_expected = _p11_all_sops[0]
                        logger.info(f"OHIF OP SEG: forcing all SEG frame references to selected source SOP {_p11_all_sops[0]}")
                except Exception as _p11_op_ref_e:
                    logger.warning(f"OHIF OP SEG: could not force single-source references: {_p11_op_ref_e}")

            if hasattr(_p11_seg, "PerFrameFunctionalGroupsSequence"):
                for fi, fg in enumerate(_p11_seg.PerFrameFunctionalGroupsSequence):
                    _p11_uid = _p11_all_sops[fi] if fi < len(_p11_all_sops) else (_p11_expected or _p11_all_sops[0] if _p11_all_sops else None)
                    if _p11_uid:
                        _p11_total += _p11_force(fg, _p11_uid)'''


content = CONVERT.read_text()
if MARKER in content:
    print("already patched")
elif old not in content:
    raise SystemExit("Patch 11 per-frame reference block not found")
else:
    content = content.replace(old, new, 1)
    content = content.replace(
        "### OHIF_PATCH_11_FORCE_SOP ###",
        f"### {MARKER} ###\n    ### OHIF_PATCH_11_FORCE_SOP ###",
        1,
    )
    CONVERT.write_text(content)
    print("patched")
