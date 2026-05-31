import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  exchangeOAuthCode,
  getCurrentUser,
  isAuthenticated,
  login,
  loginWithGithub,
  loginWithGoogle,
  register,
} from '../../services/api';
import './Login.css';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const redirectTarget = useMemo(
    () => location.state?.from?.pathname || '/research',
    [location.state]
  );

  useEffect(() => {
    if (isAuthenticated()) {
      getCurrentUser()
        .then(() => navigate(redirectTarget, { replace: true }))
        .catch(() => {});
    }
  }, [navigate, redirectTarget]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const code = params.get('code');
    const provider = params.get('provider');
    if (!code || !provider) return;

    const redirectUri = `${window.location.origin}/login?provider=${provider}`;

    setLoading(true);
    exchangeOAuthCode(provider, code, redirectUri)
      .then(() => navigate('/research', { replace: true }))
      .catch((err) => setError(err.message || 'OAuth sign-in failed'))
      .finally(() => setLoading(false));
  }, [location.search, navigate]);

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (mode === 'register') {
        await register(email, password, fullName);
      } else {
        await login(email, password);
      }
      navigate(redirectTarget, { replace: true });
    } catch (err) {
      setError(err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogle() {
    setError('');
    setLoading(true);
    try {
      await loginWithGoogle(`${window.location.origin}/login?provider=google`);
    } catch (err) {
      setError(err.message || 'Google login failed');
      setLoading(false);
    }
  }

  async function handleGithub() {
    setError('');
    setLoading(true);
    try {
      await loginWithGithub(`${window.location.origin}/login?provider=github`);
    } catch (err) {
      setError(err.message || 'GitHub login failed');
      setLoading(false);
    }
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="login-brand">CortexAI</div>
        <h1 className="login-title">
          {mode === 'login' ? 'Sign In' : 'Create Account'}
        </h1>
        <p className="login-subtitle">
          Access protected research sessions, persistent checkpoints, and secure workspace state.
        </p>

        <form className="login-form" onSubmit={handleSubmit}>
          {mode === 'register' && (
            <input
              className="input"
              type="text"
              placeholder="Full name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          )}

          <input
            className="input"
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <input
            className="input"
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />

          {error && <div className="login-error">{error}</div>}

          <button className="btn btn-primary login-submit" type="submit" disabled={loading}>
            {loading ? 'Please wait...' : mode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
        </form>

        <div className="login-divider"><span>or continue with</span></div>

        <div className="login-socials">
          <button className="btn btn-secondary login-social" onClick={handleGoogle} disabled={loading}>
            Google
          </button>
          <button className="btn btn-secondary login-social" onClick={handleGithub} disabled={loading}>
            GitHub
          </button>
        </div>

        <button
          className="btn btn-ghost login-switch"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          disabled={loading}
        >
          {mode === 'login' ? 'Need an account? Register' : 'Already have an account? Sign in'}
        </button>
      </div>
    </div>
  );
}
