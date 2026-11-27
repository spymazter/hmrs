import { useEffect, useState } from 'react'
import { Download, FileText, Megaphone, RefreshCw } from 'lucide-react'
import api, { errorMessage } from '../api'
import { Badge, Card, Notice, PageHead, fmtDate } from '../components/ui'

export default function NoticeBoard() {
  const [notices, setNotices] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await api.get('/circulars/inbox')
      setNotices(response.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const markViewed = async (circular) => {
    if (circular.viewed_by_me) return circular
    const response = await api.post(`/circulars/${circular.id}/view`)
    setNotices((items) => items.map((item) => item.id === circular.id ? response.data : item))
    return response.data
  }

  const open = async (circular) => {
    setError('')
    try {
      await markViewed(circular)
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
      setError(errorMessage(err))
    }
  }

  const acknowledge = async (circular) => {
    setError('')
    try { await markViewed(circular) }
    catch (err) { setError(errorMessage(err)) }
  }

  const unread = notices.filter((item) => !item.viewed_by_me).length

  return (
    <>
      <PageHead
        title="Notice board"
        subtitle="Circulars issued by HR for all employees or for you"
        actions={<button className="btn btn-outline" onClick={load}><RefreshCw size={15} /> Refresh</button>}
      />
      <Notice type="error">{error}</Notice>

      <Card
        title="Circulars"
        subtitle={`${unread} unread · ${notices.length} circular${notices.length === 1 ? '' : 's'}`}
      >
        {loading ? <div className="loader">Loading notice board…</div> : notices.length === 0 ? (
          <p className="muted">No circulars have been issued yet.</p>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {notices.map((circular) => (
              <div
                key={circular.id}
                style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '14px', borderRadius: 8,
                  background: circular.viewed_by_me ? '#f8fafc' : '#eef2ff',
                }}
              >
                <div className="kpi-icon" style={{
                  background: circular.viewed_by_me ? '#e2e8f0' : '#dbeafe',
                  color: '#4f46e5',
                }}>
                  <Megaphone size={18} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <strong style={{ color: '#0f172a', fontSize: 14 }}>{circular.title}</strong>
                    {!circular.viewed_by_me && <Badge status="pending">New</Badge>}
                    <Badge status="info">{circular.audience_label}</Badge>
                  </div>
                  <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                    <FileText size={12} style={{ verticalAlign: -2, marginRight: 4 }} />
                    {circular.original_filename} · Issued {fmtDate(circular.issued_date)}
                    {circular.viewed_at ? ` · Viewed ${fmtDate(circular.viewed_at)}` : ''}
                  </div>
                </div>
                <button className="btn btn-outline btn-sm" onClick={() => open(circular)}>
                  <Download size={14} /> Open
                </button>
                {!circular.viewed_by_me && (
                  <button className="btn btn-primary btn-sm" onClick={() => acknowledge(circular)}>
                    Mark viewed
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  )
}
