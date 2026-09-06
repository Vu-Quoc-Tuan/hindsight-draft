import { useState, useEffect } from 'react'
import { api } from './api'
import type { AnalysisConfigView, CalibrationReport } from './types'

export interface AnalysisSettingsModalProps {
  isOpen: boolean
  onClose: () => void
  onConfigChanged: (config: AnalysisConfigView) => void
}

export function AnalysisSettingsModal({
  isOpen,
  onClose,
  onConfigChanged,
}: AnalysisSettingsModalProps) {
  const [config, setConfig] = useState<AnalysisConfigView | null>(null)
  const [values, setValues] = useState<Record<string, number>>({})
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
      .catch((err) => {
        if (!active) return
        setError(err instanceof Error ? err.message : 'Failed to load configuration')
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
      setSuccess(`Parameters updated! Active version: ${updated.config_version}`)
      onConfigChanged(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save configuration')
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
      setSuccess(`Configuration restored to default! Active version: ${reset.config_version}`)
      onConfigChanged(reset)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset configuration')
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
