(() => {
  const select = document.getElementById('theme');
  const control = document.querySelector('.theme-control');
  let choice = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  function apply() {
    document.documentElement.dataset.theme = choice;
    select.value = choice;
    const dark = choice === 'dark';
    document.querySelectorAll('meta[name="theme-color"]').forEach(meta => {
      meta.content = dark ? '#1e1e2e' : '#eff1f5';
    });
  }
  select.addEventListener('change', () => {
    choice = select.value === 'dark' ? 'dark' : 'light';
    try { localStorage.setItem('theme', choice); } catch {}
    apply();
  });
  window.addEventListener('storage', event => {
    if (event.key !== 'theme' && event.key !== null) return;
    choice = event.newValue === 'dark' ? 'dark' : 'light';
    apply();
  });
  apply();
  control.hidden = false;
})();
