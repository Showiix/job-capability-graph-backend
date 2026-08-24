import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { AuthUser } from '../types/api';
import { API_BASE_URL } from '../services/apiBase';

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  sessionError: string | null;
  ensureSession: () => Promise<AuthUser | null>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

// In mock mode we skip the real login check
const MOCK_USER: AuthUser = {
  id: 'mock-admin',
  username: 'admin',
  display_name: '管理员（演示）',
  role: 'admin',
  is_active: true,
};

async function fetchMe(): Promise<AuthUser | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
      credentials: 'include',
    });
    if (!res.ok) return null;
    const body = await res.json();
    return (body.data ?? body) as AuthUser;
  } catch {
    return null;
  }
}

async function createGuestSession(): Promise<AuthUser> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/guest`, {
    method: 'POST',
    credentials: 'include',
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      (body as any).error?.message
        ?? (body as any).detail
        ?? '浏览器任务通道初始化失败，请确认后端服务已启动',
    );
  }
  return ((body as any).data ?? body) as AuthUser;
}

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const sessionPromiseRef = useRef<Promise<AuthUser | null> | null>(null);
  const bootstrappedRef = useRef(false);

  const ensureSession = useCallback(async (): Promise<AuthUser | null> => {
    if (USE_MOCK) {
      setUser(MOCK_USER);
      setSessionError(null);
      setLoading(false);
      return MOCK_USER;
    }
    if (user) return user;
    if (sessionPromiseRef.current) return sessionPromiseRef.current;

    const request = (async () => {
      setLoading(true);
      setSessionError(null);
      try {
        const current = await fetchMe();
        const next = current ?? await createGuestSession();
        setUser(next);
        return next;
      } catch (error) {
        setUser(null);
        setSessionError(error instanceof Error ? error.message : '浏览器任务通道初始化失败');
        return null;
      } finally {
        setLoading(false);
      }
    })();

    sessionPromiseRef.current = request;
    void request.then(
      () => {
        if (sessionPromiseRef.current === request) sessionPromiseRef.current = null;
      },
      () => {
        if (sessionPromiseRef.current === request) sessionPromiseRef.current = null;
      },
    );
    return request;
  }, [user]);

  useEffect(() => {
    if (bootstrappedRef.current) return;
    bootstrappedRef.current = true;
    void ensureSession();
  }, [ensureSession]);

  const login = async (username: string, password: string) => {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error((body as any).error?.message ?? (body as any).detail ?? '登录失败');
    }
    const u = await fetchMe();
    setUser(u);
  };

  const logout = async () => {
    if (!USE_MOCK) {
      const csrf = document.cookie.match(/(?:^|; )csrf=([^;]*)/)?.[1];
      await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {},
      }).catch(() => {});
    }
    setUser(null);
    sessionPromiseRef.current = null;
  };

  return (
    <AuthContext.Provider value={{ user, loading, sessionError, ensureSession, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
