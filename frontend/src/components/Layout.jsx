import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  BarChart3, BriefcaseBusiness, Building2, CalendarCheck2, CalendarRange, ChevronDown, ClipboardList,
  Coffee, FileBarChart, FileText, Fingerprint, LayoutDashboard, LogOut, MapPin, Menu, ShieldCheck, UserCircle2, Users, Wallet, X, KeyRound,
} from 'lucide-react'
import api, { errorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Modal, Field, Notice } from './ui'

const NAV = [
  { section: 'Overview', items: [
    { to: '/', label: 'Dashboard', icon: LayoutDashboard, perm: ['dashboard.view', 'self.portal'] },
  ] },
  { section: 'People & shifts', items: [
    { to: '/employees', label: 'Employees', icon: Users, perm: ['employee.view'] },
    { to: '/documents', label: 'Documents', icon: FileText, perm: ['document.view', 'self.portal'] },
    { to: '/departments', label: 'Departments', icon: Building2, perm: ['employee.view'] },
    { to: '/designations', label: 'Designations', icon: BriefcaseBusiness, perm: ['employee.view'] },
    { to: '/locations', label: 'Locations', icon: MapPin, perm: ['employee.view'] },
    { to: '/shifts', label: 'Shifts', icon: CalendarCheck2, perm: ['shift.view', 'employee.view'] },
    { to: '/shift-groups', label: 'Shift groups', icon: CalendarRange, perm: ['shift.view', 'employee.view'] },
    { to: '/lunch-break', label: 'Lunch break', icon: Coffee, perm: ['shift.view', 'employee.view'] },
    { to: '/leaves', label: 'Leave management', icon: ClipboardList, perm: ['leave.view'] },
  ] },
  { section: 'Attendance', items: [
    { to: '/attendance', label: 'Attendance', icon: Fingerprint, perm: ['attendance.view'] },
    { to: '/reports', label: 'Reports', icon: BarChart3, perm: ['report.view'] },
    { to: '/advanced-reports', label: 'Advanced reports', icon: FileBarChart, perm: ['report.view'] },
    { to: '/devices', label: 'Biometric devices', icon: Fingerprint, perm: ['device.view'] },
  ] },
  { section: 'Payroll & security', items: [
    { to: '/payroll', label: 'Payroll & slips', icon: Wallet, perm: ['payroll.view', 'payslip.view'] },
    { to: '/access', label: 'Roles & access', icon: ShieldCheck, perm: ['access.view'] },
  ] },
  { section: 'Self service', items: [
    { to: '/portal', label: 'My portal', icon: UserCircle2, perm: ['self.portal'] },
  ] },
]

const TITLES = {
  '/': ['Dashboard', 'Today at a glance'],
  '/employees': ['Employees', 'Manage employee master and device enrollment'],
  '/documents': ['Employee documents', 'HR documents and employee-uploaded PAN / Aadhaar KYC files'],
  '/departments': ['Departments', 'Maintain departments and their heads'],
  '/designations': ['Designations', 'Maintain job titles grouped by department'],
  '/locations': ['Locations', 'Workplaces and branches used by advanced reports'],
  '/shifts': ['Shifts', 'Working hours, grace time and weekly offs'],
  '/shift-groups': ['Shift groups', 'Shared rotations and employee mapping'],
  '/lunch-break': ['Lunch break', '1-hour lunch and four-punch sequence'],
  '/leaves': ['Leave management', 'Applications and approvals'],
  '/attendance': ['Attendance', 'Daily records and raw punch logs'],
  '/reports': ['Reports', 'Daily, weekly and monthly attendance analytics'],
  '/advanced-reports': ['Advanced reports', 'Time & attendance reporting engine'],
  '/devices': ['Biometric devices', 'Device connection and punch synchronization'],
  '/payroll': ['Payroll', 'Salary structures, processing and payslips'],
  '/access': ['Roles & access', 'Users, roles and combined role groups'],
  '/portal': ['My portal', 'Your attendance, leaves and salary slips'],
}

export default function Layout() {
  const { user, has, logout, setUser } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [pwOpen, setPwOpen] = useState(false)
  const [pw, setPw] = useState({ old_password: '', new_password: '' })
  const [pwError, setPwError] = useState('')
  const [pwDone, setPwDone] = useState('')

  const needsOnboarding = Boolean(
    user?.employee_id && (!user.profile_completed || user.must_change_password),
  )
  const emptyOnboarding = {
    first_name: '', last_name: '', email: '', phone: '', alternate_phone: '',
    date_of_birth: '', gender: '', emergency_contact_name: '',
    emergency_contact_phone: '', emergency_contact_relationship: '', address: '',
    old_password: '', new_password: '',
  }
  const [onboarding, setOnboarding] = useState(emptyOnboarding)
  const [onboardingError, setOnboardingError] = useState('')
  const [onboardingBusy, setOnboardingBusy] = useState(false)

  const [title, subtitle] = TITLES[location.pathname] || ['HRMS', '']

  useEffect(() => {
    if (!needsOnboarding) return
    api.get('/employees/me').then((r) => {
      const p = r.data
      setOnboarding({
        ...emptyOnboarding,
        first_name: p.first_name || '', last_name: p.last_name || '',
        email: p.email || '', phone: p.phone || '',
        alternate_phone: p.alternate_phone || '',
        date_of_birth: p.date_of_birth || '', gender: p.gender || '',
        emergency_contact_name: p.emergency_contact_name || '',
        emergency_contact_phone: p.emergency_contact_phone || '',
        emergency_contact_relationship: p.emergency_contact_relationship || '',
        address: p.address || '',
      })
    }).catch((e) => setOnboardingError(errorMessage(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsOnboarding])

  const completeOnboarding = async () => {
    setOnboardingError('')
    setOnboardingBusy(true)
    try {
      const r = await api.post('/auth/onboarding', onboarding)
      setUser(r.data.user)
    } catch (err) {
      setOnboardingError(errorMessage(err))
    } finally {
      setOnboardingBusy(false)
    }
  }

  const changePassword = async () => {
    setPwError('')
    setPwDone('')
    try {
      await api.post('/auth/change-password', pw)
      setPwDone('Password updated successfully')
      setPw({ old_password: '', new_password: '' })
    } catch (err) {
      setPwError(err.response?.data?.detail || 'Could not change password')
    }
  }

  return (
    <div className="app-shell">
      {sidebarOpen && <div className="modal-backdrop" style={{ zIndex: 25 }} onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-logo">
          <div className="logo-mark"><Fingerprint size={21} /></div>
          <div><strong>HRMS</strong><small>Attendance & Payroll</small></div>
          <button className="close-x" style={{ marginLeft: 'auto', color: '#fff' }} onClick={() => setSidebarOpen(false)}><X size={16} /></button>
        </div>
        {NAV.map((group) => {
          const items = group.items.filter((item) => has(...item.perm))
          if (!items.length) return null
          return (
            <div className="nav-section" key={group.section}>
              <div className="nav-section-title">{group.section}</div>
              {items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                  onClick={() => setSidebarOpen(false)}
                >
                  <span className="nav-icon"><item.icon size={17} /></span>
                  {item.label}
                </NavLink>
              ))}
            </div>
          )
        })}
        <div className="sidebar-footer">HRMS v1.0 · Biometric enabled</div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button className="btn btn-outline btn-icon mobile-toggle" onClick={() => setSidebarOpen(true)}><Menu size={18} /></button>
            <div>
              <div className="topbar-title">{title}</div>
              <div className="topbar-sub">{subtitle}</div>
            </div>
          </div>
          <div className="user-chip" style={{ position: 'relative' }}>
            <div className="avatar">{(user?.full_name || user?.username || 'U').slice(0, 2).toUpperCase()}</div>
            <div className="user-meta">
              <strong>{user?.full_name || user?.username}</strong>
              <small>{user?.roles?.map((r) => r.name).join(', ') || 'User'}</small>
            </div>
            <button className="btn btn-outline btn-icon btn-sm" onClick={() => setMenuOpen(!menuOpen)}><ChevronDown size={15} /></button>
            {menuOpen && (
              <div className="card" style={{ position: 'absolute', right: 0, top: 48, width: 210, zIndex: 40, padding: 6 }}>
                <button className="nav-item" style={{ color: 'var(--slate-700)', width: '100%' }} onClick={() => { navigate('/portal'); setMenuOpen(false) }}>
                  <UserCircle2 size={16} /> My portal
                </button>
                <button className="nav-item" style={{ color: 'var(--slate-700)', width: '100%' }} onClick={() => { setPwOpen(true); setMenuOpen(false) }}>
                  <KeyRound size={16} /> Change password
                </button>
                <button className="nav-item" style={{ color: 'var(--red)', width: '100%' }} onClick={logout}>
                  <LogOut size={16} /> Logout
                </button>
              </div>
            )}
          </div>
        </header>
        <main className="content"><Outlet /></main>
      </div>

      <Modal
        open={pwOpen}
        onClose={() => setPwOpen(false)}
        title="Change password"
        footer={<><button className="btn btn-outline" onClick={() => setPwOpen(false)}>Cancel</button><button className="btn btn-primary" onClick={changePassword}>Update password</button></>}
      >
        <Notice type="error">{pwError}</Notice>
        <Notice type="success">{pwDone}</Notice>
        <div className="form-grid">
          <Field label="Current password" full><input type="password" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} /></Field>
          <Field label="New password" full><input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} hint="Minimum 6 characters" /></Field>
        </div>
      </Modal>

      <Modal
        open={needsOnboarding}
        dismissible={false}
        title="Complete your profile"
        width={760}
        footer={
          <button className="btn btn-primary" disabled={onboardingBusy} onClick={completeOnboarding}>
            {onboardingBusy ? 'Saving…' : 'Save and continue'}
          </button>
        }
      >
        <Notice type="info">
          Please confirm your personal details and set a new password before continuing.
          Your username <strong>{user?.username}</strong> cannot be changed.
        </Notice>
        <Notice type="error">{onboardingError}</Notice>
        <div className="form-grid">
          <Field label="Username" hint="Fixed — cannot be changed"><input value={user?.username || ''} disabled /></Field>
          <Field label="Gender"><input value={onboarding.gender} onChange={(e) => setOnboarding({ ...onboarding, gender: e.target.value })} /></Field>
          <Field label="First name"><input value={onboarding.first_name} onChange={(e) => setOnboarding({ ...onboarding, first_name: e.target.value })} /></Field>
          <Field label="Last name"><input value={onboarding.last_name} onChange={(e) => setOnboarding({ ...onboarding, last_name: e.target.value })} /></Field>
          <Field label="Date of birth"><input type="date" value={onboarding.date_of_birth} onChange={(e) => setOnboarding({ ...onboarding, date_of_birth: e.target.value })} /></Field>
          <Field label="Email"><input type="email" value={onboarding.email} onChange={(e) => setOnboarding({ ...onboarding, email: e.target.value })} /></Field>
          <Field label="Phone"><input value={onboarding.phone} onChange={(e) => setOnboarding({ ...onboarding, phone: e.target.value })} /></Field>
          <Field label="Alternate phone"><input value={onboarding.alternate_phone} onChange={(e) => setOnboarding({ ...onboarding, alternate_phone: e.target.value })} /></Field>
          <Field label="Emergency contact name"><input value={onboarding.emergency_contact_name} onChange={(e) => setOnboarding({ ...onboarding, emergency_contact_name: e.target.value })} /></Field>
          <Field label="Emergency contact phone"><input value={onboarding.emergency_contact_phone} onChange={(e) => setOnboarding({ ...onboarding, emergency_contact_phone: e.target.value })} /></Field>
          <Field label="Relationship"><input value={onboarding.emergency_contact_relationship} onChange={(e) => setOnboarding({ ...onboarding, emergency_contact_relationship: e.target.value })} /></Field>
          <Field label="Address" full><input value={onboarding.address} onChange={(e) => setOnboarding({ ...onboarding, address: e.target.value })} /></Field>
          <Field label="Current password"><input type="password" value={onboarding.old_password} onChange={(e) => setOnboarding({ ...onboarding, old_password: e.target.value })} /></Field>
          <Field label="New password" hint="Minimum 6 characters"><input type="password" value={onboarding.new_password} onChange={(e) => setOnboarding({ ...onboarding, new_password: e.target.value })} /></Field>
        </div>
      </Modal>
    </div>
  )
}
