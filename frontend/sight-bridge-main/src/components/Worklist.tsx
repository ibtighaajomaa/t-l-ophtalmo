import { useMemo, useState, useEffect, useCallback } from "react";
import ReactDOM from "react-dom";
import {
  Filter,
  Search,
  MonitorPlay,
  FileText,
  RefreshCw,
  Clock,
  Loader2,
  CheckCircle2,
  Calendar,
  ClipboardList,
  X,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import {
  fetchExams,
  updateExam as apiUpdateExam,
  getExamStats,
  syncWithOrthanc,
} from "@/lib/exam-api";
import type { Exam, ExamStatus } from "@/lib/mock-worklist";
import { Pagination } from "@/components/Pagination";

const STATUS_STYLES: Record<ExamStatus, string> = {
  "En attente": "bg-orange-100 text-orange-700 ring-orange-200",
  "En cours": "bg-blue-100 text-blue-700 ring-blue-200",
  Interprété: "bg-green-100 text-green-700 ring-green-200",
};

function QualityBadge({ exam, onClick }: { exam: Exam; onClick: () => void }) {
  const hasDetailedResults = (exam.imageQualityResults?.length ?? 0) > 0;
  const summaryCategory = exam.qualityCategory;
  const summaryScore = exam.qualityScore;
  const hasSummary = Boolean(summaryCategory) && summaryScore != null;

  if (exam.qualityStatus === "pending" || exam.qualityStatus === "in_progress") {
    return (
      <button
        type="button"
        onClick={onClick}
        className="cursor-pointer text-xs text-slate-400 hover:ring-2"
      >
        Analyse IA…
      </button>
    );
  }
  if (exam.qualityStatus === "failed") {
    return (
      <button
        type="button"
        onClick={onClick}
        className="cursor-pointer text-xs text-red-600 hover:ring-2"
      >
        Échec qualité
      </button>
    );
  }
  if (!hasSummary && !hasDetailedResults) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="cursor-pointer text-xs text-slate-400 hover:ring-2"
      >
        —
      </button>
    );
  }
  const styles = {
    good: "bg-emerald-100 text-emerald-700 ring-emerald-200",
    acceptable: "bg-amber-100 text-amber-700 ring-amber-200",
    bad: "bg-red-100 text-red-700 ring-red-200",
  };
  const labels = {
    good: "Bonne",
    acceptable: "Acceptable",
    bad: "Mauvaise",
  };
  if (!summaryCategory || summaryScore == null) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="cursor-pointer text-xs text-slate-500 hover:ring-2"
      >
        Détails
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex cursor-pointer rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 transition hover:ring-2 ${styles[summaryCategory]}`}
    >
      {labels[summaryCategory]} · {summaryScore.toFixed(1)}
    </button>
  );
}

function QualityModal({ exam, onClose }: { exam: Exam; onClose: () => void }) {
  const results = (exam.imageQualityResults ?? []).filter(Boolean);
  const summaryScore = typeof exam.qualityScore === "number" ? exam.qualityScore : undefined;
  const summaryCategory = exam.qualityCategory as "good" | "acceptable" | "bad" | undefined;

  const styles = {
    good: "bg-emerald-100 text-emerald-700 ring-emerald-200",
    acceptable: "bg-amber-100 text-amber-700 ring-amber-200",
    bad: "bg-red-100 text-red-700 ring-red-200",
  };
  const labels = {
    good: "Bonne",
    acceptable: "Acceptable",
    bad: "Mauvaise",
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="quality-modal-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
          <div>
            <h2 id="quality-modal-title" className="text-lg font-semibold text-slate-900">
              Qualité des images — {exam.id}
            </h2>
            <p className="mt-1 text-sm text-slate-500">{exam.patientName}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto px-6 py-5">
          {summaryScore != null && summaryCategory && (
            <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="text-sm font-semibold text-slate-900">Résumé de qualité</div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold tabular-nums text-slate-700">
                  {summaryScore.toFixed(1)}/100
                </span>
                <span
                  className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${styles[summaryCategory]}`}
                >
                  {labels[summaryCategory]}
                </span>
              </div>
            </div>
          )}

          {results.length ? (
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
              {results.map((result, index) => {
                const seriesUid = result.seriesInstanceUid || result.studyInstanceUid || "—";
                return (
                  <li
                    key={result.orthancInstanceId || result.sopInstanceUid || `${index}`}
                    className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3"
                  >
                    <span className="min-w-24 text-sm font-medium text-slate-900">
                      Instance {index + 1}
                    </span>
                    <span
                      className="min-w-36 flex-1 font-mono text-xs text-slate-500"
                      title={seriesUid}
                    >
                      {seriesUid ? `…${seriesUid.slice(-12)}` : "—"}
                    </span>
                    <span className="text-sm font-semibold tabular-nums text-slate-700">
                      {typeof result.score === "number" ? `${result.score.toFixed(1)}/100` : "—"}
                    </span>
                    <span
                      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${styles[result.category]}`}
                    >
                      {result.category === "bad" || result.score < 40
                        ? "À refaire"
                        : labels[result.category]}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-slate-500">
              {summaryScore != null && summaryCategory
                ? "Aucun détail d’instance n’est disponible pour cette analyse."
                : "Aucun résultat de qualité disponible."}
            </p>
          )}
        </div>

        <div className="flex justify-end border-t border-slate-200 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700"
          >
            Fermer
          </button>
        </div>
      </div>
    </div>
  );
}

function clinicalValue(info: Record<string, unknown> | null | undefined, keys: string[], fallback = "") {
  if (!info) return fallback;
  for (const key of keys) {
    const value = info[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return String(value);
    }
  }
  return fallback;
}

function clinicalBoolean(info: Record<string, unknown> | null | undefined, keys: string[]) {
  const value = clinicalValue(info, keys, "");
  const normalized = value.toLowerCase();
  if (["true", "1", "oui", "yes"].includes(normalized)) return "OUI";
  if (["false", "0", "non", "no"].includes(normalized)) return "NON";
  return "";
}

function ClinicalHistoryModal({ exam, onClose }: { exam: Exam; onClose: () => void }) {
  const info = exam.clinicalInfo;
  const diabetesType = clinicalValue(info, ["diabetes_type", "type_diabete", "typeDiabete"]);
  const hta = clinicalBoolean(info, ["hta", "hypertension", "hypertension_arterielle"]);
  const otherPathology = clinicalValue(info, ["other_pathology", "autre_pathologie", "autrePathologie"]);
  const notes = clinicalValue(info, ["notes", "motif", "motif_notes", "motifNotes", "clinical_notes"]);
  const inputClass =
    "min-h-11 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm";
  const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";

  function Field({ label, value, className = "" }: { label: string; value: string; className?: string }) {
    return (
      <label className={`space-y-1.5 ${className}`}>
        <span className={labelClass}>{label}</span>
        <span className={`${inputClass} flex items-center`}>{value}</span>
      </label>
    );
  }

  function Choice({
    label,
    selected,
    tone = "blue",
  }: {
    label: string;
    selected: boolean;
    tone?: "blue" | "emerald";
  }) {
    const activeClass =
      tone === "emerald"
        ? "border-emerald-500 bg-emerald-50 text-emerald-700"
        : "border-blue-500 bg-blue-50 text-blue-700";

    return (
      <span
        className={`flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${
          selected ? activeClass : "border-slate-200 bg-white text-slate-600"
        }`}
      >
        <span
          className={`h-3.5 w-3.5 rounded-full border ${
            selected ? "border-current bg-current shadow-[inset_0_0_0_3px_white]" : "border-slate-300 bg-white"
          }`}
        />
        {label}
      </span>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="patient-history-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="max-h-[92vh] w-full max-w-4xl overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 bg-white px-6 py-5">
          <div className="flex gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
              <ClipboardList className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">Dossier clinique</p>
              <h2 id="patient-history-title" className="mt-1 text-xl font-semibold text-slate-950">
                Renseignements cliniques et antécédents
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                {exam.patientName}
                {exam.patientId ? ` · ${exam.patientId}` : ""}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[calc(92vh-88px)] overflow-y-auto px-6 py-5">
          <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-950">Diabète</h3>
                  <p className="mt-0.5 text-sm text-slate-500">Type, durée et derniers bilans biologiques.</p>
                </div>
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <span className={labelClass}>Type de diabète</span>
                  <div className="grid gap-2 sm:grid-cols-3">
              {["TYPE 1", "TYPE 2", "Gestationnel"].map((type) => (
                      <Choice
                        key={type}
                        label={type}
                        selected={diabetesType.toLowerCase().includes(type.toLowerCase().replace("type ", ""))}
                      />
              ))}
                  </div>
                </div>

                <Field label="Durée du diabète" value={clinicalValue(info, ["diabetes_duration", "duree_diabete", "dureeDiabete"])} />

                <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
                  <Field label="Dernière glycémie" value={clinicalValue(info, ["last_glycemia", "derniere_glycemie", "glycemie"])} />
                  <Field label="Date" value={clinicalValue(info, ["last_glycemia_date", "date_glycemie"])} />
                </div>

                <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
                  <Field label="Dernière HbA1c" value={clinicalValue(info, ["last_hba1c", "derniere_hba1c", "hba1c"])} />
                  <Field label="Date" value={clinicalValue(info, ["last_hba1c_date", "date_hba1c"])} />
                </div>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="font-semibold text-slate-950">Traitement et facteurs de risque</h3>
              <p className="mt-0.5 text-sm text-slate-500">Informations utiles avant lecture de l’examen.</p>

              <div className="mt-4 space-y-4">
                <Field label="Type de traitement" value={clinicalValue(info, ["treatment_type", "type_traitement", "traitement"])} />

                <div className="space-y-1.5">
                  <span className={labelClass}>Hypertension artérielle (HTA)</span>
                  <div className="grid grid-cols-2 gap-2">
              {["OUI", "NON"].map((choice) => (
                      <Choice key={choice} label={choice} selected={hta === choice} tone="emerald" />
              ))}
                  </div>
                </div>

                <label className="space-y-1.5">
                  <span className={labelClass}>Autre pathologie</span>
                  <span className={`${inputClass} block min-h-28 whitespace-pre-line`}>{otherPathology}</span>
                </label>
              </div>
            </section>
          </div>

          <section className="mt-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2">
              <Calendar className="h-4 w-4 text-blue-600" />
              <h3 className="font-semibold text-slate-950">Motif et notes</h3>
            </div>
            <div className={`${inputClass} block min-h-32 whitespace-pre-line leading-relaxed`}>{notes}</div>
          </section>

          <div className="mt-5 flex justify-end border-t border-slate-200 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700"
            >
              Fermer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const TODAY = "2026-06-12";

interface WorklistProps {
  todayOnly?: boolean;
  showStats?: boolean;
}

export function Worklist({ todayOnly = false, showStats = false }: WorklistProps) {
  const { user } = useAuth();
  const isDoctorView = user?.role === "Medecin" || user?.role === "Resident";
  const [exams, setExams] = useState<Exam[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<ExamStatus | "Tous">("Tous");
  const [query, setQuery] = useState("");
  const [regionFilter, setRegionFilter] = useState("");
  const [doctorFilter, setDoctorFilter] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState<string>("");
  const [historyExam, setHistoryExam] = useState<Exam | null>(null);
  const [qualityModalExam, setQualityModalExam] = useState<Exam | null>(null);
  const [reportUnavailableExam, setReportUnavailableExam] = useState<Exam | null>(null);

  const [stats, setStats] = useState({ attente: 0, cours: 0, interprete: 0 });

  const loadExams = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      console.log("[Worklist] Fetching exams...", {
        statusFilter,
        query,
        regionFilter,
        doctorFilter,
        filterDate,
        page,
      });
      const result = await fetchExams({
        status: statusFilter === "Tous" ? undefined : statusFilter,
        q: query || undefined,
        region: regionFilter || undefined,
        doctor: doctorFilter || undefined,
        date: filterDate || undefined,
        page,
        page_size: 10,
      });
      console.log("[Worklist] Exams received:", result);
      setExams(result.exams);
      setTotal(result.total);

      const statsData = await getExamStats({
        q: query || undefined,
        region: regionFilter || undefined,
        doctor: doctorFilter || undefined,
        date: filterDate || undefined,
      });
      setStats({
        attente: statsData["En attente"],
        cours: statsData["En cours"],
        interprete: statsData["Interprété"],
      });
    } catch (err) {
      console.error("[Worklist] Failed to load exams:", err);
      setError("Impossible de charger les examens.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, query, regionFilter, doctorFilter, filterDate, page]);

  useEffect(() => {
    loadExams();
  }, [loadExams]);

  useEffect(() => {
    const handleExamStatusUpdate = (event: StorageEvent) => {
      if (event.key === "teleoph.exam-status-updated") {
        loadExams();
      }
    };

    window.addEventListener("storage", handleExamStatusUpdate);
    return () => window.removeEventListener("storage", handleExamStatusUpdate);
  }, [loadExams]);

  // On affiche la colonne "Assigné à" uniquement pour les admins (les autres médecins ne voient que leurs propres examens)
  const showAssignedTo = user?.role === "Admin";

  const handleSync = async () => {
    setSyncing(true);
    try {
      const result = await syncWithOrthanc();
      alert(
        `Synchronisation terminée : ${result.created} créé(s), ${result.updated} mis à jour, ${result.errors} erreur(s)`,
      );
      loadExams();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erreur de synchronisation";
      alert(msg);
    } finally {
      setSyncing(false);
    }
  };

  const handleStatusChange = async (examId: string, newStatus: ExamStatus) => {
    try {
      await apiUpdateExam(examId, { status: newStatus });
      setExams((prev) => prev.map((e) => (e.id === examId ? { ...e, status: newStatus } : e)));
    } catch (err) {
      console.error("Failed to update status:", err);
    }
  };

  // Le backend filtre déjà par utilisateur authentifié (token Keycloak).
  // Pas besoin de filtrer côté client.
  const scopedExams = exams;

  const filtered = useMemo(
    () =>
      scopedExams.filter((e) => {
        const matchStatus = statusFilter === "Tous" || e.status === statusFilter;
        const q = query.toLowerCase();
        const matchQ =
          !q ||
          e.patientName.toLowerCase().includes(q) ||
          e.id.toLowerCase().includes(q) ||
          (e.patientId?.toLowerCase().includes(q) ?? false);
        const matchRegion =
          !regionFilter ||
          (e.region && e.region.toLowerCase().includes(regionFilter.toLowerCase()));
        const matchDoctor =
          !doctorFilter ||
          (e.assignedTo && e.assignedTo.toLowerCase().includes(doctorFilter.toLowerCase()));
        return matchStatus && matchQ && matchRegion && matchDoctor;
      }),
    [scopedExams, statusFilter, query, regionFilter, doctorFilter],
  );

  const paginatedExams = useMemo(() => {
    // Les données sont déjà paginées par le backend (10 par page).
    // Inutile de faire un slice() qui casserait l'affichage à partir de la page 2.
    return filtered;
  }, [filtered]);

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {showStats && !loading && (
        <div
          className={`grid grid-cols-1 gap-3 ${isDoctorView ? "sm:grid-cols-2" : "sm:grid-cols-3"}`}
        >
          {!isDoctorView && (
            <StatPill label="En attente" value={stats.attente} icon={Clock} color="orange" />
          )}
          <StatPill label="En cours" value={stats.cours} icon={Loader2} color="blue" />
          <StatPill label="Interprété" value={stats.interprete} icon={CheckCircle2} color="green" />
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-3 sm:items-center justify-between">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Rechercher patient ou ID…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex-1 max-w-xs">
          <input
            value={regionFilter}
            onChange={(e) => {
              setRegionFilter(e.target.value);
              setPage(1);
            }}
            placeholder="Filtrer par établissement…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex-1 max-w-xs">
          <input
            value={doctorFilter}
            onChange={(e) => {
              setDoctorFilter(e.target.value);
              setPage(1);
            }}
            placeholder="Filtrer par médecin assigné…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-slate-400" />
          {(["Tous", "En attente", "En cours", "Interprété"] as const).map((s) => (
            <button
              key={s}
              onClick={() => {
                setStatusFilter(s);
                setPage(1);
              }}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${
                statusFilter === s
                  ? "bg-blue-600 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Calendar className="h-4 w-4 text-slate-400" />
          <input
            type="date"
            value={filterDate}
            onChange={(e) => {
              setFilterDate(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border border-slate-200 bg-white py-1.5 px-3 text-sm text-slate-600 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100"
          />
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50 transition"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
          {syncing ? "Synchro…" : "Sync Orthanc"}
        </button>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">ID patient</th>
                <th className="px-4 py-3 text-left font-semibold">Patient</th>
                <th className="px-4 py-3 text-left font-semibold">Antécédents</th>
                <th className="px-4 py-3 text-left font-semibold">Date</th>
                <th className="px-4 py-3 text-left font-semibold">Priorité</th>
                <th className="px-4 py-3 text-left font-semibold">Nom d'établissement</th>
                <th className="px-4 py-3 text-left font-semibold">Qualité IA</th>
                <th className="px-4 py-3 text-left font-semibold">Statut</th>
                {showAssignedTo && <th className="px-4 py-3 text-left font-semibold">Assigné à</th>}
                <th className="px-4 py-3 text-center font-semibold">Compte rendu</th>
                <th className="px-4 py-3 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td
                    colSpan={showAssignedTo ? 11 : 10}
                    className="px-4 py-10 text-center text-sm text-slate-500"
                  >
                    <Loader2 className="inline h-5 w-5 animate-spin mr-2" />
                    Chargement des examens…
                  </td>
                </tr>
              ) : (
                paginatedExams.map((exam) => {
                  const isOldDoctor =
                    user && exam.reassignedFromName === `Dr. ${user.firstName} ${user.lastName}`;
                  const dicomStudyInstanceUid =
                    exam.imageQualityResults?.find((result) => result.studyInstanceUid)
                      ?.studyInstanceUid || exam.studyInstanceUid;
                  const rowClass = exam.isReassigned24h
                    ? "bg-red-50/50 hover:bg-red-100/50"
                    : "hover:bg-slate-50/60";

                  return (
                    <tr key={exam.id} className={rowClass}>
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">
                        {exam.patientId || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-900">{exam.patientName}</div>
                        <div className="text-xs text-slate-500">
                          {exam.patientBirthDate ? `${exam.patientAge} ans` : "Âge non renseigné"}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => setHistoryExam(exam)}
                          title="Afficher les antécédents"
                          aria-label={`Afficher les antécédents de ${exam.patientName}`}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700 ring-1 ring-blue-200 transition hover:bg-blue-100"
                        >
                          <ClipboardList className="h-4 w-4" />
                        </button>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{exam.date}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                            exam.priority === "Urgent"
                              ? "bg-red-50 text-red-700 ring-1 ring-red-200"
                              : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {exam.priority === "Urgent" && (
                            <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                          )}
                          {exam.priority}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div
                          className="max-w-56 truncate font-medium text-slate-800"
                          title={exam.institutionName || exam.region || "Établissement inconnu"}
                        >
                          {exam.institutionName || exam.region || "Établissement inconnu"}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <QualityBadge exam={exam} onClick={() => setQualityModalExam(exam)} />
                      </td>
                      <td className="px-4 py-3">
                        {isOldDoctor && exam.isReassigned24h ? (
                          <span className="inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 bg-red-100 text-red-700 ring-red-200">
                            Retiré et réassigné
                          </span>
                        ) : (
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${STATUS_STYLES[exam.status]}`}
                          >
                            {exam.status}
                          </span>
                        )}
                        {exam.isReassigned24h && !isOldDoctor && (
                          <div className="mt-1 text-[10px] text-red-600 font-medium">
                            ⚠️ Réassigné (retard 24h)
                          </div>
                        )}
                      </td>
                      {showAssignedTo && (
                        <td className="px-4 py-3 text-slate-700">
                          <span className="text-sm">
                            {exam.assignedTo ?? (
                              <span className="text-slate-400 italic">Non assigné</span>
                            )}
                          </span>
                          {exam.isReassigned24h && exam.reassignedFromName && (
                            <div className="text-[10px] text-red-500 mt-0.5">
                              Retiré à : {exam.reassignedFromName}
                            </div>
                          )}
                        </td>
                      )}
                      <td className="px-4 py-3 text-center">
                        {exam.status === "Interprété" ? (
                          <a
                            href={`/compte-rendu/${encodeURIComponent(exam.id)}`}
                            title="Afficher le compte rendu"
                            aria-label={`Afficher le compte rendu de ${exam.patientName}`}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 transition hover:bg-emerald-100"
                          >
                            <FileText className="h-4 w-4" />
                          </a>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setReportUnavailableExam(exam)}
                            title="Compte rendu non disponible"
                            aria-label={`Compte rendu non disponible pour ${exam.patientName}`}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-red-50 text-red-700 ring-1 ring-red-200 transition hover:bg-red-100"
                          >
                            <FileText className="h-4 w-4" />
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {dicomStudyInstanceUid && (
                            <a
                              href={`/ohif/viewer?StudyInstanceUIDs=${encodeURIComponent(
                                dicomStudyInstanceUid,
                              )}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 transition"
                            >
                              <MonitorPlay className="h-3.5 w-3.5" /> Visualiser
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td
                    colSpan={showAssignedTo ? 11 : 10}
                    className="px-4 py-10 text-center text-sm text-slate-500"
                  >
                    Aucun examen ne correspond aux filtres.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <Pagination currentPage={page} totalPages={Math.ceil(total / 10)} onPageChange={setPage} />
      </div>
      {historyExam &&
        ReactDOM.createPortal(
          <ClinicalHistoryModal exam={historyExam} onClose={() => setHistoryExam(null)} />,
          document.body,
        )}
      {qualityModalExam &&
        ReactDOM.createPortal(
          <QualityModal exam={qualityModalExam} onClose={() => setQualityModalExam(null)} />,
          document.body,
        )}
      {reportUnavailableExam &&
        ReactDOM.createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="report-unavailable-title"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setReportUnavailableExam(null);
            }}
          >
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2
                    id="report-unavailable-title"
                    className="text-lg font-semibold text-slate-900"
                  >
                    Compte rendu non disponible
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">
                    {reportUnavailableExam.patientName} · statut {reportUnavailableExam.status}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setReportUnavailableExam(null)}
                  aria-label="Fermer"
                  className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <p className="mt-5 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-amber-200">
                Le compte rendu n'est pas disponible.
              </p>
              <div className="mt-5 flex justify-end">
                <button
                  type="button"
                  onClick={() => setReportUnavailableExam(null)}
                  className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700"
                >
                  Fermer
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

function StatPill({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: number;
  icon: typeof Clock;
  color: "orange" | "blue" | "green";
}) {
  const map = {
    orange: {
      bg: "bg-orange-50",
      text: "text-orange-700",
      ring: "ring-orange-200",
      icon: "text-orange-500",
    },
    blue: { bg: "bg-blue-50", text: "text-blue-700", ring: "ring-blue-200", icon: "text-blue-500" },
    green: {
      bg: "bg-green-50",
      text: "text-green-700",
      ring: "ring-green-200",
      icon: "text-green-500",
    },
  } as const;
  const c = map[color];
  return (
    <div
      className={`flex items-center justify-between rounded-xl ${c.bg} ring-1 ${c.ring} px-4 py-3`}
    >
      <div>
        <div className={`text-xs font-medium uppercase tracking-wide ${c.text}`}>{label}</div>
        <div className={`mt-1 text-2xl font-bold ${c.text}`}>{value}</div>
      </div>
      <Icon className={`h-6 w-6 ${c.icon}`} />
    </div>
  );
}
