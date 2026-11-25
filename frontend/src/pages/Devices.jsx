import { useEffect, useRef, useState } from 'react'
import { Download, Fingerprint, Pencil, PlugZap, RefreshCw, Server } from 'lucide-react'
import api, { errorMessage } from '../api'
import { Badge, Card, Field, Modal, Notice, PageHead, SearchableSelect } from '../components/ui'

const MODE_OPTIONS = [
  { value: 'live', label: 'Live device' },
  { value: 'simulate', label: 'Simulation (demo)' },
]
const YES_NO_OPTIONS = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
]

function SyncLog({ job, onClear }) {
  const endRef = useRef(null)
  const lines = job?.logs || []
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }) }, [lines.length])

  const pct = job?.total ? Math.min(100, Math.round((job.processed || 0) / job.total * 100)) : 0
  const status = job?.status || 'running'
  const summary = job?.total
    ? `${job.processed || 0} / ${job.total} punches scanned · ${job.new_punches || 0} new`
    : status === 'running' ? 'Connecting to device…' : 'Finished · no new punches'

  return (
    <div className="sync-log">
      <div className="sync-log-head">
        <span><RefreshCw size={12} style={{ verticalAlign: -2, marginRight: 6 }} /> Sync log · job #{job?.id}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {job?.full_history && <span className="chip">Full history</span>}
          <span className="sync-log-phase">{status} / {job?.phase || 'queued'}</span>
          <button className="btn btn-sm btn-outline" style={{ background: '#334155', color: '#e2e8f0', borderColor: '#475569' }} onClick={onClear}>Clear</button>
        </span>
      </div>
      <div className="sync-log-bar"><i style={{ width: `${pct}%` }} /></div>
      <div className="sync-log-body">
        {lines.map((line, i) => (
          <div className="sync-log-line" key={i}>
            <span className="sync-log-time">{line.time || ''}</span>
            <span className="sync-log-tag">[{line.phase}]</span>
            <span>{line.message}</span>
          </div>
        ))}
        {status === 'running' && <div className="sync-log-line"><span className="sync-log-tag">[live]</span><span>Waiting for next update…</span></div>}
        <div ref={endRef} />
      </div>
      <div className="sync-log-foot">
        {summary}
        {job?.message ? ` · ${job.message}` : ''}
      </div>
    </div>
  )
}

export default function Devices() {
  const [devices, setDevices] = useState([])
  const [settings, setSettings] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(null)
  const [activeJobs, setActiveJobs] = useState({})   // device_id -> job_id
  const [jobs, setJobs] = useState({})               // job_id -> job detail
  const [history, setHistory] = useState([])
  const [fullConfirm, setFullConfirm] = useState(null)
  const finishedRef = useRef(new Set())              // job ids that already completed

  const load = () => {
    api.get('/devices').then((r) => setDevices(r.data)).catch((e) => setError(errorMessage(e)))
    api.get('/devices/settings').then((r) => setSettings(r.data)).catch(() => {})
    api.get('/devices/sync-jobs?limit=8').then((r) => setHistory(r.data)).catch(() => {})
  }
  useEffect(() => { load() }, [])

  // Poll every active sync job so its log window updates while it runs.
  useEffect(() => {
    const ids = Object.values(activeJobs)
    if (!ids.length) return
    const timer = setInterval(async () => {
      for (const id of ids) {
        if (finishedRef.current.has(id)) continue
        try {
          const r = await api.get(`/devices/sync-jobs/${id}`)
          const detail = r.data
          setJobs((prev) => ({ ...prev, [id]: detail }))
          if (detail.status !== 'running') {
            finishedRef.current.add(id)
            setNotice(detail.message || `Sync ${detail.status}`)
            load()
          }
        } catch (err) {
          setError(errorMessage(err))
        }
      }
    }, 700)
    return () => clearInterval(timer)
  }, [activeJobs])

  const test = async (device) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const r = await api.post('/devices/test', null, { params: { ip: device.ip_address, port: device.port } })
      if (r.data.success) setNotice(`Connected to ${device.ip_address}:${device.port} — ${r.data.users} users, ${r.data.attendance_records} punch records`)
      else setError(`Connection failed: ${r.data.message}`)
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const sync = async (device, fullHistory = false) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const r = await api.post(`/devices/${device.id}/sync-job`, null, { params: fullHistory ? { full_history: true } : {} })
      const jobId = r.data.job_id
      if (activeJobs[device.id]) finishedRef.current.delete(activeJobs[device.id])
      setJobs((prev) => ({
        ...prev,
        [jobId]: {
          id: jobId, device_id: device.id, status: 'running', phase: 'queued',
          processed: 0, total: 0, new_punches: 0, new_employees: 0,
          full_history: fullHistory,
          logs: [{ time: new Date().toISOString().slice(11, 19), phase: 'queued', message: `${fullHistory ? 'Starting full-history download' : 'Starting sync'} for ${device.ip_address}:${device.port}` }],
        },
      }))
      setActiveJobs((prev) => ({ ...prev, [device.id]: jobId }))
      load()
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  const save = async () => {
    try {
      await api.put(`/devices/${modal.id}`, modal)
      setModal(null); setNotice('Device settings saved — the new IP/port is used by the next sync immediately'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  return (
    <>
      <PageHead title="Biometric devices" subtitle="Manage the eSSL / ZKTeco device connection and punch synchronization" />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <Notice type="info">
        Device mode <strong>{settings?.mode || '—'}</strong> · configured endpoint <strong>{settings?.configured_ip}:{settings?.configured_port}</strong> ·
        auto-sync every {settings?.sync_interval_minutes} min. Change the IP/port with <strong>Edit</strong> — the saved value is used by the next sync immediately, no restart needed.
        Set <code>DEVICE_MODE=live</code> in <code>.env</code> for fresh installs.
      </Notice>

      <div className="grid grid-2">
        {devices.map((device) => {
          const jobId = activeJobs[device.id]
          const job = jobId ? jobs[jobId] : null
          const running = job?.status === 'running'
          return (
            <Card key={device.id} title={<span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Server size={16} /> {device.name}</span>}
              actions={<Badge status={device.mode}>{device.mode}</Badge>}>
              <div style={{ display: 'grid', gap: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#64748b' }}>IP address</span><strong className="mono">{device.ip_address}</strong></div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#64748b' }}>TCP port</span><strong className="mono">{device.port}</strong></div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#64748b' }}>Last sync</span><strong>{device.last_sync_at ? new Date(device.last_sync_at).toLocaleString() : 'Never'}</strong></div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#64748b' }}>Status</span><Badge status={device.is_active ? 'active' : 'inactive'} /></div>
                {device.last_error && <div className="notice notice-error" style={{ margin: 0 }}>{device.last_error}</div>}
                <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                  <button className="btn btn-outline" disabled={busy} onClick={() => test(device)}><PlugZap size={15} /> Test connection</button>
                  <button className="btn btn-primary" disabled={busy || running} onClick={() => sync(device)}><RefreshCw size={15} /> Sync punches now</button>
                  <button className="btn btn-outline" disabled={busy || running} onClick={() => setFullConfirm(device)}><Download size={15} /> Download all logs</button>
                  <button className="btn btn-outline" onClick={() => setModal({ ...device })}><Pencil size={14} /> Edit IP / settings</button>
                </div>
                {job && <SyncLog job={job} onClear={() => {
                  finishedRef.current.delete(jobId)
                  setActiveJobs((prev) => { const next = { ...prev }; delete next[device.id]; return next })
                }} />}
              </div>
            </Card>
          )
        })}
        {!devices.length && <Card><div className="empty">No device configured</div></Card>}
      </div>

      <Card title="Recent sync runs">
        {history.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Job</th><th>Status</th><th>Mode</th><th>Phase</th><th>Punches</th><th>New employees</th><th>Started</th><th>Message</th></tr></thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="mono">#{h.id}</td>
                    <td><Badge status={h.status === 'success' ? 'active' : h.status === 'failed' ? 'inactive' : 'pending'}>{h.status}</Badge></td>
                    <td>{h.full_history ? 'Full history' : 'Incremental'}</td>
                    <td>{h.phase}</td>
                    <td>{h.new_punches}{h.total ? ` / ${h.total}` : ''}</td>
                    <td>{h.new_employees}</td>
                    <td>{new Date(h.started_at).toLocaleString()}</td>
                    <td style={{ maxWidth: 320 }}>{h.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty">No sync runs yet</div>}
      </Card>

      <Card title="How synchronization works">
        <div style={{ display: 'grid', gap: 8, color: '#475569', lineHeight: 1.7, fontSize: 13 }}>
          <p style={{ margin: 0 }}><Fingerprint size={14} style={{ verticalAlign: -2, color: '#4f46e5' }} /> The backend speaks the ZKTeco/eSSL TCP protocol on port <strong>4370</strong> using the <code>pyzk</code> client.</p>
          <p style={{ margin: 0 }}>Each punch is stored as a raw log. The attendance engine pairs the first and last punch of the day, then applies the employee's shift rules (late grace, half day, overtime, weekly off).</p>
          <p style={{ margin: 0 }}>New device enrolment IDs are automatically created as employees when <strong>auto-create users</strong> is enabled. Map them to your employee master from the Employees page.</p>
          <p style={{ margin: 0 }}>The sync is read-only on the device. A high-water mark skips punches already imported, so repeat syncs show <strong>0 new</strong>.</p>
          <p style={{ margin: 0 }}><Download size={14} style={{ verticalAlign: -2, color: '#4f46e5' }} /> Use <strong>Download all logs</strong> to scan the device's complete attendance history from the beginning. Every missing punch is imported, duplicates are skipped and the device data is never changed.</p>
        </div>
      </Card>

      <Modal open={!!modal} onClose={() => setModal(null)} title="Edit device connection"
        footer={<><button className="btn btn-outline" onClick={() => setModal(null)}>Cancel</button><button className="btn btn-primary" onClick={save}>Save</button></>}>
        {modal && <div className="form-grid">
          <Field label="Device name" full><input value={modal.name} onChange={(e) => setModal({ ...modal, name: e.target.value })} /></Field>
          <Field label="IP address"><input value={modal.ip_address} onChange={(e) => setModal({ ...modal, ip_address: e.target.value })} /></Field>
          <Field label="TCP port"><input type="number" value={modal.port} onChange={(e) => setModal({ ...modal, port: +e.target.value })} /></Field>
          <Field label="Mode"><SearchableSelect value={modal.mode} onChange={(v) => setModal({ ...modal, mode: v })} options={MODE_OPTIONS} clearable={false} /></Field>
          <Field label="Enabled"><SearchableSelect value={modal.is_active ? 'yes' : 'no'} onChange={(v) => setModal({ ...modal, is_active: v === 'yes' })} options={YES_NO_OPTIONS} clearable={false} /></Field>
        </div>}
      </Modal>

      <Modal open={!!fullConfirm} onClose={() => setFullConfirm(null)} title="Download all logs from the device"
        footer={<>
          <button className="btn btn-outline" onClick={() => setFullConfirm(null)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => { const device = fullConfirm; setFullConfirm(null); sync(device, true) }}><Download size={15} /> Download all logs</button>
        </>}>
        <div style={{ display: 'grid', gap: 10, lineHeight: 1.7, fontSize: 13, color: '#475569' }}>
          <p style={{ margin: 0 }}>This will read the <strong>complete attendance log</strong> from <strong className="mono">{fullConfirm?.ip_address}:{fullConfirm?.port}</strong>, from the earliest record on the device, and import every punch missing in HRMS.</p>
          <p style={{ margin: 0 }}>Punches already imported are skipped, so no duplicates are created. Attendance is recalculated for any dates that receive new punches.</p>
          <p style={{ margin: 0 }}>The device is only read — no logs, users, settings or time are changed. Large histories may take a few minutes; progress appears in the sync log.</p>
        </div>
      </Modal>
    </>
  )
}
