/** Layout protégé — sidebar + outlet. */
import { createFileRoute, Outlet } from "@tanstack/react-router";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Sidebar } from "@/components/Sidebar";

export const Route = createFileRoute("/_app")({
  component: AppLayout,
});

function AppLayout() {
  return (
    <ProtectedRoute>
      <div className="flex min-h-screen w-full bg-slate-50">
        <Sidebar />
        <main className="flex-1 min-w-0 flex flex-col">
          <Outlet />
        </main>
      </div>
    </ProtectedRoute>
  );
}
