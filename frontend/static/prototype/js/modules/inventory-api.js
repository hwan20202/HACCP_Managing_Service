// =============================================
// 재고장 · 수불일지 — /api/v1/inventory/ 연결 화면
// (docs/inventory-frontend.md: 시제품 틀·디자인은 그대로, 재고 데이터만 API 로)
//
// - 수불대장: 수불 내역 / 현재고 탭. 두 탭의 품목명은 같은 품목 상세창을 연다
// - 상세창: 현재 품목 합계 / 전체 LOT 현재고 / 선택 기간 수불·LOT별 기간 요약
// - 0 재고는 재고 표에서만 기본 제외. 해당 LOT의 과거 수불은 기간 조회에 남는다
// - 소비기한은 날짜가 없을 때 '없음'(NONE)과 '미확인'(UNKNOWN)을 구분해 표시 (0007)
// - 수량은 API 의 문자열을 그대로 표시 (계산하지 않음)
// 기존 prototype inventory.js(고정 데이터)는 보존하고, 메뉴만 이 화면으로 연결한다.
// =============================================

const InventoryApiPage = {
  API: '/api/v1/inventory',

  TYPES: {
    raw: {
      title: '원료 수불대장',
      desc: '품목별 입출고 내역과 LOT별 현재 잔량을 함께 확인합니다.',
      itemTypes: ['RAW'],
      dateCol: 'received',
    },
    sub: {
      title: '부자재 수불대장',
      desc: '포장재 LOT별 현재고와 입출고 이력',
      itemTypes: ['PACKAGING'],
      dateCol: 'received',
    },
    finished: {
      title: '완제품 수불대장',
      desc: '제조 완료된 벌크(반제품)와 완제품의 LOT별 현재고·수불 — 이번 범위는 벌크 산출까지',
      itemTypes: ['SEMI', 'FINISHED'],
      dateCol: 'manufactured',
    },
  },

  LOT_STATUS: { QUARANTINE: ['검사대기', 'badge-warning'], AVAILABLE: ['사용가능', 'badge-success'], REJECTED: ['부적합', 'badge-danger'] },
  EXPIRATION: { NONE: ['소비기한 없음', 'badge-neutral'], UNKNOWN: ['미확인', 'badge-warning'] },

  type: 'raw',
  states: {},
  items: {},

  state() {
    const key = this.type;
    if (!this.states[key]) {
      const today = this.today();
      this.states[key] = {
        selectedLot: null, selectedItem: null, tab: 'ledger', period: 'month', q: '', direction: '', lowOnly: false, expiryDays: '', displayUnit: '',
        itemId: '',
        lotNumber: '',
        expirationStatus: '',
        includeEmpty: false,
        ledgerSortBy: 'occurred_at', ledgerSortOrder: 'desc',
        stockSortBy: 'item_code', stockSortOrder: 'asc', receiptVisibility: 'all',
        usableOnly: false,
        madeFrom: '',
        madeTo: '',
        from: today.slice(0, 8) + '01',
        to: today,
      };
    }
    return this.states[key];
  },

  today() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  },

  esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  query(params) {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined && v !== false) q.append(k, v === true ? '1' : v);
    });
    return q.toString();
  },

  async getJson(path, params = {}) {
    const response = await fetch(`${this.API}${path}?${this.query(params)}`, { headers: { Accept: 'application/json' } });
    let body = {};
    try { body = await response.json(); } catch (e) { /* not JSON */ }
    if (!response.ok) throw new Error(body?.error?.message || `요청 실패 (${response.status})`);
    return body;
  },

  // ---------- 화면 틀 ----------
  render(type = 'raw') {
    this.type = type;
    const cfg = this.TYPES[type];
    setTimeout(() => this.load(), 0);
    return `
    <style>
      #invApiPage .inv-panel { min-width:0;padding:0;overflow:hidden; }
      #invApiPage .inv-panel-head { padding:0.85rem 1rem;border-bottom:1px solid var(--border-subtle); }
      #invApiPage .inv-panel-head h2 { font-size:0.95rem;margin:0 0 0.35rem; }
      #invApiPage .inv-panel-head p { font-size:0.76rem;color:var(--text-muted);margin:0; }
      #invApiPage .inv-item-group td { background:var(--bg-elevated,#eef2f6);font-weight:700; }
      #invApiPage .inv-selected { background:var(--bg-elevated,#eef3ff);outline:2px solid var(--brand-primary);outline-offset:-2px; }
      #invApiPage .tabs .tab-btn.active { background:var(--brand-primary,#007bff);color:#fff;box-shadow:var(--shadow-sm); }
      #invApiPage .tabs .tab-btn:focus-visible { outline:2px solid var(--brand-primary,#007bff);outline-offset:2px; }
      #invApiPage { display:flex;flex-direction:column;gap:0;min-height:420px; }
      #invApiPage > .page-header, #invApiPage > .tabs, #invApiPage > .card { flex-shrink:0; }
      #invApiContent { flex:1;min-height:0;display:flex;flex-direction:column; }
      #invApiContent > .card { flex:1;min-height:0;display:flex;flex-direction:column; }
      #invApiContent > .table-wrapper, #invApiContent > .card > .table-wrapper { flex:1;min-height:0;max-height:none !important;overflow:auto; }
      #invApiContent thead th { position:sticky;top:0;z-index:1;background:var(--bg-elevated,#eef2f6); }
      .inv-item-link { border:0;background:none;color:var(--brand-primary);padding:0.25rem 0;font:inherit;text-align:left;cursor:pointer; }
      .inv-item-link:hover, .inv-item-link:focus-visible { text-decoration:underline; }
      .inventory-detail-modal .inv-summary { display:flex;flex-wrap:wrap;gap:1rem;padding:1rem;background:var(--bg-elevated);margin-bottom:1rem; }
      .inventory-detail-modal .table-wrapper { overflow:auto;max-width:100%; }
      .modal-container.inventory-detail-modal { width:calc(100vw - 2rem);max-width:1200px; }
      .inventory-detail-modal .data-table { min-width:1050px; }
      .inventory-detail-modal .data-table td, .inventory-detail-modal .data-table th { white-space:nowrap; }
    </style>
    <div class="fade-in" id="invApiPage">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">${cfg.title}</h1>
          <p class="page-desc">수불 내역과 현재고를 조회합니다. 입고 등록·취소는 오른쪽 버튼에서 진행합니다.</p>
        </div>
        <div class="page-actions">
          <button id="qaReceiptOpen" class="btn btn-primary" onclick="InventoryApiPage.openQaReceipt()">입고 등록</button>
          <button id="receiptCancelPickerOpen" class="btn btn-danger" onclick="InventoryApiPage.openReceiptPicker()">입고 취소</button>
          <button class="btn btn-secondary" onclick="InventoryApiPage.load()">새로고침</button>
          <button class="btn btn-secondary" id="invExport" onclick="InventoryApiPage.exportExcel()">엑셀 다운로드</button>
        </div>
      </div>
      <div class="tabs" style="margin-bottom:0.75rem;">
        ${[['ledger','수불 내역'],['stock','현재고']].map(([v,l]) => `<button data-inventory-tab="${v}" aria-pressed="${this.state().tab === v}" class="tab-btn ${this.state().tab === v ? 'active' : ''}" onclick="InventoryApiPage.set('tab','${v}')">${l}</button>`).join('')}
      </div>
      <div class="card" style="padding:0.75rem;margin-bottom:0.75rem;">
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:flex-end;">${this.renderFilters()}</div>
        <p style="margin:0.6rem 0 0;font-size:0.78rem;color:var(--text-muted);">현재고는 조회 시점의 잔량입니다. 수불 내역은 선택한 기간의 기록입니다. 품목 상세창에서 기간을 변경할 수 있습니다.</p>
      </div>
      <div id="invApiContent"><div class="empty-state"><p>불러오는 중…</p></div></div>
    </div>`;
  },

  field(label, html) {
    return `<label style="display:flex;flex-direction:column;gap:0.2rem;font-size:0.72rem;color:var(--text-muted);font-weight:600;">${label}${html}</label>`;
  },

  fitViewport() {
    const page = document.getElementById('invApiPage');
    if (!page) return;
    const padding = parseFloat(getComputedStyle(document.getElementById('pageContainer')).paddingBottom) || 0;
    page.style.height = `${Math.max(420, window.innerHeight - page.getBoundingClientRect().top - padding)}px`;
  },

  sortControls() {
    const s = this.state(), ledger = s.tab === 'ledger';
    const key = ledger ? 'ledgerSortBy' : 'stockSortBy', order = ledger ? 'ledgerSortOrder' : 'stockSortOrder';
    const options = ledger ? [['occurred_at','수불일자'],['item_code','품목코드'],['item_name','품목명'],['lot_number','LOT 번호']] : [['item_code','품목코드'],['item_name','품목명'],['total','총재고']];
    return this.field('정렬 기준', `<select id="invSortBy" class="form-control" onchange="InventoryApiPage.set('${key}',this.value)">${options.map(([v,l]) => `<option value="${v}" ${s[key]===v?'selected':''}>${l}</option>`).join('')}</select>`) +
      this.field('정렬 방향', `<select id="invSortOrder" class="form-control" onchange="InventoryApiPage.set('${order}',this.value)">${[['asc','오름차순'],['desc','내림차순']].map(([v,l]) => `<option value="${v}" ${s[order]===v?'selected':''}>${l}</option>`).join('')}</select>`);
  },

  renderFilters() {
    const s = this.state();
    const search = this.field('검색', `<input id="invSearch" type="search" class="form-control" style="min-width:260px" value="${this.esc(s.q)}" placeholder="품목코드 · 품목명 · 공급처 · LOT" oninput="InventoryApiPage.search(this.value)">`);
    if (s.tab === 'stock') return `${search}${this.sortControls()}
      <label><input type="checkbox" ${s.lowOnly ? 'checked' : ''} onchange="InventoryApiPage.set('lowOnly',this.checked)"> 부족 품목만</label>
      <label><input id="invIncludeEmpty" type="checkbox" ${s.includeEmpty ? 'checked' : ''} onchange="InventoryApiPage.set('includeEmpty',this.checked)"> 소진 LOT 포함</label>
      ${this.field('소비기한', `<select class="form-control" onchange="InventoryApiPage.set('expiryDays',this.value)">${[['','전체'],['7','경과·7일 이내'],['30','경과·30일 이내'],['90','경과·90일 이내']].map(([v,l])=>`<option value="${v}" ${s.expiryDays===v?'selected':''}>${l}</option>`).join('')}</select>`)}
      ${this.field('표시 단위', `<select class="form-control" onchange="InventoryApiPage.set('displayUnit',this.value)">${[['','기준 단위'],['kg','kg'],['g','g']].map(([v,l])=>`<option value="${v}" ${s.displayUnit===v?'selected':''}>${l}</option>`).join('')}</select>`)}`;
    return `${search}
      <div style="display:flex;gap:0.3rem;flex-wrap:wrap">${[['','전체'],['IN','입고'],['OUT','출고']].map(([v,l])=>`<button data-direction="${v}" aria-pressed="${s.direction===v && (v!=='' || !(s.selectedLot || s.itemId || s.lotNumber))}" class="btn ${s.direction===v && (v!=='' || !(s.selectedLot || s.itemId || s.lotNumber))?'btn-primary':'btn-secondary'} btn-sm" onclick="InventoryApiPage.set('direction','${v}')">${l}</button>`).join('')}</div>
      <div style="display:flex;gap:0.3rem;flex-wrap:wrap">${[['today','오늘'],['month','이번 달'],['3month','3개월'],['6month','6개월'],['year','1년']].map(([v,l])=>`<button data-period="${v}" aria-pressed="${s.period===v}" class="btn ${s.period===v?'btn-primary':'btn-secondary'} btn-sm" onclick="InventoryApiPage.setPeriod('${v}')">${l}</button>`).join('')}</div>
      ${this.field('조회 기간', `<span style="display:flex;gap:0.3rem"><input id="invFrom" type="date" class="form-control" value="${s.from}" onchange="InventoryApiPage.set('from',this.value)"> ~ <input id="invTo" type="date" class="form-control" value="${s.to}" onchange="InventoryApiPage.set('to',this.value)"></span>`)}
      ${this.sortControls()}
      ${this.field('취소 입고 이력', `<select id="invReceiptVisibility" class="form-control" onchange="InventoryApiPage.set('receiptVisibility',this.value)">${[['all','포함'],['hide','제외'],['only','취소 건만']].map(([v,l]) => `<option value="${v}" ${s.receiptVisibility===v?'selected':''}>${l}</option>`).join('')}</select>`)}`;
  },

  search(value) {
    this.state().q = value;
    this.state().selectedLot = null;
    this.state().itemId = '';
    this.state().selectedItem = null;
    this.loadSerial = (this.loadSerial || 0) + 1;
    this.cache = null;
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => { App.recordHistory?.(); this.load(); }, 250);
  },

  setPeriod(period) {
    const today = this.today();
    const d = new Date(today + 'T12:00:00');
    if (period === 'month') d.setDate(1);
    else if (period === 'year') d.setDate(d.getDate() - 365);
    else if (period !== 'today') d.setMonth(d.getMonth() - Number(period[0]));
    const pad = n => String(n).padStart(2,'0');
    this.state().from = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
    this.state().to = today;
    this.state().period = period;
    this.rerender();
  },

  // ---------- 이벤트 ----------
  set(key, value) {
    const s = this.state();
    s[key] = value;
    if(key==='direction' && value==='') {
      s.selectedLot=null; s.selectedItem=null; s.itemId=''; s.lotNumber='';
    }
    if(key==='from' || key==='to') s.period='';
    this.cache = null;
    if (key === 'tab') { s.selectedLot = null; s.itemId = ''; s.selectedItem=null; }
    // Search changes must not leave an invisible selected LOT restricting the ledger.
    if (['itemId', 'lotNumber', 'expirationStatus', 'madeFrom', 'madeTo', 'includeEmpty', 'usableOnly'].includes(key)) s.selectedLot = null;
    this.rerender();
  },

  selectLot(id, number = '', item = null) {
    const s = this.state();
    s.selectedLot = id ? { id: Number(id), number, item } : null;
    s.selectedItem=null; s.itemId=''; s.q=''; s.lotNumber='';
    s.tab = 'ledger';
    this.rerender();
  },

  rerender() {
    const container = document.getElementById('pageContainer');
    if (container) container.innerHTML = this.render(this.type);
    App.recordHistory?.();
  },

  // ---------- 데이터 ----------
  async load() {
    const host = document.getElementById('invApiPage');
    if (!host) return;
    this.fitViewport();
    const serial = this.loadSerial = (this.loadSerial || 0) + 1;
    const current = () => serial === this.loadSerial && host === document.getElementById('invApiPage');
    this.cache = null;
    try {
      const s = this.state();
      if (s.tab === 'ledger') {
        const data=await this.fetchLedger();
        if(!current()) return;
        this.cache={tab:'ledger',data};
        document.getElementById('invApiContent').innerHTML=this.renderSelection()+this.renderLedger(data);
      } else {
        const [stock, totals] = await Promise.all([this.fetchStock(), this.getJson('/stock/items/', {item_type:this.TYPES[this.type].itemTypes.join(',')})]);
        if (!current()) return;
        const matches = new Set(stock.results.map(r=>r.item.id));
        const query=s.q.trim().toLowerCase();
        const filtered = totals.results.filter(r=>(!query || `${r.item.item_code} ${r.item.name}`.toLowerCase().includes(query) || matches.has(r.item.id)) && (!s.expiryDays || matches.has(r.item.id)) && (!s.lowOnly || r.below_minimum));
        this.stockRows = stock.results;
        const sorted = this.sortStockTotals(filtered);
        this.cache = {tab:'stock', data:{results:sorted}, stock};
        document.getElementById('invApiContent').innerHTML = this.renderTotals({results:sorted});
      }
    } catch(error) {
      if (!current()) return;
      document.getElementById('invApiContent').innerHTML = `<div class="empty-state"><h3>조회하지 못했습니다</h3><p>${this.esc(error.message)}</p></div>`;
    }
  },

  clearSelection() { this.state().itemId=''; this.state().selectedItem=null; this.state().selectedLot=null; this.rerender(); },

  renderSelection() {
    const s=this.state();
    if(!s.selectedLot && !s.itemId) return '';
    const item=s.selectedLot?.item || s.selectedItem;
    return `<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem"><strong>${item?`${this.esc(item.item_code)} ${this.esc(item.name)} · `:''}${s.selectedLot?'LOT '+this.esc(s.selectedLot.number):'전체 LOT'}</strong><button id="invClearLot" class="btn btn-secondary btn-sm" onclick="InventoryApiPage.clearSelection()">선택 해제</button></div>`;
  },

  async openItem(id) {
    const s=this.state();
    this.detailContext={id:Number(id),from:s.from,to:s.to,direction:s.direction,lotId:null};
    App.showModal('품목 상세', '<p>불러오는 중…</p>');
    App.trackInventoryModal?.({kind:'item', id:Number(id)});
    document.getElementById('modalContainer').classList.add('inventory-detail-modal');
    await this.loadItemDetail();
  },

  async loadItemDetail() {
    const context=this.detailContext;
    if(!context) return;
    const serial=this.itemSerial=(this.itemSerial||0)+1;
    const type=this.type;
    const modal=document.querySelector('#modalContainer .modal-body');
    const current=()=>serial===this.itemSerial && type===this.type && context===this.detailContext &&
      modal===document.querySelector('#modalContainer .modal-body') && document.getElementById('modalContainer').classList.contains('active');
    try {
      const [item,stock,totals,ledger]=await Promise.all([
        this.getJson(`/items/${context.id}/`),
        this.getJson('/stock/lots/',{item_id:context.id,include_empty:true}),
        this.getJson('/stock/items/',{item_id:context.id}),
        this.getJson('/ledger/',{item_id:context.id,from:context.from,to:context.to}),
      ]);
      if(!current()) return;
      this.itemDetail=item;
      this.detailCache={item,stock,total:totals.results[0],ledger,queriedAt:new Date().toLocaleString('ko-KR')};
      this.stockRows=stock.results;
      this.renderItemDetail();
    } catch(error) {
      if(current()) modal.innerHTML=`<p role="alert">${this.esc(error.message)}</p><button class="btn btn-secondary" onclick="InventoryApiPage.loadItemDetail()">다시 조회</button>`;
    }
  },

  detailLedgerData() {
    const d=this.detailCache.ledger, id=this.detailContext.lotId;
    return {...d,results:d.results.map(item=>({...item,lots:item.lots.filter(lot=>!id||lot.lot_id===id)}))};
  },

  renderItemDetail() {
    const c=this.detailCache, d=this.detailContext, t=c.total;
    const total=t?.total||'0', usable=t?.usable||'0', unavailable=t?this.addQuantities(t.quarantine,t.unusable):'0';
    const unit=t?.unit||c.item.base_unit;
    const selected=c.stock.results.find(r=>r.lot_id===d.lotId);
    const modal=document.querySelector('#modalContainer .modal-body');
    modal.innerHTML=`<div id="invItemDetail">
      <h3>${this.esc(c.item.name)} <span style="font-weight:400">${this.esc(c.item.item_code)}</span></h3>
      <p>현재 재고 · 조회 시점 ${this.esc(c.queriedAt)} · 수불 조회 기간과 관계없는 잔량</p>
      <div class="inv-summary" id="invItemSummary"><span>총재고 <strong>${this.esc(total)} ${this.esc(unit)}</strong></span><span>사용 가능 <strong>${this.esc(usable)} ${this.esc(unit)}</strong></span><span>사용 불가 <strong>${this.esc(unavailable)} ${this.esc(unit)}</strong></span></div>
      <h4>전체 LOT별 현재 잔량</h4><p>소진 LOT도 포함합니다. LOT를 선택하면 아래 수불 이력만 좁혀집니다.</p>
      ${this.renderStock(c.stock,true)}
      <h4 style="margin-top:1rem">선택 기간의 수불 이력</h4>
      <form id="invItemPeriod" onsubmit="event.preventDefault();InventoryApiPage.applyItemPeriod()" style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:end">
        ${this.field('시작일',`<input id="invItemFrom" class="form-control" type="date" required value="${this.esc(d.from)}">`)}
        ${this.field('종료일',`<input id="invItemTo" class="form-control" type="date" required value="${this.esc(d.to)}">`)}
        <button class="btn btn-primary" type="submit">기간 조회</button>
        ${[['','전체'],['IN','입고'],['OUT','출고']].map(([value,label])=>`<button type="button" data-detail-direction="${value}" class="btn ${d.direction===value?'btn-primary':'btn-secondary'}" onclick="InventoryApiPage.setDetailDirection('${value}')">${label}</button>`).join('')}
        <button type="button" class="btn btn-secondary" onclick="InventoryApiPage.exportItemDetail()">상세 엑셀 다운로드</button>
      </form><p id="invItemPeriodError" role="alert" style="color:var(--color-danger)"></p>
      <p id="invDetailScope">${selected?'선택 LOT: '+this.esc(selected.lot_number):'전체 LOT'} · ${this.esc(d.from)} ~ ${this.esc(d.to)}
        ${selected?'<button class="btn btn-secondary btn-sm" onclick="InventoryApiPage.selectDetailLot(null)">전체 LOT 보기</button>':''}</p>
      <details id="invPeriodSummary"><summary>LOT별 기간 요약 · 조회 종료일 ${this.esc(d.to)} 기준 잔량</summary>${this.renderPeriodSummary(this.detailLedgerData())}</details>
      ${this.renderLedger(this.detailLedgerData(),d.direction)}
      <button class="btn btn-secondary" onclick="InventoryApiPage.applyDetailSelection()">${selected?'선택 LOT':'품목 전체'} 수불대장에서 보기</button>
    </div>`;
  },

  selectDetailLot(id) {
    if(id && !this.detailCache.stock.results.some(r=>r.lot_id===id)) return;
    this.detailContext.lotId=id;
    this.renderItemDetail();
    App.recordHistory?.();
  },

  setDetailDirection(value) {
    this.detailContext.direction=value;
    if(!value) this.detailContext.lotId=null;
    this.renderItemDetail();
    App.recordHistory?.();
  },

  async applyItemPeriod() {
    const from=document.getElementById('invItemFrom').value,to=document.getElementById('invItemTo').value;
    if(!from||!to||to<from||(new Date(to)-new Date(from))/86400000>366) {
      document.getElementById('invItemPeriodError').textContent='시작일과 종료일을 확인하세요. 조회 기간은 1년 이내입니다.';
      return;
    }
    this.detailContext={...this.detailContext,from,to};
    this.state().from=from;this.state().to=to;this.state().period='';
    document.getElementById('invItemPeriodError').textContent='조회 중…';
    this.cache=null; // prevent downloading a stale parent-period result during refresh
    this.rerender();
    await this.loadItemDetail();
  },

  applyDetailSelection() {
    const d=this.detailContext;
    this.state().direction=d.direction;
    this.state().from=d.from;this.state().to=d.to;
    if(d.lotId) {
      const row=this.detailCache.stock.results.find(r=>r.lot_id===d.lotId);
      App.closeModal(false);this.selectLot(row.lot_id,row.lot_number,row.item);
    } else this.viewItemLedger(d.id);
  },

  renderPeriodSummary(data) {
    const rows=data.results.flatMap(item=>item.lots.map(lot=>`<tr data-period-lot="${lot.lot_id}"><td>${this.esc(lot.lot_number)}</td><td>${this.esc(lot.opening)}</td><td>${this.esc(lot.in)}</td><td>${this.esc(lot.out)}</td><td data-period-closing="${this.esc(lot.closing)}">${this.esc(lot.closing)}</td><td>${this.esc(item.unit)}</td></tr>`));
    return `<p>각 LOT당 한 줄입니다. 조회 종료일 잔량은 이월과 기간 내 전체 수불을 반영하며 입출고 표시 필터와 무관합니다.</p><div class="table-wrapper"><table class="data-table"><thead><tr><th>LOT</th><th>이월</th><th>기간 입고 합계</th><th>기간 출고 합계</th><th>조회 종료일 잔량 (${this.esc(data.to)})</th><th>단위</th></tr></thead><tbody>${rows.join('')||'<tr><td colspan="6">선택 기간의 수불·이월 재고가 없습니다.</td></tr>'}</tbody></table></div>`;
  },

  viewItemLedger(id) {
    App.closeModal(false);
    const s=this.state();
    const item=this.itemDetail?.id===id?this.itemDetail:this.cache?.data.results.find(r=>r.item.id===id)?.item;
    s.itemId=String(id); s.selectedItem=item || null; s.tab='ledger'; s.selectedLot=null; s.q=''; s.lotNumber='';
    this.rerender();
  },

  fetchStock() {
    const s = this.state();
    return this.getJson('/stock/lots/', {
      item_type: this.TYPES[this.type].itemTypes.join(','),
      item_id: s.itemId,
      q: s.q.trim(),
      expiring_within_days: s.tab === 'stock' ? s.expiryDays : '',
      lot_number: s.lotNumber.trim(),
      expiration_status: s.expirationStatus,
      include_empty: s.includeEmpty,
      usable_only: s.usableOnly,
      manufactured_from: s.madeFrom,
      manufactured_to: s.madeTo,
    });
  },

  ledgerParams() {
    const s = this.state();
    return {
      from: s.from,
      to: s.to,
      lot_id: s.selectedLot?.id,
      q: s.q.trim(),
      item_type: this.TYPES[this.type].itemTypes.join(','),
      item_id: s.itemId,
      lot_number: s.lotNumber.trim(),
    };
  },

  fetchLedger() {
    return this.getJson('/ledger/', this.ledgerParams());
  },

  // Normal receipt entry uses the business API in local, QA and production environments.
  async openQaReceipt() {
    try {
      const [items, suppliers, staff] = await Promise.all([
        this.getJson('/items/'), this.getJson('/suppliers/'), this.getJson('/staff/'),
      ]);
      const options = (rows, label) => rows.map((r) => `<option value="${r.id}">${this.esc(label(r))}</option>`).join('');
      this.qaReceiptKey = crypto.randomUUID();
      this.receiptItems = items.results.filter(i=>i.is_stock_managed && ['RAW','PACKAGING','SEMI'].includes(i.item_type));
      this.receiptType = this.type === 'sub' ? 'PACKAGING' : this.type === 'finished' ? 'SEMI' : 'RAW';
      App.showModal('입고 등록', `<form id="qaReceiptForm">
        <p>저장하면 수불·재고와 입고 문서 3종이 연결됩니다.</p>
        ${this.field('품목 유형', `<select class="form-control" onchange="InventoryApiPage.receiptType=this.value;InventoryApiPage.filterReceiptItems()">${[['RAW','원료'],['PACKAGING','포장재'],['SEMI','반제품'],['','전체 유형']].map(([v,l])=>`<option value="${v}" ${this.receiptType===v?'selected':''}>${l}</option>`).join('')}</select>`)}
        ${this.field('품목명·코드 검색', `<input id="qaReceiptSearch" type="search" class="form-control" oninput="InventoryApiPage.filterReceiptItems()" placeholder="이름 또는 코드">`)}
        ${this.field('품목', '<select id="qaReceiptItem" name="item_id" class="form-control" size="4" style="height:auto" required onchange="InventoryApiPage.receiptUnit()"></select>')}
        ${this.field('공급처', `<select name="supplier_id" class="form-control">${options(suppliers.results, (i) => i.name)}</select>`)}
        ${this.field('담당자', `<select name="staff_id" class="form-control">${options(staff.results, (i) => i.name)}</select>`)}
        ${this.field('입고일', `<input name="received_date" type="date" class="form-control" value="${this.today()}" required>`)}
        ${this.field('입고량', '<input name="quantity" type="number" min="0" step="any" class="form-control" required>')}
        ${this.field('입력 단위','<select id="qaReceiptUnit" class="form-control"></select>')}
        ${this.field('소비기한 유무', '<select name="expiration_status" class="form-control" required onchange="InventoryApiPage.changeExpiration(this.value)"><option value="">선택하세요</option><option value="KNOWN">있음</option><option value="NONE">없음으로 확인</option></select>')}
        ${this.field('소비기한 (있음 선택 시 필수)', '<input name="expiration_date" type="date" class="form-control" disabled>')}
        ${this.field('입고 검사 판정', '<select name="judgment" class="form-control"><option value="">미판정 — 문서함에서 육안검사 작성</option><option value="PASS">적합</option><option value="FAIL">부적합</option></select>')}
        <p id="qaReceiptError" role="alert" style="color:var(--color-danger);"></p>
        <button type="submit" id="qaReceiptSave" class="btn btn-primary">입고 저장</button>
      </form>`);
      App.trackInventoryModal?.({kind:'entry'});
      this.filterReceiptItems();
      document.getElementById('qaReceiptForm').addEventListener('submit', (e) => { e.preventDefault(); this.saveQaReceipt(); });
    } catch (error) { App.showToast('error', '입고 준비 실패', error.message); }
  },

  filterReceiptItems() {
    const query=document.getElementById('qaReceiptSearch').value.toLowerCase().trim();
    const select=document.getElementById('qaReceiptItem');
    const current=select.value;
    const rows=this.receiptItems.filter(i=>(!this.receiptType || i.item_type===this.receiptType) && `${i.item_code} ${i.name}`.toLowerCase().includes(query));
    const labels={RAW:'원료',PACKAGING:'포장재',SEMI:'반제품'};
    select.innerHTML=rows.length ? rows.map(i=>`<option value="${i.id}">[${labels[i.item_type]}] ${this.esc(i.item_code)} ${this.esc(i.name)} (${this.esc(i.base_unit)})</option>`).join('') : '<option value="">검색 결과가 없습니다</option>';
    select.value=rows.some(i=>String(i.id)===current)?current:'';
    this.receiptUnit();
  },

  receiptUnit() {
    const item=this.receiptItems.find(i=>String(i.id)===document.getElementById('qaReceiptItem').value);
    const unit=item?.base_unit;
    document.getElementById('qaReceiptUnit').innerHTML=(['kg','g'].includes(unit)?[unit,unit==='kg'?'g':'kg']:[unit||'품목을 선택하세요']).map(v=>`<option>${this.esc(v)}</option>`).join('');
  },

  changeExpiration(status) {
    const input = document.querySelector('#qaReceiptForm [name="expiration_date"]');
    input.disabled = status !== 'KNOWN';
    input.required = status === 'KNOWN';
    if (status !== 'KNOWN') input.value = '';
  },

  quantity(value, unit) {
    const target = this.state().displayUnit;
    if (!target || unit === target || !['kg','g'].includes(unit)) return `${this.esc(value)} ${this.esc(unit)}`;
    return `${this.esc(String(Number(value) * (unit === 'kg' ? 1000 : 0.001)))} ${target}`;
  },

  renderTotals(data) {
    const below = data.results.filter(r=>r.below_minimum).length;
    return `<div style="display:flex;gap:1.5rem;margin:0.75rem 0"><strong>품목 ${data.results.length}개</strong><span>부족 품목 ${below}개</span></div>
      <div class="table-wrapper"><table class="data-table" id="invStockTable"><thead><tr><th>품목</th><th>총재고</th><th>사용 가능</th><th>사용 불가</th><th>LOT 수</th></tr></thead><tbody>
      ${data.results.map(r=>`<tr data-stock-item="${r.item.id}"><td><button class="inv-item-link" onclick="InventoryApiPage.openItem(${r.item.id})">${this.esc(r.item.name)}<br><span style="font-size:0.75rem;color:var(--text-muted)">${this.esc(r.item.item_code)}</span></button>${r.below_minimum?'<br><span class="badge badge-danger">최소재고 미만</span>':''}</td><td>${this.quantity(r.total,r.unit)}</td><td>${this.quantity(r.usable,r.unit)}</td><td>${this.quantity(this.addQuantities(r.quarantine,r.unusable),r.unit)}</td><td>${r.lot_count}</td></tr>`).join('') || '<tr><td colspan="5">조회 결과가 없습니다.</td></tr>'}
      </tbody></table></div><p style="padding:0 0.85rem;font-size:0.78rem;color:var(--text-muted)">사용 불가에는 검사대기·부적합·보류·소비기한 경과 재고가 포함됩니다. 품목명을 누르면 현재 재고 요약·전체 LOT·선택 기간 수불을 확인할 수 있습니다.</p>`;
  },

  sortStockTotals(rows) {
    const s = this.state(), sign = s.stockSortOrder === 'desc' ? -1 : 1;
    return [...rows].sort((a, b) => {
      if (s.stockSortBy === 'total') {
        const scaled = value => { const [n, f = ''] = String(value).split('.'); return BigInt(n) * 1000000n + BigInt(f.padEnd(6, '0')); };
        const x = scaled(a.total), y = scaled(b.total);
        return sign * (x < y ? -1 : x > y ? 1 : 0) || a.item.item_code.localeCompare(b.item.item_code);
      }
      const key = s.stockSortBy === 'item_name' ? 'name' : 'item_code';
      return sign * a.item[key].localeCompare(b.item[key], 'ko', {numeric:true}) || a.item.id - b.item.id;
    });
  },

  ledgerLines(data, direction=this.state().direction) {
    return data.results.flatMap(item=>item.lots.flatMap(lot=>lot.lines.map(line=>({item,lot,line}))))
      .filter(r=>!direction || (direction==='OUT')===String(r.line.quantity).startsWith('-'))
      .filter(({line}) => this.state().receiptVisibility === 'hide' ? line.source?.receipt_status !== 'CANCELLED' : this.state().receiptVisibility === 'only' ? line.source?.receipt_status === 'CANCELLED' : true)
      .sort((a,b) => {
        const s = this.state(), sign = s.ledgerSortOrder === 'asc' ? 1 : -1;
        const value = r => s.ledgerSortBy === 'item_code' ? r.item.item.item_code : s.ledgerSortBy === 'item_name' ? r.item.item.name : s.ledgerSortBy === 'lot_number' ? r.lot.lot_number : r.line.occurred_at;
        return sign * String(value(a)).localeCompare(String(value(b)), 'ko', {numeric:true}) || sign * (a.line.movement_id-b.line.movement_id);
      });
  },

  filePart(value) { return String(value||'').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,60); },

  ledgerSheet(data,direction='') {
    const headers=['수불일자','품목코드','품목명','LOT','구분','입고','출고','거래 직후 LOT 잔량','단위','처리자','사유'];
    return {name:'수불 내역',title:this.TYPES[this.type].title,subtitle:`${data.from} ~ ${data.to} · ${direction==='IN'?'입고':direction==='OUT'?'출고':'전체'} · 거래 직후 잔량`,columns:headers.map((header,i)=>({header,width:20,type:[5,6,7].includes(i)?'number':'text'})),rows:this.ledgerLines(data,direction).map(({item,lot,line})=>[line.occurred_at,item.item.item_code,item.item.name,lot.lot_number,line.movement_name,String(line.quantity).startsWith('-')?'':line.quantity,String(line.quantity).startsWith('-')?String(line.quantity).slice(1):'',line.balance,item.unit,line.staff_name,line.reason||''])};
  },

  exportExcel() {
    const c=this.cache,s=this.state();
    if(!c) return App.showToast('info','조회 중','검색 결과가 표시된 후 내려받으세요.');
    const menu=this.TYPES[this.type].title.replace(' 수불대장','');
    const scope=[s.q,s.selectedItem?.item_code,s.selectedLot?.number,s.lotNumber].filter(Boolean).map(v=>this.filePart(v)).join('_');
    if(c.tab==='ledger') {
      const sheet=this.ledgerSheet(c.data,s.direction);
      sheet.subtitle+=` · 검색: ${s.q||'전체'} · ${s.selectedLot?'선택 LOT '+s.selectedLot.number:s.selectedItem?.name||'전체 품목'}${s.lotNumber?' · LOT 검색 '+s.lotNumber:''}`;
      XlsxWriter.download(`${menu}수불대장_${c.data.from}_${c.data.to}_${s.direction==='IN'?'입고':s.direction==='OUT'?'출고':'전체'}${scope?'_'+scope:''}.xlsx`,[sheet]);
    } else {
      const headers=['품목코드','품목명','총재고','사용 가능','사용 불가','최소재고','단위','LOT 수'];
      const sheet={name:'품목별 현재고',title:this.TYPES[this.type].title,subtitle:`조회 시점 현재고 · 검색: ${s.q||'전체'} · ${s.lowOnly?'부족 품목만':'전체 품목'} · 소비기한: ${s.expiryDays?s.expiryDays+'일 이내':'전체'} · 품목 전체 합계`,columns:headers.map((header,i)=>({header,width:20,type:[2,3,4,5,7].includes(i)?'number':'text'})),rows:c.data.results.map(r=>[r.item.item_code,r.item.name,r.total,r.usable,this.addQuantities(r.quarantine,r.unusable),r.minimum_stock,r.unit,r.lot_count])};
      XlsxWriter.download(`${menu}현재고_${this.today()}${scope?'_'+scope:''}${s.lowOnly?'_부족품목':''}${s.expiryDays?'_소비기한'+s.expiryDays+'일':''}.xlsx`,[sheet]);
    }
  },

  exportItemDetail() {
    const c=this.detailCache,d=this.detailContext,data=this.detailLedgerData();
    const columns=headers=>headers.map(header=>({header,width:22,type:'text'}));
    const t=c.total,unit=t?.unit||c.item.base_unit;
    const sheets=[{name:'현재 재고 요약',title:c.item.name,subtitle:`조회 시점 ${c.queriedAt} · 품목 전체 현재 재고`,columns:columns(['품목코드','품목명','총재고','사용 가능','사용 불가','단위']),rows:[[c.item.item_code,c.item.name,t?.total||'0',t?.usable||'0',t?this.addQuantities(t.quarantine,t.unusable):'0',unit]]},
      {name:'전체 LOT 현재고',title:c.item.name,subtitle:`조회 시점 ${c.queriedAt} · 소진 LOT 포함 · 기간과 무관`,columns:columns(['LOT','현재 잔량','단위','소비기한','상태']),rows:c.stock.results.map(r=>[r.lot_number,r.quantity,r.unit,r.expiration_date||(r.expiration_status==='NONE'?'없음':'미확인'),this.lotStatusLabel(r)])},
      {name:'LOT별 기간 요약',title:c.item.name,subtitle:`${d.from} ~ ${d.to} · ${d.lotId?'선택 LOT':'전체 LOT'} · 조회 종료일 기준 잔량`,columns:columns(['LOT','이월','입고 합계','출고 합계','조회 종료일 잔량','단위']),rows:data.results.flatMap(item=>item.lots.map(lot=>[lot.lot_number,lot.opening,lot.in,lot.out,lot.closing,item.unit]))},this.ledgerSheet(data,d.direction)];
    for(const index of [2,3,4]) sheets[0].columns[index].type='number';
    sheets[1].columns[1].type='number';
    for(const index of [1,2,3,4]) sheets[2].columns[index].type='number';
    const selected=c.stock.results.find(r=>r.lot_id===d.lotId);
    XlsxWriter.download(`품목상세_${this.filePart(c.item.item_code)}_${d.from}_${d.to}_${d.direction==='IN'?'입고':d.direction==='OUT'?'출고':'전체'}${selected?'_'+this.filePart(selected.lot_number):''}.xlsx`,sheets);
  },

  lotStatusLabel(row) {
    if(row.is_expired) return '소비기한 경과';
    if(row.active_hold_count>0) return '보류';
    if(Number(row.quantity)===0) return '소진';
    return this.LOT_STATUS[row.status]?.[0] || row.status;
  },

  addQuantities(a, b) {
    const scaled = v => { const [n, f = ''] = String(v).split('.'); return BigInt(n) * 1000000n + BigInt(f.padEnd(6, '0')); };
    const sum = scaled(a) + scaled(b);
    return `${sum / 1000000n}.${String(sum % 1000000n).padStart(6, '0')}`.replace(/\.?0+$/, '');
  },

  async saveQaReceipt() {
    const form = document.getElementById('qaReceiptForm');
    const button = document.getElementById('qaReceiptSave');
    if (!form || button.disabled) return;
    const body = Object.fromEntries(new FormData(form));
    if (!body.expiration_status) return;
    button.disabled = true;
    body.idempotency_key = this.qaReceiptKey;
    const item=this.receiptItems.find(i=>String(i.id)===String(body.item_id));
    if(!item) { button.disabled=false; return; }
    const unit=document.getElementById('qaReceiptUnit').value;
    if (unit!==item.base_unit) {
      const match=/^(\d+)(?:\.(\d{1,6}))?$/.exec(body.quantity);
      if(!match) { button.disabled=false; document.getElementById('qaReceiptError').textContent='소수점 6자리 이내 수량을 입력하세요.'; return; }
      let amount=BigInt(match[1])*1000000n+BigInt((match[2]||'').padEnd(6,'0'));
      if(unit==='g' && amount%1000n) { button.disabled=false; document.getElementById('qaReceiptError').textContent='kg 환산 수량은 소수점 6자리 이내여야 합니다.'; return; }
      amount=unit==='g'?amount/1000n:amount*1000n;
      body.quantity=`${amount/1000000n}.${String(amount%1000000n).padStart(6,'0')}`;
    }
    ['item_id', 'supplier_id', 'staff_id'].forEach((key) => { body[key] = Number(body[key]); });
    const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || '';
    try {
      const response = await fetch(`${this.API}/receipts/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || `요청 실패 (${response.status})`);
      App.closeModal(false);
      App.recordHistory?.(true);
      App.showToast('success', '입고 완료', '수불·재고·문서가 연결되었습니다. 문서함에서 입고 문서를 확인하세요.');
      this.load();
    } catch (error) {
      const target = document.getElementById('qaReceiptError');
      if (target) target.textContent = error.message;
    } finally { button.disabled = false; }
  },

  // ---------- 표시 ----------
  badge([label, cls]) {
    return `<span class="badge ${cls}">${this.esc(label)}</span>`;
  },

  expiryCell(date, status, days) {
    if (date) {
      const warn = days !== null && days !== undefined && days <= 30;
      const dday = days === null || days === undefined ? '' : days < 0 ? ` <span class="badge badge-danger">경과</span>` : warn ? ` <span class="badge badge-warning">D-${days}</span>` : '';
      return `<span class="no-wrap">${this.esc(date)}</span>${dday}`;
    }
    return this.badge(this.EXPIRATION[status] || this.EXPIRATION.UNKNOWN);
  },

  lotStatus(row) {
    if (row.is_expired) return this.badge(['소비기한 경과', 'badge-danger']);
    if (row.active_hold_count > 0) return this.badge(['보류', 'badge-danger']);
    if (row.quantity === '0') return this.badge(['재고 없음', 'badge-neutral']);
    return this.badge(this.LOT_STATUS[row.status] || [row.status, 'badge-neutral']);
  },

  renderStock(data, compact = false) {
    const rows = data.results;
    const cfg = this.TYPES[this.type];
    if (!rows.length) return `<div class="empty-state"><h3>등록된 LOT가 없습니다</h3></div>`;
    const dateHead = cfg.dateCol === 'manufactured' ? '제조일' : '입고일';
    return `
    <div class="card" style="padding:0;">
      <div class="table-wrapper" style="max-height:340px;overflow:auto;">
        <table class="data-table">
          <thead><tr>
            ${compact?`<th>LOT 번호</th><th style="text-align:right">현재고</th><th>상태 · 우선순위</th><th>소비기한</th><th>${dateHead}</th>`:`<th>품목코드</th><th>품목명</th><th>LOT 번호</th><th>${dateHead}</th><th>소비기한</th>
            <th>상태</th><th>사용 우선순위</th><th style="text-align:right;">현재고</th><th>단위</th>${cfg.dateCol === 'received' ? '<th>공급처</th>' : ''}`}
          </tr></thead>
          <tbody>
            ${rows.map((r) => `<tr data-stock-lot="${r.lot_id}" tabindex="0" role="button" aria-label="${this.esc(r.item.name)} ${this.esc(r.lot_number)} 수불 조회" aria-pressed="${this.detailContext?.lotId === r.lot_id}" style="cursor:pointer;${this.detailContext?.lotId === r.lot_id ? 'background:var(--bg-elevated);outline:2px solid var(--brand-primary);outline-offset:-2px;' : ''}"
              onclick="InventoryApiPage.selectDetailLot(${r.lot_id})"
              onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();InventoryApiPage.selectDetailLot(${r.lot_id})}">
              ${compact?`<td style="font-family:monospace;color:var(--brand-primary)">${this.esc(r.lot_number)}</td>
              <td style="text-align:right;font-weight:700">${this.quantity(r.quantity,r.unit)}</td>
              <td>${this.lotStatus(r)}${r.use_priority?`<br><span style="font-size:0.75rem">${this.esc(r.use_priority)}순위</span>`:''}</td>
              <td>${this.expiryCell(r.expiration_date,r.expiration_status,r.days_to_expiry)}</td>
              <td>${this.esc((cfg.dateCol==='manufactured'?r.manufactured_date:r.received_date)||'-')}</td>`:`<td class="no-wrap">${this.esc(r.item.item_code)}</td>
              <td>${this.esc(r.item.name)}</td>
              <td class="no-wrap" style="font-family:monospace;color:var(--brand-primary);">${this.esc(r.lot_number)}</td>
              <td class="no-wrap">${this.esc((cfg.dateCol === 'manufactured' ? r.manufactured_date : r.received_date) || '-')}</td>
              <td>${this.expiryCell(r.expiration_date, r.expiration_status, r.days_to_expiry)}</td>
              <td>${this.lotStatus(r)}</td>
              <td class="no-wrap">${r.use_priority ? this.esc(r.use_priority) + '순위' : '—'}</td>
              <td style="text-align:right;font-weight:700;">${this.esc(r.quantity)}</td>
              <td>${this.esc(r.unit)}</td>
              ${cfg.dateCol === 'received' ? `<td>${this.esc(r.supplier_name || '-')}</td>` : ''}`}
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
      <div style="padding:0.6rem 1rem;border-top:1px solid var(--border-subtle);font-size:0.75rem;color:var(--text-muted);">
        LOT ${rows.length}건 · 우선순위는 품목별 사용 가능한 전체 LOT 기준(검색으로 순위 재부여 안 함). 현재 시스템 정책: 기한 있는 LOT 우선 → 날짜 없는 LOT은 입고일/제조일순, 날짜 미상은 마지막. 소비기한 당일까지 사용 가능.
      </div>
    </div>`;
  },

  renderLedger(data, direction=this.state().direction) {
    const lines = this.ledgerLines(data,direction);
    const rows = lines.map(({ item, lot, line }) => {
      const negative = String(line.quantity).startsWith('-');
      return `<tr data-ledger-lot="${lot.lot_id}" data-movement="${line.movement_id}">
        <td class="no-wrap">${this.esc(String(line.occurred_at).replace('T', ' ').slice(0, 19))}</td>
        <td>${this.esc(item.item.item_code)}</td><td><button type="button" class="inv-item-link" onclick="InventoryApiPage.openItem(${item.item.id})">${this.esc(item.item.name)}</button></td>
        <td class="no-wrap">${this.esc(lot.lot_number)}</td><td>${this.esc(line.movement_name)}${line.source?.receipt_status==='CANCELLED'?'<br><span class="badge badge-neutral">취소된 입고</span>':''}</td>
        <td style="text-align:right;">${negative ? '' : this.esc(line.quantity)}</td>
        <td style="text-align:right;">${negative ? this.esc(String(line.quantity).slice(1)) : ''}</td>
        <td style="text-align:right;">${this.esc(line.balance)}</td><td>${this.esc(item.unit)}</td>
        <td>${this.esc(line.staff_name)}</td><td>${this.esc(line.reason || '')}</td><td>${this.renderSourceLinks(line,lot.lot_id)}</td></tr>`;
    }).join('');
    return `<div class="card" style="padding:0;">
      <div style="padding:0.6rem 1rem;color:var(--text-muted);font-size:0.78rem;">${this.esc(data.from)} ~ ${this.esc(data.to)} · 개별 수불 ${lines.length}건 · 잔량은 각 수불 발생 직후의 LOT 잔량 · 취소 표시·정렬은 실제 잔량에 영향을 주지 않습니다.</div>
      <div class="table-wrapper" style="max-height:420px;overflow:auto;"><table class="data-table" id="invLedgerTable">
        <thead><tr><th>수불일자</th><th>품목코드</th><th>품목명</th><th>LOT 번호</th><th>구분</th><th>입고(+)</th><th>출고(-)</th><th>거래 직후 LOT 잔량</th><th>단위</th><th>처리자</th><th>사유</th><th>관련 기록</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="12" style="text-align:center;padding:2rem;">선택한 기간 안에 수불 이력이 없습니다. 현재 재고에는 이월 재고가 포함될 수 있습니다.</td></tr>'}</tbody>
      </table></div></div>`;
  },

  renderSourceLinks(line,lotId) {
    const source=line.source||{};
    return `${source.receipt_id?`<button class="inv-item-link" data-source-receipt="${source.receipt_id}" onclick="InventoryApiPage.openReceipt(${source.receipt_id})">입고 #${source.receipt_id}</button><br>`:''}${source.batch?`<button class="inv-item-link" data-source-batch="${source.batch.id}" onclick="InventoryApiPage.openBatch(${source.batch.id})">${this.esc(source.batch.number)}</button><br>`:''}${source.receipt_status==='CANCELLED'?'':`<button class="inv-item-link" data-source-docs="${lotId}" onclick="InventoryApiPage.openLinkedDocs(${lotId},${source.batch?.id||'null'})">연결 문서</button>`}`;
  },

  openBatch(id, tab='work') {
    App.closeModal(false);ProductionApiPage.s.batchId=id;ProductionApiPage.s.creating=false;ProductionApiPage.s.detailTab=tab;App.navigate('production-batches');
  },

  openLinkedDocs(lotId,batchId) {
    if(batchId) return this.openBatch(batchId,'documents');
    if(!window.TempEntry) return App.showToast('info','문서함','문서함에서 관련 LOT·배치를 확인하세요.');
    App.closeModal(false);
    window.TempEntry.open('temp-lot-docs',{lotId});
  },

  async openReceiptPicker(options = {}) {
    const context = this.receiptPicker = {offset: 0, limit: 20};
    const filters = {from: options.from ?? this.state().from, to: options.to ?? this.state().to, item_id: options.item_id || ''};
    App.showModal('입고 취소 · 입고 선택', '<p>입고 목록을 준비하는 중…</p>');
    App.trackInventoryModal?.({kind:'picker', ...filters, offset:options.offset || 0});
    document.getElementById('modalContainer').classList.add('inventory-detail-modal');
    const modal = document.querySelector('#modalContainer .modal-body');
    try {
      const items = await this.getJson('/items/');
      if (context !== this.receiptPicker || modal !== document.querySelector('#modalContainer .modal-body')) return;
      modal.innerHTML = `<p>취소할 입고의 품목·LOT·수량을 확인하고 <strong>선택</strong>을 누르세요. 취소 사유 입력 후 최종 확인할 수 있습니다.</p>
        <form id="receiptPickerFilters" style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end;margin-bottom:1rem;">
          ${this.field('품목', `<select name="item_id" class="form-control"><option value="">전체 품목</option>${items.results.filter(i => i.is_stock_managed && ['RAW', 'PACKAGING', 'SEMI'].includes(i.item_type)).map(i => `<option value="${i.id}" ${String(i.id)===filters.item_id?'selected':''}>${this.esc(i.item_code)} · ${this.esc(i.name)}</option>`).join('')}</select>`)}
          ${this.field('입고일 시작', `<input name="from" type="date" class="form-control" value="${this.esc(filters.from)}">`)}
          ${this.field('입고일 종료', `<input name="to" type="date" class="form-control" value="${this.esc(filters.to)}">`)}
          <button type="submit" class="btn btn-secondary">조회</button>
        </form>
        <p>미취소 입고를 표시합니다. 재고·결재 상태에 따른 취소 가능 여부는 취소 실행 시 검사합니다.</p>
        <div id="receiptPickerResults"></div>`;
      document.getElementById('receiptPickerFilters').addEventListener('submit', e => { e.preventDefault(); this.loadReceiptPicker(); });
      await this.loadReceiptPicker(options.offset || 0);
    } catch (error) {
      if (context === this.receiptPicker && modal === document.querySelector('#modalContainer .modal-body')) modal.innerHTML = `<p role="alert">${this.esc(error.message)}</p>`;
    }
  },

  async loadReceiptPicker(offset = 0) {
    const host = document.getElementById('receiptPickerResults');
    const form = document.getElementById('receiptPickerFilters');
    if (!host || !form) return;
    const context = this.receiptPicker;
    const serial = this.pickerSerial = (this.pickerSerial || 0) + 1;
    const params = Object.fromEntries(new FormData(form));
    if (params.from && params.to && params.from > params.to) { host.innerHTML = '<p role="alert">입고일 시작은 종료일 이전이어야 합니다.</p>'; return; }
    host.innerHTML = '<p>입고 목록을 불러오는 중…</p>';
    try {
      const data = await this.getJson('/receipts/', {...params, status: 'COMPLETED', limit: context.limit, offset});
      if (serial !== this.pickerSerial || context !== this.receiptPicker || host !== document.getElementById('receiptPickerResults')) return;
      context.offset = offset;
      host.innerHTML = this.renderReceiptPicker(data, context);
      App.trackInventoryModal?.({kind:'picker', ...params, offset});
    } catch (error) {
      if (serial === this.pickerSerial && host === document.getElementById('receiptPickerResults')) host.innerHTML = `<p role="alert">${this.esc(error.message)}</p>`;
    }
  },

  renderReceiptPicker(data, {offset, limit}) {
    if (!data.results.length) return '<p>조회 조건에 맞는 미취소 입고가 없습니다. 품목 또는 입고일을 변경해 주세요.</p>';
    return `<p>미취소 입고 ${data.count}건 · ${offset + 1}–${offset + data.results.length}번째</p>
      <div class="table-wrapper" style="max-height:45vh;overflow:auto;"><table class="data-table"><thead><tr><th>입고</th><th>입고일</th><th>품목</th><th>LOT</th><th>입고량</th><th>공급처</th><th>작업</th></tr></thead>
        <tbody>${data.results.map(r => `<tr><td>#${r.id}</td><td>${this.esc(r.received_date)}</td><td>${this.esc(r.item.item_code)} · ${this.esc(r.item.name)}</td><td>${this.esc(r.lot_number)}</td><td>${this.esc(r.quantity)} ${this.esc(r.unit)}</td><td>${this.esc(r.supplier.name)}</td><td><button class="btn btn-danger btn-sm" data-cancel-receipt="${r.id}" onclick="InventoryApiPage.openReceipt(${r.id}, true)">선택</button></td></tr>`).join('')}</tbody>
      </table></div>
      <div style="display:flex;gap:0.75rem;margin-top:1rem;">
        <button class="btn btn-secondary" ${offset === 0 ? 'disabled' : ''} onclick="InventoryApiPage.loadReceiptPicker(${Math.max(0, offset - limit)})">이전</button>
        <button class="btn btn-secondary" ${offset + data.results.length >= data.count ? 'disabled' : ''} onclick="InventoryApiPage.loadReceiptPicker(${offset + limit})">다음</button>
      </div>`;
  },

  async openReceipt(id, cancel = false) {
    const serial=this.receiptSerial=(this.receiptSerial||0)+1;
    App.showModal('입고 기록','<p>불러오는 중…</p>');
    App.trackInventoryModal?.({kind:'receipt', id:Number(id), cancel});
    const modal=document.querySelector('#modalContainer .modal-body');
    try {
      const r=await this.getJson(`/receipts/${id}/`);
      if(serial!==this.receiptSerial || modal!==document.querySelector('#modalContainer .modal-body') || !document.getElementById('modalContainer').classList.contains('active')) return;
      this.receiptDetail = r;
      modal.innerHTML = this.renderReceipt(r);
      if (cancel) await this.openReceiptCancel(id);
    } catch(error) { if(serial===this.receiptSerial && modal===document.querySelector('#modalContainer .modal-body')) modal.innerHTML=`<p role="alert">${this.esc(error.message)}</p>`; }
  },

  renderReceipt(r) {
    const cancelled = r.receipt_status === 'CANCELLED';
    return `<h3>${this.esc(r.item.name)} · 입고 #${r.id}</h3>
      <p>LOT ${this.esc(r.lot_number)} · 입고일 ${this.esc(r.received_date)}</p>
      <p>입고량 ${this.esc(r.quantity)} ${this.esc(r.unit)} · 공급처 ${this.esc(r.supplier.name)} · 처리자 ${this.esc(r.staff.name)}</p>
      <p>상태: ${cancelled ? '취소됨' : '입고 완료'}${cancelled ? ` · 취소 사유: ${this.esc(r.cancel_reason)}` : ''}</p>
      ${cancelled ? `<p>취소 시각: ${this.esc(r.cancelled_at || '')}</p><p>취소된 입고의 연결 문서는 일반 조회에서 제외됩니다. 입고와 수불의 취소 이력은 유지됩니다.</p>` : ''}
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
        <button class="btn btn-secondary" onclick="InventoryApiPage.openItem(${r.item.id})">품목 상세</button>
        ${!cancelled ? `<button class="btn btn-secondary" onclick="InventoryApiPage.openLinkedDocs(${r.lot_id},null)">입고 연결 문서</button>
        <button id="receiptCancelOpen" class="btn btn-danger" onclick="InventoryApiPage.openReceiptCancel(${r.id})">입고 취소</button>` : ''}
      </div>
      <div id="receiptCancelPanel"></div>`;
  },

  async openReceiptCancel(id) {
    if (this.receiptDetail?.id !== id || this.receiptDetail.receipt_status === 'CANCELLED') return;
    const panel = document.getElementById('receiptCancelPanel');
    if (!panel || this.receiptCancelling) return;
    App.trackInventoryModal?.({kind:'receipt', id:Number(id), cancel:true});
    const serial = this.receiptSerial;
    panel.innerHTML = '<p>담당자를 불러오는 중…</p>';
    try {
      const staff = await this.getJson('/staff/');
      if (serial !== this.receiptSerial || panel !== document.getElementById('receiptCancelPanel')) return;
      panel.innerHTML = `<form id="receiptCancelForm" style="margin-top:1rem;display:grid;gap:0.75rem;">
        <p>입고를 취소하면 잔여 입고 수량이 차감되고 관련 입고 서류도 함께 삭제됩니다. 입고·수불 이력은 유지됩니다.</p>
        <p>이미 사용·조정된 LOT 또는 결재 중·승인·정정 중인 문서가 있으면 취소할 수 없습니다.</p>
        ${this.field('취소 담당자', `<select name="staff_id" class="form-control" required><option value="">담당자를 선택하세요</option>${staff.results.map(s => `<option value="${s.id}">${this.esc(s.name)}</option>`).join('')}</select>`)}
        ${this.field('취소 사유', '<textarea name="reason" class="form-control" rows="3" required placeholder="취소 사유를 입력하세요"></textarea>')}
        <p id="receiptCancelError" role="alert" style="color:var(--color-danger);"></p>
        <div><button id="receiptCancelSave" type="submit" class="btn btn-danger">입고 취소 확인</button></div>
      </form>`;
      document.getElementById('receiptCancelForm').addEventListener('submit', e => { e.preventDefault(); this.cancelReceipt(id); });
      document.getElementById('receiptCancelOpen').disabled = true;
    } catch (error) {
      if (serial === this.receiptSerial && panel === document.getElementById('receiptCancelPanel')) panel.innerHTML = `<p role="alert">${this.esc(error.message)}</p>`;
    }
  },

  async cancelReceipt(id) {
    const form = document.getElementById('receiptCancelForm');
    const button = document.getElementById('receiptCancelSave');
    const errorBox = document.getElementById('receiptCancelError');
    const receipt = this.receiptDetail;
    if (!form || !button || this.receiptCancelling || receipt?.id !== id || !form.reportValidity()) return;
    const values = Object.fromEntries(new FormData(form));
    const reason = values.reason.trim();
    if (!reason) { errorBox.textContent = '취소 사유를 입력하세요.'; return; }
    if (!window.confirm(`${receipt.item.name} · LOT ${receipt.lot_number}\n입고량 ${receipt.quantity} ${receipt.unit}\n\n입고를 취소하고 관련 입고 서류도 함께 삭제하시겠습니까?`)) return;
    this.receiptCancelling = true;
    button.disabled = true;
    errorBox.textContent = '';
    const serial = this.receiptSerial;
    const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || '';
    try {
      const response = await fetch(`${this.API}/receipts/${id}/cancel/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
        body: JSON.stringify({ staff_id: Number(values.staff_id), reason }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || `요청 실패 (${response.status})`);
      App.showToast('success', '입고 취소 완료', '수불·재고에 취소를 반영하고 관련 입고 서류를 삭제했습니다.');
      this.load();
      const modal = document.querySelector('#modalContainer .modal-body');
      if (serial === this.receiptSerial && form === document.getElementById('receiptCancelForm') && modal) {
        this.receiptDetail = result;
        modal.innerHTML = this.renderReceipt(result);
        App.trackInventoryModal?.({kind:'receipt', id:Number(id), cancel:false});
      }
      window.TempEntry?.refreshBadges?.();
    } catch (error) {
      if (form === document.getElementById('receiptCancelForm')) errorBox.textContent = error.message;
    } finally {
      this.receiptCancelling = false;
      button.disabled = false;
    }
  },

};
