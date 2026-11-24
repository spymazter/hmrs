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

export default function Attendance() {
  const { has } = useAuth()
  const canManage = has('attendance.manage')
  const canViewAll = has('employee.view')
  const [searchParams] = useSearchParams()
  const day = searchParams.get('date')
  const [tab, setTab] = useState('records')
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState({
    from_date: searchParams.get('from') || day || todayStr(),
    to_date: searchParams.get('to') || day || todayStr(),
    employee_id: searchParams.get('employee_id') || '',
    status: searchParams.get('status') || '',
  })
  const [punchModal, setPunchModal] = useState(false)
  const [punch, setPunch] = useState({ employee_id: '', punch_time: `${todayStr()}T09:00`, punch_type: 'in' })

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ from_date: filters.from_date, to_date: filters.to_date, limit: '500' })
    if (filters.employee_id) params.set('employee_id', filters.employee_id)
    if (filters.status && tab === 'records') params.set('status', filters.status)
    api.get(`/attendance/${tab === 'records' ? 'records' : 'logs'}?${params}`)
      .then((r) => { setRows(r.data.items); setTotal(r.data.total) })
      .catch((e) => setError(errorMessage(e))).finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!canViewAll) return
    api.get('/employees?limit=500').then((r) => {
      setEmployees(r.data.items)
      if (r.data.items.length && !punch.employee_id) setPunch((p) => ({ ...p, employee_id: String(r.data.items[0].id) }))
    }).catch(() => {})
  }, [canViewAll])
  useEffect(() => {
    const t = setTimeout(load, 150)
    return () => clearTimeout(t)
  }, [filters, tab])

  const recompute = async () => {
    setError(''); setNotice('')
    try {
      const r = await api.post(`/attendance/recompute?from_date=${filters.from_date}&to_date=${filters.to_date}`)
      setNotice(r.data.message); load()
    } catch (err) { setError(errorMessage(err)) }
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
    { label: 'Shift', render: (r) => r.shift_name || '—' },
    { label: 'Check in', render: (r) => <span className="mono">{fmtTime(r.check_in)}</span> },
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
          <button className="btn btn-outline" onClick={recompute}><RefreshCw size={15} /> Recompute</button>
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
            if (filters.from_date === todayStr()) {
              const yearAgo = new Date(Date.now() - 364 * 86400000).toISOString().slice(0, 10)
              setFilters((f) => ({ ...f, from_date: yearAgo }))
            }
            setRows([]); setTotal(0)
          }
          setTab('logs')
        }}>Raw punch logs</button>
      </div>
      <Card title={`${tab === 'records' ? 'Daily records' : 'Raw punch logs'} (${total})`}
        actions={<div className="export-buttons">
          <button className="btn btn-outline btn-sm" disabled={!!exporting} onClick={() => exportView('xlsx')} title="Download current view as Excel">
            <Download size={14} /> Excel
          </button>
          <button className="btn btn-outline btn-sm" disabled={!!exporting} onClick={() => exportView('pdf')} title="Download current view as PDF">
            <FileBarChart size={14} /> PDF
          </button>
        </div>}>
        <div className="toolbar" style={{ marginTop: 0 }}>
          <div className="field-inline"><label>From</label><input type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} style={{ width: 150 }} /></div>
          <div className="field-inline"><label>To</label><input type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} style={{ width: 150 }} /></div>
          {canViewAll && <SearchableSelect
            value={filters.employee_id}
            onChange={(v) => setFilters({ ...filters, employee_id: v })}
            options={employees.map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.first_name} ${e.last_name}` }))}
            placeholder="All employees" style={{ width: 230 }}
          />}
          {tab === 'records' && <SearchableSelect
            value={filters.status}
            onChange={(v) => setFilters({ ...filters, status: v })}
            options={STATUS_OPTIONS} placeholder="All statuses" style={{ width: 160 }}
          />}
        </div>
        <DataTable columns={tab === 'records' ? recordColumns : logColumns} rows={rows} loading={loading} emptyText="No attendance data for this period" />
      </Card>

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
