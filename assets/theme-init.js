(() => {
  let saved = 'light';
  try { saved = localStorage.getItem('theme'); } catch {}
  document.documentElement.dataset.theme = saved === 'dark' ? 'dark' : 'light';
})();
