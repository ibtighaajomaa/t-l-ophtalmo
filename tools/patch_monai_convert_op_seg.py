from pathlib import Path


CONVERT = Path("/usr/local/lib/python3.10/dist-packages/monailabel/datastore/utils/convert.py")


def main():
    content = CONVERT.read_text()
    old = '''        # Fix dimension mismatch: mask z may not match source instance count
        if image_datasets:
            ref = image_datasets[0]
            expected = (len(image_datasets), int(ref.Rows), int(ref.Columns))
            mask_arr = SimpleITK.GetArrayFromImage(mask)
            if mask_arr.shape != expected and mask_arr.size == np.prod(expected):
                import itertools
                for perm in itertools.permutations(range(mask_arr.ndim)):
                    t = np.transpose(mask_arr, perm)
                    if t.shape == expected:
                        mask = SimpleITK.GetImageFromArray(t.astype(np.uint16))
                        logger.info(f"Reshaped mask {mask_arr.shape} -> {expected} via perm {perm}")
                        break

        output_file = tempfile.NamedTemporaryFile(suffix=".dcm").name'''
    new = '''        # OHIF/OP fix: retinal models output one 2D mask.  The source OP
        # series can contain several capture instances, and NIfTI axes may be
        # HxWx1 or WxHx1.  Normalize to exactly one SEG frame with Rows/Columns
        # matching the single referenced OP image.
        if image_datasets:
            ref = image_datasets[0]
            ref_rows = int(ref.Rows)
            ref_cols = int(ref.Columns)
            mask_arr = SimpleITK.GetArrayFromImage(mask)
            original_shape = mask_arr.shape

            def _as_single_frame(arr, rows, cols):
                arr = np.asarray(arr)
                if arr.ndim == 2:
                    if arr.shape == (rows, cols):
                        return arr[None, :, :]
                    if arr.shape == (cols, rows):
                        return arr.T[None, :, :]
                if arr.ndim == 3:
                    import itertools
                    for perm in itertools.permutations(range(3)):
                        t = np.transpose(arr, perm)
                        if t.shape == (1, rows, cols):
                            return t
                        if t.shape == (1, cols, rows):
                            return np.transpose(t, (0, 2, 1))
                    for axis in range(3):
                        moved = np.moveaxis(arr, axis, 0)
                        if moved.shape[1:] == (rows, cols):
                            return moved[:1]
                        if moved.shape[1:] == (cols, rows):
                            return np.transpose(moved[:1], (0, 2, 1))
                return None

            single_frame = _as_single_frame(mask_arr, ref_rows, ref_cols)
            if single_frame is not None:
                if single_frame.shape != mask_arr.shape:
                    logger.info(
                        f"OHIF OP SEG: normalized mask {original_shape} -> {single_frame.shape} "
                        f"for source Rows/Columns=({ref_rows}, {ref_cols})"
                    )
                mask = SimpleITK.GetImageFromArray(single_frame.astype(np.uint16))
                if len(image_datasets) != 1:
                    logger.info(
                        f"OHIF OP SEG: using single source DICOM for SEG reference "
                        f"instead of {len(image_datasets)} instances"
                    )
                    image_datasets = [ref]
            else:
                logger.warning(
                    f"OHIF OP SEG: could not normalize mask shape {original_shape} "
                    f"to source Rows/Columns=({ref_rows}, {ref_cols})"
                )

        output_file = tempfile.NamedTemporaryFile(suffix=".dcm").name'''

    if "OHIF OP SEG: retinal models output one 2D mask" in content:
        print("already patched")
        return
    if old not in content:
        raise SystemExit("target block not found")
    CONVERT.write_text(content.replace(old, new))
    print("patched")


if __name__ == "__main__":
    main()
