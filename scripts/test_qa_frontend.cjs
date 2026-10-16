// UI logic checks without a browser; real Safari/iPad QA is separate.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(file, name, document = {}) {
  const context = vm.createContext({console, document, setTimeout: () => {}, window: {}, crypto: {randomUUID: () => 'test-key'}});
  vm.runInContext(fs.readFileSync(file, 'utf8') + `\nthis.page = ${name};`, context);
  return context.page;
}
const root = 'frontend/static/prototype/js/modules/';
const date = {value: '2027-01-01', disabled: false, required: true};
const inventory = page(root + 'inventory-api.js', 'InventoryApiPage', {querySelector: () => date});
inventory.changeExpiration('NONE');
assert.equal(date.value, '');
assert.equal(date.disabled, true);
assert.equal(date.required, false);
inventory.changeExpiration('KNOWN');
assert.equal(date.disabled, false);
assert.equal(date.required, true);
assert.equal(inventory.addQuantities('1.000001', '0.999999'), '2');
assert.equal(inventory.addQuantities('0', '0'), '0');
const totals = inventory.renderTotals({results: [{item: {item_code:'RAW', name:'원료'}, total:'3', usable:'2', quarantine:'0', unusable:'1', unit:'kg'}]});
assert.match(totals, /총재고/);
assert.match(totals, /사용 불가/);
assert.match(totals, /<td>3<\/td><td>2<\/td><td>1<\/td>/);
const production = page(root + 'production-api.js', 'ProductionApiPage', {
  querySelectorAll: () => [{dataset:{pick:'10'}}, {dataset:{pick:'11'}}],
  querySelector: selector => ({value: selector.includes('10') ? '0.999999' : '1.000001'}),
});
production.detail = {readiness:{lines:[{stock_managed:true, bom_line_id:1, name:'녹용', allowed_items:[{id:1,item_code:'1000004',name:'녹용',base_unit:'kg'},{id:2,item_code:'1000005',name:'녹용(러시아)',base_unit:'kg'}]}]}};
production.inputItems = [{id:99,item_code:'1000015',name:'홍삼분말'}];
const form = production.renderUseForm();
assert.match(form, /1000004/);
assert.match(form, /1000005/);
assert.doesNotMatch(form, /1000015|홍삼분말/);
assert.match(form, /일괄 투입/);
assert.equal(production.allocationTotal(), '2');
assert.equal(production.s.statusFilter, 'ACTIVE');
console.log('UI logic checks passed: BOM choices, expiry transitions, exact totals, cancelled default.');
