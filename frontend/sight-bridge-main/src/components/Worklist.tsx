/**
 * Worklist — table d'examens partagée, actions adaptées au rôle.
 * - Admin : lecture seule
 * - Chef  : peut assigner
 * - Medecin/Resident : peut ouvrir & changer le statut
 */
import { useMemo, useState, useEffect } from "react";
import { Link } from "@tanstack/react-router";
import { Filter, Search, UserCheck, Eye, Clock, Loader2, CheckCircle2, MonitorPlay } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { MOCK_EXAMS, type Exam, type ExamStatus } from "@/lib/mock-worklist";
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
  const { user, users } = useAuth();
  const [exams, setExams] = useState<Exam[]>(MOCK_EXAMS);
  const [statusFilter, setStatusFilter] = useState<ExamStatus | "Tous">("Tous");
  const [query, setQuery] = useState("");
  const [regionFilter, setRegionFilter] = useState("");
  const [doctorFilter, setDoctorFilter] = useState("");
  const [page, setPage] = useState(1);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilter, query, regionFilter, doctorFilter]);

  const baseExams = useMemo(
    () => (todayOnly ? exams.filter((e) => e.date === TODAY) : exams),
    [exams, todayOnly],
  );

  const showAssignedTo = user?.role === "Admin" || user?.role === "Chef";
  const doctors = useMemo(() => users.filter((u) => u.role === "Medecin" || u.role === "Resident"), [users]);

  useEffect(() => {
    // Assigner automatiquement les examens non assignés à un médecin aléatoire
    if (doctors.length > 0) {
      setExams((prev) => {
        let changed = false;
        const next = prev.map((e) => {
          if (!e.assignedTo) {
            changed = true;
            const randomDoc = doctors[Math.floor(Math.random() * doctors.length)];
            return {
              ...e,
              assignedTo: `Dr. ${randomDoc.firstName} ${randomDoc.lastName}`,
              status: "En cours" as ExamStatus,
            };
          }
          return e;
        });
        return changed ? next : prev;
      });
    }
  }, [doctors]);

  const stats = useMemo(
    () => ({
      attente: baseExams.filter((e) => e.status === "En attente").length,
      cours: baseExams.filter((e) => e.status === "En cours").length,
      interprete: baseExams.filter((e) => e.status === "Interprété").length,
    }),
    [baseExams],
  );

  const filtered = useMemo(
    () =>
      baseExams.filter((e) => {
        const matchStatus = statusFilter === "Tous" || e.status === statusFilter;
        const q = query.toLowerCase();
        const matchQ =
          !q ||
          e.patientName.toLowerCase().includes(q) ||
          e.id.toLowerCase().includes(q);
        
        const matchRegion = !regionFilter || (e.region && e.region.toLowerCase().includes(regionFilter.toLowerCase()));
        const matchDoctor = !doctorFilter || (e.assignedTo && e.assignedTo.toLowerCase().includes(doctorFilter.toLowerCase()));
        
        const isRestrictedScope =
          ["Chef", "Medecin", "Resident"].includes(user?.role ?? "")
            ? e.doctorId === user?.id ||
              e.createdByUserId === user?.id ||
              e.assignedTo === `Dr. ${user?.firstName} ${user?.lastName}`
            : true;

        return matchStatus && matchQ && matchRegion && matchDoctor && isRestrictedScope;
      }),
    [baseExams, statusFilter, query, regionFilter, doctorFilter, user],
  );

  const paginatedExams = useMemo(() => {
    return filtered.slice((page - 1) * 10, page * 10);
  }, [filtered, page]);

  const updateExam = (id: string, patch: Partial<Exam>) =>
    setExams((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)));

  return (
    <div className="space-y-4">
      {showStats && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatPill label="En attente" value={stats.attente} icon={Clock} color="orange" />
          <StatPill label="En cours" value={stats.cours} icon={Loader2} color="blue" />
          <StatPill label="Interprété" value={stats.interprete} icon={CheckCircle2} color="green" />
        </div>
      )}

      {/* Filtres */}
      <div className="flex flex-col sm:flex-row gap-3 sm:items-center justify-between">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher patient ou ID…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex-1 max-w-xs">
          <input
            value={regionFilter}
            onChange={(e) => setRegionFilter(e.target.value)}
            placeholder="Filtrer par région…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex-1 max-w-xs">
          <input
            value={doctorFilter}
            onChange={(e) => setDoctorFilter(e.target.value)}
            placeholder="Filtrer par médecin assigné…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-slate-400" />
          {(["Tous", "En attente", "En cours", "Interprété"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
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
      </div>

      {/* Table */}
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
              {paginatedExams.map((exam) => (
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
                          href={`http://localhost:8099/viewer?StudyInstanceUIDs=${exam.studyInstanceUid}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 transition"
                        >
                          <MonitorPlay className="h-3.5 w-3.5" /> Visualiser
                        </a>
                      )}
                      {user?.role === "Admin" ? (
                        <Link
                          to="/worklist/$id"
                          params={{ id: exam.id }}
                          className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-blue-600"
                        >
                          <Eye className="h-3.5 w-3.5" /> Voir
                        </Link>
                      ) : user?.role === "Chef" ? (
                        <Link
                          to="/worklist/$id"
                          params={{ id: exam.id }}
                          className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700"
                        >
                          <UserCheck className="h-3.5 w-3.5" /> Détails
                        </Link>
                      ) : (
                        <Link
                          to="/worklist/$id"
                          params={{ id: exam.id }}
                          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                        >
                          Interpréter
                        </Link>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
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
