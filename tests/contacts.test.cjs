const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../assets/contacts.js'), 'utf8');

function setup(present = true, writeText = async () => {}) {
  const listeners = {};
  let focused = false;
  let handleFocused = false;
  let selected = false;
  const trigger = {focus: () => { focused = true; }};
  const handle = {value: 'bogon.77', focus: () => { handleFocused = true; }, select: () => { selected = true; }};
  const copy = {hidden: true, disabled: false, textContent: 'Copy username', addEventListener: (_, handler) => { listeners.copy = handler; }};
  const close = {hidden: true, addEventListener: (_, handler) => { listeners.close = handler; }};
  const status = {textContent: ''};
  const contact = {
    open: true,
    contains: target => [contact, trigger, handle, copy, close, status].includes(target),
    querySelector: selector => ({summary: trigger, '.signal-handle': handle, '.signal-copy': copy, '.signal-close': close, '.contact-status': status})[selector],
    addEventListener: (type, handler) => { listeners[type] = handler; },
  };
  vm.runInNewContext(script, {navigator: {clipboard: writeText ? {writeText} : undefined}, document: {
    querySelector: () => present ? contact : null,
    addEventListener: (type, handler) => { listeners[type] = handler; },
  }});
  return {listeners, contact, trigger, handle, copy, close, status, focused: () => focused, handleFocused: () => handleFocused, selected: () => selected};
}

test('outside touch, click, or keyboard focus closes the popup', () => {
  for (const event of ['pointerdown', 'click', 'focusin']) {
    const state = setup();
    state.listeners[event]({target: {}});
    assert.equal(state.contact.open, false, event);
    assert.equal(state.focused(), false, 'outside action keeps its own focus');
  }
});

test('interacting with the handle or trigger preserves native details behavior', () => {
  const state = setup();
  for (const target of [state.handle, state.trigger, state.contact, state.copy, state.close]) {
    for (const event of ['pointerdown', 'click', 'focusin']) state.listeners[event]({target});
    assert.equal(state.contact.open, true);
  }
});

test('Escape dismisses and returns keyboard focus to the trigger', () => {
  const state = setup();
  let prevented = false;
  state.listeners.keydown({key: 'Enter'});
  assert.equal(state.contact.open, true);
  state.listeners.keydown({key: 'Escape', preventDefault: () => { prevented = true; }});
  assert.equal(state.contact.open, false);
  assert.equal(state.focused(), true);
  assert.equal(prevented, true);
});

test('pages without contact controls do not install listeners', () => {
  assert.equal(Object.keys(setup(false).listeners).length, 0);
});

test('copy writes the username and announces success', async () => {
  let copied;
  const state = setup(true, async value => { copied = value; });
  assert.equal(state.copy.hidden, false);
  assert.equal(state.close.hidden, false);
  await state.listeners.copy();
  assert.equal(copied, 'bogon.77');
  assert.equal(state.copy.disabled, false);
  assert.equal(state.copy.textContent, 'Copied');
  assert.equal(state.status.textContent, 'Username copied.');
  state.listeners.toggle();
  assert.equal(state.status.textContent, '');
  assert.equal(state.copy.textContent, 'Copy username');
});

test('unavailable or denied clipboard selects the username for manual copying', async () => {
  for (const writeText of [null, async () => { throw Error('Denied'); }]) {
    const state = setup(true, writeText);
    await state.listeners.copy();
    assert.equal(state.handleFocused(), true);
    assert.equal(state.selected(), true);
    assert.equal(state.status.textContent, 'Select and copy the username.');
    assert.equal(state.copy.disabled, false);
  }
});

test('close button dismisses the popup and returns focus', () => {
  const state = setup();
  state.listeners.close();
  assert.equal(state.contact.open, false);
  assert.equal(state.focused(), true);
});

test('clipboard rejection after dismissal does not steal focus', async () => {
  let reject;
  const state = setup(true, () => new Promise((_, fail) => { reject = fail; }));
  const pending = state.listeners.copy();
  state.listeners.pointerdown({target: {}});
  reject(Error('Denied'));
  await pending;
  assert.equal(state.handleFocused(), false);
  assert.equal(state.status.textContent, '');
});

test('a stale copy result cannot overwrite a reopened popup', async () => {
  let resolve;
  const state = setup(true, () => new Promise(done => { resolve = done; }));
  const pending = state.listeners.copy();
  state.contact.open = false;
  state.listeners.toggle();
  state.contact.open = true;
  state.listeners.toggle();
  resolve();
  await pending;
  assert.equal(state.copy.textContent, 'Copy username');
  assert.equal(state.status.textContent, '');
});
