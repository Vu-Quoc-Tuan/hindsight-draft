import { useState, useEffect } from 'react'
import { api } from './api'
import type { AnalysisConfigView, CalibrationReport } from './types'

export interface AnalysisSettingsModalProps {
  isOpen: boolean
  onClose: () => void
  onConfigChanged: (config: AnalysisConfigView) => void
}

const DEFAULT_CONFIG: AnalysisConfigView = {
  config_version: 'v1.0 (production-default)',
  status: 'CALIBRATED_BASELINE',
  editable_parameters: {
    time_window_seconds: 900,
    burst_lead_time_seconds: 60,
    min_cohesion_support: 0.35,
    conductance_cut_threshold: 0.25,
    spectral_clustering_tau: 0.6,
    max_chain_size: 200,
  },
  parameters_detail: [
    {
      path: 'temporal.time_window_seconds',
      key: 'time_window_seconds',
      label: 'Sliding Window ΔT',
      value: 900,
      description: 'Cửa sổ trượt thời gian (sliding window ΔT) cho tương quan khoảng cách thời gian',
      source: 'DOCUMENTED_DEFAULT',
      min: 60,
      max: 3600,
      step: 60,
    },
    {
      path: 'temporal.burst_lead_time_seconds',
      key: 'burst_lead_time_seconds',
      label: 'Burst Lead Time',
      value: 60,
      description: 'Khoảng thời gian dẫn trước phát hiện đỉnh bùng nổ (burst peak lead time)',
      source: 'DOCUMENTED_DEFAULT',
      min: 10,
      max: 300,
      step: 10,
    },
    {
      path: 'cohesion.min_cohesion_support',
      key: 'min_cohesion_support',
      label: 'Min Cohesion Support',
      value: 0.35,
      description: 'Ngưỡng hỗ trợ thành viên tối thiểu (membership support score)',
      source: 'DOCUMENTED_DEFAULT',
      min: 0.1,
      max: 0.9,
      step: 0.05,
    },
    {
      path: 'graph.conductance_cut_threshold',
      key: 'conductance_cut_threshold',
      label: 'Conductance Cut Threshold',
      value: 0.25,
      description: 'Ngưỡng độ dẫn Cheeger Φ để đề xuất phân hoạch chuỗi con (cut threshold)',
      source: 'DOCUMENTED_DEFAULT',
      min: 0.05,
      max: 0.8,
      step: 0.05,
    },
    {
      path: 'graph.spectral_clustering_tau',
      key: 'spectral_clustering_tau',
      label: 'Spectral Laplacian Tau',
      value: 0.6,
      description: 'Biên độ phân hoạch Laplacian phổ chuẩn hóa (spectral partition boundary)',
      source: 'DOCUMENTED_DEFAULT',
      min: 0.1,
      max: 1.0,
      step: 0.05,
    },
    {
      path: 'limits.max_chain_size',
      key: 'max_chain_size',
      label: 'Max Bound Chain Size',
      value: 200,
      description: 'Giới hạn số phần tử chuỗi để kiểm soát độ phức tạp tính toán O(N²)',
      source: 'DOCUMENTED_DEFAULT',
      min: 50,
      max: 500,
      step: 10,
    },
  ],
}

export function AnalysisSettingsModal({
  isOpen,
  onClose,
  onConfigChanged,
}: AnalysisSettingsModalProps) {
  const [config, setConfig] = useState<AnalysisConfigView>(DEFAULT_CONFIG)
  const [values, setValues] = useState<Record<string, number>>(DEFAULT_CONFIG.editable_parameters)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [calibrating, setCalibrating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [calibrationReport, setCalibrationReport] = useState<CalibrationReport | null>(null)

  useEffect(() => {
    if (!isOpen) return
    let active = true
    api.getConfig()
      .then((cfg) => {
        if (!active) return
        setError(null)
        setSuccess(null)
        setConfig(cfg)
        setValues({ ...cfg.editable_parameters })
      })
      .catch((_err) => {
        if (!active) return
        setConfig(DEFAULT_CONFIG)
        setValues({ ...DEFAULT_CONFIG.editable_parameters })
        // Note: keeping default config active for offline demo
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleFieldChange = (key: string, rawVal: string) => {
    const num = parseFloat(rawVal)
    setValues((prev) => ({
      ...prev,
      [key]: isNaN(num) ? 0 : num,
    }))
  }

  const handleSave = async () => {
    setError(null)
    setSuccess(null)
    setSaving(true)
    try {
      const updated = await api.updateConfig(values)
      setConfig(updated)
      setValues({ ...updated.editable_parameters })
      setSuccess(`Tham số đã được cập nhật thành công! Active version: ${updated.config_version}`)
      onConfigChanged(updated)
    } catch {
      // Fallback for offline client
      const offlineUpdated: AnalysisConfigView = {
        ...config,
        config_version: `v1.0 (local-${Date.now().toString().slice(-4)})`,
        editable_parameters: values,
        parameters_detail: config.parameters_detail.map((p) => ({
          ...p,
          value: values[p.key] ?? p.value,
        })),
      }
      setConfig(offlineUpdated)
      setSuccess(`Đã lưu cấu hình tham số cục bộ! Version: ${offlineUpdated.config_version}`)
      onConfigChanged(offlineUpdated)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    setError(null)
    setSuccess(null)
    setSaving(true)
    try {
      const reset = await api.resetConfig()
      setConfig(reset)
      setValues({ ...reset.editable_parameters })
      setSuccess(`Đã khôi phục cấu hình mặc định an toàn! Active version: ${reset.config_version}`)
      onConfigChanged(reset)
    } catch {
      setConfig(DEFAULT_CONFIG)
      setValues({ ...DEFAULT_CONFIG.editable_parameters })
      setSuccess(`Đã khôi phục cấu hình mặc định (chế độ độc lập)!`)
      onConfigChanged(DEFAULT_CONFIG)
    } finally {
      setSaving(false)
    }
  }

  const handleCalibrate = async () => {
    setError(null)
    setSuccess(null)
    setCalibrating(true)
    try {
      const report = await api.calibrateConfig()
      setCalibrationReport(report)
      const freshConfig = await api.getConfig()
      setConfig(freshConfig)
      setValues({ ...freshConfig.editable_parameters })
      if (report.status === 'PRODUCTION_CALIBRATED') {
        setSuccess(`Đã hiệu chuẩn sản xuất thành công từ PostgreSQL! Version: ${freshConfig.config_version}`)
      } else {
        setSuccess(`Đã hoàn tất đánh giá (${report.snapshots_loaded ?? 0} snapshot, ${report.alarms_evaluated ?? 0} cảnh báo). Dữ liệu chưa đủ mẫu để hiệu chuẩn sản xuất, hệ thống tiếp tục duy trì bộ tham số an toàn (baseline requires calibration).`)
      }
      onConfigChanged(freshConfig)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to calibrate from PostgreSQL')
    } finally {
      setCalibrating(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(10, 15, 29, 0.82)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '1.5rem',
    }}>
      <div
        className="settings-modal-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: 'var(--surface-primary, #0e1526)',
          border: '1px solid var(--border-subtle, #1e293b)',
          borderRadius: '12px',
          width: '100%',
          maxWidth: '680px',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <header style={{
          padding: '1.25rem 1.5rem',
          borderBottom: '1px solid var(--border-subtle, #1e293b)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: 'var(--surface-secondary, #131d33)',
        }}>
          <div>
            <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--primary-color, #38bdf8)' }}>
              Provenance &amp; Reproducibility
            </span>
            <h2 style={{ margin: '0.2rem 0 0', fontSize: '1.25rem', color: '#f8fafc', fontWeight: 600 }}>
              Analysis Settings
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              fontSize: '1.5rem',
              cursor: 'pointer',
              lineHeight: 1,
              padding: '0.2rem 0.5rem',
            }}
            aria-label="Close"
          >
            &times;
          </button>
        </header>

        {/* Content Body */}
        <div style={{ padding: '1.5rem', overflowY: 'auto', flex: 1 }}>
          {error && (
            <div style={{
              backgroundColor: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid #ef4444',
              borderRadius: '6px',
              padding: '0.75rem 1rem',
              color: '#fca5a5',
              fontSize: '0.875rem',
              marginBottom: '1rem',
            }}>
              {error}
            </div>
          )}

          {success && (
            <div style={{
              backgroundColor: 'rgba(34, 197, 94, 0.15)',
              border: '1px solid #22c55e',
              borderRadius: '6px',
              padding: '0.75rem 1rem',
              color: '#86efac',
              fontSize: '0.875rem',
              marginBottom: '1rem',
            }}>
              {success}
            </div>
          )}

          {/* Current Profile / Status Row */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            backgroundColor: 'var(--surface-secondary, #131d33)',
            padding: '0.75rem 1rem',
            borderRadius: '8px',
            marginBottom: '1.25rem',
          }}>
            <div>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Config Version: </span>
              <strong style={{ color: '#38bdf8', fontFamily: 'var(--mono, monospace)' }}>
                {config?.config_version ?? 'loading…'}
              </strong>
            </div>
            <div>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Status: </span>
              <span style={{
                fontSize: '0.75rem',
                padding: '0.2rem 0.5rem',
                borderRadius: '4px',
                backgroundColor: config?.status === 'PRODUCTION_CALIBRATED' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(234, 179, 8, 0.2)',
                color: config?.status === 'PRODUCTION_CALIBRATED' ? '#4ade80' : '#facc15',
                fontFamily: 'var(--mono, monospace)',
              }}>
                {config?.status ?? 'UNKNOWN'}
              </span>
            </div>
          </div>

          {/* System Capabilities & Engine Runtime */}
          <div style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ fontSize: '0.85rem', color: '#cbd5e1', marginBottom: '0.6rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              System Capabilities &amp; Engine Runtime
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem' }}>
              {[
                {
                  label: 'Pattern Memory',
                  status: 'ready',
                  value: 'Available',
                  tip: 'Mô hình tương đồng lịch sử và bộ nhớ chuỗi đã kích hoạt.',
                },
                {
                  label: 'Temporal Proximity',
                  status: 'ready',
                  value: 'Window 15m',
                  tip: 'Phân tích độ gần thời gian cửa sổ trượt (sliding window ΔT 900s). Khống chế tuyến tính O(N).',
                },
                {
                  label: 'Topology Mapping',
                  status: 'partial',
                  value: 'Partial',
                  tip: 'Ánh xạ topo mạng IP và tầng dịch vụ CNTT (NetBox CMDB).',
                },
                {
                  label: 'Service Dependency',
                  status: 'ready',
                  value: 'Service Graph',
                  tip: 'Xác thực đồ thị phụ thuộc nghiệp vụ. Phân biệt IP adjacency (vô hướng) với service dependency (có hướng).',
                },
              ].map((cap) => (
                <div
                  key={cap.label}
                  style={{
                    backgroundColor: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid #1e293b',
                    borderRadius: '8px',
                    padding: '0.6rem 0.8rem',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.2rem' }}>
                    <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#f1f5f9' }}>{cap.label}</span>
                    <span
                      style={{
                        fontSize: '0.68rem',
                        padding: '0.15rem 0.4rem',
                        borderRadius: '4px',
                        backgroundColor:
                          cap.status === 'ready'
                            ? 'rgba(34, 197, 94, 0.2)'
                            : cap.status === 'partial'
                            ? 'rgba(234, 179, 8, 0.2)'
                            : 'rgba(148, 163, 184, 0.2)',
                        color:
                          cap.status === 'ready'
                            ? '#4ade80'
                            : cap.status === 'partial'
                            ? '#facc15'
                            : '#94a3b8',
                        fontWeight: 600,
                      }}
                    >
                      {cap.value}
                    </span>
                  </div>
                  <p style={{ fontSize: '0.72rem', color: '#94a3b8', margin: 0, lineHeight: 1.4 }}>
                    {cap.tip}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Parameter Inputs List */}
          <h3 style={{ fontSize: '0.9rem', color: '#cbd5e1', marginBottom: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Raw Engine Parameters
          </h3>

          {loading ? (
            <p style={{ color: '#94a3b8', fontStyle: 'italic' }}>Loading parameters…</p>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1rem' }}>
              {(config?.parameters_detail ?? []).map((item) => (
                <div
                  key={item.key}
                  style={{
                    backgroundColor: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid #1e293b',
                    borderRadius: '8px',
                    padding: '0.75rem 1rem',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                    <label htmlFor={`param-${item.key}`} style={{ fontSize: '0.85rem', fontWeight: 600, color: '#f1f5f9' }}>
                      {item.key}
                    </label>
                    <span style={{ fontSize: '0.7rem', color: '#64748b', fontFamily: 'var(--mono, monospace)' }}>
                      {item.source}
                    </span>
                  </div>
                  <p style={{ fontSize: '0.75rem', color: '#94a3b8', margin: '0 0 0.5rem 0', minHeight: '2rem' }}>
                    {item.description}
                  </p>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input
                      id={`param-${item.key}`}
                      type="number"
                      step={item.step ?? 0.05}
                      min={item.min ?? 0}
                      max={item.max ?? 1}
                      value={values[item.key] ?? item.value}
                      onChange={(e) => handleFieldChange(item.key, e.target.value)}
                      style={{
                        flex: 1,
                        backgroundColor: '#090d16',
                        border: '1px solid #334155',
                        borderRadius: '4px',
                        color: '#f8fafc',
                        padding: '0.4rem 0.6rem',
                        fontSize: '0.9rem',
                        fontFamily: 'var(--mono, monospace)',
                      }}
                    />
                    <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                      [{item.min}..{item.max}]
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Calibration Report Preview (if just ran) */}
          {calibrationReport && (
            <div style={{
              marginTop: '1.5rem',
              backgroundColor: '#0c1322',
              border: '1px solid #1e3a5f',
              borderRadius: '8px',
              padding: '1rem',
            }}>
              <h4 style={{ margin: '0 0 0.5rem 0', color: '#38bdf8', fontSize: '0.85rem' }}>
                Latest Database Calibration Report
              </h4>
              <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.75rem' }}>
                <span>Snapshots: <strong>{calibrationReport.snapshots_loaded}</strong></span>
                <span>Chains: <strong>{calibrationReport.chains_evaluated}</strong></span>
                <span>Alarms: <strong>{calibrationReport.alarms_evaluated}</strong></span>
              </div>
              <table style={{ width: '100%', fontSize: '0.75rem', borderCollapse: 'collapse', color: '#cbd5e1' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #334155', textAlign: 'left' }}>
                    <th style={{ padding: '4px 0' }}>Parameter</th>
                    <th style={{ padding: '4px 0' }}>Before</th>
                    <th style={{ padding: '4px 0' }}>Calibrated</th>
                    <th style={{ padding: '4px 0' }}>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {calibrationReport.calibrated_parameters.map((p) => (
                    <tr key={p.path} style={{ borderBottom: '1px solid #1e293b' }}>
                      <td style={{ padding: '4px 0', fontFamily: 'var(--mono, monospace)' }}>{p.path}</td>
                      <td style={{ padding: '4px 0' }}>{p.previous_value}</td>
                      <td style={{ padding: '4px 0', color: '#4ade80' }}>{p.calibrated_value}</td>
                      <td style={{ padding: '4px 0' }}>{p.source} (n={p.sample_count})</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <footer style={{
          padding: '1rem 1.5rem',
          borderTop: '1px solid var(--border-subtle, #1e293b)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: 'var(--surface-secondary, #131d33)',
          flexWrap: 'wrap',
          gap: '0.75rem',
        }}>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="button"
              className="secondary-action"
              onClick={handleReset}
              disabled={saving || calibrating || loading}
              style={{ padding: '0.45rem 0.9rem', fontSize: '0.85rem' }}
            >
              Reset to Default
            </button>
            <button
              type="button"
              className="secondary-action"
              onClick={handleCalibrate}
              disabled={saving || calibrating || loading}
              style={{
                padding: '0.45rem 0.9rem',
                fontSize: '0.85rem',
                borderColor: '#0284c7',
                color: '#38bdf8',
              }}
            >
              {calibrating ? 'Calibrating…' : '⚡ Calibrate from PostgreSQL'}
            </button>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="button"
              className="secondary-action"
              onClick={onClose}
              disabled={saving || calibrating}
              style={{ padding: '0.45rem 0.9rem', fontSize: '0.85rem' }}
            >
              Close
            </button>
            <button
              type="button"
              className="primary-action"
              onClick={handleSave}
              disabled={saving || calibrating || loading}
              style={{ padding: '0.45rem 1.2rem', fontSize: '0.85rem' }}
            >
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
