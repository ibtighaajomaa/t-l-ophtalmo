import { createFileRoute } from "@tanstack/react-router";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Navbar } from "@/components/Navbar";
import { Worklist } from "@/components/Worklist";

export const Route = createFileRoute("/_app/historique/examens")({
  component: () => (
    <ProtectedRoute roles={["Admin", "Chef", "Resident"]}>
      <ExamHistory />
    </ProtectedRoute>
  ),
});

function ExamHistory() {
  return (
    <>
      <Navbar
        title="Historique des examens"
        subtitle="Worklist complète — tous les examens, tous les jours"
      />
      <div className="flex-1 p-6">
        <Worklist showStats />
      </div>
    </>
  );
}
