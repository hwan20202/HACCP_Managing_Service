// =============================================
// 개발 검증 (임시) 사이드 탭 — 공통 진입점
// - 시제품 app.js의 navigate()가 'temp-*' 페이지를 TempEntry.mount()로 넘긴다(T3).
// - 시제품 모듈·HACCP_DATA·localStorage는 쓰지 않는다. 데이터는 /api/v1/ 만 사용한다.
// =============================================
(function () {
  const config = window.TEMP_ENTRY_CONFIG || { devConsole: false, devConsoleUrl: '' };

  const STATUS = {
    draft: { label: '작성중', badge: 'badge-neutral' },
    completed: { label: '작성완료', badge: 'badge-warning' },
    submitted: { label: '결재중', badge: 'badge-info' },
    approved: { label: '승인', badge: 'badge-success' },
    rejected: { label: '반려', badge: 'badge-danger' },
    correcting: { label: '정정 중', badge: 'badge-warning' },  // P6 (p6-s1-screens DOC-SC-04)
    skipped: { label: '작성 안 함', badge: 'badge-neutral te-badge-skipped' },  // P8 (p8-s1-screens 6장, 회색)
  };

  // P10(p10-s1-screens 2장): 문서함·결재함의 화면 id. 예전 temp-doc·temp-approval(북마크·콘솔 링크)도 같은 화면으로
  const PAGE_ALIAS = { 'temp-doc': 'doc-box', 'temp-approval': 'approval-box' };
  const BOX_PAGES = ['doc-box', 'approval-box'];
  const pageOf = (page) => PAGE_ALIAS[page] || page;

  const TempEntry = {
    screens: {},
    PAGE_ALIAS,
    pageOf,
    staff: null,
    container: null,
    config,
    STATUS,

    register(page, screen) {
      const id = pageOf(page);
      this.screens[id] = screen;
      Object.keys(PAGE_ALIAS).filter((old) => PAGE_ALIAS[old] === id).forEach((old) => { this.screens[old] = screen; });  // 예전 이름으로 찾는 코드·스크립트
    },

    // 다른 임시 화면으로 이동하면서 열 대상을 넘긴다(예: 결재 요청 상세 → 문서 상세).
    intent: null,
    open(page, intent) {
      this.intent = intent || null;
      App.navigate(pageOf(page));
    },
    takeIntent() {
      const value = this.intent;
      this.intent = null;
      return value;
    },

    async mount(page, container) {
      // 화면마다 새 host에 그린다. 이전 화면의 늦게 끝난 비동기 렌더링은 떼어낸 host에 쓰여 보이지 않는다
      // (예: 문서 상세를 읽는 중에 사이드바에서 결재함을 누른 경우).
      container.innerHTML = '';
      const host = document.createElement('div');
      container.appendChild(host);
      this.container = host;
      page = pageOf(page);
      document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.page === page));
      const screen = this.screens[page];
      if (!screen) {
        host.innerHTML = '<div class="empty-state"><h3>준비 중</h3><p>등록되지 않은 임시 화면입니다.</p></div>';
        return;
      }
      const section = BOX_PAGES.includes(page) && config.docMenu === 'haccp' ? 'HACCP 관리' : '개발 검증';
      document.getElementById('breadcrumb').textContent = `${section} › ${screen.title}`;
      await this.loadStaff();
      this.refreshBadges();
      if (this.container !== host) return; // 그사이 다른 화면으로 이동함
      screen.start(host);
    },

    async loadStaff() {
      if (this.staff) return this.staff;
      const result = await HaccpApi.get('staff');
      this.staff = result.ok ? result.data.items : [];
      if (HaccpApi.staffId && !this.staff.includes(Number(HaccpApi.staffId))) HaccpApi.setStaff('');
      return this.staff;
    },

    // ---------- 공통 화면 요소 ----------
    topBar(title, desc, documentId, { temp = true } = {}) {
      const options = ['<option value="">선택하세요</option>']
        .concat((this.staff || []).map((id) =>
          `<option value="${id}" ${String(id) === HaccpApi.staffId ? 'selected' : ''}>staff ${id}</option>`))
        .join('');
      const consoleLink = config.devConsole
        ? `<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener"
             href="${config.devConsoleUrl}${documentId ? `?document_id=${documentId}` : ''}">개발 콘솔에서 보기 ↗</a>`
        : '';
      return `
        <div class="page-header">
          <div class="page-title-group">
            <h1 class="page-title">${this.esc(title)}${temp ? ' <span class="badge badge-warning">임시</span>' : ''}</h1>
            <p class="page-desc">${this.esc(desc)}</p>
          </div>
          <div class="page-actions te-userbar">
            <label class="te-user-label" for="teStaff">현재 사용자</label>
            <select id="teStaff" class="form-control te-user-select">${options}</select>
            ${consoleLink}
          </div>
        </div>
        ${HaccpApi.staffId ? '' : '<div class="te-notice">현재 사용자를 선택하세요. 선택 전에는 저장·삭제를 할 수 없습니다.</div>'}`;
    },

    bindTopBar(root, onChange) {
      const select = root.querySelector('#teStaff');
      if (!select) return;
      select.addEventListener('change', () => {
        HaccpApi.setStaff(select.value);
        this.refreshBadges();
        onChange && onChange();
      });
    },

    // ---------- P10 사이드바 숫자 배지(p10-s1-screens 2장, S1-Q4 — 폴링 없음) ----------
    // 문서함 = 작성 필요 전체(A08 mine=0 counts 합 — 상신 대기·30일 넘은 미완료 제외), 결재함 = 내 차례(대기 total).
    // 화면을 열 때·사용자를 바꿀 때·내가 저장·작성완료·상신·결재·상신 취소·작성 안 함 한 뒤(api 쓰기 호출 성공) 다시 센다.
    badgeSeq: 0,
    async refreshBadges() {
      const doc = document.getElementById('badge-doc-box');
      const apr = document.getElementById('badge-approval-box');
      if (!doc && !apr) return;
      const seq = ++this.badgeSeq;
      const set = (el, n) => { if (!el) return; el.textContent = n ? String(n) : ''; el.hidden = !n; };
      if (!HaccpApi.staffId) { set(doc, 0); set(apr, 0); return; }
      const [todo, inbox] = await Promise.all([
        doc ? HaccpApi.get('todo') : null,
        apr ? HaccpApi.get('approval-inbox?box=pending&page=1') : null,
      ]);
      if (seq !== this.badgeSeq) return;  // 그사이 더 새로 셈
      set(doc, todo && todo.ok ? Object.values(todo.data.counts).reduce((a, b) => a + b, 0) : 0);
      set(apr, inbox && inbox.ok ? inbox.data.total : 0);
    },

    statusBadge(status) {
      const s = STATUS[status] || { label: status, badge: 'badge-neutral' };
      return `<span class="badge ${s.badge}">${s.label}</span>`;
    },

    esc(value) {
      return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },

    fmtDateTime(iso) {
      if (!iso) return '-';
      return iso.replace('T', ' ').slice(0, 16);
    },

    // ---------- 토스트 ----------
    toast(message, type = 'info') {
      let box = document.getElementById('teToast');
      if (!box) {
        box = document.createElement('div');
        box.id = 'teToast';
        box.className = 'toast-container te-toast-container';
        document.body.appendChild(box);
      }
      const item = document.createElement('div');
      item.className = `toast te-toast te-toast-${type}`;
      item.textContent = message;
      box.appendChild(item);
      setTimeout(() => item.remove(), 3500);
    },

    errorText(record) {
      const d = record.data || {};
      return d.code ? `[${d.code}] ${d.message}` : `요청 실패 (${record.status})`;
    },

    // ---------- 모달 (시제품 App.openModal을 쓰지 않는 자체 모달) ----------
    modal({ title, body, buttons }) {
      return new Promise((resolve) => {
        const wrap = document.createElement('div');
        wrap.className = 'te-modal-wrap';
        wrap.innerHTML = `
          <div class="te-modal" role="dialog" aria-modal="true">
            <div class="modal-header"><div class="modal-title">${this.esc(title)}</div></div>
            <div class="te-modal-body">${body}</div>
            <div class="te-modal-footer">
              ${buttons.map((b, i) => `<button class="btn ${b.cls || 'btn-secondary'}" data-i="${i}">${this.esc(b.label)}</button>`).join('')}
            </div>
          </div>`;
        document.body.appendChild(wrap);
        const close = (value) => { wrap.remove(); resolve(value); };
        wrap.addEventListener('click', (e) => {
          if (e.target === wrap) close(null);
          const btn = e.target.closest('button[data-i]');
          if (btn) close(buttons[Number(btn.dataset.i)].value);
        });
        wrap.querySelector('button[data-i]')?.focus();
      });
    },

    confirm(title, message, okLabel = '확인', okCls = 'btn-primary') {
      return this.modal({
        title, body: `<p>${message}</p>`,
        buttons: [{ label: '취소', value: false }, { label: okLabel, value: true, cls: okCls }],
      });
    },
  };

  window.TempEntry = TempEntry;

  // 쓰기 호출이 성공하면 배지를 다시 센다(여러 호출이 이어지면 한 번만)
  let badgeTimer = null;
  HaccpApi.onCall((record) => {
    const method = record.request && record.request.method;
    if (!record.ok || method === 'GET' || !String(record.request.url).startsWith('/api/v1/')) return;
    clearTimeout(badgeTimer);
    badgeTimer = setTimeout(() => TempEntry.refreshBadges(), 300);
  });
})();
