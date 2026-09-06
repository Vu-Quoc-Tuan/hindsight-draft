import { useState } from 'react'
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
  const [activeTab, setActiveTab] = useState<'INTERACTIVE' | 'SYNTHESIS'>('INTERACTIVE')

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm animate-fadeIn">
      {/* Backdrop close area */}
      <div className="flex-1" onClick={onClose}></div>

      {/* Drawer Container */}
      <div className="w-full max-w-xl bg-surface-container-lowest/95 backdrop-blur-xl border-l border-surface-container-highest shadow-2xl flex flex-col justify-between overflow-hidden h-full z-10 animate-slideLeft">
        {/* Drawer Header */}
        <div className="p-space-md bg-surface-container-low flex flex-col gap-space-xs border-b border-surface-container-highest">
          <div className="flex items-center justify-between">
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

          {/* Telemetry Status Badges */}
          <div className="flex items-center justify-between pt-space-2xs">
            <div className="flex items-center gap-space-xs">
              <div className="w-2 h-2 rounded-full bg-secondary animate-pulse"></div>
              <span className="font-code-sm text-code-sm text-secondary font-semibold">
                Streaming Grounded Engine (18ms)
              </span>
            </div>
            <span className="font-code-sm text-code-sm text-on-surface-variant font-mono">
              model: hindsight-v1
            </span>
          </div>

          {/* Mode Switcher */}
          <div className="flex items-center bg-surface-container-lowest p-space-2xs rounded mt-space-xs">
            <button
              onClick={() => setActiveTab('INTERACTIVE')}
              className={`flex-1 py-1 text-center font-code-sm text-code-sm rounded transition-colors ${
                activeTab === 'INTERACTIVE'
                  ? 'bg-secondary-container text-on-secondary-container font-bold'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Query Assistant
            </button>
            <button
              onClick={() => setActiveTab('SYNTHESIS')}
              className={`flex-1 py-1 text-center font-code-sm text-code-sm rounded transition-colors ${
                activeTab === 'SYNTHESIS'
                  ? 'bg-secondary-container text-on-secondary-container font-bold'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Incident Synthesis
            </button>
          </div>
        </div>

        {/* Drawer Body */}
        <div className="p-space-lg flex-1 overflow-y-auto flex flex-col gap-space-md">
          {activeTab === 'INTERACTIVE' ? (
            <NocProAssistantPanel context={context} onNavigate={onNavigate} />
          ) : (
            <div className="flex flex-col gap-space-md font-body-sm text-body-sm">
              {/* Operator Query Example Bubble */}
              <div className="p-space-md bg-surface-container-high rounded-lg flex flex-col gap-space-2xs">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-space-xs">
                    <span className="material-symbols-outlined text-secondary text-[16px]">account_circle</span>
                    <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">
                      OPERATOR CONTEXT
                    </span>
                  </div>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">Chain: {context.chain_id}</span>
                </div>
                <p className="font-body-md text-body-md text-on-surface font-medium">
                  “Giải thích tại sao cụm 5 cảnh báo tại trạm DEHT01 nên được tách khỏi chuỗi sự cố chính C2214039?”
                </p>
              </div>

              {/* Rich Synthesis Breakdown */}
              <div className="flex flex-col gap-space-xs bg-surface-container rounded-lg p-space-md">
                <div className="flex items-center gap-space-xs">
                  <span className="px-space-xs py-space-2xs bg-secondary-container/20 text-secondary font-label-caps text-label-caps uppercase font-bold rounded">
                    1
                  </span>
                  <span className="font-headline-md text-body-md font-bold text-on-surface">
                    Phân hoạch Phổ Laplacian (Spectral Bottleneck)
                  </span>
                </div>
                <p className="text-on-surface-variant">
                  Chỉ số dẫn truyền vết cắt (Cut Conductance) giữa cụm DEHL01 và DEHT01 đạt <code className="text-secondary font-code-sm bg-surface-container-lowest px-1 rounded">Φ = 0.038</code>, thấp hơn nhiều so với ngưỡng đồng nhất 0.20. Điều này chỉ ra rằng 5 cảnh báo tại DEHT01 liên kết với chuỗi chính chỉ qua một liên kết yếu (Weak Cut Boundary).
                </p>
              </div>

              <div className="flex flex-col gap-space-xs bg-surface-container rounded-lg p-space-md">
                <div className="flex items-center gap-space-xs">
                  <span className="px-space-xs py-space-2xs bg-secondary-container/20 text-secondary font-label-caps text-label-caps uppercase font-bold rounded">
                    2
                  </span>
                  <span className="font-headline-md text-body-md font-bold text-on-surface">
                    Độ trễ thời gian bất đối xứng (T_delay Violated)
                  </span>
                </div>
                <p className="text-on-surface-variant">
                  Cảnh báo tại DEHT01 xuất hiện sau T0 tới +4.10s, vượt quá cửa sổ lan truyền trực tiếp 2.5s từ DWDM transponder. Đây là tín hiệu phản xạ (secondary symptom), không phải nguyên nhân trực tiếp.
                </p>
              </div>

              <div className="p-space-sm bg-primary-container/10 border border-primary-container/30 rounded-lg flex items-center justify-between">
                <div className="flex items-center gap-space-xs">
                  <span className="material-symbols-outlined text-primary text-[18px]">alt_route</span>
                  <span className="font-code-sm text-code-sm text-primary font-bold">
                    Khuyến nghị: SPLIT_SUBCHAIN_01 (Tách chuỗi con)
                  </span>
                </div>
                <button
                  onClick={() =>
                    onNavigate({
                      kind: 'NAVIGATE',
                      label: 'Mở Audit',
                      target: {
                        snapshot_id: context.snapshot_id,
                        snapshot_version: context.snapshot_version,
                        chain_id: context.chain_id,
                        tab: 'structure',
                      },
                    })
                  }
                  className="px-space-sm py-1 bg-primary text-on-primary text-code-sm rounded font-semibold"
                >
                  Mở Audit
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
