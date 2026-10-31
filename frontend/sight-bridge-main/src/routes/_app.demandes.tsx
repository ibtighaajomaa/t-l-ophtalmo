/** Technicien — liste d'attente des demandes d'acquisition adressées par les médecins référants. */
import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Clock, Loader2, Search } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { StatPill } from "@/components/Worklist";
import { listReferrals, type PatientReferral } from "@/lib/referral-api";

export const Route = createFileRoute("/_app/demandes")({
  component: () => (
    <ProtectedRoute roles={["Technicien", "Chef"]}>
      <DemandesPage />
    </ProtectedRoute>
  ),
});

type Filtre = "attente" | "toutes";

const isPending = (r: PatientReferral) => r.exam_id === null;

/** Ordre d'une liste d'attente : à acquérir d'abord, urgences en tête, puis les plus anciennes. */
function compareDemandes(a: PatientReferral, b: PatientReferral) {
  if (isPending(a) !== isPending(b)) return isPending(a) ? -1 : 1;
  if (a.priority !== b.priority) return a.priority === "Urgent" ? -1 : 1;
  return a.created_at.localeCompare(b.created_at);
}

function StatutBadge({ referral }: { referral: PatientReferral }) {
  if (isPending(referral)) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700">
        <Clock className="h-3 w-3" /> En attente d'acquisition
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
      <CheckCircle2 className="h-3 w-3" /> Examen acquis
      {referral.exam_date ? ` le ${new Date(referral.exam_date).toLocaleDateString("fr-FR")}` : ""}
    </span>
  );
}

function DemandesPage() {
  const [referrals, setReferrals] = useState<PatientReferral[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filtre, setFiltre] = useState<Filtre>("attente");

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

  const stats = useMemo(
    () => ({
      attente: referrals.filter(isPending).length,
      acquises: referrals.filter((r) => !isPending(r)).length,
    }),
    [referrals],
  );

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return referrals
      .filter((r) => filtre === "toutes" || isPending(r))
      .filter((r) => !q || r.patient_id.toLowerCase().includes(q))
      .sort(compareDemandes);
  }, [referrals, search, filtre]);

  return (
    <>
      <Navbar
        title="Demandes"
        subtitle="Patients adressés par les médecins référants, en attente d'acquisition"
      />
      <div className="flex-1 space-y-4 p-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <StatPill
            label="En attente d'acquisition"
            value={loading ? 0 : stats.attente}
            icon={Clock}
            color="orange"
          />
          <StatPill
            label="Examens acquis"
            value={loading ? 0 : stats.acquises}
            icon={CheckCircle2}
            color="green"
          />
        </div>

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
            <h3 className="font-semibold text-slate-950">Liste d'attente</h3>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={filtre}
                onChange={(e) => setFiltre(e.target.value as Filtre)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
              >
                <option value="attente">En attente d'acquisition</option>
                <option value="toutes">Toutes les demandes</option>
              </select>
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
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold">ID</th>
                  <th className="px-4 py-3 text-left font-semibold">ID patient</th>
                  <th className="px-4 py-3 text-left font-semibold">Âge</th>
                  <th className="px-4 py-3 text-left font-semibold">Priorité</th>
                  <th className="px-4 py-3 text-left font-semibold">Antécédents / motif</th>
                  <th className="px-4 py-3 text-left font-semibold">Médecin référant</th>
                  <th className="px-4 py-3 text-left font-semibold">Demandé le</th>
                  <th className="px-4 py-3 text-left font-semibold">Statut</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                      <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                    </td>
                  </tr>
                ) : listError ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-red-600">
                      {listError}
                    </td>
                  </tr>
                ) : visible.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                      {search.trim()
                        ? "Aucune demande ne correspond à la recherche."
                        : filtre === "attente"
                          ? "Aucune demande en attente d'acquisition."
                          : "Aucune demande."}
                    </td>
                  </tr>
                ) : (
                  visible.map((r) => (
                    <tr key={r.id} className="align-top">
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-500">
                        #{r.id}
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-900">{r.patient_id}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {r.patient_age != null ? `${r.patient_age} ans` : "—"}
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
                      <td className="px-4 py-3 text-slate-700">{r.created_by_name || "—"}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                        {new Date(r.created_at).toLocaleDateString("fr-FR")}
                      </td>
                      <td className="px-4 py-3">
                        <StatutBadge referral={r} />
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
