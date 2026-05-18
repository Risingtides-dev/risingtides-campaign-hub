import { Toaster as SonnerToaster } from "sonner"

/**
 * Thin wrapper around sonner's <Toaster /> with project defaults.
 * Mount once at the app shell (Layout.tsx).
 *
 * - position: top-right keeps toasts out of the way of inline progress strips
 * - richColors enables success/error/info color treatments
 * - closeButton lets users dismiss long toasts manually
 */
export function Toaster() {
  return (
    <SonnerToaster
      position="top-right"
      richColors
      closeButton
      duration={4000}
    />
  )
}
