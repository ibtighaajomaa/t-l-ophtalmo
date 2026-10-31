import { createFileRoute } from "@tanstack/react-router";
import { Navbar } from "@/components/Navbar";
import { Worklist } from "@/components/Worklist";
import { useAuth } from "@/lib/auth-context";
import { ProtectedRoute } from "@/components/ProtectedRoute";

export const Route = createFileRoute("/_app/worklist")({
  component: () => (
    <ProtectedRoute roles={["Admin", "Chef", "Medecin", "Technicien"]}>
      <WorklistPage />
    </ProtectedRoute>
  ),
});

function WorklistPage() {
  const { user } = useAuth();
  const subtitle =
    user?.role === "Admin"
      ? "Activité du jour — supervision nationale (lecture seule)"
      : user?.role === "Chef"
        ? `Activité du jour — supervision de l'établissement${user?.etablissement ? ` (${user.etablissement})` : ""}`
        : user?.role === "Technicien"
          ? `Acquisitions de l'établissement${user?.etablissement ? ` (${user.etablissement})` : ""}`
          : "Examens du jour à interpréter";
  return (
    <>
      <Navbar title="Worklist" subtitle={subtitle} />
      <div className="flex-1 p-6">
        <Worklist showStats />
      </div>
    </>
  );
}
