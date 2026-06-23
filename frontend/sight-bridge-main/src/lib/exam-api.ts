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
  "Interprété": number;
  Urgent: number;
}

const BASE = "/api/exams";

function getHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (typeof window !== "undefined") {
    const token = sessionStorage.getItem("teleoph.token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }
  return headers;
}

function toFrontendExam(api: ApiExam): Exam {
  return {
    id: `EX-${api.id}`,
    patientName: api.patient_name,
    patientAge: api.patient_age ?? 0,
    type: api.exam_type as Exam["type"],
    date: api.date,
    priority: api.priority as Exam["priority"],
    status: api.status as ExamStatus,
    assignedTo: api.assigned_to_name,
    notes: api.notes || undefined,
    region: api.region,
    modalityIp: api.modality_ip,
    studyInstanceUid: api.study_instance_uid ?? undefined,
  };
}

export async function fetchExams(params?: {
  status?: string;
  q?: string;
  region?: string;
  doctor?: string;
  today_only?: boolean;
  page?: number;
  page_size?: number;
}): Promise<{ exams: Exam[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.q) searchParams.set("q", params.q);
  if (params?.region) searchParams.set("region", params.region);
  if (params?.doctor) searchParams.set("doctor", params.doctor);
  if (params?.today_only) searchParams.set("today_only", "true");
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

export async function updateExam(
  id: string,
  data: Partial<Exam>,
): Promise<Exam> {
  const numericId = id.replace("EX-", "");
  const body: Record<string, unknown> = {};
  if (data.status) body.status = data.status;
  if (data.priority) body.priority = data.priority;
  if (data.assignedTo !== undefined) body.assigned_to_name = data.assignedTo;
  if (data.region !== undefined) body.region = data.region;
  if (data.notes !== undefined) body.notes = data.notes;
  if (data.studyInstanceUid !== undefined)
    body.study_instance_uid = data.studyInstanceUid;

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

export async function getExamStats(): Promise<ExamStats> {
  const res = await fetch(`${BASE}/stats/`, { headers: getHeaders() });
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

export async function syncWithOrthanc(): Promise<{
  created: number;
  skipped: number;
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
