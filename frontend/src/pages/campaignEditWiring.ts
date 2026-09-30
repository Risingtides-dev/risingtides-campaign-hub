type EditMutation = {
  mutateAsync: (data: Record<string, unknown>) => Promise<unknown>
  isError: boolean
  error?: { message?: string } | null
  isPending: boolean
  reset: () => void
}

export function campaignEditWiring(mutation: EditMutation) {
  return {
    onEdit: (data: Record<string, unknown>) => mutation.mutateAsync(data),
    editError: mutation.isError ? (mutation.error?.message || "Failed to save campaign") : undefined,
    isEditing: mutation.isPending,
    onResetEdit: () => mutation.reset(),
  }
}
