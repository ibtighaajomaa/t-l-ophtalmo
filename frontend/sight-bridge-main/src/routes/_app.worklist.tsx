import { createFileRoute } from "@tanstack/react-router";
import { Navbar } from "@/components/Navbar";
import { Worklist } from "@/components/Worklist";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/_app/worklist")({
  component: WorklistPage,
});

function WorklistPage() {
  const { user } = useAuth();
  const subtitle =
    user?.role === "Admin"
      ? "Activité du jour — supervision (lecture seule)"
      : user?.role === "Chef"
        ? "Examens du jour — filtrer, assigner et superviser"
        : "Examens du jour à interpréter";
  return (
    <>
      <Navbar title="Worklist" subtitle={subtitle} />
      <div className="flex-1 p-6">
        <Worklist todayOnly showStats />
      </div>
    </>
  );
}
