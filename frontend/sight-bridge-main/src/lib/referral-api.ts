/** API des patients adressés par le médecin référant. */

export type ReferralPriority = "Urgent" | "Normal";

export interface ReferralClinicalInfo {
  diabete_type?: string;
  duree_diabete?: string;
  derniere_glycemie?: string;
  date_derniere_glycemie?: string;
  derniere_hba1c?: string;
  date_derniere_hba1c?: string;
  type_traitement?: string;
  hta?: string;
  autre_pathologie?: string;
  motif_notes?: string;
}

export interface PatientReferral {
  id: number;
  patient_id: string;
  patient_age: number | null;
  priority: ReferralPriority;
  clinical_info: ReferralClinicalInfo;
  patient_history: string;
  etablissement: string;
  created_at: string;
  created_by_name: string;
  exam_id: number | null;
  exam_status: "En attente" | "En cours" | "Interprété" | null;
  exam_date: string | null;
  exam_patient_name: string;
  exam_patient_age: number | null;
}

export interface NewReferral {
  patient_id: string;
  priority: ReferralPriority;
  clinical_info: ReferralClinicalInfo;
}

const BASE = "/api/patients-adresses/";

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const token = localStorage.getItem("teleoph.token") || sessionStorage.getItem("teleoph.token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body?.fields) return Object.values(body.fields as Record<string, string>).join(" ");
    if (body?.error) return String(body.error);
  } catch {
    /* corps non JSON */
  }
  return `Erreur serveur (${res.status})`;
}

export async function listReferrals(search = ""): Promise<PatientReferral[]> {
  const qs = search ? `?search=${encodeURIComponent(search)}` : "";
  const res = await fetch(`${BASE}${qs}`, { headers: headers() });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function createReferral(data: NewReferral): Promise<PatientReferral> {
  const res = await fetch(BASE, { method: "POST", headers: headers(), body: JSON.stringify(data) });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}
