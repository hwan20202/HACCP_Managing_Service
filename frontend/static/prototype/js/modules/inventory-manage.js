const InventoryManage = {
  items:[], staff:[], importRows:[], preview:null,
  esc(value) { return InventoryApiPage.esc(value); },
  request(...args) {return BomApiPage.request(...args);},
  host() {return document.querySelector('#modalContainer .modal-body');},
  async open(kind) {
    this.kind=kind; this.preview=null;
    App.showModal(kind==='import'?'입고 일괄 업로드':'품목 삭제','<p>불러오는 중…</p>');
    document.getElementById('modalContainer').classList.add('inventory-detail-modal');
    try {
      const [staff,items]=await Promise.all([this.request('/staff/'),this.request('/items/?active=all')]);
      this.staff=staff.results;this.items=items.results;
      this.host().innerHTML=`<label>담당자<select id="manageStaff" class="form-control">${this.staff.map(s=>`<option value="${s.id}">${this.esc(s.name)}</option>`).join('')}</select></label><div id="manageContent"></div><p id="manageError" role="alert" style="color:var(--color-danger)"></p>`;
      kind==='import'?this.importForm():this.removeForm();
    } catch(error) {this.error(error);}
  },
  error(error) {const host=document.getElementById('manageError'); if(host) host.textContent=error.message;else App.showToast('error','처리 실패',error.message);},
  importForm() {
    this.importRows=[];
    document.getElementById('manageContent').innerHTML=`<p>엑셀에서 CSV UTF-8로 저장한 입고 내역을 업로드하세요. 최대 500건이며 오류가 있으면 전체를 저장하지 않습니다.</p>
      <p>필수: item_code(품목코드), supplier_code(공급처코드), received_date(입고일), quantity(수량), unit(단위), expiration_status(KNOWN/NONE), expiration_date(소비기한 있음일 때).</p>
      <p>선택: judgment(PASS/FAIL, 비우면 적합), ea_count(참고 개수), supplier_lot_number. 날짜는 YYYY-MM-DD입니다.</p>
      <button class="btn btn-secondary" onclick="InventoryManage.template()">CSV 양식 다운로드</button>
      <input id="receiptCsv" type="file" accept=".csv,text/csv" class="form-control" onchange="InventoryManage.readFile(this.files[0])">
      <p id="importStatus"></p><button id="importPreview" class="btn btn-secondary" onclick="InventoryManage.previewImport()" disabled>검증·미리보기</button>
      <button id="importSave" class="btn btn-primary" onclick="InventoryManage.saveImport()" disabled>확인한 입고 일괄 등록</button><div id="importResult"></div>`;
  },
  template() {
    const text='\uFEFFitem_code,supplier_code,received_date,quantity,unit,expiration_status,expiration_date,judgment,ea_count,supplier_lot_number\r\n';
    const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='receipt-import.csv';link.click();URL.revokeObjectURL(url);
  },
  parseCsv(text) {
    const rows=[];let row=[],cell='',quoted=false;
    text=text.replace(/^\uFEFF/,'');
    for(let i=0;i<text.length;i++) {
      const c=text[i];
      if(c==='"') {if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(quoted||!cell) quoted=!quoted;else throw new Error('CSV 따옴표 형식을 확인하세요.');}
      else if(!quoted&&(c===','||c==='\n'||c==='\r')) {row.push(cell);cell='';if(c!==','){if(c==='\r'&&text[i+1]==='\n')i++;if(row.some(v=>v.trim()))rows.push(row);row=[];}}
      else cell+=c;
    }
    if(quoted) throw new Error('CSV 따옴표가 닫히지 않았습니다.');
    row.push(cell);if(row.some(v=>v.trim()))rows.push(row);
    const headers=rows.shift()?.map(h=>h.trim());
    if(!headers || new Set(headers).size!==headers.length)throw new Error('CSV 헤더를 확인하세요.');
    for(const name of ['item_code','supplier_code','received_date','quantity'])if(!headers.includes(name))throw new Error(`${name} 열이 필요합니다.`);
    return rows.map((values,i)=>{if(values.length!==headers.length)throw new Error(`${i+2}행 열 수를 확인하세요.`);return Object.fromEntries(headers.map((h,n)=>[h,values[n].trim()]));});
  },
  async readFile(file) {
    this.preview=null;document.getElementById('importSave').disabled=true;
    document.getElementById('importPreview').disabled=true;
    try {
      if(!file)return;
      if(file.size>2*1024*1024)throw new Error('CSV 파일은 2MB 이하여야 합니다.');
      this.importRows=this.parseCsv(await file.text());this.importKey=crypto.randomUUID();
      if(!this.importRows.length||this.importRows.length>500)throw new Error('입고 내역을 1~500건 입력하세요.');
      document.getElementById('importStatus').textContent=`${this.importRows.length}건 읽음`;
      document.getElementById('importPreview').disabled=false;
    }catch(error){this.error(error);}
  },
  async previewImport() {
    const button=document.getElementById('importPreview');button.disabled=true;
    this.preview=null;document.getElementById('importSave').disabled=true;
    try {
      const payload={rows:this.importRows,staff_id:Number(document.getElementById('manageStaff').value),idempotency_key:this.importKey};
      const result=await this.request('/receipts/import/','POST',{...payload,dry_run:true});
      this.preview=JSON.parse(JSON.stringify(payload));
      document.getElementById('importResult').innerHTML=`<p>${result.count}건 검증 완료. 아직 저장하지 않았습니다.</p><div class="table-wrapper"><table class="data-table"><thead><tr><th>품목</th><th>입고일</th><th>수량</th><th>소비기한</th><th>판정</th></tr></thead><tbody>${result.results.map(r=>`<tr><td>${this.esc(r.item.name)}</td><td>${this.esc(r.received_date)}</td><td>${this.esc(r.quantity)} ${this.esc(r.unit)}</td><td>${this.esc(r.expiration_date||'없음')}</td><td>${this.esc(r.lot_status)}</td></tr>`).join('')}</tbody></table></div>`;
      document.getElementById('importSave').disabled=false;
    }catch(error){this.error(error);}finally{button.disabled=false;}
  },
  async saveImport() {
    const button=document.getElementById('importSave');if(button.disabled||!this.preview)return;
    button.disabled=true;
    try {
      const result=await this.request('/receipts/import/','POST',{...this.preview,dry_run:false});
      this.preview=null;App.showToast('success','입고 업로드',`${result.count}건 등록 완료`);
      App.closeModal();InventoryApiPage.load();
    }catch(error){this.error(error);button.disabled=false;}
  },
  removeForm() {
    document.getElementById('manageContent').innerHTML=`<p>생산·BOM·보류·결재 등 다른 업무에 사용되지 않은 품목만 삭제할 수 있습니다. 삭제 시 해당 품목의 입고·수불·연결 문서도 제거됩니다.</p>
      <label><input type="checkbox" onchange="document.querySelectorAll('[data-remove-item]').forEach(c=>c.checked=this.checked)"> 전체 선택</label>
      <div class="table-wrapper" style="max-height:350px;overflow:auto"><table class="data-table"><thead><tr><th>선택</th><th>코드</th><th>품목</th><th>상태</th></tr></thead><tbody>${this.items.map(i=>`<tr><td><input type="checkbox" data-remove-item="${i.id}"></td><td>${this.esc(i.item_code)}</td><td>${this.esc(i.name)}</td><td>${i.is_active?'사용':'중지'}</td></tr>`).join('')}</tbody></table></div>
      <button class="btn btn-secondary" onclick="InventoryManage.previewRemoval()">삭제 대상·이력 확인</button><div id="removePreview"></div>`;
  },
  async previewRemoval() {
    this.preview=null;
    try {
      const payload={item_ids:[...document.querySelectorAll('[data-remove-item]:checked')].map(e=>Number(e.dataset.removeItem)),staff_id:Number(document.getElementById('manageStaff').value)};
      const result=await this.request('/items/delete/','POST',{...payload,dry_run:true});
      this.preview={...payload,item_ids:result.removable.map(i=>i.id)};
      document.getElementById('removePreview').innerHTML=`<p>삭제 가능 ${result.removable.length}건 · 삭제 불가 ${result.blocked.length}건</p>${result.blocked.map(i=>`<p>${this.esc(i.name||i.id)}: ${this.esc(i.reason)}</p>`).join('')}
        <ul>${result.removable.map(i=>`<li>${this.esc(i.item_code)} ${this.esc(i.name)}: LOT ${i.lots}, 입고 ${i.receipts}, 수불 ${i.movements}, 문서 ${i.documents}건 삭제</li>`).join('')}</ul>
        <button id="removeSave" class="btn btn-danger" ${result.removable.length?'':'disabled'} onclick="InventoryManage.remove()">삭제 가능한 품목과 이력 영구 삭제</button>`;
    }catch(error){this.error(error);}
  },
  async remove() {
    if(!this.preview?.item_ids.length||!confirm('미리보기에 표시된 품목과 입고·수불·문서 이력을 영구 삭제합니다. 계속할까요?'))return;
    const button=document.getElementById('removeSave');if(button.disabled)return;button.disabled=true;
    try {
      const result=await this.request('/items/delete/','POST',{...this.preview,dry_run:false,confirmation:'DELETE_UNUSED_ITEMS'});
      App.showToast('success','품목 삭제',`${result.removable.length}건 삭제 완료`);App.closeModal();InventoryApiPage.load();
    }catch(error){this.error(error);button.disabled=false;}
  },
};
