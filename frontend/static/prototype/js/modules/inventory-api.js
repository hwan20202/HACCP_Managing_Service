// =============================================
// 재고장 · 수불일지 — /api/v1/inventory/ 연결 화면
// (docs/inventory-frontend.md: 시제품 틀·디자인은 그대로, 재고 데이터만 API 로)
//
// - 재고장: LOT 별 현재고 (stock/lots). 0 재고는 기본 제외
// - 수불일지: 기간 안의 수불 이력과 누적 잔량 (ledger), CSV 내려받기
// - 소비기한은 날짜가 없을 때 '없음'(NONE)과 '미확인'(UNKNOWN)을 구분해 표시 (0007)
// - 수량은 API 의 문자열을 그대로 표시 (계산하지 않음)
// 기존 prototype inventory.js(고정 데이터)는 보존하고, 메뉴만 이 화면으로 연결한다.
// =============================================

const InventoryApiPage = {
  API: '/api/v1/inventory',

  TYPES: {
    raw: {
      title: '원료 수불대장',
      desc: 'LOT별 현재고(재고장)와 입출고 이력(수불일지)',
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
        tab: 'stock',
        itemId: '',
        lotNumber: '',
        expirationStatus: '',
        includeEmpty: false,
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
    const s = this.state();
    setTimeout(() => this.load(), 0);
    const tab = (key, label) => `<button class="tab-btn ${s.tab === key ? 'active' : ''}" onclick="InventoryApiPage.switchTab('${key}')">${label}</button>`;
    return `
    <div class="fade-in" id="invApiPage">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">${cfg.title}</h1>
          <p class="page-desc">${cfg.desc}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" onclick="InventoryApiPage.load()">새로고침</button>
          ${s.tab === 'ledger' ? `<a class="btn btn-secondary" id="invApiCsv" href="#" onclick="return InventoryApiPage.downloadCsv()">CSV 내려받기</a>` : ''}
        </div>
      </div>
      <div class="tabs">
        ${tab('stock', '📦 재고장 (LOT별 현재고)')}
        ${tab('ledger', '📋 수불일지')}
      </div>
      <div class="card" style="padding:0.75rem;margin-bottom:0.75rem;">
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:flex-end;">${this.renderFilters()}</div>
      </div>
      <div id="invApiContent"><div class="empty-state"><p>불러오는 중…</p></div></div>
    </div>`;
  },

  field(label, html) {
    return `<label style="display:flex;flex-direction:column;gap:0.2rem;font-size:0.72rem;color:var(--text-muted);font-weight:600;">${label}${html}</label>`;
  },

  renderFilters() {
    const s = this.state();
    const cfg = this.TYPES[this.type];
    const items = this.items[this.type] || [];
    const itemOptions = ['<option value="">전체 품목</option>', ...items.map((i) =>
      `<option value="${i.id}" ${String(s.itemId) === String(i.id) ? 'selected' : ''}>${this.esc(i.item_code)} ${this.esc(i.name)}</option>`)].join('');
    const parts = [
      this.field('품목', `<select class="form-control" style="min-width:200px;" onchange="InventoryApiPage.set('itemId', this.value)">${itemOptions}</select>`),
      this.field('LOT 번호', `<input class="form-control" style="width:150px;font-family:monospace;" value="${this.esc(s.lotNumber)}" placeholder="일부만 입력" onkeydown="if(event.key==='Enter'){InventoryApiPage.set('lotNumber', this.value)}" onchange="InventoryApiPage.set('lotNumber', this.value)" />`),
    ];
    if (s.tab === 'stock') {
      parts.push(this.field('소비기한 유무', `<select class="form-control" onchange="InventoryApiPage.set('expirationStatus', this.value)">
        ${[['', '전체'], ['KNOWN', '있음'], ['NONE', '없음'], ['UNKNOWN', '미확인']].map(([v, l]) => `<option value="${v}" ${s.expirationStatus === v ? 'selected' : ''}>${l}</option>`).join('')}
      </select>`));
      if (cfg.dateCol === 'manufactured') {
        parts.push(this.field('제조일 (생산 LOT)', `<span style="display:flex;gap:0.25rem;align-items:center;">
          <input type="date" class="form-control" value="${s.madeFrom}" onchange="InventoryApiPage.set('madeFrom', this.value)" /> ~
          <input type="date" class="form-control" value="${s.madeTo}" onchange="InventoryApiPage.set('madeTo', this.value)" /></span>`));
      }
      parts.push(`<label style="display:flex;gap:0.3rem;align-items:center;font-size:0.8rem;padding-bottom:0.45rem;">
        <input type="checkbox" ${s.includeEmpty ? 'checked' : ''} onchange="InventoryApiPage.set('includeEmpty', this.checked)" /> 재고 0인 LOT 포함</label>`);
    } else {
      parts.push(this.field('수불 기간 (최대 1년)', `<span style="display:flex;gap:0.25rem;align-items:center;">
        <input type="date" class="form-control" value="${s.from}" onchange="InventoryApiPage.set('from', this.value)" /> ~
        <input type="date" class="form-control" value="${s.to}" onchange="InventoryApiPage.set('to', this.value)" /></span>`));
    }
    return parts.join('');
  },

  // ---------- 이벤트 ----------
  switchTab(tab) {
    this.state().tab = tab;
    this.rerender();
  },

  set(key, value) {
    this.state()[key] = value;
    this.rerender();
  },

  rerender() {
    const container = document.getElementById('pageContainer');
    if (container) container.innerHTML = this.render(this.type);
  },

  // ---------- 데이터 ----------
  async load() {
    const target = () => document.getElementById('invApiContent');
    try {
      await this.loadItems();
      const s = this.state();
      const html = s.tab === 'stock' ? this.renderStock(await this.fetchStock()) : this.renderLedger(await this.fetchLedger());
      if (target()) target().innerHTML = html;
    } catch (error) {
      if (target()) target().innerHTML = `<div class="empty-state"><h3>조회하지 못했습니다</h3><p>${this.esc(error.message)}</p></div>`;
      if (typeof App !== 'undefined') App.showToast('error', '조회 실패', error.message);
    }
  },

  async loadItems() {
    if (this.items[this.type]) return;
    const lists = await Promise.all(this.TYPES[this.type].itemTypes.map((t) => this.getJson('/items/', { item_type: t })));
    this.items[this.type] = lists.flatMap((l) => l.results);
    const filters = document.querySelector('#invApiPage .card');
    if (filters) filters.firstElementChild.innerHTML = this.renderFilters();
  },

  fetchStock() {
    const s = this.state();
    return this.getJson('/stock/lots/', {
      item_type: this.TYPES[this.type].itemTypes.join(','),
      item_id: s.itemId,
      lot_number: s.lotNumber.trim(),
      expiration_status: s.expirationStatus,
      include_empty: s.includeEmpty,
      manufactured_from: s.madeFrom,
      manufactured_to: s.madeTo,
    });
  },

  ledgerParams() {
    const s = this.state();
    return {
      from: s.from,
      to: s.to,
      item_type: this.TYPES[this.type].itemTypes.join(','),
      item_id: s.itemId,
      lot_number: s.lotNumber.trim(),
    };
  },

  fetchLedger() {
    return this.getJson('/ledger/', this.ledgerParams());
  },

  downloadCsv() {
    window.location.href = `${this.API}/ledger/export.csv?${this.query(this.ledgerParams())}`;
    return false;
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
    if (row.active_hold_count > 0) return this.badge(['보류', 'badge-danger']);
    return this.badge(this.LOT_STATUS[row.status] || [row.status, 'badge-neutral']);
  },

  renderStock(data) {
    const rows = data.results;
    const cfg = this.TYPES[this.type];
    if (!rows.length) return `<div class="empty-state"><h3>재고가 있는 LOT이 없습니다</h3><p>조건을 바꾸거나 '재고 0인 LOT 포함'을 선택하세요.</p></div>`;
    const dateHead = cfg.dateCol === 'manufactured' ? '제조일' : '입고일';
    return `
    <div class="card" style="padding:0;">
      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr>
            <th>품목코드</th><th>품목명</th><th>LOT 번호</th><th>${dateHead}</th><th>소비기한</th>
            <th>상태</th><th style="text-align:right;">현재고</th><th>단위</th>${cfg.dateCol === 'received' ? '<th>공급처</th>' : ''}
          </tr></thead>
          <tbody>
            ${rows.map((r) => `<tr>
              <td class="no-wrap">${this.esc(r.item.item_code)}</td>
              <td>${this.esc(r.item.name)}</td>
              <td class="no-wrap" style="font-family:monospace;color:var(--brand-primary);">${this.esc(r.lot_number)}</td>
              <td class="no-wrap">${this.esc((cfg.dateCol === 'manufactured' ? r.manufactured_date : r.received_date) || '-')}</td>
              <td>${this.expiryCell(r.expiration_date, r.expiration_status, r.days_to_expiry)}</td>
              <td>${this.lotStatus(r)}</td>
              <td style="text-align:right;font-weight:700;">${this.esc(r.quantity)}</td>
              <td>${this.esc(r.unit)}</td>
              ${cfg.dateCol === 'received' ? `<td>${this.esc(r.supplier_name || '-')}</td>` : ''}
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
      <div style="padding:0.6rem 1rem;border-top:1px solid var(--border-subtle);font-size:0.75rem;color:var(--text-muted);">
        LOT ${rows.length}건 · 수량은 품목 기준 단위 · 소비기한 없음/미확인은 날짜가 없는 LOT입니다
      </div>
    </div>`;
  },

  renderLedger(data) {
    const items = data.results;
    if (!items.length) return `<div class="empty-state"><h3>기간 안에 수불이 없습니다</h3><p>${this.esc(data.from)} ~ ${this.esc(data.to)}</p></div>`;
    const qtyIn = (q) => (q && !String(q).startsWith('-') && q !== '0' ? this.esc(q) : '');
    const qtyOut = (q) => (q && String(q).startsWith('-') ? this.esc(String(q).slice(1)) : '');
    return items.map((item) => `
    <div class="card" style="padding:0;margin-bottom:0.75rem;">
      <div style="padding:0.6rem 1rem;border-bottom:1px solid var(--border-subtle);display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
        <strong>${this.esc(item.item.item_code)} ${this.esc(item.item.name)}</strong>
        <span style="font-size:0.78rem;color:var(--text-muted);">이월 ${this.esc(item.opening)} · 입고 ${this.esc(item.in)} · 출고 ${this.esc(item.out)} · 기말 <b>${this.esc(item.closing)}</b> ${this.esc(item.unit)}</span>
      </div>
      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr><th>LOT 번호</th><th>소비기한</th><th>일시</th><th>구분</th><th style="text-align:right;">입고(+)</th><th style="text-align:right;">출고(-)</th><th style="text-align:right;">잔량</th><th>사유</th><th>담당자</th></tr></thead>
          <tbody>
            ${item.lots.map((lot) => {
              const lotCells = `<td class="no-wrap" style="font-family:monospace;color:var(--brand-primary);">${this.esc(lot.lot_number)}</td><td>${this.expiryCell(lot.expiration_date, lot.expiration_status)}</td>`;
              const opening = `<tr style="background:var(--bg-elevated, #f8f9fa);">${lotCells}<td>${this.esc(data.from)} 이전</td><td>이월</td><td></td><td></td><td style="text-align:right;">${this.esc(lot.opening)}</td><td></td><td></td></tr>`;
              const lines = lot.lines.map((l) => `<tr>
                <td></td><td></td>
                <td class="no-wrap">${this.esc(String(l.occurred_at).replace('T', ' ').slice(0, 16))}</td>
                <td class="no-wrap">${this.esc(l.movement_name)}${l.corrects_movement_id ? ' <span class="badge badge-info">정정</span>' : ''}</td>
                <td style="text-align:right;">${qtyIn(l.quantity)}</td>
                <td style="text-align:right;">${qtyOut(l.quantity)}</td>
                <td style="text-align:right;font-weight:700;">${this.esc(l.balance)}</td>
                <td>${this.esc(l.reason || '')}</td>
                <td class="no-wrap">${this.esc(l.staff_name)}</td>
              </tr>`).join('');
              return opening + lines;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>`).join('');
  },
};
