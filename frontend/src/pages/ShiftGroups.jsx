import { useEffect, useState } from 'react'
import { Pencil, Plus, Trash2, UserPlus, UsersRound, X } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect } from '../components/ui'

const ACTIVE_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
]
const EMPTY = { name: '', code: '', description: '', is_active: true, shift_ids: [], employee_ids: [], designation_ids: [] }
const SELECTED_DESIGNATIONS = '__selected__'

export default function ShiftGroups() {
  const { has } = useAuth()
  const canManage = has('shift.manage')
  const [groups, setGroups] = useState([])
  const [shifts, setShifts] = useState([])
  const [employees, setEmployees] = useState([])
  const [designations, setDesignations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [mapGroup, setMapGroup] = useState(null)
  const [formEmpFilter, setFormEmpFilter] = useState('')
  const [mapEmpFilter, setMapEmpFilter] = useState('')
  // Tracks which employee ids were added automatically by a designation, so
  // removing the designation only removes those employees, not manual picks.
  const [formAuto, setFormAuto] = useState({})
  const [mapAuto, setMapAuto] = useState({})

  const load = () => {
    setLoading(true)
    Promise.all([
      api.get('/shift-groups'), api.get('/shifts'), api.get('/employees?limit=500'), api.get('/designations'),
    ]).then(([g, s, e, d]) => {
      setGroups(g.data)
      setShifts(s.data)
      setEmployees(e.data.items)
      setDesignations(d.data)
    }).catch((err) => setError(errorMessage(err))).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const employeeLabel = (id) => {
    const e = employees.find((x) => x.id === id)
    return e ? `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`}` : `Employee #${id}`
  }
  const shiftLabel = (id) => shifts.find((s) => s.id === id)?.name || `Shift #${id}`
  const designationLabel = (id) => designations.find((d) => d.id === id)?.name || `Designation #${id}`
  const matchedEmployeeIds = (designationId) => employees
    .filter((e) => e.designation_id === Number(designationId))
    .map((e) => e.id)

  // Designation -> employees is expanded at selection time; the resulting
  // employees are stored as normal direct group members.
  const withDesignation = (target, value, auto) => {
    const id = Number(value)
    if (!id || (target.designation_ids || []).includes(id)) return { target, auto }
    const matched = matchedEmployeeIds(id)
    return {
      target: {
        ...target,
        designation_ids: [...(target.designation_ids || []), id],
        employee_ids: [...new Set([...(target.employee_ids || []), ...matched])],
      },
      auto: {
        ...auto,
        ...Object.fromEntries(matched.map((employeeId) => [employeeId, id])),
      },
    }
  }
  const withoutDesignation = (target, value, auto) => {
    const id = Number(value)
    if (!id) return { target, auto }
    return {
      target: {
        ...target,
        designation_ids: (target.designation_ids || []).filter((v) => v !== id),
        employee_ids: (target.employee_ids || []).filter(
          (employeeId) => !(auto[employeeId] === id && matchedEmployeeIds(id).includes(employeeId)),
        ),
      },
      auto: Object.fromEntries(Object.entries(auto).filter(([, designationId]) => designationId !== id)),
    }
  }

  const openNew = () => {
    setEditing(null)
    setForm(EMPTY)
    setFormAuto({})
    setFormEmpFilter('')
    setModal(true)
  }
  const openEdit = (row) => {
    const designationIds = row.designation_ids || []
    const employeeIds = [...(row.employee_ids || [])]
    const auto = {}
    designationIds.forEach((designationId) => matchedEmployeeIds(designationId).forEach((employeeId) => {
      if (!employeeIds.includes(employeeId)) employeeIds.push(employeeId)
      auto[employeeId] = designationId
    }))
    setEditing(row.id)
    setForm({ ...EMPTY, ...row, shift_ids: row.shift_ids || [], employee_ids: employeeIds, designation_ids: designationIds })
    setFormAuto(auto)
    setFormEmpFilter('')
    setModal(true)
  }
  const openMap = (row) => {
    const designationIds = row.designation_ids || []
    const employeeIds = [...(row.employee_ids || [])]
    const auto = {}
    designationIds.forEach((designationId) => matchedEmployeeIds(designationId).forEach((employeeId) => {
      if (!employeeIds.includes(employeeId)) employeeIds.push(employeeId)
      auto[employeeId] = designationId
    }))
    setMapGroup({ ...row, employee_ids: employeeIds, designation_ids: designationIds })
    setMapAuto(auto)
    setMapEmpFilter('')
    setError('')
  }

  const addDesignation = (isForm, value) => {
    const update = (current, auto) => withDesignation(current, value, auto)
    if (isForm) {
      const next = update(form, formAuto)
      setForm(next.target); setFormAuto(next.auto)
    } else if (mapGroup) {
      const next = update(mapGroup, mapAuto)
      setMapGroup(next.target); setMapAuto(next.auto)
    }
  }
  const dropDesignation = (isForm, value) => {
    const update = (current, auto) => withoutDesignation(current, value, auto)
    if (isForm) {
      const next = update(form, formAuto)
      setForm(next.target); setFormAuto(next.auto)
    } else if (mapGroup) {
      const next = update(mapGroup, mapAuto)
      setMapGroup(next.target); setMapAuto(next.auto)
    }
  }
  const toggleShift = (id) => setForm((f) => ({
    ...f,
    shift_ids: f.shift_ids.includes(id) ? f.shift_ids.filter((v) => v !== id) : [...f.shift_ids, id],
  }))
  const toggleEmployee = (isForm, id) => {
    const apply = (current, auto) => {
      const remove = current.employee_ids.includes(id)
      const nextAuto = { ...auto }
      if (remove) delete nextAuto[id]
      return {
        target: {
          ...current,
          employee_ids: remove ? current.employee_ids.filter((v) => v !== id) : [...current.employee_ids, id],
        },
        auto: nextAuto,
      }
    }
    if (isForm) {
      const next = apply(form, formAuto)
      setForm(next.target); setFormAuto(next.auto)
    } else if (mapGroup) {
      const next = apply(mapGroup, mapAuto)
      setMapGroup(next.target); setMapAuto(next.auto)
    }
  }
  const addEmployee = (isForm, value) => {
    const id = Number(value)
    if (!id) return
    const target = isForm ? form : mapGroup
    if (!target || target.employee_ids.includes(id)) return
    if (isForm) setForm((f) => ({ ...f, employee_ids: [...f.employee_ids, id] }))
    else setMapGroup((g) => ({ ...g, employee_ids: [...g.employee_ids, id] }))
  }

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

  const saveMapping = async () => {
    setError('')
    try {
      await api.put(`/shift-groups/${mapGroup.id}/employees`, {
        employee_ids: mapGroup.employee_ids,
        designation_ids: mapGroup.designation_ids,
      })
      setNotice(`Mapped ${mapGroup.employee_ids.length} employee(s) and ${mapGroup.designation_ids.length} designation(s) to ${mapGroup.name}`)
      setMapGroup(null); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const designationOptions = (ids = []) => [
    { value: '', label: 'All designations' },
    ...(ids.length ? [{ value: SELECTED_DESIGNATIONS, label: `Selected group designations (${ids.length})` }] : []),
    ...designations.map((d) => ({ value: d.id, label: d.name })),
  ]
  const employeeOptions = (selectedIds = [], filter) => {
    const source = filter === SELECTED_DESIGNATIONS
      ? employees.filter((e) => (selectedIds || []).includes(e.designation_id))
      : filter ? employees.filter((e) => e.designation_id === Number(filter)) : employees
    return source
      .filter((e) => !(selectedIds || []).includes(e.id))
      .map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`}` }))
  }
  const designationList = (ids, onRemove) => {
    if (!ids?.length) return <div className="muted" style={{ padding: '10px 0', fontSize: 12 }}>No designations assigned — use the selector above.</div>
    return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
      {ids.map((id) => <span className="chip" key={id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {designationLabel(id)}
        {onRemove && <button type="button" className="close-x" style={{ width: 16, height: 16 }} onClick={() => onRemove(id)} aria-label={`Remove ${designationLabel(id)}`}><X size={12} /></button>}
      </span>)}
    </div>
  }
  const mappedList = (ids, onRemove) => {
    if (!ids?.length) return <div className="muted" style={{ padding: '10px 0', fontSize: 12 }}>No employees mapped yet — select a designation above or add individuals.</div>
    return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
      {ids.map((id) => <span className="chip" key={id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {employeeLabel(id)}
        {onRemove && <button type="button" className="close-x" style={{ width: 16, height: 16 }} onClick={() => onRemove(id)} aria-label={`Remove ${employeeLabel(id)}`}><X size={12} /></button>}
      </span>)}
    </div>
  }
  const coveredList = (ids) => {
    const covered = employees.filter((e) => (ids || []).includes(e.designation_id))
    if (!covered.length) return <div className="muted" style={{ padding: '10px 0', fontSize: 12 }}>No employees hold the selected designations.</div>
    return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, maxHeight: 170, overflowY: 'auto', padding: '4px 0' }}>
      {covered.map((e) => <span className="chip" key={e.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        {e.employee_code} — {e.full_name || `${e.first_name} ${e.last_name}`}
        <span className="muted" style={{ fontSize: 11 }}>({e.designation_name})</span>
      </span>)}
    </div>
  }

  const designationFields = (isForm) => {
    const target = isForm ? form : mapGroup
    const filter = isForm ? formEmpFilter : mapEmpFilter
    const setFilter = isForm ? setFormEmpFilter : setMapEmpFilter
    if (!target) return null
    return <>
      <Field label="Assign by designation" full hint="Selecting a designation automatically adds every matching employee below. Removing it removes only those auto-added employees.">
        <SearchableSelect value="" onChange={(v) => addDesignation(isForm, v)}
          options={designations.filter((d) => !target.designation_ids.includes(d.id)).map((d) => ({ value: d.id, label: d.name }))}
          placeholder="Search and add designations…" searchPlaceholder="Search designations…" />
        {designationList(target.designation_ids, (id) => dropDesignation(isForm, id))}
      </Field>
      {target.designation_ids.length > 0 && (
        <Field label={`Auto-added employees (${employees.filter((e) => target.designation_ids.includes(e.designation_id)).length})`} full hint="Employees automatically populated from the selected designations.">
          {coveredList(target.designation_ids)}
        </Field>
      )}
      <Field label="Filter employee list by designation" full hint="Narrow the picker to one designation, or to the designations selected above.">
        <SearchableSelect value={filter} onChange={setFilter} clearable={false}
          options={designationOptions(target.designation_ids)} searchPlaceholder="Search designations…" />
      </Field>
      <Field label={`Map employees to this group (${target.employee_ids.length})`} full hint="Designation members are added automatically. Use this picker for individual overrides or employees without a designation.">
        <SearchableSelect value="" onChange={(v) => addEmployee(isForm, v)}
          options={employeeOptions(target.employee_ids, filter)}
          placeholder="Search and add employees…" searchPlaceholder="Search by name or code…" />
        {mappedList(target.employee_ids, (id) => toggleEmployee(isForm, id))}
      </Field>
    </>
  }

  return (
    <>
      <PageHead title="Shift groups" subtitle="Group shifts together and assign them by employee or designation"
        actions={canManage && <button className="btn btn-primary" onClick={openNew}><Plus size={16} /> Add shift group</button>} />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <Card title={`Configured shift groups (${groups.length})`}>
        <DataTable loading={loading} rows={groups} emptyText="No shift groups yet — add one to map employees and shifts"
          columns={[
            { label: 'Group', render: (r) => <><span className="strong">{r.name}</span><span className="sub">{r.code || r.description || '—'}</span></> },
            { label: 'Shifts', render: (r) => (r.shift_ids || []).length
              ? r.shift_ids.map((id) => <span className="chip" key={id}>{shiftLabel(id)}</span>) : '—' },
            { label: 'Rotation', render: (r) => (r.shift_ids || []).length > 1 ? 'Weekly rotation' : (r.shift_ids || []).length === 1 ? 'Single shift' : '—' },
            { label: 'Users', render: (r) => {
              const direct = r.employee_ids || []
              const byDesignation = employees.filter((e) => (r.designation_ids || []).includes(e.designation_id)).map((e) => e.id)
              const total = new Set([...direct, ...byDesignation]).size
              return <>{total}<span className="sub">{direct.length} direct · {byDesignation.length} by designation</span></>
            } },
            { label: 'Designations', render: (r) => (r.designation_ids || []).length
              ? r.designation_ids.map((id) => <span className="chip" key={id}>{designationLabel(id)}</span>) : '—' },
            { label: 'Status', render: (r) => <Badge status={r.is_active ? 'active' : 'inactive'} /> },
            ...(canManage ? [{ label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-outline btn-sm" onClick={() => openMap(r)}><UsersRound size={14} /> Map members</button>
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
          <Field label="Shifts in this group" full hint="Members rotate through these shifts weekly when no daily roster row exists.">
            {shifts.length ? <div className="check-grid">
              {shifts.map((s) => <label className="check-item" key={s.id}>
                <input type="checkbox" checked={form.shift_ids.includes(s.id)} onChange={() => toggleShift(s.id)} />
                <span>{s.name}</span>
              </label>)}
            </div> : <div className="muted" style={{ padding: 10, fontSize: 12 }}>No shifts configured yet — create them on the Shifts page first.</div>}
          </Field>
          {designationFields(true)}
          <Field label="Status"><SearchableSelect value={form.is_active ? 'active' : 'inactive'} onChange={(v) => setForm({ ...form, is_active: v === 'active' })} options={ACTIVE_OPTIONS} clearable={false} /></Field>
        </div>
      </Modal>

      <Modal open={!!mapGroup} onClose={() => setMapGroup(null)} title={`Map members — ${mapGroup?.name || ''}`} width={720}
        footer={<><button className="btn btn-outline" onClick={() => setMapGroup(null)}>Cancel</button><button className="btn btn-primary" onClick={saveMapping}><UserPlus size={15} /> Save mapping</button></>}>
        {mapGroup && <div className="form-grid">
          {designationFields(false)}
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
