import type { AssistantAction, AssistantContext } from '../types'
import { NocProAssistantPanel } from '../NocProAssistantPanel'

interface AIAnalystDrawerProps {
  isOpen: boolean
  onClose: () => void
  onOpen?: () => void
  context: AssistantContext
  onNavigate: (action: AssistantAction) => void
}

export function AIAnalystDrawer({
  isOpen,
  onClose,
  onOpen,
  context,
  onNavigate,
}: AIAnalystDrawerProps) {
  if (!isOpen) {
    return (
      <button
        onClick={onOpen}
        className="fixed bottom-5 right-6 z-40 w-12 h-12 rounded-full bg-gradient-to-tr from-primary to-secondary text-white shadow-[0_4px_20px_rgba(249,115,22,0.45)] hover:shadow-[0_6px_25px_rgba(249,115,22,0.65)] hover:scale-105 active:scale-95 transition-all flex items-center justify-center cursor-pointer group"
        title="Mở chat AI Analyst (NocPro Assistant)"
        aria-label="NocPro Assistant"
      >
        <span className="material-symbols-outlined text-[22px]">chat</span>
        <span className="absolute top-0 right-0 w-3 h-3 rounded-full bg-emerald-400 ring-2 ring-background animate-pulse" />
      </button>
    )
  }

  return (
    <div
      style={{ backgroundColor: '#0c1322' }}
      className="fixed bottom-5 right-6 z-50 w-[380px] max-w-[calc(100vw-32px)] h-[540px] max-h-[calc(100vh-90px)] rounded-2xl border border-surface-container-highest shadow-[0_16px_48px_rgba(0,0,0,0.95)] flex flex-col overflow-hidden animate-slideUp text-on-surface"
    >
      {/* Top Window Control Bar (Facebook Messenger Style) */}
      <div className="px-3 py-1.5 bg-surface-container-low border-b border-surface-container-highest flex items-center justify-between select-none">
        <div className="flex items-center gap-1.5 text-xs text-on-surface-variant font-medium">
          <span className="material-symbols-outlined text-[15px] text-secondary">forum</span>
          <span>NocPro AI Messenger</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onClose}
            className="w-6 h-6 rounded flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors cursor-pointer"
            title="Thu nhỏ / Đóng"
            aria-label="Đóng chat"
          >
            <span className="material-symbols-outlined text-[16px]">close</span>
          </button>
        </div>
      </div>

      {/* Main Chat Body */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <NocProAssistantPanel context={context} onNavigate={onNavigate} />
      </div>
    </div>
  )
}
