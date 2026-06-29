/** Sidebar dynamique selon le rôle. */
import { useState } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  Users,
  ClipboardList,
  Eye,
  LogOut,
  Stethoscope,
  UserPlus,
  History,
  ChevronDown,
  Activity,
  FileText,
  Calendar,
  BarChart3,
  User,
} from "lucide-react";
import { useAuth, type Role } from "@/lib/auth-context";
import { AddUserModal } from "./AddUserModal";
import { ProfileModal } from "./ProfileModal";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Eye;
  roles: Role[];
}

const NAV: NavItem[] = [
  { to: "/admin", label: "Dashboard", icon: LayoutDashboard, roles: ["Admin", "Chef"] },
  {
    to: "/worklist",
    label: "Worklist",
    icon: ClipboardList,
    roles: ["Admin", "Chef", "Medecin", "Resident"],
  },
  {
    to: "/analyse",
    label: "Analyse",
    icon: BarChart3,
    roles: ["Admin", "Chef", "Medecin", "Resident"],
  },
  {
    to: "/historique/examens",
    label: "Historique des examens",
    icon: FileText,
    roles: ["Chef", "Resident"],
  },
  {
    to: "/calendrier",
    label: "Calendrier",
    icon: Calendar,
    roles: ["Admin", "Chef", "Medecin", "Resident"],
  },
  {
    to: "/logs",
    label: "Logs",
    icon: Activity,
    roles: ["Admin"],
  },
];

const HISTORY_ROLES: Role[] = ["Admin", "Chef", "Medecin", "Resident"];

export function Sidebar() {
  const { user, logout } = useAuth();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [modalOpen, setModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  if (!user) return null;

  const items = NAV.filter((i) => i.roles.includes(user.role));

  return (
    <>
      <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2 px-5 py-5 border-b border-slate-200">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Eye className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">Télé-rétinographie</div>
            <div className="text-xs text-slate-500">Plateforme médicale</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {items.map((item) => {
            const active = pathname.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}

          {/* Separator if needed, but NAV now handles everything */}

          {(user.role === "Admin" || user.role === "Chef") && (
            <button
              onClick={() => setModalOpen(true)}
              className="mt-3 flex w-full items-center gap-2 rounded-lg bg-blue-600 px-3 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
            >
              <UserPlus className="h-4 w-4" />
              Ajouter un utilisateur
            </button>
          )}
        </nav>

        <div className="border-t border-slate-200 p-3">
          <div className="flex items-center justify-between px-2 py-2">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-blue-700">
                <Stethoscope className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-slate-900">
                  {user.firstName} {user.lastName}
                </div>
                <div className="truncate text-xs text-slate-500">{user.role}</div>
              </div>
            </div>
            <button
              onClick={() => setProfileModalOpen(true)}
              className="text-slate-400 hover:text-blue-600 transition p-1"
              title="Modifier mon profil"
            >
              <User className="h-4 w-4" />
            </button>
          </div>
          <button
            onClick={logout}
            className="mt-2 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 hover:text-red-600"
          >
            <LogOut className="h-4 w-4" />
            Déconnexion
          </button>
        </div>
      </aside>

      <AddUserModal open={modalOpen} onClose={() => setModalOpen(false)} />
      <ProfileModal open={profileModalOpen} onClose={() => setProfileModalOpen(false)} />
    </>
  );
}
