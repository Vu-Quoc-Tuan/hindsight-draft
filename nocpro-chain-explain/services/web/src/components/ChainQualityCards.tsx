import type { ChainOverviewCardContext } from '../types'

type Context = ChainOverviewCardContext
type CardStatus = 'READY' | 'PENDING' | 'UNAVAILABLE' | 'NOT_APPLICABLE'

function statusMessage(status: CardStatus, pending: string, unavailable: string): string {
  if (status === 'NOT_APPLICABLE') return 'Không áp dụng cho chuỗi singleton.'
  if (status === 'UNAVAILABLE') return unavailable
  return pending
}

export function RepresentativeMemberCard({ context, status = context ? 'READY' : 'PENDING' }: { context: Context | null; status?: CardStatus }) {
  const member = context?.representative_member
  const available = status === 'READY' && member?.status === 'AVAILABLE'
  const role = member?.role ?? 'UNAVAILABLE'

  return (
    <div className="bg-[#0b1322] border border-[#1b2b48] hover:border-amber-500/50 p-space-md rounded-lg shadow-sm flex flex-col justify-between transition-all">
      <div>
        <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-xs mb-1.5">
          <span className="flex items-center gap-1.5 text-amber-400 font-bold uppercase tracking-wider">
            <span className="material-symbols-outlined text-[16px]">workspace_premium</span>
            Thành viên evidence mạnh nhất
          </span>
          <span className="px-1.5 py-0.5 rounded bg-amber-400/15 text-amber-400 font-mono text-[10px] font-bold">
            {available ? role : status === 'READY' ? 'N/A' : status}
          </span>
        </div>
        {available ? (
          <>
            <h4 className="font-headline-sm text-sm text-on-surface font-bold truncate mt-1" title={member?.alarm_name ?? member?.alarm_id}>
              {member?.alarm_name ?? member?.alarm_id}
            </h4>
            <div className="flex items-center gap-1.5 mt-2 text-xs font-mono text-on-surface-variant">
              <span className="material-symbols-outlined text-[14px] text-primary">router</span>
              <span className="text-on-surface font-bold">{member?.device_code ?? 'Thiết bị chưa xác định'}</span>
            </div>
          </>
        ) : (
          <p className="text-xs text-on-surface-variant mt-3">
            {statusMessage(status, 'Đang chuẩn bị evidence thành viên…', 'Chưa đủ evidence để chọn đại diện.')}
          </p>
        )}
      </div>
      <div className="mt-3 pt-2 border-t border-[#17233a] flex items-center justify-between gap-2 text-xs font-mono text-on-surface-variant">
        <span>Evidence:</span>
        {available ? (
          <span className="text-secondary font-bold text-right">
            Support {member?.membership_support?.toFixed(2) ?? 'N/A'} · {member?.computable_groups ?? 0} nhóm
          </span>
        ) : <span>Không suy ra root cause</span>}
      </div>
    </div>
  )
}

export function TopologyCoverageCard({ context, status = context ? 'READY' : 'PENDING' }: { context: Context | null; status?: CardStatus }) {
  const topology = context?.topology
  const mapped = topology?.mapped_device_count ?? 0
  const total = topology?.total_device_count ?? 0
  const ratio = topology?.device_mapping_ratio

  return (
    <div className="bg-[#0b1322] border border-[#1b2b48] hover:border-primary/50 p-space-md rounded-lg shadow-sm flex flex-col justify-between transition-all">
      <div>
        <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-xs mb-1.5">
          <span className="flex items-center gap-1.5 text-primary font-bold uppercase tracking-wider">
            <span className="material-symbols-outlined text-[16px]">lan</span>
            Thiết bị trong topology
          </span>
          <span className="px-1.5 py-0.5 rounded bg-primary/15 text-primary font-mono text-[10px] font-bold">
            {status === 'READY' && topology ? `${Math.round((ratio ?? 0) * 100)}%` : status}
          </span>
        </div>
        {status === 'READY' && topology ? (
          <>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="font-headline-lg text-2xl font-bold text-on-surface">{mapped}/{total}</span>
              <span className="text-xs text-on-surface-variant">thiết bị đã ánh xạ</span>
            </div>
            <p className="text-xs text-on-surface-variant mt-2">
              {mapped === total && total > 0
                ? 'Tất cả thiết bị của chuỗi đều có mặt trong topology.'
                : `Còn ${Math.max(0, total - mapped)} thiết bị chưa ánh xạ được.`}
            </p>
          </>
        ) : (
          <p className="text-xs text-on-surface-variant mt-3">
            {statusMessage(status, 'Đang đối chiếu thiết bị với topology…', 'Topology chưa sẵn sàng')}
          </p>
        )}
      </div>
      <div className="mt-3 pt-2 border-t border-[#17233a] flex items-center justify-between text-xs font-mono text-on-surface-variant">
        <span>Kết nối quan sát:</span>
        <span className="text-on-surface font-semibold">
            {status === 'READY' && topology
            ? topology!.pair_total
              ? `${topology!.connected_pair_count ?? 0}/${topology!.pair_total} cặp resource`
              : 'Chưa đủ cặp để kiểm tra'
            : statusMessage(status, 'Đang đối chiếu topology…', 'Topology chưa sẵn sàng')}
        </span>
      </div>
    </div>
  )
}

function recommendationText(context: Context): string {
  const recommendations = context.recommendations ?? { split_recommended: false }
  if ((recommendations.count ?? 0) > 0) {
    const evaluated = recommendations.evaluated_count ?? 0
    return evaluated > 0
      ? `Đã thử ${evaluated} PA · giữ lại ${recommendations.count} PA tốt hơn`
      : `Giữ lại ${recommendations.count} phương án tốt hơn`
  }
  if (recommendations.evaluation_completed) {
    const evaluated = recommendations.evaluated_count ?? 0
    const rejected = recommendations.rejected_count ?? 0
    const passed = Math.max(0, evaluated - rejected)
    if (recommendations.status === 'NO_CLEAR_ALTERNATIVE') {
      return evaluated > 0
        ? `Đã thử ${evaluated} PA · chưa có PA tốt hơn`
        : 'Đã thử · chưa có phương án tốt hơn'
    }
    return evaluated > 0
      ? `Đã thử ${evaluated} PA · ${passed} PA qua kiểm tra an toàn`
      : 'Đã hoàn tất so sánh phương án'
  }
  if (recommendations.status === 'UNAVAILABLE') return 'Chưa thể chạy so sánh'
  if (recommendations.status === 'NOT_EVALUATED') return 'Chưa chạy so sánh phương án'
  if (recommendations.status === 'NO_CLEAR_ALTERNATIVE') return 'Đã chạy · chưa thấy phương án tốt hơn'
  return 'Chưa tìm thấy phương án tốt hơn'
}

export function ChainQualityCard({
  context,
  onOpenRecommendations,
  status = context ? 'READY' : 'PENDING',
}: {
  context: Context | null
  onOpenRecommendations?: () => void
  status?: CardStatus
}) {
  const assessment = context?.quality_assessment
  const stars = assessment?.stars
  const recommendationCount = context?.recommendations?.count ?? 0
  const starText = stars == null ? '☆☆☆☆☆' : `${'★'.repeat(stars)}${'☆'.repeat(5 - stars)}`

  return (
    <div className="bg-[#0b1322] border border-[#1b2b48] hover:border-amber-400/50 p-space-md rounded-lg shadow-sm flex flex-col justify-between transition-all">
      <div>
        <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-xs mb-1.5">
          <span className="flex items-center gap-1.5 text-amber-300 font-bold uppercase tracking-wider">
            <span className="material-symbols-outlined text-[16px]">hotel_class</span>
            Độ vững của chuỗi
          </span>
          <span className="px-1.5 py-0.5 rounded bg-amber-400/10 text-amber-300 border border-amber-400/20 font-mono text-[10px] font-bold">
            HEURISTIC
          </span>
        </div>
        {status === 'READY' && assessment ? (
          <>
            <div className="flex items-center gap-2 mt-1" aria-label={stars == null ? (assessment?.label ?? 'Chưa thể chấm') : `${stars} trên 5 sao`}>
              <span className="text-xl tracking-[0.12em] text-amber-300" aria-hidden="true">{starText}</span>
              {stars != null && <span className="font-mono text-xs text-on-surface-variant">{stars}/5</span>}
            </div>
            <p className="text-xs text-on-surface font-semibold mt-2">{assessment?.label ?? 'Chưa thể chấm'}</p>
          </>
        ) : (
          <p className="text-xs text-on-surface-variant mt-3">
            {statusMessage(status, 'Đang tổng hợp evidence để chấm…', 'Chưa thể chấm deterministic')}
          </p>
        )}
      </div>
      <div className="mt-3 pt-2 border-t border-[#17233a] flex items-center justify-between gap-2 text-xs font-mono text-on-surface-variant">
        <span>Counterfactual:</span>
        {status === 'READY' && context && recommendationCount > 0 ? (
          <button
            type="button"
            onClick={onOpenRecommendations}
            className="inline-flex items-center gap-1 text-cyan-400 font-bold hover:underline cursor-pointer bg-cyan-500/10 px-1.5 py-0.5 rounded border border-cyan-500/25"
          >
            {recommendationText(context)}
            <span className="material-symbols-outlined text-[13px]">arrow_forward</span>
          </button>
        ) : (
          <span className="text-on-surface font-semibold text-right">
            {status === 'READY' && context
              ? recommendationText(context)
              : statusMessage(status, 'Đang chuẩn bị đánh giá…', 'Chưa thể đánh giá deterministic')}
          </span>
        )}
      </div>
    </div>
  )
}
