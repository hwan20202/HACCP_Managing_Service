// =============================================
// 제조배치 (생산) — /api/v1/inventory/batches/ 연결 화면
// (docs/history/planning/inventory-frontend.md: 시제품 틀·디자인은 그대로, 데이터는 생산 API 로)
//
// 흐름: 반제품 제조배치 생성 → 시작(CCP 일지 생성) → 원료 LOT 선택·투입 → 산출 등록 → 완료
//       → 재고·수불 확인. 모든 기록은 생산 API 로만 (SQL 직접 입력 없음)
// - 생산 시작 때 수불이 문서 앱 require_for_batch 를 부른다. 이 화면은 문서 API
//   (/api/v1/batches/<id>/documents) 로 CCP 일지가 실제로 연결됐는지 보여 준다
// - 한 배치의 산출 LOT 은 하나 (0006). 산출을 나눠 입력해도 같은 LOT 에 더해진다
// - 수량은 API 의 문자열을 그대로 표시 (계산하지 않음). 요청 키는 화면 입력마다 하나
// =============================================

const ProductionApiPage = {
  API: '/api/v1/inventory',
  DOC_API: '/api/v1',

  STATUS: {
    PLANNED: ['계획', 'badge-neutral'],
    IN_PROGRESS: ['진행', 'badge-info'],
    COMPLETED: ['완료', 'badge-success'],
    CANCELLED: ['취소', 'badge-danger'],
  },
  DOC_STATUS: {
    draft: ['작성중', 'badge-neutral'], completed: ['작성완료', 'badge-info'], submitted: ['결재중', 'badge-warning'],
    approved: ['승인', 'badge-success'], rejected: ['반려', 'badge-danger'], correcting: ['정정 중', 'badge-warning'],
  },
  // 문서 쪽 규칙(doc_requirements.rules.CCP_PROCESSES)의 제조 배치 기본값 — 안내용
  EXPECTED_CCP: ['1P', '2B', '3P'],

  s: {
    staffId: '',
    statusFilter: 'ACTIVE',
    batchId: null,
    creating: true,
    detailTab: 'work',
    use: { itemId: '', quantity: '', lotId: '', key: '' },
    output: { quantity: '', key: '' },
  },
  staff: [],
  semiItems: [],
  inputItems: [],
  detail: null,
  docs: null,
  docsError: '',
  trace: null,
  busy: false,
  bulkUse: null,
  holdForm: null,
  printBatchIds: [],
  printSelecting: false,
  listBatches: [],

  // ---------- 공통 ----------
  today() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  },
  esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },
  key() {
    return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  },
  query(params) {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) q.append(k, v); });
    return q.toString();
  },
  csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  },
  async request(method, url, body) {
    const response = await fetch(url, {
      method,
      headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf() } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    });
    let data = {};
    try { data = await response.json(); } catch (e) { /* not JSON */ }
    if (!response.ok) {
      const err = data.error || data;
      const error = new Error(err.message || `요청 실패 (${response.status})`);
      error.code = err.code;
      throw error;
    }
    return data;
  },
  get(path, params = {}) { return this.request('GET', `${this.API}${path}?${this.query(params)}`); },
  post(path, body) { return this.request('POST', `${this.API}${path}`, body); },
  badge([label, cls]) { return `<span class="badge ${cls}">${this.esc(label)}</span>`; },
  toast(type, title, msg) { if (typeof App !== 'undefined' && App.showToast) App.showToast(type, title, msg); },
  field(label, html) {
    return `<label style="display:flex;flex-direction:column;gap:0.2rem;font-size:0.72rem;color:var(--text-muted);font-weight:600;">${label}${html}</label>`;
  },
  saveStaff(id) {
    this.s.staffId = id;
    try { sessionStorage.setItem('prodApi.staffId', id); } catch (e) { /* storage off */ }
    const actor=document.getElementById('prodHoldActor');
    if(actor) actor.textContent=this.staff.find(s=>String(s.id)===String(id))?.name||'상단에서 담당자를 선택하세요.';
  },

  // ---------- 화면 틀 ----------
  render() {
    if (!this.s.staffId) {
      try { this.s.staffId = sessionStorage.getItem('prodApi.staffId') || ''; } catch (e) { /* storage off */ }
    }
    // 문서 쪽 화면에서 이 배치로 들어올 때(P11 S5 r2): TempEntry.open('production-batches', {productionBatchId, tab})
    const intent = window.TempEntry && TempEntry.intent && TempEntry.intent.productionBatchId ? TempEntry.takeIntent() : null;
    if (intent) {
      this.s.creating = false;
      this.s.batchId = Number(intent.productionBatchId);
      this.s.detailTab = intent.tab || 'work';
    }
    setTimeout(() => this.init(), 0);
    return `
    <style>
      #prodApiPage .prod-layout { display:grid;grid-template-columns:minmax(240px,320px) minmax(0,1fr);gap:0.75rem;align-items:start; }
      #prodApiPage .prod-layout.creating { grid-template-columns:minmax(0,1fr); }
      #prodApiPage .prod-layout.creating > .card { display:none; }
      #prodApiPage .prod-plan-grid { display:grid;grid-template-columns:minmax(240px,0.8fr) minmax(0,1.2fr);gap:1rem; }
      #prodApiPage .prod-plan-fields { display:flex;flex-direction:column;gap:0.8rem; }
      @media(max-width:800px) { #prodApiPage .prod-plan-grid {grid-template-columns:1fr;} }
      #prodApiPage input:not([type=checkbox]):not([type=radio]), #prodApiPage select { min-height:40px; }
      #prodApiPage .btn { display:inline-flex;align-items:center;justify-content:center;gap:0.35rem;box-sizing:border-box;min-height:40px;padding:0.5rem 0.9rem;line-height:1.25;white-space:nowrap; }
      #prodApiPage .btn-sm { min-height:32px;padding:0.35rem 0.65rem; }
      #prodApiPage .tabs .tab-btn.active { background:var(--brand-primary,#007bff);color:#fff;box-shadow:var(--shadow-sm); }
      #prodApiPage .tabs .tab-btn:focus-visible { outline:2px solid var(--brand-primary,#007bff);outline-offset:2px; }
      #prodApiPage .prod-lot-link { color:var(--brand-primary);text-decoration:underline;font-family:monospace;white-space:nowrap; }
      #prodUsages .prod-usage-table td[rowspan] { vertical-align:middle;background:var(--bg-surface); }
      #prodUsages .prod-usage-table .prod-ingredient-start td { border-top:1px solid var(--border-strong); }
      #prodUsages .prod-lot-quantity { text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums; }
      #prodApiPage > .page-header { flex-direction:column;align-items:stretch;gap:1rem; }
      #prodApiPage .prod-toolbar { display:flex;align-items:flex-end;flex-wrap:wrap;gap:0.75rem 1.5rem; }
      #prodApiPage .prod-toolbar-fields { display:flex;align-items:flex-end;flex:1 1 360px;max-width:460px;gap:0.75rem;min-width:0; }
      #prodApiPage .prod-toolbar-fields label { min-width:0; }
      #prodApiPage .prod-toolbar-fields label:first-child { flex:1; }
      #prodApiPage .prod-toolbar-fields label:last-child { flex:0 0 132px; }
      #prodApiPage .prod-toolbar-fields select { height:40px;min-height:40px;width:100%;box-sizing:border-box;padding:0 0.75rem;font-size:0.85rem;line-height:normal; }
      #prodApiPage .prod-toolbar-actions { display:flex;align-items:center;flex-wrap:wrap;gap:0.5rem;margin-left:auto; }
      #prodApiPage .prod-toolbar-actions .btn { height:40px;font-size:0.85rem; }
      @media(max-width:600px) { #prodApiPage .prod-toolbar-actions { margin-left:0; } #prodApiPage .prod-toolbar-fields { flex-basis:100%;max-width:none; } }
      #prodApiPage fieldset:disabled button { opacity:0.45;cursor:not-allowed; }
      #prodHolds { scroll-margin-top:90px; }
      @media (max-width:1000px) { #prodApiPage .prod-layout { grid-template-columns:minmax(0,1fr); } }
    </style>
    <div class="fade-in" id="prodApiPage">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">생산지시 · 실적</h1>
          <p class="page-desc">생산 계획을 등록하고, 시작한 생산의 원료 투입과 생산량을 기록합니다.</p>
        </div>
        <div class="prod-toolbar">
          <div class="prod-toolbar-fields">
            ${this.field('담당자', `<select class="form-control" id="prodStaff" onchange="ProductionApiPage.saveStaff(this.value)"><option value="">불러오는 중…</option></select>`)}
            ${this.field('표시 단위', `<select class="form-control" id="prodDisplayUnit" onchange="ProductionApiPage.setDisplayUnit(this.value)"><option value="">기준 단위</option><option value="kg" ${this.s.bomUnit==='kg'?'selected':''}>kg</option><option value="g" ${this.s.bomUnit==='g'?'selected':''}>g</option></select>`)}
          </div>
          <div class="prod-toolbar-actions">
            <button class="btn btn-secondary" onclick="ProductionApiPage.refresh()">새로고침</button>
            <button class="btn btn-secondary" onclick="BomApiPage.open()">BOM 관리</button>
            <button class="btn btn-secondary" id="prodPrint" onclick="ProductionApiPage.printSelecting?ProductionApiPage.endPrintSelection():ProductionApiPage.beginPrintSelection()">${this.printSelecting?'인쇄 선택 취소':'생산지시 인쇄 / PDF'}</button>
            <button class="btn btn-primary" id="prodNewBtn" onclick="ProductionApiPage.openCreate()">+ 새 생산 계획</button>
          </div>
        </div>
      </div>
      <div class="tabs" style="margin-bottom:0.75rem">
        <button class="tab-btn ${this.s.creating?'active':''}" onclick="ProductionApiPage.openCreate()">생산 계획 등록</button>
        <button class="tab-btn ${!this.s.creating?'active':''}" onclick="ProductionApiPage.showHistory()">생산 목록 · 실적 입력</button>
      </div>
      <div class="prod-layout ${this.s.creating?'creating':''}">
        <div class="card" style="padding:0;">
          <div style="padding:0.6rem 0.8rem;border-bottom:1px solid var(--border-subtle);display:flex;gap:0.5rem;align-items:center;">
            <strong style="flex:1;">배치 목록</strong>
            <select class="form-control" style="width:auto;" onchange="ProductionApiPage.setFilter(this.value)">
              ${[['ACTIVE', '취소 제외'], ['', '전체'], ['PLANNED', '계획'], ['IN_PROGRESS', '진행'], ['COMPLETED', '완료'], ['CANCELLED', '취소']]
                .map(([v, l]) => `<option value="${v}" ${this.s.statusFilter === v ? 'selected' : ''}>${l}</option>`).join('')}
            </select>
          </div>
          <div id="prodList"><div class="empty-state"><p>불러오는 중…</p></div></div>
        </div>
        <div id="prodDetail"><div class="empty-state"><p>배치를 고르거나 새 제조배치를 만드세요.</p></div></div>
      </div>
    </div>`;
  },

  async init() {
    try {
      const [staff, semi, raw, semiInputs] = await Promise.all([
        this.get('/staff/'), this.get('/items/', { item_type: 'SEMI' }),
        this.get('/items/', { item_type: 'RAW' }), this.get('/items/', { item_type: 'SEMI' }),
      ]);
      this.staff = staff.results;
      this.semiItems = semi.results;
      this.inputItems = [...raw.results, ...semiInputs.results];
      if (!this.staff.some((x) => String(x.id) === String(this.s.staffId))) this.saveStaff(this.staff[0] ? String(this.staff[0].id) : '');
      const sel = document.getElementById('prodStaff');
      if (sel) sel.innerHTML = this.staff.map((x) => `<option value="${x.id}" ${String(x.id) === String(this.s.staffId) ? 'selected' : ''}>${this.esc(x.staff_code)} ${this.esc(x.name)}</option>`).join('') || '<option value="">담당자 없음</option>';
      await this.loadList();
      if (this.s.creating) this.renderCreate();
      else if (this.s.batchId) await this.select(this.s.batchId);
    } catch (error) {
      this.showError('prodList', error);
    }
  },

  refresh() {
    this.loadList();
    if (this.s.batchId && !this.s.creating) this.select(this.s.batchId);
  },

  setFilter(value) { this.s.statusFilter = value; this.loadList(); },

  showError(id, error) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = `<div class="empty-state"><h3>조회하지 못했습니다</h3><p>${this.esc(error.message)}</p></div>`;
    this.toast('error', '조회 실패', error.message);
  },

  // ---------- 목록 ----------
  async loadList() {
    const el = () => document.getElementById('prodList');
    try {
      const data = await this.get('/batches/', { status: this.s.statusFilter === 'ACTIVE' ? '' : this.s.statusFilter, exclude_cancelled: this.s.statusFilter === 'ACTIVE' ? '1' : '0', limit: 100 });
      if (!el()) return;
      this.listBatches=data.results;
      this.printBatchIds=this.printBatchIds.filter(id=>data.results.some(b=>b.id===id));
      this.renderBatchList();
    } catch (error) { this.showError('prodList', error); }
  },

  renderBatchList() {
      const el=document.getElementById('prodList');
      if(!el) return;
      const rows=this.listBatches;
      const selection=this.printSelecting?`<div style="padding:0.65rem 0.8rem;border-bottom:1px solid var(--border-subtle)"><label><input type="checkbox" id="prodPrintAll" ${rows.length && rows.every(b=>this.printBatchIds.includes(b.id))?'checked':''} onchange="ProductionApiPage.selectPrintBatches(this.checked)"> 조회 배치 전체 선택</label><div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.5rem"><button class="btn btn-primary btn-sm" id="prodPrintSelected" onclick="ProductionApiPage.printBatch()">선택 인쇄</button><button class="btn btn-secondary btn-sm" id="prodPrintCancel" onclick="ProductionApiPage.endPrintSelection()">취소</button></div></div>`:'';
      el.innerHTML = selection + (rows.length?rows.map((b) => `
        <div class="prod-batch-row" data-batch="${b.id}" onclick="ProductionApiPage.select(${b.id})"
             style="padding:0.55rem 0.8rem;border-bottom:1px solid var(--border-subtle);cursor:pointer;${b.id === this.s.batchId && !this.s.creating ? 'background:var(--bg-elevated, #eef3ff);' : ''}">
          <div style="display:flex;justify-content:space-between;gap:0.5rem;">
            <span style="font-family:monospace;color:var(--brand-primary);font-weight:700;">${this.printSelecting?`<input type="checkbox" data-print-batch="${b.id}" aria-label="${this.esc(b.batch_number)} 인쇄 선택" ${this.printBatchIds.includes(b.id)?'checked':''} onclick="event.stopPropagation()" onchange="ProductionApiPage.selectPrintBatch(${b.id},this.checked)"> `:''}${this.esc(b.batch_number)}</span>
            <span>${b.active_hold_count ? '<span class="badge badge-danger">보류 중</span> ' : ''}${this.badge(this.STATUS[b.status] || [b.status, 'badge-neutral'])}</span>
          </div>
          <div style="font-size:0.75rem;color:var(--text-muted);">${this.esc(b.item.name)} · 제조일 ${this.esc(b.manufactured_date || '미정')}</div>
        </div>`).join(''):'<div class="empty-state"><p>배치가 없습니다.</p></div>');
      this.updatePrintSelection();
  },

  // ---------- 생성 ----------
  openCreate() {
    this.printSelecting=false;
    this.printBatchIds=[];
    this.renderBatchList();
    this.s.creating = true;
    this.s.draft = {itemId: '', quantity: '', date:this.today(), notes:''};
    this.s.createKey = this.key();
    this.renderCreate();
  },

  updateLayout() {
    document.querySelector('#prodApiPage .prod-layout')?.classList.toggle('creating',this.s.creating);
    document.querySelectorAll('#prodApiPage > .tabs .tab-btn').forEach((el,i)=>el.classList.toggle('active',i===0?this.s.creating:!this.s.creating));
  },

  showHistory() {
    this.s.creating=false;
    this.updateLayout();
    if(this.s.batchId) this.select(this.s.batchId);
    else document.getElementById('prodDetail').innerHTML='<div class="empty-state"><p>왼쪽 생산 목록에서 실적을 입력할 생산을 선택하세요.</p></div>';
  },

  renderCreate() {
    const el=document.getElementById('prodDetail');
    if(!el) return;
    this.updateLayout();
    const d=this.s.draft || (this.s.draft={itemId:'',quantity:'',date:this.today(),notes:''});
    el.innerHTML=`<div id="prodCreate" class="prod-plan-grid">
      <div class="card"><div class="card-header"><div class="card-title">생산 계획</div></div>
        <div class="prod-plan-fields">
        ${this.field('생산 품목',`<select class="form-control" name="item_id" onchange="ProductionApiPage.updatePreview()"><option value="">품목을 선택하세요</option>${this.semiItems.map(i=>`<option value="${i.id}" ${String(i.id)===d.itemId?'selected':''}>${this.esc(i.item_code)} ${this.esc(i.name)} (${this.esc(i.base_unit)})</option>`).join('')}</select>`)}
        ${this.field('계획일',`<input type="date" class="form-control" name="planned_date" value="${this.esc(d.date)}" onchange="ProductionApiPage.updatePreview()">`)}
        ${this.field('계획 수량',`<input type="number" min="0" step="any" class="form-control" name="planned_quantity" value="${this.esc(d.quantity)}" oninput="ProductionApiPage.updatePreview()">`)}
        ${this.field('입력 단위', `<select class="form-control" name="plan_unit" onchange="ProductionApiPage.updatePreview()"><option value="kg" ${d.unit!=='g'?'selected':''}>kg</option><option value="g" ${d.unit==='g'?'selected':''}>g</option></select>`)}
        ${this.field('메모 (선택)',`<input class="form-control" name="notes" maxlength="200" value="${this.esc(d.notes)}" oninput="ProductionApiPage.s.draft.notes=this.value">`)}
        <p style="font-size:0.8rem;color:var(--text-muted)">계획 등록 시 재고는 차감되지 않습니다. 생산 시작 후 실제 사용량을 확인해 투입합니다.</p>
        <button class="btn btn-primary" id="prodCreateSubmit" onclick="ProductionApiPage.create()">계획 등록</button>
        </div></div>
      <div id="prodPlanPreview"><div class="card"><strong>BOM 소요량 · 가용재고</strong><p>품목과 계획 수량을 입력하면 필요한 원료와 재고를 미리 확인할 수 있습니다.</p></div></div>
    </div>`;
    if(d.itemId && Number(d.quantity)>0) this.updatePreview();
  },

  updatePreview() {
    const form=document.getElementById('prodCreate');
    if(!form) return;
    const v=n=>form.querySelector(`[name="${n}"]`).value;
    const d=this.s.draft={itemId:v('item_id'),quantity:v('planned_quantity'),date:v('planned_date'),notes:v('notes'),unit:v('plan_unit')};
    const serial=this.previewSerial=(this.previewSerial||0)+1;
    clearTimeout(this.previewTimer);
    const host=document.getElementById('prodPlanPreview');
    host.innerHTML='<div class="card"><strong>BOM 소요량 · 가용재고</strong><p>품목과 0보다 큰 계획 수량을 입력하세요.</p></div>';
    if(!d.itemId || !(Number(d.quantity)>0)) return;
    host.innerHTML='<div class="card">소요량을 조회하고 있습니다…</div>';
    this.previewTimer=setTimeout(async()=>{
      try {
        const readiness=await this.get('/batches/preview/',{item_id:d.itemId,quantity:MassUnits.convert(d.quantity,d.unit,this.semiItems.find(i=>String(i.id)===d.itemId).base_unit,true),planned_date:d.date});
        if(serial===this.previewSerial && host===document.getElementById('prodPlanPreview')) host.innerHTML=this.renderReadiness({readiness});
      } catch(error) {
        if(serial===this.previewSerial && host===document.getElementById('prodPlanPreview')) host.innerHTML=`<div class="card" role="alert">${this.esc(error.message)}</div>`;
      }
    },250);
  },

  cancelCreate() {
    this.s.creating = false;
    if (this.s.batchId) this.select(this.s.batchId);
    else document.getElementById('prodDetail').innerHTML = '<div class="empty-state"><p>배치를 고르거나 새 제조배치를 만드세요.</p></div>';
  },

  async create() {
    const form = document.getElementById('prodCreate');
    const v = (n) => form.querySelector(`[name="${n}"]`).value;
    if (!this.s.staffId) return this.toast('error', '담당자', '담당자를 고르세요.');
    if (!v('item_id') || !(Number(v('planned_quantity')) > 0)) return this.toast('error','계획 등록','품목과 0보다 큰 계획 수량을 입력하세요.');
    await this.run('배치 생성', async () => {
      const batch = await this.post('/batches/', {
        item_id: Number(v('item_id')), staff_id: Number(this.s.staffId), process_type: 'MANUFACTURE',
        planned_date: v('planned_date') || null, planned_quantity: MassUnits.convert(v('planned_quantity'),v('plan_unit'),this.semiItems.find(i=>String(i.id)===v('item_id')).base_unit,true), notes: v('notes') || null,
      });
      this.s.creating = false;
      this.toast('success', '배치 생성', `${batch.batch_number} (계획)`);
      await this.loadList();
      await this.select(batch.id);
    });
  },

  // ---------- 상세 ----------
  async select(id) {
    this.bulkUse = null;
    this.s.creating = false;
    this.updateLayout();
    const serial=this.selectSerial=(this.selectSerial||0)+1;
    if (this.s.batchId !== id) {
      this.holdForm = null;
      this.s.batchId = id;
      this.s.use = { itemId: '', quantity: '', lotId: '', key: this.key() };
      this.s.output = { quantity: '', key: this.key() };
      this.lotChoices = null;
      this.useOptionCache = null;
      this.fefo = null;
    }
    document.querySelectorAll('.prod-batch-row').forEach((row) => {
      row.style.background = String(row.dataset.batch) === String(id) ? 'var(--bg-elevated, #eef3ff)' : '';
    });
    try {
      const detail = await this.get(`/batches/${id}/`);
      if(serial!==this.selectSerial) return;
      this.detail = detail;
      if(this.holdForm?.kind==='release' && !detail.holds?.some(h=>h.id===this.holdForm.id && h.is_open)) this.holdForm=null;
      await this.loadDocs();
      if(serial!==this.selectSerial) return;
      this.renderDetail();
      this.loadTrace();
    } catch (error) { this.showError('prodDetail', error); }
  },

  async loadDocs() {
    const batchId=this.detail.id;
    this.docs = null;
    this.docsError = '';
    try {
      const docs=await this.request('GET', `${this.DOC_API}/batches/${batchId}/documents`);
      if(this.detail.id===batchId) this.docs=docs;
    } catch (error) {
      if(this.detail.id===batchId) this.docsError = error.message;
    }
  },

  renderDetail() {
    const el=document.getElementById('prodDetail');
    if(!el || !this.detail || this.s.creating) return;
    const b=this.detail;
    const tab=this.s.detailTab || 'work';
    const hasHoldHistory=(b.holds||[]).length>0;
    el.innerHTML=`${this.renderHead(b)}${b.active_hold_count||hasHoldHistory?this.renderHolds(b):''}
      <div class="tabs" style="margin-bottom:0.75rem">${[['work','생산 진행 · 실적'],['documents','연결 문서'],['trace','재고 · 수불 이력']].map(([v,l])=>`<button class="tab-btn ${tab===v?'active':''}" onclick="ProductionApiPage.detailTab('${v}')">${l}</button>`).join('')}</div>
      ${tab==='documents'?this.renderCcp(b):tab==='trace'?'<div class="card" id="prodTrace">불러오는 중…</div>':`
        ${b.active_hold_count||['PLANNED','IN_PROGRESS'].includes(b.status)?`<div class="card" style="margin-bottom:0.75rem"><strong>${b.active_hold_count?'보류 중입니다. 담당자 확인 후 보류를 해제하면 생산 작업을 진행할 수 있습니다.':b.status==='PLANNED'?'다음 단계: 제조일을 확인하고 생산을 시작하세요.':'원료별 투입량 확인 → 생산량 등록 → 생산 완료'}</strong></div>`:''}
        <fieldset ${b.active_hold_count?'disabled':''} style="border:0;padding:0;margin:0;min-width:0">
        ${b.status==='PLANNED'?this.renderReadiness(b)+this.renderStart(b):''}
        ${b.status!=='PLANNED'?this.renderUsages(b)+this.renderOutputs(b):''}
        ${b.status==='IN_PROGRESS'?this.renderComplete(b):''}</fieldset>
        ${b.status==='IN_PROGRESS' && !b.active_hold_count && !hasHoldHistory?this.renderHolds(b):''}`}`;
    if(tab==='trace') this.loadTrace();
  },

  detailTab(tab) { this.s.detailTab=tab; this.renderDetail(); },

  // ---------- 수동 보류 · 해제 (문서 결재와 별도 처리) ----------
  holdDate(value) { return value ? this.esc(value.replace('T',' ').slice(0,16)) : '-'; },

  renderHolds(b) {
    const holds=b.holds||[], active=holds.filter(h=>h.is_open), form=this.holdForm;
    // Normal planning has no hold controls; keep existing active holds visible for recovery.
    if(!active.length && b.status==='PLANNED') return '';
    if(!active.length && !holds.length && b.status!=='IN_PROGRESS') return '';
    const release=form?.kind==='release';
    const target=release?active.find(h=>h.id===form.id):null;
    const formVisible=form && (!release || target);
    return `${active.length?'<div class="card" style="margin-bottom:0.75rem;border-color:var(--color-danger)">':`<details class="card" id="prodHoldManage" ${formVisible?'open':''} style="margin-top:0.75rem;margin-bottom:0.75rem"><summary style="cursor:pointer;color:var(--text-muted);font-size:0.85rem">${holds.length?`보류·해제 이력 ${holds.length}건`:'보류 관리'}</summary>`}
      <div id="prodHolds" style="${active.length?'':'margin-top:0.75rem;'}">
      <div class="card-header" style="display:flex;justify-content:space-between;gap:0.75rem;align-items:center;flex-wrap:wrap">
        <div class="card-title">제조배치 보류 ${active.length?'<span class="badge badge-danger">보류 중</span>':''}</div>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap">${!active.length && b.status==='IN_PROGRESS' && !form?'<button class="btn btn-secondary btn-sm" id="prodHoldOpen" onclick="ProductionApiPage.openHoldForm()">보류 등록</button>':''}<button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.select(${b.id})">다시 확인</button></div>
      </div>
      ${active.map(h=>`<div style="margin-bottom:0.75rem"><strong style="white-space:pre-wrap;overflow-wrap:anywhere">${this.esc(h.reason)}</strong>
        <div style="font-size:0.8rem;color:var(--text-muted)">${this.holdDate(h.held_at)} · ${this.esc(h.held_by.name)}</div>
        ${!form?`<button class="btn btn-secondary btn-sm" data-release-hold="${h.id}" onclick="ProductionApiPage.openHoldForm(${h.id})">개선조치 확인 · 해제</button>`:''}</div>`).join('')}
      <p style="font-size:0.8rem;color:var(--text-muted)">${active.length?'생산 시작·원료 투입·산출 등록·완료가 제한되며, 산출 LOT도 보류됩니다. ':''}보류·해제는 담당자가 직접 처리하며 문서 결재와 별도로 진행합니다.</p>
      ${formVisible?`<form id="prodHoldForm" onsubmit="event.preventDefault();ProductionApiPage.saveHold()">
        <h3 style="font-size:0.95rem">${release?'개선조치 확인 및 보류 해제':'제조배치 보류 등록'}</h3>
        <label style="display:block">${release?'개선조치 내용 및 해제 사유':'보류 사유'}<textarea class="form-control" name="reason" rows="3" required oninput="ProductionApiPage.holdForm.reason=this.value">${this.esc(form.reason)}</textarea></label>
        ${release?`<label style="display:flex;gap:0.5rem;align-items:flex-start;margin:0.75rem 0"><input type="checkbox" name="confirmed" required ${form.confirmed?'checked':''} onchange="ProductionApiPage.holdForm.confirmed=this.checked">개선조치가 완료되었고 보류를 해제해도 되는지 확인했습니다.</label><p style="font-size:0.8rem">이 배치에서 전파된 산출 LOT 보류도 함께 해제됩니다. 별도로 등록된 LOT 보류는 유지됩니다.</p>`:'<p style="font-size:0.8rem">이 배치와 산출 LOT를 보류합니다. 재고 수량은 변경하지 않습니다.</p>'}
        <p style="font-size:0.8rem">처리 담당자: <span id="prodHoldActor">${this.esc(this.staff.find(s=>String(s.id)===String(this.s.staffId))?.name||'상단에서 담당자를 선택하세요.')}</span></p>
        <div style="display:flex;gap:0.5rem"><button type="submit" class="btn btn-primary" id="prodHoldSave">${release?'보류 해제':'보류 등록'}</button><button type="button" class="btn btn-secondary" onclick="ProductionApiPage.holdForm=null;ProductionApiPage.renderDetail()">닫기</button></div>
      </form>`:''}
      ${holds.length?`<details ${active.length?'':'open'} style="margin-top:0.75rem" id="prodHoldHistory"><summary>보류·해제 이력 ${holds.length}건</summary><div class="table-wrapper"><table class="data-table"><thead><tr><th>상태</th><th>보류 사유</th><th>보류 일시 · 담당자</th><th>해제 내용</th><th>해제 일시 · 담당자</th></tr></thead><tbody>${holds.map(h=>`<tr><td>${h.is_open?'<span class="badge badge-danger">보류 중</span>':this.esc(({RELEASE:'해제',REWORK:'재작업',RETURN:'반품',DISPOSE:'폐기'})[h.disposition]||'처리 완료')}</td><td style="white-space:pre-wrap;overflow-wrap:anywhere">${this.esc(h.reason)}</td><td>${this.holdDate(h.held_at)}<br>${this.esc(h.held_by.name)}</td><td style="white-space:pre-wrap;overflow-wrap:anywhere">${this.esc(h.release_reason||'-')}</td><td>${this.holdDate(h.released_at)}<br>${this.esc(h.released_by?.name||'-')}</td></tr>`).join('')}</tbody></table></div></details>`:''}
    </div>${active.length?'</div>':'</details>'}`;
  },

  openHoldForm(id=null) {
    this.holdForm={kind:id?'release':'create',id,reason:'',confirmed:false};
    this.renderDetail();
    document.querySelector('#prodHoldForm textarea')?.focus();
  },

  async saveHold() {
    const form=this.holdForm, batchId=this.detail.id;
    if(!form) return;
    const reason=form.reason.trim(), release=form.kind==='release';
    if(!reason) return this.toast('error',release?'보류 해제':'보류 등록','사유를 입력하세요.');
    if(release && !form.confirmed) return this.toast('error','보류 해제','개선조치 완료 및 해제 가능 여부를 확인하세요.');
    await this.run(release?'보류 해제':'보류 등록',async()=>{
      await this.post(release?`/holds/${form.id}/release/`:'/holds/',release
        ?{disposition:'RELEASE',reason,staff_id:Number(this.s.staffId)}
        :{batch_id:batchId,source_type:'MANUAL',reason,staff_id:Number(this.s.staffId)});
      this.holdForm=null;
      this.bulkUse=null;
      this.s.use={itemId:'',quantity:'',lotId:'',key:this.key()};
      this.fefo=null;
      this.lotChoices=null;
      this.useOptionCache=null;
      this.toast('success',release?'보류 해제':'보류 등록',release?'담당자 확인 후 보류를 해제했습니다.':'제조배치와 산출 LOT를 보류했습니다.');
      await this.loadList();
      if(this.s.batchId===batchId) await this.select(batchId);
    });
  },

  renderReadiness(b) {
    const r = b.readiness;
    if (!r) return '';
    return `<div class="card" style="margin-bottom:0.75rem;"><strong>계획 원료 · 가용재고</strong>
      <p>${this.esc(r.message)}</p>
      <div class="table-wrapper"><table class="data-table"><thead><tr><th>원료</th><th>필요량</th><th>사용 가능 (대체 포함)</th><th>부족량</th></tr></thead><tbody>
      ${r.lines.map(l => `<tr><td>${this.esc(l.item_code)} ${this.esc(l.name)}</td><td>${this.mass(l.required,l.unit)}</td><td>${l.stock_managed ? this.mass(l.available,l.unit) : '재고 관리 제외'}</td><td>${this.mass(l.shortfall,l.unit)}</td></tr>`).join('')}
      </tbody></table></div><p>조회 시점의 재고입니다. 생산 시작·투입 시 다시 확인하며, 실제 투입할 때 차감합니다.</p></div>`;
  },

  renderHead(b) {
    const steps = ['PLANNED', 'IN_PROGRESS', 'COMPLETED'];
    const at = b.status === 'CANCELLED' ? -1 : steps.indexOf(b.status);
    const stepper = steps.map((st, i) => {
      const done = at >= i;
      return `<span style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.8rem;font-weight:${at === i ? 700 : 500};color:${done ? 'var(--brand-primary)' : 'var(--text-muted)'};">
        <span style="width:1.3rem;height:1.3rem;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:0.7rem;border:1px solid currentColor;${done ? 'background:var(--brand-primary);color:#fff;' : ''}">${i + 1}</span>${this.STATUS[st][0]}</span>`;
    }).join('<span style="color:var(--text-muted);">→</span>');
    const canCancel = b.status === 'PLANNED' || b.status === 'IN_PROGRESS';
    return `
      <div class="card" style="margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;gap:0.75rem;flex-wrap:wrap;align-items:flex-start;">
          <div>
            <div style="font-family:monospace;font-size:1.1rem;font-weight:700;color:var(--brand-primary);" id="prodBatchNumber">${this.esc(b.batch_number)}</div>
            <div style="font-size:0.85rem;">${this.esc(b.item.item_code)} ${this.esc(b.item.name)} · ${this.badge(this.STATUS[b.status] || [b.status, 'badge-neutral'])}</div>
            <div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.2rem;">
              제조일 ${this.esc(b.manufactured_date || '시작 때 정해짐')} · 계획 ${this.esc(b.planned_date || '-')} ${b.planned_quantity ? `/ ${this.esc(b.planned_quantity)} ${this.esc(b.unit)}` : ''}
              · BOM ${b.bom_id ? `v${this.esc(b.bom_version??'—')}` : '없음'} · 담당 ${this.esc(b.staff.name)}
              ${b.cancel_reason ? `<br>취소 사유: ${this.esc(b.cancel_reason)}` : ''}
            </div>
          </div>
          <div style="display:flex;flex-direction:column;gap:0.5rem;align-items:flex-end;">
            <div style="display:flex;gap:0.4rem;align-items:center;">${stepper}</div>
            <button class="btn btn-secondary btn-sm" id="prodPrintCurrent" onclick="ProductionApiPage.printBatch(true)">이 배치 인쇄 / PDF</button>
            ${canCancel ? `<button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.cancelBatch()">배치 취소</button>` : ''}
          </div>
        </div>
      </div>`;
  },

  renderCcp(b) {
    const docs = (this.docs && this.docs.documents) || [];
    let verdict;
    if (this.docsError) {
      verdict = `<span class="badge badge-danger">조회 실패</span> <span style="font-size:0.8rem;">${this.esc(this.docsError)}</span>`;
    } else if (b.status === 'PLANNED') {
      verdict = '<span class="badge badge-neutral">시작 전</span> <span style="font-size:0.8rem;color:var(--text-muted);">생산을 시작하면 문서 앱이 CCP 일지를 만듭니다.</span>';
    } else if (docs.length) {
      const codes = docs.map((d) => d.process_code);
      const missing = this.EXPECTED_CCP.filter((c) => !codes.includes(c));
      verdict = missing.length
        ? `<span class="badge badge-warning">CCP 일지 ${docs.length}건 연결</span> <span style="font-size:0.8rem;">제조 기본 공정 중 없음: ${missing.map((c) => `CCP-${c}`).join(', ')} (문서 쪽 품목 예외일 수 있음)</span>`
        : `<span class="badge badge-success" id="prodCcpOk">CCP 일지 ${docs.length}건 연결됨</span>`;
    } else if (b.status === 'CANCELLED') {
      verdict = '<span class="badge badge-neutral">취소된 배치</span>';
    } else {
      verdict = '<span class="badge badge-danger" id="prodCcpMissing">CCP 일지 없음</span> <span style="font-size:0.8rem;">시작된 배치인데 연결된 CCP 일지가 없습니다. 문서 담당자에게 확인하세요.</span>';
    }
    const docLinks = !!window.TempEntry;  // 문서 화면(temp-entry)이 실린 설정에서만 [열기]·[CCP 대시보드]
    const rows = docs.map((d) => `<tr data-ccp-doc="${this.esc(d.document_id)}">
        <td class="no-wrap">${this.esc(d.type_code)}</td><td>${this.esc(d.process_code || '-')}</td>
        <td>${this.badge(this.DOC_STATUS[d.status] || [d.status, 'badge-neutral'])}</td>
        <td>${this.ccpMeasure(d.summary)}</td><td>${this.ccpDeviation(d.summary)}</td>
        <td style="text-align:right;" class="no-wrap">#${this.esc(d.document_id)}
          ${docLinks ? `<button class="btn btn-secondary btn-sm" data-open-doc="${this.esc(d.document_id)}" onclick="ProductionApiPage.openDoc(${Number(d.document_id)})">열기</button>` : ''}</td></tr>`).join('');
    return `
      <div class="card" style="margin-bottom:0.75rem;" id="prodCcp">
        <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;">
          <div class="card-title">CCP 일지</div>
          <span style="display:flex;gap:0.4rem;">
            ${docs.length && window.TempEntry ? `<button class="btn btn-secondary btn-sm" id="prodCcpDash" onclick="ProductionApiPage.openDashboard()">CCP 대시보드에서 보기</button>` : ''}
            <button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.recheckDocs()">다시 확인</button>
          </span>
        </div>
        <div style="margin-bottom:0.5rem;">${verdict}</div>
        ${docs.length ? `<div class="table-wrapper"><table class="data-table"><thead><tr><th>문서</th><th>공정</th><th>상태</th><th>최근 측정</th><th>이탈 · 개선조치</th><th style="text-align:right;">문서</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}
        <p style="font-size:0.72rem;color:var(--text-muted);margin:0.4rem 0 0;">생산 시작 시 필요한 CCP 일지가 함께 생성됩니다.</p>
      </div>`;
  },

  // P11 S5 r2: 연결 문서 줄의 측정 요약(문서 앱 REQ-A02 summary — 없으면 '-')
  ccpMeasure(m) {
    if (!m) return '<span style="color:var(--text-muted);">-</span>';
    if (!m.row_count) return '<span class="badge badge-warning">▲ 측정 없음</span>';
    const l = m.latest;
    const at = l && l.at ? String(l.at).replace('T', ' ').slice(5, 16) : '시각 없음';
    const v = l && l.verdict ? ` · ${l.verdict === '부적합' ? '<b style="color:var(--danger,#c0392b);">부적합</b>' : this.esc(l.verdict)}` : '';
    return `${this.esc(at)}${l && l.phase ? ` ${this.esc(l.phase)}` : ''}${v} <span style="color:var(--text-muted);">(측정 ${this.esc(m.row_count)})</span>`;
  },
  ccpDeviation(m) {
    if (!m) return '<span style="color:var(--text-muted);">-</span>';
    const parts = [];
    if (m.nonconforming_count) parts.push(`<span class="badge badge-danger">⚠ 이탈 ${this.esc(m.nonconforming_count)}</span>`);
    if (m.no_action) parts.push(`<span class="badge badge-danger">개선조치 없음 ${this.esc(m.no_action)}</span>`);
    if (m.pending) parts.push(`<span class="badge badge-warning">● 확인 대기 ${this.esc(m.pending)}</span>`);
    if (m.checked) parts.push(`<span class="badge badge-success">확인됨 ${this.esc(m.checked)}</span>`);
    return parts.join(' ') || '<span class="badge badge-success">이상 없음</span>';
  },
  // 문서 상세로(문서 앱 화면). [뒤로] = 이 배치의 [연결 문서] 탭
  openDoc(documentId) {
    if (!window.TempEntry) return;
    TempEntry.open('doc-box', { documentId, back: { page: 'production-batches', intent: { productionBatchId: this.detail.id, tab: 'documents' } } });
  },
  // CCP 대시보드(문서 앱) — 제조일을 기준일로, 이 배치 영역을 펼쳐서
  openDashboard() {
    if (!window.TempEntry || !this.detail) return;
    TempEntry.open('ccp-dashboard', { date: this.detail.manufactured_date, focusBatch: this.detail.batch_number });
  },
  // 다른 화면에서 배치 열기(문서 앱이 부름): tab = 'work' | 'documents'
  openBatch(batchId, tab) {
    if (window.TempEntry) { TempEntry.open('production-batches', { productionBatchId: batchId, tab: tab || 'work' }); return; }
    Object.assign(this.s, { creating: false, batchId: Number(batchId), detailTab: tab || 'work' });
    App.navigate('production-batches');
  },

  async recheckDocs() {
    await this.loadDocs();
    this.renderDetail();
    this.loadTrace();
  },

  renderStart(b) {
    return `
      <div class="card" style="margin-bottom:0.75rem;" id="prodStart">
        <div class="card-header"><div class="card-title">생산 시작</div></div>
        <div style="display:flex;gap:0.75rem;align-items:flex-end;flex-wrap:wrap;">
          ${this.field('제조일 (생산 시작일)', `<input type="date" class="form-control" name="manufactured_date" value="${this.esc(b.manufactured_date || this.today())}" max="${this.today()}">`)}
          <button class="btn btn-primary" id="prodStartBtn" onclick="ProductionApiPage.start()">생산 시작</button>
        </div>
        <p style="font-size:0.75rem;color:var(--text-muted);margin:0.5rem 0 0;">산출 LOT 번호와 소비기한은 이 날짜로 정해집니다 (제조일 = 생산 시작일, 소비기한은 품목에 등록된 기간으로 계산).</p>
      </div>`;
  },

  async start() {
    const date = document.querySelector('#prodStart [name="manufactured_date"]').value;
    await this.run('생산 시작', async () => {
      const b = await this.post(`/batches/${this.detail.id}/start/`, { staff_id: Number(this.s.staffId), manufactured_date: date || null });
      this.toast('success', '생산 시작', `${b.batch_number} 진행 — CCP 일지를 확인하세요`);
      await this.loadList();
      await this.select(b.id);
    });
  },

  // ---------- 투입 ----------
  renderUsages(b) {
    const matched=new Set();
    const lotCells=(u,primaryId)=>u?`<td><a class="prod-lot-link" href="#prod-lot-${u.lot_id}" onclick="event.preventDefault();ProductionApiPage.openUsageLot(${u.lot_id})">${this.esc(u.lot_number)}</a></td><td>${u.item.id===primaryId?'기본 원료':`${primaryId?'<span class="badge badge-neutral">대체</span> ':''}${this.esc(u.item.name)}`}</td><td class="prod-lot-quantity">${this.inputMass(u.net_quantity,u.unit)}${u.quantity!==u.net_quantity?'<br><span class="badge badge-neutral">정정 반영</span>':''}</td>`:'<td colspan="3" style="color:var(--text-muted)">—</td>';
    const check = b.bom_check;
    const bom = check ? `
      <div style="font-size:0.78rem;margin:0.5rem 0 0.25rem;"><strong>BOM 기준량</strong> (기준: ${this.esc(check.basis === 'output' ? '산출량' : check.basis === 'plan' ? '계획량' : check.basis)} ${this.esc(check.basis_quantity)})</div>
      <div class="table-wrapper"><table class="data-table prod-usage-table"><thead><tr><th>#</th><th>BOM 원료</th><th style="text-align:right;">기준량</th><th style="text-align:right;">총 투입량</th><th>단위</th><th>투입 LOT</th><th>사용 원료</th><th style="text-align:right;">LOT별 사용량</th><th></th></tr></thead><tbody>
      ${check.lines.map((l) => {
        const usages=b.usages.filter(u=>u.bom_line_id!=null?u.bom_line_id===l.bom_line_id:u.item.id===l.item.id);
        usages.forEach(u=>matched.add(u.id));
        const count=Math.max(1,usages.length);
        return `<tr class="prod-ingredient-start"><td rowspan="${count}">${l.line_no}</td><td rowspan="${count}">${this.esc(l.item.item_code)} ${this.esc(l.item.name)}</td><td rowspan="${count}" style="text-align:right;">${this.esc(MassUnits.convert(l.standard,l.unit,MassUnits.unit(l.unit,this.s.bomUnit)))}</td><td rowspan="${count}" style="text-align:right;font-weight:700">${this.esc(MassUnits.convert(l.actual,l.unit,MassUnits.unit(l.unit,this.s.bomUnit)))}</td><td rowspan="${count}">${this.esc(MassUnits.unit(l.unit,this.s.bomUnit))}</td>${lotCells(usages[0],l.item.id)}
        <td rowspan="${count}">${l.stock_managed === false ? '<span class="badge badge-neutral">재고 아님</span>' : b.status === 'IN_PROGRESS' ? `<button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.pickBomLine(${l.item.id})">투입량 확인</button>` : ''}</td></tr>${usages.slice(1).map(u=>`<tr>${lotCells(u,l.item.id)}</tr>`).join('')}`;
      }).join('')}
      </tbody></table></div>` : '';
    const form = b.status === 'IN_PROGRESS' ? (this.bulkUse ? this.renderBulkUse() : this.renderUseForm()) : '';
    return `
      <div class="card" style="margin-bottom:0.75rem;" id="prodUsages">
        <div class="card-header"><div class="card-title">원료 투입 (${b.usages.length}건)</div></div>
        ${!b.usages.length?'<p style="font-size:0.8rem;color:var(--text-muted);">투입 기록이 없습니다.</p>':''}
        ${b.status === 'IN_PROGRESS' ? '<p><button class="btn btn-primary" onclick="ProductionApiPage.prepareBulkUse()">남은 원료 일괄 투입</button></p>' : ''}
        ${this.bulkUse ? '' : bom}
        ${!this.bulkUse&&b.usages.some(u=>!matched.has(u.id))?`<div style="margin-top:0.75rem"><strong>${check?'BOM 행 연결 없는 투입':'투입 LOT'}</strong><div class="table-wrapper"><table class="data-table"><thead><tr><th>투입 LOT</th><th>사용 원료</th><th style="text-align:right">LOT별 사용량</th></tr></thead><tbody>${b.usages.filter(u=>!matched.has(u.id)).map(u=>`<tr>${lotCells(u)}</tr>`).join('')}</tbody></table></div></div>`:''}
        ${form}
      </div>`;
  },

  async openUsageLot(lotId) {
    const b=this.detail;
    try {
      const lot=await this.get(`/lots/${lotId}/`);
      if(this.detail!==b)return;
      const usages=b.usages.filter(u=>u.lot_id===lotId);
      App.showModal('투입 LOT 상세', `<p><strong>${this.esc(lot.item.item_code)} ${this.esc(lot.item.name)}</strong> · ${this.esc(lot.lot_number)}</p><p>소비기한 ${this.esc(lot.expiration_date||'미등록')} · 현재고 ${this.inputMass(lot.quantity,lot.item.base_unit)}</p>
        <div class="table-wrapper"><table class="data-table"><thead><tr><th>이 배치 투입 기록</th><th>최초 투입량</th><th>정정 반영 실투입량</th></tr></thead><tbody>${usages.map(u=>`<tr><td>#${u.id}</td><td>${this.inputMass(u.quantity,u.unit)}</td><td>${this.inputMass(u.net_quantity,u.unit)}</td></tr>`).join('')}</tbody></table></div>
        <h4>LOT 수불 이력</h4><div class="table-wrapper"><table class="data-table"><thead><tr><th>일시</th><th>구분</th><th>수량</th><th>사유</th><th>담당자</th></tr></thead><tbody>${lot.movements.map(m=>`<tr><td>${this.esc(String(m.occurred_at).replace('T',' ').slice(0,16))}</td><td>${this.esc(m.movement_name)}</td><td>${this.inputMass(m.signed_quantity,m.unit)}</td><td>${this.esc(m.reason||'')}</td><td>${this.esc(m.staff.name)}</td></tr>`).join('')}</tbody></table></div>`);
      document.getElementById('modalContainer').classList.add('inventory-detail-modal');
    } catch(error) { this.toast('error','투입 LOT 조회',error.message); }
  },

  renderUseForm() {
    const u=this.s.use;
    const line=(this.detail.readiness?.lines||[]).find(l=>String(l.bom_line_id)===String(u.lineId));
    if(!line) return '<p style="color:var(--text-muted);font-size:0.8rem">위 BOM 표에서 원료의 ‘투입량 확인’을 누르세요.</p>';
    const choices=this.lotChoices||[];
    const picked=choices.filter(l=>u.allocations?.[l.lot_id]);
    return `<div id="prodUseForm" style="margin-top:0.75rem;border-top:1px solid var(--border-subtle);padding-top:0.75rem">
      <strong>${this.esc(line.item_code)} ${this.esc(line.name)} 투입</strong>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:flex-end;margin:0.75rem 0">
        ${this.field('입력 단위',`<select class="form-control" name="use_unit" onchange="ProductionApiPage.s.use.inputUnit=this.value;ProductionApiPage.renderDetail()">${this.unitOptions(line.unit,this.inputUnit(line.unit,u.inputUnit))}</select>`)}
        ${this.field('이번 투입 총량',`<input type="number" min="0" step="any" name="use_quantity" class="form-control" value="${this.esc(this.inputQuantity(u.quantity,line.unit,u.inputUnit))}" oninput="ProductionApiPage.changeDisplayedUseQuantity(this.value)" onchange="ProductionApiPage.proposeAllocation()">`)}
        ${line.allowed_items.length>1?this.field('사용 원료',`<select class="form-control" name="use_item" onchange="ProductionApiPage.changeUseItem(this.value)"><option value="">기준 원료 우선 · 부족 시 등록 대체 원료</option>${line.allowed_items.map(i=>`<option value="${i.id}" ${String(i.id)===String(u.itemId)?'selected':''}>${this.esc(i.item_code)} ${this.esc(i.name)}</option>`).join('')}</select>`):''}
        <button class="btn btn-secondary" onclick="ProductionApiPage.proposeAllocation()">배분 다시 계산</button>
      </div>
      <div id="prodAllocationSummary" aria-live="polite">${this.fefo?`<p>자동 배분: ${picked.map(l=>`${this.esc(l.item.name)} · ${this.esc(l.lot_number)} ${this.inputMass(u.allocations[l.lot_id],l.unit,u.inputUnit)}`).join(' / ') || '배분 가능한 LOT 없음'}</p><p>선택 합계 <strong id="prodAllocationTotal">${this.esc(this.inputQuantity(this.allocationTotal()??'0',line.unit,u.inputUnit))}</strong> ${this.esc(this.inputUnit(line.unit,u.inputUnit))} · 부족 ${this.inputMass(this.fefo.shortfall,line.unit,u.inputUnit)}</p>`:'<p>총량을 입력하면 소비기한·입고일 순으로 LOT를 자동 배분합니다.</p>'}</div>
      <details ${u.manual?'open':''} ontoggle="ProductionApiPage.s.use.manual=this.open"><summary style="cursor:pointer;margin:0.75rem 0">LOT · 배분량 직접 수정</summary>
        <div class="table-wrapper"><table class="data-table"><thead><tr><th>선택</th><th>원료 · LOT</th><th>소비기한</th><th>가용재고</th><th>투입량</th></tr></thead><tbody>
        ${choices.map(l=>`<tr><td><input type="checkbox" data-pick="${l.lot_id}" ${u.allocations?.[l.lot_id]?'checked':''} onchange="ProductionApiPage.captureAllocation()"></td><td>${this.esc(l.item.name)}<br>${this.esc(l.lot_number)}</td><td>${this.esc(l.expiration_date||'날짜 없음')}</td><td>${this.inputMass(l.quantity,l.unit,u.inputUnit)}</td><td><input class="form-control" type="number" min="0" max="${this.esc(this.inputQuantity(l.quantity,l.unit,u.inputUnit))}" step="any" data-amount="${l.lot_id}" value="${this.esc(this.inputQuantity(u.allocations?.[l.lot_id],l.unit,u.inputUnit))}" oninput="ProductionApiPage.captureAllocation()"> ${this.esc(this.inputUnit(l.unit,u.inputUnit))}</td></tr>`).join('') || '<tr><td colspan="5">사용 가능한 LOT가 없습니다.</td></tr>'}
        </tbody></table></div>
      </details>
      <p id="prodAllocationError" role="alert" style="color:var(--color-danger)"></p>
      <button class="btn btn-primary" id="prodUseBtn" ${this.fefo && picked.length && this.scaled(this.allocationTotal())===this.scaled(u.quantity)?'':'disabled'} onclick="ProductionApiPage.addUsage()">배분 확인 · 일괄 투입</button>
      <p style="font-size:0.75rem;color:var(--text-muted)">저장하면 재고에서 차감됩니다. 실제 사용한 LOT와 수량을 확인하세요.</p>
    </div>`;
  },

  scaled(value) {
    const m=/^(\d+)(?:\.(\d{1,6}))?$/.exec(String(value));
    return m?BigInt(m[1])*1000000n+BigInt((m[2]||'').padEnd(6,'0')):null;
  },
  unscaled(value) { return `${value/1000000n}.${String(value%1000000n).padStart(6,'0')}`.replace(/\.?0+$/,''); },
  remaining(line) {
    const check=this.detail.bom_check?.lines.find(l=>l.item.id===line.item_id);
    const amount=(this.scaled(check?.standard || line.required)||0n)-(this.scaled(check?.actual||'0')||0n);
    return this.unscaled(amount>0n?amount:0n);
  },

  async pickBomLine(itemId) {
    if(this.busy) return;
    this.bulkUse=null;
    const line=this.detail.readiness.lines.find(l=>l.item_id===itemId);
    if(!line) return;
    this.s.use={lineId:line.bom_line_id,itemId:'',quantity:this.remaining(line),allocations:{},key:this.key(),manual:false};
    this.fefo=null;
    this.lotChoices=[];
    this.renderDetail();
    await this.loadUseLots();
    if(Number(this.s.use.quantity)>0) await this.proposeAllocation();
    document.getElementById('prodUseForm')?.scrollIntoView({behavior:'smooth',block:'nearest'});
  },

  async loadUseLots() {
    const u=this.s.use;
    const line=this.detail.readiness.lines.find(l=>String(l.bom_line_id)===String(u.lineId));
    const items=u.itemId?line.allowed_items.filter(i=>String(i.id)===String(u.itemId)):line.allowed_items;
    try {
      const lists=await Promise.all(items.map(i=>this.get('/stock/lots/',{item_id:i.id,usable_only:'1'})));
      if(this.s.use!==u) return;
      this.lotChoices=lists.flatMap(l=>l.results.filter(r=>r.can_use));
    } catch(error) { this.toast('error','LOT 조회 실패',error.message); }
  },

  changeUseQuantity(value) {
    this.s.use.quantity=value;
    this.s.use.allocations={};
    this.fefo=null;
    document.getElementById('prodUseBtn').disabled=true;
    document.getElementById('prodAllocationSummary').textContent='총량이 바뀌었습니다. 입력을 마치면 다시 배분합니다.';
  },

  unitOptions(base,selected=base) {return (['kg','g'].includes(base)?['kg','g']:[base]).map(u=>`<option value="${this.esc(u)}" ${u===selected?'selected':''}>${this.esc(u)}</option>`).join('');},
  inputUnit(base,override) { return MassUnits.unit(base,override||this.s.bomUnit); },
  inputQuantity(value,base,override) {
    return value===null || value===undefined || value==='' ? '' : MassUnits.convert(value,base,this.inputUnit(base,override));
  },
  inputMass(value,base,override) { return `${this.esc(this.inputQuantity(value,base,override))} ${this.esc(this.inputUnit(base,override))}`; },
  setDisplayUnit(unit) {
    this.s.bomUnit=unit;
    // A new page selection applies to all open rows. Row selections override it afterward.
    if(this.s.use) delete this.s.use.inputUnit;
    for(const row of this.bulkUse?.rows||[]) delete row.inputUnit;
    this.s.creating?this.renderCreate():this.renderDetail();
  },
  changeDisplayedUseQuantity(value) {
    const u=this.s.use,line=this.detail.readiness.lines.find(l=>l.bom_line_id===u.lineId);
    try {this.changeUseQuantity(value?MassUnits.convert(value,this.inputUnit(line.unit,u.inputUnit),line.unit,true):'');}
    catch(error) {this.changeUseQuantity('');this.toast('error','투입량',error.message);}
  },

  async changeUseItem(value) {
    const u=this.s.use;
    u.itemId=value; u.allocations={}; this.fefo=null;
    await this.loadUseLots();
    if(this.s.use===u) await this.proposeAllocation();
  },

  async proposeAllocation() {
    const u=this.s.use;
    if(!u.lineId || !(Number(u.quantity)>0)) return;
    const quantity=u.quantity, itemId=u.itemId, batchId=this.detail.id;
    await this.run('LOT 자동 배분',async()=>{
      const result=await this.get(`/batches/${batchId}/allocation/`,{bom_line_id:u.lineId,quantity,item_id:itemId});
      if(this.s.use!==u || u.quantity!==quantity || u.itemId!==itemId || this.detail.id!==batchId) return;
      this.fefo=result;
      u.allocations=Object.fromEntries(result.results.map(l=>[l.lot_id,l.quantity]));
      this.renderDetail();
    });
  },

  allocationTotal() {
    const u=this.s.use;
    if(Object.values(u.allocations||{}).some(value=>value===null)) return null;
    const line=this.detail.readiness?.lines.find(l=>String(l.bom_line_id)===String(u.lineId));
    if(!line) return '0';
    let sum=0n;
    for(const lot of this.lotChoices||[]) {
      if(!u.allocations?.[lot.lot_id]) continue;
      let amount=this.scaled(u.allocations[lot.lot_id]);
      if(amount===null) return null;
      if(lot.unit!==line.unit) {
        if(lot.unit==='kg' && line.unit==='g') amount*=1000n;
        else if(lot.unit==='g' && line.unit==='kg' && amount%1000n===0n) amount/=1000n;
        else return null;
      }
      sum+=amount;
    }
    return this.unscaled(sum);
  },

  captureAllocation() {
    const allocations={};
    for(const el of document.querySelectorAll('#prodUseForm [data-pick]:checked')) {
      const lot=this.lotChoices.find(l=>String(l.lot_id)===String(el.dataset.pick));
      const value=document.querySelector(`#prodUseForm [data-amount="${el.dataset.pick}"]`).value;
      try { allocations[el.dataset.pick]=value?MassUnits.convert(value,this.inputUnit(lot.unit,this.s.use.inputUnit),lot.unit,true):''; }
      catch { allocations[el.dataset.pick]=null; }
    }
    this.s.use.allocations=allocations;
    // Keep the request key until success: retries with a changed payload are rejected.
    const total=this.allocationTotal();
    const el=document.getElementById('prodAllocationTotal');
    const line=this.detail.readiness.lines.find(l=>String(l.bom_line_id)===String(this.s.use.lineId));
    if(el) el.textContent=total===null?'환산 가능한 소수점 6자리 이내 수량을 입력하세요':this.inputQuantity(total,line.unit,this.s.use.inputUnit);
    const valid=total!==null && this.scaled(total)===this.scaled(this.s.use.quantity) && Object.keys(allocations).length>0;
    document.getElementById('prodUseBtn').disabled=!valid;
    document.getElementById('prodAllocationError').textContent=valid?'':'선택 LOT 합계와 이번 투입 총량을 같게 맞춰 주세요.';
  },

  async addUsage() {
    if(this.busy) return;
    const u=this.s.use;
    const entries=Object.entries(u.allocations||{}).map(([id,quantity])=>({lot_id:Number(id),bom_line_id:Number(u.lineId),quantity}));
    const total=this.allocationTotal();
    if(!entries.length || entries.some(r=>!(Number(r.quantity)>0)) || total===null || this.scaled(total)!==this.scaled(u.quantity)) {
      return this.toast('error','원료 투입','선택 LOT 합계와 이번 투입 총량을 같게 맞춰 주세요.');
    }
    const batchId=this.detail.id;
    await this.run('일괄 투입',async()=>{
      await this.post(`/batches/${batchId}/usages/`,{entries,staff_id:Number(this.s.staffId),idempotency_key:u.key,expected_quantity:u.quantity,expected_bom_line_id:Number(u.lineId)});
      this.toast('success','원료 투입 완료',`${entries.length}개 LOT 저장`);
      this.s.use={lineId:'',itemId:'',quantity:'',allocations:{},key:this.key()};
      this.fefo=null;
      await this.select(batchId);
    });
  },

  // ---------- 여러 원료 검토 · 일괄 투입 ----------
  async prepareBulkUse(recalculate=false) {
    if(this.busy) return;
    const batchId=this.detail.id, previous=this.bulkUse;
    const lines=recalculate ? previous.rows.filter(r=>r.selected).map(r=>({bom_line_id:r.bom_line_id,quantity:r.quantity,item_id:r.item_id||null})) : undefined;
    if(recalculate && !lines.length) return this.toast('error','일괄 투입','원료를 선택하세요.');
    await this.run('남은 원료 불러오기',async()=>{
      const result=await this.post(`/batches/${batchId}/bulk-allocation/`,lines?{lines}:{});
      if(this.detail.id!==batchId || this.bulkUse!==previous) return;
      const rows=result.lines.map(r=>({...r,inputUnit:recalculate?previous.rows.find(p=>p.bom_line_id===r.bom_line_id)?.inputUnit:undefined,selected:true,allocations:Object.fromEntries(r.results.map(l=>[l.lot_id,l.quantity]))}));
      // Unselected rows stay visible and can be selected again without reloading the batch.
      if(recalculate) rows.push(...previous.rows.filter(r=>!r.selected));
      this.bulkUse={batchId,rows,key:this.key(),basis:this.detail.bom_check?.basis,basisQuantity:this.detail.bom_check?.basis_quantity};
      this.renderDetail();
      document.getElementById('prodBulkUse')?.scrollIntoView({behavior:'smooth',block:'nearest'});
    });
  },

  bulkTotal(row) {
    let total=0n;
    for(const lot of row.choices) {
      if(!Object.hasOwn(row.allocations,lot.lot_id)) continue;
      let amount=this.scaled(row.allocations[lot.lot_id]);
      if(amount===null || amount<=0n) return null;
      if(lot.unit!==row.unit) {
        if(lot.unit==='kg' && row.unit==='g') amount*=1000n;
        else if(lot.unit==='g' && row.unit==='kg' && amount%1000n===0n) amount/=1000n;
        else return null;
      }
      total+=amount;
    }
    return total;
  },

  bulkErrors() {
    const rows=this.bulkUse?.rows.filter(r=>r.selected)||[], errors=[], lots=new Map();
    if(!rows.length) return ['투입할 원료를 선택하세요.'];
    let count=0;
    for(const row of rows) {
      const total=this.bulkTotal(row), quantity=this.scaled(row.quantity);
      if(quantity===null || quantity<=0n || total!==quantity) errors.push(`${row.name}: LOT 합계와 이번 실제 투입량을 맞춰 주세요.`);
      for(const lot of row.choices) {
        if(!Object.hasOwn(row.allocations,lot.lot_id)) continue;
        count++;
        const amount=this.scaled(row.allocations[lot.lot_id]);
        lots.set(lot.lot_id,{amount:(lots.get(lot.lot_id)?.amount||0n)+(amount||0n),stock:this.scaled(lot.stock),name:lot.lot_number});
      }
    }
    for(const lot of lots.values()) if(lot.amount>lot.stock) errors.push(`${lot.name}: 여러 원료에 배분한 합계가 가용재고를 초과합니다.`);
    if(count>100) errors.push('한 번에 투입할 LOT 행은 최대 100개입니다. 원료를 나눠 선택하세요.');
    return errors;
  },

  renderBulkUse() {
    const draft=this.bulkUse, errors=this.bulkErrors();
    return `<div id="prodBulkUse" style="margin-top:1rem;border-top:1px solid var(--border-subtle);padding-top:1rem">
      <h3>남은 원료 일괄 투입</h3>
      <p style="font-size:0.8rem">기준: ${draft.basis==='output'?'산출량':'계획량'} ${this.inputMass(draft.basisQuantity,this.detail.unit)}</p>
      <p>기준량에서 기등록량을 뺀 수량입니다. 실제 사용한 수량·LOT를 확인하고 다른 부분만 수정하세요. 저장 전에는 재고가 차감되지 않습니다.</p>
      <fieldset ${draft.submitted?'disabled':''} style="border:0;padding:0;min-width:0">
      <div class="table-wrapper" style="max-height:560px;overflow:auto"><table class="data-table"><thead style="position:sticky;top:0;z-index:1"><tr><th>선택</th><th>원료</th><th>기준량</th><th>기등록량</th><th>이번 실제 투입량</th><th>LOT 배분 · 상태</th></tr></thead><tbody>
      ${draft.rows.map((r,index)=>`<tr>
        <td><input type="checkbox" aria-label="${this.esc(r.name)} 선택" ${r.selected?'checked':''} onchange="ProductionApiPage.editBulk(${index},'selected',this.checked)"></td>
        <td>${this.esc(r.item_code)} ${this.esc(r.name)}</td><td>${this.inputMass(r.standard,r.unit,r.inputUnit)}</td><td>${this.inputMass(r.actual,r.unit,r.inputUnit)}</td>
        <td><span style="display:inline-flex;gap:0.25rem;align-items:center"><input class="form-control" style="width:110px" type="number" min="0" step="any" aria-label="${this.esc(r.name)} 이번 실제 투입량" value="${this.esc(this.inputQuantity(r.quantity,r.unit,r.inputUnit))}" oninput="ProductionApiPage.editDisplayedBulk(${index},this.value)"><select class="form-control" aria-label="${this.esc(r.name)} 입력 단위" onchange="ProductionApiPage.bulkUse.rows[${index}].inputUnit=this.value;ProductionApiPage.renderDetail()">${this.unitOptions(r.unit,this.inputUnit(r.unit,r.inputUnit))}</select></span></td>
        <td><div data-bulk-summary="${index}">${this.bulkSummary(r)}</div>
          <details><summary>LOT · 배분량 직접 수정</summary>
          ${r.allowed_items.length>1?`<label>자동 배분 원료 <select class="form-control" onchange="ProductionApiPage.editBulk(${index},'item_id',this.value)"><option value="">기준 원료 우선 · 부족 시 대체 원료</option>${r.allowed_items.map(i=>`<option value="${i.id}" ${String(r.item_id)===String(i.id)?'selected':''}>${this.esc(i.name)}</option>`).join('')}</select></label>`:''}
          ${r.choices.map(l=>`<label style="display:block;margin:0.5rem 0">${this.esc(l.name)} · ${this.esc(l.lot_number)}<br>소비기한 ${this.esc(l.expiration_date||'없음')} · 가용 ${this.inputMass(l.stock,l.unit,r.inputUnit)}<input class="form-control" type="number" min="0" max="${this.esc(this.inputQuantity(l.stock,l.unit,r.inputUnit))}" step="any" aria-label="${this.esc(r.name)} ${this.esc(l.lot_number)} 배분량" value="${this.esc(this.inputQuantity(r.allocations[l.lot_id],l.unit,r.inputUnit))}" oninput="ProductionApiPage.editDisplayedBulkLot(${index},${l.lot_id},this.value)"> ${this.esc(this.inputUnit(l.unit,r.inputUnit))}</label>`).join('')||'<p>사용 가능한 LOT가 없습니다.</p>'}
          </details></td></tr>`).join('')||'<tr><td colspan="6">BOM 기준 남은 투입량이 없습니다. 추가 투입은 원료별 ‘투입량 확인’을 이용하세요.</td></tr>'}
      </tbody></table></div>
      <p><button class="btn btn-secondary" onclick="ProductionApiPage.prepareBulkUse(true)">선택 원료 LOT 다시 자동 배분</button> <small>선택 원료의 수동 배분을 새 제안으로 바꿉니다.</small></p>
      </fieldset>
      <p id="prodBulkSelected">선택 ${draft.rows.filter(r=>r.selected).length} / ${draft.rows.length}개 원료</p>
      ${draft.submitted?'<p>등록 요청 후에는 같은 내용으로 재시도합니다. 내용을 수정하려면 ‘남은 원료 일괄 투입’으로 다시 불러오세요.</p>':''}
      <div id="prodBulkErrors" role="alert" style="color:var(--color-danger)">${errors.map(e=>`<p>${this.esc(e)}</p>`).join('')}</div>
      <button class="btn btn-primary" id="prodBulkSave" ${errors.length?'disabled':''} onclick="ProductionApiPage.saveBulkUse()">확인한 원료 일괄 등록</button>
      <button class="btn btn-secondary" onclick="ProductionApiPage.closeBulkUse()">닫기</button>
      <p>등록하면 선택 원료의 재고가 함께 차감됩니다. 하나라도 실패하면 이번 요청 전체를 저장하지 않습니다.</p>
    </div>`;
  },

  bulkSummary(row) {
    const total=this.bulkTotal(row), quantity=this.scaled(row.quantity);
    const picks=row.choices.filter(l=>row.allocations[l.lot_id]).map(l=>`${this.esc(l.lot_number)} ${this.inputMass(row.allocations[l.lot_id],l.unit,row.inputUnit)}`).join(' / ');
    const shortage=quantity!==null && total!==null && quantity>total?this.unscaled(quantity-total):'0';
    return `${picks||'배분된 LOT 없음'}<br><strong>${total!==null?this.esc(this.inputQuantity(this.unscaled(total),row.unit,row.inputUnit)):'수량 확인'} / ${this.inputMass(row.quantity,row.unit,row.inputUnit)}</strong> · ${total===quantity && quantity>0n?'배분 완료':`배분 확인 · 부족 ${this.inputMass(shortage,row.unit,row.inputUnit)}`}`;
  },

  editDisplayedBulk(index,value) {
    const row=this.bulkUse.rows[index];
    try {this.editBulk(index,'quantity',value?MassUnits.convert(value,this.inputUnit(row.unit,row.inputUnit),row.unit,true):'');}
    catch(error) {this.editBulk(index,'quantity','');this.toast('error','투입량',error.message);}
  },

  editBulk(index,field,value) {
    if(this.busy || this.bulkUse?.submitted) return;
    this.bulkUse.rows[index][field]=value;
    if(field==='item_id') {
      this.bulkUse.rows[index].allocations={};
      document.querySelectorAll('#prodBulkUse [data-bulk-summary]')[index]?.closest('td')?.querySelectorAll('input').forEach(el=>{el.value='';});
    }
    this.refreshBulkStatus();
  },
  editBulkLot(index,lotId,value) {
    if(this.busy || this.bulkUse?.submitted) return;
    const row=this.bulkUse.rows[index];
    if(!value || this.scaled(value)===0n) delete row.allocations[lotId];
    else row.allocations[lotId]=value;
    this.refreshBulkStatus();
  },
  editDisplayedBulkLot(index,lotId,value) {
    if(this.busy || this.bulkUse?.submitted) return;
    const row=this.bulkUse.rows[index], lot=row.choices.find(l=>l.lot_id===lotId);
    try {this.editBulkLot(index,lotId,value?MassUnits.convert(value,this.inputUnit(lot.unit,row.inputUnit),lot.unit,true):'');}
    catch(error) {row.allocations[lotId]=null;this.refreshBulkStatus();this.toast('error','LOT 배분량',error.message);}
  },
  refreshBulkStatus() {
    const errors=this.bulkErrors();
    document.getElementById('prodBulkSave').disabled=errors.length>0;
    document.getElementById('prodBulkSelected').textContent=`선택 ${this.bulkUse.rows.filter(r=>r.selected).length} / ${this.bulkUse.rows.length}개 원료`;
    document.getElementById('prodBulkErrors').innerHTML=errors.map(e=>`<p>${this.esc(e)}</p>`).join('');
    document.querySelectorAll('#prodBulkUse [data-bulk-summary]').forEach(el=>{el.innerHTML=this.bulkSummary(this.bulkUse.rows[Number(el.dataset.bulkSummary)]);});
  },
  async closeBulkUse() {
    if(this.busy) return;
    const submitted=this.bulkUse?.submitted;
    this.bulkUse=null;
    if(submitted) await this.select(this.detail.id);
    else this.renderDetail();
  },

  async saveBulkUse() {
    if(this.busy || !this.bulkUse) return;
    const errors=this.bulkErrors();
    if(errors.length) return this.toast('error','일괄 투입',errors[0]);
    const draft=this.bulkUse, rows=draft.rows.filter(r=>r.selected), batchId=draft.batchId;
    const entries=rows.flatMap(r=>Object.entries(r.allocations).map(([lotId,quantity])=>({lot_id:Number(lotId),quantity,bom_line_id:r.bom_line_id})));
    const expected_lines=rows.map(r=>({bom_line_id:r.bom_line_id,actual:r.actual,standard:r.standard,quantity:r.quantity}));
    await this.run('원료 일괄 투입',async()=>{
      draft.payload ||= {entries,expected_lines,staff_id:Number(this.s.staffId),idempotency_key:draft.key};
      draft.submitted=true;
      this.renderDetail();
      await this.post(`/batches/${batchId}/usages/`,draft.payload);
      this.toast('success','원료 투입 완료',`${rows.length}개 원료 · ${entries.length}개 LOT 투입 기록 저장`);
      if(this.detail.id===batchId) await this.select(batchId);
    });
  },

  // ---------- 산출 ----------

  renderOutputs(b) {
    const lot = b.output_lot;
    const rows = b.outputs.map((o) => `<tr>
        <td class="no-wrap" style="font-family:monospace;color:var(--brand-primary);">${this.esc(o.lot_number)}</td>
        <td style="text-align:right;">${this.esc(o.quantity)}</td><td style="text-align:right;">${this.esc(o.net_quantity)}</td><td>${this.esc(o.unit)}</td></tr>`).join('');
    const form = b.status === 'IN_PROGRESS' ? `
      <div style="border-top:1px solid var(--border-subtle);margin-top:0.6rem;padding-top:0.6rem;display:flex;gap:0.6rem;align-items:flex-end;flex-wrap:wrap;" id="prodOutputForm">
        ${this.field('입력 단위', `<select class="form-control" name="output_unit">${BomApiPage.unitOptions(b.unit)}</select>`)}
        ${this.field(`산출량`, `<input type="number" class="form-control" name="output_quantity" min="0" step="any" style="width:140px;" value="${this.esc(this.s.output.quantity)}">`)}
        ${this.field('EA (참고 개수 · 선택)', '<input class="form-control" name="ea_count" type="number" min="0" step="1" placeholder="미입력 가능">')}
        <button class="btn btn-primary" id="prodOutputBtn" onclick="ProductionApiPage.addOutput()">산출 등록</button>
        <span style="font-size:0.72rem;color:var(--text-muted);">${lot ? `같은 LOT ${this.esc(lot.lot_number)} 에 더해집니다.` : 'LOT 번호는 제조일 + 품목별 순번으로 자동 채번됩니다.'}</span>
      </div>` : '';
    return `
      <div class="card" style="margin-bottom:0.75rem;" id="prodOutputs">
        <div class="card-header"><div class="card-title">산출 (벌크)</div></div>
        ${lot ? `<div style="margin-bottom:0.5rem;font-size:0.85rem;">산출 LOT <span style="font-family:monospace;font-weight:700;color:var(--brand-primary);" id="prodOutputLot">${this.esc(lot.lot_number)}</span> · 산출 합계 ${this.esc(lot.net_quantity)} · 현재고 <b>${this.esc(lot.stock)}</b> ${this.esc(b.unit)}</div>` : ''}
        ${b.outputs.length ? `<div class="table-wrapper"><table class="data-table"><thead><tr><th>LOT</th><th style="text-align:right;">산출</th><th style="text-align:right;">정정 반영</th><th>단위</th></tr></thead><tbody>${rows}</tbody></table></div>`
          : `<p style="font-size:0.8rem;color:var(--text-muted);">${b.status === 'PLANNED' ? '생산을 시작하면 산출을 등록할 수 있습니다.' : '산출 기록이 없습니다.'}</p>`}
        ${form}
      </div>`;
  },

  async addOutput() {
    let quantity;
    try { quantity=MassUnits.convert(document.querySelector('#prodOutputForm [name="output_quantity"]').value,document.querySelector('#prodOutputForm [name="output_unit"]').value,this.detail.unit,true); } catch(error) {return this.toast('error','산출량',error.message);}
    if (!(Number(quantity) > 0)) return this.toast('error', '산출', '0보다 큰 산출량을 입력하세요.');
    this.s.output.quantity = quantity;
    await this.run('산출 등록', async () => {
      const b = await this.post(`/batches/${this.detail.id}/outputs/`, {
        quantity, ea_count:document.querySelector('#prodOutputForm [name=ea_count]').value, staff_id: Number(this.s.staffId), idempotency_key: this.s.output.key,
      });
      this.toast('success', '산출 등록', `${b.output_lot ? b.output_lot.lot_number : ''} ${quantity}`);
      this.s.output = { quantity: '', key: this.key() };
      await this.select(b.id);
    });
  },

  // ---------- 완료 · 취소 ----------
  renderComplete(b) {
    const ready = b.outputs.length > 0;
    return `
      <div class="card" style="margin-bottom:0.75rem;" id="prodComplete">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:0.75rem;flex-wrap:wrap;">
          <div><strong>생산 완료</strong><div style="font-size:0.75rem;color:var(--text-muted);">${ready ? '완료하면 투입·산출을 더 추가할 수 없습니다.' : '산출을 먼저 등록하세요.'}</div></div>
          <button class="btn btn-primary" id="prodCompleteBtn" ${ready ? '' : 'disabled'} onclick="ProductionApiPage.complete()">완료</button>
        </div>
      </div>`;
  },

  async complete() {
    await this.run('생산 완료', async () => {
      const b = await this.post(`/batches/${this.detail.id}/complete/`, { staff_id: Number(this.s.staffId) });
      this.toast('success', '생산 완료', b.batch_number);
      await this.loadList();
      await this.select(b.id);
    });
  },

  async cancelBatch() {
    const reason = window.prompt('배치 취소 사유를 입력하세요. (투입·산출이 있으면 먼저 정정해야 합니다)');
    if (reason === null) return;
    if (!reason.trim()) return this.toast('error', '배치 취소', '사유를 입력하세요.');
    await this.run('배치 취소', async () => {
      const b = await this.post(`/batches/${this.detail.id}/cancel/`, { staff_id: Number(this.s.staffId), reason: reason.trim() });
      this.toast('success', '배치 취소', b.batch_number);
      await this.loadList();
      await this.select(b.id);
    });
  },

  async run(label, fn) {
    if (this.busy) return;
    if (!this.s.staffId) { this.toast('error', label, '담당자를 고르세요.'); return; }
    this.busy = true;
    document.querySelectorAll('#prodApiPage button').forEach((btn) => { btn.dataset.wasDisabled = btn.disabled ? '1' : ''; btn.disabled = true; });
    try {
      await fn();
    } catch (error) {
      this.toast('error', `${label} 실패`, error.message);
      const el = document.getElementById('prodDetail');
      if (el) el.insertAdjacentHTML('afterbegin', `<div class="card" id="prodError" style="border-color:var(--color-danger);margin-bottom:0.75rem;color:var(--color-danger);font-size:0.85rem;"><b>${this.esc(label)} 실패</b>${error.code ? ` (${this.esc(error.code)})` : ''}: ${this.esc(error.message)}</div>`);
    } finally {
      this.busy = false;
      document.querySelectorAll('#prodApiPage button').forEach((btn) => { if (btn.dataset.wasDisabled !== undefined) btn.disabled = btn.dataset.wasDisabled === '1'; });
    }
  },

  // ---------- 재고·수불 확인 ----------
  async loadTrace() {
    const el = () => document.getElementById('prodTrace');
    const b = this.detail;
    if (!b || !el()) return;
    const lots = new Map();
    b.usages.forEach((u) => lots.set(u.lot_id, { lot_id: u.lot_id, lot_number: u.lot_number, role: '투입 원료', item: u.item }));
    if (b.output_lot) lots.set(b.output_lot.lot_id, { lot_id: b.output_lot.lot_id, lot_number: b.output_lot.lot_number, role: '산출 벌크', item: b.item });
    if (!lots.size) {
      el().innerHTML = '<div style="padding:0.75rem 1rem;"><strong>재고·수불 확인</strong><p style="font-size:0.8rem;color:var(--text-muted);margin:0.3rem 0 0;">투입·산출이 생기면 관련 LOT 의 현재고와 수불 기록을 보여 줍니다.</p></div>';
      return;
    }
    const batchMoves = new Set([...b.usages, ...b.outputs].map((x) => x.stock_movement_id));
    const today = this.today();
    const start = (b.manufactured_date || today) < today ? b.manufactured_date : today;
    try {
      const results = await Promise.all([...lots.values()].map((lot) =>
        this.get('/ledger/', { from: start, to: today, lot_id: lot.lot_id }).then((data) => ({ lot, data }))));
      if(this.detail!==b || !el()) return;
      const sections = results.map(({ lot, data }) => {
        const item = data.results[0];
        const ledgerLot = item && item.lots.find((x) => x.lot_id === lot.lot_id);
        if (!ledgerLot) return '';
        const lines = ledgerLot.lines.map((l) => `<tr style="${batchMoves.has(l.movement_id) ? 'background:rgba(59,130,246,0.08);' : ''}">
            <td class="no-wrap">${this.esc(String(l.occurred_at).replace('T', ' ').slice(0, 16))}</td>
            <td class="no-wrap">${this.esc(l.movement_name)}${batchMoves.has(l.movement_id) ? ' <span class="badge badge-info">이 배치</span>' : ''}</td>
            <td style="text-align:right;">${this.esc(l.quantity)}</td><td style="text-align:right;font-weight:700;">${this.esc(l.balance)}</td>
            <td>${this.esc(l.reason || '')}</td><td class="no-wrap">${this.esc(l.staff_name)}</td></tr>`).join('');
        return `
          <div style="padding:0.5rem 1rem;border-top:1px solid var(--border-subtle);display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;" class="prod-trace-lot" data-lot="${this.esc(lot.lot_number)}">
            <span><span class="badge badge-neutral">${this.esc(lot.role)}</span> ${this.esc(item.item.item_code)} ${this.esc(item.item.name)} · <span style="font-family:monospace;color:var(--brand-primary);">${this.esc(lot.lot_number)}</span></span>
            <span style="font-size:0.8rem;">LOT 현재고 <b class="prod-trace-closing">${this.esc(ledgerLot.closing)}</b> ${this.esc(item.unit)}</span>
          </div>
          <div style="padding:0.5rem 1rem">이 배치 ${lot.role==='투입 원료'?'투입':'산출'}량 <strong>${this.esc(this.unscaled([...b.usages,...b.outputs].filter(row=>row.lot_id===lot.lot_id).reduce((sum,row)=>sum+(this.scaled(row.net_quantity)||0n),0n)))}</strong> ${this.esc(item.unit)}</div>
          <details><summary style="padding:0.5rem 1rem;cursor:pointer">수불 이력 보기</summary><div class="table-wrapper"><table class="data-table"><thead><tr><th>일시</th><th>구분</th><th style="text-align:right;">수량(±)</th><th style="text-align:right;">LOT 잔량</th><th>사유</th><th>담당자</th></tr></thead><tbody>${lines}</tbody></table></div></details>`;
      }).join('');
      el().innerHTML = `
        <div style="padding:0.75rem 1rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
          <div><strong>재고·수불 확인</strong> <span style="font-size:0.75rem;color:var(--text-muted);">${this.esc(start)} ~ ${this.esc(today)} · 수불일지 API (ledger) 기준, 이 배치의 이동은 파란 줄</span></div>
          <span style="display:flex;gap:0.4rem;">
            <button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.openLedger('raw')">원료 수불대장</button>
            <button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.openLedger('finished')">완제품 수불대장</button>
          </span>
        </div>${sections}`;
    } catch (error) {
      if(this.detail!==b || !el()) return;
      el().innerHTML = `<div style="padding:0.75rem 1rem;"><strong>재고·수불 확인</strong><p style="color:var(--color-danger);font-size:0.8rem;">${this.esc(error.message)}</p></div>`;
    }
  },

  mass(value,unit) {return `${this.esc(MassUnits.convert(value,unit,MassUnits.unit(unit,this.s.bomUnit)))} ${this.esc(MassUnits.unit(unit,this.s.bomUnit))}`;},

  openLedger(type) {
    const b=this.detail;
    InventoryApiPage.type=type;
    const s=InventoryApiPage.state();
    Object.assign(s,{tab:'ledger',q:'',direction:'',itemId:'',lotNumber:'',ledgerPage:null,selectedLot:null,selectedItem:null,receiptVisibility:'all',focusBatch:b.id,focusBatchNumber:b.batch_number,
      from:b.manufactured_date||b.planned_date||this.today(),to:this.today(),period:''});
    App.navigate(type==='raw'?'raw-materials':'finished-goods');
  },

  beginPrintSelection() {
    if(this.printSelecting || this.printing) return;
    this.printSelecting=true;
    this.printBatchIds=[];
    if(this.s.creating) this.showHistory();
    this.renderBatchList();
  },
  endPrintSelection() {
    if(this.printing) return;
    this.printSelecting=false;
    this.printBatchIds=[];
    this.renderBatchList();
  },
  selectPrintBatch(id,checked) {
    this.printBatchIds=checked?[...new Set([...this.printBatchIds,id])]:this.printBatchIds.filter(v=>v!==id);
    this.updatePrintSelection();
  },
  selectPrintBatches(checked) {
    this.printBatchIds=checked?this.listBatches.map(b=>b.id):[];
    this.updatePrintSelection();
  },
  updatePrintSelection() {
    document.querySelectorAll('[data-print-batch]').forEach(el=>{el.checked=this.printBatchIds.includes(Number(el.dataset.printBatch));});
    const all=document.getElementById('prodPrintAll');
    if(all) {all.checked=this.listBatches.length>0 && this.listBatches.every(b=>this.printBatchIds.includes(b.id));all.indeterminate=this.printBatchIds.length>0 && !all.checked;}
    const selected=document.getElementById('prodPrintSelected');if(selected){selected.textContent=`선택 ${this.printBatchIds.length}개 인쇄`;selected.disabled=!this.printBatchIds.length||!!this.printing;}
    const cancel=document.getElementById('prodPrintCancel');if(cancel)cancel.disabled=!!this.printing;
    const button=document.getElementById('prodPrint');if(button){button.textContent=this.printSelecting?'인쇄 선택 취소':'생산지시 인쇄 / PDF';button.disabled=!!this.printing;}
  },
  printBatchSection(b,unit) {
    const e=v=>this.esc(v), mass=(v,u)=>v===null||v===undefined?'—':`${e(MassUnits.convert(v,u,MassUnits.unit(u,unit)))} ${e(MassUnits.unit(u,unit))}`;
    return `<section class="print-sheet" data-print-batch="${b.id}"><h1>생산지시서</h1><p>배치: ${e(b.batch_number)} · 상태: ${e(this.STATUS[b.status]?.[0])}</p><p>품목: ${e(b.item.item_code)} ${e(b.item.name)}</p><p>계획일: ${e(b.planned_date||'—')} · 제조일: ${e(b.manufactured_date||'—')} · 계획량: ${mass(b.planned_quantity,b.unit)}</p><p>BOM 버전: ${e(b.bom_version||'—')}</p>
      <h2>BOM 계획 소요량</h2><table><thead><tr><th>원료</th><th>기준 소요량</th></tr></thead><tbody>${(b.readiness?.lines||[]).map(l=>`<tr><td>${e(l.item_code)} ${e(l.name)}</td><td>${mass(l.required,l.unit)}</td></tr>`).join('')}</tbody></table>
      <h2>원료 투입</h2><table><thead><tr><th>원료</th><th>LOT</th><th>실제 투입량</th></tr></thead><tbody>${b.usages.map(u=>`<tr><td>${e(u.item.name)}</td><td>${e(u.lot_number)}</td><td>${mass(u.net_quantity,u.unit)}</td></tr>`).join('')}</tbody></table><h2>산출</h2><table><thead><tr><th>LOT</th><th>실제 산출량</th></tr></thead><tbody>${b.outputs.map(o=>`<tr><td>${e(o.lot_number)}</td><td>${mass(o.net_quantity,o.unit)}</td></tr>`).join('')}</tbody></table><p>메모: ${e(b.notes||'')}</p></section>`;
  },
  async printBatch(single=false) {
    if(this.printing) return;
    const ids=single?!this.s.creating && this.detail?[this.detail.id]:[]:[...this.printBatchIds];
    if(!ids.length) return this.toast('info','생산지시 출력','목록에서 인쇄할 배치를 선택하세요.');
    const unit=this.s.bomUnit;
    this.printing=true;
    this.updatePrintSelection();
    try {
      const batches=[];
      // Bound concurrent requests and retain the complete selection across list refreshes.
      for(let i=0;i<ids.length;i+=5) batches.push(...await Promise.all(ids.slice(i,i+5).map(id=>this.get(`/batches/${id}/`))));
      batches.sort((a,b)=>(a.manufactured_date||a.planned_date||'9999').localeCompare(b.manufactured_date||b.planned_date||'9999')||a.batch_number.localeCompare(b.batch_number,'ko',{numeric:true})||a.id-b.id);
      const html=`<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>생산지시서 ${batches.length}건</title><style>@page{size:A4;margin:12mm}body{font:12px "Malgun Gothic",sans-serif;color:#111;margin:0}h1{font-size:22px}h2{font-size:15px}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{border:1px solid #888;padding:7px;text-align:left;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}.print-sheet+.print-sheet{break-before:page;page-break-before:always}</style></head><body>${batches.map(b=>this.printBatchSection(b,unit)).join('')}</body></html>`;
      if(!BrowserPrint.print(html,single?undefined:()=>this.endPrintSelection())) this.toast('info','인쇄','열려 있는 인쇄 창을 마친 후 다시 시도하세요.');
    } catch(error) {this.toast('error','생산지시 출력',error.message);}
    finally {this.printing=false;this.updatePrintSelection();}
  },
};
