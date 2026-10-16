// =============================================
// 재고장 · 수불일지 — /api/v1/inventory/ 연결 화면
// (docs/inventory-frontend.md: 시제품 틀·디자인은 그대로, 재고 데이터만 API 로)
//
// - 한 화면: LOT별 현재고(stock/lots)와 기간별 개별 수불(ledger), CSV 내려받기
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
      desc: '입출고 내역과 품목별 현재 재고를 확인합니다.',
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
    if (!this.states[this.type]) {
      const today = this.today();
      this.states[this.type] = {
        selectedLot: null, tab: 'ledger', q: '', direction: '', lowOnly: false, expiryDays: '', displayUnit: '',
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
    return this.states[this.type];
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
    <div class="fade-in" id="invApiPage">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">${cfg.title}</h1>
          <p class="page-desc">${cfg.desc}</p>
        </div>
        <div class="page-actions">
          ${window.HACCP_SITE?.qa ? '<button id="qaReceiptOpen" class="btn btn-primary" onclick="InventoryApiPage.openQaReceipt()">QA 입고 등록</button>' : ''}
          <button class="btn btn-secondary" onclick="InventoryApiPage.load()">새로고침</button>
          <button class="btn btn-secondary" id="invExport" onclick="InventoryApiPage.exportExcel()">엑셀 다운로드</button>
        </div>
      </div>
      <div class="tabs" style="margin-bottom:0.75rem;">
        ${[['ledger','수불 내역'],['stock','현재고']].map(([v,l]) => `<button class="tab-btn ${this.state().tab === v ? 'active' : ''}" onclick="InventoryApiPage.set('tab','${v}')">${l}</button>`).join('')}
      </div>
      <div class="card" style="padding:0.75rem;margin-bottom:0.75rem;">
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:flex-end;">${this.renderFilters()}</div>
        <p style="margin:0.6rem 0 0;font-size:0.78rem;color:var(--text-muted);">현재고는 지금의 잔량입니다. 품목을 선택하면 LOT와 수불 이력을 확인할 수 있습니다.</p>
      </div>
      <div id="invApiContent"><div class="empty-state"><p>불러오는 중…</p></div></div>
    </div>`;
  },

  field(label, html) {
    return `<label style="display:flex;flex-direction:column;gap:0.2rem;font-size:0.72rem;color:var(--text-muted);font-weight:600;">${label}${html}</label>`;
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
      <div style="display:flex;gap:0.3rem;flex-wrap:wrap">${[['today','오늘'],['month','이번 달'],['3month','3개월'],['6month','6개월'],['year','1년']].map(([v,l])=>`<button class="btn btn-secondary btn-sm" onclick="InventoryApiPage.setPeriod('${v}')">${l}</button>`).join('')}</div>
      ${this.field('조회 기간', `<span style="display:flex;gap:0.3rem"><input id="invFrom" type="date" class="form-control" value="${s.from}" onchange="InventoryApiPage.set('from',this.value)"> ~ <input id="invTo" type="date" class="form-control" value="${s.to}" onchange="InventoryApiPage.set('to',this.value)"></span>`)}
      <details><summary style="cursor:pointer">상세 조건</summary><label>LOT 번호 <input class="form-control" value="${this.esc(s.lotNumber)}" onchange="InventoryApiPage.set('lotNumber',this.value)"></label></details>`;
  },

  search(value) {
    this.state().q = value;
    this.state().selectedLot = null;
    this.state().itemId = '';
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
    this.rerender();
  },

  // ---------- 이벤트 ----------
  set(key, value) {
    const s = this.state();
    s[key] = value;
    this.cache = null;
    if (key === 'tab') { s.selectedLot = null; s.itemId = ''; }
    // Search changes must not leave an invisible selected LOT restricting the ledger.
    if (['itemId', 'lotNumber', 'expirationStatus', 'madeFrom', 'madeTo', 'includeEmpty', 'usableOnly'].includes(key)) s.selectedLot = null;
    this.rerender();
  },

  selectLot(id, number = '') {
    const s = this.state();
    s.selectedLot = id ? { id: Number(id), number } : null;
    s.tab = 'ledger';
    this.rerender();
  },

  rerender() {
    const container = document.getElementById('pageContainer');
    if (container) container.innerHTML = this.render(this.type);
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
        const data = await this.fetchLedger();
        if (!current()) return;
        this.cache = {tab:'ledger', data};
        const selection = s.selectedLot || s.itemId ? `<button class="btn btn-secondary btn-sm" onclick="InventoryApiPage.clearSelection()">품목·LOT 선택 해제</button>` : '';
        document.getElementById('invApiContent').innerHTML = selection + this.renderLedger(data);
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

  clearSelection() { this.state().itemId=''; this.state().selectedLot=null; this.rerender(); },

  async openItem(id) {
    const type = this.type;
    const serial = this.itemSerial = (this.itemSerial || 0) + 1;
    App.showModal('품목 LOT · 수불 이력', '<p>불러오는 중…</p>');
    const modal = document.querySelector('#modalContainer .modal-body');
    try {
      const data = await this.getJson('/stock/lots/', {item_id:id, include_empty:true});
      if (serial !== this.itemSerial || type !== this.type || modal !== document.querySelector('#modalContainer .modal-body') || !document.getElementById('modalContainer').classList.contains('active')) return;
      this.stockRows = data.results;
      App.showModal('품목 LOT · 수불 이력', `<p>LOT를 선택하면 해당 수불 이력을 조회합니다.</p>${this.renderStock(data)}<button class="btn btn-primary" onclick="InventoryApiPage.viewItemLedger(${id})">품목 전체 수불 보기</button>`);
    } catch(error) { App.showToast('error','LOT 조회 실패',error.message); }
  },

  viewItemLedger(id) {
    App.closeModal();
    const s=this.state();
    s.itemId=String(id); s.tab='ledger'; s.selectedLot=null; s.q='';
    this.rerender();
  },

  fetchStock() {
    const s = this.state();
    return this.getJson('/stock/lots/', {
      item_type: this.TYPES[this.type].itemTypes.join(','),
      item_id: s.itemId,
      q: s.q.trim(),
      expiring_within_days: s.expiryDays,
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

  ledgerLines(data) {
    const direction=this.state().direction;
    return data.results.flatMap(item=>item.lots.flatMap(lot=>lot.lines.map(line=>({item,lot,line}))))
      .filter(r=>!direction || (direction==='OUT')===String(r.line.quantity).startsWith('-'))
      .sort((a,b)=>b.line.occurred_at.localeCompare(a.line.occurred_at) || b.line.movement_id-a.line.movement_id);
  },

  exportExcel() {
    const c=this.cache;
    if (!c) return App.showToast('info','조회 중','검색 결과가 표시된 후 내려받으세요.');
    let headers, rows;
    if(c.tab==='ledger') {
      headers=['수불일자','품목코드','품목명','LOT','구분','입고','출고','수불 후 LOT 잔량','단위','담당자','사유'];
      rows=this.ledgerLines(c.data).map(({item,lot,line})=>[line.occurred_at,item.item.item_code,item.item.name,lot.lot_number,line.movement_name,String(line.quantity).startsWith('-')?'':line.quantity,String(line.quantity).startsWith('-')?String(line.quantity).slice(1):'',line.balance,item.unit,line.staff_name,line.reason||'']);
    } else {
      headers=['품목코드','품목명','총재고','사용 가능','사용 불가','최소재고','단위','LOT 수'];
      rows=c.data.results.map(r=>[r.item.item_code,r.item.name,r.total,r.usable,this.addQuantities(r.quarantine,r.unusable),r.minimum_stock,r.unit,r.lot_count]);
    }
    const numeric=c.tab==='ledger'?[5,6,7]:[2,3,4,5,7];
    XlsxWriter.download(`수불재고_${this.today()}.xlsx`,[{name:c.tab==='ledger'?'수불 내역':'현재고',title:this.TYPES[this.type].title,subtitle:`${c.tab==='ledger'?`${this.state().from} ~ ${this.state().to} · ${this.state().direction==='IN'?'입고':this.state().direction==='OUT'?'출고':'전체'}`:'현재고 · 기준 단위'} / 검색: ${this.state().q || '전체'}`,columns:headers.map((header,i)=>({header,width:20,type:numeric.includes(i)?'number':'text'})),rows}]);
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

  renderLedger(data) {
    const lines = this.ledgerLines(data);
    lines.sort((a, b) => b.line.occurred_at.localeCompare(a.line.occurred_at) || b.line.movement_id - a.line.movement_id);
    const rows = lines.map(({ item, lot, line }) => {
      const negative = String(line.quantity).startsWith('-');
      return `<tr data-ledger-lot="${lot.lot_id}" data-movement="${line.movement_id}">
        <td class="no-wrap">${this.esc(String(line.occurred_at).replace('T', ' ').slice(0, 19))}</td>
        <td>${this.esc(item.item.item_code)}</td><td>${this.esc(item.item.name)}</td>
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
    if (row) { App.closeModal(); this.selectLot(row.lot_id, row.lot_number); }
  },
};
