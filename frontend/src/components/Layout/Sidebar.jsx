import { NavLink, useNavigate } from 'react-router-dom';
import { clearAuthTokens } from '../../services/api';
import './Sidebar.css';

const NAV_GROUPS = [
  {
    label: null, // no label — primary action
    items: [
      { path: '/', icon: '◆', label: 'Home' },
      { path: '/research', icon: '🔬', label: 'New Research' },
    ],
  },
  {
    label: 'Library',
    items: [
      { path: '/history', icon: '🕐', label: 'History' },
      { path: '/workspace', icon: '📁', label: 'Workspace' },
      { path: '/tasks', icon: '📋', label: 'Tasks' },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { path: '/knowledge', icon: '🧠', label: 'Knowledge Graph' },
      { path: '/experiments', icon: '🧪', label: 'Experiments' },
      { path: '/observability', icon: '📡', label: 'Observability' },
      { path: '/workflow', icon: '⚡', label: 'Workflow Builder' },
      { path: '/webcompare', icon: '🔗', label: 'Web Compare' },
    ],
  },
  {
    label: null,
    items: [
      { path: '/settings', icon: '⚙', label: 'Settings' },
    ],
  },
];

export default function Sidebar() {
  const navigate = useNavigate();

  function handleLogout() {
    clearAuthTokens();
    navigate('/login', { replace: true });
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-icon">◈</div>
        <div>
          <div className="brand-name">CortexAI</div>
          <div className="brand-label">Deep Research</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi} className="nav-group">
            {group.label && <div className="nav-group-label">{group.label}</div>}
            {group.items.map(item => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              >
                <span className="nav-icon">{item.icon}</span>
                <span className="nav-label">{item.label}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-status">
          <span className="status-dot"></span>
          <span>System Online</span>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={handleLogout}>
          Sign Out
        </button>
        <div className="sidebar-version">v2.1</div>
      </div>
    </aside>
  );
}
