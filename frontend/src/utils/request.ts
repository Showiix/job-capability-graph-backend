import axios from 'axios';
import type { AxiosInstance, AxiosRequestConfig, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { API_BASE_URL } from '../services/apiBase';

// Use mock for graph/static data; real backend for auth + business flows
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

// API base URL
const BASE_URL = API_BASE_URL;

// URLs that always use mock static files regardless of USE_MOCK flag
// Empty array when USE_MOCK is false to allow all requests to hit real backend
const ALWAYS_MOCK_PREFIXES = USE_MOCK ? ['/api/graph', '/api/resume', '/api/jd', '/api/match'] : [];

// URLs that always bypass mock and hit the real backend (auth, admin api v1)
const NEVER_MOCK_PREFIXES = ['/api/v1/'];

const WRITE_METHODS = new Set(['post', 'put', 'patch', 'delete']);

// Debug logging
console.log('[Request] Configuration:', {
  USE_MOCK,
  BASE_URL,
  ALWAYS_MOCK_PREFIXES,
  VITE_USE_MOCK: import.meta.env.VITE_USE_MOCK,
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
});

/** Read a cookie value by name (CSRF token is stored in a non-HttpOnly cookie). */
function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

function shouldUseMock(url: string): boolean {
  if (NEVER_MOCK_PREFIXES.some((p) => url.startsWith(p))) return false;
  if (USE_MOCK) return true;
  return ALWAYS_MOCK_PREFIXES.some((p) => url.startsWith(p));
}

class Request {
  private instance: AxiosInstance;

  constructor() {
    this.instance = axios.create({
      baseURL: BASE_URL,
      timeout: 30000,
      withCredentials: true, // send session cookies on every request
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor
    this.instance.interceptors.request.use(
      (config: InternalAxiosRequestConfig) => {
        const url = config.url ?? '';

        if (shouldUseMock(url)) {
          // Rewrite to local static JSON mock
          config.url = `/mock${url}.json`;
          config.baseURL = '';
          config.method = 'get';
          config.data = undefined;
          return config;
        }

        // Real backend: inject CSRF token for write methods
        const method = (config.method ?? 'get').toLowerCase();
        if (WRITE_METHODS.has(method)) {
          const csrf = getCookie('csrf');
          if (csrf) {
            config.headers['X-CSRF-Token'] = csrf;
          }
        }

        return config;
      },
      (error) => Promise.reject(error),
    );

    // Response interceptor
    this.instance.interceptors.response.use(
      (response: AxiosResponse) => {
        // Mock files use a {code, data, message} envelope we created
        const url = response.config.url ?? '';
        if (url.startsWith('/mock/')) {
          const { code, data, message } = response.data;
          if (code === 200) return data;
          return Promise.reject(new Error(message ?? '请求失败'));
        }
        // Real backend: most api/v1 routes return a { data } envelope.
        const body = response.data;
        if (body && typeof body === 'object' && Object.prototype.hasOwnProperty.call(body, 'data')) {
          return body.data;
        }
        return body;
      },
      (error) => {
        const status = error.response?.status;
        const body = error.response?.data;
        const detail = body?.detail;
        const apiError = body?.error;

        // Removed 401 redirect logic - no authentication required

        const message =
          typeof apiError?.message === 'string'
            ? apiError.message
            : typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((d: any) => d.msg).join('; ')
              : error.message;

        console.error(`[API ${status ?? 'ERR'}]`, message);
        return Promise.reject(Object.assign(error, { apiMessage: message, apiCode: apiError?.code }));
      },
    );
  }

  get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.get(url, config);
  }

  post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.post(url, data, config);
  }

  put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.put(url, data, config);
  }

  patch<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.patch(url, data, config);
  }

  upload<T = any>(url: string, formData: FormData, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.post(url, formData, {
      ...config,
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  }
}

export default new Request();
