import type { AssistantAction, AssistantContext } from '../types'
import { NocProAssistantPanel } from '../NocProAssistantPanel'

interface AIAnalystDrawerProps {
  isOpen: boolean
  onClose: () => void
  context: AssistantContext
  onNavigate: (action: AssistantAction) => void
}

export function AIAnalystDrawer({
  isOpen,
  onClose,
  context,
  onNavigate,
}: AIAnalystDrawerProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm animate-fadeIn">
      {/* Backdrop close area */}
      <div className="flex-1" onClick={onClose}></div>

      {/* Drawer Container */}
      <div className="w-full max-w-xl bg-surface-container-lowest/95 backdrop-blur-xl border-l border-surface-container-highest shadow-2xl flex flex-col justify-between overflow-hidden h-full z-10 animate-slideLeft">
        {/* Drawer Header */}
        <div className="p-space-md bg-surface-container-low flex items-center justify-between border-b border-surface-container-highest">
          <div className="flex items-center gap-space-xs">
            <span className="text-secondary font-bold text-lg">✦</span>
            <span className="font-headline-md text-headline-md font-bold text-on-surface">
              AI Analyst
            </span>
            <span className="px-space-xs py-space-2xs bg-surface-container-highest text-secondary rounded font-label-caps text-label-caps uppercase font-bold">
              Hindsight Co-Pilot
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-on-surface transition-colors p-space-2xs rounded hover:bg-surface-container cursor-pointer"
            type="button"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {/* Chatbot Body — single panel, no tabs */}
        <div className="p-space-lg flex-1 overflow-y-auto flex flex-col gap-space-md">
          <NocProAssistantPanel context={context} onNavigate={onNavigate} />
        </div>
      </div>
    </div>
  )
}
