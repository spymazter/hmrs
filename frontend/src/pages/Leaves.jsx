import { useEffect, useState } from 'react'
import { Check, Plus, X } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect, todayStr } from '../components/ui'

export default function Leaves() {
  const { user, has } = useAuth()
  const [rows, setRows] = useState([])
  const [types, setTypes] = useState([])
  const [employees, setEmployees] = useState([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [form, setForm] = useState({ employee_id: user?.employee_id || '', leave_type_id: '', from_date: todayStr(), to_date: todayStr(), reason: '' })

  const load = () => {
    api.get('/leaves/requests').then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)))
    api.get('/leave-types').then((r) => setTypes(r.data)).catch(() => {})
    if (has('employee.view')) api.get('/employees?limit=500').then((r) => setEmployees(r.data.items)).catch(() => {})
  }
  useEffect(() => { load() }, [])

  const act = async (id, status) => {
    try { await api.post(`/leaves/requests/${id}/action`, { status }); setNotice(`Leave ${status}`); load() }
    catch (err) { setError(errorMessage(err)) }
  }

  const apply = async () => {
    try {
      await api.post('/leaves/requests', { ...form, employee_id: Number(form.employee_id || user.employee_id), leave_type_id: Number(form.leave_type_id || types[0]?.id) })
      setModal(false); setNotice('Leave application submitted'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  return (
    <>
      <PageHead title="Leave management" subtitle="Leave applications, approvals and balances"
        actions={<button className="btn btn-primary" onClick={() => setModal(true)}><Plus size={15} /> Apply leave</button>} />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        {types.map((t) => <div className="card kpi" key={t.id}>
          <div className="kpi-icon" style={{ background: `${t.color || '#0ea5e9'}20`, color: t.color || '#0ea5e9' }}><Check size={19} /></div>
          <div><div className="kpi-value">{t.max_days_per_year}</div><div className="kpi-label">{t.name}</div><div className="kpi-foot">{t.is_paid ? 'Paid leave' : 'Unpaid leave'}</div></div>
        </div>)}
      </div>
      <Card title={`Leave requests (${rows.length})`}>
        <DataTable rows={rows} emptyText="No leave applications yet" columns={[
          { label: 'Employee', render: (r) => <span className="strong">{r.employee_name}</span> },
          { label: 'Leave type', render: (r) => r.leave_type_name || '—' },
          { label: 'From', render: (r) => r.from_date },
          { label: 'To', render: (r) => r.to_date },
          { label: 'Reason', render: (r) => r.reason || '—' },
          { label: 'Status', render: (r) => <Badge status={r.status} /> },
          ...(has('leave.approve') ? [{ label: 'Actions', className: 'text-right', render: (r) => r.status === 'pending' ? <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-success btn-sm btn-icon" title="Approve" onClick={() => act(r.id, 'approved')}><Check size={14} /></button>
            <button className="btn btn-danger btn-sm btn-icon" title="Reject" onClick={() => act(r.id, 'rejected')}><X size={14} /></button>
          </div> : '—' }] : []),
        ]} />
      </Card>

      <Modal open={modal} onClose={() => setModal(false)} title="Apply for leave"
        footer={<><button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button><button className="btn btn-primary" onClick={apply}>Submit application</button></>}>
        <div className="form-grid">
          {has('employee.view') && <Field label="Employee" full><SearchableSelect value={form.employee_id} onChange={(v) => setForm({ ...form, employee_id: v })} options={employees.map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`}` }))} placeholder="Select employee" /></Field>}
          <Field label="Leave type" full><SearchableSelect value={form.leave_type_id} onChange={(v) => setForm({ ...form, leave_type_id: v })} options={types.map((t) => ({ value: t.id, label: t.name }))} placeholder="Select leave type" clearable={false} /></Field>
          <Field label="From date"><input type="date" value={form.from_date} onChange={(e) => setForm({ ...form, from_date: e.target.value })} /></Field>
          <Field label="To date"><input type="date" value={form.to_date} onChange={(e) => setForm({ ...form, to_date: e.target.value })} /></Field>
          <Field label="Reason" full><textarea rows="3" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        </div>
      </Modal>
    </>
  )
}
