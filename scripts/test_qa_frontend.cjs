// UI logic checks without a browser; real Safari/iPad QA is separate.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(file, name, document = {}) {
  const context = vm.createContext({console, document, App: {}, URLSearchParams, clearTimeout: () => {}, setTimeout: () => {}, window: {}, crypto: {randomUUID: () => 'test-key'}});
  vm.runInContext(fs.readFileSync('frontend/static/prototype/js/modules/mass-units.js','utf8'),context);
  vm.runInContext(fs.readFileSync(file, 'utf8') + `\nthis.page = ${name};`, context);
  return context.page;
}
const root = 'frontend/static/prototype/js/modules/';
const date = {value: '2027-01-01', disabled: false, required: true};
const content = {innerHTML:''};
const inventory = page(root + 'inventory-api.js', 'InventoryApiPage', {querySelector: () => date, getElementById: id => id==='invApiContent'?content:null});
assert.equal(inventory.state().tab, 'ledger');
inventory.rerender=()=>{};
inventory.setPeriod('today');
assert.equal(inventory.state().from,inventory.state().to);
assert.match(inventory.renderFilters(),/data-period="today" aria-pressed="true"/);
inventory.set('from','2026-10-01');
assert.equal(inventory.state().period,'');
inventory.changeExpiration('NONE');
assert.equal(date.value, '');
assert.equal(date.disabled, true);
assert.equal(date.required, false);
inventory.changeExpiration('KNOWN');
assert.equal(date.disabled, false);
assert.equal(date.required, true);
assert.equal(inventory.addQuantities('1.000001', '0.999999'), '2');
assert.equal(inventory.addQuantities('0', '0'), '0');
const totals = inventory.renderTotals({results: [{item: {id:1,item_code:'RAW', name:'원료'}, total:'3', usable:'2', quarantine:'0', unusable:'1', minimum_stock:'0',unit:'kg',lot_count:1}]});
assert.match(totals, /총재고/);
assert.match(totals, /사용 불가/);
assert.match(totals, /<td>3 kg<\/td><td>2 kg<\/td><td>1 kg<\/td>/);
const item={id:1,item_code:'1000040',name:'덱스트린',base_unit:'kg'};
const ledger={from:'2026-09-30',to:'2026-10-01',results:[{item,unit:'kg',lots:[
  {lot_id:10,lot_number:'A',opening:'2',in:'0',out:'0.5',closing:'1.5',lines:[{movement_id:1,occurred_at:'2026-10-01',quantity:'-0.5',balance:'1.5',movement_name:'생산 투입',staff_name:'QA',reason:'확인',source:{batch:{id:7,number:'B-7'}}}]},
  {lot_id:11,lot_number:'B',opening:'0',in:'1',out:'1',closing:'0',lines:[]},
]}]};
inventory.detailContext={id:1,from:ledger.from,to:ledger.to,direction:'',lotId:null};
inventory.detailCache={item,ledger,queriedAt:'2026-10-19',total:{total:'3',usable:'2',quarantine:'0.5',unusable:'0.5',unit:'kg'},stock:{results:[{lot_id:10,lot_number:'A',item,quantity:'3',unit:'kg',status:'AVAILABLE',expiration_status:'NONE'}]}};
inventory.renderItemDetail();
assert.match(date.innerHTML,/총재고/);
assert.match(date.innerHTML,/使用 불가|사용 불가/);
assert.match(date.innerHTML,/invItemFrom/);
assert.match(date.innerHTML,/거래 직후 LOT 잔량/);
assert.match(date.innerHTML,/openBatch\(7\)/);
assert.equal((inventory.renderPeriodSummary(ledger).match(/data-period-lot=/g)||[]).length,2);
assert.equal((inventory.renderPeriodSummary(ledger).match(/data-period-closing="1.5"/g)||[]).length,1);
assert.doesNotMatch(inventory.renderLedger(ledger),/data-period-closing/);
inventory.selectDetailLot(10);
assert.equal(inventory.detailLedgerData().results[0].lots.length,1);
assert.equal(inventory.detailCache.stock.results.length,1);
inventory.setDetailDirection('');
assert.equal(inventory.detailContext.lotId,null);
inventory.state().selectedLot={id:10,number:'A'};inventory.state().itemId='1';
inventory.set('direction','');
assert.equal(inventory.state().selectedLot,null);
assert.equal(inventory.state().itemId,'');
const production = page(root + 'production-api.js', 'ProductionApiPage', {
  querySelectorAll: () => [{dataset:{pick:'10'}}, {dataset:{pick:'11'}}],
  querySelector: selector => ({value: selector.includes('10') ? '0.999999' : '1.000001'}),
});
production.detail = {readiness:{lines:[{stock_managed:true, bom_line_id:1, name:'녹용',unit:'kg',item_code:'1000004', allowed_items:[{id:1,item_code:'1000004',name:'녹용',base_unit:'kg'},{id:2,item_code:'1000005',name:'녹용(러시아)',base_unit:'g'}]}]}};
production.s.use={lineId:1,itemId:'',quantity:'2',allocations:{10:'0.999999',11:'1000.001'}};
production.lotChoices=[{lot_id:10,unit:'kg',item:{name:'녹용'}},{lot_id:11,unit:'g',item:{name:'녹용(러시아)'}}];
production.inputItems = [{id:99,item_code:'1000015',name:'홍삼분말'}];
const form = production.renderUseForm();
assert.match(form, /1000004/);
assert.match(form, /1000005/);
assert.doesNotMatch(form, /1000015|홍삼분말/);
assert.match(form, /일괄 투입/);
assert.equal(production.allocationTotal(), '2');
production.s.use.allocations[11]='0.000001';
assert.equal(production.allocationTotal(), null); // g -> kg precision loss must be rejected.
assert.doesNotMatch(form, /type="search"/);
assert.match(form, /LOT · 배분량 직접 수정/);
inventory.state().q='녹용';
assert.equal(inventory.ledgerParams().q,'녹용');
inventory.state().direction='OUT';
const filteredLedger={results:[{item:{},lots:[{lines:[{quantity:'1',occurred_at:'2026-10-16',movement_id:1},{quantity:'-0.5',occurred_at:'2026-10-16',movement_id:2}]}]}]};
assert.equal(inventory.ledgerLines(filteredLedger).length,1);
assert.equal(inventory.ledgerLines(filteredLedger)[0].line.quantity,'-0.5');
assert.equal(production.s.statusFilter, 'ACTIVE');
const bulkRow=(id,quantity,amount,unit='kg')=>({bom_line_id:id,name:'원료 '+id,unit,quantity,selected:true,standard:quantity,actual:'0',allocations:{10:amount},choices:[{lot_id:10,lot_number:'SHARED',unit:'g',stock:'1000'}],allowed_items:[{id:1,name:'원료'}]});
production.bulkUse={rows:[bulkRow(1,'0.6','600'),bulkRow(2,'0.5','500')]};
assert.equal(production.bulkTotal(production.bulkUse.rows[0]),600000n);
assert.match(production.bulkErrors().join(' '),/가용재고/); // competing BOM lines share a LOT
production.bulkUse.rows[1].selected=false;
assert.equal(production.bulkErrors().length,0);
production.bulkUse.rows[0].allocations[10]='0.000001';
assert.equal(production.bulkTotal(production.bulkUse.rows[0]),null); // exact conversion required
assert.match(production.bulkErrors().join(' '),/LOT 합계/);
production.bulkUse.rows[0].allocations[10]='600';
assert.match(production.renderBulkUse(),/이번 실제 투입량/);
assert.match(production.renderBulkUse(),/기등록량/);
assert.match(production.renderBulkUse(),/선택 1 \/ 2개 원료/);
assert.match(production.renderBulkUse(),/원료 LOT 다시 자동 배분/);
console.log('UI logic checks passed: BOM choices, expiry transitions, exact totals, cancelled default.');

// Display filters hide the entire cancelled receipt history without changing balances.
inventory.state().direction='';
const auditLedger={results:[{item:{id:1,item_code:'A',name:'원료'},unit:'kg',lots:[
  {lot_id:1,lot_number:'CANCELLED',lines:[
    {movement_id:1,occurred_at:'2026-10-01',quantity:'5',balance:'5',source:{receipt_status:'CANCELLED'}},
    {movement_id:2,occurred_at:'2026-10-02',quantity:'-5',balance:'0',source:{receipt_status:'CANCELLED'}},
  ]},
  {lot_id:2,lot_number:'ACTIVE',lines:[{movement_id:3,occurred_at:'2026-10-03',quantity:'2',balance:'2',source:{receipt_status:'COMPLETED'}}]},
]}]};
const original=JSON.stringify(auditLedger);
inventory.state().receiptVisibility='hide';
assert.deepEqual(Array.from(inventory.ledgerLines(auditLedger), r=>r.line.movement_id),[3]);
inventory.state().receiptVisibility='only';
inventory.state().ledgerSortOrder='asc';
assert.deepEqual(Array.from(inventory.ledgerLines(auditLedger), r=>r.line.movement_id),[1,2]);
assert.equal(inventory.ledgerLines(auditLedger)[1].line.balance,'0');
assert.equal(JSON.stringify(auditLedger),original);
inventory.state().receiptVisibility='all';
inventory.state().ledgerSortOrder='desc';
assert.deepEqual(Array.from(inventory.ledgerLines(auditLedger), r=>r.line.movement_id),[3,2,1]);
inventory.state().stockSortBy='total'; inventory.state().stockSortOrder='desc';
const stock=[{item:{id:1,item_code:'A'},total:'9007199254740992.000001'},{item:{id:2,item_code:'B'},total:'9007199254740992.000002'}];
assert.equal(inventory.sortStockTotals(stock)[0].item.id,2,'Stock sorting must preserve exact decimal precision.');
console.log('Inventory sort/cancellation display checks passed; original balances are unchanged.');
