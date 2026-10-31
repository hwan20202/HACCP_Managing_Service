// BOM authoring uses the existing versioned recipe tables and production API.
const BomApiPage = {
  items: [], boms: [], staff: [], draft: null, openItems: {}, runningBatches: [], runningBomIds: new Set(), query: '', page: 1, pageSize: 10,
  esc(value) { return InventoryApiPage.esc(value); },
  async request(path, method = 'GET', body) {
    const token = decodeURIComponent(document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || '');
    const response = await fetch('/api/v1/inventory' + path, {
      method, credentials: 'same-origin',
      headers: {'Content-Type':'application/json', 'X-CSRFToken':token},
      ...(body ? {body:JSON.stringify(body)} : {}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error?.message || '요청 실패');
    return result;
  },
  async open() {
    App.showModal('BOM 관리', '<p>BOM을 불러오는 중…</p>');
    document.getElementById('modalContainer').classList.add('inventory-detail-modal');
    try {
      const [items, boms, staff, running, planned] = await Promise.all([
        this.request('/items/'), this.request('/boms/?include_inactive=1'), this.request('/staff/'),
        this.request('/batches/?status=IN_PROGRESS&limit=200'), this.request('/batches/?status=PLANNED&limit=200'),
      ]);
      this.items=items.results; this.boms=boms.results; this.staff=staff.results;
      // Open plans/runs (계획·진행). An inactive version with open ones is an "이전 버전 · 진행 중 N건".
      this.runningBatches=[...running.results,...planned.results];
      this.runningBomIds=new Set(this.runningBatches.map(batch=>batch.bom_id));
      this.list();
    } catch (error) { this.error(error); }
  },
  host() { return document.querySelector('#modalContainer .modal-body'); },
  error(error) { App.showToast('error','BOM 관리',error.message); },
  search(value) {
    this.query=value; this.page=1; this.list();
    const input=document.getElementById('bomSearch'); input.focus(); input.setSelectionRange(value.length,value.length);
  },
  changePage(value) { this.page=value; this.list(); },
  list() {
    const items=new Map(this.items.map(item=>[item.id,item])), grouped=new Map();
    for(const bom of this.boms) {
      if(!grouped.has(bom.item_id))grouped.set(bom.item_id,[]);
      grouped.get(bom.item_id).push(bom);
    }
    const query=this.query.trim().toLocaleLowerCase();
    const groups=[...grouped.entries()].filter(([id])=>!query||`${items.get(id)?.item_code||id} ${items.get(id)?.name||''}`.toLocaleLowerCase().includes(query)).sort(([a],[b])=>String(items.get(b)?.item_code||b).localeCompare(String(items.get(a)?.item_code||a),'ko',{numeric:true})||b-a);
    const pages=Math.max(1,Math.ceil(groups.length/this.pageSize)); this.page=Math.min(this.page,pages);
    if(this.revealItemId!=null) { const index=groups.findIndex(([id])=>id===this.revealItemId); if(index>=0)this.page=Math.floor(index/this.pageSize)+1; this.revealItemId=null; }
    this.host().innerHTML = `<style>#bomList .data-table{min-width:680px}#bomList .bom-actions{white-space:nowrap}#bomList > details > summary{cursor:pointer;padding:0.85rem 1rem}#bomList summary:focus-visible{outline:2px solid var(--brand-primary);outline-offset:-2px}#bomList .bom-activation.is-active{background:#e8f5ff;border-color:#b9ddf5;color:#31729c;box-shadow:none}#bomList .bom-activation.is-active:hover{background:#dbedfb}#bomList .bom-connection-note{display:block;max-width:26rem;margin-top:0.3rem;color:var(--text-muted);font-size:0.72rem;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}</style>
      <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;flex-wrap:wrap"><p>활성 버전은 품목당 하나입니다. 버전을 전환해도 기존 생산지시는 원래 배합을 유지합니다.</p><button class="btn btn-primary" onclick="BomApiPage.edit()">새 BOM 등록</button></div>
      <div style="display:flex;gap:0.75rem;align-items:end;flex-wrap:wrap;margin-bottom:0.75rem"><label style="flex:1;min-width:180px">품목 검색<input id="bomSearch" class="form-control" type="search" placeholder="품목코드 또는 품명" value="${this.esc(this.query)}" oninput="BomApiPage.search(this.value)"></label><label>표시 품목 수<select class="form-control" onchange="BomApiPage.pageSize=Number(this.value);BomApiPage.changePage(1)">${[10,20,50].map(n=>`<option ${n===this.pageSize?'selected':''}>${n}</option>`).join('')}</select></label></div>
      <p style="font-size:0.8rem;color:var(--text-muted)">조회 품목 ${groups.length}개 / 전체 ${grouped.size}개 · 품목코드 내림차순 · 활성 버전 → 기존 생산 진행 중 → 비활성, 각 버전 오름차순</p>
      <div id="bomList">${groups.slice((this.page-1)*this.pageSize,this.page*this.pageSize).map(([itemId,boms])=>{
        const item=items.get(itemId);
        const rank=b=>b.is_active?0:this.openCount(b)?1:2;
        const versions=[...boms].sort((a,b)=>rank(a)-rank(b)||a.version-b.version||a.id-b.id);
        return `<details data-bom-item="${itemId}" ${this.openItems[itemId]?'open':''} ontoggle="BomApiPage.openItems[${itemId}]=this.open" style="border:1px solid var(--border-subtle);border-radius:8px;margin-bottom:0.65rem;overflow:hidden">
          <summary><strong>${this.esc(item?.item_code||itemId)} ${this.esc(item?.name||'')}</strong> <span style="font-size:0.8rem;color:var(--text-muted);margin-left:0.5rem">${versions.length}개 버전 · 활성 ${versions.filter(b=>b.is_active).map(b=>`v${b.version}`).join(', ')||'없음'}${versions.filter(b=>!b.is_active&&this.openCount(b)).map(b=>` · 이전 버전 v${b.version} 진행 중 ${this.openCount(b)}건`).join('')}</span></summary>
          <div class="table-wrapper"><table class="data-table"><thead><tr><th>버전</th><th>적용 시작일</th><th>상태</th><th>원료 수</th><th>관리</th></tr></thead><tbody>
          ${versions.map(b=>`<tr data-bom-id="${b.id}"><td>v${b.version}</td><td>${this.esc(b.effective_from)}</td><td>${this.statusBadges(b)} · ${b.used?'생산 연결 이력 있음':'미사용'}${this.connectionNote(b)}</td><td>${b.lines.length}</td><td class="bom-actions"><button class="btn btn-secondary btn-sm" onclick="BomApiPage.edit(${b.id})">조회·수정</button> <button class="btn btn-secondary btn-sm" onclick="BomApiPage.edit(${b.id},true)">새 버전</button> <button class="btn btn-danger btn-sm" ${b.used?'disabled title="생산 연결 이력이 있어 삭제할 수 없습니다."':''} onclick="BomApiPage.remove(${b.id})">삭제</button> <button class="btn btn-secondary btn-sm bom-activation" data-bom-action="${b.is_active?'deactivate':'activate'}" onclick="BomApiPage.activate(${b.id},this)">${b.is_active?'비활성화':'활성화'}</button></td></tr>`).join('')}
          </tbody></table></div></details>`;
      }).join('')||`<div class="empty-state"><p>${query?'검색 결과가 없습니다.':'등록된 BOM이 없습니다.'}</p></div>`}</div>
      <div style="display:flex;align-items:center;justify-content:center;gap:1rem;margin-top:1rem"><button class="btn btn-secondary btn-sm" ${this.page<=1?'disabled':''} onclick="BomApiPage.changePage(${this.page-1})">이전</button><span>${this.page} / ${pages}</span><button class="btn btn-secondary btn-sm" ${this.page>=pages?'disabled':''} onclick="BomApiPage.changePage(${this.page+1})">다음</button></div>`;
  },
  openCount(bom) { return bom.open_batch_count ?? this.runningBatches.filter(batch=>batch.bom_id===bom.id).length; },
  // 활성은 품목당 하나. 비활성인데 계획·진행 중 지시가 남은 버전은 "이전 버전 · 진행 중 N건".
  statusBadges(bom) {
    if(bom.is_active) return '<span class="badge badge-success">활성</span>';
    const count=this.openCount(bom);
    if(!count) return '<span class="badge badge-neutral">비활성</span>';
    const tip=`새 생산계획에는 적용되지 않습니다. 이 버전으로 계획·진행 중인 생산지시 ${count}건은 그대로 진행됩니다.`;
    return `<span class="badge badge-neutral">이전 버전</span> <span class="badge badge-warning" title="${this.esc(tip)}">진행 중 ${count}건</span>`;
  },
  connectionNote(bom) {
    if(bom.is_active) return '';
    const batches=this.runningBatches.filter(batch=>batch.bom_id===bom.id);
    if(!batches.length) return '';
    const names=batches.map(batch=>batch.batch_number);
    const summary=`${names[0]}${names.length>1?' 외 '+(names.length-1)+'건':''}`;
    const detail=`${names.join(', ')} 생산지시 연결 · 생산 완료까지 기존 배합 유지. 신규 생산에서는 비활성입니다.`;
    return `<small class="bom-connection-note" title="${this.esc(detail)}">* ${this.esc(summary)} 생산지시 연결 · 완료까지 기존 배합 유지</small>`;
  },
  options(rows, selected) { return rows.map(i=>`<option value="${i.id}" ${String(i.id)===String(selected)?'selected':''}>${this.esc(i.item_code || i.staff_code)} ${this.esc(i.name)}</option>`).join(''); },
  edit(id,copy=false) {
    const bom=this.boms.find(b=>b.id===id);
    if(bom)this.openItems[bom.item_id]=true;
    this.draft=bom ? {id, item_id:bom.item_id, base_quantity:bom.base_quantity, base_unit:this.items.find(i=>i.id===bom.item_id)?.base_unit, effective_from:bom.effective_from, is_active:bom.is_active, notes:bom.notes||'',copy,
      lines:bom.lines.map(l=>({item_id:l.item.id,quantity:l.quantity,unit:l.unit,alternatives:l.alternatives.map(a=>a.id)}))}
      : {item_id:this.items.find(i=>i.item_type==='SEMI')?.id,base_quantity:'1',effective_from:InventoryApiPage.today(),is_active:true,notes:'',lines:[]};
    const d=this.draft;
    this.host().innerHTML=`<form id="bomForm" onsubmit="event.preventDefault();BomApiPage.save()">
      <p>${bom?`v${bom.version}${copy?' 기반 새 버전 등록':' 조회·수정'} · 메모만 바꾸면 현재 버전에 저장합니다.`:'신규 BOM 등록'}</p>
      ${bom?`<div style="margin-bottom:0.75rem"><div role="tablist" aria-label="배합·적용 시작일 변경 시 저장 방식" style="display:flex;gap:0.5rem;flex-wrap:wrap"><button type="button" role="tab" aria-selected="true" data-save-mode="new" class="btn btn-primary btn-sm" onclick="BomApiPage.setSaveMode('new')">새 버전으로 저장 (권장)</button><button type="button" role="tab" aria-selected="false" data-save-mode="existing" class="btn btn-secondary btn-sm" ${bom.used?'disabled aria-describedby="bomOverwriteReason"':''} onclick="BomApiPage.setSaveMode('existing')">이 버전에 덮어쓰기</button></div><input type="hidden" name="save_mode" value="new"><p id="bomOverwriteReason" style="font-size:0.8rem;color:var(--text-muted);margin-top:0.4rem">${bom.used?'생산 연결 이력이 있어 덮어쓸 수 없습니다. 기존 생산 기록을 보존하려면 새 버전으로 저장하세요.':'미사용 버전은 확인 후 덮어쓸 수 있습니다. 새 버전 저장 시 활성화 여부를 선택합니다.'}</p></div>`:''}
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
      <label>생산 품목<select class="form-control" name="item_id" ${id?'disabled':''} onchange="BomApiPage.changeItem(this.value)">${this.options(this.items.filter(i=>i.item_type==='SEMI'),d.item_id)}</select></label>
      <label>기준 생산량<input class="form-control" name="base_quantity" type="number" min="0" step="any" required value="${this.esc(d.base_quantity)}"></label>
      <label>단위<select class="form-control" name="base_unit">${this.unitOptions(d.base_unit || this.items.find(i=>i.id===d.item_id)?.base_unit)}</select></label>
      <label>적용 시작일<input class="form-control" name="effective_from" type="date" required value="${this.esc(d.effective_from)}"></label>
      <label>담당자<select class="form-control" name="staff_id">${this.options(this.staff,ProductionApiPage.s.staffId)}</select></label>
      <input type="hidden" name="is_active" value="${d.is_active?'1':'0'}"></div>
      <label>변경 사유·메모<input class="form-control" name="notes" value="${this.esc(d.notes)}"></label>
      <p>구성 원료와 기준 생산량당 소요량을 입력하세요. 대체 원료는 여러 개 선택할 수 있습니다.</p>
      <div class="table-wrapper"><table class="data-table"><thead><tr><th>원료</th><th>소요량</th><th>단위</th><th>대체 원료</th><th></th></tr></thead><tbody id="bomLines"></tbody></table></div>
      <button type="button" class="btn btn-secondary" onclick="BomApiPage.addLine()">원료 추가</button>
      <p id="bomError" role="alert" style="color:var(--color-danger)"></p>
      <button id="bomSave" class="btn btn-primary">저장</button> <button type="button" class="btn btn-secondary" onclick="BomApiPage.list()">목록</button>
      </form>`;
    this.lines();
  },
  setSaveMode(mode) {
    if(mode==='existing' && this.boms.find(b=>b.id===this.draft.id)?.used) return;
    document.querySelector('#bomForm [name=save_mode]').value=mode;
    document.querySelectorAll('#bomForm [data-save-mode]').forEach(button=>{
      const selected=button.dataset.saveMode===mode;
      button.setAttribute('aria-selected',String(selected));
      button.className=`btn ${selected?'btn-primary':'btn-secondary'} btn-sm`;
    });
  },
  unitOptions(unit) { return (['kg','g'].includes(unit)?[unit,unit==='kg'?'g':'kg']:[unit||'kg']).map(u=>`<option>${this.esc(u)}</option>`).join(''); },
  changeItem(value) { const item=this.items.find(i=>String(i.id)===value); this.draft.item_id=item.id; document.querySelector('#bomForm [name=base_unit]').innerHTML=this.unitOptions(item.base_unit); },
  lines() {
    const choices=this.items.filter(i=>i.id!==Number(this.draft.item_id));
    document.getElementById('bomLines').innerHTML=this.draft.lines.map((l,n)=>`<tr data-line="${n}">
      <td><select class="form-control" data-key="item_id" onchange="BomApiPage.component(${n},this.value)">${this.options(choices,l.item_id)}</select></td>
      <td><input class="form-control" data-key="quantity" type="number" min="0" step="any" required value="${this.esc(l.quantity)}"></td>
      <td><select class="form-control" data-key="unit">${this.unitOptions(l.unit)}</select></td>
      <td><select multiple class="form-control" data-key="alternatives" aria-label="대체 원료">${choices.filter(i=>i.id!==l.item_id).map(i=>`<option value="${i.id}" ${l.alternatives.includes(i.id)?'selected':''}>${this.esc(i.item_code)} ${this.esc(i.name)}</option>`).join('')}</select></td>
      <td><button type="button" class="btn btn-danger btn-sm" onclick="BomApiPage.dropLine(${n})">제거</button></td></tr>`).join('');
  },
  readLines() { this.draft.lines=[...document.querySelectorAll('#bomLines tr')].map(row=>({item_id:Number(row.querySelector('[data-key=item_id]').value),quantity:row.querySelector('[data-key=quantity]').value,unit:row.querySelector('[data-key=unit]').value,alternatives:[...row.querySelector('[data-key=alternatives]').selectedOptions].map(o=>Number(o.value))})); },
  addLine() { this.readLines(); const item=this.items.find(i=>i.id!==Number(this.draft.item_id)); if(item) this.draft.lines.push({item_id:item.id,quantity:'',unit:item.base_unit,alternatives:[]}); this.lines(); },
  dropLine(n) { this.readLines(); this.draft.lines.splice(n,1); this.lines(); },
  component(n,value) { this.readLines(); const item=this.items.find(i=>String(i.id)===value); this.draft.lines[n].unit=item.base_unit; this.draft.lines[n].alternatives=this.draft.lines[n].alternatives.filter(id=>id!==item.id); this.lines(); },
  recipeKey(data) {
    const unit=id=>this.items.find(i=>i.id===Number(id))?.base_unit;
    return JSON.stringify([MassUnits.convert(data.base_quantity,data.base_unit,unit(data.item_id)),data.effective_from,
      data.lines.map(l=>[Number(l.item_id),MassUnits.convert(l.quantity,l.unit,unit(l.item_id)),[...l.alternatives].sort((a,b)=>a-b)]).sort((a,b)=>a[0]-b[0])]);
  },
  chooseActivation() {
    return new Promise(resolve=>{
      const dialog=document.createElement('dialog');
      dialog.id='bomActivationDialog';
      dialog.style.cssText='position:fixed;inset:0;margin:auto;max-width:460px;width:calc(100vw - 3rem);max-height:calc(100vh - 3rem);border:1px solid var(--border-subtle);border-radius:12px;padding:1.25rem;background:var(--bg-surface,#fff);color:var(--text-primary);';
      dialog.innerHTML=`<style>#bomActivationDialog::backdrop{background:#0007}</style><form method="dialog"><h3 id="bomActivationTitle">새 버전을 활성화할까요?</h3><p style="margin:0.75rem 0 1rem">활성화하면 새 생산지시부터 이 버전을 사용합니다. 기존 생산지시는 원래 배합을 유지합니다.</p><div style="display:flex;gap:0.5rem;flex-wrap:wrap"><button value="activate" class="btn btn-primary" autofocus>저장 후 활성화</button><button value="inactive" class="btn btn-secondary">비활성으로 저장</button><button value="cancel" class="btn btn-secondary">취소</button></div></form>`;
      dialog.setAttribute('aria-labelledby','bomActivationTitle');
      dialog.addEventListener('close',()=>{
        const choice=dialog.returnValue;
        dialog.remove();resolve(choice==='activate'?true:choice==='inactive'?false:null);
      },{once:true});
      document.body.append(dialog);dialog.showModal();
    });
  },
  async save() {
    const button=document.getElementById('bomSave'); if(button.disabled) return;
    this.readLines(); const d=this.draft, form=Object.fromEntries(new FormData(document.getElementById('bomForm')));
    button.disabled=true;
    try {
      const payload={...form,item_id:Number(d.item_id),staff_id:Number(form.staff_id),is_active:form.is_active==='1',lines:d.lines,new_version:form.save_mode==='new',overwrite:form.save_mode==='existing',reason:form.notes};
      delete payload.save_mode;
      let createsVersion=!d.id;
      if(d.id) {
        const old=this.boms.find(b=>b.id===d.id);
        const previous={...old,base_unit:this.items.find(i=>i.id===old.item_id)?.base_unit,lines:old.lines.map(l=>({item_id:l.item.id,quantity:l.quantity,unit:l.unit,alternatives:l.alternatives.map(a=>a.id)}))};
        const changed=this.recipeKey(payload)!==this.recipeKey(previous);
        if(!changed && payload.is_active===old.is_active && form.notes.trim()===(old.notes||'').trim()) {
          document.getElementById('bomError').textContent='변경된 내용이 없습니다.';
          App.showToast('info','BOM 저장','변경된 내용이 없습니다.'); return;
        }
        createsVersion=changed&&payload.new_version;
        if(changed && !payload.new_version && old.used) throw new Error('생산 연결 이력이 있는 버전은 덮어쓸 수 없습니다. 새 버전으로 저장하세요.');
        if(changed && !payload.new_version && !old.used && !confirm(`v${old.version}의 기존 내용을 변경합니다. 이력을 남기려면 새 버전 저장을 권장합니다. 기존 버전에 저장할까요?`)) return;
        if(!changed) {
          const metadata={staff_id:payload.staff_id,is_active:payload.is_active,notes:payload.notes,reason:payload.reason};
          Object.keys(payload).forEach(key=>delete payload[key]); Object.assign(payload,metadata);
        }
      }
      if(createsVersion) {
        const active=await this.chooseActivation();
        if(active===null) return;
        payload.is_active=active;
      }
      const result=await this.request(`/boms/${d.id?d.id+'/':''}`,d.id?'PATCH':'POST',payload);
      App.showToast('success','BOM 저장',`v${result.version} 저장 완료${createsVersion?(result.is_active?' · 활성화됨':' · 비활성'):''}`);
      this.openItems[result.item_id]=true;
      this.query=''; this.revealItemId=result.item_id;
      await this.open();
      if(ProductionApiPage.s.creating) ProductionApiPage.renderCreate();
    } catch(error) { const target=document.getElementById('bomError'); if(target) target.textContent=error.message; }
    finally { button.disabled=false; }
  },
  async activate(id,button) {
    const bom=this.boms.find(b=>b.id===id);
    if(button.disabled) return;
    const active=!bom.is_active;
    const future=active && bom.effective_from>InventoryApiPage.today()?` 적용 시작일(${bom.effective_from})이 오늘 이후라 그 전까지는 새 생산계획을 등록할 수 없습니다.`:'';
    if(!confirm(active?`이 품목의 활성 BOM을 v${bom.version}으로 바꿀까요? 기존 활성 버전은 비활성으로 전환되며, 기존 생산지시는 원래 배합을 유지합니다.${future}`:`v${bom.version}을 비활성화할까요? 이 품목에 활성 BOM이 없어져 새 생산계획을 등록할 수 없게 됩니다. 연결된 생산지시는 기존 배합을 유지합니다.`)) return;
    button.disabled=true;
    try {
      await this.request(`/boms/${id}/`,'PATCH',{staff_id:Number(ProductionApiPage.s.staffId||this.staff[0]?.id),is_active:active});
      this.openItems[bom.item_id]=true;
      await this.open();
      if(ProductionApiPage.s.creating) ProductionApiPage.renderCreate();
      App.showToast('success','BOM 상태',`v${bom.version}을 ${active?'활성화':'비활성화'}했습니다.`);
    } catch(error) {this.error(error);}
    finally {button.disabled=false;}
  },
  async remove(id) {
    const bom=this.boms.find(b=>b.id===id);
    if(bom.used) {this.error(new Error('생산 연결 이력이 있는 BOM은 기존 기록 보존을 위해 삭제할 수 없습니다.'));return;}
    if(!confirm('이 BOM을 삭제할까요?')) return;
    try {
      const staffId=ProductionApiPage.s.staffId || this.staff[0]?.id;
      await this.request(`/boms/${id}/delete/`,'POST',{staff_id:Number(staffId)});
      await this.open();
    } catch(error) {this.error(error);}
  },
};
