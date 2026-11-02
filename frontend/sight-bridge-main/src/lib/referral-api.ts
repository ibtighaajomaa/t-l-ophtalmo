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
  /** INS du patient, vérifié dans le SIIS (ID à saisir sur le rétinographe). */
  patient_id: string;
  patient_age: number | null;
  patient_name: string;
  patient_name_ar: string;
  patient_birth_date: string | null;
  patient_sex: "" | "M" | "F" | "O";
  ins_verified: boolean;
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

/** Citoyen trouvé dans le SIIS (registre national de santé). */
export interface SiisPatient {
  ins: string;
  first_name_fr: string;
  last_name_fr: string;
  first_name_ar: string;
  last_name_ar: string;
  filiation_fr: string;
  filiation_ar: string;
  gender: "" | "M" | "F" | "O";
  birth_date: string;
  deceased: boolean;
}

export type InsSearch =
  | { mode: "cin"; cin: string; birth_date: string }
  | { mode: "social"; social_id: string; birth_date: string }
  | { mode: "ins"; ins: string };

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

/** Recherche de l'INS dans le SIIS (CIN ou identifiant social + date de naissance, ou INS). */
export async function searchIns(criteria: InsSearch): Promise<SiisPatient[]> {
  const res = await fetch(`${BASE}recherche-ins/`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(criteria),
  });
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as { patients: SiisPatient[] };
  return body.patients;
}
