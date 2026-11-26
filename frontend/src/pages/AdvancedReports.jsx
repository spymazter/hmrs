import { useEffect, useMemo, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { Download, FileBarChart, Settings2, RefreshCw } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, MultiSearchableSelect, Notice, PageHead, SearchableSelect, todayStr } from '../components/ui'

const STATUS_COLORS = {
  P: '#16a34a', present: '#16a34a', HD: '#f59e0b', MIS: '#f59e0b',
  A: '#dc2626', absent: '#dc2626', CL: '#0ea5e9', SL: '#0ea5e9',
  EL: '#0ea5e9', LWP: '#dc2626', L: '#0ea5e9', OD: '#6366f1',
  CO: '#6366f1', WO: '#94a3b8', HL: '#8b5cf6',
}

const firstOfMonth = () => `${todayStr().slice(0, 7)}-01`
const DEFAULT_FILTERS = {
  report: 'daily_basic', from_date: firstOfMonth(), to_date: todayStr(),
  department_id: [], location_id: [], designation_id: [], shift_id: [], employee_code: '',
}

function paramString(filters) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => { if (item !== '' && item != null) params.append(key, item) })
    } else if (value !== '' && value != null) {
      params.set(key, value)
    }
  })
  return params.toString()
}

export default function AdvancedReports() {
  const { has } = useAuth()
  const canManage = has('attendance.manage')
  const [meta, setMeta] = useState({ reports: [], departments: [], locations: [], designations: [], shifts: [] })
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [configOpen, setConfigOpen] = useState(false)
  const [config, setConfig] = useState(null)

  useEffect(() => {
    api.get('/attendance/advanced/meta').then((r) => setMeta(r.data)).catch((e) => setError(errorMessage(e)))
    if (canManage) api.get('/attendance/advanced/config').then((r) => setConfig(r.data)).catch(() => {})
  }, [canManage])

  useEffect(() => {
    setLoading(true)
    const timer = setTimeout(() => {
      api.get(`/attendance/advanced/report?${paramString(filters)}`)
        .then((r) => { setData(r.data); setError('') })
        .catch((e) => setError(errorMessage(e)))
        .finally(() => setLoading(false))
    }, 150)
    return () => clearTimeout(timer)
  }, [filters])

  const set = (key, value) => {
    setNotice('')
    setFilters((current) => ({
      ...current,
      [key]: typeof value === 'function' ? value(current[key]) : value,
    }))
  }

  const exportFile = async (format) => {
    setBusy(true); setError('')
    try {
      const response = await api.get(`/attendance/advanced/export?${paramString({ ...filters, format })}`, { responseType: 'blob' })
      const mime = {
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        csv: 'text/csv', json: 'application/json', pdf: 'application/pdf',
      }[format]
      const url = URL.createObjectURL(new Blob([response.data], { type: mime }))
      const link = document.createElement('a')
      link.href = url
      link.download = `advanced_${filters.report}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const saveConfig = async () => {
    setBusy(true); setError('')
    try {
      const payload = { ...config }
      if (typeof payload.authorized_devices === 'string') {
        payload.authorized_devices = payload.authorized_devices.split(',').map((item) => item.trim()).filter(Boolean)
      }
      const response = await api.put('/attendance/advanced/config', payload)
      setConfig(response.data)
      setNotice('Engine settings saved')
      setConfigOpen(false)
      setFilters((current) => ({ ...current }))
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const recalculate = async () => {
    setBusy(true); setError(''); setNotice('')
    try {
      const { report, ...recomputeFilters } = filters
      const response = await api.post(`/attendance/advanced/recompute?${paramString(recomputeFilters)}`)
      setNotice(`${response.data.message} (${response.data.from_date} → ${response.data.to_date})`)
      setFilters((current) => ({ ...current }))
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const statusChart = useMemo(
    () => Object.entries(data?.charts?.status_counts || {}).map(([key, value]) => ({
      name: key, value, color: STATUS_COLORS[key] || '#94a3b8',
    })),
    [data],
  )
  const hoursChart = useMemo(() => (data?.charts?.daily_hours || []).slice(-14), [data])

  const columns = useMemo(() => (data?.columns || []).map((column) => ({
    label: column.label,
    render: (row) => {
      const value = row[column.key]
      if (column.key === 'status_code' || column.key === 'status' || column.key === 'current_state') {
        return <span className="chip" style={{ color: STATUS_COLORS[value] || undefined }}>{value || '—'}</span>
      }
      if (typeof value === 'number') return <span className="mono">{value}</span>
      return value ?? '—'
    },
  })), [data])

  const summaryItems = Object.entries(data?.summary || {}).filter(([, value]) => typeof value === 'number')
  const rows = (data?.rows || []).slice(0, 300)

  return (
    <div className="advanced-reports">
      <PageHead title="Advanced reports" subtitle="Time & attendance reporting engine" />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{notice}</Notice>

      <div className="toolbar">
        <div className="field-inline">
          <label>Report</label>
          <SearchableSelect
            value={filters.report} onChange={(value) => set('report', value)} clearable={false}
            options={meta.reports.map((item) => ({ value: item.id, label: `${item.category} · ${item.name}` }))}
            style={{ width: 320 }}
          />
        </div>
        <div className="field-inline"><label>From</label><input type="date" value={filters.from_date} onChange={(e) => set('from_date', e.target.value)} style={{ width: 145 }} /></div>
        <div className="field-inline"><label>To</label><input type="date" value={filters.to_date} onChange={(e) => set('to_date', e.target.value)} style={{ width: 145 }} /></div>
        <div className="field-inline"><label>Employee code</label><input value={filters.employee_code} placeholder="e.g. DEV-111" onChange={(e) => set('employee_code', e.target.value)} style={{ width: 150 }} /></div>
      </div>
      <div className="toolbar">
        <MultiSearchableSelect value={filters.department_id} onChange={(v) => set('department_id', v)} options={meta.departments.map((d) => ({ value: d.id, label: d.name }))} placeholder="All departments" style={{ width: 190 }} />
        <MultiSearchableSelect value={filters.location_id} onChange={(v) => set('location_id', v)} options={meta.locations.map((d) => ({ value: d.id, label: d.name }))} placeholder="All locations" style={{ width: 180 }} />
        <MultiSearchableSelect value={filters.designation_id} onChange={(v) => set('designation_id', v)} options={meta.designations.map((d) => ({ value: d.id, label: d.name }))} placeholder="All designations" style={{ width: 190 }} />
        <MultiSearchableSelect value={filters.shift_id} onChange={(v) => set('shift_id', v)} options={meta.shifts.map((s) => ({ value: s.id, label: s.name }))} placeholder="All shifts" style={{ width: 170 }} />
      </div>

      <div className="advanced-actions">
        <div className="export-buttons">
          <button className="btn btn-outline" disabled={busy} onClick={() => exportFile('xlsx')}><Download size={15} /> Excel</button>
          <button className="btn btn-outline" disabled={busy} onClick={() => exportFile('csv')}><Download size={15} /> CSV</button>
          <button className="btn btn-outline" disabled={busy} onClick={() => exportFile('json')}><Download size={15} /> JSON</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => exportFile('pdf')}><FileBarChart size={15} /> PDF</button>
        </div>
        {canManage && <div className="export-buttons">
          <button className="btn btn-outline" disabled={busy} onClick={() => config && setConfigOpen(true)}><Settings2 size={15} /> Engine settings</button>
          <button className="btn btn-outline" disabled={busy} title="Uses the current date range, employee and shift filters"
            onClick={recalculate}><RefreshCw size={15} /> {busy ? 'Recalculating…' : 'Recalculate attendance'}</button>
        </div>}
      </div>

      {loading && !data ? <div className="loader">Loading advanced report…</div> : data && (
        <>
          <div className="notice notice-info advanced-description">
            {data.description}
            {data.notes ? ` ${data.notes}` : ''}
            {data.params.length > 0 && <span> · {data.params.join(' · ')}</span>}
          </div>

          {summaryItems.length > 0 && (
            <div className="grid grid-4" style={{ marginBottom: 16 }}>
              {summaryItems.slice(0, 8).map(([key, value]) => (
                <Card key={key} title={key.replaceAll('_', ' ')}><div className="advanced-stat">{value}</div></Card>
              ))}
            </div>
          )}

          <div className="grid grid-2" style={{ marginBottom: 16 }}>
            <Card title="Status distribution" subtitle="Final calculated status codes">
              <div style={{ height: 230 }}>
                {statusChart.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={statusChart} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={78} label>
                        {statusChart.map((item) => <Cell key={item.name} fill={item.color} />)}
                      </Pie>
                      <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : <div className="loader">No status data</div>}
              </div>
            </Card>
            <Card title="Hours by date" subtitle="Net worked hours (last 14 days)">
              <div style={{ height: 230 }}>
                {hoursChart.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={hoursChart} margin={{ top: 8, right: 12 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#64748b' }} interval={1} />
                      <YAxis tick={{ fontSize: 10, fill: '#64748b' }} />
                      <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                      <Bar dataKey="hours" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <div className="loader">No hours recorded</div>}
              </div>
            </Card>
          </div>

          <Card title={`${data.title} · ${data.period_label}`}
            subtitle={`${data.rows.length} rows${data.rows.length > 300 ? ' · showing first 300 (export for all)' : ''}`}>
            <DataTable rows={rows} columns={columns} emptyText="No rows match this filter" />
            {data.legend && (
              <div className="report-legend">
                <span className="strong">Legend:</span>
                {Object.entries(data.legend).map(([code, meaning]) => (
                  <span className="chip" key={code}><strong>{code}</strong> {meaning}</span>
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      <Modal open={configOpen} onClose={() => setConfigOpen(false)} title="Attendance engine settings" width={820}
        footer={<><button className="btn btn-outline" onClick={() => setConfigOpen(false)}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={saveConfig}>Save settings</button></>}>
        {config && <div className="form-grid">
          <Field label="Punch pairing mode" full hint="Strict sums every completed IN/OUT session; first-in/last-out uses total span.">
            <SearchableSelect value={config.pairing_mode} clearable={false}
              onChange={(v) => setConfig({ ...config, pairing_mode: v })}
              options={[{ value: 'strict', label: 'Strict alternating pairs' }, { value: 'first_last', label: 'First in / last out' }]} />
          </Field>
          <Field label="Duplicate debounce (minutes)"><input type="number" min="0" value={config.punch_debounce_minutes} onChange={(e) => setConfig({ ...config, punch_debounce_minutes: +e.target.value })} /></Field>
          <Field label="Half-day hours (below)"><input type="number" step="0.25" value={config.half_day_hours} onChange={(e) => setConfig({ ...config, half_day_hours: +e.target.value })} /></Field>
          <Field label="Full-day hours"><input type="number" step="0.25" value={config.full_day_hours} onChange={(e) => setConfig({ ...config, full_day_hours: +e.target.value })} /></Field>
          <Field label="Minimum OT (minutes)"><input type="number" min="0" value={config.ot_min_minutes} onChange={(e) => setConfig({ ...config, ot_min_minutes: +e.target.value })} /></Field>
          <Field label="OT rounding (minutes)"><input type="number" min="1" value={config.ot_round_minutes} onChange={(e) => setConfig({ ...config, ot_round_minutes: +e.target.value })} /></Field>
          <Field label="Normal OT multiplier"><input type="number" step="0.1" value={config.ot_multiplier} onChange={(e) => setConfig({ ...config, ot_multiplier: +e.target.value })} /></Field>
          <Field label="Holiday OT multiplier"><input type="number" step="0.1" value={config.holiday_ot_multiplier} onChange={(e) => setConfig({ ...config, holiday_ot_multiplier: +e.target.value })} /></Field>
          <Field label="Weekly-off OT multiplier"><input type="number" step="0.1" value={config.weekoff_ot_multiplier} onChange={(e) => setConfig({ ...config, weekoff_ot_multiplier: +e.target.value })} /></Field>
          <Field label="Hours per comp-off day"><input type="number" step="0.5" value={config.comp_off_hours_per_day} onChange={(e) => setConfig({ ...config, comp_off_hours_per_day: +e.target.value })} /></Field>
          <Field label="Continuous absence alert (days)"><input type="number" min="1" value={config.continuous_absence_days} onChange={(e) => setConfig({ ...config, continuous_absence_days: +e.target.value })} /></Field>
          <Field label="Late instances per penalty"><input type="number" min="1" value={config.late_penalty_instances} onChange={(e) => setConfig({ ...config, late_penalty_instances: +e.target.value })} /></Field>
          <Field label="Penalty days"><input type="number" step="0.5" value={config.late_penalty_days} onChange={(e) => setConfig({ ...config, late_penalty_days: +e.target.value })} /></Field>
          <Field label="Sandwich rule" full>
            <label className="chip" style={{ cursor: 'pointer' }}>
              <input type="checkbox" checked={!!config.sandwich_rule} onChange={(e) => setConfig({ ...config, sandwich_rule: e.target.checked })} style={{ marginRight: 6 }} />
              Mark WO/HL absent when bracketed by absences
            </label>
          </Field>
          <Field label="Authorized devices" full hint="Comma-separated device serials. Leave blank to skip the device check.">
            <input value={Array.isArray(config.authorized_devices) ? config.authorized_devices.join(', ') : config.authorized_devices || ''} onChange={(e) => setConfig({ ...config, authorized_devices: e.target.value })} />
          </Field>
        </div>}
      </Modal>
    </div>
  )
}
