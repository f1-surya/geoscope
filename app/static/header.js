const SUN_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

(function setupTheme() {
  const root = document.documentElement;

  function currentTheme() {
    return root.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function updateButton(theme) {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    const dark = theme === 'dark';
    button.innerHTML = dark ? SUN_ICON : MOON_ICON;
    const label = dark ? 'Switch to light theme' : 'Switch to dark theme';
    button.setAttribute('aria-label', label);
    button.title = label;
  }

  function apply(theme) {
    root.setAttribute('data-theme', theme);
    try { localStorage.setItem('geoscope-theme', theme); } catch (_) {}
    updateButton(theme);
  }

  const actions = document.querySelector('.header-actions');
  if (actions) {
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'theme-toggle';
    button.className = 'theme-toggle';
    button.addEventListener('click', () => apply(currentTheme() === 'dark' ? 'light' : 'dark'));
    actions.appendChild(button);
  }

  updateButton(currentTheme());
})();

const quitLink = document.getElementById('quit');

if (quitLink) {
  quitLink.addEventListener('click', async event => {
    event.preventDefault();
    const status = document.getElementById('quit-status');
    if (!window.confirm('Stop GEOscope? The local server will shut down.')) return;
    if (status) status.textContent = 'Shutting down...';
    try {
      const response = await fetch('/api/shutdown', {method: 'POST'});
      let data = {};
      try { data = await response.json(); } catch (_) {}
      if (!response.ok) throw new Error(data.detail || 'Request failed');
      document.body.innerHTML = '<main><h1>GEOscope has stopped.</h1><p>You can close this tab.</p></main>';
    } catch (error) {
      if (status) status.textContent = error.message;
    }
  });
}
