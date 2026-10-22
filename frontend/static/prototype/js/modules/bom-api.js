// BOM authoring uses the existing versioned recipe tables and production API.
const BomApiPage = {
  items: [], boms: [], staff: [], draft: null,
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
      const [items, boms, staff] = await Promise.all([
        this.request('/items/'), this.request('/boms/?include_inactive=1'), this.request('/staff/'),
      ]);
      this.items=items.results; this.boms=boms.results; this.staff=staff.results;
      this.list();
    } catch (error) { this.error(error); }
  },
  host() { return document.querySelector('#modalContainer .modal-body'); },
  error(error) { App.showToast('error','BOM 관리',error.message); },
  list() {
    const itemName = id => this.items.find(i=>i.id===id)?.name || id;
    this.host().innerHTML = `<div style="display:flex;justify-content:space-between"><p>생산에 연결된 배합은 새 버전으로 저장됩니다. 사용한 BOM 삭제는 사용 중지로 처리됩니다.</p><button class="btn btn-primary" onclick="BomApiPage.edit()">새 BOM 등록</button></div>
      <div class="table-wrapper"><table class="data-table" id="bomList"><thead><tr><th>품목</th><th>버전</th><th>적용 시작일</th><th>상태</th><th>원료 수</th><th>관리</th></tr></thead><tbody>
      ${this.boms.map(b=>`<tr><td>${this.esc(itemName(b.item_id))}</td><td>v${b.version}</td><td>${this.esc(b.effective_from)}</td><td>${b.is_active?'사용':'중지'} · ${b.used?'생산 연결됨':'미사용'}</td><td>${b.lines.length}</td><td><button class="btn btn-secondary btn-sm" onclick="BomApiPage.edit(${b.id})">조회·수정</button> <button class="btn btn-secondary btn-sm" onclick="BomApiPage.edit(${b.id},true)">새 버전</button> <button class="btn btn-danger btn-sm" onclick="BomApiPage.remove(${b.id})">${b.used?'사용 중지':'삭제'}</button></td></tr>`).join('') || '<tr><td colspan="6">등록된 BOM이 없습니다.</td></tr>'}</tbody></table></div>`;
  },
  options(rows, selected) { return rows.map(i=>`<option value="${i.id}" ${String(i.id)===String(selected)?'selected':''}>${this.esc(i.item_code || i.staff_code)} ${this.esc(i.name)}</option>`).join(''); },
  edit(id, copy=false) {
    const bom=this.boms.find(b=>b.id===id);
    this.draft=bom ? {id, item_id:bom.item_id, base_quantity:bom.base_quantity, base_unit:this.items.find(i=>i.id===bom.item_id)?.base_unit, effective_from:bom.effective_from, is_active:bom.is_active, notes:bom.notes||'', new_version:copy||bom.used,
      lines:bom.lines.map(l=>({item_id:l.item.id,quantity:l.quantity,unit:l.unit,alternatives:l.alternatives.map(a=>a.id)}))}
      : {item_id:this.items.find(i=>i.item_type==='SEMI')?.id,base_quantity:'1',effective_from:InventoryApiPage.today(),is_active:true,notes:'',lines:[]};
    const d=this.draft;
    this.host().innerHTML=`<form id="bomForm" onsubmit="event.preventDefault();BomApiPage.save()">
      <p>${bom?`v${bom.version} ${d.new_version?'→ 새 버전으로 저장':'수정'}`:'신규 BOM 등록'}</p>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
      <label>생산 품목<select class="form-control" name="item_id" ${id?'disabled':''} onchange="BomApiPage.changeItem(this.value)">${this.options(this.items.filter(i=>i.item_type==='SEMI'),d.item_id)}</select></label>
      <label>기준 생산량<input class="form-control" name="base_quantity" type="number" min="0" step="any" required value="${this.esc(d.base_quantity)}"></label>
      <label>단위<select class="form-control" name="base_unit">${this.unitOptions(d.base_unit || this.items.find(i=>i.id===d.item_id)?.base_unit)}</select></label>
      <label>적용 시작일<input class="form-control" name="effective_from" type="date" required value="${this.esc(d.effective_from)}"></label>
      <label>담당자<select class="form-control" name="staff_id">${this.options(this.staff,ProductionApiPage.s.staffId)}</select></label>
      <label>상태<select class="form-control" name="is_active"><option value="1">사용</option><option value="0" ${!d.is_active?'selected':''}>중지</option></select></label></div>
      <label>변경 사유·메모<input class="form-control" name="notes" value="${this.esc(d.notes)}"></label>
      <p>구성 원료와 기준 생산량당 소요량을 입력하세요. 대체 원료는 여러 개 선택할 수 있습니다.</p>
      <div class="table-wrapper"><table class="data-table"><thead><tr><th>원료</th><th>소요량</th><th>단위</th><th>대체 원료</th><th></th></tr></thead><tbody id="bomLines"></tbody></table></div>
      <button type="button" class="btn btn-secondary" onclick="BomApiPage.addLine()">원료 추가</button>
      <p id="bomError" role="alert" style="color:var(--color-danger)"></p>
      <button id="bomSave" class="btn btn-primary">${d.new_version?'새 버전 저장':'저장'}</button> <button type="button" class="btn btn-secondary" onclick="BomApiPage.list()">목록</button>
      </form>`;
    this.lines();
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
  async save() {
    const button=document.getElementById('bomSave'); if(button.disabled) return;
    this.readLines(); const d=this.draft, form=Object.fromEntries(new FormData(document.getElementById('bomForm')));
    button.disabled=true;
    try {
      const result=await this.request(`/boms/${d.id?d.id+'/':''}`,d.id?'PATCH':'POST',{...form,item_id:Number(d.item_id),staff_id:Number(form.staff_id),is_active:form.is_active==='1',lines:d.lines,new_version:!!d.new_version,reason:form.notes});
      App.showToast('success','BOM 저장',`v${result.version} 저장 완료`);
      await this.open();
      if(ProductionApiPage.s.creating) ProductionApiPage.renderCreate();
    } catch(error) { const target=document.getElementById('bomError'); if(target) target.textContent=error.message; }
    finally { button.disabled=false; }
  },
  async remove(id) {
    const bom=this.boms.find(b=>b.id===id);
    if(!confirm(bom.used?'생산에 연결된 BOM입니다. 기존 기록은 보존하고 신규 계획에서 사용하지 않도록 중지할까요?':'이 BOM을 삭제할까요?')) return;
    try {
      const staffId=ProductionApiPage.s.staffId || this.staff[0]?.id;
      await this.request(`/boms/${id}/delete/`,'POST',{staff_id:Number(staffId)});
      await this.open();
    } catch(error) {this.error(error);}
  },
};
