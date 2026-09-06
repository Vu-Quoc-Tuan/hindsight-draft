import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AnalysisSettingsModal } from './AnalysisSettingsModal'

describe('AnalysisSettingsModal', () => {
  it('does not render when isOpen is false', () => {
    const html = renderToStaticMarkup(
      <AnalysisSettingsModal isOpen={false} onClose={() => {}} onConfigChanged={() => {}} />
    )
    expect(html).toBe('')
  })

  it('renders modal structure with settings when isOpen is true', () => {
    const html = renderToStaticMarkup(
      <AnalysisSettingsModal isOpen={true} onClose={() => {}} onConfigChanged={() => {}} />
    )
    expect(html).toContain('Analysis Settings')
    expect(html).toContain('Provenance &amp; Reproducibility')
    expect(html).toContain('System Capabilities &amp; Engine Runtime')
    expect(html).toContain('Temporal Proximity')
    expect(html).toContain('Pattern Memory')
    expect(html).toContain('Reset to Default')
    expect(html).toContain('Calibrate from PostgreSQL')
    expect(html).toContain('Save Changes')
  })
})
