import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Activity, Search } from "lucide-react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Navbar } from "@/components/Navbar";
import { useAuth, type Role, type UsageEvent } from "@/lib/auth-context";
import { Pagination } from "@/components/Pagination";

export const Route = createFileRoute("/_app/logs")({
  component: () => (
    <ProtectedRoute roles={["Admin"]}>
      <LogsPage />
    </ProtectedRoute>
  ),
});

const ROLE_LABEL: Record<Role, string> = {
  Admin: "Admin",
  Chef: "Chef de Service",
  Medecin: "Ophtalmologue",
  Resident: "Résident",
};

function LogsPage() {
  const { users } = useAuth();
  const [query, setQuery] = useState("");
  const [userQuery, setUserQuery] = useState("");

  // Pagination states
  const [logsPage, setLogsPage] = useState(1);
  const [usersPage, setUsersPage] = useState(1);
  const [backendLogs, setBackendLogs] = useState<any[]>([]);
  const [logsTotalPages, setLogsTotalPages] = useState(0);

  // Reset page when filters change
  useEffect(() => {
    setLogsPage(1);
  }, [query]);

  useEffect(() => {
    setUsersPage(1);
  }, [userQuery]);

  // Fetch paginated logs
  useEffect(() => {
    const loadLogs = async () => {
      try {
        let url = `http://localhost:8000/api/logs/?page=${logsPage}&size=10`;
        if (query) url += `&search=${encodeURIComponent(query)}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.logs) {
          setBackendLogs(data.logs);
          setLogsTotalPages(data.total_pages);
        }
      } catch (err) {
        console.error("Erreur de chargement des logs", err);
      }
    };
    loadLogs();
  }, [logsPage, query]);

  const filteredUsers = useMemo(() => {
    return users.filter((u) => {
      if (u.role === "Admin") return false;
      const fullName = `${u.firstName} ${u.lastName}`.toLowerCase();
      return !userQuery || fullName.includes(userQuery.toLowerCase());
    });
  }, [users, userQuery]);

  const paginatedUsers = useMemo(() => {
    return filteredUsers.slice((usersPage - 1) * 10, usersPage * 10);
  }, [filteredUsers, usersPage]);

  return (
    <>
      <Navbar
        title="Logs"
        subtitle="Historique des connexions et utilisateurs enregistrés"
      />
      <div className="flex-1 p-6 space-y-6">


        {/* Historique des connexions */}
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="font-semibold text-slate-900">Connexions et déconnexions (tous les jours)</h2>
            <div className="relative w-full max-w-xs">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Rechercher utilisateur ou rôle…"
                className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-4">Date</th>
                  <th className="py-2 pr-4">Heure</th>
                  <th className="py-2 pr-4">Utilisateur</th>
                  <th className="py-2 pr-4">Rôle</th>
                  <th className="py-2 pr-4">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {backendLogs.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-slate-500">
                      Aucun événement.
                    </td>
                  </tr>
                ) : (
                  backendLogs.map((e) => {
                    const d = new Date(e.at);
                    return (
                      <tr key={e.id} className="hover:bg-slate-50">
                        <td className="py-3 pr-4 text-slate-700">
                          {isNaN(d.getTime()) ? "—" : d.toISOString().slice(0, 10)}
                        </td>
                        <td className="py-3 pr-4 text-slate-600">
                          {isNaN(d.getTime()) ? "—" : d.toISOString().slice(11, 16)}
                        </td>
                        <td className="py-3 pr-4 font-medium text-slate-900">
                          {e.userName}
                        </td>
                        <td className="py-3 pr-4 text-slate-600">{ROLE_LABEL[e.role] || e.role}</td>
                        <td className="py-3 pr-4">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                              e.action === "login"
                                ? "bg-green-50 text-green-700 ring-1 ring-green-200"
                                : "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {e.action === "login" ? "Connexion" : "Déconnexion"}
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
            currentPage={logsPage}
            totalPages={Math.max(1, logsTotalPages)}
            onPageChange={setLogsPage}
          />
        </section>

        {/* Utilisateurs enregistrés de tous */}
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="font-semibold text-slate-900">Utilisateurs enregistrés (Tous)</h2>
            <div className="relative w-full max-w-xs">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={userQuery}
                onChange={(e) => setUserQuery(e.target.value)}
                placeholder="Rechercher par nom..."
                className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
              />
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-4">Nom</th>
                  <th className="py-2 pr-4">Rôle</th>
                  <th className="py-2 pr-4">Email</th>
                  <th className="py-2 pr-4">Téléphone</th>
                  <th className="py-2 pr-4">Créé le</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {paginatedUsers.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-slate-500">
                      Aucun utilisateur enregistré.
                    </td>
                  </tr>
                ) : (
                  paginatedUsers.map((u) => {
                    return (
                      <tr key={u.id} className="hover:bg-slate-50">
                        <td className="py-3 pr-4 font-medium text-slate-900">
                          {u.firstName} {u.lastName}
                        </td>
                        <td className="py-3 pr-4 text-slate-600">{ROLE_LABEL[u.role]}</td>
                        <td className="py-3 pr-4 text-slate-600">{u.email}</td>
                        <td className="py-3 pr-4 text-slate-600">{u.phone ?? "—"}</td>
                        <td className="py-3 pr-4 text-slate-600">
                          {u.createdAt ? u.createdAt.slice(0, 10) : "—"}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            currentPage={usersPage}
            totalPages={Math.ceil(filteredUsers.length / 10)}
            onPageChange={setUsersPage}
          />
        </section>
      </div>
    </>
  );
}
