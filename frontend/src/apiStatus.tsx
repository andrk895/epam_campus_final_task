import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, endpointKey, ENDPOINTS, type EndpointInfo } from "./api";

// Reads the backend's /openapi.json to find out which endpoints exist yet, so the UI can
// say "coming in T3.2" instead of showing a confusing 404 while the backend is being built.

interface ApiStatus {
  /** null while loading or when the backend is unreachable */
  available: Set<string> | null;
  reachable: boolean | null;
  checkedAt: Date | null;
  refresh: () => void;
  /** true/false once known; true while unknown so the UI doesn't block on a slow check */
  has: (method: string, path: string) => boolean;
  /** The catalogue entry for a missing endpoint, for "coming in Tx.y" messages. */
  missing: (method: string, path: string) => EndpointInfo | undefined;
}

const Ctx = createContext<ApiStatus | null>(null);
const REFRESH_MS = 30_000;

export function ApiStatusProvider({ children }: { children: ReactNode }) {
  const [available, setAvailable] = useState<Set<string> | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const spec = await api.openapi();
      const keys = new Set<string>();
      for (const [path, methods] of Object.entries(spec.paths ?? {})) {
        for (const m of Object.keys(methods)) keys.add(endpointKey(m, path));
      }
      setAvailable(keys);
      setReachable(true);
    } catch {
      setAvailable(null);
      setReachable(false);
    }
    setCheckedAt(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const has = useCallback(
    (method: string, path: string) => (available ? available.has(endpointKey(method, path)) : true),
    [available],
  );
  const missing = useCallback(
    (method: string, path: string) => {
      if (has(method, path)) return undefined;
      const key = endpointKey(method, path);
      return ENDPOINTS.find((e) => endpointKey(e.method, e.path) === key);
    },
    [has],
  );

  return (
    <Ctx.Provider value={{ available, reachable, checkedAt, refresh: () => void refresh(), has, missing }}>
      {children}
    </Ctx.Provider>
  );
}

export function useApiStatus(): ApiStatus {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApiStatus must be used inside ApiStatusProvider");
  return ctx;
}
