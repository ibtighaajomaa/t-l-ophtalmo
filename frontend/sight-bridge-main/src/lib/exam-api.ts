import type { Exam, ExamStatus } from "@/lib/mock-worklist";

interface ApiExam {
  id: number;
  study_instance_uid: string | null;
  patient_id: string;
  patient_name: string;
  patient_birth_date: string | null;
  patient_age: number | null;
  patient_history: string;
  clinical_info?: Record<string, unknown> | null;
  exam_type: string;
  date: string;
  priority: string;
  status: string;
  assigned_to: number | null;
  assigned_to_name: string | null;
  created_by: number | null;
  created_by_name: string | null;
  region: string;
  institution_name?: string;
  modality_ip: string;
  notes: string;
  created_at: string;
  updated_at: string;
  is_reassigned_24h?: boolean;
  reassigned_from_name?: string | null;
  status_history?: Array<{ status: ExamStatus; changed_at: string }>;
  quality_status?: "pending" | "in_progress" | "completed" | "failed";
  quality_score?: number | null;
  quality_category?: "good" | "acceptable" | "bad" | "";
  quality_error?: string;
  image_quality_results?: Array<{
    orthanc_instance_id: string;
    study_instance_uid: string;
    series_instance_uid: string;
    sop_instance_uid: string;
    patient_id: string;
    score: number;
    category: "good" | "acceptable" | "bad";
    label: string;
  }>;
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

type ApiUser = {
  id?: number | string;
  firstName?: string;
  lastName?: string;
  first_name?: string;
  last_name?: string;
  username?: string;
  email?: string;
  role?: string;
  is_active?: boolean;
  isActive?: boolean;
};

export type PlatformDoctor = {
  id: string;
  name: string;
  role: string;
};

type FetchExamsParams = {
  status?: string;
  q?: string;
  region?: string;
  doctor?: string;
  date?: string;
  page?: number;
  page_size?: number;
};

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
  let patientAge = api.patient_age ?? 0;
  if (api.patient_birth_date) {
    const birthDate = new Date(`${api.patient_birth_date}T00:00:00`);
    const today = new Date();
    patientAge = today.getFullYear() - birthDate.getFullYear();
    if (
      today.getMonth() < birthDate.getMonth() ||
      (today.getMonth() === birthDate.getMonth() && today.getDate() < birthDate.getDate())
    ) {
      patientAge -= 1;
    }
  }

  return {
    id: `EX-${api.id}`,
    patientId: api.patient_id,
    patientName: api.patient_name,
    patientAge,
    patientBirthDate: api.patient_birth_date ?? undefined,
    patientHistory: api.patient_history || undefined,
    clinicalInfo: api.clinical_info ?? null,
    type: api.exam_type as Exam["type"],
    date: api.date,
    priority: api.priority as Exam["priority"],
    status: status,
    assignedTo: api.assigned_to_name,
    notes: api.notes || undefined,
    region: api.region,
    institutionName: api.institution_name || api.region || undefined,
    modalityIp: api.modality_ip,
    studyInstanceUid: api.study_instance_uid ?? undefined,
    isReassigned24h: api.is_reassigned_24h,
    reassignedFromName: api.reassigned_from_name,
    statusHistory: api.status_history?.map((event) => ({
      status: event.status,
      changedAt: event.changed_at,
    })),
    qualityStatus: api.quality_status,
    qualityScore: api.quality_score,
    qualityCategory: api.quality_category || undefined,
    qualityError: api.quality_error,
    imageQualityResults: api.image_quality_results?.map((result) => ({
      orthancInstanceId: result.orthanc_instance_id,
      studyInstanceUid: result.study_instance_uid,
      seriesInstanceUid: result.series_instance_uid,
      sopInstanceUid: result.sop_instance_uid,
      patientId: result.patient_id,
      score: result.score,
      category: result.category,
      label: result.label,
    })),
  };
}

export async function fetchExams(params?: FetchExamsParams): Promise<{ exams: Exam[]; total: number }> {
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

export async function fetchAllExams(params?: Omit<FetchExamsParams, "page" | "page_size">): Promise<{
  exams: Exam[];
  total: number;
}> {
  const pageSize = 200;
  const firstPage = await fetchExams({ ...params, page: 1, page_size: pageSize });
  const exams = [...firstPage.exams];
  const totalPages = Math.ceil(firstPage.total / pageSize);

  for (let page = 2; page <= totalPages; page += 1) {
    const result = await fetchExams({ ...params, page, page_size: pageSize });
    exams.push(...result.exams);
  }

  return { exams, total: firstPage.total };
}

export async function fetchPlatformDoctors(): Promise<PlatformDoctor[]> {
  const res = await fetch("/api/users/paginated/?page=1&size=200", {
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch doctors");

  const data = await res.json();
  const users: ApiUser[] = data.users || data.results || [];
  const doctors = new Map<string, PlatformDoctor>();

  for (const user of users) {
    const role = user.role || "";
    const isCareDoctor = role === "Medecin" || role === "Resident" || role === "Chef";
    const isActive = user.is_active !== false && user.isActive !== false;
    if (!isCareDoctor || !isActive) continue;

    const first = user.firstName ?? user.first_name ?? "";
    const last = user.lastName ?? user.last_name ?? "";
    const fallback = user.username || user.email || "";
    const title = role === "Chef" ? "Pr." : "Dr.";
    const fullName = `${title} ${first} ${last}`.trim().replace(/\s+/g, " ");
    const name = fullName === title ? fallback : fullName;
    if (!name) continue;

    const id = String(user.id ?? name);
    doctors.set(name, { id, name, role });
  }

  return [...doctors.values()].sort((a, b) => a.name.localeCompare(b.name, "fr"));
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

export interface PerEyeMetrics {
  disc_area_px: number;
  cup_area_px: number;
  cup_disc_ratio: number;
  disc_center_x: number | null;
  laterality: "OD" | "OS" | "UNKNOWN";
}

export interface PerEyeGlaucoma {
  vcdr: number;
  risk: string;
  disc_area_px: number;
  cup_area_px: number;
}

export type DRProbability = { label: string; score: number };
export type DRProbabilities = DRProbability[] | Record<string, number>;
export interface FoveaLocation {
  x_px: number;
  y_px: number;
  x_normalized: number;
  y_normalized: number;
  source_width: number;
  source_height: number;
  model: string;
}

export interface DeepSeeNetFactor {
  class_index: number;
  label: string;
  probability: number;
  probabilities: number[];
  source_sop_instance_uid?: string | null;
  source_series_uid?: string | null;
  preprocessing_mode?: "fovea_centered" | "central_crop_fallback";
}

export interface DeepSeeNetResult {
  status: string;
  aggregation: "most_critical_per_factor";
  conservative: boolean;
  note?: string;
  drusen?: DeepSeeNetFactor;
  pigment?: DeepSeeNetFactor;
  amd?: DeepSeeNetFactor;
  patient_summary?: {
    simplified_score: number | null;
    score_status: "complete" | "bilateral_input_missing";
    aggregation: string;
  };
}

export interface PerInstanceResult {
  index: number;
  optic_disc_cup: PerEyeMetrics;
  glaucoma: PerEyeGlaucoma;
  vessels: { coverage_pct: number; pixel_count: number };
  lesions: { microaneurysms: number; hemorrhages: number; exudates: number; coverage_pct: number };
  severity_score: number;
  dr_classification?: { grade: string; confidence: number; probabilities: DRProbabilities };
  gradcam_image?: string | null;
  clahe_image?: string | null;
  fovea?: FoveaLocation | null;
}

export interface CriticalEyeAnalysis {
  index: number;
  severity_score: number;
  dr_classification: { grade: string; confidence: number; probabilities: DRProbabilities };
  lesions: { microaneurysms: number; hemorrhages: number; exudates: number; coverage_pct: number };
  glaucoma: PerEyeGlaucoma;
  optic_disc_cup: PerEyeMetrics;
  vessels: { coverage_pct: number; pixel_count: number };
  gradcam_image: string | null;
  clahe_image: string | null;
  fovea?: FoveaLocation | null;
}

export interface AnalysisResult {
  dr_classification: {
    grade: string;
    confidence: number;
    probabilities: DRProbabilities;
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
  fovea?: FoveaLocation | null;
  deepseenet_plus?: DeepSeeNetResult | null;
  gradcam_image: string | null;
  clahe_image: string | null;
  per_instance?: PerInstanceResult[];
  critical?: {
    od: CriticalEyeAnalysis | null;
    os: CriticalEyeAnalysis | null;
  };
}

export type EyeSide = "right" | "left";
export type PerEyeAnalysis = Partial<Record<EyeSide, AnalysisResult & {
  side?: EyeSide;
  series_instance_uids?: string[];
  source_series_uid?: string;
}>>;

export async function runAIAnalysis(
  studyInstanceUid: string,
): Promise<{ status: string; analysis: AnalysisResult | PerEyeAnalysis }> {
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

export async function fetchAnalysis(
  studyInstanceUid: string,
): Promise<{ status: string; analysis: PerEyeAnalysis; fovea_markers?: Array<{
  study_instance_uid?: string;
  series_instance_uid?: string;
  sop_instance_uid: string;
  x_px: number;
  y_px: number;
  source_width: number;
  source_height: number;
}> }> {
  const res = await fetch(
    `${BASE}/analysis/?study_instance_uid=${encodeURIComponent(studyInstanceUid)}`,
    { headers: getHeaders() },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Analysis not found");
  }
  return res.json();
}

export async function generateReport(
  analysisData: AnalysisResult,
  patientId: string,
  options?: { patientAge?: number; eye?: string; seriesUid?: string; studyInstanceUid?: string },
): Promise<{ report_text?: string; report_html?: string; status?: string; report_generation_status?: string }> {
  const res = await fetch(`${BASE}/generate-report/`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({
      report_data: analysisData,
      patient_id: patientId,
      patient_age: options?.patientAge,
      eye: options?.eye,
      study_instance_uid: options?.studyInstanceUid,
      series_uid: options?.seriesUid,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Report generation failed");
  }
  return res.json();
}

export interface MedicalReport {
  id: number;
  patient_id: string;
  examination_id: string;
  status: string;
  ai_content: string;
  doctor_content: string;
  final_content: string;
  ai_report_data: unknown;
  validated_by_name: string | null;
  validated_at: string | null;
  signed_by_name: string | null;
  signed_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function fetchMedicalReports(examinationId: string): Promise<MedicalReport[]> {
  const res = await fetch(
    `${BASE}/medical-reports/?examination_id=${encodeURIComponent(examinationId)}&limit=1`,
    { headers: getHeaders() },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Medical report not found");
  }
  return res.json();
}

export async function updateMedicalReport(
  reportId: number,
  doctorContent: string,
  options?: { studyInstanceUid?: string },
): Promise<MedicalReport> {
  const res = await fetch(`${BASE}/medical-reports/${reportId}/`, {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify({
      doctor_content: doctorContent,
      study_instance_uid: options?.studyInstanceUid,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Échec de l'enregistrement du compte rendu.");
  }
  return res.json();
}

export async function syncWithOrthanc(): Promise<{
  created: number;
  updated: number;
  errors: number;
  total: number;
}> {
  const res = await fetch(`${BASE}/sync-orthanc/?force_refresh=true`, {
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
