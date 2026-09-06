import { useState } from 'react'

interface OperatorValidationModalProps {
  isOpen: boolean
  onClose: () => void
  chainId: string
  onConfirmSignOff: (note: string) => void
}

export function OperatorValidationModal({
  isOpen,
  onClose,
  chainId,
  onConfirmSignOff,
}: OperatorValidationModalProps) {
  const [operatorNote, setOperatorNote] = useState(
    'Xác nhận tách nhánh đo nhiệt độ và flap phụ trợ sang trạm DEHT01 để tập trung xử lý đứt cáp quang chính tại DEHL01. Giữ nguyên gốc sự cố tại DEHL01-CR01.'
  )
  const [signed, setSigned] = useState(false)

  if (!isOpen) return null

  const handleSignOff = () => {
    setSigned(true)
    setTimeout(() => {
      onConfirmSignOff(operatorNote)
      onClose()
    }, 800)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-space-md animate-fadeIn select-none">
      <div className="w-full max-w-2xl bg-surface-container-lowest/95 backdrop-blur-xl border border-surface-container-highest rounded-xl shadow-2xl p-space-xl flex flex-col gap-space-lg animate-scaleUp">
        {/* Modal Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-space-sm">
            <div className="w-10 h-10 rounded-lg bg-tertiary/15 flex items-center justify-center">
              <span className="material-symbols-outlined text-tertiary text-[24px]">verified_user</span>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-space-xs">
                <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold tracking-wider">
                  FAIL-CLOSED SAFEGUARD
                </span>
                <span className="px-space-2xs py-px bg-surface-container-high rounded text-on-surface-variant font-code-sm text-code-sm">
                  OP #1 REQ
                </span>
              </div>
              <span className="font-headline-lg text-headline-lg font-bold text-on-surface leading-tight">
                Phê duyệt Can thiệp Cấu trúc Chuỗi Sự cố
              </span>
              <span className="font-body-sm text-body-sm text-on-surface-variant">
                Sign-off Counterfactual Action • Chain Partition Protocol
              </span>
            </div>
          </div>
          <div className="px-space-sm py-space-2xs bg-surface-container-high rounded flex items-center gap-space-xs">
            <span className="w-2 h-2 rounded-full bg-tertiary animate-pulse"></span>
            <span className="font-code-sm text-code-sm text-on-surface font-semibold">AWAITING REVIEW</span>
          </div>
        </div>

        {/* Action Spec Badge Card */}
        <div className="bg-surface-container-low rounded-lg p-space-md flex flex-col gap-space-sm border border-surface-container-highest">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
              PROPOSED TOPOLOGY MUTATION
            </span>
            <span className="font-code-sm text-code-sm text-secondary font-mono">
              OP_ID: MUT-20260801-0941
            </span>
          </div>
          <div className="flex items-center gap-space-md p-space-xs bg-surface-container rounded">
            <div className="px-space-sm py-space-xs bg-tertiary-container/30 rounded text-tertiary font-code-md text-code-md font-bold">
              SPLIT_SUBCHAIN_01
            </div>
            <span className="material-symbols-outlined text-on-surface-variant text-[18px]">arrow_forward</span>
            <div className="flex flex-col">
              <span className="font-body-md text-body-md text-on-surface font-semibold">
                Tạo chuỗi con {chainId}_B (5 Alarms)
              </span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">
                Tách khỏi chuỗi gốc {chainId} (Còn lại 48 Alarms tại DEHL01)
              </span>
            </div>
          </div>
        </div>

        {/* Audit Guardrails Checklist */}
        <div className="flex flex-col gap-space-xs">
          <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
            BẢNG KIỂM TOÁN AN TOÀN (AUDIT GUARDRAILS CHECKLIST)
          </span>
          <div className="flex flex-col gap-space-2xs">
            <div className="flex items-center justify-between p-space-sm bg-surface-container-low rounded">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-secondary text-[18px]">check_circle</span>
                <span className="font-body-sm text-body-sm text-on-surface">
                  Không ảnh hưởng đến P1 SLA Tickets đang mở (Verified)
                </span>
              </div>
              <span className="font-code-sm text-code-sm text-secondary font-mono font-bold">STATUS: PASS</span>
            </div>
            <div className="flex items-center justify-between p-space-sm bg-surface-container-low rounded">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-secondary text-[18px]">check_circle</span>
                <div className="flex flex-col">
                  <span className="font-body-sm text-body-sm text-on-surface">
                    Audit hash SHA-256 xác thực bất biến
                  </span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant font-mono">
                    sha256:d8a94bc109fe29bf8a00293cd1...44f
                  </span>
                </div>
              </div>
              <span className="font-code-sm text-code-sm text-secondary font-mono font-bold">IMMUTABLE</span>
            </div>
            <div className="flex items-center justify-between p-space-sm bg-surface-container-low rounded">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-secondary text-[18px]">check_circle</span>
                <span className="font-body-sm text-body-sm text-on-surface">
                  Phục hồi nguyên trạng được trong 30 phút (Reversible staging active)
                </span>
              </div>
              <span className="font-code-sm text-code-sm text-secondary font-mono font-bold">SNAPSHOT: READY</span>
            </div>
          </div>
        </div>

        {/* Multi-Reviewer Consensus Section */}
        <div className="flex flex-col gap-space-xs">
          <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
            CHỮ KÝ XÁC NHẬN ĐA TẦNG (MULTI-REVIEWER CONSENSUS)
          </span>
          <div className="grid grid-cols-2 gap-space-sm">
            <div className="p-space-md bg-surface-container rounded flex flex-col gap-space-xs border border-secondary/30">
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">
                  OPERATOR 1 (TRƯỞNG CA NOC)
                </span>
                <span className="px-space-xs py-space-2xs bg-secondary-container/20 text-secondary font-code-sm text-code-sm font-bold rounded">
                  ĐÃ KÝ DUYỆT
                </span>
              </div>
              <span className="font-code-md text-code-md text-on-surface font-semibold">ca_truc_hanoi_01</span>
              <span className="font-code-sm text-code-sm text-secondary">
                Approved at 10:14:02 UTC • Key: 0x8F9C
              </span>
            </div>

            <div className="p-space-md bg-surface-container rounded flex flex-col gap-space-xs border border-tertiary/30">
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-tertiary">
                  OPERATOR 2 (CHUYÊN GIA IP CORE)
                </span>
                <span className="px-space-xs py-space-2xs bg-tertiary/20 text-tertiary font-code-sm text-code-sm font-bold rounded animate-pulse">
                  {signed ? 'ĐÃ KÝ' : 'CHỜ PHÊ DUYỆT'}
                </span>
              </div>
              <span className="font-code-md text-code-md text-on-surface font-semibold">specialist_ip_dehl</span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">
                {signed ? 'Cryptographic sign-off attached' : 'Pending your cryptographic sign-off'}
              </span>
            </div>
          </div>
        </div>

        {/* Operator Note Input */}
        <div className="flex flex-col gap-space-2xs">
          <label className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
            GHI CHÚ ĐIỀU HÀNH & LÝ DO KIỂM TOÁN
          </label>
          <textarea
            value={operatorNote}
            onChange={e => setOperatorNote(e.target.value)}
            rows={2}
            className="w-full bg-surface-container-low p-space-sm rounded text-on-surface font-body-sm text-body-sm border border-surface-container-highest focus:border-secondary focus:outline-none"
          />
        </div>

        {/* Modal Actions */}
        <div className="flex items-center justify-end gap-space-md pt-space-xs border-t border-surface-container-highest">
          <button
            onClick={onClose}
            className="px-space-lg py-space-xs bg-surface-container-high hover:bg-surface-variant text-on-surface rounded font-body-md text-body-md font-semibold transition-colors flex items-center gap-space-xs cursor-pointer"
            type="button"
          >
            <span className="material-symbols-outlined text-[16px]">close</span>
            Hủy bỏ / Xem xét lại
          </button>
          <button
            onClick={handleSignOff}
            disabled={signed}
            className="px-space-lg py-space-xs bg-primary-container hover:brightness-110 text-on-primary-container rounded font-body-md text-body-md font-bold transition-all shadow-md flex items-center gap-space-xs cursor-pointer"
            type="button"
          >
            <span className="material-symbols-outlined text-[18px]">verified</span>
            {signed ? 'Đang thực thi lệnh...' : 'Ký duyệt & Thực thi Phân hoạch (Approve & Dispatch Cut)'}
          </button>
        </div>
      </div>
    </div>
  )
}
