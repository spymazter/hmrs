import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CalendarCheck2, ClipboardList, Clock3, Download, FileText, Megaphone, TrendingUp, UserCheck, UserX, Users, Wallet } from 'lucide-react'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { Badge, Card, Notice, PageHead, Stat, fmtDate, todayStr } from '../components/ui'

export default function Dashboard() {
  const { user, has } = useAuth()
  const [data, setData] = useState(null)
  const [circulars, setCirculars] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/dashboard/summary')
      .then((res) => { setData(res.data); setCirculars(res.data.circulars || []) })
      .catch((err) => setError(err.response?.data?.detail || 'Unable to load dashboard'))
  }, [])

  const markViewed = async (circular) => {
    if (circular.viewed_by_me) return
    try {
      const response = await api.post(`/circulars/${circular.id}/view`)
      setCirculars((items) => items.map((item) => item.id === circular.id ? response.data : item))
    } catch (err) {
      setError(err.response?.data?.detail || 'Unable to record the circular view')
    }
  }

  const openCircular = async (circular) => {
    await markViewed(circular)
    try {
      const response = await api.get(`/circulars/${circular.id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.download = circular.original_filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.response?.data?.detail || 'Unable to open the circular')
    }
  }

  const quickLinks = [
    ...(has('employee.view') ? [{ to: '/employees', label: 'Employees', icon: Users, desc: 'Add or edit employee records' }] : []),
    ...(has('attendance.view') ? [{ to: '/attendance', label: 'Attendance', icon: CalendarCheck2, desc: 'Review punches and daily records' }] : []),
    ...(has('report.view') ? [{ to: '/reports', label: 'Reports', icon: TrendingUp, desc: 'Daily, weekly and monthly views' }] : []),
    ...(has('payroll.view', 'payslip.view') ? [{ to: '/payroll', label: 'Payroll', icon: Wallet, desc: 'Process salary and download slips' }] : []),
    { to: '/portal', label: 'My portal', icon: UserCheck, desc: 'Your own attendance and payslips' },
  ]

  return (
    <>
      <PageHead
        title={`Good day, ${(user?.full_name || user?.username || 'there').split(' ')[0]}`}
        subtitle="Here is what is happening across your workplace today."
      />
      <Notice type="error">{error}</Notice>

      {circulars.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Card
            title="Circular notices"
            subtitle={`${circulars.filter((item) => !item.viewed_by_me).length} unread · HR notices and announcements`}
          >
            <div style={{ display: 'grid', gap: 10 }}>
              {circulars.map((circular) => (
                <div
                  key={circular.id}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 14px', borderRadius: 8,
                    background: circular.viewed_by_me ? '#f8fafc' : '#eef2ff',
                  }}
                >
                  <div className="kpi-icon" style={{ background: circular.viewed_by_me ? '#e2e8f0' : '#dbeafe', color: '#4f46e5' }}>
                    <Megaphone size={18} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <strong style={{ color: '#0f172a', fontSize: 13 }}>{circular.title}</strong>
                      {!circular.viewed_by_me && <Badge status="pending">New</Badge>}
                    </div>
                    <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
                      <FileText size={12} style={{ verticalAlign: -2, marginRight: 4 }} />
                      {circular.original_filename} · Issued {fmtDate(circular.issued_date)}
                      {circular.viewed_at ? ` · Viewed ${fmtDate(circular.viewed_at)}` : ''}
                    </div>
                  </div>
                  <button className="btn btn-outline btn-sm" onClick={() => openCircular(circular)}>
                    <Download size={14} /> Open
                  </button>
                  {!circular.viewed_by_me && (
                    <button className="btn btn-primary btn-sm" onClick={() => markViewed(circular)}>
                      Mark viewed
                    </button>
                  )}
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {!data ? <div className="loader">Loading dashboard…</div> : (
        <>
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <Stat
              icon={<Users size={20} />}
              label="Active employees"
              value={data.total_employees}
              foot="Currently on roll · click to view"
              to={has('employee.view') ? '/employees?status=active' : undefined}
            />
            <Stat
              icon={<UserCheck size={20} />}
              label="Present today"
              value={data.present_today}
              foot={`${data.late_today} late arrivals · click to view`}
              color="#16a34a"
              to={has('attendance.view') ? `/attendance?date=${todayStr()}&status=attended` : undefined}
            />
            <Stat
              icon={<UserX size={20} />}
              label="Absent today"
              value={data.absent_today}
              foot={`${data.on_leave_today} on leave · click to view`}
              color="#dc2626"
              to={has('attendance.view') ? `/attendance?date=${todayStr()}&status=absent` : undefined}
            />
            <Stat icon={<Clock3 size={20} />} label="Avg. hours / week" value={data.avg_hours_week} foot="Per employee with punches" color="#d97706" />
          </div>

          <div className="grid" style={{ gridTemplateColumns: '1.6fr 1fr', gap: 16 }}>
            <Card title="Attendance trend" subtitle="Present versus absent over the last 7 days">
              <div style={{ height: 250 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.trend} barSize={18}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#64748b' }} />
                    <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#64748b' }} />
                    <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }} />
                    <Bar dataKey="present" name="Present" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="absent" name="Absent" fill="#fca5a5" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Today's summary" subtitle={data.date}>
              <div style={{ display: 'grid', gap: 10 }}>
                {[
                  { label: 'Present / half day', value: data.present_today, color: '#16a34a' },
                  { label: 'Absent', value: data.absent_today, color: '#dc2626' },
                  { label: 'On leave', value: data.on_leave_today, color: '#0284c7' },
                  { label: 'Late arrivals', value: data.late_today, color: '#d97706' },
                ].map((row) => (
                  <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 12px', background: '#f8fafc', borderRadius: 8 }}>
                    <span style={{ color: '#475569' }}>{row.label}</span>
                    <strong style={{ color: row.color }}>{row.value}</strong>
                  </div>
                ))}
                <div style={{ marginTop: 4, padding: '12px', background: '#eef2ff', borderRadius: 8, fontSize: 12, color: '#4338ca' }}>
                  <ClipboardList size={14} style={{ verticalAlign: -3, marginRight: 6 }} />
                  {data.pending_payslips} salary slip(s) awaiting payment · {data.open_payroll_periods} open period(s)
                </div>
              </div>
            </Card>
          </div>

          <div className="grid grid-3" style={{ marginTop: 16 }}>
            {quickLinks.slice(0, 4).map((link) => (
              <Link to={link.to} key={link.to} className="card" style={{ padding: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
                <div className="kpi-icon" style={{ background: '#eef2ff', color: '#4f46e5' }}><link.icon size={19} /></div>
                <div><strong style={{ color: '#0f172a', fontSize: 13 }}>{link.label}</strong><div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>{link.desc}</div></div>
              </Link>
            ))}
          </div>
        </>
      )}
    </>
  )
}
