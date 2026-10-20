// Browser-history state tests; full DOM behavior is checked with local browser QA.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const entries = [];
const nodes = new Map();
const node = id => {
  if (!nodes.has(id)) nodes.set(id, {innerHTML:'',textContent:'',scrollTop:0,classList:{remove:()=>{},toggle:()=>{}},style:{}});
  return nodes.get(id);
};
const history = {
  state:null,
  pushState(state) { this.state=structuredClone(state); entries.push(this.state); },
  replaceState(state) { this.state=structuredClone(state); if(entries.length) entries[entries.length-1]=this.state; else entries.push(this.state); },
};
const context=vm.createContext({
  console, history,
  window:{addEventListener:()=>{}},
  document:{getElementById:node,querySelectorAll:()=>[],addEventListener:()=>{},body:{style:{}}},
  InventoryApiPage:{states:{raw:{tab:'ledger',receiptVisibility:'all'}},detailContext:null,render:()=>'<div>inventory</div>'},
  DashboardPage:{render:()=>'<div>dashboard</div>'},
});
vm.runInContext(fs.readFileSync('frontend/static/prototype/js/app.js','utf8')+'\nthis.app=App;',context);
const app=context.app;
(async()=>{
  app.setupHistory();
  assert.equal(entries.length,1);
  app.navigate('raw-materials');
  assert.equal(entries.length,2);
  context.InventoryApiPage.states.raw.tab='stock';
  app.recordHistory();
  const selected=structuredClone(history.state);
  assert.equal(entries.length,3);
  assert.equal(entries[1].inventory.raw.tab,'ledger','Past state must not change when current filters change.');
  const count=entries.length;
  await app.restoreHistory(entries[1]);
  assert.equal(context.InventoryApiPage.states.raw.tab,'ledger');
  assert.equal(app.currentPage,'raw-materials');
  assert.equal(entries.length,count,'Restoring history must not push a new entry.');
  await app.restoreHistory(selected);
  assert.equal(context.InventoryApiPage.states.raw.tab,'stock');
  assert.equal(app.restoringHistory,false);
  app.trackInventoryModal({kind:'picker',from:'2026-10-01',to:'2026-10-20',item_id:'',offset:0});
  const before=entries.length;
  app.trackInventoryModal({kind:'picker',item_id:'',to:'2026-10-20',from:'2026-10-01',offset:0});
  assert.equal(entries.length,before,'Equivalent picker routes must not create duplicate back steps.');
  app.navigate('sub-materials');
  assert.equal(history.state.modal,null,'Navigating menus closes inventory modals.');
  console.log('Navigation state checks passed: isolated snapshots, back/forward restoration, route deduplication and modal cleanup.');
})().catch(error=>{console.error(error);process.exitCode=1;});
