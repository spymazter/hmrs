import { useEffect, useMemo, useState } from 'react'
import { Download, FileText, Trash2, Upload } from 'lucide-react'
import api, { errorMessage } from '../api'
import { DOCUMENT_SIZE_MB, prepareDocument } from '../utils/documentUpload'
import {
  Badge, Card, DataTable, Field, Notice, PageHead, SearchableSelect, fmtDate,
} from '../components/ui'

const AUDIENCE_OPTIONS = [
  { value: 'all', label: 'All employees' },
  { value: 'employee', label: 'Specific employee' },
]

const today = () => new Date().toISOString().slice(0, 10)

export default function Circulars() {
  const [notices, setNotices] = useState([])
  const [employees, setEmployees] = useState([])
  const [form, setForm] = useState({
    title: '', audience: 'all', employee_id: '', issued_date: today(),
  })
  const [file, setFile] = useState(null)
  const [fileKey, setFileKey] = useState(0)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [uploading, setUploading] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await api.get('/circulars')
      setNotices(response.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    let active = true
    const loadEmployees = async () => {
      const all = []
      let skip = 0
      let total = 0
      for (;;) {
        const response = await api.get('/employees', { params: { skip, limit: 500 } })
        const items = response.data.items || []
        total = response.data.total || 0
        all.push(...items)
        skip += items.length
        if (!items.length || skip >= total) break
      }
      if (active) setEmployees(all)
    }
    loadEmployees().catch(() => {})
    return () => { active = false }
  }, [])

  const employeeOptions = useMemo(() => employees.map((employee) => ({
    value: employee.id,
    label: `${employee.employee_code} — ${employee.full_name || `${employee.first_name} ${employee.last_name}`.trim()}`,
  })), [employees])

  const upload = async () => {
    if (!form.title.trim()) {
      setError('Enter a title for the circular')
      return
    }
    if (form.audience === 'employee' && !form.employee_id) {
      setError('Select the employee this circular is issued to')
      return
    }
    if (!file) {
      setError('Choose a PDF, Word or image file')
      return
    }
    setError('')
    setSuccess('')
    setUploading(true)
    try {
      const prepared = await prepareDocument(file)
      const body = new FormData()
      body.append('title', form.title.trim())
      body.append('audience', form.audience)
      if (form.audience === 'employee') body.append('employee_id', String(form.employee_id))
      body.append('issued_date', form.issued_date || today())
      body.append('file', prepared)
      await api.post('/circulars', body)
      setForm({ title: '', audience: 'all', employee_id: '', issued_date: today() })
      setFile(null)
      setFileKey((value) => value + 1)
      setSuccess('Circular uploaded and published to the notice board')
      load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  const download = async (row) => {
    setError('')
    try {
      const response = await api.get(`/circulars/${row.id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.download = row.original_filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const remove = async (row) => {
    if (!window.confirm(`Remove circular "${row.title}"?`)) return
    setError('')
    try {
      await api.delete(`/circulars/${row.id}`)
      setSuccess('Circular removed')
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const columns = [
    {
      label: 'Circular',
      render: (row) => (
        <><strong>{row.title}</strong><div className="muted">{row.original_filename}</div></>
      ),
    },
    {
      label: 'Audience',
      render: (row) => (
        <Badge status={row.audience === 'all' ? 'generated' : 'holiday'}>
          {row.audience === 'all'
            ? 'All employees'
            : `${row.employee_code || ''} ${row.employee_name || ''}`.trim()}
        </Badge>
      ),
    },
    {
      label: 'Issued',
      render: (row) => fmtDate(row.issued_date),
    },
    {
      label: 'Views',
      render: (row) => (
        <Badge status={row.viewed_count >= row.target_count && row.target_count > 0 ? 'active' : 'pending'}>
          {row.viewed_count}/{row.target_count}
        </Badge>
      ),
    },
    {
      label: 'Uploaded',
      render: (row) => (
        <>{row.uploaded_by_name || 'HR'}<div className="muted">{fmtDate(row.created_at)}</div></>
      ),
    },
    {
      label: 'Actions',
      className: 'text-right',
      render: (row) => (
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <button className="btn btn-outline btn-sm" onClick={() => download(row)}><Download size={14} /> Download</button>
          <button className="btn btn-danger btn-sm" onClick={() => remove(row)}><Trash2 size={14} /> Delete</button>
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHead
        title="Circular notices"
        subtitle="Upload HR notices to the employee dashboard notice board"
      />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{success}</Notice>

      <div style={{ marginBottom: 16 }}>
        <Card title="Upload circular" subtitle="Issue a notice to every employee or select one employee">
          <div className="form-grid">
            <Field label="Title" full>
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="e.g. Diwali holiday notice"
              />
            </Field>
            <Field label="Audience">
              <SearchableSelect
                value={form.audience}
                onChange={(value) => setForm({ ...form, audience: value, employee_id: '' })}
                options={AUDIENCE_OPTIONS}
                placeholder="Select audience"
                clearable={false}
              />
            </Field>
            <Field label="Issued date">
              <input
                type="date"
                value={form.issued_date}
                onChange={(e) => setForm({ ...form, issued_date: e.target.value })}
              />
            </Field>
            {form.audience === 'employee' && (
              <Field label="Employee" full>
                <SearchableSelect
                  value={form.employee_id}
                  onChange={(value) => setForm({ ...form, employee_id: value })}
                  options={employeeOptions}
                  placeholder="Search employee…"
                  clearable={false}
                />
              </Field>
            )}
            <Field label="PDF, Word or image" full>
              <input
                key={fileKey}
                type="file"
                accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </Field>
            <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 12 }}>
              <button className="btn btn-primary" disabled={uploading} onClick={upload}>
                <Upload size={15} /> {uploading ? 'Uploading…' : 'Upload circular'}
              </button>
              <span className="muted" style={{ fontSize: 12 }}>
                Maximum {DOCUMENT_SIZE_MB} MB per file. Oversized images are compressed automatically.
              </span>
            </div>
          </div>
        </Card>
      </div>

      <Card title="Published circulars" subtitle="Employees see these on their dashboard notice board">
        <DataTable
          columns={columns}
          rows={notices}
          loading={loading}
          emptyText="No circulars uploaded yet"
        />
        <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
          <FileText size={13} style={{ verticalAlign: -2, marginRight: 5 }} />
          Views are recorded when an employee opens or acknowledges a circular in the dashboard.
        </p>
      </Card>
    </>
  )
}
