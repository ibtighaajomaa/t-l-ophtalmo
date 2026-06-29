import type { Exam, ExamStatus } from "@/lib/mock-worklist";

interface ApiExam {
  id: number;
  study_instance_uid: string | null;
  patient_name: string;
  patient_age: number | null;
  exam_type: string;
  date: string;
  priority: string;
  status: string;
  assigned_to: number | null;
  assigned_to_name: string | null;
  created_by: number | null;
  created_by_name: string | null;
  region: string;
  modality_ip: string;
  notes: string;
  created_at: string;
  updated_at: string;
  is_reassigned_24h?: boolean;
  reassigned_from_name?: string | null;
}

interface PaginatedResponse {
  count: number;
  page: number;
  page_size: number;
  results: ApiExam[];
}

interface ExamStats {
  total: number;
  "En attente": number;
  "En cours": number;
  Interprété: number;
  Urgent: number;
}

const BASE = "/api/exams";

function getHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("teleoph.token") || sessionStorage.getItem("teleoph.token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }
  return headers;
}

function toFrontendExam(api: ApiExam): Exam {
  let status = api.status as ExamStatus;
  if (!api.assigned_to_name && status === "En cours") {
    status = "En attente";
  }

  return {
    id: `EX-${api.id}`,
    patientName: api.patient_name,
    patientAge: api.patient_age ?? 0,
    type: api.exam_type as Exam["type"],
    date: api.date,
    priority: api.priority as Exam["priority"],
    status: status,
    assignedTo: api.assigned_to_name,
    notes: api.notes || undefined,
    region: api.region,
    modalityIp: api.modality_ip,
    studyInstanceUid: api.study_instance_uid ?? undefined,
    isReassigned24h: api.is_reassigned_24h,
    reassignedFromName: api.reassigned_from_name,
  };
}

export async function fetchExams(params?: {
  status?: string;
  q?: string;
  region?: string;
  doctor?: string;
  date?: string;
  page?: number;
  page_size?: number;
}): Promise<{ exams: Exam[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.q) searchParams.set("q", params.q);
  if (params?.region) searchParams.set("region", params.region);
  if (params?.doctor) searchParams.set("doctor", params.doctor);
  if (params?.date) searchParams.set("date", params.date);
  if (params?.page) searchParams.set("page", String(params.page));
  if (params?.page_size) searchParams.set("page_size", String(params.page_size));

  const res = await fetch(`${BASE}/?${searchParams.toString()}`, {
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch exams");
  const data: PaginatedResponse = await res.json();
  return {
    exams: data.results.map(toFrontendExam),
    total: data.count,
  };
}

export async function createExam(data: Partial<Exam>): Promise<Exam> {
  const body = {
    patient_name: data.patientName,
    patient_age: data.patientAge,
    exam_type: data.type,
    date: data.date,
    priority: data.priority,
    status: data.status,
    region: data.region,
    modality_ip: data.modalityIp,
    notes: data.notes,
    study_instance_uid: data.studyInstanceUid,
  };

  const res = await fetch(`${BASE}/`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Failed to create exam");
  }
  const api: ApiExam = await res.json();
  return toFrontendExam(api);
}

export async function updateExam(id: string, data: Partial<Exam>): Promise<Exam> {
  const numericId = id.replace("EX-", "");
  const body: Record<string, unknown> = {};
  if (data.status) body.status = data.status;
  if (data.priority) body.priority = data.priority;
  if (data.assignedTo !== undefined) body.assigned_to_name = data.assignedTo;
  if (data.region !== undefined) body.region = data.region;
  if (data.notes !== undefined) body.notes = data.notes;
  if (data.studyInstanceUid !== undefined) body.study_instance_uid = data.studyInstanceUid;

  const res = await fetch(`${BASE}/${numericId}/`, {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update exam");
  const api: ApiExam = await res.json();
  return toFrontendExam(api);
}

export async function deleteExam(id: string): Promise<void> {
  const numericId = id.replace("EX-", "");
  const res = await fetch(`${BASE}/${numericId}/`, {
    method: "DELETE",
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete exam");
}

export async function getExamStats(params?: {
  q?: string;
  region?: string;
  doctor?: string;
  date?: string;
}): Promise<ExamStats> {
  const searchParams = new URLSearchParams();
  if (params?.q) searchParams.set("q", params.q);
  if (params?.region) searchParams.set("region", params.region);
  if (params?.doctor) searchParams.set("doctor", params.doctor);
  if (params?.date) searchParams.set("date", params.date);

  const res = await fetch(`${BASE}/stats/?${searchParams.toString()}`, { headers: getHeaders() });
  if (!res.ok) throw new Error("Failed to fetch exam stats");
  return res.json();
}

export async function getExam(id: string): Promise<Exam> {
  const numericId = id.replace("EX-", "");
  const res = await fetch(`${BASE}/${numericId}/`, {
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error("Exam not found");
  const api: ApiExam = await res.json();
  return toFrontendExam(api);
}

export interface AnalysisResult {
  dr_classification: {
    grade: string;
    confidence: number;
    probabilities: { label: string; score: number }[];
  };
  lesions: {
    microaneurysms: number;
    hemorrhages: number;
    exudates: number;
    coverage_pct: number;
  };
  optic_disc_cup: {
    disc_area_px: number;
    cup_area_px: number;
    cup_disc_ratio: number;
  };
  glaucoma: {
    vcdr: number;
    risk: string;
    disc_area_px: number;
    cup_area_px: number;
  };
  vessels: {
    coverage_pct: number;
    pixel_count: number;
  };
  gradcam_image: string | null;
  clahe_image: string | null;
}

export async function runAIAnalysis(
  studyInstanceUid: string,
): Promise<{ status: string; analysis: AnalysisResult }> {
  const res = await fetch(`${BASE}/run-analysis/`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ study_instance_uid: studyInstanceUid }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "AI analysis failed");
  }
  return res.json();
}

export async function generateReport(
  analysisData: AnalysisResult,
  patientId: string,
): Promise<{ report_text: string; report_html: string }> {
  const res = await fetch(`${BASE}/generate-report/`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({
      report_data: analysisData,
      patient_id: patientId,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Report generation failed");
  }
  return res.json();
}

export async function syncWithOrthanc(): Promise<{
  created: number;
  updated: number;
  errors: number;
  total: number;
}> {
  const res = await fetch(`${BASE}/sync-orthanc/`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Failed to sync Orthanc");
  }
  return res.json();
}

export interface DoctorNote {
  id: number;
  series_instance_uid: string;
  user: number | null;
  user_name: string | null;
  eye: "right" | "left" | "both";
  text: string;
  created_at: string;
}

export async function fetchDoctorNotes(seriesInstanceUid: string): Promise<DoctorNote[]> {
  const res = await fetch(
    `${BASE}/doctor-notes/?series_instance_uid=${encodeURIComponent(seriesInstanceUid)}`,
    { headers: getHeaders() },
  );
  if (!res.ok) {
    if (res.status === 401) throw new Error("Veuillez vous reconnecter.");
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Échec du chargement des notes.");
  }
  return res.json();
}

export async function createDoctorNote(
  seriesInstanceUid: string,
  text: string,
  eye: string,
): Promise<DoctorNote> {
  const res = await fetch(`${BASE}/doctor-notes/`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({
      series_instance_uid: seriesInstanceUid,
      text,
      eye,
    }),
  });
  if (!res.ok) {
    if (res.status === 401) throw new Error("Veuillez vous reconnecter.");
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Échec de l'enregistrement de la note.");
  }
  return res.json();
}
