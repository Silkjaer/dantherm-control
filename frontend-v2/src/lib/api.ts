export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly endpoint?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  retries?: number;
}

function delay(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/** Resolve an app path such as "/api/auth/status" against the page instead of
 *  the host root, so the WebUI also works below a prefix like Home Assistant's
 *  ingress path. The app uses hash routing, so the page path never changes. */
export function appUrl(path: string): string {
  return path.startsWith("/") ? path.slice(1) : path;
}

let loginRedirect = false;

/** The Pi answers 401 with login_required when the session has ended, e.g. after a restart. */
function redirectToLogin() {
  if (loginRedirect || window.location.pathname.endsWith("/login")) return;
  loginRedirect = true;
  window.location.assign(appUrl("/login"));
}

export async function requestJson<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 4000, retries = 0, ...init } = options;
  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(appUrl(endpoint), {
        cache: "no-store",
        credentials: "same-origin",
        ...init,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...init.headers,
        },
      });
      const raw = await response.text();
      let payload: unknown = null;
      if (raw) {
        try { payload = JSON.parse(raw); }
        catch {
          if (response.ok) throw new ApiError("Ugyldigt JSON-svar", response.status, endpoint);
        }
      }
      if (!response.ok) {
        if (response.status === 401 && payload && typeof payload === "object" && (payload as { login_required?: unknown }).login_required === true) {
          redirectToLogin();
        }
        const message = payload && typeof payload === "object" && "error" in payload
          ? String((payload as { error?: unknown }).error || `HTTP ${response.status}`)
          : `HTTP ${response.status}`;
        throw new ApiError(message, response.status, endpoint);
      }
      return payload as T;
    } catch (error) {
      lastError = error;
      if (attempt < retries) await delay(180 * (attempt + 1));
    } finally {
      window.clearTimeout(timer);
    }
  }

  if (lastError instanceof ApiError) throw lastError;
  if (lastError instanceof DOMException && lastError.name === "AbortError") {
    throw new ApiError("Timeout", undefined, endpoint);
  }
  throw new ApiError(lastError instanceof Error ? lastError.message : "Ukendt netværksfejl", undefined, endpoint);
}

export function postJson<T>(endpoint: string, body: unknown, csrf?: string): Promise<T> {
  return requestJson<T>(endpoint, {
    method: "POST",
    timeoutMs: 5000,
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: JSON.stringify(body),
  });
}
