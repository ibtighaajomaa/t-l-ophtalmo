/**
 * AuthProvider — Contexte React simulant l'authentification.
 * Stocke l'utilisateur courant + persiste la session dans localStorage.
 * Gère également la création de comptes (Chef de Service par Admin,
 * Médecins/Résidents par Chef de Service) — stockés en mémoire/localStorage.
 * Conserve un historique d'utilisation (logins).
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { jwtDecode } from "jwt-decode";

interface KeycloakTokenPayload {
  email?: string;
  given_name?: string;
  family_name?: string;
  realm_access?: {
    roles: string[];
  };
}

export type Role = "Admin" | "Chef" | "Medecin" | "Resident";

export interface AppUser {
  id: string;
  email: string;
  password: string;
  role: Role;
  firstName: string;
  lastName: string;
  specialty?: string;
  phone?: string;
  createdAt?: string; // ISO date
  createdBy?: string; // Admin's name who added the user
  is_disponible?: boolean;
  charge_actuelle?: number;
}

export interface UsageEvent {
  id: string;
  userId: string;
  userName: string;
  role: Role;
  at: string; // ISO date
  action: "login" | "logout";
}

const STORAGE_USERS = "teleoph.users";
const STORAGE_SESSION = "teleoph.session";
const STORAGE_USAGE = "teleoph.usage";

const SEED_USERS: AppUser[] = [
  {
    id: "u-admin",
    email: "admin@teleoph.com",
    password: "admin123",
    role: "Admin",
    firstName: "Sarah",
    lastName: "Admin",
    createdAt: "2026-06-01T10:00:00Z",
    createdBy: "Système",
  },
  {
    id: "u-chef",
    email: "chef@teleoph.com",
    password: "chef123",
    role: "Chef",
    firstName: "Karim",
    lastName: "Benali",
    specialty: "Ophtalmologie",
    phone: "+213 555 100 100",
    createdAt: "2026-06-12T08:30:00Z",
    createdBy: "Sarah Admin",
  },
  {
    id: "u-med",
    email: "medecin@teleoph.com",
    password: "med123",
    role: "Medecin",
    firstName: "Leïla",
    lastName: "Hadj",
    specialty: "Rétine",
    createdAt: "2026-06-12T09:15:00Z",
    createdBy: "Karim Benali",
  },
  {
    id: "u-res",
    email: "resident@teleoph.com",
    password: "res123",
    role: "Resident",
    firstName: "Yanis",
    lastName: "Mokrane",
    createdAt: "2026-06-12T07:50:00Z",
    createdBy: "Karim Benali",
  },
];

const SEED_USAGE: UsageEvent[] = [
  { id: "ev-1", userId: "u-chef", userName: "Karim Benali", role: "Chef", at: "2026-06-10T08:30:00Z", action: "login" },
  { id: "ev-2", userId: "u-med", userName: "Leïla Hadj", role: "Medecin", at: "2026-06-10T09:15:00Z", action: "login" },
  { id: "ev-2-out", userId: "u-med", userName: "Leïla Hadj", role: "Medecin", at: "2026-06-10T17:30:00Z", action: "logout" },
  { id: "ev-3", userId: "u-res", userName: "Yanis Mokrane", role: "Resident", at: "2026-06-11T07:50:00Z", action: "login" },
  { id: "ev-4", userId: "u-med", userName: "Leïla Hadj", role: "Medecin", at: "2026-06-11T10:00:00Z", action: "login" },
  { id: "ev-5", userId: "u-chef", userName: "Karim Benali", role: "Chef", at: "2026-06-12T08:05:00Z", action: "login" },
  { id: "ev-5-out", userId: "u-chef", userName: "Karim Benali", role: "Chef", at: "2026-06-12T12:00:00Z", action: "logout" },
  { id: "ev-6", userId: "u-admin", userName: "Sarah Admin", role: "Admin", at: "2026-06-12T08:45:00Z", action: "login" },
];

interface AuthContextValue {
  user: AppUser | null;
  users: AppUser[];
  usage: UsageEvent[];
  login: (email: string, password: string) => Promise<{ ok: boolean; requirePasswordReset?: boolean; error?: string }>;
  logout: () => void;
  resetPassword: (email: string, newPassword: string) => Promise<{ ok: boolean; error?: string }>;
  createUser: (u: Omit<AppUser, "id">) => Promise<{ ok: boolean; error?: string }>;
  deleteUser: (id: string) => { ok: boolean; error?: string };
  updateUser: (oldEmail: string, data: { email: string; firstName: string; lastName: string; phone?: string; role?: Role; password?: string; oldPassword?: string }) => Promise<{ ok: boolean; error?: string }>;
  hasRole: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function loadUsers(): AppUser[] {
  if (typeof window === "undefined") return SEED_USERS;
  try {
    const raw = localStorage.getItem(STORAGE_USERS);
    if (!raw) {
      localStorage.setItem(STORAGE_USERS, JSON.stringify(SEED_USERS));
      return SEED_USERS;
    }
    return JSON.parse(raw) as AppUser[];
  } catch {
    return SEED_USERS;
  }
}

function loadUsage(): UsageEvent[] {
  if (typeof window === "undefined") return SEED_USAGE;
  try {
    const raw = localStorage.getItem(STORAGE_USAGE);
    if (!raw) {
      localStorage.setItem(STORAGE_USAGE, JSON.stringify(SEED_USAGE));
      return SEED_USAGE;
    }
    return JSON.parse(raw) as UsageEvent[];
  } catch {
    return SEED_USAGE;
  }
}

function loadSession(users: AppUser[]): AppUser | null {
  if (typeof window === "undefined") return null;
  try {
    const id = localStorage.getItem(STORAGE_SESSION) || sessionStorage.getItem(STORAGE_SESSION);
    return users.find((u) => u.id === id) ?? null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [initKeycloak, setInitKeycloak] = useState(false);
  const [users, setUsers] = useState<AppUser[]>(() => loadUsers());
  const [usage, setUsage] = useState<UsageEvent[]>([]);
  const [user, setUser] = useState<AppUser | null>(() => loadSession(loadUsers()));

  useEffect(() => {
    fetch("/api/logs/")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch logs");
        return res.json();
      })
      .then((data) => setUsage(data))
      .catch((err) => console.error("Error loading logs from backend:", err));
  }, [user]);

  useEffect(() => {
    localStorage.setItem(STORAGE_USERS, JSON.stringify(users));
  }, [users]);

  useEffect(() => {
    localStorage.setItem(STORAGE_USAGE, JSON.stringify(usage));
  }, [usage]);

  useEffect(() => {
    const token = localStorage.getItem("teleoph.token") || sessionStorage.getItem("teleoph.token");
    if (token) {
      try {
        const decoded = jwtDecode<KeycloakTokenPayload>(token);
        const roles = decoded.realm_access?.roles || [];
        let userRole: Role = "Medecin";
        if (roles.includes("ADMIN_SYSTEME") || roles.includes("ADMIN")) userRole = "Admin";
        else if (roles.includes("CHEF_SERVICE")) userRole = "Chef";
        else if (roles.includes("RESIDENT")) userRole = "Resident";
        
        const email = decoded.email || "user@example.com";
        const loggedUser: AppUser = {
          id: email,
          email: email,
          password: "",
          role: userRole,
          firstName: decoded.given_name || email.split("@")[0],
          lastName: decoded.family_name || "",
        };

        localStorage.setItem(STORAGE_SESSION, loggedUser.id);
        
        setUsers((prev) => {
          if (!prev.find((u) => u.id === loggedUser.id)) {
            return [...prev, loggedUser];
          }
          return prev;
        });
        setUser(loggedUser);
      } catch (err) {
        console.error("Token invalide", err);
        localStorage.removeItem("teleoph.token");
        localStorage.removeItem(STORAGE_SESSION);
        sessionStorage.removeItem("teleoph.token");
        sessionStorage.removeItem(STORAGE_SESSION);
        setUser(null);
      }
    } else {
      setUser(null);
      localStorage.removeItem(STORAGE_SESSION);
      sessionStorage.removeItem(STORAGE_SESSION);
    }
    setInitKeycloak(true);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      users,
      usage,
      login: async (email, password) => {
        try {
          const loginUrl = "/api/auth/login/";
          
          const response = await fetch(loginUrl, {
              method: 'POST',
              headers: {
                  'Content-Type': 'application/json'
              },
              body: JSON.stringify({ email, password })
          });

          if (response.ok) {
              const tokens = await response.json();
              localStorage.setItem('teleoph.token', tokens.access_token);
              if (tokens.refresh_token) {
                localStorage.setItem('teleoph.refresh_token', tokens.refresh_token);
              }
              
              const decoded = jwtDecode<KeycloakTokenPayload>(tokens.access_token);
              const roles = decoded.realm_access?.roles || [];
              let userRole: Role = "Medecin";
              if (roles.includes("ADMIN_SYSTEME") || roles.includes("ADMIN")) userRole = "Admin";
              else if (roles.includes("CHEF_SERVICE")) userRole = "Chef";
              else if (roles.includes("RESIDENT")) userRole = "Resident";
              
              const loggedUser: AppUser = {
                id: email,
                email: email,
                password: "",
                role: userRole,
                firstName: decoded.given_name || email.split("@")[0],
                lastName: decoded.family_name || "",
              };

              localStorage.setItem(STORAGE_SESSION, loggedUser.id);
              
              setUsers((prev) => {
                if (!prev.find((u) => u.id === loggedUser.id)) {
                  return [...prev, loggedUser];
                }
                return prev;
              });
              setUser(loggedUser);
              return { ok: true };
          } else {
              const errData = await response.json();
              if (errData.error_code === "invalid_grant" && errData.error?.includes("Account is not fully set up")) {
                  return { ok: false, requirePasswordReset: true, error: "Changement de mot de passe requis." };
              }
              return { ok: false, error: errData.error || "Identifiants incorrects" };
          }
        } catch (error) {
            console.error("Erreur serveur Keycloak", error);
            return { ok: false, error: "Erreur de connexion au serveur" };
        }
      },
      logout: () => {
        const refreshToken = localStorage.getItem("teleoph.refresh_token");
        if (refreshToken) {
          fetch("/api/auth/logout/", {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({ refresh_token: refreshToken })
          }).catch((err) => {
            console.error("Erreur lors de la déconnexion Keycloak:", err);
          });
        }
        localStorage.removeItem(STORAGE_SESSION);
        localStorage.removeItem("teleoph.token");
        localStorage.removeItem("teleoph.refresh_token");
        sessionStorage.removeItem(STORAGE_SESSION);
        sessionStorage.removeItem("teleoph.token");
        sessionStorage.removeItem("teleoph.refresh_token");
        setUser(null);
      },
      resetPassword: async (email, newPassword) => {
        try {
          const res = await fetch("/api/auth/reset-password/", {
            method: "POST",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({ username: email, new_password: newPassword }),
          });

          if (!res.ok) {
            const errData = await res.json().catch(() => null);
            return { ok: false, error: errData?.error || "Erreur de réinitialisation." };
          }
          return { ok: true };
        } catch (err) {
          console.error(err);
          return { ok: false, error: "Impossible de joindre le backend Django." };
        }
      },
      createUser: async (data) => {
        try {
          const payload = {
            email: data.email,
            prenom: data.firstName,
            nom: data.lastName,
            role: data.role === "Admin" ? "ADMIN_SYSTEME" : data.role === "Chef" ? "CHEF_SERVICE" : data.role === "Resident" ? "RESIDENT" : "OPHTALMOLOGUE",
            password_provisoire: data.password,
            telephone: data.phone,
            createdBy: user ? `${user.firstName} ${user.lastName}` : ""
          };

          const token = localStorage.getItem("teleoph.token") || sessionStorage.getItem("teleoph.token");
          const res = await fetch("/api/auth/register-user/", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify(payload),
          });

          if (!res.ok) {
            const errData = await res.json().catch(() => null);
            return { ok: false, error: errData?.error || "Erreur de création côté serveur." };
          }

          // Ajout local pour que l'interface se mette à jour sans recharger
          const newUser: AppUser = { 
            ...data, 
            id: `u-${Date.now()}`,
            createdAt: new Date().toISOString(),
            createdBy: user ? `${user.firstName} ${user.lastName}` : "Système"
          };
          setUsers((prev) => [...prev, newUser]);
          return { ok: true };

        } catch (err) {
          console.error(err);
          return { ok: false, error: "Impossible de joindre le backend Django." };
        }
      },
      deleteUser: (id) => {
        if (user?.id === id) {
          return { ok: false, error: "Vous ne pouvez pas supprimer votre propre compte." };
        }
        setUsers((prev) => prev.filter((u) => u.id !== id));
        return { ok: true };
      },
      updateUser: async (oldEmail, data) => {
        try {
          const payload = {
            old_email: oldEmail,
            email: data.email,
            prenom: data.firstName,
            nom: data.lastName,
            telephone: data.phone,
            password: data.password, // Nouveau mot de passe (optionnel)
            old_password: data.oldPassword, // Ancien mot de passe
            role: data.role ? (data.role === "Admin" ? "ADMIN_SYSTEME" : data.role === "Chef" ? "CHEF_SERVICE" : data.role === "Resident" ? "RESIDENT" : "OPHTALMOLOGUE") : undefined
          };

          const token = localStorage.getItem("teleoph.token") || sessionStorage.getItem("teleoph.token");
          const res = await fetch("/api/users/update/", {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
              "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify(payload),
          });

          if (!res.ok) {
            const errData = await res.json().catch(() => null);
            return { ok: false, error: errData?.error || "Erreur de modification côté serveur." };
          }

          // Mettre à jour l'utilisateur local dans le state users
          setUsers((prev) =>
            prev.map((u) => {
              if (u.email === oldEmail) {
                return {
                  ...u,
                  email: data.email,
                  firstName: data.firstName,
                  lastName: data.lastName,
                  phone: data.phone,
                  role: data.role || u.role,
                };
              }
              return u;
            })
          );
          
          // Si l'utilisateur modifié est l'utilisateur connecté lui-même, mettre à jour son profil aussi
          if (user && user.email === oldEmail) {
            setUser((prev) => prev ? {
              ...prev,
              email: data.email,
              firstName: data.firstName,
              lastName: data.lastName,
              phone: data.phone,
              role: data.role || prev.role,
            } : null);
          }

          return { ok: true };
        } catch (err) {
          console.error(err);
          return { ok: false, error: "Impossible de joindre le backend Django." };
        }
      },
      hasRole: (...roles) => !!user && roles.includes(user.role),
    }),
    [user, users, usage],
  );

  if (!initKeycloak) {
    return <div className="flex min-h-screen items-center justify-center text-slate-600">Chargement de la sécurité Keycloak...</div>;
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}


export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth doit être utilisé dans <AuthProvider>");
  return ctx;
}
