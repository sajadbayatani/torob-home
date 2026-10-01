/**
 * The single place where the app talks HTTP.
 * Components and stores must never call `fetch` themselves.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function buildUrl(path: string, params?: Record<string, unknown>): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function request<T>(path: string, init?: RequestInit & { params?: Record<string, unknown> }): Promise<T> {
  const { params, ...rest } = init ?? {}
  let response: Response
  try {
    response = await fetch(buildUrl(path, params), {
      headers: { 'Content-Type': 'application/json', ...(rest.headers ?? {}) },
      ...rest,
    })
  } catch {
    // product copy: say what failed and what the user can do next
    throw new ApiError('اتصال به سرور برقرار نشد. اینترنت یا سرویس را بررسی کنید و دوباره تلاش کنید.', 0)
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const body = text ? safeParse(text) : null

  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : 'این درخواست انجام نشد. چند لحظه بعد دوباره تلاش کنید.'
    throw new ApiError(message, response.status, body)
  }
  return body as T
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export const http = {
  get: <T>(path: string, params?: Record<string, unknown>) => request<T>(path, { method: 'GET', params }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export { BASE_URL }
