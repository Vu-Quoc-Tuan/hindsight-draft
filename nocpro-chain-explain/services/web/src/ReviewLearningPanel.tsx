import { LearningModal } from './components/LearningModal'

interface ReviewLearningPanelProps {
  open: boolean
  onClose: () => void
}

export function ReviewLearningPanel({ open, onClose }: ReviewLearningPanelProps) {
  return (
    <LearningModal
      isOpen={open}
      onClose={onClose}
      defaultTab="ranker"
    />
  )
}
