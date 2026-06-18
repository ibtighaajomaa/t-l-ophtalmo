import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" />;
  if (user.role === "Admin") return <Navigate to="/admin" />;
  return <Navigate to="/worklist" />;
}
