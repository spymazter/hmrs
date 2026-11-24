import { useEffect, useState } from 'react'
import { Clock3, Pencil, Plus, Trash2 } from 'lucide-react'
import api, { errorMessage } from '../api'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect } from '../components/ui'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const ACTIVE_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
]
const SHIFT_TYPES = [
  { value: 'fixed', label: 'Fixed hours' },
  { value: 'rotational', label: 'Rotational / roster' },
  { value: 'flexi', label: 'Flexible hours' },
  { value: 'night', label: 'Night shift' },
]
const EMPTY = {
  name: '', start_time: '09:00', end_time: '18:00', grace_minutes: 15,
  early_out_grace_minutes: 0, min_hours_for_full_day: 8, half_day_hours: 4,
  week_off_days: [6], is_active: true, color: '#4f46e5',
  shift_type: 'fixed', target_hours: null, break_minutes: 0, rotation_group: '',
}

export default function Shifts() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)

  const load = () => { api.get('/shifts').then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e))).finally(() => setLoading(false)) }
  useEffect(() => { load() }, [])

  const openNew = () => { setEditing(null); setForm(EMPTY); setModal(true) }
  const openEdit = (row) => {
    setEditing(row.id)
    setForm({ ...EMPTY, ...row, week_off_days: row.week_off_days || [], rotation_group: row.rotation_group || '' })
    setModal(true)
  }

  const save = async () => {
    setError('')
    try {
      if (editing) { await api.put(`/shifts/${editing}`, form); setNotice('Shift updated') }
      else { await api.post('/shifts', form); setNotice('Shift created') }
      setModal(false); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const remove = async (row) => {
    if (!window.confirm(`Delete shift "${row.name}"?`)) return
    try { await api.delete(`/shifts/${row.id}`); setNotice('Shift deleted'); load() } catch (err) { setError(errorMessage(err)) }
  }

  const toggleDay = (index) => setForm({
    ...form,
    week_off_days: form.week_off_days.includes(index) ? form.week_off_days.filter((d) => d !== index) : [...form.week_off_days, index],
  })

  return (
    <>
      <PageHead title="Shifts" subtitle="Define working hours, late grace and weekly off days" actions={<button className="btn btn-primary" onClick={openNew}><Plus size={16} /> Add shift</button>} />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <Card title={`Configured shifts (${rows.length})`}>
        <DataTable loading={loading} rows={rows} columns={[
          { label: 'Shift', render: (r) => <><span className="strong">{r.name}</span><span className="sub">{r.start_time?.slice(0, 5)} – {r.end_time?.slice(0, 5)}</span></> },
          { label: 'Type', render: (r) => <span className="chip">{SHIFT_TYPES.find((t) => t.value === r.shift_type)?.label || 'Fixed hours'}</span> },
          { label: 'Full day', render: (r) => `${r.min_hours_for_full_day} hrs` },
          { label: 'Late grace', render: (r) => `${r.grace_minutes} min` },
          { label: 'Weekly off', render: (r) => (r.week_off_days || []).length ? r.week_off_days.map((d) => <span className="chip" key={d}>{DAYS[d]}</span>) : '—' },
          { label: 'Status', render: (r) => <Badge status={r.is_active ? 'active' : 'inactive'} /> },
          { label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-outline btn-sm btn-icon" onClick={() => openEdit(r)}><Pencil size={14} /></button>
            <button className="btn btn-danger btn-sm btn-icon" onClick={() => remove(r)}><Trash2 size={14} /></button>
          </div> },
        ]} />
      </Card>

      <Modal open={modal} onClose={() => setModal(false)} title={editing ? 'Edit shift' : 'Add shift'}
        footer={<><button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button><button className="btn btn-primary" onClick={save}>Save shift</button></>}>
        <div className="form-grid">
          <Field label="Shift name" full><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Shift type" hint="Night shifts crossing midnight and flexi shifts are calculated automatically by the engine.">
            <SearchableSelect value={form.shift_type || 'fixed'} clearable={false}
              onChange={(v) => setForm({ ...form, shift_type: v })} options={SHIFT_TYPES} />
          </Field>
          <Field label="Rotation group" hint="Shifts in the same group rotate weekly when no roster row exists.">
            <input value={form.rotation_group || ''} placeholder="e.g. OpsRotation" onChange={(e) => setForm({ ...form, rotation_group: e.target.value })} />
          </Field>
          <Field label="Start time"><input type="time" value={form.start_time?.slice(0, 5)} onChange={(e) => setForm({ ...form, start_time: e.target.value })} /></Field>
          <Field label="End time"><input type="time" value={form.end_time?.slice(0, 5)} onChange={(e) => setForm({ ...form, end_time: e.target.value })} /></Field>
          <Field label="Late grace (minutes)"><input type="number" min="0" value={form.grace_minutes} onChange={(e) => setForm({ ...form, grace_minutes: +e.target.value })} /></Field>
          <Field label="Early-out grace (minutes)"><input type="number" min="0" value={form.early_out_grace_minutes} onChange={(e) => setForm({ ...form, early_out_grace_minutes: +e.target.value })} /></Field>
          <Field label="Full day hours"><input type="number" step="0.5" value={form.min_hours_for_full_day} onChange={(e) => setForm({ ...form, min_hours_for_full_day: +e.target.value })} /></Field>
          <Field label="Half day hours"><input type="number" step="0.5" value={form.half_day_hours} onChange={(e) => setForm({ ...form, half_day_hours: +e.target.value })} /></Field>
          <Field label="Flexi target hours"><input type="number" step="0.25" value={form.target_hours ?? ''} placeholder="Defaults to shift span" onChange={(e) => setForm({ ...form, target_hours: e.target.value === '' ? null : +e.target.value })} /></Field>
          <Field label="Break minutes (reference)"><input type="number" min="0" value={form.break_minutes ?? 0} onChange={(e) => setForm({ ...form, break_minutes: +e.target.value })} /></Field>
          <Field label="Weekly off days" full>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', paddingTop: 4 }}>
              {DAYS.map((day, index) => (
                <label key={day} className={`chip ${form.week_off_days.includes(index) ? 'badge badge-blue' : ''}`} style={{ cursor: 'pointer', padding: '7px 10px' }}>
                  <input type="checkbox" checked={form.week_off_days.includes(index)} onChange={() => toggleDay(index)} style={{ marginRight: 5, width: 13, height: 13 }} />{day}
                </label>
              ))}
            </div>
          </Field>
          <Field label="Status"><SearchableSelect value={form.is_active ? 'active' : 'inactive'} onChange={(v) => setForm({ ...form, is_active: v === 'active' })} options={ACTIVE_OPTIONS} clearable={false} /></Field>
          <Field label="Color"><input type="color" value={form.color || '#4f46e5'} onChange={(e) => setForm({ ...form, color: e.target.value })} style={{ padding: 3, height: 38 }} /></Field>
        </div>
      </Modal>
    </>
  )
}
