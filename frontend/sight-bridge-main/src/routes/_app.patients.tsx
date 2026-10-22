import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, FileText, Loader2, Search, UserPlus } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import {
  createReferral,
  listReferrals,
  type PatientReferral,
  type ReferralClinicalInfo,
  type ReferralPriority,
} from "@/lib/referral-api";

export const Route = createFileRoute("/_app/patients")({
  component: () => (
    <ProtectedRoute roles={["MedecinReferant"]}>
      <PatientsPage />
    </ProtectedRoute>
  ),
});

// Date locale du jour au format AAAA-MM-JJ : borne des champs date (pas de bilan futur).
const TODAY_ISO = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
  .toISOString()
  .slice(0, 10);

const EMPTY_FORM = {
  patient_id: "",
  priority: "Normal" as ReferralPriority,
  clinical: {} as ReferralClinicalInfo,
};

const inputClass =
  "mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100";
const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";

function Choice({
  label,
  selected,
  onClick,
  tone = "blue",
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
  tone?: "blue" | "emerald" | "red";
}) {
  const active = {
    blue: "border-blue-500 bg-blue-50 text-blue-700",
    emerald: "border-emerald-500 bg-emerald-50 text-emerald-700",
    red: "border-red-500 bg-red-50 text-red-700",
  }[tone];
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={`flex min-h-10 items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition ${
        selected ? active : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
      }`}
    >
      <span
        className={`h-3.5 w-3.5 rounded-full border ${
          selected
            ? "border-current bg-current shadow-[inset_0_0_0_3px_white]"
            : "border-slate-300 bg-white"
        }`}
      />
      {label}
    </button>
  );
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="font-semibold text-slate-950">{title}</h3>
      {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

function StatusBadge({ referral }: { referral: PatientReferral }) {
  if (!referral.exam_status) {
    return (
      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
        En attente d'acquisition
      </span>
    );
  }
  const tone =
    referral.exam_status === "Interprété"
      ? "bg-emerald-50 text-emerald-700"
      : referral.exam_status === "En cours"
        ? "bg-blue-50 text-blue-700"
        : "bg-amber-50 text-amber-700";
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>
      Examen {referral.exam_status.toLowerCase()}
    </span>
  );
}

function PatientsPage() {
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<PatientReferral | null>(null);
  const [referrals, setReferrals] = useState<PatientReferral[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const setClinical = (key: keyof ReferralClinicalInfo, value: string) =>
    setForm((f) => ({ ...f, clinical: { ...f.clinical, [key]: value } }));

  const load = useCallback(async (q: string) => {
    setLoading(true);
    try {
      setReferrals(await listReferrals(q));
      setListError(null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search, load]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSaved(null);
    if (!form.patient_id.trim()) return setFormError("L'identifiant patient est obligatoire.");
    setSaving(true);
    try {
      const created = await createReferral({
        patient_id: form.patient_id.trim(),
        priority: form.priority,
        clinical_info: form.clinical,
      });
      setSaved(created);
      setForm(EMPTY_FORM);
      load(search.trim());
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Enregistrement impossible.");
    } finally {
      setSaving(false);
    }
  }

  const c = form.clinical;

  return (
    <>
      <Navbar
        title="Patients adressés"
        subtitle="Ajouter un patient avec ses antécédents et sa priorité"
      />
      <div className="flex-1 space-y-6 p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <Section
            title="Patient"
            subtitle="L'identifiant doit être celui saisi sur le rétinographe."
          >
            <div className="max-w-md">
              <label className="block">
                <span className={labelClass}>ID patient *</span>
                <input
                  required
                  value={form.patient_id}
                  onChange={(e) => setForm({ ...form, patient_id: e.target.value })}
                  className={inputClass}
                  placeholder="Ex. 20037559"
                  maxLength={255}
                />
              </label>
            </div>
            <div>
              <span className={labelClass}>Priorité *</span>
              <div role="radiogroup" className="mt-1.5 grid max-w-sm grid-cols-2 gap-2">
                <Choice
                  label="Normal"
                  selected={form.priority === "Normal"}
                  onClick={() => setForm({ ...form, priority: "Normal" })}
                />
                <Choice
                  label="Urgent"
                  tone="red"
                  selected={form.priority === "Urgent"}
                  onClick={() => setForm({ ...form, priority: "Urgent" })}
                />
              </div>
            </div>
          </Section>

          <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <Section title="Diabète" subtitle="Type, durée et derniers bilans biologiques.">
              <div>
                <span className={labelClass}>Type de diabète</span>
                <div role="radiogroup" className="mt-1.5 grid gap-2 sm:grid-cols-3">
                  {["Type 1", "Type 2", "Gestationnel"].map((t) => (
                    <Choice
                      key={t}
                      label={t}
                      selected={c.diabete_type === t}
                      onClick={() => setClinical("diabete_type", c.diabete_type === t ? "" : t)}
                    />
                  ))}
                </div>
              </div>
              <label className="block">
                <span className={labelClass}>Durée du diabète</span>
                <input
                  value={c.duree_diabete ?? ""}
                  onChange={(e) => setClinical("duree_diabete", e.target.value)}
                  className={inputClass}
                  placeholder="Ex. 8 ans"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
                <label className="block">
                  <span className={labelClass}>Dernière glycémie</span>
                  <input
                    value={c.derniere_glycemie ?? ""}
                    onChange={(e) => setClinical("derniere_glycemie", e.target.value)}
                    className={inputClass}
                    placeholder="g/L"
                  />
                </label>
                <label className="block">
                  <span className={labelClass}>Date</span>
                  <input
                    type="date"
                    min="1900-01-01"
                    max={TODAY_ISO}
                    value={c.date_derniere_glycemie ?? ""}
                    onChange={(e) => setClinical("date_derniere_glycemie", e.target.value)}
                    className={inputClass}
                  />
                </label>
              </div>
              <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
                <label className="block">
                  <span className={labelClass}>Dernière HbA1c</span>
                  <input
                    value={c.derniere_hba1c ?? ""}
                    onChange={(e) => setClinical("derniere_hba1c", e.target.value)}
                    className={inputClass}
                    placeholder="%"
                  />
                </label>
                <label className="block">
                  <span className={labelClass}>Date</span>
                  <input
                    type="date"
                    min="1900-01-01"
                    max={TODAY_ISO}
                    value={c.date_derniere_hba1c ?? ""}
                    onChange={(e) => setClinical("date_derniere_hba1c", e.target.value)}
                    className={inputClass}
                  />
                </label>
              </div>
            </Section>

            <Section
              title="Traitement et facteurs de risque"
              subtitle="Informations utiles avant lecture de l'examen."
            >
              <label className="block">
                <span className={labelClass}>Type de traitement</span>
                <input
                  value={c.type_traitement ?? ""}
                  onChange={(e) => setClinical("type_traitement", e.target.value)}
                  className={inputClass}
                  placeholder="Ex. insuline, ADO"
                />
              </label>
              <div>
                <span className={labelClass}>Hypertension artérielle (HTA)</span>
                <div role="radiogroup" className="mt-1.5 grid grid-cols-2 gap-2">
                  {[
                    ["OUI", "oui"],
                    ["NON", "non"],
                  ].map(([label, value]) => (
                    <Choice
                      key={value}
                      label={label}
                      tone="emerald"
                      selected={c.hta === value}
                      onClick={() => setClinical("hta", c.hta === value ? "" : value)}
                    />
                  ))}
                </div>
              </div>
              <label className="block">
                <span className={labelClass}>Autre pathologie</span>
                <textarea
                  rows={4}
                  value={c.autre_pathologie ?? ""}
                  onChange={(e) => setClinical("autre_pathologie", e.target.value)}
                  className={inputClass}
                />
              </label>
            </Section>
          </div>

          <Section title="Motif et notes">
            <textarea
              rows={4}
              value={c.motif_notes ?? ""}
              onChange={(e) => setClinical("motif_notes", e.target.value)}
              className={inputClass}
              placeholder="Motif de l'examen, autres antécédents…"
            />
          </Section>

          {formError && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0" /> {formError}
            </div>
          )}
          {saved && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              Patient {saved.patient_id} enregistré.
              {saved.exam_id
                ? " Son examen en cours a été mis à jour."
                : " Les renseignements seront joints à son examen dès l'acquisition."}
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              Ajouter le patient
            </button>
          </div>
        </form>

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
            <h3 className="font-semibold text-slate-950">Mes patients adressés</h3>
            <label className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher un ID patient"
                className="w-64 rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
              />
            </label>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold">ID patient</th>
                  <th className="px-4 py-3 text-left font-semibold">Patient</th>
                  <th className="px-4 py-3 text-left font-semibold">Priorité</th>
                  <th className="px-4 py-3 text-left font-semibold">Antécédents</th>
                  <th className="px-4 py-3 text-left font-semibold">Ajouté le</th>
                  <th className="px-4 py-3 text-left font-semibold">Suivi</th>
                  <th className="px-4 py-3 text-left font-semibold">Compte rendu</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                      <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                    </td>
                  </tr>
                ) : listError ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-red-600">
                      {listError}
                    </td>
                  </tr>
                ) : referrals.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                      Aucun patient adressé.
                    </td>
                  </tr>
                ) : (
                  referrals.map((r) => (
                    <tr key={r.id} className="align-top">
                      <td className="px-4 py-3 font-medium text-slate-900">{r.patient_id}</td>
                      <td className="px-4 py-3 text-slate-700">
                        {r.exam_patient_name ? (
                          <>
                            <div className="font-medium text-slate-900">{r.exam_patient_name}</div>
                            {(r.exam_patient_age ?? r.patient_age) != null && (
                              <div className="text-xs text-slate-500">
                                {r.exam_patient_age ?? r.patient_age} ans
                              </div>
                            )}
                          </>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                            r.priority === "Urgent"
                              ? "bg-red-50 text-red-700"
                              : "bg-slate-100 text-slate-700"
                          }`}
                        >
                          {r.priority}
                        </span>
                      </td>
                      <td className="max-w-md whitespace-pre-line px-4 py-3 text-slate-600">
                        {r.patient_history || "—"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                        {new Date(r.created_at).toLocaleDateString("fr-FR")}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge referral={r} />
                      </td>
                      <td className="px-4 py-3">
                        {r.exam_id && r.exam_status === "Interprété" ? (
                          <Link
                            to="/compte-rendu/$id"
                            params={{ id: String(r.exam_id) }}
                            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                          >
                            <FileText className="h-3.5 w-3.5" /> Voir / modifier
                          </Link>
                        ) : (
                          <span className="text-xs text-slate-400">Pas encore disponible</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
