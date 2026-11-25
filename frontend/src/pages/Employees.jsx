import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Pencil, Plus, Search, Trash2 } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect, todayStr } from '../components/ui'

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
  { value: 'left', label: 'Left' },
]
const GENDER_OPTIONS = ['Male', 'Female', 'Other'].map((v) => ({ value: v, label: v }))

const EMPTY = {
  employee_code: '', first_name: '', last_name: '', email: '', phone: '',
  gender: '', date_of_joining: todayStr(), status: 'active', device_user_id: '',
  department_id: '', designation_id: '', shift_id: '', shift_group_id: '', location_id: '', manager_id: '',
  create_login: false, login_password: 'emp123',
}

export default function Employees() {
  const { has } = useAuth()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [dept, setDept] = useState('')
  const [searchParams] = useSearchParams()
  const [status, setStatus] = useState(searchParams.get('status') || '')
  const [sort, setSort] = useState(null)
  const [master, setMaster] = useState({ departments: [], designations: [], shifts: [], shiftGroups: [], locations: [], employees: [] })
  const [modal, setModal] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [editing, setEditing] = useState(null)

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (dept) params.set('department_id', dept)
    if (status) params.set('status', status)
    api.get(`/employees?${params}`).then((r) => setRows(r.data.items)).catch((e) => setError(errorMessage(e))).finally(() => setLoading(false))
  }

  useEffect(() => {
    Promise.all([
      api.get('/departments'), api.get('/designations'), api.get('/shifts'), api.get('/shift-groups'), api.get('/locations'), api.get('/employees?limit=500'),
    ]).then(([d, des, s, g, l, e]) => setMaster({ departments: d.data, designations: des.data, shifts: s.data, shiftGroups: g.data, locations: l.data, employees: e.data.items }))
      .catch(() => {})
  }, [])

  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [search, dept, status])

  const sortValue = (row, key) => {
    if (key === 'employee') return `${row.first_name || ''} ${row.last_name || ''}`.trim()
    if (key === 'device_user_id') return row.device_user_id || ''
    return row[key] || ''
  }
  const sortedRows = useMemo(() => {
    if (!sort) return rows
    return [...rows].sort((a, b) => {
      const av = sortValue(a, sort.key)
      const bv = sortValue(b, sort.key)
      if (!av && bv) return 1
      if (av && !bv) return -1
      const result = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' })
      return sort.direction === 'desc' ? -result : result
    })
  }, [rows, sort])
  const toggleSort = (key) => setSort((current) => (
    !current || current.key !== key ? { key, direction: 'asc' } : { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
  ))

  const openNew = () => { setEditing(null); setForm(EMPTY); setModal(true) }
  const openEdit = (row) => {
    setEditing(row.id)
    setForm({ ...EMPTY, ...row, department_id: row.department_id || '', designation_id: row.designation_id || '', shift_id: row.shift_id || '', shift_group_id: row.shift_group_id || '', location_id: row.location_id || '', manager_id: row.manager_id || '', date_of_joining: row.date_of_joining || '' })
    setModal(true)
  }

  const save = async () => {
    setError('')
    try {
      const payload = { ...form }
      ;['department_id', 'designation_id', 'shift_id', 'shift_group_id', 'location_id', 'manager_id'].forEach((k) => { if (payload[k] === '') payload[k] = null })
      if (!payload.date_of_joining) payload.date_of_joining = null
      if (editing) {
        delete payload.create_login
        delete payload.login_password
        await api.put(`/employees/${editing}`, payload)
        setNotice('Employee updated')
      } else {
        await api.post('/employees', payload)
        setNotice('Employee created')
      }
      setModal(false)
      load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const remove = async (row) => {
    if (!window.confirm(`Delete ${row.first_name} ${row.last_name}?`)) return
    try { await api.delete(`/employees/${row.id}`); setNotice('Employee deleted'); load() }
    catch (err) { setError(errorMessage(err)) }
  }

  const columns = [
    { label: 'Employee', sortKey: 'employee', render: (r) => <><span className="strong">{r.first_name} {r.last_name}</span><span className="sub">{r.employee_code} · {r.email || '—'}</span></> },
    { label: 'Department', sortKey: 'department_name', render: (r) => r.department_name || '—' },
    { label: 'Designation', sortKey: 'designation_name', render: (r) => r.designation_name || '—' },
    { label: 'Shift', render: (r) => <><span>{r.shift_name || '—'}</span><span className="sub">{r.shift_group_name || 'No group'}</span></> },
    { label: 'Device UID', sortKey: 'device_user_id', render: (r) => <span className="mono">{r.device_user_id || '—'}</span> },
    { label: 'Status', render: (r) => <Badge status={r.status} /> },
    ...(has('employee.edit', 'employee.delete') ? [{ label: 'Actions', className: 'text-right', render: (r) => (
      <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
        {has('employee.edit') && <button className="btn btn-outline btn-sm btn-icon" onClick={() => openEdit(r)} title="Edit"><Pencil size={14} /></button>}
        {has('employee.delete') && <button className="btn btn-danger btn-sm btn-icon" onClick={() => remove(r)} title="Delete"><Trash2 size={14} /></button>}
      </div>
    ) }] : []),
  ]

  return (
    <>
      <PageHead title="Employees" subtitle="Employee master, enrollment IDs and reporting lines" actions={has('employee.create') && <button className="btn btn-primary" onClick={openNew}><Plus size={16} /> Add employee</button>} />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{notice}</Notice>
      <Card title={`All employees (${rows.length})`}>
        <div className="toolbar">
          <div style={{ flex: 1, minWidth: 200, position: 'relative' }}>
            <Search size={15} style={{ position: 'absolute', left: 10, top: 10, color: '#94a3b8' }} />
            <input type="text" placeholder="Search name, code or email…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ paddingLeft: 32 }} />
          </div>
          <SearchableSelect
            value={dept} onChange={setDept}
            options={master.departments.map((d) => ({ value: d.id, label: d.name }))}
            placeholder="All departments" style={{ width: 190 }}
          />
          <SearchableSelect
            value={status} onChange={setStatus}
            options={STATUS_OPTIONS} placeholder="All statuses" style={{ width: 150 }}
          />
        </div>
        <DataTable columns={columns} rows={sortedRows} loading={loading} emptyText="No employees found" sort={sort} onSort={toggleSort} />
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? 'Edit employee' : 'Add employee'}
        width={720}
        footer={<><button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button><button className="btn btn-primary" onClick={save}>{editing ? 'Save changes' : 'Create employee'}</button></>}
      >
        <div className="form-grid">
          <Field label="Employee code"><input value={form.employee_code} onChange={(e) => setForm({ ...form, employee_code: e.target.value })} disabled={!!editing} /></Field>
          <Field label="Device user ID (UID)" hint="Must match the enrolment ID on the biometric device"><input value={form.device_user_id} onChange={(e) => setForm({ ...form, device_user_id: e.target.value })} placeholder="e.g. 13" /></Field>
          <Field label="First name"><input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></Field>
          <Field label="Last name"><input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></Field>
          <Field label="Email"><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Phone"><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
          <Field label="Department"><SearchableSelect value={form.department_id} onChange={(v) => setForm({ ...form, department_id: v, designation_id: '' })} options={master.departments.map((d) => ({ value: d.id, label: d.name }))} placeholder="—" /></Field>
          <Field label="Designation"><SearchableSelect value={form.designation_id} onChange={(v) => setForm({ ...form, designation_id: v })} options={master.designations.filter((d) => !form.department_id || d.department_id === Number(form.department_id)).map((d) => ({ value: d.id, label: d.name }))} placeholder="—" /></Field>
          <Field label="Shift"><SearchableSelect value={form.shift_id} onChange={(v) => setForm({ ...form, shift_id: v })} options={master.shifts.map((s) => ({ value: s.id, label: s.name }))} placeholder="—" /></Field>
          <Field label="Shift group" hint="Shared rotation group; mapped on Shift groups page too"><SearchableSelect value={form.shift_group_id} onChange={(v) => setForm({ ...form, shift_group_id: v })} options={master.shiftGroups.map((g) => ({ value: g.id, label: g.name }))} placeholder="— No group" /></Field>
          <Field label="Location"><SearchableSelect value={form.location_id} onChange={(v) => setForm({ ...form, location_id: v })} options={master.locations.map((l) => ({ value: l.id, label: l.label || l.name }))} placeholder="—" /></Field>
          <Field label="Reporting manager"><SearchableSelect value={form.manager_id} onChange={(v) => setForm({ ...form, manager_id: v })} options={master.employees.filter((e) => e.id !== editing).map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.first_name} ${e.last_name}` }))} placeholder="—" /></Field>
          <Field label="Date of joining"><input type="date" value={form.date_of_joining} onChange={(e) => setForm({ ...form, date_of_joining: e.target.value })} /></Field>
          <Field label="Status"><SearchableSelect value={form.status} onChange={(v) => setForm({ ...form, status: v })} options={STATUS_OPTIONS} clearable={false} /></Field>
          {!editing && (
            <>
              <Field label="Gender"><SearchableSelect value={form.gender} onChange={(v) => setForm({ ...form, gender: v })} options={GENDER_OPTIONS} placeholder="—" /></Field>
              <Field label="Create employee login">
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, paddingTop: 8 }}><input type="checkbox" checked={form.create_login} onChange={(e) => setForm({ ...form, create_login: e.target.checked })} /> Enable self-service login</label>
              </Field>
              {form.create_login && <Field label="Initial password" full><input value={form.login_password} onChange={(e) => setForm({ ...form, login_password: e.target.value })} hint="Username will be the employee code" /></Field>}
            </>
          )}
        </div>
      </Modal>
    </>
  )
}
