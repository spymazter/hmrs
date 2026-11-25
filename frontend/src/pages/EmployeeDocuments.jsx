import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, FileText, Trash2, Upload } from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import {
  Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect, fmtDate,
} from '../components/ui'

const CATEGORIES = [
  { value: 'appointment_order', label: 'Appointment order' },
  { value: 'medical_fitness', label: 'Medical fitness certificate' },
  { value: 'antecedent_verification', label: 'Antecedent verification form (HR only)' },
  { value: 'employee_pan', label: 'Employee PAN card' },
  { value: 'employee_aadhaar', label: 'Employee Aadhaar card' },
  { value: 'nominee_pan', label: 'Nominee PAN card' },
  { value: 'nominee_aadhaar', label: 'Nominee Aadhaar card' },
]

const EMPTY = { employee_id: '', category: 'appointment_order' }

export default function EmployeeDocuments() {
  const { user, has } = useAuth()
  const isHR = (user?.roles || []).some((role) =>
    ['HR Manager', 'Admin'].includes(role?.name)) || user?.username === 'admin'
  const canUpload = isHR && has('document.manage')

  const [rows, setRows] = useState([])
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [modal, setModal] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const fileRef = useRef(null)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const params = {}
      if (category) params.category = category
      const response = await api.get('/employee-documents', { params })
      setRows(response.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [category])

  useEffect(() => {
    if (!isHR) return
    api.get('/employees?limit=500')
      .then((r) => setEmployees(r.data.items || []))
      .catch(() => {})
  }, [isHR])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((row) =>
      [row.employee_code, row.employee_name, row.original_filename, row.category_label]
        .some((value) => String(value || '').toLowerCase().includes(q)))
  }, [rows, search])

  const download = async (row) => {
    setError('')
    try {
      const response = await api.get(`/employee-documents/${row.id}/download`, { responseType: 'blob' })
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

  const upload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!form.employee_id || !form.category) {
      setError('Select an employee and document type first')
      return
    }
    setError('')
    setNotice('')
    const body = new FormData()
    body.append('employee_id', String(form.employee_id))
    body.append('category', form.category)
    body.append('file', file)
    try {
      const response = await api.post('/employee-documents', body)
      setNotice(`${response.data.category_label} uploaded for ${response.data.employee_code}`)
      setModal(false)
      setForm(EMPTY)
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const remove = async (row) => {
    if (!window.confirm(`Remove ${row.original_filename}?`)) return
    setError('')
    try {
      await api.delete(`/employee-documents/${row.id}`)
      setNotice('Document removed')
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const columns = [
    ...(isHR ? [{
      key: 'employee',
      label: 'Employee',
      render: (row) => (
        <><strong>{row.employee_code}</strong><div className="muted">{row.employee_name}</div></>
      ),
    }] : []),
    {
      key: 'category',
      label: 'Document',
      render: (row) => <Badge status={row.category === 'antecedent_verification' ? 'pending' : 'info'}>{row.category_label}</Badge>,
    },
    {
      key: 'file',
      label: 'File',
      render: (row) => (
        <><div>{row.original_filename}</div><div className="muted">{Math.ceil((row.size_bytes || 0) / 1024)} KB</div></>
      ),
    },
    {
      key: 'uploaded',
      label: 'Uploaded',
      render: (row) => (
        <>{fmtDate(row.uploaded_at)}<div className="muted">{row.uploaded_by_name || 'HR'}</div></>
      ),
    },
    {
      key: 'actions',
      label: 'Actions',
      className: 'text-right',
      render: (row) => (
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <button className="btn btn-outline btn-sm" onClick={() => download(row)}><Download size={14} /> Download</button>
          {canUpload && <button className="btn btn-outline btn-sm" onClick={() => remove(row)}><Trash2 size={14} /></button>}
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHead
        title="Employee documents"
        subtitle="HR documents and employee-uploaded PAN / Aadhaar KYC files"
        actions={canUpload && (
          <button className="btn btn-primary" onClick={() => { setForm(EMPTY); setModal(true) }}>
            <Upload size={15} /> Upload document
          </button>
        )}
      />
      <Notice type="error">{error}</Notice>
      <Notice type="success">{notice}</Notice>
      <Card>
        <div className="toolbar">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employee or file…" style={{ width: 260 }} />
          <SearchableSelect
            value={category}
            onChange={setCategory}
            options={[{ value: '', label: 'All document types' }, ...CATEGORIES.filter((c) => isHR || c.value !== 'antecedent_verification')]}
            placeholder="All document types"
            style={{ width: 260 }}
          />
        </div>
        <DataTable
          columns={columns}
          rows={filtered}
          loading={loading}
          emptyText={isHR ? 'No documents uploaded yet' : 'No documents available for your profile'}
        />
        <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
          Employees can download their own documents and upload PAN / Aadhaar cards from My portal. HR sees every document; antecedent verification forms are HR-only.
        </p>
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title="Upload employee document"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setModal(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={() => fileRef.current?.click()}><Upload size={15} /> Choose file</button>
          </>
        }
      >
        <div className="form-grid">
          <Field label="Employee" full>
            <SearchableSelect
              value={form.employee_id}
              onChange={(value) => setForm({ ...form, employee_id: value })}
              options={employees.map((e) => ({
                value: e.id,
                label: `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`.trim()}`,
              }))}
              placeholder="Search employee…"
              clearable={false}
            />
          </Field>
          <Field label="Document type" full>
            <SearchableSelect
              value={form.category}
              onChange={(value) => setForm({ ...form, category: value })}
              options={CATEGORIES}
              placeholder="Select document type"
              clearable={false}
            />
          </Field>
        </div>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
          onChange={upload}
        />
        <p className="muted" style={{ fontSize: 12 }}>
          PDF, Word or image files up to 20 MB. Uploading another file of the same type keeps both versions; the newest appears first.
        </p>
      </Modal>
    </>
  )
}
