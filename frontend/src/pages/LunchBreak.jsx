import { useEffect, useState } from 'react'
import { Coffee, Pencil, RefreshCw, Save } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead } from '../components/ui'

const DEFAULT_SEQUENCE = ['IN', 'Lunch OUT', 'Lunch IN', 'Exit']

export default function LunchBreak() {
  const { has } = useAuth()
  const canManage = has('shift.manage')
  const canRecompute = has('attendance.manage')
  const [config, setConfig] = useState({ enabled: true, duration_minutes: 60, sequence: DEFAULT_SEQUENCE, shifts: [] })
  const [draft, setDraft] = useState({ enabled: true, duration_minutes: 60 })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [recomputing, setRecomputing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [minutes, setMinutes] = useState(0)

  const load = () => {
    setLoading(true)
    api.get('/lunch-break')
      .then((r) => {
        setConfig(r.data)
        setDraft({ enabled: r.data.enabled, duration_minutes: r.data.duration_minutes })
      })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const saveRule = async () => {
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const r = await api.put('/lunch-break', {
        enabled: draft.enabled,
        duration_minutes: Math.max(0, Number(draft.duration_minutes) || 0),
      })
      setConfig(r.data)
      setNotice('Lunch break rule saved. Use Recompute attendance to apply it to history.')
    } catch (err) { setError(errorMessage(err)) } finally { setSaving(false) }
  }

  const recompute = async () => {
    setRecomputing(true)
    setError('')
    setNotice('')
    try {
      const r = await api.post('/attendance/recompute-all')
      setNotice(r.data.message || 'Attendance recomputed')
    } catch (err) { setError(errorMessage(err)) } finally { setRecomputing(false) }
  }

  const openEdit = (row) => {
    setEditing(row)
    setMinutes(Number(row.break_minutes) || 0)
    setError('')
    setModal(true)
  }

  const saveShift = async () => {
    setError('')
    try {
      await api.put(`/shifts/${editing.id}`, { break_minutes: Math.max(0, Number(minutes) || 0) })
      setNotice(`Lunch break updated for ${editing.name}`)
      setModal(false)
      load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const sequence = config.sequence?.length === 4 ? config.sequence : DEFAULT_SEQUENCE

  return (
    <>
      <PageHead title="Lunch break" subtitle="Configure the 1-hour lunch punch sequence for employees" />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{notice}</Notice>

      <Card title="Lunch break rule"
        subtitle="The device records most punches as IN. The day's punches are read in order, so lunch is identified by position, not by device label.">
        <div className="form-grid">
          <Field label="Enable lunch deduction" hint="When on, a four-punch day has the configured lunch duration deducted.">
            <label className="inline-check">
              <input type="checkbox" checked={!!draft.enabled} disabled={!canManage}
                onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
              <span>{draft.enabled ? 'Enabled' : 'Disabled'}</span>
            </label>
          </Field>
          <Field label="Lunch duration (minutes)" hint="Default 60 minutes for employees. A shift override below wins when set.">
            <input type="number" min="0" max="1440" step="5" disabled={!canManage || !draft.enabled}
              value={draft.duration_minutes}
              onChange={(e) => setDraft({ ...draft, duration_minutes: e.target.value })} />
          </Field>
          <Field label="Punch sequence" full hint="1st punch = job IN, 2nd = Lunch OUT, 3rd = Lunch IN, 4th = end of day / Exit.">
            <div className="lunch-sequence">
              {sequence.map((label, index) => (
                <div className="lunch-step" key={`${index}-${label}`}>
                  <span className="lunch-step-no">{index + 1}</span>
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </Field>
        </div>
        <div className="toolbar" style={{ marginTop: 16 }}>
          {canManage && <button className="btn btn-primary" disabled={saving} onClick={saveRule}>
            <Save size={15} /> Save rule
          </button>}
          {canRecompute && <button className="btn btn-outline" disabled={recomputing} onClick={recompute}>
            <RefreshCw size={15} /> {recomputing ? 'Recomputing…' : 'Recompute attendance'}
          </button>}
        </div>
      </Card>

      <Card title={`Lunch break by shift (${config.shifts?.length || 0})`}
        subtitle="Shift override is optional. Blank / 0 uses the rule duration above.">
        <DataTable loading={loading} rows={config.shifts || []} emptyText="No shifts configured yet" columns={[
          { label: 'Shift', render: (r) => <><span className="strong">{r.name}</span><span className="sub">{r.is_active ? 'active' : 'inactive'}</span></> },
          { label: 'Timing', render: (r) => `${r.start_time || '—'} – ${r.end_time || '—'}` },
          { label: 'Shift override', render: (r) => <span className="mono">{r.break_minutes || '—'}</span> },
          { label: 'Applied lunch', render: (r) => <><span className="mono">{r.effective_minutes}</span><span className="sub">minutes</span></> },
          { label: 'Rule', render: () => <Badge status={config.enabled ? 'active' : 'inactive'} /> },
          ...(canManage ? [{ label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-outline btn-sm btn-icon" onClick={() => openEdit(r)} title="Edit lunch break"><Pencil size={14} /></button>
          </div> }] : []),
        ]} />
      </Card>

      <Modal open={modal} onClose={() => setModal(false)} title={`Lunch break — ${editing?.name || ''}`}
        footer={<><button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button><button className="btn btn-primary" onClick={saveShift}><Coffee size={15} /> Save</button></>}>
        <div className="form-grid">
          <Field label="Lunch minutes for this shift" full hint="Set 0 to use the global lunch duration. This overrides the global rule for this shift.">
            <input type="number" min="0" max="1440" step="5" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          </Field>
        </div>
      </Modal>
    </>
  )
}
