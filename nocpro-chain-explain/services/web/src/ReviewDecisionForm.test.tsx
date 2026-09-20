import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ReviewDecisionForm } from './components/ReviewDecisionForm'
import { SimilarReviewCases } from './components/SimilarReviewCases'

describe('ReviewDecisionForm', () => {
  it('renders all 6 review decisions and zero mutation notice', () => {
    const html = renderToStaticMarkup(
      <ReviewDecisionForm
        jobId="job_123"
        chainId="C1"
        candidateId="cand_abc"
        onFeedbackSaved={() => {}}
      />
    )

    // Check decisions rendered
    expect(html).toContain('Approve')
    expect(html).toContain('Reject')
    expect(html).not.toContain('Insufficient Evidence')

    // Check Zero-Mutation Safe Mode
    expect(html).toContain('Zero-Mutation Safe Mode')
    expect(html).not.toContain('PO_ASSERTED')
    expect(html).toContain('Decision Confidence: 100%')
    expect(html).toContain('Record Review Feedback')
  })

  it('renders existing feedback when provided', () => {
    const html = renderToStaticMarkup(
      <ReviewDecisionForm
        jobId="job_123"
        chainId="C1"
        candidateId="cand_abc"
        existingFeedback={{
          feedback_id: 'fb_existing_123',
          job_id: 'job_123',
          chain_id: 'C1',
          candidate_id: 'cand_abc',
          operation: 'MOVE_MEMBER',
          decision: 'APPROVE',
          operator_id: 'test_reviewer',
          confidence: 0.95,
          reason: 'Verified topological boundary',
          created_at: '2026-09-11T08:00:00Z',
        }}
        onFeedbackSaved={() => {}}
      />
    )

    expect(html).toContain('Active Feedback on this Candidate: APPROVE')
    expect(html).toContain('test_reviewer')
    expect(html).toContain('Supersede')
    expect(html).toContain('Retract')
  })
})

describe('SimilarReviewCases', () => {
  it('renders disclaimer and multi-block header', () => {
    const html = renderToStaticMarkup(
      <SimilarReviewCases
        jobId="job_123"
        candidateId="cand_abc"
      />
    )

    expect(html).toContain('Historical Similar Cases (Multi-Block)')
    expect(html).toContain('Historical reference only — not probability or automated recommendation')
  })
})
