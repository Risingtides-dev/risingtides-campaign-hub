declare const process: { env: Record<string, string | undefined> }
process.env.TZ = 'Pacific/Auckland'

import { describe, expect, it } from 'vitest'
import { localTickDate } from '../chartDate'

describe('local chart tick dates in Auckland', () => {
  it('formats a local-midnight timestamp from local calendar fields', () => {
    const localMidnight = new Date(2026, 7, 20).getTime()
    expect(localTickDate(localMidnight)).toBe('08-20')
  })
})
