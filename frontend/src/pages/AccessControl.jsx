import { useEffect, useState } from 'react'
import { KeyRound, Plus, ShieldCheck, Users, Layers3 } from 'lucide-react'
import api, { errorMessage } from '../api'
import { Badge, Card, DataTable, Field, Modal, Notice, PageHead, SearchableSelect } from '../components/ui'

const ACTIVE_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
]

export default function AccessControl() {
  const [tab, setTab] = useState('users')
  const [users, setUsers] = useState([])
  const [roles, setRoles] = useState([])
  const [groups, setGroups] = useState([])
  const [permissions, setPermissions] = useState([])
  const [employees, setEmployees] = useState([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [roleModal, setRoleModal] = useState(null)
  const [groupModal, setGroupModal] = useState(null)
  const [userModal, setUserModal] = useState(null)
  const [assignModal, setAssignModal] = useState(null)

  const load = () => {
    api.get('/access/users').then((r) => setUsers(r.data)).catch((e) => setError(errorMessage(e)))
    api.get('/access/roles').then((r) => setRoles(r.data)).catch(() => {})
    api.get('/access/groups').then((r) => setGroups(r.data)).catch(() => {})
    api.get('/access/permissions').then((r) => setPermissions(r.data)).catch(() => {})
    api.get('/employees?limit=500').then((r) => setEmployees(r.data.items)).catch(() => {})
  }
  useEffect(() => { load() }, [])

  const toggleInList = (state, setter, key, value) => {
    const list = state[key] || []
    setter({ ...state, [key]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] })
  }

  const saveRole = async () => {
    try {
      const payload = { name: roleModal.name, description: roleModal.description, permissions: roleModal.permissions || [] }
      if (roleModal.id) await api.put(`/access/roles/${roleModal.id}`, payload)
      else await api.post('/access/roles', payload)
      setRoleModal(null); setNotice('Role saved'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const saveGroup = async () => {
    try {
      const payload = { name: groupModal.name, description: groupModal.description, role_ids: groupModal.role_ids || [] }
      if (groupModal.id) await api.put(`/access/groups/${groupModal.id}`, payload)
      else await api.post('/access/groups', payload)
      setGroupModal(null); setNotice('Role group saved'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const saveUser = async () => {
    try {
      const payload = { ...userModal }
      if (payload.id) {
        delete payload.id
        delete payload.role_ids
        delete payload.group_ids
        if (!payload.password) delete payload.password
        await api.put(`/access/users/${userModal.id}`, payload)
      }
      else await api.post('/access/users', payload)
      setUserModal(null); setNotice('User saved'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const assign = async () => {
    try {
      await api.post(`/access/users/${assignModal.id}/assign`, { role_ids: assignModal.role_ids || [], group_ids: assignModal.group_ids || [] })
      setAssignModal(null); setNotice('Roles and groups assigned'); load()
    } catch (err) { setError(errorMessage(err)) }
  }

  const groupedPermissions = permissions.reduce((acc, p) => { (acc[p.module] ||= []).push(p); return acc }, {})

  return (
    <>
      <PageHead title="Roles & access" subtitle="Combine multiple roles into groups and assign them to users" />
      <Notice type="error">{error}</Notice><Notice type="success">{notice}</Notice>
      <div className="tabs">
        <button className={`tab ${tab === 'users' ? 'active' : ''}`} onClick={() => setTab('users')}><Users size={15} /> Users ({users.length})</button>
        <button className={`tab ${tab === 'roles' ? 'active' : ''}`} onClick={() => setTab('roles')}><ShieldCheck size={15} /> Roles ({roles.length})</button>
        <button className={`tab ${tab === 'groups' ? 'active' : ''}`} onClick={() => setTab('groups')}><Layers3 size={15} /> Role groups ({groups.length})</button>
      </div>

      {tab === 'users' && (
        <Card title="Users and their effective access" actions={<button className="btn btn-primary btn-sm" onClick={() => setUserModal({ username: '', password: '', full_name: '', email: '', employee_id: '', is_active: true, role_ids: [], group_ids: [] })}><Plus size={14} /> Add user</button>}>
          <DataTable rows={users} emptyText="No users" columns={[
            { label: 'User', render: (r) => <><span className="strong">{r.full_name || r.username}</span><span className="sub">@{r.username}</span></> },
            { label: 'Direct roles', render: (r) => r.roles.length ? r.roles.map((x) => <span className="chip" key={x.id}>{x.name}</span>) : '—' },
            { label: 'Role groups', render: (r) => r.groups.length ? r.groups.map((x) => <Badge key={x.id} status="purple">{x.name}</Badge>) : '—' },
            { label: 'Effective permissions', render: (r) => <span className="chip">{r.permissions.length} permissions</span> },
            { label: 'Status', render: (r) => <Badge status={r.is_active ? 'active' : 'inactive'} /> },
            { label: 'Actions', className: 'text-right', render: (r) => <div className="row-actions" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-outline btn-sm" onClick={() => setAssignModal({ ...r, role_ids: r.roles.map((x) => x.id), group_ids: r.groups.map((x) => x.id) })}><KeyRound size={13} /> Assign</button>
              <button className="btn btn-outline btn-sm" onClick={() => setUserModal({ ...r, password: '' })}>Edit</button>
            </div> },
          ]} />
        </Card>
      )}

      {tab === 'roles' && (
        <Card title="Roles" subtitle="A role is a bundle of permissions" actions={<button className="btn btn-primary btn-sm" onClick={() => setRoleModal({ name: '', description: '', permissions: [] })}><Plus size={14} /> Add role</button>}>
          <DataTable rows={roles} emptyText="No roles" columns={[
            { label: 'Role', render: (r) => <><span className="strong">{r.name}</span><span className="sub">{r.description}</span></> },
            { label: 'Permissions', render: (r) => <span className="chip">{r.permissions?.length || 0} permissions</span> },
            { label: 'Type', render: (r) => r.is_system ? <Badge status="blue">System</Badge> : <Badge status="gray">Custom</Badge> },
            { label: 'Actions', className: 'text-right', render: (r) => <button className="btn btn-outline btn-sm" onClick={() => setRoleModal({ ...r })}>Edit permissions</button> },
          ]} />
        </Card>
      )}

      {tab === 'groups' && (
        <Card title="Role groups" subtitle="Combine multiple roles; users inherit every permission from every role in the group">
          <div className="grid grid-3" style={{ marginBottom: 16 }}>
            {groups.map((g) => <div className="card" key={g.id} style={{ padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div><strong style={{ color: '#0f172a' }}>{g.name}</strong><div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>{g.description}</div></div>
                <button className="btn btn-outline btn-sm" onClick={() => setGroupModal({ ...g })}>Edit</button>
              </div>
              <div style={{ marginTop: 12 }}>{g.roles.map((r) => <Badge key={r.id} status="blue">{r.name}</Badge>)}</div>
            </div>)}
          </div>
          <button className="btn btn-primary" onClick={() => setGroupModal({ name: '', description: '', role_ids: [] })}><Plus size={15} /> Create role group</button>
        </Card>
      )}

      {/* Role modal */}
      <Modal open={!!roleModal} onClose={() => setRoleModal(null)} title={roleModal?.id ? `Edit role — ${roleModal.name}` : 'Create role'} width={760}
        footer={<><button className="btn btn-outline" onClick={() => setRoleModal(null)}>Cancel</button><button className="btn btn-primary" onClick={saveRole}>Save role</button></>}>
        {roleModal && <div className="form-grid">
          <Field label="Role name"><input value={roleModal.name} onChange={(e) => setRoleModal({ ...roleModal, name: e.target.value })} disabled={!!roleModal.id} /></Field>
          <Field label="Description"><input value={roleModal.description || ''} onChange={(e) => setRoleModal({ ...roleModal, description: e.target.value })} /></Field>
          <div className="full">
            <p style={{ fontWeight: 700, fontSize: 12, marginBottom: 10 }}>Permissions granted by this role</p>
            {Object.entries(groupedPermissions).map(([module, items]) => (
              <div key={module}>
                <div className="permission-module">{module}</div>
                <div className="check-grid">
                  {items.map((p) => <label className="check-item" key={p.code}>
                    <input type="checkbox" checked={(roleModal.permissions || []).includes(p.code)} onChange={() => toggleInList(roleModal, setRoleModal, 'permissions', p.code)} />
                    <span>{p.label}</span>
                  </label>)}
                </div>
              </div>
            ))}
          </div>
        </div>}
      </Modal>

      {/* Group modal */}
      <Modal open={!!groupModal} onClose={() => setGroupModal(null)} title={groupModal?.id ? `Edit group — ${groupModal.name}` : 'Create role group'} width={560}
        footer={<><button className="btn btn-outline" onClick={() => setGroupModal(null)}>Cancel</button><button className="btn btn-primary" onClick={saveGroup}>Save group</button></>}>
        {groupModal && <div className="form-grid">
          <Field label="Group name"><input value={groupModal.name} onChange={(e) => setGroupModal({ ...groupModal, name: e.target.value })} disabled={!!groupModal.id} /></Field>
          <Field label="Description"><input value={groupModal.description || ''} onChange={(e) => setGroupModal({ ...groupModal, description: e.target.value })} /></Field>
          <Field label="Combine roles" full hint="Select two or more roles to create a composite role group">
            <div className="check-grid">
              {roles.map((r) => <label className="check-item" key={r.id}>
                <input type="checkbox" checked={(groupModal.role_ids || []).includes(r.id)} onChange={() => toggleInList(groupModal, setGroupModal, 'role_ids', r.id)} />
                <span>{r.name}</span>
              </label>)}
            </div>
          </Field>
        </div>}
      </Modal>

      {/* User modal */}
      <Modal open={!!userModal} onClose={() => setUserModal(null)} title={userModal?.id ? `Edit user — ${userModal.username}` : 'Create user'} width={640}
        footer={<><button className="btn btn-outline" onClick={() => setUserModal(null)}>Cancel</button><button className="btn btn-primary" onClick={saveUser}>Save user</button></>}>
        {userModal && <div className="form-grid">
          <Field label="Username"><input value={userModal.username} onChange={(e) => setUserModal({ ...userModal, username: e.target.value })} disabled={!!userModal.id} /></Field>
          <Field label={userModal.id ? 'New password (leave blank to keep)' : 'Password'}><input type="password" value={userModal.password || ''} onChange={(e) => setUserModal({ ...userModal, password: e.target.value })} /></Field>
          <Field label="Full name"><input value={userModal.full_name || ''} onChange={(e) => setUserModal({ ...userModal, full_name: e.target.value })} /></Field>
          <Field label="Email"><input value={userModal.email || ''} onChange={(e) => setUserModal({ ...userModal, email: e.target.value })} /></Field>
          <Field label="Linked employee"><SearchableSelect value={userModal.employee_id || ''} onChange={(v) => setUserModal({ ...userModal, employee_id: v ? +v : null })} options={employees.map((e) => ({ value: e.id, label: `${e.employee_code} — ${e.full_name || `${e.first_name} ${e.last_name}`}` }))} placeholder="—" /></Field>
          <Field label="Status"><SearchableSelect value={userModal.is_active ? 'active' : 'inactive'} onChange={(v) => setUserModal({ ...userModal, is_active: v === 'active' })} options={ACTIVE_OPTIONS} clearable={false} /></Field>
          {!userModal.id && <>
            <Field label="Direct roles" full><div className="check-grid">{roles.map((r) => <label className="check-item" key={r.id}><input type="checkbox" checked={(userModal.role_ids || []).includes(r.id)} onChange={() => toggleInList(userModal, setUserModal, 'role_ids', r.id)} /><span>{r.name}</span></label>)}</div></Field>
            <Field label="Role groups" full><div className="check-grid">{groups.map((g) => <label className="check-item" key={g.id}><input type="checkbox" checked={(userModal.group_ids || []).includes(g.id)} onChange={() => toggleInList(userModal, setUserModal, 'group_ids', g.id)} /><span>{g.name}</span></label>)}</div></Field>
          </>}
        </div>}
      </Modal>

      {/* Assign modal */}
      <Modal open={!!assignModal} onClose={() => setAssignModal(null)} title={`Assign access — ${assignModal?.username}`} width={640}
        footer={<><button className="btn btn-outline" onClick={() => setAssignModal(null)}>Cancel</button><button className="btn btn-primary" onClick={assign}>Apply assignment</button></>}>
        {assignModal && <div className="form-grid">
          <Field label="Direct roles" full hint="Permissions from these roles are added directly"><div className="check-grid">{roles.map((r) => <label className="check-item" key={r.id}><input type="checkbox" checked={(assignModal.role_ids || []).includes(r.id)} onChange={() => toggleInList(assignModal, setAssignModal, 'role_ids', r.id)} /><span>{r.name}</span></label>)}</div></Field>
          <Field label="Role groups" full hint="Each group contributes all of its combined roles"><div className="check-grid">{groups.map((g) => <label className="check-item" key={g.id}><input type="checkbox" checked={(assignModal.group_ids || []).includes(g.id)} onChange={() => toggleInList(assignModal, setAssignModal, 'group_ids', g.id)} /><span>{g.name} ({g.roles.map((r) => r.name).join(' + ')})</span></label>)}</div></Field>
        </div>}
      </Modal>
    </>
  )
}
