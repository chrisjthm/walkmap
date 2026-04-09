import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { getApiBase as getConfiguredApiBase } from "../env";

type AuthUser = {
  id: string;
  email: string;
};

type AuthContextValue = {
  token: string | null;
  user: AuthUser | null;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
  authFetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export const getApiBase = () => {
  return getConfiguredApiBase();
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const setSession = useCallback((nextToken: string, nextUser: AuthUser) => {
    setToken(nextToken);
    setUser(nextUser);
  }, []);
  const clearSession = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);
  const authFetch = useCallback(
    (input: RequestInfo | URL, init?: RequestInit) => {
      if (!token) {
        throw new Error("Authentication required");
      }
      const headers = new Headers(init?.headers);
      headers.set("Authorization", `Bearer ${token}`);
      return fetch(input, {
        ...init,
        headers,
      });
    },
    [token],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      user,
      setSession,
      clearSession,
      authFetch,
    }),
    [authFetch, clearSession, setSession, token, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
