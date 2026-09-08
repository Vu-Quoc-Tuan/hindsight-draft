import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'

interface InfoTipProps {
  text: string
  className?: string
}

/**
 * Clean compact `?` icon with fixed-position portal popover.
 * Completely immune to container clipping/overflow and has NO native title attribute.
 */
export function InfoTip({ text, className = '' }: InfoTipProps) {
  const [visible, setVisible] = useState(false)
  const [coords, setCoords] = useState<{ top: number; left: number; above: boolean }>({
    top: 0,
    left: 0,
    above: true,
  })
  const triggerRef = useRef<HTMLSpanElement>(null)

  const updatePosition = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      // If there's enough space above the trigger (at least 100px from window top), show above
      const showAbove = rect.top > 110
      const tipWidth = 260
      const centerLeft = rect.left + rect.width / 2 - tipWidth / 2
      const clampedLeft = Math.max(12, Math.min(window.innerWidth - tipWidth - 12, centerLeft))

      setCoords({
        top: showAbove ? rect.top - 10 : rect.bottom + 10,
        left: clampedLeft,
        above: showAbove,
      })
    }
  }

  const handleMouseEnter = () => {
    updatePosition()
    setVisible(true)
  }

  const handleMouseLeave = () => {
    setVisible(false)
  }

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!visible) {
      updatePosition()
      setVisible(true)
    } else {
      setVisible(false)
    }
  }

  // Close on Escape or scroll
  useEffect(() => {
    if (!visible) return
    const handleScrollOrEsc = (e: Event) => {
      if (e.type === 'scroll' || (e instanceof KeyboardEvent && e.key === 'Escape')) {
        setVisible(false)
      }
    }
    window.addEventListener('scroll', handleScrollOrEsc, true)
    window.addEventListener('keydown', handleScrollOrEsc)
    return () => {
      window.removeEventListener('scroll', handleScrollOrEsc, true)
      window.removeEventListener('keydown', handleScrollOrEsc)
    }
  }, [visible])

  return (
    <span
      ref={triggerRef}
      className={`inline-flex items-center align-middle ${className}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      aria-label={text}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleClick(e as unknown as React.MouseEvent)
        }
      }}
    >
      <span className="w-3.5 h-3.5 rounded-full bg-surface-container-highest/80 text-on-surface-variant flex items-center justify-center text-[10px] font-bold cursor-help select-none hover:bg-secondary/20 hover:text-secondary border border-transparent hover:border-secondary/40 transition-colors">
        ?
      </span>
      {visible &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            style={{
              position: 'fixed',
              top: `${coords.top}px`,
              left: `${coords.left}px`,
              transform: coords.above ? 'translateY(-100%)' : 'none',
            }}
            className="w-[260px] p-2.5 bg-[#0b1322]/95 backdrop-blur-md text-[#e2e8f0] text-[11px] font-body-sm rounded-lg shadow-2xl border border-secondary/40 z-[999999] leading-relaxed pointer-events-none animate-fadeIn whitespace-normal break-words text-left"
          >
            <div className="flex items-start gap-1.5">
              <span className="material-symbols-outlined text-secondary text-[14px] shrink-0 mt-0.5">
                info
              </span>
              <p className="m-0 leading-normal">{text}</p>
            </div>
          </div>,
          document.body
        )}
    </span>
  )
}
