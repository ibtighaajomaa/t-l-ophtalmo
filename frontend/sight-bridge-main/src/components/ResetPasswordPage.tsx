import React, { useState } from 'react';
import { Route } from '../routes/reset-password';
import { useNavigate } from '@tanstack/react-router';
import { Lock, Eye, ShieldCheck } from 'lucide-react';
import axios from 'axios';
import { useAuth } from '@/lib/auth-context';

export const ResetPasswordPage = () => {
  const { token } = Route.useSearch();
  const navigate = useNavigate();
  const { login } = useAuth();
  
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    
    try {
      const res = await axios.post('/api/confirm-reset/', { token, password });
      const email = res.data.email;
      
      // Auto-login with the new password
      const loginRes = await login(email, password);
      setIsLoading(false);
      
      if (!loginRes.ok) {
        setError(loginRes.error ?? "Erreur lors de la reconnexion automatique.");
      } else {
        // Redirection after successful login
        const roles = ["Admin"]; // Just checking if they are admin, wait, we can just redirect to "/" or "/worklist"
        navigate({ to: "/worklist" });
      }
    } catch (err: any) {
      setIsLoading(false);
      setError(err.response?.data?.error || "Une erreur est survenue lors de la réinitialisation.");
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-slate-50">
      {/* Brand panel (Same as login) */}
      <div className="hidden lg:flex flex-col justify-between bg-gradient-to-br from-blue-600 to-blue-800 p-12 text-white">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 backdrop-blur">
            <Eye className="h-6 w-6" />
          </div>
          <span className="text-lg font-semibold">Télé-rétinographie</span>
        </div>
        <div>
          <h1 className="text-4xl font-bold leading-tight">
            La télé-ophtalmologie,<br />enfin fluide et sécurisée.
          </h1>
          <p className="mt-4 max-w-md text-blue-100">
            Centralisez les examens, collaborez entre médecins et résidents, et
            interprétez les images à distance — depuis une plateforme unique.
          </p>
          <div className="mt-8 flex items-center gap-2 text-sm text-blue-100">
            <ShieldCheck className="h-4 w-4" />
            Données chiffrées · Conforme aux exigences hospitalières
          </div>
        </div>
        <div className="text-xs text-blue-200">© 2026 Télé-rétinographie</div>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">
          <div className="lg:hidden mb-8 flex items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 text-white">
              <Eye className="h-5 w-5" />
            </div>
            <span className="text-lg font-semibold text-slate-900">Télé-rétinographie</span>
          </div>

          <h2 className="text-2xl font-bold text-slate-900">Nouveau mot de passe</h2>
          <p className="mt-1 text-sm text-slate-500">
            Saisissez votre nouveau mot de passe pour accéder à votre espace.
          </p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            <div>
              <label className="text-sm font-medium text-slate-700">Nouveau mot de passe</label>
              <div className="relative mt-1">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                  placeholder="••••••••"
                />
              </div>
            </div>

            {error && (
              <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading || !password}
              className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              {isLoading ? "Enregistrement en cours..." : "Valider et se connecter"}
            </button>
            
            <button 
              type="button"
              onClick={() => navigate({ to: '/login' })}
              className="mt-4 w-full text-center text-sm font-medium text-blue-600 hover:underline"
            >
              Retour à la connexion
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default ResetPasswordPage;
