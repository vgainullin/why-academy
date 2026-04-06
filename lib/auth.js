// Why Academy — Google Identity Services auth module
// Public client ID is safe to embed (not a secret).
// We request only openid/email/profile scopes — no Sheets/Drive access.

(function () {
  'use strict';

  const CLIENT_ID = '685261821443-5gm88a2lkv98h3e24cpkged1np18fjhu.apps.googleusercontent.com';
  const SCOPES = 'openid email profile';

  // In-memory state — never persisted
  let idToken = null;
  let user = null; // { email, name, sub }
  let tokenClient = null;
  let isAllowlisted = false;
  let authReadyCallbacks = [];

  // Worker URL — feedback ingestion endpoint.
  // Falls back to null = client-only mode for offline dev.
  const WORKER_URL = 'https://why-academy-feedback.gainullin.workers.dev';

  // ── Public API ──
  window.WhyAuth = {
    init: init,
    signIn: signIn,
    signOut: signOut,
    getUser: () => user,
    getIdToken: () => idToken,
    isAuthenticated: () => !!user,
    isAllowlisted: () => isAllowlisted,
    onReady: cb => {
      if (window.google && window.google.accounts) cb();
      else authReadyCallbacks.push(cb);
    }
  };

  // ── Init ──
  function init() {
    waitForGIS().then(() => {
      // Use ID token (credential) flow — Sign In With Google button
      // We don't need access tokens since we're not calling Google APIs.
      // The ID token is what we'll send to our worker for verification.
      google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: onCredentialResponse,
        auto_select: false,
        cancel_on_tap_outside: true
      });

      // Wire the manual sign-in button
      const signinBtn = document.getElementById('signin-btn');
      const signoutBtn = document.getElementById('signout-btn');

      signinBtn.classList.remove('hidden');
      signinBtn.addEventListener('click', signIn);
      signoutBtn.addEventListener('click', signOut);

      authReadyCallbacks.forEach(cb => cb());
      authReadyCallbacks = [];
    });
  }

  function waitForGIS() {
    return new Promise(resolve => {
      const check = () => {
        if (window.google && window.google.accounts && window.google.accounts.id) {
          resolve();
        } else {
          setTimeout(check, 100);
        }
      };
      check();
    });
  }

  function signIn() {
    // Show the One Tap / sign-in prompt
    google.accounts.id.prompt((notification) => {
      if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
        // Fallback: render the explicit Sign In With Google button.
        // For now, just log — students can click again.
        console.log('Sign-in prompt not shown:', notification.getNotDisplayedReason() || notification.getSkippedReason());
      }
    });
  }

  function signOut() {
    idToken = null;
    user = null;
    isAllowlisted = false;
    google.accounts.id.disableAutoSelect();
    updateUI();
    notifyAuthChange();
  }

  // ── ID token callback ──
  function onCredentialResponse(response) {
    if (!response.credential) {
      console.error('No credential in response');
      return;
    }
    idToken = response.credential;
    user = decodeJwtPayload(idToken);
    updateUI();

    // If a worker is configured, ask it whether this user is allowlisted.
    // Otherwise, fall back to a client-side check (for local dev only).
    checkAllowlist().then(() => {
      notifyAuthChange();
    });
  }

  // ── Allowlist check ──
  // In production this is enforced by the worker (which is the source of
  // truth). The client-side check is purely for UX — to hide/show the
  // feedback toolbar. Anyone can bypass this check, but the worker won't
  // accept their feedback.
  async function checkAllowlist() {
    if (!user) return;
    if (WORKER_URL) {
      try {
        const resp = await fetch(WORKER_URL + '/check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ idToken: idToken })
        });
        if (resp.ok) {
          const data = await resp.json();
          isAllowlisted = !!data.allowed;
          return;
        }
      } catch (e) {
        console.warn('Allowlist check failed, falling back to UI-only mode:', e);
      }
    }
    // Client-side fallback (UI hint only — never trust this for security)
    const localAllowlist = ['gainullin@gmail.com'];
    isAllowlisted = localAllowlist.includes(user.email);
  }

  // ── UI ──
  function updateUI() {
    const signinBtn = document.getElementById('signin-btn');
    const userInfo = document.getElementById('user-info');
    const userEmail = document.getElementById('user-email');

    if (user) {
      signinBtn.classList.add('hidden');
      userInfo.classList.remove('hidden');
      userEmail.textContent = user.email;
    } else {
      signinBtn.classList.remove('hidden');
      userInfo.classList.add('hidden');
    }
  }

  function notifyAuthChange() {
    document.dispatchEvent(new CustomEvent('whyauth:change', {
      detail: { user: user, isAllowlisted: isAllowlisted }
    }));
  }

  // ── Helpers ──
  function decodeJwtPayload(token) {
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return null;
      const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
      return {
        email: payload.email,
        name: payload.name,
        sub: payload.sub,
        emailVerified: payload.email_verified
      };
    } catch (e) {
      console.error('Failed to decode JWT:', e);
      return null;
    }
  }
})();
