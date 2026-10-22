/** Médecin référant — worklist des patients adressés (page par défaut du rôle). */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, FileText, Loader2, Search } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { StatPill } from "@/components/Worklist";
import { listReferrals, type PatientReferral } from "@/lib/referral-api";

export const Route = createFileRoute("/_app/patients")({
  component: () => (
    <ProtectedRoute roles={["MedecinReferant"]}>
      <ReferralWorklistPage />
    </ProtectedRoute>
  ),
});

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

function ReferralWorklistPage() {
  const [referrals, setReferrals] = useState<PatientReferral[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReferrals(await listReferrals());
      setListError(null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Compteurs calculés sur tous les patients adressés, indépendamment de la recherche.
  // "En cours" : examen acquis mais pas encore interprété ; "Terminés" : examen interprété.
  const stats = useMemo(
    () => ({
      enCours: referrals.filter((r) => r.exam_status && r.exam_status !== "Interprété").length,
      termines: referrals.filter((r) => r.exam_status === "Interprété").length,
    }),
    [referrals],
  );

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? referrals.filter((r) => r.patient_id.toLowerCase().includes(q)) : referrals;
  }, [referrals, search]);

  return (
    <>
      <Navbar title="Worklist" subtitle="Suivi des examens de mes patients adressés" />
      <div className="flex-1 space-y-4 p-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <StatPill
            label="Examens en cours"
            value={loading ? 0 : stats.enCours}
            icon={Loader2}
            color="blue"
          />
          <StatPill
            label="Examens terminés"
            value={loading ? 0 : stats.termines}
            icon={CheckCircle2}
            color="green"
          />
        </div>

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
                ) : visible.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                      {search.trim()
                        ? "Aucun patient ne correspond à la recherche."
                        : "Aucun patient adressé."}
                    </td>
                  </tr>
                ) : (
                  visible.map((r) => (
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
