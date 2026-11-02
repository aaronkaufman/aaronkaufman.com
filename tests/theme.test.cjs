const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function environment(saved, dark, blocked = false) {
  const dataset = {};
  const listeners = {};
  const select = {value:'', addEventListener: (type, fn) => listeners[type] = fn};
  const control = {hidden:true};
  const metas = [{content:''}, {content:''}];
  const media = {matches:dark, addEventListener: (_, fn) => listeners.system = fn};
  const context = vm.createContext({
    document: {documentElement:{dataset}, getElementById:() => select, querySelector:() => control, querySelectorAll:() => metas},
    localStorage: {getItem:() => {if(blocked) throw Error('Blocked'); return saved;}, setItem:(_, value) => {if(blocked) throw Error('Blocked'); saved = value;}},
    matchMedia:() => media,
    window:{addEventListener:(_, fn) => listeners.storage = fn},
  });
  for (const name of ['theme-init.js','theme.js']) vm.runInContext(fs.readFileSync(path.join(__dirname,'../assets',name),'utf8'), context);
  return {dataset,select,control,metas,media,listeners,saved:() => saved};
}

test('Latte is the default even when the browser prefers dark', () => {
  const env = environment(null,true);
  assert.equal(env.control.hidden,false);
  assert.equal(env.select.value,'light');
  assert.equal(env.dataset.theme,'light');
  assert.equal(env.metas[0].content,'#eff1f5');
  assert.equal(env.listeners.system,undefined);
  env.select.value='dark'; env.listeners.change();
  assert.equal(env.dataset.theme,'dark');
  assert.equal(env.saved(),'dark');
  assert.equal(env.metas[0].content,'#1e1e2e');
  env.select.value='light'; env.listeners.change();
  assert.equal(env.dataset.theme,'light');
  assert.equal(env.saved(),'light');
  assert.equal(env.metas[0].content,'#eff1f5');
});

test('stored choice and changes from another tab', () => {
  const env=environment('dark',false);
  assert.equal(env.dataset.theme,'dark');
  env.listeners.storage({key:'theme',newValue:'light'});
  assert.equal(env.dataset.theme,'light');
  env.listeners.storage({key:null,newValue:null});
  assert.equal(env.dataset.theme,'light');
});

test('blocked storage and invalid saved values do not break controls', () => {
  const env=environment(null,true,true);
  assert.equal(env.dataset.theme,'light');
  env.select.value='dark'; env.listeners.change();
  assert.equal(env.dataset.theme,'dark');
  assert.equal(environment('invalid',true).select.value,'light');
  assert.equal(environment('system',true).select.value,'light');
});
