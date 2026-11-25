import { useEffect, useState } from 'react'
import { Pencil, Plus, Trash2, UserPlus, UsersRound, X } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect } from '../components/ui'

const ACTIVE_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
]
const EMPTY = { name: '', code: '', description: '', is_active: true, shift_ids: [], employee_ids: [] }

export default function ShiftGroups() {
  const { has } = useAuth()
  const canManage = has('shift.manage')
  const [groups, setGroups] = useState([])
  const [shifts, setShifts] = useState([])
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [mapGroup, setMapGroup] = useState(null)

  const load = () => {
    setLoading(true)
    Promise.all([
      api.get('/shift-groups'), api.get('/shifts'), api.get('/employees?limit=500'),
    ]).then(([g, s, e]) => {
      setGroups(g.data)
      setShifts(s.data)
      setEmployees(e.data.items)
    }).catch((err) => setError(errorMessage(err))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const openNew = () => { setEditing(null); setForm(EMPTY); setModal(true) }
  const openEdit = (row) => {
    setEditing(row.id)
    setForm({ ...EMPTY, ...row, shift_ids: row.shift_ids || [], employee_ids: row.employee_ids || [] })
    setModal(true)
  }
  const toggle = (key, id) => setForm((f) => ({
    ...f,
    [key]: f[key].includes(id) ? f[key].filter((v) => v !== id) : [...f[key], id],
  }))

  const save = async () => {
    setError('')
    if (!form.name.trim()) { setError('Group name is required'); return }
    try {
      if (editing) { await api.put(`/shift-groups/${editing}`, form); setNotice('Shift group updated') }
      else { await api.post('/shift-groups', form); setNotice('Shift group created') }
      setModal(false); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const remove = async (row) => {
    if (!window.confirm(`Delete shift group "${row.name}"? Employees and shifts will be unmapped.`)) return
    try { await api.delete(`/shift-groups/${row.id}`); setNotice('Shift group deleted'); load() }
    catch (err) { setError(errorMessage(err)) }
  }

  const employeeLabel = (id) => {
    const e = employees.find((x) => x.id === id)
    return e ? `${e.employee_code} — ${e.first_name} ${e.last_name}` : `Employee #${id}`
  }
  const shiftLabel = (id) => shifts.find((s) => s.id === id)?.name || `Shift #${id}`

  const openMap = (row) => { setMapGroup({ ...row, employee_ids: row.employee_ids || [] }); setError('') }
  const addToForm = (value) => {
    const id = Number(value)
    if (!id || form.employee_ids.includes(id)) return
    setForm((f) => ({ ...f, employee_ids: [...f.employee_ids, id] }))
  }
  const addMapped = (value) => {
    const id = Number(value)
    if (!id || (mapGroup?.employee_ids || []).includes(id)) return
    setMapGroup((g) => ({ ...g, employee_ids: [...g.employee_ids, id] }))
  }
  const dropMapped = (id) => setMapGroup((g) => ({ ...g, employee_ids: g.employee_ids.filter((v) => v !== id) }))
  const saveMapping = async () => {
    setError('')
    try {
      await api.put(`/shift-groups/${mapGroup.id}/employees`, { employee_ids: mapGroup.employee_ids })
      setNotice(`Mapped ${mapGroup.employee_ids.length} employee(s) to ${mapGroup.name}`)
      setMapGroup(null); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const mappedList = (ids, onRemove) => {
    if (!ids?.length) return <div className="muted" style={{ padding: '10px 0', fontSize: 12 }}>No employees mapped yet — use the selector above.</div>
    return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
      {ids.map((id) => <span className="chip" key={id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {employeeLabel(id)}
        {onRemove && <button type="button" className="close-x" style={{ width: 16, height: 16 }} onClick={() => onRemove(id)} aria-label={`Remove ${employeeLabel(id)}`}><X size={12} /></button>}
      </span>)}
    </div>
  }

  return (
    <>
      <PageHead title="Shift groups" subtitle="Group shifts together and map employees to a shared rotation"
        actions={canManage && <button className="btn btn-primary" onClick={openNew}><Plus size={16} /> Add shift group</button>} />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <Card title={`Configured shift groups (${groups.length})`}>
        <DataTable loading={loading} rows={groups} emptyText="No shift groups yet — add one to map employees and shifts"
          columns={[
            { label: 'Group', render: (r) => <><span className="strong">{r.name}</span><span className="sub">{r.code || r.description || '—'}</span></> },
            { label: 'Shifts', render: (r) => (r.shift_ids || []).length
              ? r.shift_ids.map((id) => <span className="chip" key={id}>{shiftLabel(id)}</span>) : '—' },
            { label: 'Rotation', render: (r) => (r.shift_ids || []).length > 1 ? 'Weekly rotation' : (r.shift_ids || []).length === 1 ? 'Single shift' : '—' },
            { label: 'Employees', render: (r) => <>{r.employee_ids?.length || 0}<span className="sub">mapped</span></> },
            { label: 'Status', render: (r) => <Badge status={r.is_active ? 'active' : 'inactive'} /> },
            ...(canManage ? [{ label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-outline btn-sm" onClick={() => openMap(r)}><UsersRound size={14} /> Map employees</button>
              <button className="btn btn-outline btn-sm btn-icon" onClick={() => openEdit(r)} title="Edit"><Pencil size={14} /></button>
              <button className="btn btn-danger btn-sm btn-icon" onClick={() => remove(r)} title="Delete"><Trash2 size={14} /></button>
            </div> }] : []),
          ]} />
      </Card>

      <Modal open={modal} onClose={() => setModal(false)} title={editing ? `Edit group — ${form.name}` : 'Create shift group'} width={720}
        footer={<><button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button><button className="btn btn-primary" onClick={save}>Save group</button></>}>
        <div className="form-grid">
          <Field label="Group name"><input value={form.name} placeholder="e.g. Operations rotation" onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Code"><input value={form.code || ''} placeholder="e.g. OPS-ROT" onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
          <Field label="Description" full><input value={form.description || ''} placeholder="What is this group used for?" onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          <Field label="Shifts in this group" full hint="Mapped employees rotate through these shifts weekly when no daily roster row exists.">
            {shifts.length ? <div className="check-grid">
              {shifts.map((s) => <label className="check-item" key={s.id}>
                <input type="checkbox" checked={form.shift_ids.includes(s.id)} onChange={() => toggle('shift_ids', s.id)} />
                <span>{s.name}</span>
              </label>)}
            </div> : <div className="muted" style={{ padding: 10, fontSize: 12 }}>No shifts configured yet — create them on the Shifts page first.</div>}
          </Field>
          <Field label="Map employees to this group" full hint="Employees here use this group's rotation instead of the legacy rotation group on their shift.">
            <SearchableSelect value="" onChange={addToForm}
              options={employees.filter((e) => !form.employee_ids.includes(e.id)).map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.first_name} ${e.last_name}` }))}
              placeholder="Search and add employees…" searchPlaceholder="Search by name or code…" />
            {mappedList(form.employee_ids, (id) => toggle('employee_ids', id))}
          </Field>
          <Field label="Status"><SearchableSelect value={form.is_active ? 'active' : 'inactive'} onChange={(v) => setForm({ ...form, is_active: v === 'active' })} options={ACTIVE_OPTIONS} clearable={false} /></Field>
        </div>
      </Modal>

      <Modal open={!!mapGroup} onClose={() => setMapGroup(null)} title={`Map employees — ${mapGroup?.name || ''}`} width={640}
        footer={<><button className="btn btn-outline" onClick={() => setMapGroup(null)}>Cancel</button><button className="btn btn-primary" onClick={saveMapping}><UserPlus size={15} /> Save mapping</button></>}>
        {mapGroup && <div className="form-grid">
          <Field label="Add employees" full hint="Select employees to include in this group. An employee belongs to one group at a time.">
            <SearchableSelect value="" onChange={addMapped}
              options={employees.filter((e) => !mapGroup.employee_ids.includes(e.id)).map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.first_name} ${e.last_name}` }))}
              placeholder="Search and add employees…" searchPlaceholder="Search by name or code…" />
          </Field>
          <Field label={`Mapped employees (${mapGroup.employee_ids.length})`} full>
            {mappedList(mapGroup.employee_ids, dropMapped)}
          </Field>
          <Field label="Group shifts" full hint="Used for weekly rotation when there is no explicit roster row. Edit the group to change these.">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingTop: 4 }}>
              {mapGroup.shift_ids?.length ? mapGroup.shift_ids.map((id) => <span className="chip" key={id}>{shiftLabel(id)}</span>) : <span className="muted">No shifts in this group yet.</span>}
            </div>
          </Field>
        </div>}
      </Modal>
    </>
  )
}
