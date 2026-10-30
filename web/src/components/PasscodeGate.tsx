import { useState, useCallback, useEffect, type ReactNode, type FormEvent } from 'react';
import {
  setPasscode,
  clearPasscode,
  getRequests,
  getHealth,
  getMe,
  login,
  setSessionToken,
  clearSessionToken,
  getSessionToken,
  ApiError,
} from '../api';

interface Props {
  children: ReactNode;
  /** Roles that may open this screen. Default: operator. */
  roles?: string[];
}

type Mode = 'loading' | 'passcode' | 'accounts';

/**
 * Sign-in gate for Desk, Intake and Officer.
 *
 * - Development (health.auth = "passcode"): the demo screens open straight away
 *   with the shared demo passcode, and ask again only if the server says 401.
 * - Production (health.auth = "accounts"): a username and password form. The
 *   signed session token is kept in sessionStorage and sent as a Bearer header.
 *   A signed-in account without the right role sees a plain message, not data.
 */
export default function PasscodeGate({ children, roles = ['operator'] }: Props) {
  const [mode, setMode] = useState<Mode>('loading');
  const [authed, setAuthed] = useState(false);
  const [userRoles, setUserRoles] = useState<string[]>([]);
  const [username, setUsername] = useState('');
  const [input, setInput] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let auth: 'passcode' | 'accounts' = 'passcode';
      try {
        const h = await getHealth();
        auth = h.auth === 'accounts' ? 'accounts' : 'passcode';
      } catch {
        auth = getSessionToken() ? 'accounts' : 'passcode';
      }
      if (cancelled) return;
      if (auth === 'passcode') {
        // Default to authenticated using demo credentials without prompting
        setMode('passcode');
        setUserRoles(['operator', 'officer']);
        setAuthed(true);
        return;
      }
      setMode('accounts');
      if (getSessionToken()) {
        try {
          const me = await getMe();
          if (cancelled) return;
          setUserRoles(me.roles);
          setUsername(me.username ?? '');
          setAuthed(true);
        } catch {
          clearSessionToken();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handlePasscodeSubmit = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    setChecking(true);
    setError('');
    setPasscode(input.trim());
    try {
      // Verify passcode using getRequests
      await getRequests({ status: 'open' });
      setAuthed(true);
    } catch (err) {
      clearPasscode();
      if (err instanceof ApiError && err.status === 401) {
        setError('Wrong passcode. Please try again.');
      } else if (err instanceof ApiError && err.error_code === 'NETWORK_DOWN') {
        setError('Cannot reach the server. Check your connection.');
      } else {
        setError('Verification failed. Please try again.');
      }
    }
    setChecking(false);
  }, [input]);

  const handleLoginSubmit = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setChecking(true);
    setError('');
    try {
      const res = await login(username.trim(), password);
      setSessionToken(res.token);
      setUserRoles([res.user.role]);
      setUsername(res.user.username);
      setPassword('');
      setAuthed(true);
      window.dispatchEvent(new Event('vaari-auth-changed'));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Wrong username or password.');
      } else if (err instanceof ApiError && err.status === 429) {
        setError('Too many attempts. Wait a few minutes and try again.');
      } else if (err instanceof ApiError && err.error_code === 'NETWORK_DOWN') {
        setError('Cannot reach the server. Check your connection.');
      } else {
        setError('Sign-in failed. Please try again.');
      }
    }
    setChecking(false);
  }, [username, password]);

  // Children catch ApiError with UNAUTHORIZED and call triggerReauth(), which lands here.
  const handleUnauthorized = useCallback(() => {
    clearPasscode();
    clearSessionToken();
    setAuthed(false);
    setInput('');
    setPassword('');
    setError(
      mode === 'accounts'
        ? 'Your session has ended. Please sign in again.'
        : 'Session expired. Please enter the passcode again.',
    );
  }, [mode]);

  // Make handler available globally for api error handling
  if (typeof window !== 'undefined') {
    (window as unknown as Record<string, unknown>).__vaariOnUnauthorized = handleUnauthorized;
  }

  if (mode === 'loading') {
    return <div className="passcode-gate" id="auth-loading" />;
  }

  if (authed) {
    if (!roles.some(r => userRoles.includes(r))) {
      return (
        <div className="passcode-gate">
          <div className="passcode-card" id="role-denied">
            <h1>Vaari</h1>
            <p>
              Your account ({userRoles.join(', ') || 'no role'}) cannot open this screen. It needs:{' '}
              {roles.join(' or ')}.
            </p>
          </div>
        </div>
      );
    }
    return <>{children}</>;
  }

  if (mode === 'accounts') {
    return (
      <div className="passcode-gate">
        <div className="passcode-card">
          <h1>Vaari</h1>
          <p>Sign in with your staff account.</p>
          <form onSubmit={handleLoginSubmit}>
            <input
              id="login-username"
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="Username"
              autoFocus
              autoComplete="username"
            />
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Password"
              autoComplete="current-password"
            />
            <button id="login-submit" type="submit" disabled={checking || !username.trim() || !password}>
              {checking ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          {error && <p className="passcode-error" id="login-error">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="passcode-gate">
      <div className="passcode-card">
        <h1>Vaari</h1>
        <p>Enter the operator passcode to continue.</p>
        <form onSubmit={handlePasscodeSubmit}>
          <input
            id="passcode-input"
            type="password"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Passcode"
            autoFocus
            autoComplete="off"
          />
          <button id="passcode-submit" type="submit" disabled={checking || !input.trim()}>
            {checking ? 'Checking…' : 'Enter'}
          </button>
        </form>
        {error && <p className="passcode-error">{error}</p>}
      </div>
    </div>
  );
}

/**
 * Call this from any component when an ApiError with UNAUTHORIZED is caught.
 */
export function triggerReauth(err: unknown): void {
  if (err instanceof ApiError && err.error_code === 'UNAUTHORIZED') {
    const fn = (window as unknown as Record<string, unknown>).__vaariOnUnauthorized;
    if (typeof fn === 'function') fn();
  }
}
