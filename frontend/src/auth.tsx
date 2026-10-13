import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, configureApi } from "./api";

interface Session {
  token: string;
  login: string;
  expiresAt: number; // epoch ms
}

interface AuthContextValue {
  session: Session | null;
  /** Set when the session ended on its own (token expired or rejected), shown on the login page. */
  notice: string | null;
  login: (login: string, password: string) => Promise<void>;
  register: (login: string, password: string) => Promise<void>;
  logout: (notice?: string) => void;
}

const STORAGE_KEY = "pm-session";
const AuthContext = createContext<AuthContextValue | null>(null);

function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    return s.expiresAt > Date.now() ? s : null;
  } catch {
    return null;
  }
}

/** Reads `exp` from the JWT payload. Falls back to `expires_in`, then to the spec's 1 hour. */
function expiryOf(token: string, expiresIn?: number): number {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof payload.exp === "number") return payload.exp * 1000;
  } catch {
    // not a decodable JWT; fall through
  }
  return Date.now() + (expiresIn ?? 3600) * 1000;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [notice, setNotice] = useState<string | null>(null);

  const logout = useCallback((reason?: string) => {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // storage unavailable; nothing to clear
    }
    setSession(null);
    setNotice(reason ?? null);
  }, []);

  configureApi({
    getToken: () => session?.token ?? null,
    onUnauthorized: () => logout("Your session has ended. Please log in again."),
  });

  // Log out automatically when the 1-hour token expires.
  useEffect(() => {
    if (!session) return;
    const ms = session.expiresAt - Date.now();
    const timer = setTimeout(() => logout("Your session expired after 1 hour. Please log in again."), Math.max(ms, 0));
    return () => clearTimeout(timer);
  }, [session, logout]);

  const login = useCallback(async (login: string, password: string) => {
    const res = await api.login(login, password);
    const s: Session = { token: res.access_token, login, expiresAt: expiryOf(res.access_token, res.expires_in) };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch {
      // storage unavailable; the session lasts until the tab closes
    }
    setNotice(null);
    setSession(s);
  }, []);

  const register = useCallback(
    async (loginName: string, password: string) => {
      await api.register(loginName, password);
      await login(loginName, password);
    },
    [login],
  );

  const value = useMemo(() => ({ session, notice, login, register, logout }), [session, notice, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
