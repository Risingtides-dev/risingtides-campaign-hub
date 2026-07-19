import { describe, expect, it } from 'vitest'
import { keys } from '@/lib/queries'

describe('query key factory', () => {
  it('static keys are stable arrays', () => {
    expect(keys.campaigns).toEqual(['campaigns'])
    expect(keys.creators).toEqual(['creators'])
    expect(keys.internalCreators).toEqual(['internal', 'creators'])
    expect(keys.scrapeTaskHealth).toEqual(['scrape-tasks', 'health'])
  })

  it('campaign(slug) returns a unique tuple per slug', () => {
    expect(keys.campaign('a')).toEqual(['campaign', 'a'])
    expect(keys.campaign('b')).toEqual(['campaign', 'b'])
  })

  it('nested keys share the parent prefix', () => {
    expect(keys.campaignLinks('x')).toEqual(['campaign', 'x', 'links'])
    expect(keys.cobrandStats('x')).toEqual(['campaign', 'x', 'cobrand'])
  })

  it('inbox key falls back to "all" when status omitted', () => {
    expect(keys.inbox()).toEqual(['inbox', 'all'])
    expect(keys.inbox('pending')).toEqual(['inbox', 'pending'])
  })

  it('scrapeTaskQueue key normalizes missing params to empty strings', () => {
    expect(keys.scrapeTaskQueue()).toEqual([
      'scrape-tasks',
      'queue',
      '',
      '',
    ])
    expect(keys.scrapeTaskQueue({ campaign: 'a' })).toEqual([
      'scrape-tasks',
      'queue',
      'a',
      '',
    ])
    expect(keys.scrapeTaskQueue({ campaign: 'a', since: '2026-01-01' })).toEqual(
      ['scrape-tasks', 'queue', 'a', '2026-01-01'],
    )
  })

  it('internalGroup keys are distinct from internalGroupStats', () => {
    expect(keys.internalGroup('g')).not.toEqual(keys.internalGroupStats('g', 30))
  })
})
