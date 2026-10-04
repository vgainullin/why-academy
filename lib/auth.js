// Why Academy — accounts (passkeys)
//
// Accounts are passkeys: the browser's WebAuthn API creates and uses a key
// pair held by the device or password manager; the Worker verifies it and
// issues an HttpOnly session cookie (see worker/passkeys.js). No third-party
// identity provider and no external script, so pages stay bfcache-friendly.
// On load we ask /api/me whether a session exists.

(function () {
  'use strict';

  let user = null; // { id, displayName }
  let isAllowlisted = false;
  let authReadyCallbacks = [];
  let ready = false;

  window.WhyAuth = {
    init: init,
    signIn: signIn,
    signUp: signUp,
    addPasskey: addPasskey,
    signOut: signOut,
    getUser: () => user,
    isAuthenticated: () => !!user,
    isAllowlisted: () => isAllowlisted,
    onReady: cb => {
      if (ready) cb();
      else authReadyCallbacks.push(cb);
    }
  };

  // ── Init ──
  async function init() {
    const signinBtn = document.getElementById('signin-btn');
    if (!signinBtn) return;
    signinBtn.addEventListener('click', signIn);
    document.getElementById('signup-btn').addEventListener('click', signUp);
    document.getElementById('add-passkey-btn').addEventListener('click', addPasskey);
    document.getElementById('signout-btn').addEventListener('click', signOut);

    const accountsAvailable = window.PublicKeyCredential && await restoreSession();
    if (accountsAvailable) updateUI();

    ready = true;
    authReadyCallbacks.forEach(cb => cb());
    authReadyCallbacks = [];
    if (user) notifyAuthChange();
  }

  // Returns false when the API is unreachable (e.g. a plain static server).
  async function restoreSession() {
    let resp;
    try {
      resp = await fetch('/api/me', { credentials: 'same-origin' });
    } catch (e) {
      console.warn('Accounts unavailable:', e);
      return false;
    }
    if (resp.status === 404) {
      console.info('Accounts unavailable: no /api on this host');
      return false;
    }
    if (resp.ok) setUser(await resp.json());
    else if (resp.status !== 401) console.error('/api/me returned', resp.status);
    return true;
  }

  // ── Ceremonies ──

  async function signUp() {
    const name = window.prompt('Name for your account (shown in your passkey manager):', '');
    if (name === null) return;
    await runCeremony('signup-btn', async () => {
      const options = await postJson('/api/auth/register/options', { displayName: name });
      const credential = await createCredential(options);
      signedIn(await postJson('/api/auth/register/verify', { credential: credential }));
    });
  }

  async function signIn() {
    await runCeremony('signin-btn', async () => {
      const options = await postJson('/api/auth/login/options', {});
      const credential = await getCredential(options);
      signedIn(await postJson('/api/auth/login/verify', { credential: credential }));
    });
  }

  // Register another device's passkey on the current account.
  async function addPasskey() {
    await runCeremony('add-passkey-btn', async () => {
      const options = await postJson('/api/passkeys/options', {});
      const credential = await createCredential(options);
      await postJson('/api/passkeys/verify', { credential: credential });
      flash('add-passkey-btn', 'Passkey added');
    });
  }

  async function signOut() {
    try {
      const resp = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
      if (!resp.ok) console.error('Logout returned', resp.status);
    } catch (e) {
      console.error('Logout request failed:', e);
    }
    if (window.WhySync) WhySync.stop();
    setUser(null);
    updateUI();
    notifyAuthChange();
  }

  function signedIn(data) {
    setUser(data);
    updateUI();
    notifyAuthChange();
    if (window.WhySync) WhySync.start();
  }

  // Runs a WebAuthn ceremony, reporting failures on the triggering button.
  // A user cancelling the browser prompt (NotAllowedError) is not an error.
  async function runCeremony(buttonId, fn) {
    try {
      await fn();
    } catch (e) {
      if (e && e.name === 'NotAllowedError') {
        console.info('Passkey prompt dismissed:', e.message);
        return;
      }
      console.error(e);
      flash(buttonId, e && e.userMessage ? e.userMessage : 'Failed');
    }
  }

  async function postJson(url, body) {
    const resp = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(url + ' returned ' + resp.status + ': ' + (data.error || ''));
      err.userMessage = data.error || 'Failed';
      throw err;
    }
    return data;
  }

  // ── WebAuthn JSON <-> ArrayBuffer ──

  function b64urlToBuffer(s) {
    let b64 = s.replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4) b64 += '=';
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }

  function bufferToB64url(buf) {
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function descriptors(list) {
    return (list || []).map(d => Object.assign({}, d, { id: b64urlToBuffer(d.id) }));
  }

  async function createCredential(options) {
    const cred = await navigator.credentials.create({
      publicKey: Object.assign({}, options, {
        challenge: b64urlToBuffer(options.challenge),
        user: Object.assign({}, options.user, { id: b64urlToBuffer(options.user.id) }),
        excludeCredentials: descriptors(options.excludeCredentials)
      })
    });
    return {
      id: cred.id,
      rawId: bufferToB64url(cred.rawId),
      type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment || undefined,
      clientExtensionResults: cred.getClientExtensionResults(),
      response: {
        clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
        attestationObject: bufferToB64url(cred.response.attestationObject),
        transports: cred.response.getTransports ? cred.response.getTransports() : []
      }
    };
  }

  async function getCredential(options) {
    const cred = await navigator.credentials.get({
      publicKey: Object.assign({}, options, {
        challenge: b64urlToBuffer(options.challenge),
        allowCredentials: descriptors(options.allowCredentials)
      })
    });
    return {
      id: cred.id,
      rawId: bufferToB64url(cred.rawId),
      type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment || undefined,
      clientExtensionResults: cred.getClientExtensionResults(),
      response: {
        clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
        authenticatorData: bufferToB64url(cred.response.authenticatorData),
        signature: bufferToB64url(cred.response.signature),
        userHandle: cred.response.userHandle ? bufferToB64url(cred.response.userHandle) : undefined
      }
    };
  }

  // ── State / UI ──

  function setUser(data) {
    user = data ? data.user : null;
    isAllowlisted = !!(data && data.isAllowlisted);
  }

  function updateUI() {
    const signedOut = ['signin-btn', 'signup-btn'].map(id => document.getElementById(id));
    const userInfo = document.getElementById('user-info');

    if (user) {
      signedOut.forEach(el => el.classList.add('hidden'));
      userInfo.classList.remove('hidden');
      const nameEl = document.getElementById('user-name');
      nameEl.textContent = user.displayName;
      nameEl.title = 'Account id: ' + user.id;
    } else {
      signedOut.forEach(el => el.classList.remove('hidden'));
      userInfo.classList.add('hidden');
    }
  }

  function flash(buttonId, message) {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    const original = btn.dataset.label || btn.textContent;
    btn.dataset.label = original;
    btn.textContent = message;
    setTimeout(() => { btn.textContent = original; }, 3000);
  }

  function notifyAuthChange() {
    document.dispatchEvent(new CustomEvent('whyauth:change', {
      detail: { user: user, isAllowlisted: isAllowlisted }
    }));
  }
})();
