import { describe, it, expect } from 'vitest'
import { cn } from './utils'

describe('cn', () => {
  it('joins string class names', () => {
    expect(cn('a', 'b')).toBe('a b')
  })

  it('drops falsy entries', () => {
    expect(cn('a', false, null, undefined, '', 'b')).toBe('a b')
  })

  it('lets later tailwind classes override earlier ones', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })
})
