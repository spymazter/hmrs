import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Employees from './pages/Employees'
import EmployeeDocuments from './pages/EmployeeDocuments'
import Circulars from './pages/Circulars'
import NoticeBoard from './pages/NoticeBoard'
import MasterData from './pages/MasterData'
import Shifts from './pages/Shifts'
import ShiftGroups from './pages/ShiftGroups'
import LunchBreak from './pages/LunchBreak'
import Devices from './pages/Devices'
import Attendance from './pages/Attendance'
import AdvancedReports from './pages/AdvancedReports'
import Reports from './pages/Reports'
import Payroll from './pages/Payroll'
import Leaves from './pages/Leaves'
import AccessControl from './pages/AccessControl'
import MyPortal from './pages/MyPortal'

function Protected() {
  const { user, loading } = useAuth()
  if (loading) return <div className="loader" style={{ marginTop: 100 }}>Loading application…</div>
  return user ? <Outlet /> : <Navigate to="/login" replace />
}

function Guard({ perm, children }) {
  const { has } = useAuth()
  return has(...perm) ? children : <Navigate to="/" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Protected />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/employees" element={<Guard perm={['employee.view']}><Employees /></Guard>} />
            <Route path="/documents" element={<Guard perm={['document.view', 'self.portal']}><EmployeeDocuments /></Guard>} />
            <Route path="/circulars" element={<Guard perm={['circular.manage']}><Circulars /></Guard>} />
            <Route path="/notice-board" element={<Guard perm={['self.portal', 'dashboard.view']}><NoticeBoard /></Guard>} />
            <Route path="/departments" element={<Guard perm={['employee.view']}><MasterData type="departments" /></Guard>} />
            <Route path="/designations" element={<Guard perm={['employee.view']}><MasterData type="designations" /></Guard>} />
            <Route path="/locations" element={<Guard perm={['employee.view']}><MasterData type="locations" /></Guard>} />
            <Route path="/shifts" element={<Guard perm={['shift.view', 'employee.view']}><Shifts /></Guard>} />
            <Route path="/shift-groups" element={<Guard perm={['shift.view', 'employee.view']}><ShiftGroups /></Guard>} />
            <Route path="/lunch-break" element={<Guard perm={['shift.view', 'employee.view']}><LunchBreak /></Guard>} />
            <Route path="/leaves" element={<Guard perm={['leave.view']}><Leaves /></Guard>} />
            <Route path="/attendance" element={<Guard perm={['attendance.view']}><Attendance /></Guard>} />
            <Route path="/reports" element={<Guard perm={['report.view']}><Reports /></Guard>} />
            <Route path="/advanced-reports" element={<Guard perm={['report.view']}><AdvancedReports /></Guard>} />
            <Route path="/devices" element={<Guard perm={['device.view']}><Devices /></Guard>} />
            <Route path="/payroll" element={<Guard perm={['payroll.view', 'payslip.view']}><Payroll /></Guard>} />
            <Route path="/access" element={<Guard perm={['access.view']}><AccessControl /></Guard>} />
            <Route path="/portal" element={<MyPortal />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
