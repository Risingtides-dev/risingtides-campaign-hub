import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatCards } from '@/components/campaigns/StatCards'

const baseBudget = {
  total: 10000,
  booked: 4500,
  paid: 2000,
  left: 5500,
  pct: 45,
}

const baseStats = {
  live_posts: 7,
  total_views: 123456,
  cpm: 3.5,
}

describe('<StatCards />', () => {
  it('renders all five stat cards', () => {
    render(<StatCards budget={baseBudget} stats={baseStats} />)
    for (const label of ['Budget Used', 'Paid Out', 'Live Posts', 'Total Views', 'CPM']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('formats budget values with locale separators and dollar signs', () => {
    render(<StatCards budget={baseBudget} stats={baseStats} />)
    expect(screen.getByText('$4,500')).toBeInTheDocument()
    expect(screen.getByText('45% of $10,000')).toBeInTheDocument()
    expect(screen.getByText('$2,000')).toBeInTheDocument()
    expect(screen.getByText('$5,500 remaining')).toBeInTheDocument()
  })

  it('formats view count with thousands separators', () => {
    render(<StatCards budget={baseBudget} stats={baseStats} />)
    expect(screen.getByText('123,456')).toBeInTheDocument()
  })

  it('formats CPM with two decimals and dollar sign', () => {
    render(<StatCards budget={baseBudget} stats={baseStats} />)
    expect(screen.getByText('$3.50')).toBeInTheDocument()
  })

  it('shows "-" when total views is 0', () => {
    render(
      <StatCards budget={baseBudget} stats={{ ...baseStats, total_views: 0 }} />,
    )
    // Two cards may show "-" (views, cpm). Look for at least one "-".
    expect(screen.getAllByText('-').length).toBeGreaterThanOrEqual(1)
  })

  it('shows "-" when CPM is null', () => {
    render(
      <StatCards budget={baseBudget} stats={{ ...baseStats, cpm: null }} />,
    )
    expect(screen.getAllByText('-').length).toBeGreaterThanOrEqual(1)
  })

  it('renders live posts as a string', () => {
    render(<StatCards budget={baseBudget} stats={baseStats} />)
    expect(screen.getByText('7')).toBeInTheDocument()
  })
})
