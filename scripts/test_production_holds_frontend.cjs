// Production hold workflow: validation, safe rendering, payloads and retry preservation.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const notices=[], requests=[], detailNode={innerHTML:'',insertAdjacentHTML:()=>{}};
const context=vm.createContext({console,URLSearchParams,window:{},crypto:{randomUUID:()=> 'key'},
  App:{showToast:(...args)=>notices.push(args)},
  document:{getElementById:id=>id==='prodDetail'?detailNode:null,querySelector:()=>null,querySelectorAll:()=>[]}});
vm.runInContext(fs.readFileSync('frontend/static/prototype/js/modules/production-api.js','utf8')+'\nthis.page=ProductionApiPage;',context);
const p=context.page;
const renderDetail=p.renderDetail;p.renderDetail=()=>{};
const hold={id:5,is_open:true,reason:'<script>test</script>',held_at:'2026-10-24T10:00:00+09:00',held_by:{id:1,name:'가상담당'}};
p.staff=[{id:1,name:'가상담당'}];p.s.staffId='1';p.s.batchId=7;p.s.creating=false;
p.detail={id:7,status:'IN_PROGRESS',holds:[hold],active_hold_count:1};
assert.match(p.renderHolds(p.detail),/&lt;script&gt;test&lt;\/script&gt;/);
assert.doesNotMatch(p.renderHolds(p.detail),/<script>/);
assert.match(p.renderHolds(p.detail),/개선조치 확인 · 해제/);
p.openHoldForm(5);
assert.equal(p.holdForm.kind,'release');
assert.match(p.renderHolds(p.detail),/name="confirmed" required/);
p.holdForm.reason='개선조치 확인';
(async()=>{
  p.post=async(path,body)=>{requests.push({path,body});return {};};
  p.loadList=async()=>{};p.select=async()=>{};
  await p.saveHold();assert.equal(requests.length,0,'Unconfirmed release must not write.');
  p.holdForm.confirmed=true;p.holdForm.reason='  ';
  await p.saveHold();assert.equal(requests.length,0,'Blank reason must not write.');
  p.holdForm.reason='개선조치 확인';
  await p.saveHold();assert.equal(requests.length,1);
  assert.equal(requests[0].path,'/holds/5/release/');
  assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body)),{disposition:'RELEASE',reason:'개선조치 확인',staff_id:1});
  assert.equal(p.holdForm,null);
  p.openHoldForm();p.holdForm.reason='이탈 확인';
  p.post=async()=>{throw Error('통신 실패');};
  await p.saveHold();assert.equal(p.holdForm.reason,'이탈 확인','Failure preserves the draft for retry.');
  p.post=async(path,body)=>{requests.push({path,body});return {};};
  await p.saveHold();assert.equal(requests[1].path,'/holds/');
  assert.equal(requests[1].body.source_type,'MANUAL');
  assert.equal(requests[1].body.batch_id,7);
  assert.equal(requests[1].body.source_document_id,undefined);
  // Render the work tab with a hold: only the production work fieldset is disabled.
  p.renderDetail=renderDetail;
  p.renderHead=()=>'';p.renderUsages=()=>'<button>투입</button>';p.renderOutputs=()=>'<button>산출</button>';p.renderComplete=()=>'<button>완료</button>';
  p.renderDetail();assert.match(detailNode.innerHTML,/<fieldset disabled/);
  assert.ok(detailNode.innerHTML.indexOf('id="prodHolds"')<detailNode.innerHTML.indexOf('<fieldset disabled'));
  p.detail.active_hold_count=0;p.detail.holds=[{...hold,is_open:false,release_reason:'확인',released_by:{name:'가상담당'}}];
  p.renderDetail();assert.doesNotMatch(detailNode.innerHTML,/<fieldset disabled/);
  assert.match(detailNode.innerHTML,/보류·해제 이력 1건/);
  assert.match(detailNode.innerHTML,/<details class="card" id="prodHoldManage"\s+style=/,'Released history is collapsed.');
  p.detail.holds=[];p.renderDetail();
  assert.ok(detailNode.innerHTML.indexOf('id="prodHoldManage"')>detailNode.innerHTML.indexOf('</fieldset>'),'Normal progress keeps hold management below work.');
  p.detail.status='PLANNED';p.renderDetail();
  assert.doesNotMatch(detailNode.innerHTML,/id="prodHoldManage"|id="prodHolds"|id="prodHoldOpen"/,'Normal plans have no hold UI.');
  console.log('PASS: hold rendering, release confirmation, reasons, manual payload, retries and work lock');
})().catch(e=>{console.error(e);process.exitCode=1;});
