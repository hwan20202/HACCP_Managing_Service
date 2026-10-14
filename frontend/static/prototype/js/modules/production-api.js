// =============================================
// 제조배치 (생산) — /api/v1/inventory/batches/ 연결 화면
// (docs/inventory-frontend.md: 시제품 틀·디자인은 그대로, 데이터는 생산 API 로)
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
    statusFilter: '',
    batchId: null,
    creating: false,
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
  },

  // ---------- 화면 틀 ----------
  render() {
    if (!this.s.staffId) {
      try { this.s.staffId = sessionStorage.getItem('prodApi.staffId') || ''; } catch (e) { /* storage off */ }
    }
    setTimeout(() => this.init(), 0);
    return `
    <div class="fade-in" id="prodApiPage">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">제조배치</h1>
          <p class="page-desc">반제품(벌크) 제조배치 생성 → 시작 → 원료 투입 → 산출 → 완료, CCP 일지 연결과 재고·수불 확인</p>
        </div>
        <div class="page-actions" style="display:flex;gap:0.5rem;align-items:flex-end;">
          ${this.field('담당자', `<select class="form-control" id="prodStaff" style="min-width:150px;" onchange="ProductionApiPage.saveStaff(this.value)"><option value="">불러오는 중…</option></select>`)}
          <button class="btn btn-secondary" onclick="ProductionApiPage.refresh()">새로고침</button>
          <button class="btn btn-primary" id="prodNewBtn" onclick="ProductionApiPage.openCreate()">+ 새 제조배치</button>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:minmax(260px,340px) 1fr;gap:0.75rem;align-items:start;">
        <div class="card" style="padding:0;">
          <div style="padding:0.6rem 0.8rem;border-bottom:1px solid var(--border-subtle);display:flex;gap:0.5rem;align-items:center;">
            <strong style="flex:1;">배치 목록</strong>
            <select class="form-control" style="width:auto;" onchange="ProductionApiPage.setFilter(this.value)">
              ${[['', '전체'], ['PLANNED', '계획'], ['IN_PROGRESS', '진행'], ['COMPLETED', '완료'], ['CANCELLED', '취소']]
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
      const data = await this.get('/batches/', { status: this.s.statusFilter, limit: 100 });
      if (!el()) return;
      if (!data.results.length) { el().innerHTML = '<div class="empty-state"><p>배치가 없습니다.</p></div>'; return; }
      el().innerHTML = data.results.map((b) => `
        <div class="prod-batch-row" data-batch="${b.id}" onclick="ProductionApiPage.select(${b.id})"
             style="padding:0.55rem 0.8rem;border-bottom:1px solid var(--border-subtle);cursor:pointer;${b.id === this.s.batchId && !this.s.creating ? 'background:var(--bg-elevated, #eef3ff);' : ''}">
          <div style="display:flex;justify-content:space-between;gap:0.5rem;">
            <span style="font-family:monospace;color:var(--brand-primary);font-weight:700;">${this.esc(b.batch_number)}</span>
            ${this.badge(this.STATUS[b.status] || [b.status, 'badge-neutral'])}
          </div>
          <div style="font-size:0.75rem;color:var(--text-muted);">${this.esc(b.item.name)} · 제조일 ${this.esc(b.manufactured_date || '미정')}</div>
        </div>`).join('');
    } catch (error) { this.showError('prodList', error); }
  },

  // ---------- 생성 ----------
  openCreate() {
    this.s.creating = true;
    this.s.createKey = this.key();
    this.renderCreate();
  },

  renderCreate() {
    const el = document.getElementById('prodDetail');
    if (!el) return;
    const options = this.semiItems.map((i) => `<option value="${i.id}">${this.esc(i.item_code)} ${this.esc(i.name)} (${this.esc(i.base_unit)})</option>`).join('');
    el.innerHTML = `
      <div class="card" id="prodCreate">
        <div class="card-header"><div class="card-title">새 제조배치 (반제품 벌크)</div></div>
        ${this.semiItems.length ? '' : '<p style="color:var(--color-danger);">반제품(SEMI) 품목이 없습니다. 기준정보를 먼저 등록하세요.</p>'}
        <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end;">
          ${this.field('반제품 품목', `<select class="form-control" name="item_id" style="min-width:240px;">${options}</select>`)}
          ${this.field('계획일', `<input type="date" class="form-control" name="planned_date" value="${this.today()}">`)}
          ${this.field('계획 수량 (선택)', `<input type="number" class="form-control" name="planned_quantity" min="0" step="any" style="width:130px;">`)}
          ${this.field('메모 (선택)', `<input class="form-control" name="notes" maxlength="200" style="min-width:200px;">`)}
        </div>
        <p style="font-size:0.75rem;color:var(--text-muted);margin:0.6rem 0;">제조일(생산 시작일)은 생산을 시작할 때 정해집니다. 배치 번호·BOM 은 수불 규칙으로 자동입니다. 공정은 제조(MANUFACTURE)만 — 포장배치는 이번 범위 밖입니다.</p>
        <div style="display:flex;gap:0.5rem;">
          <button class="btn btn-primary" id="prodCreateSubmit" onclick="ProductionApiPage.create()">배치 만들기</button>
          <button class="btn btn-secondary" onclick="ProductionApiPage.cancelCreate()">닫기</button>
        </div>
      </div>`;
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
    await this.run('배치 생성', async () => {
      const batch = await this.post('/batches/', {
        item_id: Number(v('item_id')), staff_id: Number(this.s.staffId), process_type: 'MANUFACTURE',
        planned_date: v('planned_date') || null, planned_quantity: v('planned_quantity') || null, notes: v('notes') || null,
      });
      this.s.creating = false;
      this.toast('success', '배치 생성', `${batch.batch_number} (계획)`);
      await this.loadList();
      await this.select(batch.id);
    });
  },

  // ---------- 상세 ----------
  async select(id) {
    this.s.creating = false;
    if (this.s.batchId !== id) {
      this.s.batchId = id;
      this.s.use = { itemId: '', quantity: '', lotId: '', key: this.key() };
      this.s.output = { quantity: '', key: this.key() };
      this.lotChoices = null;
      this.fefo = null;
    }
    document.querySelectorAll('.prod-batch-row').forEach((row) => {
      row.style.background = String(row.dataset.batch) === String(id) ? 'var(--bg-elevated, #eef3ff)' : '';
    });
    try {
      this.detail = await this.get(`/batches/${id}/`);
      await this.loadDocs();
      this.renderDetail();
      this.loadTrace();
    } catch (error) { this.showError('prodDetail', error); }
  },

  async loadDocs() {
    this.docs = null;
    this.docsError = '';
    try {
      this.docs = await this.request('GET', `${this.DOC_API}/batches/${this.detail.id}/documents`);
    } catch (error) {
      this.docsError = error.message;
    }
  },

  renderDetail() {
    const el = document.getElementById('prodDetail');
    if (!el || !this.detail) return;
    const b = this.detail;
    el.innerHTML = `
      ${this.renderHead(b)}
      ${this.renderCcp(b)}
      ${b.status === 'PLANNED' ? this.renderStart(b) : ''}
      ${this.renderUsages(b)}
      ${this.renderOutputs(b)}
      ${b.status === 'IN_PROGRESS' ? this.renderComplete(b) : ''}
      <div class="card" id="prodTrace" style="padding:0;"><div style="padding:0.75rem 1rem;"><strong>재고·수불 확인</strong> <span style="font-size:0.75rem;color:var(--text-muted);">불러오는 중…</span></div></div>`;
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
              · BOM ${b.bom_id ? `#${b.bom_id}` : '없음'} · 담당 ${this.esc(b.staff.name)}
              ${b.cancel_reason ? `<br>취소 사유: ${this.esc(b.cancel_reason)}` : ''}
            </div>
          </div>
          <div style="display:flex;flex-direction:column;gap:0.5rem;align-items:flex-end;">
            <div style="display:flex;gap:0.4rem;align-items:center;">${stepper}</div>
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
    const rows = docs.map((d) => `<tr>
        <td class="no-wrap">${this.esc(d.type_code)}</td><td>${this.esc(d.process_code || '-')}</td>
        <td>${this.badge(this.DOC_STATUS[d.status] || [d.status, 'badge-neutral'])}</td>
        <td style="text-align:right;">v${this.esc(d.version)}</td><td style="text-align:right;">#${this.esc(d.document_id)}</td></tr>`).join('');
    return `
      <div class="card" style="margin-bottom:0.75rem;" id="prodCcp">
        <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;">
          <div class="card-title">CCP 일지 연결 (문서 앱)</div>
          <button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.recheckDocs()">다시 확인</button>
        </div>
        <div style="margin-bottom:0.5rem;">${verdict}</div>
        ${docs.length ? `<div class="table-wrapper"><table class="data-table"><thead><tr><th>문서</th><th>공정</th><th>상태</th><th style="text-align:right;">버전</th><th style="text-align:right;">문서 id</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}
        <p style="font-size:0.72rem;color:var(--text-muted);margin:0.4rem 0 0;">조회: GET /api/v1/batches/${b.id}/documents (docs_for_batch). 생산 시작과 CCP 일지 생성은 한 트랜잭션 — 문서 쪽 오류면 시작도 되돌려집니다.</p>
      </div>`;
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
        <p style="font-size:0.75rem;color:var(--text-muted);margin:0.5rem 0 0;">산출 LOT 번호와 소비기한은 이 날짜로 정해집니다 (제조일 = 생산 시작일, 소비기한 = 제조일 + 유통기한 − 1일).</p>
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
    const rows = b.usages.map((u) => `<tr>
        <td class="no-wrap">${this.esc(u.item.item_code)} ${this.esc(u.item.name)}</td>
        <td class="no-wrap" style="font-family:monospace;color:var(--brand-primary);">${this.esc(u.lot_number)}</td>
        <td style="text-align:right;">${this.esc(u.quantity)}</td>
        <td style="text-align:right;font-weight:700;">${this.esc(u.net_quantity)}</td><td>${this.esc(u.unit)}</td></tr>`).join('');
    const check = b.bom_check;
    const bom = check ? `
      <div style="font-size:0.78rem;margin:0.5rem 0 0.25rem;"><strong>BOM 기준량</strong> (기준: ${this.esc(check.basis === 'output' ? '산출량' : check.basis === 'plan' ? '계획량' : check.basis)} ${this.esc(check.basis_quantity)})</div>
      <div class="table-wrapper"><table class="data-table"><thead><tr><th>#</th><th>원료</th><th style="text-align:right;">기준</th><th style="text-align:right;">투입</th><th>단위</th><th></th></tr></thead><tbody>
      ${check.lines.map((l) => `<tr><td>${l.line_no}</td><td>${this.esc(l.item.item_code)} ${this.esc(l.item.name)}</td><td style="text-align:right;">${this.esc(l.standard)}</td><td style="text-align:right;">${this.esc(l.actual)}</td><td>${this.esc(l.unit)}</td>
        <td>${l.stock_managed === false ? '<span class="badge badge-neutral">재고 아님</span>' : b.status === 'IN_PROGRESS' ? `<button class="btn btn-secondary btn-sm" onclick="ProductionApiPage.pickBomLine(${l.item.id})">LOT 선택</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div>` : '';
    const form = b.status === 'IN_PROGRESS' ? this.renderUseForm() : '';
    return `
      <div class="card" style="margin-bottom:0.75rem;" id="prodUsages">
        <div class="card-header"><div class="card-title">원료 투입 (${b.usages.length}건)</div></div>
        ${b.usages.length ? `<div class="table-wrapper"><table class="data-table"><thead><tr><th>원료</th><th>LOT</th><th style="text-align:right;">투입</th><th style="text-align:right;">정정 반영</th><th>단위</th></tr></thead><tbody>${rows}</tbody></table></div>`
          : `<p style="font-size:0.8rem;color:var(--text-muted);">${b.status === 'PLANNED' ? '생산을 시작하면 투입할 수 있습니다.' : '투입 기록이 없습니다.'}</p>`}
        ${bom}
        ${form}
      </div>`;
  },

  renderUseForm() {
    const u = this.s.use;
    const items = this.inputItems.filter((i) => i.id !== this.detail.item.id);
    const itemOptions = ['<option value="">원료 선택</option>', ...items.map((i) =>
      `<option value="${i.id}" ${String(u.itemId) === String(i.id) ? 'selected' : ''}>${this.esc(i.item_code)} ${this.esc(i.name)} (${this.esc(i.base_unit)})</option>`)].join('');
    const choices = this.lotChoices || [];
    const fefoIds = (this.fefo && this.fefo.results || []).map((p) => p.lot_id);
    const lotOptions = choices.length ? choices.map((l) => {
      const pick = fefoIds.indexOf(l.lot_id);
      const exp = l.expiration_date || (l.expiration_status === 'NONE' ? '소비기한 없음' : '미확인');
      return `<option value="${l.lot_id}" ${String(u.lotId) === String(l.lot_id) ? 'selected' : ''}>${this.esc(l.lot_number)} · 재고 ${this.esc(l.quantity)}${this.esc(l.unit)} · ${this.esc(exp)}${pick >= 0 ? ` · FEFO ${pick + 1}순위` : ''}</option>`;
    }).join('') : `<option value="">${u.itemId ? '사용 가능한 LOT 없음' : '원료를 먼저 고르세요'}</option>`;
    const fefo = this.fefo ? `<div style="font-size:0.75rem;color:var(--text-muted);" id="prodFefo">FEFO 추천: ${this.fefo.results.map((p) => `${this.esc(p.lot_number)} ${this.esc(p.take)}`).join(', ') || '없음'}${this.fefo.shortfall && this.fefo.shortfall !== '0' ? ` · <span style="color:var(--color-danger);">부족 ${this.esc(this.fefo.shortfall)}</span>` : ''}</div>` : '';
    return `
      <div style="border-top:1px solid var(--border-subtle);margin-top:0.6rem;padding-top:0.6rem;" id="prodUseForm">
        <div style="display:flex;flex-wrap:wrap;gap:0.6rem;align-items:flex-end;">
          ${this.field('원료', `<select class="form-control" name="use_item" style="min-width:220px;" onchange="ProductionApiPage.setUseItem(this.value)">${itemOptions}</select>`)}
          ${this.field('투입량', `<input type="number" class="form-control" name="use_quantity" min="0" step="any" style="width:120px;" value="${this.esc(u.quantity)}" onchange="ProductionApiPage.setUseQuantity(this.value)">`)}
          ${this.field('LOT (사용 가능 · 소비기한 빠른 순)', `<select class="form-control" name="use_lot" style="min-width:300px;" onchange="ProductionApiPage.s.use.lotId=this.value">${lotOptions}</select>`)}
          <button class="btn btn-primary" id="prodUseBtn" onclick="ProductionApiPage.addUsage()">투입 등록</button>
        </div>
        ${fefo}
        <p style="font-size:0.72rem;color:var(--text-muted);margin:0.3rem 0 0;">사용 가능(검사 적합·보류 없음·투입일 기준 소비기한 안 지남) LOT 만 보입니다. 같은 입력을 두 번 눌러도 한 번만 등록됩니다.</p>
      </div>`;
  },

  pickBomLine(itemId) { this.setUseItem(String(itemId)); },

  async setUseItem(itemId) {
    this.s.use.itemId = itemId;
    this.s.use.lotId = '';
    this.lotChoices = null;
    this.fefo = null;
    if (itemId) {
      try {
        const stock = await this.get('/stock/lots/', { item_id: itemId, status: 'AVAILABLE' });
        this.lotChoices = stock.results.filter((l) => l.is_usable);
        await this.loadFefo();
      } catch (error) { this.toast('error', 'LOT 조회 실패', error.message); }
    }
    this.renderDetail();
    this.loadTrace();
  },

  async setUseQuantity(value) {
    this.s.use.quantity = value;
    await this.loadFefo();
    this.renderDetail();
    this.loadTrace();
  },

  async loadFefo() {
    const u = this.s.use;
    if (!u.itemId || !(Number(u.quantity) > 0)) { this.fefo = null; this.sortChoices(); return; }
    try {
      this.fefo = await this.get('/batches/fefo/', { item_id: u.itemId, quantity: u.quantity });
    } catch (error) { this.fefo = null; }
    this.sortChoices();
  },

  sortChoices() {
    if (!this.lotChoices) return;
    const order = (this.fefo && this.fefo.results || []).map((p) => p.lot_id);
    const rank = (l) => (order.includes(l.lot_id) ? order.indexOf(l.lot_id) : order.length + 1);
    const day = (l) => l.expiration_date || '9999-12-31';
    this.lotChoices.sort((a, b) => rank(a) - rank(b) || day(a).localeCompare(day(b)));
    if (!this.s.use.lotId && this.lotChoices[0]) this.s.use.lotId = String(this.lotChoices[0].lot_id);
  },

  async addUsage() {
    const form = document.getElementById('prodUseForm');
    const u = this.s.use;
    u.quantity = form.querySelector('[name="use_quantity"]').value;
    u.lotId = form.querySelector('[name="use_lot"]').value;
    if (!u.lotId || !(Number(u.quantity) > 0)) return this.toast('error', '투입', '원료 LOT 과 0보다 큰 투입량을 입력하세요.');
    await this.run('투입 등록', async () => {
      await this.post(`/batches/${this.detail.id}/usages/`, {
        lot_id: Number(u.lotId), quantity: u.quantity, staff_id: Number(this.s.staffId), idempotency_key: u.key,
      });
      this.toast('success', '투입 등록', `${u.quantity} 투입`);
      this.s.use = { itemId: u.itemId, quantity: '', lotId: '', key: this.key() };
      this.detail = await this.get(`/batches/${this.detail.id}/`);
      await this.setUseItem(u.itemId);
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
        ${this.field(`산출량 (${this.esc(b.unit)})`, `<input type="number" class="form-control" name="output_quantity" min="0" step="any" style="width:140px;" value="${this.esc(this.s.output.quantity)}">`)}
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
    const quantity = document.querySelector('#prodOutputForm [name="output_quantity"]').value;
    if (!(Number(quantity) > 0)) return this.toast('error', '산출', '0보다 큰 산출량을 입력하세요.');
    this.s.output.quantity = quantity;
    await this.run('산출 등록', async () => {
      const b = await this.post(`/batches/${this.detail.id}/outputs/`, {
        quantity, staff_id: Number(this.s.staffId), idempotency_key: this.s.output.key,
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
            <span style="font-size:0.8rem;">이월 ${this.esc(ledgerLot.opening)} · 입고 ${this.esc(ledgerLot.in)} · 출고 ${this.esc(ledgerLot.out)} · 현재고 <b class="prod-trace-closing">${this.esc(ledgerLot.closing)}</b> ${this.esc(item.unit)}</span>
          </div>
          <div class="table-wrapper"><table class="data-table"><thead><tr><th>일시</th><th>구분</th><th style="text-align:right;">수량(±)</th><th style="text-align:right;">잔량</th><th>사유</th><th>담당자</th></tr></thead><tbody>${lines}</tbody></table></div>`;
      }).join('');
      el().innerHTML = `
        <div style="padding:0.75rem 1rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
          <div><strong>재고·수불 확인</strong> <span style="font-size:0.75rem;color:var(--text-muted);">${this.esc(start)} ~ ${this.esc(today)} · 수불일지 API (ledger) 기준, 이 배치의 이동은 파란 줄</span></div>
          <span style="display:flex;gap:0.4rem;">
            <button class="btn btn-secondary btn-sm" onclick="App.navigate('raw-materials')">원료 수불대장</button>
            <button class="btn btn-secondary btn-sm" onclick="App.navigate('finished-goods')">완제품 수불대장</button>
          </span>
        </div>${sections}`;
    } catch (error) {
      el().innerHTML = `<div style="padding:0.75rem 1rem;"><strong>재고·수불 확인</strong><p style="color:var(--color-danger);font-size:0.8rem;">${this.esc(error.message)}</p></div>`;
    }
  },
};
