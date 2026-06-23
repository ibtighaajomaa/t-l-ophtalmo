import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, useEffect } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Navbar } from "@/components/Navbar";
import { useAuth } from "@/lib/auth-context";
import { MOCK_PLANNING } from "@/lib/mock-planning";
import { fetchExams } from "@/lib/exam-api";
import type { Exam } from "@/lib/mock-worklist";
import { CalendarDays, Loader2 } from "lucide-react";
import { Pagination } from "@/components/Pagination";

export const Route = createFileRoute("/_app/calendrier")({
  component: () => (
    <ProtectedRoute roles={["Admin", "Chef", "Medecin", "Resident"]}>
      <CalendrierPage />
    </ProtectedRoute>
  ),
});

function CalendrierPage() {
  const { user } = useAuth();
  const [page, setPage] = useState(1);
  const [exams, setExams] = useState<Exam[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchExams({ page_size: 100 })
      .then((r) => setExams(r.exams))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const normalize = (name: string) => name.toLowerCase().replace(/^(dr\.|pr|dr)\s+/i, '').trim();

  const planning = useMemo(() => {
    if (["Chef", "Medecin", "Resident"].includes(user?.role ?? "")) {
      const userName = normalize(`${user!.firstName} ${user!.lastName}`);
      return MOCK_PLANNING.filter(s => normalize(s.doctorName) === userName);
    }
    return MOCK_PLANNING;
  }, [user]);

  // Reset page when user role planning changes
  useMemo(() => {
    setPage(1);
  }, [planning]);

  const paginatedPlanning = useMemo(() => {
    return planning.slice((page - 1) * 10, page * 10);
  }, [planning, page]);

  // Calculer le nombre d'examens assignés par médecin
  const examsCountByDoctor = useMemo(() => {
    const map = new Map<string, number>();
    exams.forEach((e) => {
      if (e.assignedTo) {
        const normName = normalize(e.assignedTo);
        map.set(normName, (map.get(normName) || 0) + 1);
      }
    });
    return map;
  }, [exams]);

  return (
    <>
      <Navbar
        title="Planning des téléconsultations"
        subtitle="Calendrier de pédopsychiatrie et affectations des médecins"
      />
      <div className="flex-1 p-6 space-y-6">
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-6 flex items-center gap-2 text-slate-900">
            <CalendarDays className="h-6 w-6 text-blue-600" />
            <h2 className="text-lg font-semibold">Planning des Téléconsultations de Pédopsychiatrie</h2>
          </div>
          
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr className="text-left text-xs font-bold uppercase tracking-wide text-slate-700">
                  <th className="py-3 px-4 border-r border-slate-200 w-16 text-center">N°</th>
                  <th className="py-3 px-4 border-r border-slate-200">Dates</th>
                  <th className="py-3 px-4 border-r border-slate-200">Nom Médecin</th>
                  <th className="py-3 px-4 border-r border-slate-200">Affectation Médecins</th>
                  <th className="py-3 px-4 text-center">Examens assignés</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {paginatedPlanning.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-slate-500">
                      Aucune téléconsultation planifiée.
                    </td>
                  </tr>
                ) : (
                  paginatedPlanning.map((session) => {
                    const count = examsCountByDoctor.get(normalize(session.doctorName)) || 0;
                    
                    let bgClass = "bg-white";
                    if (session.affiliation.includes("Razi")) bgClass = "bg-yellow-50/30";
                    else if (session.affiliation.includes("libre pratique")) bgClass = "bg-blue-50/30";
                    else if (session.affiliation.includes("Mongi Slim")) bgClass = "bg-purple-50/30";

                    return (
                      <tr key={session.id} className={`hover:bg-slate-50 transition-colors ${bgClass}`}>
                        <td className="py-3 px-4 border-r border-slate-200 font-medium text-slate-500 text-center">
                          {session.id}
                        </td>
                        <td className="py-3 px-4 border-r border-slate-200 font-medium text-slate-900">
                          {session.date}
                        </td>
                        <td className="py-3 px-4 border-r border-slate-200 font-medium text-slate-800">
                          {session.doctorName}
                        </td>
                        <td className="py-3 px-4 border-r border-slate-200 text-slate-600">
                          {session.affiliation}
                        </td>
                        <td className="py-3 px-4 text-center">
                          <span className={`inline-flex min-w-[2rem] justify-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                            count > 0 
                              ? "bg-blue-100 text-blue-800 ring-1 ring-blue-300" 
                              : "bg-slate-100 text-slate-500 ring-1 ring-slate-200"
                          }`}>
                            {count}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            currentPage={page}
            totalPages={Math.ceil(planning.length / 10)}
            onPageChange={setPage}
          />
        </div>
      </div>
    </>
  );
}
