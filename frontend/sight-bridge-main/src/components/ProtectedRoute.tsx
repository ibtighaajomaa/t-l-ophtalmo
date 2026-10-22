/** Garde de route — vérifie session + rôle autorisé. */
import { Navigate } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { homePathFor, useAuth, type Role } from "@/lib/auth-context";

export function ProtectedRoute({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" />;
  if (roles && !roles.includes(user.role)) return <Navigate to={homePathFor(user.role)} />;
  return <>{children}</>;
}
