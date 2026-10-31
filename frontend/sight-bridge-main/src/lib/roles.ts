/** Rôles applicatifs : libellés, correspondance Keycloak et liste des établissements. */
import type { Role } from "@/lib/auth-context";

/** Libellés affichés. Les codes internes (Admin, Chef…) sont inchangés pour rester compatibles avec Keycloak. */
export const ROLE_LABELS: Record<Role, string> = {
  Admin: "Coordinateur national",
  Chef: "Coordinateur d'établissement",
  Medecin: "Ophtalmologue",
  Technicien: "Technicien",
  MedecinReferant: "Médecin référant",
};

export const ROLE_TO_KEYCLOAK: Record<Role, string> = {
  Admin: "ADMIN_SYSTEME",
  Chef: "CHEF_SERVICE",
  Medecin: "OPHTALMOLOGUE",
  Technicien: "TECHNICIEN",
  MedecinReferant: "MEDECIN_REFERANT",
};

/** Rôle applicatif déduit des rôles realm du token ; null si aucun rôle autorisé (ex. ancien résident). */
export function roleFromKeycloak(realmRoles: string[]): Role | null {
  if (realmRoles.includes("ADMIN_SYSTEME") || realmRoles.includes("ADMIN")) return "Admin";
  if (realmRoles.includes("CHEF_SERVICE")) return "Chef";
  if (realmRoles.includes("OPHTALMOLOGUE")) return "Medecin";
  if (realmRoles.includes("TECHNICIEN")) return "Technicien";
  if (realmRoles.includes("MEDECIN_REFERANT")) return "MedecinReferant";
  return null;
}

/** Seul le coordinateur national n'est pas rattaché à un établissement. */
export function requiresEtablissement(role: Role): boolean {
  return role !== "Admin";
}

/** Un coordinateur (national ou d'établissement) supervise : il ne lit pas d'examens. */
export function isCoordinator(role: Role | undefined): boolean {
  return role === "Admin" || role === "Chef";
}

export const ETABLISSEMENTS = [
  "HOPITAL CIRCONSCRIPTION KELIBIA",
  "Hôpital de Circonscription Menzel Temime",
  "HOPITAL REGIONAL KEBILI",
  "Hôpital de Circonscription Deguech",
  "Hôpital de Circonscription Mateur",
  "HOPITAL REGIONAL SILIANA",
];
