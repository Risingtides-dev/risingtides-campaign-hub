import { describe, expect, it } from 'vitest'
import { cn } from '@/lib/utils'

describe('cn', () => {
  it('joins string class names', () => {
    expect(cn('a', 'b')).toBe('a b')
  })

  it('drops falsy values', () => {
    expect(cn('a', false && 'never', null, undefined, 'b')).toBe('a b')
  })

  it('merges tailwind class conflicts so the last wins', () => {
    // tailwind-merge collapses conflicting utilities — only p-4 should remain.
    expect(cn('p-2', 'p-4')).toBe('p-4')
  })

  it('handles object syntax via clsx', () => {
    expect(cn({ a: true, b: false, c: true })).toBe('a c')
  })

  it('handles array syntax via clsx', () => {
    expect(cn(['a', 'b'], 'c')).toBe('a b c')
  })

  it('returns empty string for no inputs', () => {
    expect(cn()).toBe('')
  })
})
