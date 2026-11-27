import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download, FileBarChart, Plus, RefreshCw, Trash2 } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect, fmtTime, todayStr } from '../components/ui'

const STATUS_OPTIONS = [
  { value: 'attended', label: 'Present / half day' },
  { value: 'late', label: 'Late arrivals' },
  { value: 'absent', label: 'Absent' },
  { value: 'half_day', label: 'Half day' },
  { value: 'leave', label: 'Leave' },
  { value: 'week_off', label: 'Week off' },
  { value: 'holiday', label: 'Holiday' },
]
const PUNCH_TYPES = [
  { value: 'in', label: 'Check in' }, { value: 'out', label: 'Check out' },
  { value: 'break_in', label: 'Break in' }, { value: 'break_out', label: 'Break out' },
]
const QUICK_RANGES = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'this_week', label: 'This week' },
  { value: 'last_7_working_days', label: 'Last 7 working days' },
  { value: 'custom', label: 'Custom range' },
]
const dateText = (value) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
const addDays = (value, days) => new Date(value.getFullYear(), value.getMonth(), value.getDate() + days)
const weekStart = () => {
  const today = new Date()
  const weekday = today.getDay() || 7
  return addDays(today, 1 - weekday)
}
const lastWorkingDaysStart = (count = 7) => {
  const today = new Date()
  let cursor = today
  let workingDays = 0
  while (workingDays < count) {
    const weekday = cursor.getDay()
    if (weekday !== 0 && weekday !== 6) workingDays += 1
    if (workingDays < count) cursor = addDays(cursor, -1)
  }
  return dateText(cursor)
}

export default function Attendance() {
  const { has } = useAuth()
  const canManage = has('attendance.manage')
  const canViewAll = has('employee.view')
  const [searchParams] = useSearchParams()
  const day = searchParams.get('date')
  const hasUrlDates = Boolean(searchParams.get('from') || searchParams.get('to') || day)
  const [tab, setTab] = useState('records')
  const [quickRange, setQuickRange] = useState(hasUrlDates ? 'custom' : 'today')
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [employees, setEmployees] = useState([])
  const [designations, setDesignations] = useState([])
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState({
    from_date: searchParams.get('from') || day || todayStr(),
    to_date: searchParams.get('to') || day || todayStr(),
    employee_id: searchParams.get('employee_id') || '',
    designation_id: searchParams.get('designation_id') || '',
    status: searchParams.get('status') || '',
  })
  const [punchModal, setPunchModal] = useState(false)
  const [punch, setPunch] = useState({ employee_id: '', punch_time: `${todayStr()}T09:00`, punch_type: 'in' })
  const [recomputeModal, setRecomputeModal] = useState(false)
  const [recomputePlan, setRecomputePlan] = useState(null)
  const [recomputing, setRecomputing] = useState(false)

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ from_date: filters.from_date, to_date: filters.to_date, limit: '500' })
    if (filters.employee_id) params.set('employee_id', filters.employee_id)
    if (filters.designation_id) params.set('designation_id', filters.designation_id)
    if (filters.status && tab === 'records') params.set('status', filters.status)
    api.get(`/attendance/${tab === 'records' ? 'records' : 'logs'}?${params}`)
      .then((r) => { setRows(r.data.items); setTotal(r.data.total) })
      .catch((e) => setError(errorMessage(e))).finally(() => setLoading(false))
  }

  const setDate = (key, value) => {
    setQuickRange('custom')
    setError('')
    setNotice('')
    setFilters((current) => ({ ...current, [key]: value }))
  }

  const applyQuickRange = (value) => {
    setQuickRange(value)
    setError('')
    setNotice('')
    if (value === 'today') {
      setFilters((current) => ({ ...current, from_date: todayStr(), to_date: todayStr() }))
    } else if (value === 'yesterday') {
      const yesterday = dateText(addDays(new Date(), -1))
      setFilters((current) => ({ ...current, from_date: yesterday, to_date: yesterday }))
    } else if (value === 'this_week') {
      setFilters((current) => ({ ...current, from_date: dateText(weekStart()), to_date: todayStr() }))
    } else if (value === 'last_7_working_days') {
      setFilters((current) => ({ ...current, from_date: lastWorkingDaysStart(7), to_date: todayStr() }))
    }
  }

  useEffect(() => {
    if (!canViewAll) return
    api.get('/employees?limit=500').then((r) => {
      setEmployees(r.data.items)
      if (r.data.items.length && !punch.employee_id) setPunch((p) => ({ ...p, employee_id: String(r.data.items[0].id) }))
    }).catch(() => {})
  }, [canViewAll])
  useEffect(() => {
    api.get('/designations').then((r) => setDesignations(r.data)).catch(() => {})
  }, [])
  useEffect(() => {
    const t = setTimeout(load, 150)
    return () => clearTimeout(t)
  }, [filters, tab])

  const recomputeParams = () => {
    const params = new URLSearchParams({ from_date: filters.from_date, to_date: filters.to_date })
    if (filters.employee_id) params.set('employee_id', filters.employee_id)
    if (filters.designation_id) params.set('designation_id', filters.designation_id)
    if (filters.status) params.set('status', filters.status)
    return params
  }

  const openRecompute = async () => {
    setError(''); setNotice(''); setRecomputing(true)
    try {
      const r = await api.post(`/attendance/recompute-view?${recomputeParams()}`)
      setRecomputePlan(r.data); setRecomputeModal(true)
    } catch (err) { setError(errorMessage(err)) } finally { setRecomputing(false) }
  }

  const applyRecompute = async () => {
    setRecomputing(true)
    try {
      const params = recomputeParams()
      params.set('apply', 'true')
      const r = await api.post(`/attendance/recompute-view?${params}`)
      setNotice(r.data.message); setRecomputeModal(false); setRecomputePlan(null); load()
    } catch (err) { setError(errorMessage(err)) } finally { setRecomputing(false) }
  }

  const addPunch = async () => {
    setError('')
    try {
      await api.post('/attendance/logs', { ...punch, employee_id: Number(punch.employee_id), punch_time: punch.punch_time.replace('T', ' ') })
      setPunchModal(false); setNotice('Punch added'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const removePunch = async (row) => {
    if (!window.confirm('Delete this punch log?')) return
    try { await api.delete(`/attendance/logs/${row.id}`); setNotice('Punch deleted'); load() } catch (err) { setError(errorMessage(err)) }
  }

  const exportView = async (format) => {
    setExporting(format); setError(''); setNotice('')
    try {
      const params = new URLSearchParams({
        view: tab, format, from_date: filters.from_date, to_date: filters.to_date,
      })
      if (filters.employee_id) params.set('employee_id', filters.employee_id)
      if (filters.designation_id) params.set('designation_id', filters.designation_id)
      if (tab === 'records' && filters.status) params.set('status', filters.status)
      const response = await api.get(`/attendance/export?${params}`, { responseType: 'blob' })
      const mime = {
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        pdf: 'application/pdf',
      }[format]
      const url = URL.createObjectURL(new Blob([response.data], { type: mime }))
      const link = document.createElement('a')
      link.href = url
      link.download = `attendance_${tab}_${filters.from_date}_${filters.to_date}.${format}`
      link.click()
      URL.revokeObjectURL(url)
      setNotice(`${format.toUpperCase()} download started for the current ${tab === 'records' ? 'daily records' : 'punch logs'} view`)
    } catch (err) { setError(errorMessage(err)) } finally { setExporting('') }
  }

  const recordColumns = [
    { label: 'Date', render: (r) => <span className="strong">{r.record_date}</span> },
    { label: 'Employee', render: (r) => <><span className="strong">{r.employee_name}</span><span className="sub">{r.employee_code}</span></> },
    { label: 'Designation', render: (r) => r.designation_name || '—' },
    { label: 'Shift', render: (r) => r.shift_name || '—' },
    { label: 'Check in', render: (r) => <span className="mono">{fmtTime(r.check_in)}</span> },
    { label: 'Lunch check out', render: (r) => <span className="mono">{fmtTime(r.lunch_out)}</span> },
    { label: 'Lunch check in', render: (r) => <span className="mono">{fmtTime(r.lunch_in)}</span> },
    { label: 'Check out', render: (r) => <span className="mono">{fmtTime(r.check_out)}</span> },
    { label: 'Hours', render: (r) => <span className="mono">{r.total_hours}</span> },
    { label: 'OT', render: (r) => <span className="mono">{r.overtime_hours}</span> },
    { label: 'Late', render: (r) => <span className="mono">{r.late_minutes}m</span> },
    { label: 'Status', render: (r) => <Badge status={r.status} /> },
  ]

  const logColumns = [
    { label: 'Time', render: (r) => <span className="strong">{new Date(r.punch_time).toLocaleString()}</span> },
    { label: 'Employee', render: (r) => r.employee_name || <span style={{ color: '#94a3b8' }}>Unmapped UID {r.device_user_id}</span> },
    { label: 'Device UID', render: (r) => <span className="mono">{r.device_user_id}</span> },
    { label: 'Type', render: (r) => <Badge status={r.punch_type}>{r.punch_type ? r.punch_type.replace('_', ' ') : '—'}</Badge> },
    { label: 'Source', render: (r) => <span className="chip">{r.source}</span> },
    ...(canManage ? [{ label: 'Actions', className: 'text-right', render: (r) => <button className="btn btn-danger btn-sm btn-icon" onClick={() => removePunch(r)}><Trash2 size={14} /></button> }] : []),
  ]

  return (
    <>
      <PageHead title="Attendance" subtitle="Raw punches and computed daily attendance records"
        actions={canManage ? <>
          {tab === 'records' && <button className="btn btn-outline" disabled={recomputing} onClick={openRecompute} title="Check current shift groups and rosters, then apply the changes">
            <RefreshCw size={15} /> Recompute
          </button>}
          <button className="btn btn-primary" onClick={() => setPunchModal(true)}><Plus size={15} /> Manual punch</button>
        </> : null} />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <div className="tabs" style={{ border: 'none', marginBottom: 16 }}>
        <button className={`tab ${tab === 'records' ? 'active' : ''}`} onClick={() => {
          if (tab === 'logs') { setRows([]); setTotal(0) }
          setTab('records')
        }}>Daily records</button>
        <button className={`tab ${tab === 'logs' ? 'active' : ''}`} onClick={() => {
          if (tab !== 'logs') {
            if (quickRange === 'today') {
              setQuickRange('last_7_working_days')
              setFilters((f) => ({ ...f, from_date: lastWorkingDaysStart(7), to_date: todayStr() }))
            }
            setRows([]); setTotal(0)
          }
          setTab('logs')
        }}>Raw punch logs</button>
      </div>
      <Card title={`${tab === 'records' ? 'Daily records' : 'Raw punch logs'} (${total})`}
        subtitle={tab === 'records' ? 'Sorted by employee A–Z' : undefined}
        actions={<div className="export-buttons">
          <button className="btn btn-outline btn-sm" disabled={!!exporting} onClick={() => exportView('xlsx')} title="Download current view as Excel">
            <Download size={14} /> Excel
          </button>
          <button className="btn btn-outline btn-sm" disabled={!!exporting} onClick={() => exportView('pdf')} title="Download current view as PDF">
            <FileBarChart size={14} /> PDF
          </button>
        </div>}>
        <div className="toolbar" style={{ marginTop: 0 }}>
          <div className="field-inline"><label>Quick range</label><SearchableSelect value={quickRange} onChange={applyQuickRange} options={QUICK_RANGES} clearable={false} style={{ width: 175 }} /></div>
          <div className="field-inline"><label>From</label><input type="date" value={filters.from_date} onChange={(e) => setDate('from_date', e.target.value)} style={{ width: 150 }} /></div>
          <div className="field-inline"><label>To</label><input type="date" value={filters.to_date} onChange={(e) => setDate('to_date', e.target.value)} style={{ width: 150 }} /></div>
          {canViewAll && <SearchableSelect
            value={filters.employee_id}
            onChange={(v) => setFilters({ ...filters, employee_id: v })}
            options={employees.map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.first_name} ${e.last_name}` }))}
            placeholder="All employees" style={{ width: 230 }}
          />}
          <SearchableSelect
            value={filters.designation_id}
            onChange={(v) => setFilters({ ...filters, designation_id: v })}
            options={designations.map((d) => ({ value: d.id, label: d.name }))}
            placeholder="All designations" style={{ width: 190 }}
          />
          {tab === 'records' && <SearchableSelect
            value={filters.status}
            onChange={(v) => setFilters({ ...filters, status: v })}
            options={STATUS_OPTIONS} placeholder="All statuses" style={{ width: 160 }}
          />}
        </div>
        <DataTable columns={tab === 'records' ? recordColumns : logColumns} rows={rows} loading={loading} emptyText="No attendance data for this period" />
      </Card>

      {canManage && <Modal open={recomputeModal} onClose={() => setRecomputeModal(false)} title="Recompute attendance"
        footer={<>
          <button className="btn btn-outline" onClick={() => setRecomputeModal(false)}>Cancel</button>
          {!!recomputePlan?.changed && <button className="btn btn-primary" disabled={recomputing} onClick={applyRecompute}>
            <RefreshCw size={15} /> Apply {recomputePlan.changed} change{recomputePlan.changed === 1 ? '' : 's'}
          </button>}
        </>}>
        <div style={{ display: 'grid', gap: 12, fontSize: 13, color: '#475569', lineHeight: 1.6 }}>
          <p style={{ margin: 0 }}>
            Checked <strong>{recomputePlan?.checked ?? 0}</strong> records in the current view against the latest shift groups and rosters.
            {' '}<strong>{recomputePlan?.changed ?? 0}</strong> would change, {recomputePlan?.unchanged ?? 0} already match.
          </p>
          {!!recomputePlan?.changes?.length && <div style={{ maxHeight: 260, overflow: 'auto', border: '1px solid #e2e8f0', borderRadius: 8 }}>
            {recomputePlan.changes.map((change, i) => (
              <div key={`${change.employee_id}-${change.date}-${i}`} style={{ padding: '8px 10px', borderBottom: i === recomputePlan.changes.length - 1 ? 'none' : '1px solid #f1f5f9' }}>
                <div className="strong">{change.employee_name} ({change.employee_code}) · {change.date} · {change.shift}</div>
                <div>{change.fields.map(([label, before, after]) => `${label}: ${before} → ${after}`).join(' · ')}</div>
              </div>
            ))}
          </div>}
          {recomputePlan?.truncated && <p style={{ margin: 0 }}>Showing the first {recomputePlan.changes.length} changes.</p>}
          <p style={{ margin: 0 }}>Night shifts are saved on their start date. Include that date in the range to update a night shift.</p>
        </div>
      </Modal>}

      {canManage && <Modal open={punchModal} onClose={() => setPunchModal(false)} title="Add manual punch"
        footer={<><button className="btn btn-outline" onClick={() => setPunchModal(false)}>Cancel</button><button className="btn btn-primary" onClick={addPunch}>Add punch</button></>}>
        <div className="form-grid">
          <Field label="Employee" full><SearchableSelect value={punch.employee_id} onChange={(v) => setPunch({ ...punch, employee_id: v })} options={employees.map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.first_name} ${e.last_name}` }))} placeholder="Select employee" /></Field>
          <Field label="Punch date & time" full><input type="datetime-local" value={punch.punch_time} onChange={(e) => setPunch({ ...punch, punch_time: e.target.value })} /></Field>
          <Field label="Punch type" full><SearchableSelect value={punch.punch_type} onChange={(v) => setPunch({ ...punch, punch_type: v })} options={PUNCH_TYPES} clearable={false} /></Field>
        </div>
      </Modal>}
    </>
  )
}
