// Pagination must not truncate exports/prints or alter ledger balances.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
let printed='',popupAllowed=true;
const notices=[];
const context=vm.createContext({console,URLSearchParams,setTimeout:()=>{},clearTimeout:()=>{},document:{},
  BrowserPrint:{print:html=>{if(!popupAllowed)throw Error('인쇄 창 오류');printed=html;return true;}},
  window:{open:()=>popupAllowed?{opener:{},document:{write:text=>{printed=text;},close:()=>{}},focus:()=>{}}:null},
  App:{showToast:(...args)=>notices.push(args)}});
for(const name of ['mass-units','inventory-api']) vm.runInContext(fs.readFileSync(`frontend/static/prototype/js/modules/${name}.js`,'utf8')+(name==='inventory-api'?'\nthis.page=InventoryApiPage;':''),context);
const page=context.page;
const item={item:{id:1,item_code:'QA-1',name:'<검증 & 원료>'},unit:'kg',lots:[{lot_id:1,lot_number:'LOT-1',lines:Array.from({length:123},(_,i)=>({movement_id:i+1,occurred_at:'2026-10-23T12:00:00+09:00',quantity:i%2?'-0.5':'1',balance:'12.5',movement_name:'입고',reason:'<script>alert(1)</script>',source:{receipt_status:i<3?'CANCELLED':'COMPLETED'}}))}]};
const data={from:'2026-10-01',to:'2026-10-23',results:[item]};
page.cache={tab:'ledger',data,queriedAt:'검증 시각'};
assert.equal((page.renderLedger(data).match(/data-movement=/g)||[]).length,50);
page.state().ledgerPage=3;
assert.equal((page.renderLedger(data).match(/data-movement=/g)||[]).length,23);
assert.match(page.renderLedger(data),/101–123/);
page.state().displayUnit='g';
page.printResults();
assert.equal((printed.match(/<tbody>[\s\S]*<\/tbody>/)[0].match(/<tr>/g)||[]).length,123);
assert.match(printed,/12500/); // Transaction balance converted exactly to g.
assert.match(printed,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.doesNotMatch(printed,/<script>/);
assert.match(printed,/취소됨/);
page.state().direction='OUT';page.state().receiptVisibility='hide';
const expected=page.ledgerLines(data,'OUT').length;
page.printResults();
assert.equal((printed.match(/<tbody>[\s\S]*<\/tbody>/)[0].match(/<tr>/g)||[]).length,expected);
assert.doesNotMatch(printed,/<td>취소됨<\/td>/);
assert.equal(item.lots[0].lines[0].balance,'12.5');
page.detailContext={lotId:1,direction:'IN',ledgerPage:2};
page.detailCache={item:item.item,ledger:data,stock:{results:[{lot_id:1,lot_number:'LOT-1'}]},queriedAt:'상세 조회'};
page.printResults(true);
assert.match(printed,/선택 LOT LOT-1/);
assert.equal((printed.match(/<tbody>[\s\S]*<\/tbody>/)[0].match(/<tr>/g)||[]).length,page.ledgerLines(data,'IN').length);
popupAllowed=false;page.printResults();assert.equal(notices.at(-1)[0],'error');
page.rerender=()=>{};page.state().from='2024-03-31';page.shiftMonth(-1);
assert.equal(page.state().from,'2024-02-01');assert.equal(page.state().to,'2024-02-29');
page.state().from='2026-01-01';page.shiftMonth(-1);assert.equal(page.state().from,'2025-12-01');
page.resetFilters();assert.equal(page.state().q,'');assert.equal(page.state().selectedLot,null);
page.state().ledgerPage=999;page.pageRows([1,2],'ledgerPage');assert.equal(page.state().ledgerPage,1);
popupAllowed=true;
page.cache={tab:'stock',queriedAt:'현재고 조회',data:{results:[{item:item.item,total:'2',usable:'1.5',quarantine:'0.25',unusable:'0.25',minimum_stock:'1',unit:'kg',lot_count:3}]}};
page.state().displayUnit='g';page.printResults();assert.match(printed,/<td>2000<\/td>/);assert.match(printed,/<td>500<\/td>/);
const host={innerHTML:''}, content={innerHTML:''};
context.document.getElementById=id=>id==='invApiPage'?host:content;
context.document.querySelector=()=>null;
page.fitViewport=()=>{};page.fetchLedger=async()=>data;
page.state().focusBatch=77;page.state().ledgerPage=null;
item.lots[0].lines[22].source.batch={id:77};
(async()=>{
  await page.load();
  assert.equal(page.state().ledgerPage,3,'Production link must locate the batch beyond page one.');
  assert.match(content.innerHTML,/data-highlight="true"/);
  console.log('Inventory browsing checks passed: bounded pages, full filtered print, exact balances, escaping, selected LOT, stock units, blocked popup, leap month, reset and production focus.');
})().catch(error=>{console.error(error);process.exitCode=1;});
