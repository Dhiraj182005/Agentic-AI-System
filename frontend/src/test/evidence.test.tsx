import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import EvidenceSources from '../components/EvidenceSources'
import type { EvidenceItem } from '../services/claims'

const published: EvidenceItem = {
  id: 'e1', claim_id: 'c1', title: 'Published review', url: 'https://publisher.example/review',
  snippet: 'Reviewed statement', source_name: 'publisher.example', relevance_score: .8,
  retrieved_at: '2026-11-03T10:00:00Z', source_type: 'google_fact_check',
  publisher: 'Original Publisher', external_rating: 'Mostly True',
  review_date: '2026-10-01T00:00:00Z', claim_reviewed: 'The original reviewed statement.', claimant: null,
}

describe('published evidence attribution', () => {
  it('keeps publisher rating separate from MAVES verification', () => {
    render(<EvidenceSources items={[published]} factCheckStatus="matched" verification={undefined} />)
    expect(screen.getByText(/Mostly True/)).toBeInTheDocument()
    expect(screen.getByText(/Original Publisher/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Published review' })).toHaveAttribute('href', published.url)
    expect(screen.getByTestId('maves-status')).toHaveTextContent(/not verified/i)
  })
  it('reports no match without assigning false', () => {
    render(<EvidenceSources items={[]} factCheckStatus="no_match" verification={undefined} />)
    expect(screen.getByText('No matching published fact-check found.')).toBeInTheDocument()
    expect(screen.getByTestId('maves-status')).toHaveTextContent(/not verified/i)
  })
  it('continues to display web sources when Google fails', () => {
    render(<EvidenceSources items={[{ ...published, id: 'web1', source_type: 'web', title: 'Web source' }]}
      factCheckStatus="failed" verification={undefined} />)
    expect(screen.getByRole('link', { name: 'Web source' })).toBeInTheDocument()
    expect(screen.getByText(/Published fact-check search failed/)).toBeInTheDocument()
  })
  it('handles missing publisher review fields', () => {
    render(<EvidenceSources items={[{ ...published, publisher: null, external_rating: null, review_date: null, claim_reviewed: null }]}
      factCheckStatus="matched" verification={undefined} />)
    expect(screen.getByRole('link', { name: 'Published review' })).toBeInTheDocument()
  })
})
