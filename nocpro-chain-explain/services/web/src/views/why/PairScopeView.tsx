import { useMemo, useEffect } from 'react'
import type { Member, PairWhy, WhyScope } from '../../types'
import { InfoTip } from '../../components/InfoTip'

interface PairScopeViewProps {
  members: Member[]
  selectedMemberIds: string[]
  setSelectedMemberIds: (ids: string[]) => void
  pairWhy: PairWhy | null
  pairWhyState: 'IDLE' | 'LOADING' | 'AVAILABLE' | 'LOADED' | 'UNAVAILABLE'
  pairWhyReason: string | null
  onSwitchScope: (scope: WhyScope) => void
}

export function PairScopeView({
  members,
  selectedMemberIds,
  setSelectedMemberIds,
  pairWhy,
  pairWhyState,
  pairWhyReason,
  onSwitchScope: _onSwitchScope,
}: PairScopeViewProps) {
  // Auto-select first two members if not already selected
  useEffect(() => {
    if (selectedMemberIds.length < 2 && members.length >= 2) {
      setSelectedMemberIds([members[0].alarm_id, members[1].alarm_id])
    }
  }, [members, selectedMemberIds.length, setSelectedMemberIds])

  const topMembers = useMemo(() => members.slice(0, 6), [members])

  // Current selected IDs
  const idA = selectedMemberIds[0] ?? ''
  const idB = selectedMemberIds[1] ?? ''

  const handleSwap = () => {
    if (idA && idB) {
      setSelectedMemberIds([idB, idA])
    }
  }

  const handleQuickCompare = (first: string, second: string) => {
    setSelectedMemberIds([first, second])
  }

  return (
    <div className="flex flex-col gap-space-md animate-fadeIn">
      {/* Top Controls & Pair Selector Card */}
      <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-xs">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary text-[20px]">compare_arrows</span>
            <h3 className="font-headline-md text-sm font-bold text-on-surface">
              Đối sánh chứng cứ theo cặp (Pair WHY)
            </h3>
            <InfoTip text="Đối sánh trực tiếp 2 cảnh báo A và B. Hệ thống sẽ bóc tách tất cả các kênh bằng chứng: Trễ thời gian, Topology, Phần cứng và Ngữ nghĩa để giải thích vì sao 2 cảnh báo này được xâu chuỗi." />
          </div>

        </div>

        {/* Endpoint Selectors Form */}
        <div className="grid grid-cols-1 sm:grid-cols-11 gap-space-sm items-center bg-[#080d17] p-space-sm rounded border border-[#1b273e]/60">
          <div className="sm:col-span-5 flex flex-col gap-1">
            <label className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
              Cảnh báo nguồn A (Source)
              <InfoTip text="Cảnh báo đầu tiên được chọn trong cặp đối sánh." />
            </label>
            <select
              aria-label="Pair endpoint A"
              value={idA}
              onChange={e => setSelectedMemberIds([e.target.value, idB].filter(Boolean))}
              className="w-full h-8 px-2.5 bg-[#0e1728] text-on-surface font-code-sm text-xs rounded border border-[#1b273e] outline-none focus:border-secondary"
            >
              <option value="">-- Chọn cảnh báo A --</option>
              {members.map(m => (
                <option key={m.alarm_id} value={m.alarm_id} disabled={m.alarm_id === idB}>
                  {m.alarm_id} · {m.alarm_name || 'Unnamed'} ({m.device_code ?? m.node_reference ?? 'N/A'})
                </option>
              ))}
            </select>
          </div>

          <div className="sm:col-span-1 flex justify-center py-1">
            <button
              type="button"
              onClick={handleSwap}
              disabled={!idA || !idB}
              aria-label="Swap A and B"
              title="Đổi vị trí A và B"
              className="w-8 h-8 rounded-full bg-surface-container-high hover:bg-secondary/20 hover:text-secondary text-on-surface-variant flex items-center justify-center transition-colors border border-[#1b273e] disabled:opacity-30 cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">sync_alt</span>
            </button>
          </div>

          <div className="sm:col-span-5 flex flex-col gap-1">
            <label className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
              Cảnh báo đích B (Target)
              <InfoTip text="Cảnh báo thứ hai được chọn trong cặp đối sánh." />
            </label>
            <select
              aria-label="Pair endpoint B"
              value={idB}
              onChange={e => setSelectedMemberIds([idA, e.target.value].filter(Boolean))}
              className="w-full h-8 px-2.5 bg-[#0e1728] text-on-surface font-code-sm text-xs rounded border border-[#1b273e] outline-none focus:border-secondary"
            >
              <option value="">-- Chọn cảnh báo B --</option>
              {members.map(m => (
                <option key={m.alarm_id} value={m.alarm_id} disabled={m.alarm_id === idA}>
                  {m.alarm_id} · {m.alarm_name || 'Unnamed'} ({m.device_code ?? m.node_reference ?? 'N/A'})
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* NxN Evidence Heatmap Matrix Preview */}
      {topMembers.length >= 2 && (
        <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[18px]">grid_view</span>
              <h4 className="font-label-caps text-xs uppercase text-on-surface-variant font-bold">
                Ma trận tương quan &amp; Độ trễ ({topMembers.length} nút cốt lõi)
              </h4>
              <InfoTip text="Ma trận đối sánh nhanh giữa các cảnh báo. Nhấp vào ô bất kỳ để gửi truy vấn trực tiếp lên backend giải thích cặp cảnh báo đó." />
            </div>
            <span className="text-[11px] font-code-sm text-on-surface-variant">Nhấp vào ô để đối sánh cặp cảnh báo</span>
          </div>

          <div className="overflow-x-auto mt-1">
            <table className="w-full text-center font-code-sm text-xs border-collapse">
              <thead>
                <tr>
                  <th className="p-1.5 text-left text-on-surface-variant text-[10px]">Node</th>
                  {topMembers.map(m => (
                    <th key={m.alarm_id} className="p-1.5 text-[10px] text-secondary font-semibold truncate max-w-[90px]">
                      {m.alarm_id.slice(-6)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {topMembers.map((rowMember, rIdx) => (
                  <tr key={rowMember.alarm_id} className="border-t border-[#151f33]">
                    <td className="p-1.5 text-left text-on-surface font-semibold text-[11px] truncate max-w-[100px]">
                      {rowMember.alarm_id.slice(-6)}
                    </td>
                    {topMembers.map((colMember, cIdx) => {
                      const isSelf = rIdx === cIdx
                      const isCurrentPair =
                        (idA === rowMember.alarm_id && idB === colMember.alarm_id) ||
                        (idB === rowMember.alarm_id && idA === colMember.alarm_id)

                      const sameDev =
                        (rowMember.device_code ?? rowMember.node_reference) ===
                        (colMember.device_code ?? colMember.node_reference)

                      const t1 = Date.parse(rowMember.canonical_start_time || '0')
                      const t2 = Date.parse(colMember.canonical_start_time || '0')
                      const diffSec = Math.abs(t1 - t2) / 1000

                      const cellText = isSelf
                        ? '—'
                        : sameDev
                        ? 'Chassis'
                        : !isNaN(diffSec) && diffSec <= 60
                        ? `Δ${diffSec}s`
                        : 'Link'

                      return (
                        <td key={colMember.alarm_id} className="p-1">
                          <button
                            type="button"
                            disabled={isSelf}
                            onClick={() => handleQuickCompare(rowMember.alarm_id, colMember.alarm_id)}
                            className={`w-full py-1.5 rounded text-[11px] font-bold transition-all ${
                              isSelf
                                ? 'bg-surface-container-highest/30 text-on-surface-variant/30 cursor-default'
                                : isCurrentPair
                                ? 'bg-secondary text-on-secondary ring-2 ring-secondary/50 font-extrabold shadow-md'
                                : sameDev
                                ? 'bg-emerald-950/40 text-emerald-300 hover:bg-emerald-800/60 border border-emerald-500/30'
                                : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'
                            }`}
                          >
                            {cellText}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* States: Idle, Loading, Unavailable, or Loaded */}
      {pairWhyState === 'IDLE' && (
        <div className="rounded-lg border border-dashed border-[#1b273e] p-space-xl text-center bg-surface-container flex flex-col items-center justify-center">
          <span className="material-symbols-outlined text-4xl text-secondary opacity-70">compare_arrows</span>
          <p className="mt-2 font-body-md text-on-surface font-semibold">Chọn 2 cảnh báo bất kỳ để truy vấn chứng cứ theo cặp.</p>
          <p className="mt-1 text-xs text-on-surface-variant max-w-md">
            Đánh giá đa kênh hỗ trợ: kề cận topology, độ trễ thời gian, tương đồng ngữ nghĩa và cụm bùng nổ (burst).
          </p>
        </div>
      )}

      {pairWhyState === 'LOADING' && (
        <div className="rounded-lg border border-[#1b273e] bg-[#080d17] p-space-xl text-center font-code-sm text-sm text-secondary animate-pulse" role="status">
          <span className="material-symbols-outlined text-3xl animate-spin text-secondary mb-2">autorenew</span>
          <p>Đang truy vấn các kênh chứng cứ theo cặp từ backend API…</p>
        </div>
      )}

      {pairWhyState === 'UNAVAILABLE' && (
        <div className="rounded-lg border border-error/30 bg-error/10 p-space-md text-center text-error font-code-sm text-xs" role="alert">
          <span className="material-symbols-outlined text-[20px] text-error mb-1">warning</span>
          <p>CHƯA KHẢ DỤNG · {pairWhyReason || 'Không thể xác định chứng cứ theo cặp cho các cảnh báo đã chọn.'}</p>
        </div>
      )}

      {(pairWhyState === 'LOADED' || pairWhyState === 'AVAILABLE') && pairWhy && (
        <div className="flex flex-col gap-space-sm">
          {/* Pair Summary Banner */}
          <div className="rounded-lg border border-[#1b273e] bg-[#080d17] p-space-md flex flex-wrap items-center justify-between gap-space-sm shadow-sm">
            <div className="flex items-center gap-2 font-code-sm text-sm">
              <strong className="text-secondary">{pairWhy.alarm_id_a}</strong>
              <span className="text-on-surface-variant">↔</span>
              <strong className="text-secondary">{pairWhy.alarm_id_b}</strong>
              <span className="ml-2 rounded bg-secondary/15 px-2 py-0.5 text-[11px] font-bold text-secondary border border-secondary/30">
                Kết luận: {pairWhy.system_fact.status}
              </span>
              <InfoTip text="Kết luận tổng thể của hệ thống về mối quan hệ giữa 2 cảnh báo này (CORRELATED, CAUSAL hoặc INDEPENDENT)." />
            </div>
            <div className="flex items-center gap-2 text-xs font-code-sm">
              <span className="text-emerald-400 font-semibold flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                {pairWhy.evidence.filter(e => e.state === 'SUPPORT').length} Hỗ trợ
              </span>
              <span className="text-on-surface-variant">·</span>
              <span className="text-amber-300 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-300"></span>
                {pairWhy.evidence.filter(e => e.state === 'NEUTRAL').length} Trung tính
              </span>
              <span className="text-on-surface-variant">·</span>
              <span className="text-slate-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                {pairWhy.evidence.filter(e => e.state === 'UNAVAILABLE').length} Chưa khả dụng
              </span>
            </div>
          </div>

          {/* Real Evidence Channel Cards Grid (100% from backend) */}
          <div className="grid grid-cols-1 gap-space-xs">
            {pairWhy.evidence.map((item, index) => {
              const isSupport = item.state === 'SUPPORT'
              const isNeutral = item.state === 'NEUTRAL'
              const channelTitle =
                item.channel_family === 'E_device' ? 'Trùng khớp thiết bị vật lý'
                : item.channel_family === 'E_card' ? 'Trùng khớp card / linh kiện phần cứng'
                : item.channel_family === 'E_site' ? 'Cùng trạm / vị trí vật lý'
                : item.channel_family === 'E_remote' ? 'Liên kết node từ xa'
                : item.channel_family === 'T_burst' ? 'Bùng nổ đồng thời (Temporal Burst)'
                : item.channel_family === 'T_delay' ? 'Độ trễ lan truyền có hướng'
                : item.channel_family === 'S' ? 'Độ tương đồng ngữ nghĩa cảnh báo'
                : item.channel_family === 'Dep_hop' ? 'Số bước kề cận Topology (Hop)'
                : item.channel_family === 'DEP_UPSTREAM' ? 'Cổng quan hệ nhân quả thượng lưu'
                : item.channel_family === 'H' ? 'Quy luật lịch sử (Behavioral Lift)'
                : item.channel_family

              const channelExpl =
                item.channel_family === 'E_device' ? 'Cả hai cảnh báo cùng xảy ra trên cùng một thiết bị phần cứng.'
                : item.channel_family === 'E_card' ? 'Kiểm định thành phần card mạng, cổng hoặc sub-interface.'
                : item.channel_family === 'T_burst' ? 'Cả hai cảnh báo nổ ra trong cùng một cụm bùng nổ thời gian ngắn.'
                : item.channel_family === 'T_delay' ? 'Độ trễ thời gian giữa 2 cảnh báo nằm trong khoảng phân phối lan truyền sự cố.'
                : item.channel_family === 'Dep_hop' ? 'Hai thiết bị nằm kề nhau trên đồ thị topology mạng IP (1-2 hops).'
                : 'Bằng chứng tương quan được tính toán từ các kênh thuộc tính hệ thống.'

              return (
                <article
                  key={`${item.channel_family}-${item.derivation_tag}-${index}`}
                  className={`rounded-lg border p-space-sm transition-all ${
                    isSupport
                      ? 'border-emerald-500/30 bg-emerald-950/10 border-l-4 border-l-emerald-500'
                      : isNeutral
                      ? 'border-amber-500/30 bg-amber-950/10 border-l-4 border-l-amber-400'
                      : 'border-[#1b273e] bg-[#080d17] border-l-4 border-l-slate-600'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-space-xs">
                    <div className="flex items-center gap-2">
                      <strong className="text-on-surface text-xs font-semibold">{channelTitle}</strong>
                      <span className="font-mono text-[10px] text-on-surface-variant font-normal">
                        ({item.channel_family})
                      </span>
                      <InfoTip text={channelExpl} />
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm ${
                        isSupport
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                          : isNeutral
                          ? 'bg-amber-400/20 text-amber-300 border border-amber-400/40'
                          : 'bg-slate-700/30 text-slate-400 border border-slate-700/50'
                      }`}
                    >
                      {item.state}
                    </span>
                  </div>

                  <dl className="mt-space-xs grid grid-cols-2 gap-space-xs font-code-sm text-xs sm:grid-cols-4 bg-[#050912]/60 p-2 rounded">
                    <div>
                      <dt className="text-on-surface-variant text-[10px] flex items-center gap-1">
                        Điểm số (score)
                        <InfoTip text="Điểm tương quan thực tế đo được giữa 2 cảnh báo trên kênh này." />
                      </dt>
                      <dd className="font-semibold text-on-surface">{item.score === null ? 'N/A' : item.score.toFixed(4)}</dd>
                    </div>
                    <div>
                      <dt className="text-on-surface-variant text-[10px] flex items-center gap-1">
                        Ngưỡng (threshold)
                        <InfoTip text="Ngưỡng kích hoạt bằng chứng. Nếu score >= threshold, kênh sẽ chuyển sang trạng thái SUPPORT." />
                      </dt>
                      <dd className="font-semibold text-on-surface">{item.threshold === null ? 'N/A' : item.threshold.toFixed(4)}</dd>
                    </div>
                    <div>
                      <dt className="text-on-surface-variant text-[10px] flex items-center gap-1">
                        Nhóm (group)
                        <InfoTip text="Nhóm dẫn xuất bằng chứng (Derivation group) giúp loại bỏ sự trùng lặp thuộc tính." />
                      </dt>
                      <dd className="truncate text-secondary font-medium">{item.derivation_tag}</dd>
                    </div>
                    <div>
                      <dt className="text-on-surface-variant text-[10px] flex items-center gap-1">
                        Nguồn gốc (provenance)
                        <InfoTip text="Nguồn gốc kiểm chứng của bằng chứng (DATA_DRIVEN hoặc DOCUMENTED_DEFAULT)." />
                      </dt>
                      <dd className="truncate text-on-surface-variant">{item.provenance_class}</dd>
                    </div>
                  </dl>

                  {item.detail && (
                    <p className="mt-2 text-[11px] font-code-sm text-on-surface-variant bg-[#0c1424] px-2.5 py-1.5 rounded border border-[#1b273e]/60">
                      Chi tiết: <span className="text-slate-200">{item.detail}</span>
                    </p>
                  )}
                </article>
              )
            })}
          </div>


        </div>
      )}
    </div>
  )
}
