import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Activity, Search, UserCheck, UserX } from "lucide-react";
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
        let url = `/api/logs/?page=${logsPage}&size=10`;
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

  // Users backend state
  const [backendUsers, setBackendUsers] = useState<any[]>([]);
  const [usersTotalPages, setUsersTotalPages] = useState(0);
  const [reloadTrigger, setReloadTrigger] = useState(0);

  // Fetch paginated users
  useEffect(() => {
    const loadUsers = async () => {
      try {
        let url = `/api/users/paginated/?page=${usersPage}&size=10`;
        if (userQuery) url += `&search=${encodeURIComponent(userQuery)}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.users) {
          setBackendUsers(data.users);
          setUsersTotalPages(data.total_pages);
        }
      } catch (err) {
        console.error("Erreur de chargement des utilisateurs", err);
      }
    };
    loadUsers();
  }, [usersPage, userQuery, reloadTrigger]);

  const handleToggleAvailability = async (email: string) => {
    try {
      const res = await fetch("/api/users/toggle-status/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email })
      });
      const data = await res.json();
      if (res.ok) {
        setReloadTrigger(prev => prev + 1);
      } else {
        alert("Erreur : " + data.error);
      }
    } catch (err) {
      alert("Erreur réseau");
    }
  };

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
                        <td className="py-3 pr-4 text-slate-600">{ROLE_LABEL[e.role as Role] || e.role}</td>
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
                  <th className="py-2 pr-4">Disponibilité</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {backendUsers.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-slate-500">
                      Aucun utilisateur enregistré.
                    </td>
                  </tr>
                ) : (
                  backendUsers.map((u) => {
                    return (
                      <tr key={u.id} className="hover:bg-slate-50">
                        <td className="py-3 pr-4 font-medium text-slate-900">
                          {u.firstName} {u.lastName}
                        </td>
                        <td className="py-3 pr-4 text-slate-600">{ROLE_LABEL[u.role as Role]}</td>
                        <td className="py-3 pr-4 text-slate-600">{u.email}</td>
                        <td className="py-3 pr-4 text-slate-600">{u.phone ?? "—"}</td>
                        <td className="py-3 pr-4 text-slate-600">
                          {u.createdAt ? u.createdAt.slice(0, 10) : "—"}
                        </td>
                        <td className="py-3 pr-4">
                          {(u.role === "Medecin" || u.role === "Resident" || u.role === "Chef") ? (
                            <button
                              onClick={() => handleToggleAvailability(u.email)}
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium transition hover:opacity-80 cursor-pointer ${
                                u.is_disponible ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                              }`}
                              title={u.is_disponible ? "Rendre Indisponible" : "Rendre Disponible"}
                            >
                              {u.is_disponible ? <UserCheck size={12} /> : <UserX size={12} />}
                              {u.is_disponible ? " Disponible" : " Indisponible"}
                            </button>
                          ) : (
                            <span className="text-slate-400 text-xs">—</span>
                          )}
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
            totalPages={Math.max(1, usersTotalPages)}
            onPageChange={setUsersPage}
          />
        </section>
      </div>
    </>
  );
}
