import { useEffect, useState } from 'react';
import { getSessionToken, logout } from '../api';

/** Shown in the navbar only when a staff account is signed in (production mode). */
export default function SignOutButton() {
  const [signedIn, setSignedIn] = useState(!!getSessionToken());

  useEffect(() => {
    const update = () => setSignedIn(!!getSessionToken());
    window.addEventListener('vaari-auth-changed', update);
    return () => window.removeEventListener('vaari-auth-changed', update);
  }, []);

  if (!signedIn) return null;
  return (
    <button
      id="btn-sign-out"
      className="nav-link"
      type="button"
      onClick={async () => {
        await logout().catch(() => undefined);
        window.dispatchEvent(new Event('vaari-auth-changed'));
        window.location.reload();
      }}
    >
      Sign out
    </button>
  );
}
