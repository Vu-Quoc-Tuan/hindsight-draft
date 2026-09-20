import type { AnalysisConfigView } from './types'
import { LearningModal } from './components/LearningModal'

export interface AnalysisSettingsModalProps {
  isOpen: boolean
  onClose: () => void
  onConfigChanged: (config: AnalysisConfigView) => void
}

export function AnalysisSettingsModal({
  isOpen,
  onClose,
  onConfigChanged,
}: AnalysisSettingsModalProps) {
  return (
    <LearningModal
      isOpen={isOpen}
      onClose={onClose}
      defaultTab="engine"
      onConfigChanged={onConfigChanged}
    />
  )
}
