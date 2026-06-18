/** Top bar avec titre de page + info utilisateur (mobile-friendly). */
import { Bell } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export function Navbar({ title, subtitle }: { title: string; subtitle?: string }) {
  const { user } = useAuth();
  return (
    <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-4">
        <button className="rounded-lg p-2 text-slate-500 hover:bg-slate-100">
          <Bell className="h-5 w-5" />
        </button>
        {user && (
          <div className="hidden sm:block text-right">
            <div className="text-sm font-medium text-slate-900">
              {user.firstName} {user.lastName}
            </div>
            <div className="text-xs text-slate-500">{user.email}</div>
          </div>
        )}
      </div>
    </header>
  );
}
