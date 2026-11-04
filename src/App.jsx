import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate } from 'react-router-dom';
import Login from './pages/Login.jsx';
import Register from './pages/Register.jsx';
import Editor from './pages/Editor.jsx';
import Outfits from './pages/Outfits.jsx';
import Calibrate from './pages/Calibrate.jsx';
import { getToken, getCurrentUser, logout } from './api/client.js';

function Navbar() {
  const navigate = useNavigate();
  const user = getCurrentUser();

  function handleLogout() {
    logout();
    navigate('/');
  }

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand" style={{ textDecoration: 'none' }}>TryOn Studio</Link>
      <div className="navbar-links">
        <Link to="/" style={{ fontSize: '0.875rem', color: 'var(--muted)', fontWeight: 500 }}>Editor</Link>
        <Link to="/outfits" style={{ fontSize: '0.875rem', color: 'var(--muted)', fontWeight: 500, marginLeft: 4 }}>Outfits</Link>
        <Link to="/calibrate" style={{ fontSize: '0.75rem', color: 'var(--border)', fontWeight: 500, marginLeft: 4 }}>calibrate</Link>
        {user ? (
          <button className="btn btn-secondary" style={{ padding: '6px 16px', fontSize: '0.8rem', marginLeft: 8 }} onClick={handleLogout}>Log out</button>
        ) : (
          <Link to="/login" className="btn btn-secondary" style={{ padding: '6px 16px', fontSize: '0.8rem', marginLeft: 8, textDecoration: 'none' }}>Log in</Link>
        )}
      </div>
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Navbar />
      <Routes>
        <Route path="/" element={<Editor />} />
        <Route path="/editor" element={<Navigate to="/" replace />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/outfits" element={<Outfits />} />
        <Route path="/calibrate" element={<Calibrate />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
