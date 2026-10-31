import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import {
  Users,
  Trash2,
  Stethoscope,
  Briefcase,
  Activity,
  Edit,
  X,
  UserCheck,
  UserX,
  Wrench,
  HeartPulse,
} from "lucide-react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Navbar } from "@/components/Navbar";
import { useAuth, type Role, type AppUser } from "@/lib/auth-context";
import { ETABLISSEMENTS, ROLE_LABELS } from "@/lib/roles";
import { Pagination } from "@/components/Pagination";

export const Route = createFileRoute("/_app/admin")({
  component: () => (
    <ProtectedRoute roles={["Admin", "Chef"]}>
      <AdminDashboard />
    </ProtectedRoute>
  ),
});

const ROLE_FILTERS: { value: "all" | Role; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "Chef", label: "Coordinateurs d'établissement" },
  { value: "Medecin", label: "Ophtalmologues" },
  { value: "Technicien", label: "Techniciens" },
  { value: "MedecinReferant", label: "Médecins référants" },
];

const EMPTY_STATS = { total: 0, chefs: 0, medecins: 0, techniciens: 0, medecinReferants: 0 };

/** Paramètre de périmètre : le coordinateur d'établissement ne voit que son établissement. */
function scopeParam(user: AppUser | null): string {
  if (user?.role !== "Chef") return "";
  return `etablissement=${encodeURIComponent(user.etablissement || "")}`;
}

function AdminDashboard() {
  const { user, users, deleteUser, updateUser } = useAuth();
  const [filter, setFilter] = useState<"all" | Role>("all");
  const [nameFilter, setNameFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Backend state
  const [backendUsers, setBackendUsers] = useState<AppUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [reloadTrigger, setReloadTrigger] = useState(0);

  const [stats, setStats] = useState<typeof EMPTY_STATS>(EMPTY_STATS);
  // Un coordinateur d'établissement sans établissement rattaché n'a aucun périmètre : on n'interroge pas le serveur.
  const scopeMissing = user?.role === "Chef" && !user.etablissement;

  // States for Edit Modal
  const [editingUser, setEditingUser] = useState<AppUser | null>(null);
  const [editForm, setEditForm] = useState<{
    firstName: string;
    lastName: string;
    email: string;
    phone: string;
    role: Role;
    etablissement: string;
  }>({
    firstName: "",
    lastName: "",
    email: "",
    phone: "",
    role: "Medecin",
    etablissement: "",
  });
  const [editError, setEditError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Pagination states
  const [usersPage, setUsersPage] = useState(1);
  const [logsPage, setLogsPage] = useState(1);
  const [backendLogs, setBackendLogs] = useState<any[]>([]);
  const [logsTotalPages, setLogsTotalPages] = useState(0);

  // Reset pages when filters change
  useEffect(() => {
    setUsersPage(1);
  }, [filter, nameFilter]);

  // Fetch paginated logs
  useEffect(() => {
    if (user?.role !== "Admin") return;
    const loadLogs = async () => {
      try {
        const res = await fetch(`/api/logs/?page=${logsPage}&size=10&todayOnly=true`);
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
  }, [logsPage, user?.role]);

  // Fetch stats on mount
  useEffect(() => {
    if (scopeMissing) {
      setStats(EMPTY_STATS);
      return;
    }
    const scope = scopeParam(user);
    fetch(`/api/users/stats/${scope ? `?${scope}` : ""}`)
      .then((r) => r.json())
      .then((d) => setStats({ ...EMPTY_STATS, ...d }))
      .catch(console.error);
  }, [user, scopeMissing]);

  // Fetch paginated users
  useEffect(() => {
    const loadUsers = async () => {
      if (scopeMissing) {
        setBackendUsers([]);
        setTotalCount(0);
        setTotalPages(0);
        return;
      }
      setLoading(true);
      try {
        let url = `/api/users/paginated/?page=${usersPage}&size=10`;
        if (nameFilter) url += `&search=${nameFilter}`;
        if (filter !== "all") url += `&role=${filter}`;
        const scope = scopeParam(user);
        if (scope) url += `&${scope}`;

        const res = await fetch(url);
        const data = await res.json();
        if (data.users) {
          setBackendUsers(data.users);
          setTotalCount(data.total);
          setTotalPages(data.total_pages);
        }
      } catch (err) {
        console.error("Erreur de chargement", err);
      } finally {
        setLoading(false);
      }
    };
    loadUsers();
  }, [usersPage, nameFilter, filter, user, scopeMissing, reloadTrigger]);

  const visibleUsers = users.filter((u) => {
    if (user?.role === "Chef") {
      return u.etablissement === user.etablissement && u.role !== "Admin";
    }
    return u.role !== "Admin";
  });

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Supprimer l'utilisateur "${name}" ?`)) return;
    const res = await deleteUser(id);
    if (!res.ok) setError(res.error ?? "Erreur");
    else {
      setError(null);
      setReloadTrigger((prev) => prev + 1);
    }
  };

  const handleToggleAvailability = async (email: string) => {
    try {
      const res = await fetch("/api/users/toggle-status/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (res.ok) {
        setReloadTrigger((prev) => prev + 1);
      } else {
        alert("Erreur : " + data.error);
      }
    } catch (err) {
      alert("Erreur réseau");
    }
  };

  const handleEdit = (u: AppUser) => {
    setEditingUser(u);
    setEditForm({
      firstName: u.firstName,
      lastName: u.lastName,
      email: u.email,
      phone: u.phone || "",
      role: u.role,
      etablissement: u.etablissement || "",
    });
    setEditError(null);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingUser) return;

    if (!editForm.firstName.trim() || !editForm.lastName.trim() || !editForm.email.trim()) {
      setEditError("Veuillez remplir tous les champs obligatoires (Prénom, Nom, Email).");
      return;
    }

    setIsSaving(true);
    setEditError(null);
    try {
      const res = await updateUser(editingUser.email, {
        firstName: editForm.firstName.trim(),
        lastName: editForm.lastName.trim(),
        email: editForm.email.trim(),
        phone: editForm.phone.trim() || undefined,
        role: editForm.role,
        etablissement: editForm.etablissement.trim() || undefined,
      });

      if (res.ok) {
        setEditingUser(null);
        setReloadTrigger((prev) => prev + 1);
      } else {
        setEditError(res.error || "Une erreur est survenue lors de la mise à jour.");
      }
    } catch (err) {
      setEditError("Impossible de se connecter au serveur.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      <Navbar
        title="Dashboard"
        subtitle={
          user?.role === "Chef"
            ? `Supervision de l'établissement${user.etablissement ? ` — ${user.etablissement}` : ""}`
            : "Supervision nationale & gestion des utilisateurs"
        }
      />
      <div className="flex-1 p-6 space-y-6">
        {scopeMissing && (
          <div className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-amber-200">
            Aucun établissement n'est rattaché à votre compte : demandez au coordinateur national de
            le renseigner.
          </div>
        )}
        {/* Stats */}
        <div className="grid sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <StatCard
            label="Coord. d'établissement"
            value={stats.chefs}
            accent="blue"
            icon={Briefcase}
          />
          <StatCard
            label="Ophtalmologues"
            value={stats.medecins}
            accent="green"
            icon={Stethoscope}
          />
          <StatCard label="Techniciens" value={stats.techniciens} accent="purple" icon={Wrench} />
          <StatCard
            label="Méd. référants"
            value={stats.medecinReferants}
            accent="rose"
            icon={HeartPulse}
          />
          <StatCard label="Total" value={stats.total} accent="slate" icon={Users} />
        </div>

        {/* Liste utilisateurs */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-slate-900">
              <Users className="h-5 w-5 text-blue-600" />
              <h2 className="font-semibold">Utilisateurs enregistrés</h2>
            </div>
            <div className="flex flex-wrap gap-2 items-center">
              <input
                value={nameFilter}
                onChange={(e) => setNameFilter(e.target.value)}
                placeholder="Rechercher par nom..."
                className="rounded-lg border border-slate-200 bg-white py-1.5 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100"
              />
              <div className="flex gap-1.5 border-l border-slate-200 pl-2">
                {ROLE_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    onClick={() => setFilter(f.value)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                      filter === f.value
                        ? "bg-blue-600 text-white"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {error && (
            <div className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
              {error}
            </div>
          )}

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm table-fixed">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                  <th className="w-1/4 py-2 pr-4">Nom</th>
                  <th className="w-1/6 py-2 pr-4">Rôle</th>
                  <th className="w-1/4 py-2 pr-4">Contact</th>
                  <th className="w-1/6 py-2 pr-4">Disponibilité</th>
                  {user?.role === "Admin" && <th className="w-1/6 py-2 pr-4">Ajouté par</th>}
                  <th className="w-1/6 py-2 pr-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr>
                    <td
                      colSpan={user?.role === "Admin" ? 6 : 5}
                      className="py-6 text-center text-slate-500"
                    >
                      Chargement...
                    </td>
                  </tr>
                ) : backendUsers.length === 0 ? (
                  <tr>
                    <td
                      colSpan={user?.role === "Admin" ? 6 : 5}
                      className="py-6 text-center text-slate-500"
                    >
                      Aucun utilisateur.
                    </td>
                  </tr>
                ) : (
                  backendUsers.map((u) => (
                    <tr key={u.id} className="hover:bg-slate-50">
                      <td className="py-3 pr-4 font-medium text-slate-900">
                        {u.firstName} {u.lastName}
                      </td>
                      <td className="py-3 pr-4">
                        <RoleBadge role={u.role} />
                        {u.etablissement && (
                          <div
                            className="text-[11px] text-slate-500 mt-1 font-normal truncate max-w-[150px]"
                            title={u.etablissement}
                          >
                            🏥 {u.etablissement}
                          </div>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-slate-600">
                        <div className="font-medium">{u.email}</div>
                        <div className="text-xs text-slate-400 mt-0.5">{u.phone || "—"}</div>
                      </td>
                      <td className="py-3 pr-4">
                        {u.role === "Medecin" ? (
                          <div className="flex flex-col gap-1.5">
                            <div>
                              {u.is_disponible ? (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-green-100 text-green-700">
                                  <UserCheck size={12} /> Disponible
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-red-100 text-red-700">
                                  <UserX size={12} /> Indisponible
                                </span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <span className="text-slate-400 text-xs">—</span>
                        )}
                      </td>
                      {user?.role === "Admin" && (
                        <td className="py-3 pr-4 text-slate-600">{u.createdBy || "—"}</td>
                      )}
                      <td className="py-3 pr-4 text-right space-x-2">
                        {u.role === "Medecin" && (
                          <button
                            onClick={() => handleToggleAvailability(u.email)}
                            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition ${
                              u.is_disponible
                                ? "text-red-600 hover:bg-red-50"
                                : "text-green-600 hover:bg-green-50"
                            }`}
                            title={u.is_disponible ? "Rendre Indisponible" : "Rendre Disponible"}
                          >
                            {u.is_disponible ? (
                              <UserX className="h-3.5 w-3.5" />
                            ) : (
                              <UserCheck className="h-3.5 w-3.5" />
                            )}
                            Basculer
                          </button>
                        )}
                        <button
                          onClick={() => handleEdit(u)}
                          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50"
                        >
                          <Edit className="h-3.5 w-3.5" />
                          Modifier
                        </button>
                        {user?.role === "Admin" && (
                          <button
                            onClick={() => handleDelete(u.id, `${u.firstName} ${u.lastName}`)}
                            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Supprimer
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-4 border-t border-slate-100 pt-4 flex justify-center">
            <Pagination
              currentPage={usersPage}
              totalPages={Math.max(1, totalPages)}
              onPageChange={setUsersPage}
            />
          </div>
        </div>

        {/* Connexions et déconnexions du jour - réservé au coordinateur national */}
        {user?.role === "Admin" && (
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2 text-slate-900">
              <Activity className="h-5 w-5 text-blue-600" />
              <h2 className="font-semibold">Connexions et déconnexions du jour (activité)</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                    <th className="py-2 pr-4">Heure</th>
                    <th className="py-2 pr-4">Utilisateur</th>
                    <th className="py-2 pr-4">Rôle</th>
                    <th className="py-2 pr-4">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {backendLogs.map((e) => {
                    const d = new Date(e.at);
                    return (
                      <tr key={e.id} className="hover:bg-slate-50">
                        <td className="py-3 pr-4 text-slate-600">
                          {d.toISOString().slice(11, 16)}
                        </td>
                        <td className="py-3 pr-4 font-medium text-slate-900">{e.userName}</td>
                        <td className="py-3 pr-4 text-slate-600">
                          <RoleBadge role={e.role} />
                        </td>
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
                  })}
                  {backendLogs.length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-6 text-center text-slate-500">
                        Aucune activité aujourd'hui.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <Pagination
              currentPage={logsPage}
              totalPages={Math.max(1, logsTotalPages)}
              onPageChange={setLogsPage}
            />
          </div>
        )}
      </div>

      {/* Modal de Modification */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md transform overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-2xl transition-all">
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
              <div className="flex items-center gap-2 text-slate-900">
                <Edit className="h-5 w-5 text-blue-600" />
                <h3 className="font-semibold text-slate-800">Modifier l'utilisateur</h3>
              </div>
              <button
                onClick={() => setEditingUser(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-50 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleSave} className="p-6 space-y-4">
              {editError && (
                <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
                  {editError}
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                    Prénom <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={editForm.firstName}
                    onChange={(e) => setEditForm({ ...editForm, firstName: e.target.value })}
                    className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                    Nom <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={editForm.lastName}
                    onChange={(e) => setEditForm({ ...editForm, lastName: e.target.value })}
                    className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                  Email <span className="text-red-500">*</span>
                </label>
                <input
                  type="email"
                  value={editForm.email}
                  onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                  className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                  Téléphone
                </label>
                <input
                  type="text"
                  value={editForm.phone}
                  onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                  placeholder="+213 555..."
                  className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                  Rôle
                </label>
                <select
                  value={editForm.role}
                  onChange={(e) => setEditForm({ ...editForm, role: e.target.value as Role })}
                  className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100"
                >
                  {(user?.role === "Admin"
                    ? (["Admin", "Chef", "Medecin", "Technicien", "MedecinReferant"] as Role[])
                    : (["Medecin", "Technicien", "MedecinReferant"] as Role[])
                  ).map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                  Établissement / Hôpital{" "}
                  {editForm.role !== "Admin" && (
                    <span className="text-blue-600 font-normal">
                      (obligatoire, définit le périmètre)
                    </span>
                  )}
                </label>
                <input
                  type="text"
                  list="edit-etablissements-list"
                  required={editForm.role !== "Admin"}
                  // Le coordinateur d'établissement ne peut pas sortir un compte de son établissement.
                  readOnly={user?.role === "Chef"}
                  value={editForm.etablissement}
                  onChange={(e) => setEditForm({ ...editForm, etablissement: e.target.value })}
                  placeholder="Ex: HOPITAL CIRCONSCRIPTION KELIBIA"
                  className="w-full rounded-lg border border-slate-200 bg-white py-2 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-100 read-only:bg-slate-50 read-only:text-slate-600"
                />
                <datalist id="edit-etablissements-list">
                  {ETABLISSEMENTS.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </div>

              <div className="flex justify-end gap-3 border-t border-slate-100 pt-4 mt-6">
                <button
                  type="button"
                  onClick={() => setEditingUser(null)}
                  className="rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 px-4 py-2 text-sm font-medium transition"
                  disabled={isSaving}
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 text-sm font-medium transition disabled:bg-blue-400"
                  disabled={isSaving}
                >
                  {isSaving ? "Enregistrement..." : "Enregistrer"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function RoleBadge({ role }: { role: Role }) {
  const classes: Record<Role, string> = {
    Admin: "bg-slate-100 text-slate-700",
    Chef: "bg-blue-50 text-blue-700",
    Medecin: "bg-emerald-50 text-emerald-700",
    Technicien: "bg-purple-50 text-purple-700",
    MedecinReferant: "bg-rose-50 text-rose-700",
  };
  const label = ROLE_LABELS[role] || role || "Inconnu";
  const cls = classes[role] || "bg-slate-100 text-slate-700";
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
}

function StatCard({
  label,
  value,
  accent,
  icon: Icon,
}: {
  label: string;
  value: number;
  accent: "blue" | "green" | "orange" | "slate" | "purple" | "rose";
  icon: typeof Users;
}) {
  const map = {
    blue: "from-blue-500 to-blue-600",
    green: "from-emerald-500 to-emerald-600",
    orange: "from-orange-500 to-orange-600",
    slate: "from-slate-500 to-slate-700",
    purple: "from-purple-500 to-purple-600",
    rose: "from-rose-500 to-rose-600",
  } as const;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
        <Icon className="h-4 w-4 text-slate-400" />
      </div>
      <div className="mt-2">
        <span
          className={`bg-gradient-to-br bg-clip-text text-3xl font-bold text-transparent ${map[accent]}`}
        >
          {value}
        </span>
      </div>
    </div>
  );
}
