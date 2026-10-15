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
        selectedLot: null,
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
          <button class="btn btn-secondary" onclick="InventoryApiPage.load()">새로고침</button>
          <a class="btn btn-secondary" id="invApiCsv" href="#" onclick="return InventoryApiPage.downloadCsv()">수불 CSV 내려받기</a>
        </div>
      </div>
      <div class="card" style="padding:0.75rem;margin-bottom:0.75rem;">
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:flex-end;">${this.renderFilters()}</div>
        <p style="margin:0.6rem 0 0;font-size:0.78rem;color:var(--text-muted);">기간은 수불일자 기준입니다. 현재 재고는 기간과 관계없이 지금의 잔량입니다. 재고 행을 선택하면 해당 LOT의 수불만 조회합니다.</p>
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
      this.field('품목', `<select id="invItem" class="form-control" style="min-width:200px;" onchange="InventoryApiPage.set('itemId', this.value)">${itemOptions}</select>`),
      this.field('LOT 번호', `<input id="invLot" class="form-control" style="width:150px;font-family:monospace;" value="${this.esc(s.lotNumber)}" placeholder="일부만 입력" onkeydown="if(event.key==='Enter'){InventoryApiPage.set('lotNumber', this.value)}" onchange="InventoryApiPage.set('lotNumber', this.value)" />`),
    ];
    {
      parts.push(this.field('소비기한 유무 (재고)', `<select id="invExpiration" class="form-control" onchange="InventoryApiPage.set('expirationStatus', this.value)">
        ${[['', '전체'], ['KNOWN', '있음'], ['NONE', '없음'], ['UNKNOWN', '미확인']].map(([v, l]) => `<option value="${v}" ${s.expirationStatus === v ? 'selected' : ''}>${l}</option>`).join('')}
      </select>`));
      if (cfg.dateCol === 'manufactured') {
        parts.push(this.field('제조일 (생산 LOT)', `<span style="display:flex;gap:0.25rem;align-items:center;">
          <input type="date" class="form-control" value="${s.madeFrom}" onchange="InventoryApiPage.set('madeFrom', this.value)" /> ~
          <input type="date" class="form-control" value="${s.madeTo}" onchange="InventoryApiPage.set('madeTo', this.value)" /></span>`));
      }
      parts.push(`<label style="display:flex;gap:0.3rem;align-items:center;font-size:0.8rem;padding-bottom:0.45rem;">
        <input id="invUsable" type="checkbox" ${s.usableOnly ? 'checked' : ''} onchange="InventoryApiPage.set('usableOnly', this.checked)" /> 사용 가능 재고만 (재고 표)</label>`);
      parts.push(`<label style="display:flex;gap:0.3rem;align-items:center;font-size:0.8rem;padding-bottom:0.45rem;">
        <input id="invZero" type="checkbox" ${s.includeEmpty ? 'checked' : ''} onchange="InventoryApiPage.set('includeEmpty', this.checked)" /> 재고 0인 LOT 포함 (수불 이력은 항상 유지)</label>`);
      parts.push(this.field('수불일자 (최대 1년)', `<span style="display:flex;gap:0.25rem;align-items:center;">
        <input id="invFrom" type="date" class="form-control" value="${s.from}" onchange="InventoryApiPage.set('from', this.value)" /> ~
        <input id="invTo" type="date" class="form-control" value="${s.to}" onchange="InventoryApiPage.set('to', this.value)" /></span>`));
    }
    return parts.join('');
  },

  // ---------- 이벤트 ----------
  set(key, value) {
    const s = this.state();
    s[key] = value;
    // Search changes must not leave an invisible selected LOT restricting the ledger.
    if (['itemId', 'lotNumber', 'expirationStatus', 'madeFrom', 'madeTo', 'includeEmpty', 'usableOnly'].includes(key)) s.selectedLot = null;
    this.rerender();
  },

  selectLot(id, number = '') {
    const s = this.state();
    s.selectedLot = id ? { id: Number(id), number } : null;
    this.rerender();
  },

  rerender() {
    const container = document.getElementById('pageContainer');
    if (container) container.innerHTML = this.render(this.type);
  },

  // ---------- 데이터 ----------
  async load() {
    const host = document.getElementById('invApiPage');
    const serial = this.loadSerial = (this.loadSerial || 0) + 1;
    const type = this.type;
    const current = () => serial === this.loadSerial && host === document.getElementById('invApiPage') && type === this.type;
    try {
      await this.loadItems(type, host);
      if (!current()) return;
      const s = this.state();
      const [stock, ledger] = await Promise.all([this.fetchStock(), this.fetchLedger()]);
      if (!current()) return;
      this.stockRows = stock.results;
      const selection = s.selectedLot ? `<span class="badge badge-info">LOT ${this.esc(s.selectedLot.number)}</span>
        <button class="btn btn-secondary btn-sm" id="invClearLot" onclick="InventoryApiPage.selectLot(null)">LOT 선택 해제</button>` : '<span>전체 LOT</span>';
      document.getElementById('invApiContent').innerHTML = `
        <section aria-labelledby="invStockTitle"><h2 id="invStockTitle" style="font-size:1rem;">LOT별 현재 재고</h2>${this.renderStock(stock)}</section>
        <section aria-labelledby="invLedgerTitle" style="margin-top:1.25rem;">
          <div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;margin-bottom:0.6rem;"><h2 id="invLedgerTitle" style="font-size:1rem;margin:0;">수불 이력</h2>${selection}</div>
          ${this.renderLedger(ledger)}
        </section>`;
    } catch (error) {
      if (!current()) return;
      document.getElementById('invApiContent').innerHTML = `<div class="empty-state"><h3>조회하지 못했습니다</h3><p>${this.esc(error.message)}</p></div>`;
      if (typeof App !== 'undefined') App.showToast('error', '조회 실패', error.message);
    }
  },

  async loadItems(type, host) {
    if (this.items[type]) return;
    const lists = await Promise.all(this.TYPES[type].itemTypes.map((t) => this.getJson('/items/', { item_type: t })));
    this.items[type] = lists.flatMap((l) => l.results);
    if (host !== document.getElementById('invApiPage') || type !== this.type) return;
    const filters = host.querySelector('.card');
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
    const lines = data.results.flatMap((item) => item.lots.flatMap((lot) =>
      lot.lines.map((line) => ({ item, lot, line }))));
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
        <thead><tr><th>수불일자</th><th>품목코드</th><th>품목명</th><th>LOT 번호</th><th>구분</th><th>입고(+)</th><th>출고(-)</th><th>수불 후 잔량</th><th>단위</th><th>담당자</th><th>사유</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="11" style="text-align:center;padding:2rem;">선택한 기간 안에 수불 이력이 없습니다. 현재 재고에는 이월 재고가 포함될 수 있습니다.</td></tr>'}</tbody>
      </table></div></div>`;
  },

  selectStockLot(id) {
    const row = (this.stockRows || []).find((r) => r.lot_id === id);
    if (row) this.selectLot(row.lot_id, row.lot_number);
  },
};
