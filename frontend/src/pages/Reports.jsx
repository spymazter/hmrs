import { useEffect, useMemo, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { Download, FileBarChart, FileText, RefreshCw } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Notice, PageHead, SearchableSelect, Stat, todayStr } from '../components/ui'

const MONTH_OPTIONS = Array.from({ length: 12 }, (_, i) => ({
  value: i + 1, label: new Date(2020, i, 1).toLocaleString('en', { month: 'long' }),
}))
const STATUS_LABELS = {
  present: 'Present', half_day: 'Half day', absent: 'Absent', leave: 'Leave',
  week_off: 'Week off', holiday: 'Holiday', no_data: 'No data',
}
const STATUS_COLORS = {
  present: '#16a34a', half_day: '#f59e0b', absent: '#dc2626', leave: '#0ea5e9',
  week_off: '#94a3b8', holiday: '#8b5cf6', no_data: '#cbd5e1',
}
const now = new Date()
const isoWeek = (() => {
  const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()))
  const day = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - day)
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  return { year: d.getUTCFullYear(), week: Math.ceil((((d - yearStart) / 86400000) + 1) / 7) }
})()

export default function Reports() {
  const { has } = useAuth()
  const canManage = has('attendance.manage')
  const [tab, setTab] = useState('daily')
  const [data, setData] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [departments, setDepartments] = useState([])
  const [designations, setDesignations] = useState([])
  const [busy, setBusy] = useState(false)
  const [filters, setFilters] = useState({
    date_str: todayStr(), year: now.getFullYear(), month: now.getMonth() + 1,
    week: isoWeek.week, department_id: '', designation_id: '',
  })
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    api.get('/departments').then((r) => setDepartments(r.data)).catch(() => {})
    api.get('/designations').then((r) => setDesignations(r.data)).catch(() => {})
    api.get('/system/log-coverage').then((r) => setCoverage(r.data)).catch(() => {})
  }, [])

  const reportParams = () => {
    const params = new URLSearchParams()
    if (filters.department_id) params.set('department_id', filters.department_id)
    if (filters.designation_id) params.set('designation_id', filters.designation_id)
    if (tab === 'daily') params.set('date_str', filters.date_str)
    else {
      params.set('year', filters.year)
      params.set(tab === 'weekly' ? 'week' : 'month', tab === 'weekly' ? filters.week : filters.month)
    }
    return params
  }

  const recomputeParams = () => {
    const params = reportParams()
    params.set('report_type', tab)
    return params
  }

  useEffect(() => {
    setNotice('')
  }, [tab, filters])

  useEffect(() => {
    setData(null)
    const params = reportParams()
    api.get(`/reports/${tab}?${params}`)
      .then((r) => { setData(r.data); setError('') })
      .catch((e) => setError(errorMessage(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, filters, reloadKey])

  const recalculate = async () => {
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await api.post(`/reports/recompute?${recomputeParams()}`)
      setNotice(response.data.message)
      setReloadKey((key) => key + 1)
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const exportFile = async (format) => {
    setBusy(true); setError('')
    try {
      const params = reportParams()
      const res = await api.get(`/reports/${format}?${params}`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], {
        type: format === 'pdf' ? 'application/pdf' : 'text/csv',
      }))
      const link = document.createElement('a')
      link.href = url
      link.download = `attendance_${tab}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const rows = data?.rows || []
  const summary = data?.summary || {}
  const daily = tab === 'daily'
  const scopeLabel = data?.designation_label && data.designation_label !== 'All designations'
    ? `${data.department_label} · ${data.designation_label}`
    : data?.department_label || 'All departments'

  const statusChart = useMemo(() => Object.entries(data?.status_counts || {})
    .filter(([, value]) => value > 0)
    .map(([key, value]) => ({ name: STATUS_LABELS[key] || key, value, color: STATUS_COLORS[key] || '#94a3b8' })),
  [data])

  const hoursChart = useMemo(() => [...rows]
    .filter((r) => Number(r.total_hours) > 0)
    .sort((a, b) => Number(b.total_hours) - Number(a.total_hours))
    .slice(0, 8)
    .map((r) => ({ name: r.employee_name || r.employee_code, hours: Number(r.total_hours) })),
  [rows])

  const departmentChart = useMemo(() => {
    if (filters.department_id) return []
    const grouped = rows.reduce((acc, r) => {
      const name = r.department || 'Unassigned'
      acc[name] = acc[name] || { name, present: 0, absent: 0 }
      if (daily) {
        if (r.status === 'present' || r.status === 'half_day') acc[name].present += 1
        if (r.status === 'absent') acc[name].absent += 1
      } else {
        acc[name].present += Number(r.days_present || 0)
        acc[name].absent += Number(r.days_absent || 0)
      }
      return acc
    }, {})
    return Object.values(grouped).filter((d) => d.present || d.absent).sort((a, b) => b.present - a.present)
  }, [rows, daily, filters.department_id])

  const columns = daily ? [
    { label: 'Code', render: (r) => <span className="mono">{r.employee_code}</span> },
    { label: 'Employee', render: (r) => <><span className="strong">{r.employee_name}</span>{!r.has_data && <span className="sub">No data</span>}</> },
    { label: 'Department', render: (r) => r.department || '—' },
    { label: 'Shift', render: (r) => r.shift || '—' },
    { label: 'In', render: (r) => <span className="mono">{r.check_in || '—'}</span> },
    { label: 'Out', render: (r) => <span className="mono">{r.check_out || '—'}</span> },
    { label: 'Hours', render: (r) => <span className="mono">{r.total_hours}</span> },
    { label: 'OT', render: (r) => <span className="mono">{r.overtime_hours}</span> },
    { label: 'Late', render: (r) => `${r.late_minutes}m` },
    { label: 'Status', render: (r) => r.has_data ? <Badge status={r.status} /> : <span className="chip">No data</span> },
  ] : [
    { label: 'Code', render: (r) => <span className="mono">{r.employee_code}</span> },
    { label: 'Employee', render: (r) => <><span className="strong">{r.employee_name}</span>{!r.has_data && <span className="sub">No data</span>}</> },
    { label: 'Department', render: (r) => r.department || '—' },
    { label: 'Days present', render: (r) => <span className="mono">{r.days_present}</span> },
    { label: 'Absent', render: (r) => <span className="mono">{r.days_absent}</span> },
    { label: 'Half days', render: (r) => <span className="mono">{r.half_days}</span> },
    { label: 'Leave', render: (r) => <span className="mono">{r.leave_days}</span> },
    { label: 'Week offs', render: (r) => <span className="mono">{r.week_offs}</span> },
    { label: 'Total hours', render: (r) => <span className="mono">{r.total_hours}</span> },
    { label: 'OT hours', render: (r) => <span className="mono">{r.overtime_hours}</span> },
    { label: 'Late (min)', render: (r) => <span className="mono">{r.late_minutes}</span> },
  ]

  return (
    <>
      <PageHead title="Reports" subtitle="Daily, weekly and monthly attendance analytics with charts and PDF export"
        actions={<>
          {canManage && <button className="btn btn-outline" disabled={busy} title="Uses the current report date range and department filter"
            onClick={recalculate}><RefreshCw size={15} /> {busy ? 'Recalculating…' : 'Recalculate attendance'}</button>}
          <button className="btn btn-outline" disabled={busy} onClick={() => exportFile('csv')}><Download size={15} /> Export CSV</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => exportFile('pdf')}><FileText size={15} /> {busy ? 'Preparing…' : 'Export PDF'}</button>
        </>} />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{notice}</Notice>
      {coverage && (
        <Notice type="info">
          Log retention: <strong>minimum {coverage.retention_days} days</strong> ·
          {' '}Punch history: <strong>{coverage.punch_from || '—'} to {coverage.punch_to || '—'}</strong>
          {' '}({coverage.punch_count?.toLocaleString()} punches) ·
          {' '}Attendance records: {coverage.record_count?.toLocaleString()}
        </Notice>
      )}
      <div className="tabs">
        {['daily', 'weekly', 'monthly'].map((t) => (
          <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>

      <div className="toolbar">
        {tab === 'daily' ? (
          <div className="field-inline"><label>Date</label><input type="date" value={filters.date_str} onChange={(e) => setFilters({ ...filters, date_str: e.target.value })} style={{ width: 170 }} /></div>
        ) : (
          <>
            <div className="field-inline"><label>Year</label><input type="number" value={filters.year} onChange={(e) => setFilters({ ...filters, year: +e.target.value })} style={{ width: 100 }} /></div>
            {tab === 'weekly'
              ? <div className="field-inline"><label>ISO week</label><input type="number" min="1" max="53" value={filters.week} onChange={(e) => setFilters({ ...filters, week: +e.target.value })} style={{ width: 100 }} /></div>
              : <div className="field-inline"><label>Month</label><SearchableSelect value={filters.month} onChange={(v) => setFilters({ ...filters, month: v })} options={MONTH_OPTIONS} style={{ width: 150 }} clearable={false} /></div>}
          </>
        )}
        <SearchableSelect value={filters.department_id} onChange={(v) => setFilters({ ...filters, department_id: v })} options={departments.map((d) => ({ value: d.id, label: d.name }))} placeholder="All departments" style={{ width: 190 }} />
        <SearchableSelect value={filters.designation_id} onChange={(v) => setFilters({ ...filters, designation_id: v })} options={designations.map((d) => ({ value: d.id, label: d.name }))} placeholder="All designations" style={{ width: 190 }} />
      </div>

      {!data ? <div className="loader">Loading report…</div> : (
        <>
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <Stat icon={<FileBarChart size={19} />} label="Employees in report" value={summary.total} />
            <Stat icon={<FileBarChart size={19} />} label={daily ? 'Present' : 'Present days'} value={summary.present} color="#16a34a" />
            <Stat icon={<FileBarChart size={19} />} label={daily ? 'Absent' : 'Absent days'} value={summary.absent} color="#dc2626" />
            <Stat icon={<FileBarChart size={19} />} label="Total hours" value={summary.total_hours} color="#d97706" />
          </div>

          <div className="grid grid-2" style={{ marginBottom: 16 }}>
            <Card title="Status breakdown" subtitle={`${summary.with_data || 0} of ${summary.total || 0} employees with data`}>
              <div style={{ height: 250 }}>
                {statusChart.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={statusChart} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={82} label>
                        {statusChart.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
                      </Pie>
                      <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : <div className="loader">No status data</div>}
              </div>
            </Card>
            <Card title="Top employees by total hours" subtitle="Highest contributors in this period">
              <div style={{ height: 250 }}>
                {hoursChart.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={hoursChart} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                      <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} />
                      <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10, fill: '#475569' }} />
                      <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                      <Bar dataKey="hours" name="Total hours" fill="#4f46e5" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <div className="loader">No hours recorded</div>}
              </div>
            </Card>
          </div>

          {departmentChart.length > 0 && (
            <Card title="Department comparison" subtitle="Present versus absent" style={{ marginBottom: 16 }}>
              <div style={{ height: 250 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={departmentChart.slice(0, 12)} margin={{ top: 8, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#475569' }} interval={0} angle={-20} textAnchor="end" height={60} />
                    <YAxis tick={{ fontSize: 11, fill: '#64748b' }} />
                    <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="present" name={daily ? 'Present' : 'Present days'} fill="#16a34a" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="absent" name={daily ? 'Absent' : 'Absent days'} fill="#dc2626" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}

          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', margin: '2px 0 12px', fontSize: 12, color: '#475569' }}>
            <span>Half days: <strong>{summary.half_days || 0}</strong></span>
            <span>Leave days: <strong>{summary.leave || 0}</strong></span>
            <span>Week offs: <strong>{summary.week_offs || 0}</strong></span>
            <span>Overtime: <strong>{summary.overtime_hours || 0} hrs</strong></span>
            <span>Late: <strong>{summary.late || 0} days / {summary.late_minutes || 0} min</strong></span>
            <span>Avg hours/employee: <strong>{summary.avg_hours || 0}</strong></span>
          </div>

          <Card title={`${daily ? `Daily attendance — ${data.date}` : `${data.period} attendance summary`} · ${scopeLabel}`}
            subtitle={`${rows.length} employee rows (including employees with no punches)${daily ? ' · sorted by employee A–Z' : ''}`}>
            <DataTable rows={rows} emptyText="No employees match this filter" columns={columns} />
          </Card>
        </>
      )}
    </>
  )
}
