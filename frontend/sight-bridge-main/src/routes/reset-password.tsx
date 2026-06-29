import { createFileRoute } from "@tanstack/react-router";
import ResetPasswordPage from "../components/ResetPasswordPage";

export const Route = createFileRoute("/reset-password")({
  validateSearch: (search: Record<string, unknown>) => {
    return {
      token: search.token as string | undefined,
    };
  },
  component: ResetPasswordPage,
});
