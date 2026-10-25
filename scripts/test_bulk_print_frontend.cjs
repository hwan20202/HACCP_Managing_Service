// Multiple selection, ordering, escaping and direct browser-print handoff.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let html='',printCalls=0;const closeHandlers=[];
const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',disabled:false});return nodes.get(id);};
const context=vm.createContext({console,URLSearchParams,window:{},setTimeout:()=>{},clearTimeout:()=>{},
 document:{getElementById:node,querySelectorAll:()=>[]},App:{showToast:()=>{}},
 BrowserPrint:{print:(value,onClose)=>{html=value;printCalls++;closeHandlers.push(onClose);return true;}}});
for(const name of ['mass-units','production-api','inventory-api'])vm.runInContext(fs.readFileSync(`frontend/static/prototype/js/modules/${name}.js`,'utf8')+(name==='production-api'?'\nthis.prod=ProductionApiPage;':name==='inventory-api'?'\nthis.inv=InventoryApiPage;':''),context);
const {prod,inv}=context;
const batches=[{id:1,batch_number:'B-10',planned_date:'2026-10-22'},{id:2,batch_number:'B-2',planned_date:'2026-10-21'}].map(b=>({...b,status:'PLANNED',unit:'kg',planned_quantity:'1',item:{item_code:'TEST',name:'<제품>'},readiness:{lines:[{item_code:'R',name:'원료',required:'0.1',unit:'kg'}]},usages:[],outputs:[]}));
prod.listBatches=batches;prod.s.creating=false;prod.get=async path=>batches.find(b=>path===`/batches/${b.id}/`);
prod.renderBatchList();assert.doesNotMatch(node('prodList').innerHTML,/data-print-batch=/,'No persistent production selection.');
prod.beginPrintSelection();assert.match(node('prodList').innerHTML,/data-print-batch=/);
assert.equal(node('prodPrintSelected').disabled,true,'Empty selection cannot print.');
prod.selectPrintBatch(1,true);prod.selectPrintBatch(2,true);
(async()=>{
 await prod.printBatch();assert.equal(printCalls,1);
 assert.ok(html.indexOf('data-print-batch="2"')<html.indexOf('data-print-batch="1"'));
 assert.equal((html.match(/<section /g)||[]).length,2);
 assert.match(html,/&lt;제품&gt;/);assert.match(html,/break-before:page/);assert.doesNotMatch(html,/<button|window\.print/);
 closeHandlers.at(-1)();assert.equal(prod.printSelecting,false);assert.equal(prod.printBatchIds.length,0);assert.doesNotMatch(node('prodList').innerHTML,/data-print-batch=/);
 prod.beginPrintSelection();prod.selectPrintBatch(1,true);
 const previous=html;prod.get=async()=>{throw Error('조회 실패');};await prod.printBatch();assert.equal(html,previous,'No partial output after a failed batch lookup.');
 assert.equal(prod.printSelecting,true,'Lookup failure preserves selection for retry.');
 prod.endPrintSelection();assert.equal(prod.printSelecting,false);
 prod.get=async()=>batches[0];prod.detail=batches[0];await prod.printBatch(true);assert.equal((html.match(/<section /g)||[]).length,1);assert.equal(closeHandlers.at(-1),undefined,'Single batch prints directly without selection mode.');
 const make=(id,code)=>({item:{id,item_code:code,name:'원료 '+code},unit:'kg',lots:[{lot_id:id,lot_number:'LOT-'+id,lines:[{movement_id:id*10+2,occurred_at:'2026-10-22',quantity:'1',balance:'2',movement_name:'입고'},{movement_id:id*10+1,occurred_at:'2026-10-21',quantity:'1',balance:'1',movement_name:'입고'}]}]});
 const data={from:'2026-10-01',to:'2026-10-23',results:[make(3,'R-30'),make(1,'R-2'),make(2,'R-10')]};
 inv.cache={tab:'ledger',data};assert.doesNotMatch(inv.renderLedger(data),/data-print-item=/);
 inv.beginPrintSelection();assert.equal(inv.state().printSelecting,true);assert.match(inv.renderLedger(data),/data-print-item=/);
 inv.state().printItemIds=[3,1];inv.printSelectedResults();
 assert.equal((html.match(/<section /g)||[]).length,2);assert.ok(html.indexOf('data-print-item="R-2"')<html.indexOf('data-print-item="R-30"'));
 assert.doesNotMatch(html,/data-print-item="R-10"/);assert.ok(html.indexOf('<td>2026-10-21</td>')<html.indexOf('<td>2026-10-22</td>'));
 assert.equal(data.results[0].lots[0].lines[0].occurred_at,'2026-10-22','Print order cannot mutate ledger order/balances.');
 closeHandlers.at(-1)();assert.equal(inv.state().printSelecting,false);assert.equal(inv.state().printItemIds.length,0);assert.doesNotMatch(inv.renderLedger(data),/data-print-item=/);
 inv.beginPrintSelection();
 inv.selectAllPrintItems(true);assert.equal(inv.state().printItemIds.length,3);
 inv.renderPrintSelection({...data,results:[data.results[0]]},true);assert.deepEqual(Array.from(inv.state().printItemIds),[3],'A new filter prunes hidden selections.');
 inv.state().printItemIds=[];inv.printResults();assert.equal((html.match(/<section /g)||[]).length,3,'No selection preserves printing the entire filtered result.');
 inv.endPrintSelection();assert.equal(inv.state().printSelecting,false);
 console.log('PASS: multi-batch/item selection, automatic ordering, full selection, filter pruning and direct print handoff');
})().catch(e=>{console.error(e);process.exitCode=1;});
