import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"

type SessionScope = { id: string; isActive: () => boolean }
const PayoutSessionContext = createContext<SessionScope | null>(null)

export function PayoutSessionProvider({ sessionId, isActive, children }: {
  sessionId: string
  isActive?: () => boolean
  children: ReactNode
}) {
  const scope = useMemo(() => ({ id: sessionId, isActive: isActive ?? (() => true) }), [sessionId, isActive])
  return createElement(PayoutSessionContext.Provider, { value: scope }, children)
}

/** Cache identities never contain the credential used to authorize a request. */
export function usePayoutSessionPrefix(): readonly ["payouts", string] {
  const scope = useContext(PayoutSessionContext)
  const [standaloneId] = useState(() => crypto.randomUUID())
  return useMemo(() => ["payouts", scope?.id ?? standaloneId] as const, [scope?.id, standaloneId])
}

/** Ignore asynchronous UI effects after locking or unmounting the session. */
export function usePayoutSessionIsActive(): () => boolean {
  const scope = useContext(PayoutSessionContext)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  return useCallback(() => mounted.current && (scope?.isActive() ?? true), [scope])
}
