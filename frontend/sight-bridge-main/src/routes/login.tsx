import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Eye, EyeOff, Lock, Mail, ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import ForgotPassword from "../components/ForgotPassword";

export const Route = createFileRoute("/login")({
  head: () => ({ meta: [{ title: "Connexion — Télé-rétinographie" }] }),
  component: LoginPage,
});

function LoginPage() {
  const { login, resetPassword, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [isResettingPassword, setIsResettingPassword] = useState(false);
  const [isForgotPassword, setIsForgotPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  if (user) {
    navigate({
      to: user.role === "Admin" ? "/admin" : "/worklist",
    });
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    const res = await login(email, password);
    setIsLoading(false);

    if (res.requirePasswordReset) {
      setIsResettingPassword(true);
      setError(null);
      return;
    }
    if (!res.ok) return setError(res.error ?? "Erreur");
  };

  const handleResetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    const res = await resetPassword(email, newPassword);
    if (!res.ok) {
      setIsLoading(false);
      return setError(res.error ?? "Erreur lors de la configuration du mot de passe.");
    }

    // Si la réinitialisation réussit, on connecte directement l'utilisateur
    const loginRes = await login(email, newPassword);
    setIsLoading(false);
    if (!loginRes.ok)
      return setError(loginRes.error ?? "Erreur lors de la reconnexion automatique.");
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-slate-50">
      {/* Brand panel */}
      <div className="hidden lg:block relative w-full h-full bg-slate-900">
        <img
          src="/login-bg.png"
          alt="Télé-rétinographie"
          className="absolute inset-0 w-full h-full object-cover"
        />
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">
          {/* Logo Ministère */}
          <div className="mb-12 flex flex-col items-center justify-center">
            <img
              src="/logo.png"
              alt="Ministère de la Santé"
              className="h-32 sm:h-40 w-auto object-contain drop-shadow-md transition-all duration-300 hover:scale-105"
            />
          </div>

          <h2 className="text-2xl font-bold text-slate-900 text-center sm:text-left">
            {isForgotPassword
              ? "Mot de passe oublié"
              : isResettingPassword
                ? "Nouveau mot de passe"
                : "Connexion"}
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            {isForgotPassword
              ? "Entrez votre adresse email pour recevoir un lien de réinitialisation."
              : isResettingPassword
                ? "C'est votre première connexion, vous devez définir un mot de passe définitif."
                : "Accédez à votre espace professionnel."}
          </p>

          {isForgotPassword ? (
            <div className="mt-8">
              <ForgotPassword />
              <button
                onClick={() => setIsForgotPassword(false)}
                className="mt-4 w-full text-center text-sm font-medium text-blue-600 hover:underline"
              >
                Retour à la connexion
              </button>
            </div>
          ) : !isResettingPassword ? (
            <form onSubmit={handleSubmit} className="mt-8 space-y-4" autoComplete="off">
              <div>
                <label className="text-sm font-medium text-slate-700">Email</label>
                <div className="relative mt-1">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                    placeholder="vous@hopital.rns"
                    autoComplete="off"
                    name="email_nofill"
                  />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-slate-700">Mot de passe</label>
                  <button
                    type="button"
                    onClick={() => setIsForgotPassword(true)}
                    className="text-sm font-medium text-blue-600 hover:underline"
                  >
                    Mot de passe oublié ?
                  </button>
                </div>
                <div className="relative mt-1">
                  <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-10 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                    placeholder="••••••••"
                    autoComplete="new-password"
                    name="pwd_nofill"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
              >
                {isLoading ? "Connexion en cours..." : "Se connecter"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleResetSubmit} className="mt-8 space-y-4">
              <div>
                <label className="text-sm font-medium text-slate-700">Nouveau mot de passe</label>
                <div className="relative mt-1">
                  <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-10 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                    placeholder="••••••••"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
              >
                {isLoading ? "Validation en cours..." : "Valider et se connecter"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
