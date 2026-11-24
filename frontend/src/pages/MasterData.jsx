import { useEffect, useMemo, useState } from 'react'
import { BriefcaseBusiness, Building2, MapPin, Pencil, Plus, Trash2 } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect } from '../components/ui'

const EMPTY_DEPARTMENT = { name: '', code: '', head: '' }
const EMPTY_DESIGNATION = { name: '', department_id: '' }
const EMPTY_LOCATION = { name: '', code: '', city: '' }
const LABELS = {
  departments: { singular: 'department', title: 'Departments', subtitle: 'Organisation departments used across employees and reports' },
  designations: { singular: 'designation', title: 'Designations', subtitle: 'Job titles, grouped by department' },
  locations: { singular: 'location', title: 'Locations', subtitle: 'Workplaces and branches used by advanced attendance reports' },
}

export default function MasterData({ type = 'departments' }) {
  const { has } = useAuth()
  const canCreate = has('employee.create')
  const canEdit = has('employee.edit')
  const canDelete = has('employee.delete')
  const [tab, setTab] = useState(LABELS[type] ? type : 'departments')
  const [departments, setDepartments] = useState([])
  const [designations, setDesignations] = useState([])
  const [locations, setLocations] = useState([])
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_DEPARTMENT)

  useEffect(() => {
    setTab(LABELS[type] ? type : 'departments')
  }, [type])

  const load = () => {
    setLoading(true)
    Promise.all([
      api.get('/departments'), api.get('/designations'), api.get('/locations'), api.get('/employees?limit=500'),
    ]).then(([d, des, loc, emp]) => {
      setDepartments(d.data)
      setDesignations(des.data)
      setLocations(loc.data)
      setEmployees(emp.data.items || [])
    }).catch((e) => setError(errorMessage(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const counts = useMemo(() => {
    const result = { departments: {}, designations: {}, locations: {} }
    employees.forEach((employee) => {
      if (employee.department_id) result.departments[employee.department_id] = (result.departments[employee.department_id] || 0) + 1
      if (employee.designation_id) result.designations[employee.designation_id] = (result.designations[employee.designation_id] || 0) + 1
      if (employee.location_id) result.locations[employee.location_id] = (result.locations[employee.location_id] || 0) + 1
    })
    return result
  }, [employees])

  const label = LABELS[tab]
  const singular = label.singular
  const endpoint = `/${tab}`
  const rows = tab === 'departments' ? departments : tab === 'designations' ? designations : locations

  const emptyFor = (name) => (name === 'departments' ? EMPTY_DEPARTMENT : name === 'designations' ? EMPTY_DESIGNATION : EMPTY_LOCATION)

  const openNew = () => {
    setEditing(null)
    setForm(emptyFor(tab))
    setError(''); setNotice('')
    setModal(true)
  }

  const openEdit = (row) => {
    setEditing(row.id)
    setForm(tab === 'departments'
      ? { name: row.name || '', code: row.code || '', head: row.head || '' }
      : tab === 'designations'
        ? { name: row.name || '', department_id: row.department_id || '' }
        : { name: row.name || '', code: row.code || '', city: row.city || '' })
    setError(''); setNotice('')
    setModal(true)
  }

  const save = async () => {
    if (!form.name?.trim()) {
      setError('Name is required')
      return
    }
    setError('')
    try {
      const payload = tab === 'departments'
        ? { name: form.name.trim(), code: form.code?.trim() || null, head: form.head?.trim() || null }
        : tab === 'designations'
          ? { name: form.name.trim(), department_id: form.department_id || null }
          : { name: form.name.trim(), code: form.code?.trim() || null, city: form.city?.trim() || null }
      if (editing) {
        await api.put(`${endpoint}/${editing}`, payload)
        setNotice(`${label.title.slice(0, -1)} updated`)
      } else {
        await api.post(endpoint, payload)
        setNotice(`${label.title.slice(0, -1)} created`)
      }
      setModal(false)
      load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const remove = async (row) => {
    const count = counts[tab][row.id] || 0
    if (count) {
      setError(`Reassign ${count} employee(s) before deleting this ${singular}.`)
      return
    }
    if (!window.confirm(`Delete ${singular} "${row.name}"?`)) return
    setError('')
    try {
      await api.delete(`${endpoint}/${row.id}`)
      setNotice(`${label.title.slice(0, -1)} deleted`)
      load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const actionsColumn = (canEdit || canDelete) ? [{
    label: 'Actions', className: 'text-right', render: (r) => (
      <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
        {canEdit && <button className="btn btn-outline btn-sm btn-icon" onClick={() => openEdit(r)}><Pencil size={14} /></button>}
        {canDelete && <button className="btn btn-danger btn-sm btn-icon" onClick={() => remove(r)}><Trash2 size={14} /></button>}
      </div>
    ),
  }] : []

  const columns = tab === 'departments' ? [
    { label: 'Department', render: (r) => <span className="strong">{r.name}</span> },
    { label: 'Code', render: (r) => r.code || '—' },
    { label: 'Head', render: (r) => r.head || '—' },
    { label: 'Employees', render: (r) => counts.departments[r.id] || 0 },
    ...actionsColumn,
  ] : tab === 'designations' ? [
    { label: 'Designation', render: (r) => <span className="strong">{r.name}</span> },
    { label: 'Department', render: (r) => r.department_name || '—' },
    { label: 'Employees', render: (r) => counts.designations[r.id] || 0 },
    ...actionsColumn,
  ] : [
    { label: 'Location', render: (r) => <span className="strong">{r.name}</span> },
    { label: 'Code', render: (r) => r.code || '—' },
    { label: 'City', render: (r) => r.city || '—' },
    { label: 'Employees', render: (r) => counts.locations[r.id] || 0 },
    ...actionsColumn,
  ]

  return (
    <>
      <PageHead
        title={label.title}
        subtitle={label.subtitle}
        actions={canCreate && <button className="btn btn-primary" onClick={openNew}>
          <Plus size={16} /> Add {singular}
        </button>}
      />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <div className="tabs">
        <button className={`tab ${tab === 'departments' ? 'active' : ''}`} onClick={() => { setTab('departments'); setError(''); setNotice('') }}>Departments</button>
        <button className={`tab ${tab === 'designations' ? 'active' : ''}`} onClick={() => { setTab('designations'); setError(''); setNotice('') }}>Designations</button>
        <button className={`tab ${tab === 'locations' ? 'active' : ''}`} onClick={() => { setTab('locations'); setError(''); setNotice('') }}>Locations</button>
      </div>
      <Card title={`${label.title} (${rows.length})`}>
        <DataTable loading={loading} rows={rows} columns={columns} emptyText={`No ${tab} configured`} />
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Edit ${singular}` : `Add ${singular}`}
        footer={<>
          <button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button>
          <button className="btn btn-primary" onClick={save}>Save</button>
        </>}
      >
        <div className="form-grid">
          <Field label="Name" full><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          {tab === 'departments' && <>
            <Field label="Code"><input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
            <Field label="Head"><input value={form.head} onChange={(e) => setForm({ ...form, head: e.target.value })} /></Field>
          </>}
          {tab === 'designations' && <Field label="Department" full>
            <SearchableSelect
              value={form.department_id}
              onChange={(v) => setForm({ ...form, department_id: v })}
              options={departments.map((d) => ({ value: d.id, label: d.name }))}
              placeholder="No department"
            />
          </Field>}
          {tab === 'locations' && <>
            <Field label="Code"><input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
            <Field label="City"><input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} /></Field>
          </>}
        </div>
      </Modal>
    </>
  )
}
