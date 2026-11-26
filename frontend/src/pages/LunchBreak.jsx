import { useEffect, useState } from 'react'
import { Coffee, Pencil } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead } from '../components/ui'

export default function LunchBreak() {
  const { has } = useAuth()
  const canManage = has('shift.manage')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [minutes, setMinutes] = useState(0)

  const load = () => {
    setLoading(true)
    api.get('/shifts')
      .then((r) => setRows(r.data))
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const openEdit = (row) => {
    setEditing(row)
    setMinutes(Number(row.break_minutes) || 0)
    setError('')
    setModal(true)
  }

  const save = async () => {
    setError('')
    try {
      await api.put(`/shifts/${editing.id}`, { break_minutes: Math.max(0, Number(minutes) || 0) })
      setNotice(`Lunch break updated for ${editing.name}`)
      setModal(false)
      load()
    } catch (err) { setError(errorMessage(err)) }
  }

  return (
    <>
      <PageHead title="Lunch break" subtitle="Reference lunch break duration for each shift" />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{notice}</Notice>
      <Card title={`Lunch break by shift (${rows.length})`}
        subtitle="Used as shift metadata. Actual break time is measured from break-in / break-out punches.">
        <DataTable loading={loading} rows={rows} emptyText="No shifts configured yet" columns={[
          { label: 'Shift', render: (r) => <><span className="strong">{r.name}</span><span className="sub">{r.shift_type || 'fixed'}</span></> },
          { label: 'Timing', render: (r) => `${r.start_time?.slice(0, 5) || '—'} – ${r.end_time?.slice(0, 5) || '—'}` },
          { label: 'Lunch break', render: (r) => <><span className="mono">{r.break_minutes || 0}</span><span className="sub">minutes</span></> },
          { label: 'Status', render: (r) => <Badge status={r.is_active ? 'active' : 'inactive'} /> },
          ...(canManage ? [{ label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-outline btn-sm btn-icon" onClick={() => openEdit(r)} title="Edit lunch break"><Pencil size={14} /></button>
          </div> }] : []),
        ]} />
      </Card>

      <Modal open={modal} onClose={() => setModal(false)} title={`Lunch break — ${editing?.name || ''}`}
        footer={<><button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button><button className="btn btn-primary" onClick={save}><Coffee size={15} /> Save</button></>}>
        <div className="form-grid">
          <Field label="Break minutes" full hint="Reference duration for this shift. Set 0 if no fixed lunch break is configured.">
            <input type="number" min="0" step="5" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          </Field>
        </div>
      </Modal>
    </>
  )
}
