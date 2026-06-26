#!/usr/bin/env python3
"""
Test script to verify SEG display readiness in OHIF.
Runs from HOST machine (has docker + port 8002 access).
"""
import json, os, sys, time, subprocess, urllib.request, urllib.error, urllib.parse

ORTHANC = "http://orthanc-container:8042"
MONAI_HOST = "http://localhost:8002"
DOCKER_NAME = "monai-label"
TESTS_PASSED = 0
TESTS_FAILED = 0

REQUIRED_SERIES_UID = "1.2.826.0.1.3680043.10.14693038617622535132311656803458854870001"
EXPECTED_SOP_UID = "1.2.826.0.1.3680043.10.99536044805193102263881551734304074003047"
EXPECTED_STUDY_UID = "1.2.826.0.1.3680043.10.44871876904305139559864264473950195659282"


def log(name, passed, detail=""):
    global TESTS_PASSED, TESTS_FAILED
    if passed:
        TESTS_PASSED += 1
        print(f"  PASS  {name}")
    else:
        TESTS_FAILED += 1
        print(f"  FAIL  {name}: {detail}")


def docker_exec(cmd):
    """Run a command inside the monai-label container."""
    return subprocess.run(
        ["docker", "exec", DOCKER_NAME] + cmd,
        capture_output=True, text=True, timeout=30,
    )


def orthanc_get(path):
    r = docker_exec(["curl", "-s", f"{ORTHANC}{path}"])
    try:
        return json.loads(r.stdout) if r.stdout else {}
    except (json.JSONDecodeError, ValueError):
        return {"_error": r.stdout[:200]}


def orthanc_post(path, data):
    r = docker_exec([
        "curl", "-s", "-X", "POST", f"{ORTHANC}{path}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(data),
    ])
    try:
        return json.loads(r.stdout) if r.stdout else {}
    except (json.JSONDecodeError, ValueError):
        return {"_error": r.stdout[:200]}


def get_docker_logs():
    r = subprocess.run(["docker", "logs", DOCKER_NAME], capture_output=True, text=True, timeout=10)
    return r.stdout + r.stderr


def extract_ref_sops(item, ref_set, depth=0):
    if depth > 10:
        return
    if isinstance(item, dict):
        for k, v in item.items():
            if k == "ReferencedSOPInstanceUID":
                ref_set.add(str(v))
            elif isinstance(v, (dict, list)):
                extract_ref_sops(v, ref_set, depth + 1)
    elif isinstance(item, list):
        for i in item:
            extract_ref_sops(i, ref_set, depth + 1)


def run_tests():
    global TESTS_PASSED, TESTS_FAILED
    TESTS_PASSED = TESTS_FAILED = 0
    print("=" * 60)
    print("SEG Display Readiness Test Suite")
    print("=" * 60)

    # ── Test 1: Orthanc connectivity ──
    print("\n[1] Orthanc Connectivity")
    studies = orthanc_get("/studies")
    log("Orthanc reachable", isinstance(studies, (list, dict)) and "_error" not in studies,
        studies.get("_error", "") if isinstance(studies, dict) else str(studies)[:200])

    # ── Test 2: Find OP instance in Orthanc ──
    print("\n[2] OP Instance Lookup")
    result = orthanc_post("/tools/find", {
        "Level": "instance",
        "Query": {"StudyInstanceUID": EXPECTED_STUDY_UID, "SeriesInstanceUID": REQUIRED_SERIES_UID},
    })
    op_id = None
    if isinstance(result, list) and result:
        first = result[0]
        op_id = first if isinstance(first, str) else first.get("ID")
    log("OP instance found", bool(op_id), str(result)[:200] if isinstance(result, (list, dict)) else str(result))
    if not op_id:
        return

    op_tags = orthanc_get(f"/instances/{op_id}/simplified-tags")
    log("OP tags readable", isinstance(op_tags, dict) and bool(op_tags.get("SOPInstanceUID")))
    if not isinstance(op_tags, dict):
        return

    # ── Test 3: Verify OP SOPInstanceUID ──
    print("\n[3] OP SOPInstanceUID Match")
    actual_op_sop = op_tags.get("SOPInstanceUID", "")
    log("OP SOPInstanceUID correct", actual_op_sop == EXPECTED_SOP_UID, f"Got {actual_op_sop}")

    # ── Test 4: Check OP dimensions ──
    print("\n[4] OP Image Dimensions")
    op_rows = int(op_tags.get("Rows", 0))
    op_cols = int(op_tags.get("Columns", 0))
    op_samples = int(op_tags.get("SamplesPerPixel", 1))
    log("OP is 224x224", op_rows == 224 and op_cols == 224, f"Got {op_rows}x{op_cols}")
    log("OP is RGB (3 samples)", op_samples == 3, f"Got {op_samples} samples/pixel")

    # ── Test 5: Trigger segmentation ──
    print("\n[5] Trigger Segmentation")
    req = urllib.request.Request(
        f"{MONAI_HOST}/infer/optic_disc_cup?image={REQUIRED_SERIES_UID}&save_label=true",
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        log("Segmentation succeeded", resp.status == 200, f"Status {resp.status}")
        resp.read()
    except urllib.error.HTTPError as e:
        log("Segmentation succeeded", False, f"HTTP {e.code}: {e.read().decode()[:200]}")
        return
    except Exception as e:
        log("Segmentation succeeded", False, str(e)[:200])
        return

    # ── Test 6: Check Patch 11 logs ──
    print("\n[6] Patch 11 Log Verification")
    time.sleep(2)
    monai_log = get_docker_logs()
    log("Patch 11 forced SOP " + EXPECTED_SOP_UID[-20:],
        "Forced" in monai_log and EXPECTED_SOP_UID in monai_log)
    log("Patch 11 queried Orthanc for SOP",
        "Orthanc SOPInstanceUID" in monai_log and EXPECTED_SOP_UID in monai_log)
    log("Patch 11 set SEG PatientID from Orthanc",
        "Set SEG PatientID from Orthanc" in monai_log)
    log("SEG pushed successfully",
        "Pushed DICOM-SEG to Orthanc: 200" in monai_log)
    log("No patient_id injection",
        "Injected tags into source" not in monai_log,
        "Found 'Injected tags into source' in log")

    # ── Test 7: Find SEG in Orthanc ──
    print("\n[7] SEG in Orthanc")
    # Find all SEG instances
    all_instances = orthanc_get("/instances")
    seg_ids = []
    for inst_id in all_instances if isinstance(all_instances, list) else []:
        tags = orthanc_get(f"/instances/{inst_id}/simplified-tags")
        if tags.get("Modality") == "SEG":
            # Check it's in our test study
            if tags.get("StudyInstanceUID") == EXPECTED_STUDY_UID:
                seg_ids.append((inst_id, tags))

    log("SEG instances found in study", bool(seg_ids), f"Found {len(seg_ids)}")
    if not seg_ids:
        return

    # Use the most recent SEG
    last_seg_id, seg_tags = seg_ids[-1]
    log("SEG tags readable", True)

    # ── Test 8: SEG SOPInstanceUID reference ──
    print("\n[8] SEG ReferencedSOPInstanceUID")
    full_tags = orthanc_get(f"/instances/{last_seg_id}/tags")
    ref_sops = set()
    extract_ref_sops(full_tags, ref_sops)
    log("SEG references correct SOPInstanceUID",
        EXPECTED_SOP_UID in ref_sops,
        f"SEG references {ref_sops}")

    # ── Test 9: PatientID consistency ──
    print("\n[9] PatientID Consistency (OHIF 'Multiple Patients' fix)")
    op_pid = op_tags.get("PatientID", "")
    seg_pid = seg_tags.get("PatientID", "")
    log("PatientID matches OP and SEG",
        op_pid == seg_pid and bool(op_pid),
        f"OP '{op_pid}', SEG '{seg_pid}'")

    # ── Test 10: StudyInstanceUID consistency ──
    print("\n[10] StudyInstanceUID Consistency")
    op_study = op_tags.get("StudyInstanceUID", "")
    seg_study = seg_tags.get("StudyInstanceUID", "")
    log("StudyInstanceUID matches",
        op_study == seg_study and bool(op_study),
        f"OP '{op_study}', SEG '{seg_study}'")

    # ── Test 11: SEG dimensions match OP ──
    print("\n[11] SEG Dimensions")
    seg_rows = int(seg_tags.get("Rows", 0))
    seg_cols = int(seg_tags.get("Columns", 0))
    log("SEG is 224x224", seg_rows == 224 and seg_cols == 224, f"Got {seg_rows}x{seg_cols}")
    log("SEG dimensions match OP",
        seg_rows == op_rows and seg_cols == op_cols,
        f"SEG {seg_rows}x{seg_cols} vs OP {op_rows}x{op_cols}")

    # ── Test 12: SEG modality ──
    print("\n[12] SEG Type")
    log("Modality is SEG", seg_tags.get("Modality") == "SEG", f"Got '{seg_tags.get('Modality')}'")

    # ── Summary ──
    print("\n" + "=" * 60)
    print(f"RESULTS: {TESTS_PASSED} passed, {TESTS_FAILED} failed")
    print("=" * 60)
    return TESTS_FAILED == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
