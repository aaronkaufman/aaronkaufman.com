(() => {
  const contact = document.querySelector('.signal-contact');
  if (!contact) return;
  const trigger = contact.querySelector('summary');
  const handle = contact.querySelector('.signal-handle');
  const copy = contact.querySelector('.signal-copy');
  const close = contact.querySelector('.signal-close');
  const status = contact.querySelector('.contact-status');
  let interaction = 0;

  contact.addEventListener('toggle', () => {
    interaction++;
    status.textContent = '';
    copy.textContent = 'Copy username';
    copy.disabled = false;
  });

  copy.addEventListener('click', async () => {
    const attempt = ++interaction;
    copy.disabled = true;
    status.textContent = '';
    try {
      await navigator.clipboard.writeText(handle.value);
      if (attempt !== interaction || !contact.open) return;
      copy.textContent = 'Copied';
      status.textContent = 'Username copied.';
    } catch {
      if (attempt !== interaction || !contact.open) return;
      handle.focus();
      handle.select();
      status.textContent = 'Select and copy the username.';
    } finally {
      if (attempt === interaction) copy.disabled = false;
    }
  });

  close.addEventListener('click', () => {
    contact.open = false;
    trigger.focus();
  });
  copy.hidden = false;
  close.hidden = false;

  function dismissOutside(event) {
    if (contact.open && !contact.contains(event.target)) contact.open = false;
  }

  document.addEventListener('pointerdown', dismissOutside);
  document.addEventListener('click', dismissOutside);
  document.addEventListener('focusin', dismissOutside);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !contact.open) return;
    contact.open = false;
    trigger.focus();
    event.preventDefault();
  });
})();
