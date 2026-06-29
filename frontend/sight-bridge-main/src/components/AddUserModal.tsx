/** Modal — Admin crée Chef de Service, Médecin (ophtalmologue) ou Résident. */
import { useState } from "react";
import {
  X,
  UserPlus,
  Stethoscope,
  GraduationCap,
  Briefcase,
  CheckCircle2,
  ShieldCheck,
} from "lucide-react";
import { useAuth, type Role } from "@/lib/auth-context";

type CreatableRole = Extract<Role, "Admin" | "Chef" | "Medecin" | "Resident">;

const ROLE_OPTIONS: { value: CreatableRole; label: string; icon: any }[] = [
  { value: "Admin", label: "Administrateur", icon: ShieldCheck },
  { value: "Chef", label: "Chef de Service", icon: Briefcase },
  { value: "Medecin", label: "Ophtalmologue", icon: Stethoscope },
  { value: "Resident", label: "Résident", icon: GraduationCap },
];

export function AddUserModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { createUser, user } = useAuth();
  const [role, setRole] = useState<CreatableRole>("Medecin");
  const [form, setForm] = useState({
    firstName: "",
    lastName: "",
    email: "",
    specialty: "",
    phone: "",
    password: Math.random().toString(36).slice(-8),
  });
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  const [isLoading, setIsLoading] = useState(false);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setFeedback(null);
    const res = await createUser({ ...form, role });
    setIsLoading(false);
    if (res.ok) {
      setFeedback({ ok: true, msg: `${form.firstName} ${form.lastName} ajouté(e) avec succès.` });
      setForm({
        firstName: "",
        lastName: "",
        email: "",
        specialty: "",
        phone: "",
        password: Math.random().toString(36).slice(-8),
      });
    } else {
      setFeedback({ ok: false, msg: res.error ?? "Erreur lors de la création" });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <UserPlus className="h-5 w-5 text-blue-600" />
            <h2 className="font-semibold text-slate-900">Ajouter un utilisateur</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4 p-6">
          <div>
            <label className="mb-2 block text-xs font-medium text-slate-600">Rôle</label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(user?.role === "Admin"
                ? ROLE_OPTIONS
                : ROLE_OPTIONS.filter((r) => r.value === "Medecin" || r.value === "Resident")
              ).map((opt) => {
                const Icon = opt.icon;
                const active = role === opt.value;
                return (
                  <button
                    type="button"
                    key={opt.value}
                    onClick={() => setRole(opt.value)}
                    className={`flex flex-col items-center gap-1.5 rounded-lg border px-2 py-3 text-xs font-medium transition ${
                      active
                        ? "border-blue-600 bg-blue-50 text-blue-700"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <Icon className="h-5 w-5" />
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field
              label="Prénom"
              value={form.firstName}
              onChange={(v) => setForm({ ...form, firstName: v })}
            />
            <Field
              label="Nom"
              value={form.lastName}
              onChange={(v) => setForm({ ...form, lastName: v })}
            />
          </div>
          <Field
            label="Email"
            type="email"
            value={form.email}
            onChange={(v) => setForm({ ...form, email: v })}
          />

          <Field
            label="Téléphone"
            value={form.phone}
            onChange={(v) => setForm({ ...form, phone: v })}
          />
          <Field
            label="Mot de passe provisoire"
            value={form.password}
            onChange={(v) => setForm({ ...form, password: v })}
          />

          {feedback && (
            <div
              className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${
                feedback.ok
                  ? "bg-green-50 text-green-700 ring-1 ring-green-200"
                  : "bg-red-50 text-red-700 ring-1 ring-red-200"
              }`}
            >
              {feedback.ok && <CheckCircle2 className="h-4 w-4 mt-0.5" />}
              <span>{feedback.msg}</span>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
            >
              Fermer
            </button>
            <button
              disabled={isLoading}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isLoading ? "Création en cours..." : "Créer le compte"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-slate-600">{label}</label>
      <input
        type={type}
        required
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
      />
    </div>
  );
}
