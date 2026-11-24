import { useEffect, useState } from 'react'
import { CalendarDays, Download, Pencil, UserCircle2, Wallet } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, Stat, fmtTime, todayStr } from '../components/ui'

export default function MyPortal() {
  const { user, setUser } = useAuth()
  const [profile, setProfile] = useState(null)
  const [attendance, setAttendance] = useState([])
  const [payslips, setPayslips] = useState([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [from, setFrom] = useState(new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10))
  const [editOpen, setEditOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({})

  const personalFields = [
    ['first_name', 'First name'], ['last_name', 'Last name'],
    ['date_of_birth', 'Date of birth'], ['email', 'Email'],
    ['phone', 'Phone'], ['alternate_phone', 'Alternate phone'],
    ['gender', 'Gender'], ['emergency_contact_name', 'Emergency contact name'],
    ['emergency_contact_phone', 'Emergency contact phone'],
    ['emergency_contact_relationship', 'Relationship'], ['address', 'Address'],
  ]

  useEffect(() => {
    api.get('/employees/me').then((r) => setProfile(r.data)).catch((e) => setError(errorMessage(e)))
    api.get(`/attendance/records?from_date=${from}&to_date=${todayStr()}&limit=100`).then((r) => setAttendance(r.data.items)).catch((e) => setError(errorMessage(e)))
    api.get('/payroll/payslips').then((r) => setPayslips(r.data)).catch(() => {})
  }, [from])

  const download = async (slip) => {
    try {
      const res = await api.get(`/payroll/payslips/${slip.id}/pdf`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
      const link = document.createElement('a')
      link.href = url; link.download = `salary_slip_${slip.period_name}.pdf`; link.click()
      URL.revokeObjectURL(url)
    } catch (err) { setError(errorMessage(err)) }
  }

  const downloadAll = async () => {
    setError(''); setNotice('')
    try {
      const res = await api.post('/payroll/payslips/download-zip', { period_ids: [] }, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/zip' }))
      const link = document.createElement('a')
      link.href = url; link.download = `salary_slips_${user?.username || 'me'}.zip`; link.click()
      URL.revokeObjectURL(url)
      setNotice('All available salary slips downloaded')
    } catch (err) { setError(errorMessage(err)) }
  }

  const openEdit = () => {
    setError(''); setNotice('')
    setForm(Object.fromEntries(personalFields.map(([key]) => [key, profile?.[key] ?? ''])))
    setEditOpen(true)
  }

  const saveProfile = async () => {
    setSaving(true); setError(''); setNotice('')
    try {
      const r = await api.put('/employees/me', form)
      setProfile(r.data)
      setUser((u) => u ? {
        ...u,
        full_name: `${r.data.first_name} ${r.data.last_name}`.trim() || u.full_name,
        email: r.data.email || u.email,
      } : u)
      setEditOpen(false)
      setNotice('Personal details updated')
    } catch (err) { setError(errorMessage(err)) } finally { setSaving(false) }
  }

  const present = attendance.filter((a) => a.status === 'present').length

  return (
    <>
      <PageHead title="My portal" subtitle="Your profile, attendance history and salary slips"
        actions={<>
          <button className="btn btn-outline" disabled={!payslips.length} onClick={downloadAll}><Download size={15} /> Download all slips</button>
          <button className="btn btn-primary" disabled={!profile} onClick={openEdit}><Pencil size={15} /> Edit personal details</button>
        </>} />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Stat icon={<UserCircle2 size={19} />} label="Employee code" value={profile?.employee_code || '—'} />
        <Stat icon={<CalendarDays size={19} />} label="Days present" value={present} foot={`of ${attendance.length} working days`} color="#16a34a" />
        <Stat icon={<Wallet size={19} />} label="Salary slips" value={payslips.length} color="#0284c7" />
        <Stat icon={<Wallet size={19} />} label="Latest net pay" value={payslips[0] ? `₹${payslips[0].net_salary.toLocaleString('en-IN')}` : '—'} color="#d97706" />
      </div>

      <div className="grid grid-2">
        <Card title="My attendance" subtitle="Last 30 days">
          <div className="toolbar"><div className="field-inline"><label>From</label><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} style={{ width: 160 }} /></div></div>
          <DataTable rows={attendance.slice(0, 15)} emptyText="No attendance records" columns={[
            { label: 'Date', render: (r) => <span className="strong">{r.record_date}</span> },
            { label: 'In', render: (r) => <span className="mono">{fmtTime(r.check_in)}</span> },
            { label: 'Out', render: (r) => <span className="mono">{fmtTime(r.check_out)}</span> },
            { label: 'Hours', render: (r) => <span className="mono">{r.total_hours}</span> },
            { label: 'Status', render: (r) => <Badge status={r.status} /> },
          ]} />
        </Card>
        <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <Card title="My salary slips">
            <DataTable rows={payslips} emptyText="No salary slips available" columns={[
              { label: 'Period', render: (r) => <span className="strong">{r.period_name}</span> },
              { label: 'Net pay', render: (r) => `₹${Number(r.net_salary).toLocaleString('en-IN')}` },
              { label: 'Status', render: (r) => <Badge status={r.status} /> },
              { label: '', className: 'text-right', render: (r) => <button className="btn btn-outline btn-sm" onClick={() => download(r)}><Download size={14} /> PDF</button> },
            ]} />
          </Card>
          <Card title="Profile details">
            {profile ? <div style={{ display: 'grid', gap: 9 }}>
              {[
                ['Name', `${profile.first_name} ${profile.last_name}`],
                ['Username', user?.username || '—'],
                ['Date of birth', profile.date_of_birth || '—'],
                ['Email', profile.email || '—'],
                ['Phone', profile.phone || '—'],
                ['Alternate phone', profile.alternate_phone || '—'],
                ['Emergency contact', profile.emergency_contact_name ? `${profile.emergency_contact_name}${profile.emergency_contact_phone ? ` · ${profile.emergency_contact_phone}` : ''}` : '—'],
                ['Relationship', profile.emergency_contact_relationship || '—'],
                ['Address', profile.address || '—'],
                ['Department', profile.department_name || '—'],
                ['Designation', profile.designation_name || '—'],
                ['Shift', profile.shift_name || '—'],
                ['Device UID', profile.device_user_id || '—'],
                ['Date of joining', profile.date_of_joining || '—'],
              ].map(([label, value]) => <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12.5 }}><span style={{ color: '#64748b' }}>{label}</span><strong style={{ textAlign: 'right' }}>{value}</strong></div>)}
            </div> : <div className="loader">Loading profile…</div>}
          </Card>
        </div>
      </div>

      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="Edit personal details" width={720}
        footer={<>
          <button className="btn btn-outline" onClick={() => setEditOpen(false)}>Cancel</button>
          <button className="btn btn-primary" disabled={saving} onClick={saveProfile}>{saving ? 'Saving…' : 'Save changes'}</button>
        </>}>
        <Notice type="info">Your username and employee code are fixed. Contact HR if they need correction.</Notice>
        <div className="form-grid">
          {personalFields.map(([key, label]) => (
            <Field key={key} label={label} full={key === 'address'}>
              <input
                type={key === 'date_of_birth' ? 'date' : key === 'email' ? 'email' : 'text'}
                value={form[key] ?? ''}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </Field>
          ))}
        </div>
      </Modal>
    </>
  )
}
