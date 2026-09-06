import { useState } from 'react'
import type { ChainAnalysis } from '../types'
import type { MutationSpec } from '../components/OperatorValidationModal'

interface ValidationViewProps {
  analysis: ChainAnalysis
  onOpenValidationModal?: (spec?: MutationSpec) => void
}

export function ValidationView({
  analysis,
  onOpenValidationModal,
}: ValidationViewProps) {
  const [operatorSigned, setOperatorSigned] = useState(false)
  const [signTime, setSignTime] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'CONSENSUS' | 'GUARDRAILS' | 'LEDGER'>('CONSENSUS')

  const handleAttachSignature = () => {
    const now = new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC'
    setOperatorSigned(true)
    setSignTime(now)
  }

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* Screen 18 Header Bar */}
      <div className="w-full bg-surface-container-lowest px-space-lg py-space-sm rounded-lg shadow-sm flex flex-col gap-space-xs">
        <div className="flex flex-wrap items-center justify-between gap-space-sm">
          <div className="flex items-center gap-space-xs font-code-sm text-code-sm">
            <span className="text-on-surface-variant">SNAPSHOT</span>
            <span className="text-secondary font-semibold">S102</span>
            <span className="material-symbols-outlined text-[14px] text-on-surface-variant">chevron_right</span>
            <span className="text-on-surface-variant">CHAIN</span>
            <span className="text-on-surface font-semibold bg-surface-container px-space-xs py-space-2xs rounded">
              {analysis.chain_id}
            </span>
            <span className="material-symbols-outlined text-[14px] text-on-surface-variant">chevron_right</span>
            <span className="text-secondary font-semibold">
              18 - Validation &amp; Operator Consensus Protocol
            </span>
          </div>

          <div className="flex items-center gap-space-sm">
            <span className="font-label-caps text-label-caps uppercase bg-primary-container/20 text-primary px-space-sm py-space-2xs rounded font-bold flex items-center gap-space-2xs">
              <span className="material-symbols-outlined text-[14px]">security</span>
              FAIL-CLOSED SAFEGUARD ACTIVE
            </span>
            <div className="flex items-center gap-space-xs px-space-sm py-space-2xs bg-surface-container rounded border border-surface-container-highest">
              <span className={`w-2 h-2 rounded-full ${operatorSigned ? 'bg-secondary' : 'bg-tertiary animate-pulse'}`}></span>
              <span className="font-code-sm text-code-sm text-on-surface font-semibold">
                {operatorSigned ? 'CONSENSUS SEALED (2/2)' : 'AWAITING OPERATOR 2 SIGN-OFF (1/2)'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Navigation Sub-Tabs */}
      <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
        <div className="flex items-center gap-space-xs">
          <button
            onClick={() => setActiveTab('CONSENSUS')}
            className={`px-space-md py-space-xs font-body-sm text-body-sm rounded flex items-center gap-space-xs transition-colors cursor-pointer ${
              activeTab === 'CONSENSUS'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs font-semibold'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">verified_user</span>
            <span>Multi-Reviewer Consensus</span>
          </button>
          <button
            onClick={() => setActiveTab('GUARDRAILS')}
            className={`px-space-md py-space-xs font-body-sm text-body-sm rounded flex items-center gap-space-xs transition-colors cursor-pointer ${
              activeTab === 'GUARDRAILS'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs font-semibold'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">policy</span>
            <span>SLA Guardrails Checklist</span>
          </button>
          <button
            onClick={() => setActiveTab('LEDGER')}
            className={`px-space-md py-space-xs font-body-sm text-body-sm rounded flex items-center gap-space-xs transition-colors cursor-pointer ${
              activeTab === 'LEDGER'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs font-semibold'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">history_edu</span>
            <span>Mutation Audit Ledger</span>
          </button>
        </div>

        <div className="flex items-center gap-space-xs font-code-sm text-xs text-on-surface-variant">
          <span>AUDIT HASH:</span>
          <span className="font-mono text-secondary font-bold">sha256:d8a94bc109fe29bf...</span>
        </div>
      </div>

      {/* TAB 1: MULTI-REVIEWER CONSENSUS */}
      {activeTab === 'CONSENSUS' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
          {/* Left 8 cols: Two Reviewer Cards + Sign-off Area */}
          <div className="lg:col-span-8 flex flex-col gap-space-md">
            <div className="bg-surface-container rounded-lg p-space-lg shadow-md flex flex-col gap-space-md">
              <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
                <div className="flex items-center gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[22px]">group</span>
                  <div>
                    <span className="font-headline-md text-headline-md font-bold text-on-surface">
                      Chữ ký Xác nhận Đa Tầng (Multi-Reviewer Consensus)
                    </span>
                    <p className="font-body-sm text-body-sm text-on-surface-variant">
                      Chính sách an toàn viễn thông nghiêm ngặt: Yêu cầu tối thiểu 2 kỹ sư xác thực trước khi điều chuyển hạ tầng.
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
                {/* Operator 1: Trưởng ca NOC */}
                <div className="p-space-md bg-surface-container-low rounded-lg border border-secondary/40 flex flex-col gap-space-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">
                      OPERATOR 1 (TRƯỞNG CA NOC)
                    </span>
                    <span className="px-space-xs py-space-2xs bg-secondary-container/20 text-secondary font-code-sm text-xs font-bold rounded flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">check</span>
                      ĐÃ KÝ DUYỆT
                    </span>
                  </div>
                  <div className="flex flex-col">
                    <span className="font-code-md text-code-md text-on-surface font-bold">ca_truc_hanoi_01</span>
                    <span className="font-code-sm text-code-sm text-on-surface-variant">Nguyễn Văn Q. (Trưởng ca VHKT)</span>
                  </div>
                  <div className="pt-space-2xs border-t border-surface-container-highest/60 flex flex-col gap-0.5 text-code-sm font-code-sm">
                    <span className="text-secondary">Approved at 10:14:02 UTC</span>
                    <span className="text-on-surface-variant font-mono text-[11px]">Key: RSA-4096:0x8F9C...31E</span>
                  </div>
                </div>

                {/* Operator 2: Chuyên gia IP Core */}
                <div className={`p-space-md bg-surface-container-low rounded-lg border flex flex-col gap-space-sm transition-all ${
                  operatorSigned ? 'border-secondary/40' : 'border-tertiary/50 shadow-md'
                }`}>
                  <div className="flex items-center justify-between">
                    <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold">
                      OPERATOR 2 (CHUYÊN GIA IP CORE)
                    </span>
                    <span className={`px-space-xs py-space-2xs font-code-sm text-xs font-bold rounded flex items-center gap-1 ${
                      operatorSigned
                        ? 'bg-secondary-container/20 text-secondary'
                        : 'bg-tertiary/20 text-tertiary animate-pulse'
                    }`}>
                      <span className="material-symbols-outlined text-[14px]">
                        {operatorSigned ? 'check' : 'pending'}
                      </span>
                      {operatorSigned ? 'ĐÃ KÝ DUYỆT' : 'CHỜ PHÊ DUYỆT'}
                    </span>
                  </div>
                  <div className="flex flex-col">
                    <span className="font-code-md text-code-md text-on-surface font-bold">specialist_ip_dehl</span>
                    <span className="font-code-sm text-code-sm text-on-surface-variant">Bạn (Kỹ sư chuyên trách DEHL)</span>
                  </div>
                  <div className="pt-space-2xs border-t border-surface-container-highest/60 flex flex-col gap-0.5 text-code-sm font-code-sm">
                    {operatorSigned ? (
                      <>
                        <span className="text-secondary">Approved at {signTime}</span>
                        <span className="text-on-surface-variant font-mono text-[11px]">Key: ED25519:0x2B4A...99C</span>
                      </>
                    ) : (
                      <span className="text-tertiary">Yêu cầu chữ ký số của bạn để hoàn tất lệnh</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Signature Action Box */}
              {!operatorSigned ? (
                <div className="p-space-md bg-surface-container-low rounded-lg border border-tertiary/30 flex flex-col sm:flex-row items-center justify-between gap-space-md">
                  <div className="flex items-center gap-space-sm">
                    <div className="w-10 h-10 rounded-full bg-tertiary/15 flex items-center justify-center text-tertiary">
                      <span className="material-symbols-outlined text-[24px]">key</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="font-headline-sm text-body-md font-bold text-on-surface">
                        Xác thực Chữ ký Kỹ sư Trực vận hành
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant">
                        Đính kèm chữ ký mã hóa vào hồ sơ kiểm định chuỗi {analysis.chain_id}.
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={handleAttachSignature}
                    className="px-space-lg py-space-xs bg-primary text-on-primary font-body-md text-body-md font-bold rounded shadow-md hover:brightness-110 flex items-center gap-space-xs transition-all cursor-pointer whitespace-nowrap"
                  >
                    <span className="material-symbols-outlined text-[18px]">draw</span>
                    <span>Ký duyệt Xác thực Chuỗi</span>
                  </button>
                </div>
              ) : (
                <div className="p-space-md bg-secondary/10 border border-secondary/30 rounded-lg flex items-center gap-space-md">
                  <span className="material-symbols-outlined text-secondary text-[28px]">verified</span>
                  <div className="flex flex-col">
                    <span className="font-body-md text-body-md font-bold text-secondary">
                      Hồ sơ đã được phê duyệt đồng thuận đầy đủ (Consensus 2/2)
                    </span>
                    <span className="font-code-sm text-code-sm text-on-surface-variant">
                      Chữ ký hợp lệ đã được băm SHA-256 vào sổ cái kiểm toán bất biến. Chuỗi sẵn sàng cho các lệnh dispatch can thiệp.
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Quick Actions to trigger Specific Cut Modals */}
            <div className="bg-surface-container rounded-lg p-space-md shadow-md flex flex-col gap-space-sm">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                CÁC LỆNH ĐỘT BIẾN CHUỖI CẦN DUYỆT (PENDING DISPATCH ACTIONS)
              </span>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-space-sm">
                <div className="p-space-sm bg-surface-container-low rounded border border-surface-container-highest flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="font-code-sm text-code-sm text-secondary font-bold">MUT-CUT-01: Spectral Cheeger</span>
                    <span className="font-body-sm text-xs text-on-surface-variant">Tách DEHL01 Core (42 alms) vs DEHT01 Access (16 alms)</span>
                  </div>
                  <button
                    onClick={() =>
                      onOpenValidationModal?.({
                        opId: 'MUT-CUT-01',
                        opType: 'CHEEGER_SPECTRAL_CUT',
                        title: 'Phê duyệt Nhát cắt Đồ thị CUT-01',
                        targetSummary: 'Phân tách: Subchain A (DEHL01 Core, 42 alms) và Subchain B (DEHT01 Access, 16 alms)',
                        detail: 'Độ dẫn vết cắt Φ = 0.038, Gain = +0.142. Ngắt các liên kết cầu nối giữa DEHL01 và DEHT01.',
                        badgeLabel: 'CUT-01',
                        conductance: 0.038,
                        modularityGain: '+0.142',
                        disconnectedEdges: [
                          'ALM-47933130 ↔ ALM-99210014 (Weight: 0.11)',
                          'DEHL01-GW01::Gi0/1 ↔ DEHT01-SW01::Gi0/2 (Weight: 0.08)',
                        ],
                        defaultNote: 'Xác nhận phân tách CUT-01 để cô lập nhánh phụ trợ hạ lưu DEHT01 khỏi lõi sự cố DEHL01.',
                      })
                    }
                    className="px-space-sm py-1 bg-surface-container-high hover:bg-surface-bright text-on-surface font-code-sm text-xs rounded transition-colors cursor-pointer border border-surface-container-highest"
                  >
                    Xem &amp; Ký CUT-01
                  </button>
                </div>

                <div className="p-space-sm bg-surface-container-low rounded border border-surface-container-highest flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="font-code-sm text-code-sm text-tertiary font-bold">MUT-S103-FISSION: Epoch Policy</span>
                    <span className="font-body-sm text-xs text-on-surface-variant">Tách chuỗi {analysis.chain_id} thành Subchain A + B</span>
                  </div>
                  <button
                    onClick={() =>
                      onOpenValidationModal?.({
                        opId: 'MUT-S103-FISSION',
                        opType: 'TEMPORAL_EPOCH_FISSION',
                        title: 'Phê duyệt Phân rã Chuỗi Sự cố (S103 Fission Policy)',
                        targetSummary: `Tách chuỗi ${analysis.chain_id} thành C2214039-A và C2214039-B`,
                        detail: 'Chính sách tự động S103 kích hoạt do chuỗi duy trì >50 cảnh báo qua 2 chu kỳ liên tiếp (S101-S102).',
                        badgeLabel: 'EPOCH_S103',
                        defaultNote: `Xác nhận phân rã chuỗi ${analysis.chain_id} theo chính sách vòng đời sự cố S103.`,
                      })
                    }
                    className="px-space-sm py-1 bg-surface-container-high hover:bg-surface-bright text-on-surface font-code-sm text-xs rounded transition-colors cursor-pointer border border-surface-container-highest"
                  >
                    Xem &amp; Ký S103
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Right 4 cols: Fail-Closed Checklist Summary */}
          <div className="lg:col-span-4 flex flex-col gap-space-md">
            <div className="bg-surface-container rounded-lg p-space-md shadow-md flex flex-col gap-space-sm">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                FAIL-CLOSED INVARIANTS CHECKLIST
              </span>

              <div className="flex flex-col gap-space-xs">
                <div className="p-space-sm bg-surface-container-low rounded flex items-start gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[18px] mt-0.5">check_circle</span>
                  <div className="flex flex-col">
                    <span className="font-body-sm text-body-sm text-on-surface font-semibold">P1 SLA Disruption Zero</span>
                    <span className="font-code-sm text-xs text-on-surface-variant">0 tickets P1/P2 bị phân tách sai lệch</span>
                    <span className="font-mono text-secondary text-[11px] font-bold mt-0.5">STATUS: PASS</span>
                  </div>
                </div>

                <div className="p-space-sm bg-surface-container-low rounded flex items-start gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[18px] mt-0.5">check_circle</span>
                  <div className="flex flex-col">
                    <span className="font-body-sm text-body-sm text-on-surface font-semibold">Immutable Hash Integrity</span>
                    <span className="font-code-sm text-xs text-on-surface-variant">Lưu vết băm trên sổ cái an ninh mạng</span>
                    <span className="font-mono text-secondary text-[11px] font-bold mt-0.5">SHA256: VERIFIED</span>
                  </div>
                </div>

                <div className="p-space-sm bg-surface-container-low rounded flex items-start gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[18px] mt-0.5">check_circle</span>
                  <div className="flex flex-col">
                    <span className="font-body-sm text-body-sm text-on-surface font-semibold">Reversible Staging Window</span>
                    <span className="font-code-sm text-xs text-on-surface-variant">Khôi phục nguyên trạng trong 30 phút</span>
                    <span className="font-mono text-secondary text-[11px] font-bold mt-0.5">SNAPSHOT: READY</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-surface-container rounded-lg p-space-md shadow-md flex flex-col gap-space-xs font-code-sm text-xs">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                ENGINE ENVIRONMENT
              </span>
              <div className="flex justify-between py-1 border-b border-surface-container-highest">
                <span className="text-on-surface-variant">Runtime Model:</span>
                <span className="text-on-surface font-mono">Hindsight-v2.3.1</span>
              </div>
              <div className="flex justify-between py-1 border-b border-surface-container-highest">
                <span className="text-on-surface-variant">Safeguard Policy:</span>
                <span className="text-secondary font-mono">Strict Two-Person Rule</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-on-surface-variant">CMDB Sync:</span>
                <span className="text-secondary font-mono">NetBox v3.7 (LIVE)</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: GUARDRAILS CHECKLIST */}
      {activeTab === 'GUARDRAILS' && (
        <div className="bg-surface-container rounded-lg p-space-lg shadow-md flex flex-col gap-space-md">
          <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
            <span className="font-headline-md text-headline-md font-bold text-on-surface">
              Chi tiết Bảng Kiểm toán An toàn Hệ thống (Audit Guardrails Specification)
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-space-md">
            <div className="p-space-md bg-surface-container-low rounded-lg flex flex-col gap-space-xs border border-secondary/30">
              <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">
                GUARDRAIL #1: SLA COMPLIANCE
              </span>
              <span className="font-headline-sm text-body-md font-bold text-on-surface">Không ảnh hưởng P1 Tickets</span>
              <p className="font-body-sm text-xs text-on-surface-variant">
                Thuật toán đã kiểm tra danh sách ticket cấp độ Critical/Major trên NOCPro TT. Không có ticket active nào bị cắt đôi thành phần.
              </p>
              <span className="font-code-sm text-secondary font-mono font-bold mt-2">VERIFIED PASS</span>
            </div>

            <div className="p-space-md bg-surface-container-low rounded-lg flex flex-col gap-space-xs border border-secondary/30">
              <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">
                GUARDRAIL #2: CRYPTOGRAPHIC HASH
              </span>
              <span className="font-headline-sm text-body-md font-bold text-on-surface">Bất biến SHA-256 Provenance</span>
              <p className="font-body-sm text-xs text-on-surface-variant">
                Toàn bộ cấu trúc đồ thị bằng chứng và nhãn của 58 cảnh báo được mã hóa băm liên tục, chống sửa đổi sau can thiệp.
              </p>
              <span className="font-code-sm text-secondary font-mono font-bold mt-2">sha256:d8a94bc1...</span>
            </div>

            <div className="p-space-md bg-surface-container-low rounded-lg flex flex-col gap-space-xs border border-secondary/30">
              <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">
                GUARDRAIL #3: REVERSIBLE STAGING
              </span>
              <span className="font-headline-sm text-body-md font-bold text-on-surface">Khôi phục trong 30 phút</span>
              <p className="font-body-sm text-xs text-on-surface-variant">
                Nếu kỹ sư vận hành phát hiện nhầm lẫn, hệ thống hỗ trợ 1-click Rollback tái hợp nhất chuỗi trong vòng 30 phút không mất lịch sử.
              </p>
              <span className="font-code-sm text-secondary font-mono font-bold mt-2">ROLLBACK READY</span>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: MUTATION LEDGER */}
      {activeTab === 'LEDGER' && (
        <div className="bg-surface-container rounded-lg p-space-lg shadow-md flex flex-col gap-space-md">
          <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
            <span className="font-headline-md text-headline-md font-bold text-on-surface">
              Nhật ký Can thiệp &amp; Đột biến Chuỗi (Audit Ledger)
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left font-code-sm text-xs">
              <thead className="bg-surface-container-low text-on-surface-variant uppercase font-label-caps">
                <tr>
                  <th className="p-space-sm">OP ID</th>
                  <th className="p-space-sm">LOẠI ĐỘT BIẾN</th>
                  <th className="p-space-sm">MÔ TẢ CHI TIẾT</th>
                  <th className="p-space-sm">THỜI GIAN</th>
                  <th className="p-space-sm">NGƯỜI KÝ</th>
                  <th className="p-space-sm">TRẠNG THÁI</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container-highest">
                <tr className="hover:bg-surface-container-high/40">
                  <td className="p-space-sm font-bold text-secondary">MUT-20260801-0941</td>
                  <td className="p-space-sm text-primary">SPECTRAL_CHEEGER_CUT</td>
                  <td className="p-space-sm text-on-surface">Tách DEHL01 (42 alms) và DEHT01 (16 alms)</td>
                  <td className="p-space-sm text-on-surface-variant">10:14:02 UTC</td>
                  <td className="p-space-sm font-mono">ca_truc_hanoi_01</td>
                  <td className="p-space-sm text-tertiary font-bold">AWAITING 2ND KEY</td>
                </tr>
                <tr className="hover:bg-surface-container-high/40">
                  <td className="p-space-sm font-bold text-secondary">MUT-20260801-0815</td>
                  <td className="p-space-sm text-on-surface">TEMPORAL_GROUPING</td>
                  <td className="p-space-sm text-on-surface">Gộp sự cố liên trạm theo cửa sổ thời gian 600s</td>
                  <td className="p-space-sm text-on-surface-variant">08:15:30 UTC</td>
                  <td className="p-space-sm font-mono">system_engine_auto</td>
                  <td className="p-space-sm text-secondary font-bold">SEALED</td>
                </tr>
                <tr className="hover:bg-surface-container-high/40">
                  <td className="p-space-sm font-bold text-secondary">AUDIT-20260801-0730</td>
                  <td className="p-space-sm text-on-surface">BASELINE_VERIFY</td>
                  <td className="p-space-sm text-on-surface">Đối soát định tuyến và topology NetBox v3.7</td>
                  <td className="p-space-sm text-on-surface-variant">07:30:00 UTC</td>
                  <td className="p-space-sm font-mono">cmdb_sync_worker</td>
                  <td className="p-space-sm text-secondary font-bold">AUDITED</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
