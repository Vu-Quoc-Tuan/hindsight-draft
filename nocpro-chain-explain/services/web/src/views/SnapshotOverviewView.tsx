import type { ChainList, ChainQualitySummary } from '../types'
import { formatDuration } from '../format'

interface SnapshotOverviewViewProps {
  chainList?: ChainList | null
  onSelectChain: (chainId: string) => void
  onNavigate: (view: string) => void
  qualitySummary?: ChainQualitySummary | null
  qualitySummaryLoading?: boolean
  qualitySummaryError?: string | null
}

export function SnapshotOverviewView({
  chainList,
  onSelectChain,
  onNavigate,
  qualitySummary,
  qualitySummaryLoading = false,
  qualitySummaryError,
}: SnapshotOverviewViewProps) {
  if (!chainList) {
    return (
      <section
        className="mx-auto max-w-3xl rounded-xl border border-surface-container-highest bg-surface-container p-space-xl text-center shadow-md"
        role="status"
      >
        <span className="material-symbols-outlined text-4xl text-on-surface-variant">database_off</span>
        <h1 className="mt-space-sm font-headline-md text-headline-md font-bold text-on-surface">Snapshot unavailable</h1>
        <p className="mt-space-xs text-on-surface-variant">Load a snapshot from the catalog to view observed chain statistics.</p>
      </section>
    )
  }

  const chains = chainList.chains
  const sizes = chains.map(chain => chain.member_count)
  const totalAlarms = sizes.reduce((sum, value) => sum + value, 0)
  const totalChains = chains.length
  const singletons = chains.filter(chain => chain.is_singleton).length
  const multiAlarmChains = totalChains - singletons
  const singletonShare = totalChains > 0 ? (singletons / totalChains) * 100 : 0
  const buckets = [
    { label: 'Singleton (1)', count: chains.filter(chain => chain.member_count === 1), barClass: 'bg-secondary' },
    { label: '2–5 alarms', count: chains.filter(chain => chain.member_count >= 2 && chain.member_count <= 5), barClass: 'bg-sky-400' },
    { label: '6–20 alarms', count: chains.filter(chain => chain.member_count >= 6 && chain.member_count <= 20), barClass: 'bg-amber-400' },
    { label: '>20 alarms', count: chains.filter(chain => chain.member_count > 20), barClass: 'bg-rose-500' },
  ]
  const isHeavyTail = Math.max(0, ...sizes) > 10
  const attentionChains = qualitySummary?.attention_chains ?? []

  return (
    <div className="flex w-full min-w-0 flex-col gap-space-lg animate-fadeIn select-none">
      {qualitySummaryError ? <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-space-md py-space-sm text-sm text-amber-200" role="alert">Không thể tải trạng thái quality của snapshot: {qualitySummaryError}</div> : null}
      {/* 1. Top Tier: 3 Core Macro KPI Cards */}
      <section className="grid w-full min-w-0 max-w-full grid-cols-1 gap-space-md md:grid-cols-3" aria-label="Observed snapshot metrics">
        {/* Card 1: Observed alarms */}
        <div className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-secondary/40 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold">Observed alarms</span>
            <span className="material-symbols-outlined text-secondary text-[22px]">notifications</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight">
              {totalAlarms.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant mt-1 truncate" title="Sum of returned chain member counts">
              Total alarms across snapshot
            </div>
          </div>
        </div>

        {/* Card 2: Observed chains */}
        <div
          className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-secondary/50 hover:bg-[#101a2e] cursor-pointer flex flex-col justify-between group"
          onClick={() => onNavigate('all-chains')}
          title="Open all chains"
        >
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold group-hover:text-secondary transition-colors">Observed chains</span>
            <span className="material-symbols-outlined text-secondary text-[22px]">device_hub</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight group-hover:text-primary transition-colors">
              {totalChains.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-secondary-fixed mt-1 truncate flex items-center gap-1.5">
              <span className="font-bold text-secondary">{multiAlarmChains.toLocaleString()} multi-alarm</span>
              <span className="text-on-surface-variant/70">·</span>
              <span className="text-tertiary font-semibold">{singletons.toLocaleString()} singletons ({singletonShare.toFixed(0)}%)</span>
            </div>
          </div>
        </div>

        {/* Card 3: persisted quality coverage for multi-alarm chains */}
        <div className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold">Chain quality</span>
            <span className="material-symbols-outlined text-amber-300 text-[22px]">hotel_class</span>
          </div>
          <div className="mt-space-sm">
            {qualitySummary ? (
              <>
                <div className="flex items-baseline gap-1.5">
                  <span className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight">{qualitySummary.eligible_chain_count}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">chain nhiều cảnh báo</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-code-sm text-[11px]">
                  <span className="font-bold text-emerald-300">● {qualitySummary.sturdy_count} vững</span>
                  <span className="font-bold text-amber-300">● {qualitySummary.review_count} cần xem</span>
                  <span className="font-bold text-cyan-300">● {qualitySummary.evaluating_count} đang chạy</span>
                  <span className="text-on-surface-variant">○ {qualitySummary.unevaluated_count} chờ đánh giá</span>
                  <span className="text-[#94a3b8]">◌ {qualitySummary.unavailable_count ?? 0} thiếu evidence</span>
                </div>
              </>
            ) : qualitySummaryLoading ? (
              <div className="flex items-center gap-2 text-sm text-on-surface-variant" role="status">
                <span className="material-symbols-outlined animate-spin text-[18px] text-cyan-300">progress_activity</span>
                Đang đọc kết quả đã lưu…
              </div>
            ) : (
              <div className="text-sm text-on-surface-variant">
                Chưa có kết quả đánh giá được lưu cho {multiAlarmChains} chain nhiều cảnh báo.
              </div>
            )}
            <div className="mt-2 font-code-sm text-[10px] text-[#64748b]">
              Singleton không áp dụng chấm độ vững.
            </div>
          </div>
        </div>
      </section>

      <section className="grid min-w-0 grid-cols-1 gap-space-md">
        <article className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm">
          <div className="flex items-center justify-between border-b border-[#1a253c] pb-3">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[20px]">bar_chart</span>
              <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Observed chain-size distribution</h2>
            </div>
            <span className="rounded border border-[#22304c] bg-[#141d30] px-2 py-0.5 font-code-sm text-[11px] text-on-surface-variant">
              {totalChains.toLocaleString()} chains
            </span>
          </div>
          <div className="mt-space-md space-y-space-sm">
            {buckets.map(bucket => {
              const share = totalChains > 0 ? (bucket.count.length / totalChains) * 100 : 0
              return (
                <div key={bucket.label} className="space-y-1">
                  <div className="flex items-center justify-between text-code-sm">
                    <span className="font-medium text-on-surface">{bucket.label}</span>
                    <span className="font-bold text-on-surface-variant">
                      {bucket.count.length.toLocaleString()} <span className="font-normal text-[11px] text-[#64748b]">({share.toFixed(1)}%)</span>
                    </span>
                  </div>
                  <div className="h-2.5 w-full overflow-hidden rounded-full border border-[#192339] bg-[#080d17] p-0.5">
                    <div className={`h-full rounded-full transition-all duration-500 ${bucket.barClass}`} style={{ width: `${Math.max(share > 0 ? 1.5 : 0, share)}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
          <div className="mt-space-md grid grid-cols-3 gap-2 border-t border-[#1a253c] pt-space-sm">
            <div className="rounded-lg border border-[#172136] bg-[#080d17] p-2.5">
              <span className="block text-[10px] uppercase tracking-wider text-on-surface-variant font-label-caps">Avg Size</span>
              <span className="mt-0.5 block truncate font-code-sm text-sm font-bold text-on-surface">{totalChains > 0 ? (totalAlarms / totalChains).toFixed(1) : 0} <span className="text-[11px] font-normal text-on-surface-variant">alarms</span></span>
            </div>
            <div className="rounded-lg border border-[#172136] bg-[#080d17] p-2.5">
              <span className="block text-[10px] uppercase tracking-wider text-on-surface-variant font-label-caps">Singletons</span>
              <span className="mt-0.5 block truncate font-code-sm text-sm font-bold text-secondary">{singletonShare.toFixed(0)}% <span className="text-[11px] font-normal text-on-surface-variant">({singletons})</span></span>
            </div>
            <div className="rounded-lg border border-[#172136] bg-[#080d17] p-2.5">
              <span className="block text-[10px] uppercase tracking-wider text-on-surface-variant font-label-caps">Tail Skew</span>
              <span className={`mt-0.5 block truncate font-code-sm text-sm font-bold ${isHeavyTail ? 'text-rose-400' : 'text-emerald-400'}`}>{isHeavyTail ? 'Heavy Tail' : 'Normal'}</span>
            </div>
          </div>
        </article>

      </section>

      {/* 3. Bottom Tier: action-first quality queue */}
      <section className="min-w-0 overflow-hidden rounded-xl border border-[#1e2b44] bg-[#0c1322] shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-sm border-b border-[#1a253c] px-space-md py-3 bg-[#0f1728]">
          <div className="flex items-center gap-2.5">
            <div className="h-8 w-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <span className="material-symbols-outlined text-[18px]">priority_high</span>
            </div>
            <div>
              <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Chain cần xem trước</h2>
              <p className="text-code-sm text-xs text-on-surface-variant">Ưu tiên chain điểm thấp; tiếp theo là các chain đang chạy hoặc chưa được đánh giá.</p>
            </div>
          </div>

        </div>

        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-code-sm">
            <thead>
              <tr className="bg-[#080d17] font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant border-b border-[#1a253c]">
                <th className="px-space-md py-2.5">Chain</th>
                <th className="px-space-md py-2.5">Nhận định hiện tại</th>
                <th className="px-space-md py-2.5 text-right">Duration</th>
                <th className="px-space-md py-2.5 text-right">Quality</th>
                <th className="px-space-md py-2.5 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f33]">
              {attentionChains.map(chain => (
                <tr
                  key={chain.chain_id}
                  onClick={() => onSelectChain(chain.chain_id)}
                  className="hover:bg-[#101a2e] transition-colors cursor-pointer group"
                >
                  <td className="px-space-md py-3 font-bold text-primary">
                    <button
                      type="button"
                      className="rounded text-left group-hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-secondary flex items-center gap-2"
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectChain(chain.chain_id)
                      }}
                    >
                      <span className="material-symbols-outlined text-[16px] text-secondary">device_hub</span>
                      <span>{chain.chain_id}</span>
                    </button>
                  </td>
                  <td className="max-w-[430px] px-space-md py-3">
                    <strong className="block truncate text-on-surface" title={chain.title}>{chain.title}</strong>
                    <span className="block truncate text-[11px] text-on-surface-variant" title={chain.reason ?? undefined}>{chain.reason ?? chain.label}</span>
                  </td>
                  <td className="px-space-md py-3 text-right font-code-sm text-on-surface-variant">
                    {chain.duration_seconds != null ? formatDuration(chain.duration_seconds) : '—'}
                  </td>
                  <td className="px-space-md py-3 text-right">
                    {chain.stars != null ? (
                      <span className="font-bold text-amber-300">{'★'.repeat(chain.stars)}{'☆'.repeat(5 - chain.stars)}</span>
                    ) : (
                      <span className={`rounded px-2 py-1 text-[10px] font-bold ${chain.status === 'EVALUATING' ? 'bg-cyan-400/10 text-cyan-300' : 'bg-surface-container-high text-on-surface-variant'}`}>{chain.label}</span>
                    )}
                  </td>
                  <td className="px-space-md py-3 text-center">
                    <button
                      type="button"
                      className="rounded border border-secondary/40 bg-secondary/10 px-2.5 py-1 font-code-sm text-xs font-semibold text-secondary hover:bg-secondary hover:text-on-secondary transition-colors"
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectChain(chain.chain_id)
                      }}
                    >
                      Mở →
                    </button>
                  </td>
                </tr>
              ))}
              {attentionChains.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-space-md py-space-lg text-center text-on-surface-variant">
                    Không có chain nào đang chờ xử lý hoặc cần xem lại.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <span className="sr-only">{chainList.snapshot_id}@{chainList.snapshot_version}</span>
    </div>
  )
}
