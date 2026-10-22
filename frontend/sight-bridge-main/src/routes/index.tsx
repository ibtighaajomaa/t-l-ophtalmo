import { createFileRoute, Navigate } from "@tanstack/react-router";
import { homePathFor, useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" />;
  return <Navigate to={homePathFor(user.role)} />;
}
