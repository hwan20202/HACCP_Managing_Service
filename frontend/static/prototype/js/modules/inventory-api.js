// =============================================
// 재고장 · 수불일지 — /api/v1/inventory/ 연결 화면
// (docs/inventory-frontend.md: 시제품 틀·디자인은 그대로, 재고 데이터만 API 로)
//
// - 수불대장: 수불 내역 / 현재고 탭. 품목 선택은 전체 LOT, LOT 선택은 해당 이력
// - 별도 현황 메뉴: 입출고(왼쪽) + LOT별 현재고(오른쪽), 엑셀 2개 시트
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
  mode: 'ledger',
  overviewType: 'raw',
  states: {},
  items: {},

  state() {
    const key = `${this.mode}:${this.type}`;
    if (!this.states[key]) {
      const today = this.today();
      this.states[key] = {
        selectedLot: null, selectedItem: null, tab: this.mode === 'overview' ? 'overview' : 'ledger', period: 'month', q: '', direction: '', lowOnly: false, expiryDays: '', displayUnit: '',
        itemId: '',
        lotNumber: '',
        expirationStatus: '',
        includeEmpty: false,
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
  render(type = 'raw', mode = 'ledger') {
    this.type = type;
    this.mode = mode;
    const cfg = this.TYPES[type];
    setTimeout(() => this.load(), 0);
    return `
    <style>
      #invApiPage .inv-overview { display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:0.85rem;align-items:start; }
      #invApiPage .inv-panel { min-width:0;padding:0;overflow:hidden; }
      #invApiPage .inv-panel-head { padding:0.85rem 1rem;border-bottom:1px solid var(--border-subtle); }
      #invApiPage .inv-panel-head h2 { font-size:0.95rem;margin:0 0 0.35rem; }
      #invApiPage .inv-panel-head p { font-size:0.76rem;color:var(--text-muted);margin:0; }
      #invApiPage .inv-overview .table-wrapper { overflow:auto;max-height:65vh; }
      #invApiPage .inv-item-group td { background:var(--bg-elevated,#eef2f6);font-weight:700; }
      #invApiPage .inv-selected { background:var(--bg-elevated,#eef3ff);outline:2px solid var(--brand-primary);outline-offset:-2px; }
      #invApiPage .inv-overview td, #invApiPage .inv-overview th { padding:0.6rem; }
      .inv-item-link { border:0;background:none;color:var(--brand-primary);padding:0.25rem 0;font:inherit;text-align:left;cursor:pointer; }
      .inv-item-link:hover, .inv-item-link:focus-visible { text-decoration:underline; }
      .modal-container.inventory-detail-modal { width:calc(100vw - 2rem);max-width:1200px; }
      .inventory-detail-modal .data-table { min-width:1050px; }
      .inventory-detail-modal .data-table td, .inventory-detail-modal .data-table th { white-space:nowrap; }
      @media(max-width:1100px) { #invApiPage .inv-overview {grid-template-columns:minmax(0,1fr);} }
    </style>
    <div class="fade-in" id="invApiPage">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">${mode === 'overview' ? '재고·수불 현황' : cfg.title}</h1>
          <p class="page-desc">${mode === 'overview' ? '품목별 입출고와 LOT별 현재 잔량을 함께 비교합니다.' : '수불 내역과 품목별 현재고를 조회합니다. 품목명을 누르면 전체 LOT와 이력을 확인할 수 있습니다.'}</p>
        </div>
        <div class="page-actions">
          ${window.HACCP_SITE?.qa ? '<button id="qaReceiptOpen" class="btn btn-primary" onclick="InventoryApiPage.openQaReceipt()">QA 입고 등록</button>' : ''}
          <button class="btn btn-secondary" onclick="InventoryApiPage.load()">새로고침</button>
          <button class="btn btn-secondary" id="invExport" onclick="InventoryApiPage.exportExcel()">엑셀 다운로드</button>
          <button class="btn btn-secondary" id="invSwitchView" onclick="InventoryApiPage.switchView()">${mode === 'overview' ? '수불대장으로' : '재고·수불 현황'}</button>
        </div>
      </div>
      ${mode === 'overview' ? `<label style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem">품목 구분 <select id="invOverviewType" class="form-control" style="width:auto" onchange="InventoryApiPage.changeOverviewType(this.value)">${[['raw','원료'],['sub','부자재'],['finished','반제품·완제품']].map(([v,l])=>`<option value="${v}" ${type===v?'selected':''}>${l}</option>`).join('')}</select></label>` : `<div class="tabs" style="margin-bottom:0.75rem;">
        ${[['ledger','수불 내역'],['stock','현재고']].map(([v,l]) => `<button class="tab-btn ${this.state().tab === v ? 'active' : ''}" onclick="InventoryApiPage.set('tab','${v}')">${l}</button>`).join('')}
      </div>`}
      <div class="card" style="padding:0.75rem;margin-bottom:0.75rem;">
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:flex-end;">${this.renderFilters()}</div>
        <p style="margin:0.6rem 0 0;font-size:0.78rem;color:var(--text-muted);">${mode === 'overview' ? '검색은 양쪽 표에 적용됩니다. 조회 기간·입출고 구분은 왼쪽에만 적용되며, 현재고는 지금의 잔량입니다.' : '수불 내역은 선택한 기간의 기록이며, 현재고는 지금의 잔량입니다.'}</p>
      </div>
      <div id="invApiContent"><div class="empty-state"><p>불러오는 중…</p></div></div>
    </div>`;
  },

  field(label, html) {
    return `<label style="display:flex;flex-direction:column;gap:0.2rem;font-size:0.72rem;color:var(--text-muted);font-weight:600;">${label}${html}</label>`;
  },

  renderOverviewPage() { return this.render(this.overviewType, 'overview'); },
  changeOverviewType(type) { this.overviewType=type; this.type=type; this.rerender(); },
  switchView() {
    if(this.mode==='overview') App.navigate({raw:'raw-materials',sub:'sub-materials',finished:'finished-goods'}[this.type]);
    else { this.overviewType=this.type; App.navigate('inventory-overview'); }
  },

  renderFilters() {
    const s = this.state();
    const search = this.field('검색', `<input id="invSearch" type="search" class="form-control" style="min-width:260px" value="${this.esc(s.q)}" placeholder="품목코드 · 품목명 · 공급처 · LOT" oninput="InventoryApiPage.search(this.value)">`);
    if (s.tab === 'stock') return `${search}
      <label><input type="checkbox" ${s.lowOnly ? 'checked' : ''} onchange="InventoryApiPage.set('lowOnly',this.checked)"> 부족 품목만</label>
      ${this.field('소비기한', `<select class="form-control" onchange="InventoryApiPage.set('expiryDays',this.value)">${[['','전체'],['7','경과·7일 이내'],['30','경과·30일 이내'],['90','경과·90일 이내']].map(([v,l])=>`<option value="${v}" ${s.expiryDays===v?'selected':''}>${l}</option>`).join('')}</select>`)}
      ${this.field('표시 단위', `<select class="form-control" onchange="InventoryApiPage.set('displayUnit',this.value)">${[['','기준 단위'],['kg','kg'],['g','g']].map(([v,l])=>`<option value="${v}" ${s.displayUnit===v?'selected':''}>${l}</option>`).join('')}</select>`)}`;
    return `${search}
      <div style="display:flex;gap:0.3rem;flex-wrap:wrap">${[['','전체'],['IN','입고'],['OUT','출고']].map(([v,l])=>`<button class="btn ${s.direction===v?'btn-primary':'btn-secondary'} btn-sm" onclick="InventoryApiPage.set('direction','${v}')">${l}</button>`).join('')}</div>
      <div style="display:flex;gap:0.3rem;flex-wrap:wrap">${[['today','오늘'],['month','이번 달'],['3month','3개월'],['6month','6개월'],['year','1년']].map(([v,l])=>`<button data-period="${v}" aria-pressed="${s.period===v}" class="btn ${s.period===v?'btn-primary':'btn-secondary'} btn-sm" onclick="InventoryApiPage.setPeriod('${v}')">${l}</button>`).join('')}</div>
      ${this.field('조회 기간', `<span style="display:flex;gap:0.3rem"><input id="invFrom" type="date" class="form-control" value="${s.from}" onchange="InventoryApiPage.set('from',this.value)"> ~ <input id="invTo" type="date" class="form-control" value="${s.to}" onchange="InventoryApiPage.set('to',this.value)"></span>`)}
      <details><summary style="cursor:pointer">상세 조건</summary><label>LOT 번호 <input class="form-control" value="${this.esc(s.lotNumber)}" onchange="InventoryApiPage.set('lotNumber',this.value)"></label><label><input id="invIncludeEmpty" type="checkbox" ${s.includeEmpty?'checked':''} onchange="InventoryApiPage.set('includeEmpty',this.checked)"> 소진 LOT도 현재고에 표시</label></details>`;
  },

  search(value) {
    this.state().q = value;
    this.state().selectedLot = null;
    this.state().itemId = '';
    this.state().selectedItem = null;
    this.loadSerial = (this.loadSerial || 0) + 1;
    this.cache = null;
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.load(), 250);
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
    if(this.mode!=='overview') { s.selectedItem=null; s.itemId=''; s.q=''; s.lotNumber=''; }
    s.tab = this.mode === 'overview' ? 'overview' : 'ledger';
    this.rerender();
  },

  rerender() {
    const container = document.getElementById('pageContainer');
    if (container) container.innerHTML = this.render(this.type, this.mode);
  },

  // ---------- 데이터 ----------
  async load() {
    const host = document.getElementById('invApiPage');
    if (!host) return;
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
      } else if (s.tab === 'overview') {
        const [data, stock] = await Promise.all([this.fetchLedger(), this.fetchStock()]);
        if (!current()) return;
        this.cache = {tab:'overview', data, stock};
        this.stockRows = stock.results;
        document.getElementById('invApiContent').innerHTML = this.renderOverview(data, stock);
      } else {
        const [stock, totals] = await Promise.all([this.fetchStock(), this.getJson('/stock/items/', {item_type:this.TYPES[this.type].itemTypes.join(',')})]);
        if (!current()) return;
        const matches = new Set(stock.results.map(r=>r.item.id));
        const query=s.q.trim().toLowerCase();
        const filtered = totals.results.filter(r=>(!query || `${r.item.item_code} ${r.item.name}`.toLowerCase().includes(query) || matches.has(r.item.id)) && (!s.expiryDays || matches.has(r.item.id)) && (!s.lowOnly || r.below_minimum));
        this.stockRows = stock.results;
        this.cache = {tab:'stock', data:{results:filtered}};
        document.getElementById('invApiContent').innerHTML = this.renderTotals({results:filtered});
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
    const type = this.type;
    const mode = this.mode;
    const serial = this.itemSerial = (this.itemSerial || 0) + 1;
    App.showModal('품목 LOT · 수불 이력', '<p>불러오는 중…</p>');
    const modal = document.querySelector('#modalContainer .modal-body');
    try {
      const s=this.state();
      const [data, ledger] = await Promise.all([
        this.getJson('/stock/lots/', {item_id:id, include_empty:true}),
        this.getJson('/ledger/', {item_id:id,from:s.from,to:s.to}),
      ]);
      if (serial !== this.itemSerial || type !== this.type || mode !== this.mode || modal !== document.querySelector('#modalContainer .modal-body') || !document.getElementById('modalContainer').classList.contains('active')) return;
      this.stockRows = data.results;
      const item=data.results[0]?.item || ledger.results[0]?.item || this.cache?.data.results.find(r=>r.item.id===id)?.item;
      if(item) this.itemDetail=item;
      App.showModal('품목 LOT · 수불 이력', `<h3>${item?`${this.esc(item.item_code)} ${this.esc(item.name)}`:'선택 품목'} · 전체 LOT</h3><p>위 표는 현재 잔량, 아래 표는 ${this.esc(s.from)} ~ ${this.esc(s.to)} 입출고 내역입니다. LOT를 누르면 해당 LOT만 조회합니다.</p>${this.renderStock(data)}${this.renderLedger(ledger,'')}<button class="btn btn-primary" onclick="InventoryApiPage.viewItemLedger(${id})">품목 전체 수불 보기</button>`);
      document.getElementById('modalContainer').classList.add('inventory-detail-modal');
    } catch(error) { App.showToast('error','LOT 조회 실패',error.message); }
  },

  viewItemLedger(id) {
    App.closeModal();
    const s=this.state();
    const item=this.itemDetail?.id===id?this.itemDetail:this.cache?.data.results.find(r=>r.item.id===id)?.item;
    s.itemId=String(id); s.selectedItem=item || null; s.tab=this.mode==='overview'?'overview':'ledger'; s.selectedLot=null; s.q=''; s.lotNumber='';
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

  // Hosted QA uses the business API with DEBUG=false; no /api/dev/ dependency.
  async openQaReceipt() {
    try {
      const [items, suppliers, staff] = await Promise.all([
        this.getJson('/items/'), this.getJson('/suppliers/'), this.getJson('/staff/'),
      ]);
      const options = (rows, label) => rows.map((r) => `<option value="${r.id}">${this.esc(label(r))}</option>`).join('');
      this.qaReceiptKey = crypto.randomUUID();
      this.receiptItems = items.results.filter(i=>i.is_stock_managed && ['RAW','PACKAGING','SEMI'].includes(i.item_type));
      this.receiptType = this.type === 'sub' ? 'PACKAGING' : this.type === 'finished' ? 'SEMI' : 'RAW';
      App.showModal('QA 입고 등록', `<form id="qaReceiptForm">
        <p>검증용 입고입니다. 저장하면 수불·재고와 입고 문서 3종이 연결됩니다.</p>
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
        <button type="submit" id="qaReceiptSave" class="btn btn-primary">QA 입고 저장</button>
      </form>`);
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
      <div class="table-wrapper"><table class="data-table" id="invStockTable"><thead><tr><th>품목코드</th><th>품목명</th><th>총재고</th><th>사용 가능</th><th>사용 불가</th><th>최소재고</th><th>상태</th><th>LOT 수</th><th>가장 빠른 소비기한</th></tr></thead><tbody>
      ${data.results.map(r=>`<tr><td>${this.esc(r.item.item_code)}</td><td><button class="btn btn-secondary btn-sm" onclick="InventoryApiPage.openItem(${r.item.id})">${this.esc(r.item.name)}</button></td><td>${this.quantity(r.total,r.unit)}</td><td>${this.quantity(r.usable,r.unit)}</td><td>${this.quantity(this.addQuantities(r.quarantine,r.unusable),r.unit)}</td><td>${this.quantity(r.minimum_stock,r.unit)}</td><td>${r.below_minimum?'<span class="badge badge-danger">부족</span>':'<span class="badge badge-success">정상</span>'}</td><td>${r.lot_count}</td><td>${this.esc(r.nearest_expiration || '-')}</td></tr>`).join('') || '<tr><td colspan="9">조회 결과가 없습니다.</td></tr>'}
      </tbody></table></div><p style="font-size:0.78rem;color:var(--text-muted)">사용 불가에는 검사대기·부적합·보류·소비기한 경과 재고가 포함됩니다. 품목명을 누르면 LOT를 확인할 수 있습니다.</p>`;
  },

  ledgerLines(data, direction=this.state().direction) {
    return data.results.flatMap(item=>item.lots.flatMap(lot=>lot.lines.map(line=>({item,lot,line}))))
      .filter(r=>!direction || (direction==='OUT')===String(r.line.quantity).startsWith('-'))
      .sort((a,b)=>b.line.occurred_at.localeCompare(a.line.occurred_at) || b.line.movement_id-a.line.movement_id);
  },

  overviewEntries(data) {
    const entries = this.ledgerLines(data).map(r => ({...r, opening:false}));
    if (!this.state().direction) {
      for (const item of data.results) for (const lot of item.lots) {
        if (Number(lot.opening) !== 0) entries.push({item,lot,opening:true,line:{
          occurred_at:data.from, movement_id:0, movement_name:'이월',
          quantity:'0', balance:lot.opening, staff_name:'', reason:'조회 시작일 이전 잔량',
        }});
      }
    }
    return entries.sort((a,b)=>a.item.item.item_code.localeCompare(b.item.item.item_code) ||
      Number(b.opening)-Number(a.opening) || a.line.occurred_at.localeCompare(b.line.occurred_at) ||
      a.line.movement_id-b.line.movement_id || a.lot.lot_id-b.lot.lot_id);
  },

  renderOverview(data, stock) {
    const s=this.state();
    const entries=this.overviewEntries(data);
    let previous=null;
    const movements=entries.map(({item,lot,line,opening})=>{
      const group=previous!==item.item.id;
      previous=item.item.id;
      const negative=String(line.quantity).startsWith('-');
      return `${group?`<tr class="inv-item-group"><td colspan="5">${this.esc(item.item.item_code)} ${this.esc(item.item.name)} <span style="font-weight:400">(${this.esc(item.unit)})</span></td></tr>`:''}
        <tr data-ledger-lot="${lot.lot_id}" ${opening?'data-opening="true"':`data-movement="${line.movement_id}"`}>
          <td class="no-wrap" title="${this.esc(line.movement_name)} · ${this.esc(line.reason||'')}">${opening?'이월':this.esc(line.occurred_at.replace('T',' ').slice(0,16))}</td>
          <td class="no-wrap">${this.esc(lot.lot_number)}</td>
          <td style="text-align:right">${opening||negative?'':this.esc(line.quantity)}</td>
          <td style="text-align:right">${negative?this.esc(String(line.quantity).slice(1)):''}</td>
          <td style="text-align:right">${this.esc(line.balance)}</td>
        </tr>`;
    }).join('');
    const selected=s.selectedLot;
    const selection=this.renderSelection();
    const stocks=stock.results.map(r=>`<tr data-stock-lot="${r.lot_id}" tabindex="0" role="button" aria-pressed="${selected?.id===r.lot_id}" class="${selected?.id===r.lot_id?'inv-selected':''}" style="cursor:pointer" aria-label="${this.esc(r.item.item_code)} ${this.esc(r.lot_number)} 수불 조회" onclick="InventoryApiPage.selectStockLot(${r.lot_id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();InventoryApiPage.selectStockLot(${r.lot_id})}">
      <td>${this.esc(r.item.item_code)}<br><span style="font-size:0.75rem;color:var(--text-muted)">${this.esc(r.item.name)}</span></td>
      <td class="no-wrap">${this.esc(r.lot_number)}</td><td style="text-align:right;font-weight:700" data-current-quantity="${this.esc(r.quantity)}">${this.esc(r.quantity)} <span style="font-weight:400">${this.esc(r.unit)}</span></td>
      <td>${this.lotStatus(r)}</td></tr>`).join('');
    return `<div class="inv-overview">
      <section class="card inv-panel" aria-labelledby="invMovementHeading"><div class="inv-panel-head">
        <h2 id="invMovementHeading">품목별 입출고 내역</h2><p>${this.esc(data.from)} ~ ${this.esc(data.to)} · 수불 ${entries.filter(r=>!r.opening).length}건 · 잔량은 해당 수불 직후의 LOT 기준</p>${selection}
        </div><div class="table-wrapper"><table class="data-table" id="invLedgerTable"><thead><tr><th>수불일자</th><th>LOT</th><th>입고</th><th>출고</th><th>LOT 잔량</th></tr></thead><tbody>${movements||'<tr><td colspan="5" style="padding:2rem;text-align:center">선택한 조건의 입출고 내역이 없습니다.</td></tr>'}</tbody></table></div></section>
      <section class="card inv-panel" aria-labelledby="invCurrentHeading"><div class="inv-panel-head">
        <h2 id="invCurrentHeading">LOT별 현재 재고</h2><p>현재 잔량 · ${stock.results.length}개 LOT · 행을 누르면 왼쪽에서 해당 LOT의 수불을 확인합니다.</p>
        </div><div class="table-wrapper"><table class="data-table" id="invCurrentStockTable"><thead><tr><th>품목코드 · 품목명</th><th>LOT</th><th>현재고</th><th>상태</th></tr></thead><tbody>${stocks||'<tr><td colspan="4" style="padding:2rem;text-align:center">선택한 조건의 현재 재고가 없습니다.</td></tr>'}</tbody></table></div></section>
    </div>`;
  },

  exportExcel() {
    const c=this.cache;
    if (!c) return App.showToast('info','조회 중','검색 결과가 표시된 후 내려받으세요.');
    let headers, rows;
    if(c.tab!=='stock') {
      headers=['수불일자','품목코드','품목명','LOT','구분','입고','출고','수불 후 LOT 잔량','단위','담당자','사유'];
      rows=(c.tab==='overview'?this.overviewEntries(c.data):this.ledgerLines(c.data)).map(({item,lot,line,opening})=>[opening?'이월':line.occurred_at,item.item.item_code,item.item.name,lot.lot_number,line.movement_name,opening||String(line.quantity).startsWith('-')?'':line.quantity,String(line.quantity).startsWith('-')?String(line.quantity).slice(1):'',line.balance,item.unit,line.staff_name,line.reason||'']);
    } else {
      headers=['품목코드','품목명','총재고','사용 가능','사용 불가','최소재고','단위','LOT 수'];
      rows=c.data.results.map(r=>[r.item.item_code,r.item.name,r.total,r.usable,this.addQuantities(r.quarantine,r.unusable),r.minimum_stock,r.unit,r.lot_count]);
    }
    const overview=c.tab==='overview';
    const transactions=c.tab!=='stock';
    const numeric=transactions?[5,6,7]:[2,3,4,5,7];
    const sheets=[{name:transactions?'입출고 내역':'품목별 합계',title:this.TYPES[this.type].title,subtitle:`${transactions?`${this.state().from} ~ ${this.state().to} · ${this.state().direction==='IN'?'입고':this.state().direction==='OUT'?'출고':'전체'}${this.state().selectedLot?' · LOT '+this.state().selectedLot.number:''}${this.state().selectedItem?' · '+this.state().selectedItem.name:''}`:'현재고 · 기준 단위'} / 검색: ${this.state().q || '전체'}`,columns:headers.map((header,i)=>({header,width:20,type:numeric.includes(i)?'number':'text'})),rows}];
    if(overview) sheets.push({name:'LOT별 현재고',title:'LOT별 현재 재고',subtitle:`조회 시점 현재 잔량 · 검색: ${this.state().q||'전체'}`,columns:['품목코드','품목명','LOT','현재고','단위','상태','소비기한'].map((header,i)=>({header,width:20,type:i===3?'number':'text'})),rows:c.stock.results.map(r=>[r.item.item_code,r.item.name,r.lot_number,r.quantity,r.unit,r.can_use?'사용가능':this.lotStatusLabel(r),r.expiration_date||(r.expiration_status==='NONE'?'없음':'미확인')])});
    XlsxWriter.download(`수불재고_${this.today()}.xlsx`,sheets);
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
      App.closeModal();
      App.showToast('success', 'QA 입고 완료', '수불·재고·문서가 연결되었습니다. 문서함에서 입고 문서를 확인하세요.');
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

  renderStock(data) {
    const rows = data.results;
    const cfg = this.TYPES[this.type];
    if (!rows.length) return `<div class="empty-state"><h3>재고가 있는 LOT이 없습니다</h3><p>조건을 바꾸거나 '재고 0인 LOT 포함'을 선택하세요.</p></div>`;
    const dateHead = cfg.dateCol === 'manufactured' ? '제조일' : '입고일';
    return `
    <div class="card" style="padding:0;">
      <div class="table-wrapper" style="max-height:340px;overflow:auto;">
        <table class="data-table">
          <thead><tr>
            <th>품목코드</th><th>품목명</th><th>LOT 번호</th><th>${dateHead}</th><th>소비기한</th>
            <th>상태</th><th>사용 우선순위</th><th style="text-align:right;">현재고</th><th>단위</th>${cfg.dateCol === 'received' ? '<th>공급처</th>' : ''}
          </tr></thead>
          <tbody>
            ${rows.map((r) => `<tr data-stock-lot="${r.lot_id}" tabindex="0" role="button" aria-label="${this.esc(r.item.name)} ${this.esc(r.lot_number)} 수불 조회" aria-pressed="${this.state().selectedLot?.id === r.lot_id}" style="cursor:pointer;${this.state().selectedLot?.id === r.lot_id ? 'background:var(--bg-elevated);outline:2px solid var(--brand-primary);outline-offset:-2px;' : ''}"
              onclick="InventoryApiPage.selectStockLot(${r.lot_id})"
              onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();InventoryApiPage.selectStockLot(${r.lot_id})}">
              <td class="no-wrap">${this.esc(r.item.item_code)}</td>
              <td>${this.esc(r.item.name)}</td>
              <td class="no-wrap" style="font-family:monospace;color:var(--brand-primary);">${this.esc(r.lot_number)}</td>
              <td class="no-wrap">${this.esc((cfg.dateCol === 'manufactured' ? r.manufactured_date : r.received_date) || '-')}</td>
              <td>${this.expiryCell(r.expiration_date, r.expiration_status, r.days_to_expiry)}</td>
              <td>${this.lotStatus(r)}</td>
              <td class="no-wrap">${r.use_priority ? this.esc(r.use_priority) + '순위' : '—'}</td>
              <td style="text-align:right;font-weight:700;">${this.esc(r.quantity)}</td>
              <td>${this.esc(r.unit)}</td>
              ${cfg.dateCol === 'received' ? `<td>${this.esc(r.supplier_name || '-')}</td>` : ''}
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
    lines.sort((a, b) => b.line.occurred_at.localeCompare(a.line.occurred_at) || b.line.movement_id - a.line.movement_id);
    const rows = lines.map(({ item, lot, line }) => {
      const negative = String(line.quantity).startsWith('-');
      return `<tr data-ledger-lot="${lot.lot_id}" data-movement="${line.movement_id}">
        <td class="no-wrap">${this.esc(String(line.occurred_at).replace('T', ' ').slice(0, 19))}</td>
        <td>${this.esc(item.item.item_code)}</td><td><button type="button" class="inv-item-link" onclick="InventoryApiPage.openItem(${item.item.id})">${this.esc(item.item.name)}</button></td>
        <td class="no-wrap">${this.esc(lot.lot_number)}</td><td>${this.esc(line.movement_name)}</td>
        <td style="text-align:right;">${negative ? '' : this.esc(line.quantity)}</td>
        <td style="text-align:right;">${negative ? this.esc(String(line.quantity).slice(1)) : ''}</td>
        <td style="text-align:right;">${this.esc(line.balance)}</td><td>${this.esc(item.unit)}</td>
        <td>${this.esc(line.staff_name)}</td><td>${this.esc(line.reason || '')}</td></tr>`;
    }).join('');
    return `<div class="card" style="padding:0;">
      <div style="padding:0.6rem 1rem;color:var(--text-muted);font-size:0.78rem;">${this.esc(data.from)} ~ ${this.esc(data.to)} · 개별 수불 ${lines.length}건 · 잔량은 각 수불 발생 직후의 LOT 잔량</div>
      <div class="table-wrapper" style="max-height:420px;overflow:auto;"><table class="data-table" id="invLedgerTable">
        <thead><tr><th>수불일자</th><th>품목코드</th><th>품목명</th><th>LOT 번호</th><th>구분</th><th>입고(+)</th><th>출고(-)</th><th>수불 후 LOT 잔량</th><th>단위</th><th>담당자</th><th>사유</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="11" style="text-align:center;padding:2rem;">선택한 기간 안에 수불 이력이 없습니다. 현재 재고에는 이월 재고가 포함될 수 있습니다.</td></tr>'}</tbody>
      </table></div></div>`;
  },

  selectStockLot(id) {
    const row = (this.stockRows || []).find((r) => r.lot_id === id);
    if (row) { App.closeModal(); this.selectLot(row.lot_id, row.lot_number, row.item); }
  },
};
