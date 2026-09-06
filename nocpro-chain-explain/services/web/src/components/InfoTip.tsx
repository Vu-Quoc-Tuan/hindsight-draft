import { useState } from 'react'

interface InfoTipProps {
  text: string
  className?: string
}

/**
 * Clean compact `?` icon with hover/click tooltip popover.
 */
export function InfoTip({ text, className = '' }: InfoTipProps) {
  const [visible, setVisible] = useState(false)

  return (
    <span
      className={`relative inline-flex items-center ${className}`}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onClick={(e) => {
        e.stopPropagation()
        setVisible((v) => !v)
      }}
    >
      <span
        className="w-3.5 h-3.5 rounded-full bg-surface-container-highest/80 text-on-surface-variant flex items-center justify-center text-[10px] font-bold cursor-help select-none hover:bg-secondary/20 hover:text-secondary transition-colors"
        title="Bấm hoặc di chuột để xem giải thích chi tiết"
      >
        ?
      </span>
      {visible && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 max-w-xs px-3 py-2 bg-surface-container-highest text-on-surface text-[11px] font-body-sm rounded-md shadow-xl border border-secondary/30 z-50 leading-relaxed pointer-events-none animate-fadeIn whitespace-normal break-words text-left">
          {text}
        </span>
      )}
    </span>
  )
}
