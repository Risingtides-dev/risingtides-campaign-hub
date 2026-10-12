// ---- API client ----

// Operator cookies are same-origin. Vite proxies this path in local development.
const API_BASE = ""

let operatorCsrf = ""

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase()
  const headers = new Headers(init?.headers)
  headers.set("Content-Type", "application/json")
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", operatorCsrf)
  const res = await fetch(`${API_BASE}/api/sound-assignments${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
  })
  if (res.status === 401) {
    operatorCsrf = ""
    window.dispatchEvent(new Event("sound-operator-expired"))
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || body.error || `Request failed (${res.status})`)
  }
  return res.json()
}

export async function operatorSession(): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/sound-assignments/session`, { credentials: "same-origin" })
  if (res.status === 401) return false
  if (!res.ok) throw new Error(`Operator session unavailable (${res.status})`)
  const body = await res.json()
  operatorCsrf = body.csrf_token
  return true
}

export async function operatorLogin(password: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sound-assignments/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
    credentials: "same-origin",
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Login failed (${res.status})`)
  }
  const body = await res.json()
  operatorCsrf = body.csrf_token
}
