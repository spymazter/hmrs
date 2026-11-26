import { useEffect, useState } from 'react'
import { Check, Download, Plus, ShieldCheck, Upload, X } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect, todayStr } from '../components/ui'

const currentYear = new Date().getFullYear()

export default function Leaves() {
  const { user, has } = useAuth()
  const isHR = has('leave.verify') || has('leave.quota.manage') || user?.is_admin
  const isManager = has('leave.manager_approve') || user?.is_admin
  const isFinal = has('leave.final_approve') || user?.is_admin

  const [rows, setRows] = useState([])
  const [types, setTypes] = useState([])
  const [employees, setEmployees] = useState([])
  const [balances, setBalances] = useState([])
  const [quotas, setQuotas] = useState([])
  const [holidays, setHolidays] = useState([])
  const [compOffs, setCompOffs] = useState([])
  const [year, setYear] = useState(currentYear)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [quotaFile, setQuotaFile] = useState(null)
  const [rhFile, setRhFile] = useState(null)
  const [form, setForm] = useState({ employee_id: user?.employee_id || '', leave_type_id: '', from_date: todayStr(), to_date: todayStr(), reason: '', is_full_day: true, restricted_holiday_id: '' })
  const [quotaForm, setQuotaForm] = useState({ employee_id: '', leave_type_id: '', days: '' })
  const [rhForm, setRhForm] = useState({ holiday_date: '', name: '', reason: '' })
  const [accrual, setAccrual] = useState({ from_date: `${currentYear}-01-01`, to_date: todayStr() })

  const load = () => {
    api.get('/leaves/requests').then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)))
    api.get('/leave-types').then((r) => {
      setTypes(r.data)
      setForm((f) => ({ ...f, leave_type_id: f.leave_type_id || r.data[0]?.id || '' }))
    }).catch(() => {})
    if (user?.employee_id) {
      api.get(`/leaves/balances?year=${year}`).then((r) => setBalances(r.data)).catch(() => {})
    }
    if (isHR) {
      api.get(`/leaves/quotas?year=${year}`).then((r) => setQuotas(r.data)).catch(() => {})
      api.get(`/leaves/restricted-holidays?year=${year}`).then((r) => setHolidays(r.data)).catch(() => {})
    } else {
      api.get(`/leaves/restricted-holidays?year=${year}`).then((r) => setHolidays(r.data)).catch(() => {})
    }
    api.get('/leaves/comp-offs').then((r) => setCompOffs(r.data)).catch(() => {})
    if (has('employee.view')) api.get('/employees?limit=500').then((r) => setEmployees(r.data.items)).catch(() => {})
  }

  useEffect(() => { load() }, [year, user?.id])

  const report = async (promise, success) => {
    setError(''); setNotice('')
    try { await promise; setNotice(success); load() }
    catch (err) { setError(errorMessage(err)) }
  }

  const act = (row, action) => {
    let body = {}
    if (action === 'reject') {
      const reason = window.prompt('Reason for rejection', '')
      if (!reason) return
      body = { reason }
    }
    report(api.post(`/leaves/requests/${row.id}/${action}`, body), `Leave ${action === 'reject' ? 'rejected' : action.replace('-', ' ')}d`)
  }

  const apply = () => {
    const selectedType = types.find((t) => t.id === Number(form.leave_type_id))
    const payload = {
      ...form,
      employee_id: Number(form.employee_id || user.employee_id),
      leave_type_id: Number(form.leave_type_id),
      restricted_holiday_id: selectedType?.code === 'RH' ? Number(form.restricted_holiday_id) || null : null,
    }
    report(api.post('/leaves/requests', payload).then(() => setModal(false)), 'Leave application submitted')
  }

  const saveQuota = () => report(
    api.post('/leaves/quotas', {
      employee_id: Number(quotaForm.employee_id) || null,
      leave_type_id: Number(quotaForm.leave_type_id),
      year: Number(year),
      days: Number(quotaForm.days),
    }),
    'Yearly quota saved',
  )

  const uploadQuota = () => {
    if (!quotaFile) { setError('Choose a quota file first'); return }
    const body = new FormData()
    body.append('file', quotaFile)
    report(api.post('/leaves/quotas/upload', body), 'Leave quotas uploaded')
  }

  const saveHoliday = () => report(
    api.post('/leaves/restricted-holidays', { ...rhForm, year: Number(year) }),
    'Restricted holiday added',
  )

  const uploadHoliday = () => {
    if (!rhFile) { setError('Choose an RH list file first'); return }
    const body = new FormData()
    body.append('file', rhFile)
    report(api.post('/leaves/restricted-holidays/upload', body), 'RH list uploaded')
  }

  const accrue = () => report(
    api.post('/attendance/advanced/comp-offs/accrue', accrual),
    'Comp off accrual completed',
  )

  const downloadTemplate = async (path, name) => {
    try {
      const response = await api.get(path, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url; link.download = name; link.click()
      URL.revokeObjectURL(url)
    } catch (err) { setError(errorMessage(err)) }
  }

  const compBalance = compOffs[0]?.balance
  const employeeOptions = employees.map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`}` }))
  const typeOptions = types.map((t) => ({ value: t.id, label: `${t.code ? `${t.code} — ` : ''}${t.name}` }))
  const holidayOptions = holidays.map((h) => ({ value: h.id, label: `${h.holiday_date} — ${h.name}` }))

  return (
    <>
      <PageHead title="Leave management" subtitle="Applications, manager approval, HR verification, admin final approval and yearly quotas"
        actions={<button className="btn btn-primary" onClick={() => setModal(true)}><Plus size={15} /> Apply leave</button>} />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>

      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <Card title="My leave balances" subtitle="Verified against HR yearly quotas" actions={
          <div className="field-inline"><label>Year</label><input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 100 }} /></div>
        }>
          <DataTable rows={balances} emptyText="No balance data available" columns={[
            { label: 'Leave', render: (r) => <span className="strong">{r.leave_type_code || r.leave_type_name}</span> },
            { label: 'Quota', render: (r) => r.quota },
            { label: 'Used', render: (r) => r.used },
            { label: 'Pending', render: (r) => r.pending },
            { label: 'Balance', render: (r) => <span className="strong">{r.remaining}</span> },
            { label: 'Source', render: (r) => <Badge status={r.source === 'employee' ? 'approved' : 'info'}>{r.source}</Badge> },
          ]} />
        </Card>
        <Card title="Compensatory off" subtitle="1 day for every 9 extra hours worked"
          actions={<Badge status="info">{compBalance ? `${compBalance.earned_days} days earned` : 'No auto accrual yet'}</Badge>}>
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <Field label="From"><input type="date" value={accrual.from_date} onChange={(e) => setAccrual({ ...accrual, from_date: e.target.value })} /></Field>
            <Field label="To"><input type="date" value={accrual.to_date} onChange={(e) => setAccrual({ ...accrual, to_date: e.target.value })} /></Field>
            <div style={{ gridColumn: '1 / -1' }}>
              <button className="btn btn-primary" disabled={!isHR} onClick={accrue}><ShieldCheck size={15} /> Accrue from attendance</button>
            </div>
          </div>
          <DataTable rows={compOffs.slice(0, 8)} emptyText="No auto-accrued comp off yet" columns={[
            { label: 'Employee', render: (r) => r.employee_id },
            { label: 'Work date', render: (r) => r.work_date },
            { label: 'Days', render: (r) => <span className="strong">{r.days}</span> },
            { label: 'Source', render: (r) => <Badge status="info">{r.source}</Badge> },
          ]} />
        </Card>
      </div>

      {isHR && (
        <>
          <Card title="HR yearly leave mapping" subtitle="CL 12 · EL 18 · RH 2. Apply to all employees or map one employee.">
            <div className="form-grid">
              <Field label="Employee (blank = global)"><SearchableSelect value={quotaForm.employee_id} onChange={(v) => setQuotaForm({ ...quotaForm, employee_id: v })} options={employeeOptions} placeholder="All employees" /></Field>
              <Field label="Leave type"><SearchableSelect value={quotaForm.leave_type_id} onChange={(v) => setQuotaForm({ ...quotaForm, leave_type_id: v })} options={typeOptions} placeholder="Select leave type" clearable={false} /></Field>
              <Field label="Days"><input type="number" min="0" value={quotaForm.days} onChange={(e) => setQuotaForm({ ...quotaForm, days: e.target.value })} /></Field>
              <div style={{ display: 'flex', alignItems: 'end' }}><button className="btn btn-primary" onClick={saveQuota}>Save quota</button></div>
              <Field label="Upload quotas (CSV/XLSX)" full>
                <div className="toolbar"><input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => setQuotaFile(e.target.files?.[0] || null)} />
                  <button className="btn btn-outline" onClick={uploadQuota}><Upload size={14} /> Upload</button>
                  <button className="btn btn-outline" onClick={() => downloadTemplate(`/leaves/quotas/template?file_format=csv`, 'leave_quotas_template.csv')}><Download size={14} /> Template</button>
                </div>
              </Field>
            </div>
            <DataTable rows={quotas.slice(0, 20)} emptyText="No yearly quota mappings yet" columns={[
              { label: 'Scope', render: (r) => <Badge status={r.scope === 'employee' ? 'approved' : 'info'}>{r.scope}</Badge> },
              { label: 'Employee', render: (r) => r.employee_code || 'All employees' },
              { label: 'Leave', render: (r) => r.leave_type_code || r.leave_type_name },
              { label: 'Year', render: (r) => r.year },
              { label: 'Days', render: (r) => <span className="strong">{r.days}</span> },
            ]} />
          </Card>

          <Card title="Restricted holiday list" subtitle={`HR updates the ${year} RH list once a year; employees choose 2 days.`} style={{ marginTop: 16 }}>
            <div className="form-grid">
              <Field label="Date"><input type="date" value={rhForm.holiday_date} onChange={(e) => setRhForm({ ...rhForm, holiday_date: e.target.value })} /></Field>
              <Field label="Name"><input value={rhForm.name} onChange={(e) => setRhForm({ ...rhForm, name: e.target.value })} /></Field>
              <Field label="Reason" full><input value={rhForm.reason} onChange={(e) => setRhForm({ ...rhForm, reason: e.target.value })} /></Field>
              <div style={{ display: 'flex', alignItems: 'end' }}><button className="btn btn-primary" onClick={saveHoliday}>Add holiday</button></div>
              <Field label="Upload yearly list (CSV/XLSX)" full>
                <div className="toolbar"><input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => setRhFile(e.target.files?.[0] || null)} />
                  <button className="btn btn-outline" onClick={uploadHoliday}><Upload size={14} /> Upload</button>
                  <button className="btn btn-outline" onClick={() => downloadTemplate('/leaves/restricted-holidays/template?file_format=csv', 'restricted_holidays_template.csv')}><Download size={14} /> Template</button>
                </div>
              </Field>
            </div>
            <DataTable rows={holidays} emptyText="No restricted holidays uploaded for this year" columns={[
              { label: 'Date', render: (r) => <span className="strong">{r.holiday_date}</span> },
              { label: 'Name', render: (r) => r.name },
              { label: 'Reason', render: (r) => r.reason || '—' },
            ]} />
          </Card>
        </>
      )}

      <Card title={`Leave requests (${rows.length})`} style={{ marginTop: 16 }}>
        <DataTable rows={rows} emptyText="No leave applications yet" columns={[
          { label: 'Employee', render: (r) => <span className="strong">{r.employee_name}</span> },
          { label: 'Leave', render: (r) => <Badge status="info">{r.leave_type_code || r.leave_type_name}</Badge> },
          { label: 'From', render: (r) => r.from_date },
          { label: 'To', render: (r) => r.to_date },
          { label: 'Reason', render: (r) => r.reason || '—' },
          { label: 'Status', render: (r) => <Badge status={r.status} /> },
          { label: 'Stages', render: (r) => <div className="muted" style={{ fontSize: 11 }}>
            {r.manager_approved_at ? 'Manager ✓ ' : 'Manager · '}
            {r.hr_verified_at ? 'HR ✓ ' : 'HR · '}
            {r.final_approved_at ? 'Admin ✓' : 'Admin ·'}
          </div> },
          { label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
            {r.status === 'pending' && isManager && <button className="btn btn-success btn-sm" onClick={() => act(r, 'manager-approve')}>Manager approve</button>}
            {(r.status === 'manager_approved' || r.status === 'pending') && isHR && !r.hr_verified_at && <button className="btn btn-outline btn-sm" onClick={() => act(r, 'verify')}><ShieldCheck size={13} /> Verify</button>}
            {r.status === 'verified' && isFinal && <button className="btn btn-success btn-sm" onClick={() => act(r, 'final-approve')}>Final approve</button>}
            {!['approved', 'rejected'].includes(r.status) && (isManager || isHR || isFinal) && <button className="btn btn-danger btn-sm btn-icon" title="Reject" onClick={() => act(r, 'reject')}><X size={14} /></button>}
            {['approved', 'rejected'].includes(r.status) ? '—' : null}
          </div> },
        ]} />
      </Card>

      <Modal open={modal} onClose={() => setModal(false)} title="Apply for leave"
        footer={<><button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button><button className="btn btn-primary" onClick={apply}>Submit application</button></>}>
        <div className="form-grid">
          {has('employee.view') && <Field label="Employee" full><SearchableSelect value={form.employee_id} onChange={(v) => setForm({ ...form, employee_id: v })} options={employeeOptions} placeholder="Select employee" /></Field>}
          <Field label="Leave type" full><SearchableSelect value={form.leave_type_id} onChange={(v) => setForm({ ...form, leave_type_id: v, restricted_holiday_id: '' })} options={typeOptions} placeholder="Select leave type" clearable={false} /></Field>
          {types.find((t) => t.id === Number(form.leave_type_id))?.code === 'RH' && <Field label="Restricted holiday" full><SearchableSelect value={form.restricted_holiday_id} onChange={(v) => setForm({ ...form, restricted_holiday_id: v })} options={holidayOptions} placeholder="Select from HR list" clearable={false} /></Field>}
          <Field label="From date"><input type="date" value={form.from_date} onChange={(e) => setForm({ ...form, from_date: e.target.value })} /></Field>
          <Field label="To date"><input type="date" value={form.to_date} onChange={(e) => setForm({ ...form, to_date: e.target.value })} /></Field>
          <Field label="Duration"><SearchableSelect value={form.is_full_day} onChange={(v) => setForm({ ...form, is_full_day: v })} options={[{ value: true, label: 'Full day' }, { value: false, label: 'Half day' }]} clearable={false} /></Field>
          <Field label="Reason" full><textarea rows="3" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        </div>
      </Modal>
    </>
  )
}
