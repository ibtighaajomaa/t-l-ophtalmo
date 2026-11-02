/**
 * Médecin référant — formulaire d'ajout d'un patient adressé.
 * Le patient est identifié par son INS, recherché dans le SIIS ; l'INS devient l'ID patient.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardList,
  Loader2,
  Search,
  ShieldCheck,
  UserPlus,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import {
  createReferral,
  searchIns,
  type InsSearch,
  type PatientReferral,
  type ReferralClinicalInfo,
  type ReferralPriority,
  type SiisPatient,
} from "@/lib/referral-api";

export const Route = createFileRoute("/_app/ajouter-patient")({
  component: () => (
    <ProtectedRoute roles={["MedecinReferant"]}>
      <AddPatientPage />
    </ProtectedRoute>
  ),
});

// Date locale du jour au format AAAA-MM-JJ : borne des champs date (pas de bilan futur).
const TODAY_ISO = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
  .toISOString()
  .slice(0, 10);

const EMPTY_FORM = {
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

type SearchMode = InsSearch["mode"];

const SEARCH_MODES: { value: SearchMode; label: string }[] = [
  { value: "cin", label: "CIN" },
  { value: "social", label: "Identifiant social" },
  { value: "ins", label: "INS" },
];

const SEX_LABELS: Record<string, string> = { M: "Homme", F: "Femme", O: "Autre" };

const EMPTY_CRITERIA = { cin: "", social_id: "", ins: "", birth_date: "" };

/** AAAA-MM-JJ → JJ/MM/AAAA, sans passer par Date (pas de décalage de fuseau). */
function formatDate(iso: string) {
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
}

const fullName = (first: string, last: string) => [first, last].filter(Boolean).join(" ");

function PatientIdentity({ patient }: { patient: SiisPatient }) {
  const nameFr = fullName(patient.first_name_fr, patient.last_name_fr);
  const nameAr = fullName(patient.first_name_ar, patient.last_name_ar);
  const filiation = patient.filiation_fr || patient.filiation_ar;
  const details = [
    `INS ${patient.ins}`,
    SEX_LABELS[patient.gender],
    patient.birth_date && `Né(e) le ${formatDate(patient.birth_date)}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="min-w-0">
      <div className="font-semibold text-slate-950">
        <bdi>{nameFr || nameAr || "Nom non renseigné"}</bdi>
      </div>
      {nameFr && nameAr && (
        <div className="text-sm text-slate-600">
          <bdi lang="ar">{nameAr}</bdi>
        </div>
      )}
      <div className="mt-0.5 text-xs text-slate-500">{details}</div>
      {filiation && (
        <div className="text-xs text-slate-500">
          Filiation : <bdi>{filiation}</bdi>
        </div>
      )}
    </div>
  );
}

/** Recherche du patient dans le SIIS par CIN, identifiant social ou INS. */
function InsLookup({ onSelect }: { onSelect: (patient: SiisPatient) => void }) {
  const [mode, setMode] = useState<SearchMode>("cin");
  const [values, setValues] = useState(EMPTY_CRITERIA);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SiisPatient[] | null>(null);

  const set = (key: keyof typeof EMPTY_CRITERIA, value: string) =>
    setValues((v) => ({ ...v, [key]: value }));

  function criteria(): InsSearch | string {
    if (mode === "ins") {
      const ins = values.ins.trim();
      return /^[0-9A-Za-z]{4,32}$/.test(ins)
        ? { mode, ins }
        : "INS invalide (chiffres et lettres uniquement).";
    }
    const birth_date = values.birth_date;
    if (mode === "cin") {
      const cin = values.cin.trim();
      if (!/^\d{8}$/.test(cin)) return "Le numéro de CIN comporte 8 chiffres.";
      if (!birth_date) return "La date de naissance est obligatoire.";
      return { mode, cin, birth_date };
    }
    const social_id = values.social_id.trim();
    if (!/^\d{4,20}$/.test(social_id)) return "Identifiant social invalide (chiffres uniquement).";
    if (!birth_date) return "La date de naissance est obligatoire.";
    return { mode, social_id, birth_date };
  }

  async function search() {
    const c = criteria();
    setResults(null);
    if (typeof c === "string") return setError(c);
    setError(null);
    setSearching(true);
    try {
      const found = await searchIns(c);
      setResults(found);
      if (found.length === 1 && !found[0].deceased) onSelect(found[0]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recherche impossible.");
    } finally {
      setSearching(false);
    }
  }

  // Entrée lance la recherche au lieu d'envoyer tout le formulaire.
  const searchOnEnter = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (!searching) search();
    }
  };

  const idField = {
    cin: { key: "cin", label: "N° CIN *", placeholder: "8 chiffres", numeric: true, max: 8 },
    social: {
      key: "social_id",
      label: "Identifiant social *",
      placeholder: "Ex. 3017037173",
      numeric: true,
      max: 20,
    },
    ins: { key: "ins", label: "INS *", placeholder: "Ex. 7061422925", numeric: false, max: 32 },
  }[mode] as {
    key: keyof typeof EMPTY_CRITERIA;
    label: string;
    placeholder: string;
    numeric: boolean;
    max: number;
  };

  return (
    <div className="space-y-4">
      <div>
        <span className={labelClass}>Rechercher par</span>
        <div role="radiogroup" className="mt-1.5 grid max-w-lg grid-cols-3 gap-2">
          {SEARCH_MODES.map((m) => (
            <Choice
              key={m.value}
              label={m.label}
              selected={mode === m.value}
              onClick={() => {
                setMode(m.value);
                setResults(null);
                setError(null);
              }}
            />
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="block w-full sm:w-56">
          <span className={labelClass}>{idField.label}</span>
          <input
            key={idField.key}
            value={values[idField.key]}
            onChange={(e) => set(idField.key, e.target.value)}
            onKeyDown={searchOnEnter}
            inputMode={idField.numeric ? "numeric" : "text"}
            maxLength={idField.max}
            placeholder={idField.placeholder}
            autoComplete="off"
            className={inputClass}
          />
        </label>
        {mode !== "ins" && (
          <label className="block w-full sm:w-48">
            <span className={labelClass}>Date de naissance *</span>
            <input
              type="date"
              min="1800-01-01"
              max={TODAY_ISO}
              value={values.birth_date}
              onChange={(e) => set("birth_date", e.target.value)}
              onKeyDown={searchOnEnter}
              className={inputClass}
            />
          </label>
        )}
        <button
          type="button"
          onClick={search}
          disabled={searching}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-60"
        >
          {searching ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          Rechercher dans le SIIS
        </button>
      </div>
      {error && (
        <p className="flex items-center gap-1.5 text-sm text-red-600">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </p>
      )}
      {results && results.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {results.map((p) => (
            <li key={p.ins} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <PatientIdentity patient={p} />
              {p.deceased ? (
                <span className="rounded-full bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700">
                  Décédé selon le SIIS
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => onSelect(p)}
                  className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-semibold text-blue-700 transition hover:bg-blue-100"
                >
                  Sélectionner
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AddPatientPage() {
  const [form, setForm] = useState(EMPTY_FORM);
  const [patient, setPatient] = useState<SiisPatient | null>(null);
  // Change après un enregistrement pour remettre la recherche SIIS à zéro.
  const [lookupKey, setLookupKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<PatientReferral | null>(null);

  const selectPatient = (p: SiisPatient) => {
    setPatient(p);
    setFormError(null);
  };

  const setClinical = (key: keyof ReferralClinicalInfo, value: string) =>
    setForm((f) => ({ ...f, clinical: { ...f.clinical, [key]: value } }));

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSaved(null);
    if (!patient) return setFormError("Recherchez le patient dans le SIIS puis sélectionnez-le.");
    setSaving(true);
    try {
      const created = await createReferral({
        patient_id: patient.ins,
        priority: form.priority,
        clinical_info: form.clinical,
      });
      setSaved(created);
      setForm(EMPTY_FORM);
      setPatient(null);
      setLookupKey((k) => k + 1);
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
        title="Ajouter le patient"
        subtitle="Identifier le patient par son INS, puis renseigner ses antécédents et la priorité"
      />
      <div className="flex-1 p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <Section
            title="Patient"
            subtitle="Recherchez le patient dans le SIIS. Son INS devient l'ID patient, à saisir sur le rétinographe."
          >
            {patient && (
              <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50/60 p-4">
                <div className="flex min-w-0 gap-3">
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
                  <div className="min-w-0">
                    <PatientIdentity patient={patient} />
                    <div className="mt-2 text-sm text-emerald-800">
                      ID patient à saisir sur le rétinographe :{" "}
                      <span className="font-mono font-semibold">{patient.ins}</span>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setPatient(null)}
                  className="text-sm font-semibold text-slate-600 hover:text-slate-900"
                >
                  Changer de patient
                </button>
              </div>
            )}
            {/* Masquée plutôt que démontée : les résultats restent après « Changer de patient ». */}
            <div className={patient ? "hidden" : ""}>
              <InsLookup key={lookupKey} onSelect={selectPatient} />
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
              {saved.patient_name || "Patient"} enregistré avec l'INS {saved.patient_id}.
              {saved.exam_id
                ? " Son examen en cours a été mis à jour."
                : " Les renseignements seront joints à son examen dès l'acquisition."}
              <Link
                to="/patients"
                className="ml-auto inline-flex items-center gap-1 whitespace-nowrap font-semibold text-emerald-700 hover:text-emerald-800"
              >
                <ClipboardList className="h-4 w-4" /> Voir la worklist
              </Link>
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
      </div>
    </>
  );
}
