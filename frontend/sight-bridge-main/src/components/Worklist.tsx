import { useMemo, useState, useEffect, useCallback } from "react";
import { Filter, Search, MonitorPlay, RefreshCw, Clock, Loader2, CheckCircle2, Calendar } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { fetchExams, updateExam as apiUpdateExam, getExamStats, syncWithOrthanc } from "@/lib/exam-api";
import type { Exam, ExamStatus } from "@/lib/mock-worklist";
import { Pagination } from "@/components/Pagination";

const STATUS_STYLES: Record<ExamStatus, string> = {
  "En attente": "bg-orange-100 text-orange-700 ring-orange-200",
  "En cours": "bg-blue-100 text-blue-700 ring-blue-200",
  Interprété: "bg-green-100 text-green-700 ring-green-200",
};

const TODAY = "2026-06-12";

interface WorklistProps {
  todayOnly?: boolean;
  showStats?: boolean;
}

export function Worklist({ todayOnly = false, showStats = false }: WorklistProps) {
  const { user } = useAuth();
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
  const [showTodayOnly, setShowTodayOnly] = useState(todayOnly);

  const loadExams = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      console.log("[Worklist] Fetching exams...", { statusFilter, query, regionFilter, doctorFilter, showTodayOnly, page });
      const result = await fetchExams({
        status: statusFilter === "Tous" ? undefined : statusFilter,
        q: query || undefined,
        region: regionFilter || undefined,
        doctor: doctorFilter || undefined,
        today_only: showTodayOnly || undefined,
        page,
        page_size: 10,
      });
      console.log("[Worklist] Exams received:", result);
      setExams(result.exams);
      setTotal(result.total);
    } catch (err) {
      console.error("[Worklist] Failed to load exams:", err);
      setError("Impossible de charger les examens.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, query, regionFilter, doctorFilter, showTodayOnly, page]);

  useEffect(() => {
    loadExams();
  }, [loadExams]);

  const stats = useMemo(
    () => ({
      attente: exams.filter((e) => e.status === "En attente").length,
      cours: exams.filter((e) => e.status === "En cours").length,
      interprete: exams.filter((e) => e.status === "Interprété").length,
    }),
    [exams],
  );

  const showAssignedTo = user?.role === "Admin" || user?.role === "Chef";

  const handleSync = async () => {
    setSyncing(true);
    try {
      const result = await syncWithOrthanc();
      alert(`Synchronisation terminée : ${result.created} créé(s), ${result.skipped} ignoré(s)`);
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
      setExams((prev) =>
        prev.map((e) => (e.id === examId ? { ...e, status: newStatus } : e)),
      );
    } catch (err) {
      console.error("Failed to update status:", err);
    }
  };

  const scopedExams = useMemo(() => {
    console.log("[Worklist] scopedExams input:", exams.length, "user role:", user?.role);
    if (user?.role === "Medecin" || user?.role === "Resident") {
      const myName = `Dr. ${user?.firstName} ${user?.lastName}`;
      const filtered = exams.filter(
        (e) => e.assignedTo === myName || e.assignedTo === null,
      );
      console.log("[Worklist] scopedExams output:", filtered.length);
      return filtered;
    }
    console.log("[Worklist] scopedExams output (all):", exams.length);
    return exams;
  }, [exams, user]);

  const filtered = useMemo(
    () =>
      scopedExams.filter((e) => {
        const matchStatus = statusFilter === "Tous" || e.status === statusFilter;
        const q = query.toLowerCase();
        const matchQ =
          !q ||
          e.patientName.toLowerCase().includes(q) ||
          e.id.toLowerCase().includes(q);
        const matchRegion = !regionFilter || (e.region && e.region.toLowerCase().includes(regionFilter.toLowerCase()));
        const matchDoctor = !doctorFilter || (e.assignedTo && e.assignedTo.toLowerCase().includes(doctorFilter.toLowerCase()));
        return matchStatus && matchQ && matchRegion && matchDoctor;
      }),
    [scopedExams, statusFilter, query, regionFilter, doctorFilter],
  );

  const paginatedExams = useMemo(() => {
    return filtered.slice((page - 1) * 10, page * 10);
  }, [filtered, page]);

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {showStats && !loading && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatPill label="En attente" value={stats.attente} icon={Clock} color="orange" />
          <StatPill label="En cours" value={stats.cours} icon={Loader2} color="blue" />
          <StatPill label="Interprété" value={stats.interprete} icon={CheckCircle2} color="green" />
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-3 sm:items-center justify-between">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }}
            placeholder="Rechercher patient ou ID…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex-1 max-w-xs">
          <input
            value={regionFilter}
            onChange={(e) => { setRegionFilter(e.target.value); setPage(1); }}
            placeholder="Filtrer par région…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex-1 max-w-xs">
          <input
            value={doctorFilter}
            onChange={(e) => { setDoctorFilter(e.target.value); setPage(1); }}
            placeholder="Filtrer par médecin assigné…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-slate-400" />
          {(["Tous", "En attente", "En cours", "Interprété"] as const).map((s) => (
            <button
              key={s}
              onClick={() => { setStatusFilter(s); setPage(1); }}
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
        <button
          onClick={() => { setShowTodayOnly((v) => !v); setPage(1); }}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition ${
            showTodayOnly
              ? "bg-blue-600 text-white"
              : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
          }`}
        >
          <Calendar className="h-3.5 w-3.5" />
          Aujourd'hui
        </button>
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
                <th className="px-4 py-3 text-left font-semibold">ID</th>
                <th className="px-4 py-3 text-left font-semibold">Patient</th>
                <th className="px-4 py-3 text-left font-semibold">Type</th>
                <th className="px-4 py-3 text-left font-semibold">Date</th>
                <th className="px-4 py-3 text-left font-semibold">Priorité</th>
                <th className="px-4 py-3 text-left font-semibold">Région</th>
                <th className="px-4 py-3 text-left font-semibold">Statut</th>
                {showAssignedTo && <th className="px-4 py-3 text-left font-semibold">Assigné à</th>}
                <th className="px-4 py-3 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-10 text-center text-sm text-slate-500">
                    <Loader2 className="inline h-5 w-5 animate-spin mr-2" />
                    Chargement des examens…
                  </td>
                </tr>
              ) : (
                paginatedExams.map((exam) => (
                  <tr key={exam.id} className="hover:bg-slate-50/60">
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">
                      {exam.id}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{exam.patientName}</div>
                      <div className="text-xs text-slate-500">{exam.patientAge} ans</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{exam.type}</td>
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
                    <td className="px-4 py-3 text-slate-700">{exam.region || "—"}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${STATUS_STYLES[exam.status]}`}
                      >
                        {exam.status}
                      </span>
                    </td>
                    {showAssignedTo && (
                      <td className="px-4 py-3 text-slate-700">
                        <span className="text-sm">
                          {exam.assignedTo ?? (
                            <span className="text-slate-400 italic">Non assigné</span>
                          )}
                        </span>
                      </td>
                    )}
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {exam.studyInstanceUid && (
                          <a
                            href="/ohif/"
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
                ))
              )}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-10 text-center text-sm text-slate-500">
                    Aucun examen ne correspond aux filtres.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <Pagination
          currentPage={page}
          totalPages={Math.ceil(filtered.length / 10)}
          onPageChange={setPage}
        />
      </div>
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
    orange: { bg: "bg-orange-50", text: "text-orange-700", ring: "ring-orange-200", icon: "text-orange-500" },
    blue: { bg: "bg-blue-50", text: "text-blue-700", ring: "ring-blue-200", icon: "text-blue-500" },
    green: { bg: "bg-green-50", text: "text-green-700", ring: "ring-green-200", icon: "text-green-500" },
  } as const;
  const c = map[color];
  return (
    <div className={`flex items-center justify-between rounded-xl ${c.bg} ring-1 ${c.ring} px-4 py-3`}>
      <div>
        <div className={`text-xs font-medium uppercase tracking-wide ${c.text}`}>{label}</div>
        <div className={`mt-1 text-2xl font-bold ${c.text}`}>{value}</div>
      </div>
      <Icon className={`h-6 w-6 ${c.icon}`} />
    </div>
  );
}
