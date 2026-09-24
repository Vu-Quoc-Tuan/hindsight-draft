import { useMemo, useState } from 'react'

import { formatDuration } from '../format'
import type { ChainList, ChainQualitySummary } from '../types'

interface AllChainsViewProps {
  chainList: ChainList | null
  qualitySummary?: ChainQualitySummary | null
  qualitySummaryError?: string | null
  onSelectChain: (chainId: string) => void
}

type ChainFilter = 'ALL' | 'MULTI' | 'SINGLETON'
type StarFilter = 'ALL' | 'UNRATED' | 1 | 2 | 3 | 4 | 5

function compactTimestamp(value: string | null): string {
  if (!value) return 'Không có thời gian'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function starText(stars: number | null): string {
  return stars == null ? '☆☆☆☆☆' : `${'★'.repeat(stars)}${'☆'.repeat(5 - stars)}`
}

export function AllChainsView({ chainList, qualitySummary, qualitySummaryError, onSelectChain }: AllChainsViewProps) {
  const [filter, setFilter] = useState<ChainFilter>('ALL')
  const [starFilter, setStarFilter] = useState<StarFilter>('ALL')
  const chains = useMemo(() => chainList?.chains ?? [], [chainList])
  const alarmCount = chains.reduce((total, chain) => total + chain.member_count, 0)
  const qualityByChain = useMemo(() => {
    const entries = qualitySummary?.chain_assessments ?? qualitySummary?.attention_chains ?? []
    return new Map(entries.map(assessment => [assessment.chain_id, assessment]))
  }, [qualitySummary])
  const visibleChains = useMemo(() => {
    return chains.filter(chain => {
      if (filter === 'MULTI' && chain.is_singleton) return false
      if (filter === 'SINGLETON' && !chain.is_singleton) return false
      if (starFilter === 'UNRATED') return qualityByChain.get(chain.chain_id)?.stars == null
      if (starFilter !== 'ALL') return qualityByChain.get(chain.chain_id)?.stars === starFilter
      return true
    })
  }, [chains, filter, qualityByChain, starFilter])

  if (!chainList || chains.length === 0) {
    return (
      <section className="mx-auto max-w-3xl rounded-xl border border-surface-container-highest bg-surface-container p-space-xl text-center shadow-md" role="status">
        <span className="material-symbols-outlined text-4xl text-on-surface-variant">device_hub</span>
        <h1 className="mt-space-sm font-headline-md text-headline-md font-bold text-on-surface">Snapshot chưa có chain</h1>
        <p className="mt-space-xs text-on-surface-variant">Không có chain nào trong snapshot đang mở.</p>
      </section>
    )
  }

  return (
    <div className="flex w-full min-w-0 flex-col gap-space-lg animate-fadeIn">
      {qualitySummaryError ? <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-space-md py-space-sm text-sm text-amber-200" role="alert">Không thể tải số sao quality: {qualitySummaryError}</div> : null}
      <section className="overflow-hidden rounded-xl border border-[#1e2b44] bg-[#0c1322] shadow-sm">
        <div className="flex flex-col gap-space-md border-b border-[#1a253c] bg-[#0f1728] px-space-lg py-space-md lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-secondary">
              <span className="material-symbols-outlined text-[22px]">device_hub</span>
              <span className="font-label-caps text-xs font-bold uppercase tracking-[0.16em]">All chains</span>
            </div>
            <h1 className="mt-2 font-headline-lg text-2xl font-bold text-on-surface">Toàn bộ chain trong snapshot</h1>
            <p className="mt-1 truncate font-code-sm text-sm text-on-surface-variant" title={`${chainList.snapshot_id}@${chainList.snapshot_version}`}>
              {chainList.snapshot_id}@{chainList.snapshot_version} · chọn một chain để mở chi tiết evidence
            </p>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-2 font-code-sm text-xs">
            <div className="rounded-lg border border-[#22304c] bg-[#080d17] px-3 py-2"><span className="block text-on-surface-variant">Chain</span><strong className="text-lg text-on-surface">{chains.length.toLocaleString()}</strong></div>
            <div className="rounded-lg border border-[#22304c] bg-[#080d17] px-3 py-2"><span className="block text-on-surface-variant">Cảnh báo</span><strong className="text-lg text-on-surface">{alarmCount.toLocaleString()}</strong></div>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm" aria-label="Chain filters">
        <div className="flex flex-col gap-space-sm border-b border-[#1a253c] pb-space-sm md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="font-headline-md text-lg font-bold text-on-surface">Bộ lọc chain</h2>
            <p className="mt-1 text-xs text-on-surface-variant">Lọc theo loại chain hoặc số sao quality đã có.</p>
          </div>
          <span className="font-code-sm text-xs text-on-surface-variant">Hiển thị {visibleChains.length} / {chains.length}</span>
        </div>
        <div className="mt-space-md flex flex-col gap-space-md">
          <div className="flex flex-wrap items-center gap-2" aria-label="Chain filter">
            <span className="mr-1 font-label-caps text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Phân loại</span>
            {([
              ['ALL', `Tất cả (${chains.length})`],
              ['MULTI', `Multi-alarm (${chains.filter(chain => !chain.is_singleton).length})`],
              ['SINGLETON', `Singleton (${chains.filter(chain => chain.is_singleton).length})`],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
                className={`rounded-lg border px-3 py-1.5 font-code-sm text-xs font-semibold transition-colors ${filter === value ? 'border-secondary bg-secondary text-[#07101d]' : 'border-[#293754] bg-[#080d17] text-on-surface-variant hover:border-secondary/50 hover:text-on-surface'}`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2" aria-label="Star filter">
            <span className="mr-1 font-label-caps text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Lọc theo sao</span>
            {([
              ['ALL', 'Tất cả'],
              [5, '5 sao'],
              [4, '4 sao'],
              [3, '3 sao'],
              [2, '2 sao'],
              [1, '1 sao'],
              ['UNRATED', 'Chưa chấm'],
            ] as const).map(([value, label]) => (
              <button
                key={String(value)}
                type="button"
                aria-pressed={starFilter === value}
                onClick={() => setStarFilter(value)}
                className={`rounded-lg border px-2.5 py-1.5 font-code-sm text-xs font-semibold transition-colors ${starFilter === value ? 'border-amber-300 bg-amber-300 text-[#07101d]' : 'border-[#293754] bg-[#080d17] text-amber-200/80 hover:border-amber-300/50 hover:text-amber-200'}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-xl border border-[#1e2b44] bg-[#0c1322] shadow-sm" aria-label="All chains list">
        <div className="flex flex-col gap-space-sm border-b border-[#1a253c] bg-[#0f1728] px-space-md py-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="font-headline-md text-lg font-bold text-on-surface">Danh sách chain</h2>
            <p className="mt-1 text-xs text-on-surface-variant">Chọn một chain để mở chi tiết evidence và `Timeline &amp; Evolution`.</p>
          </div>
          <span className="font-code-sm text-xs text-on-surface-variant">{visibleChains.length} kết quả</span>
        </div>
        <div className="divide-y divide-[#151f33]">
          {visibleChains.map(chain => (
            <button key={chain.chain_id} type="button" onClick={() => onSelectChain(chain.chain_id)} className="grid w-full grid-cols-1 gap-3 px-space-md py-3.5 text-left transition-colors hover:bg-[#101a2e] md:grid-cols-[minmax(120px,0.7fr)_minmax(220px,1.8fr)_minmax(120px,0.7fr)_minmax(190px,1fr)_auto] md:items-center">
              <span className="font-code-sm text-sm font-bold text-primary">{chain.chain_id}</span>
              <span className="min-w-0"><span className="block truncate text-sm font-semibold text-on-surface" title={chain.title}>{chain.title || 'Không có tiêu đề'}</span><span className="font-code-sm text-[10px] uppercase tracking-wider text-on-surface-variant">{chain.is_singleton ? 'Singleton' : 'Multi-alarm chain'}</span></span>
              <span className="flex items-center gap-2" aria-label={qualityByChain.get(chain.chain_id)?.stars == null ? (qualityByChain.get(chain.chain_id)?.label ?? 'Chưa chấm') : `${qualityByChain.get(chain.chain_id)?.stars} trên 5 sao`}>
                <span className="text-lg tracking-[0.1em] text-amber-300" aria-hidden="true">{starText(qualityByChain.get(chain.chain_id)?.stars ?? null)}</span>
                <span className="font-code-sm text-[11px] text-on-surface-variant">{qualityByChain.get(chain.chain_id)?.stars != null ? `${qualityByChain.get(chain.chain_id)?.stars}/5` : (qualityByChain.get(chain.chain_id)?.label ?? 'Chưa chấm')}</span>
              </span>
              <span className="font-code-sm text-xs text-on-surface-variant">{chain.member_count} cảnh báo · {formatDuration(chain.duration_seconds)}<br /><span className="text-[10px]">{compactTimestamp(chain.start_time)}</span></span>
              <span className="font-code-sm text-xs font-bold text-secondary">Mở →</span>
            </button>
          ))}
          {visibleChains.length === 0 ? <div className="py-16 text-center text-on-surface-variant"><span className="material-symbols-outlined mb-2 block text-3xl">search_off</span>Không có chain phù hợp.</div> : null}
        </div>
      </section>
    </div>
  )
}
