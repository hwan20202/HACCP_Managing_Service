// =============================================
// BIODOT HACCP System - 메인 앱 컨트롤러
// =============================================

const App = {
  currentPage: 'dashboard',
  teamMembers: ['김정환', '박세욱', '박보경', '오주영'],

  init() {
    this.setupSidebar();
    this.updateDateTime();
    setInterval(() => this.updateDateTime(), 60000);
    this.setupEvents();
    // P16 R70: 시작 확인(활성 직원 0명 판정)이 끝나 "준비됨"일 때만 첫 화면·뒤로 가기 복원
    const start = () => { this.navigate('dashboard'); this.setupHistory(); };
    if (window.StartCheck) StartCheck.run(start);
    else start();
  },

  setupSidebar() {
    const sidebar = document.getElementById('sidebar');
    const toggle = document.getElementById('sidebarToggle');
    const mainContent = document.getElementById('mainContent');

    toggle?.addEventListener('click', () => {
      sidebar.classList.toggle('collapsed');
      mainContent.classList.toggle('expanded');
    });

    // 모바일 메뉴
    const mobileBtn = document.getElementById('mobileMenuBtn');
    mobileBtn?.addEventListener('click', () => {
      sidebar.classList.toggle('mobile-open');
    });

    // 오버레이 클릭시 모바일 사이드바 닫기
    document.addEventListener('click', (e) => {
      if (window.innerWidth <= 768) {
        if (!sidebar.contains(e.target) && !mobileBtn?.contains(e.target)) {
          sidebar.classList.remove('mobile-open');
        }
      }
    });
  },

  setupEvents() {
    window.addEventListener('resize', () => { if (typeof InventoryApiPage !== 'undefined') InventoryApiPage.fitViewport(); });
    // 네비게이션 클릭
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        this.navigate(item.dataset.page);
      });
    });

    // 알림 버튼
    document.getElementById('alertBtn')?.addEventListener('click', () => {
      this.navigate('alerts');
    });

    // 모달 배경 클릭 닫기
    document.getElementById('modalOverlay')?.addEventListener('click', () => {
      this.closeModal();
    });
  },

  setupHistory() {
    const saved = history.state;
    this.historyEnabled = true;
    window.addEventListener('popstate', event => {
      if (event.state?.haccp) this.restoreHistory(event.state);
    });
    if (saved?.haccp) this.restoreHistory(saved);
    else this.recordHistory(true);
  },

  historySnapshot() {
    return {
      haccp: true, page: this.currentPage,
      inventory: typeof InventoryApiPage !== 'undefined' ? JSON.parse(JSON.stringify(InventoryApiPage.states)) : {},
      detail: typeof InventoryApiPage !== 'undefined' ? InventoryApiPage.detailContext || null : null,
      modal: this.inventoryModal || null,
      intent: this.navigationIntent || null,
    };
  },

  recordHistory(replace = false) {
    if (!this.historyEnabled || this.restoringHistory) return;
    const state = this.historySnapshot();
    const signature = value => JSON.stringify(value, (key, v) => v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v);
    if (!replace && signature(history.state) === signature(state)) return;
    history[replace ? 'replaceState' : 'pushState'](state, '', '#' + encodeURIComponent(this.currentPage));
  },

  trackInventoryModal(route) {
    this.inventoryModal = route;
    this.recordHistory();
  },

  async restoreHistory(state) {
    const serial = this.restoreSerial = (this.restoreSerial || 0) + 1;
    this.restoringHistory = true;
    try {
      this.closeModal(false);
      if (typeof InventoryApiPage !== 'undefined') {
        InventoryApiPage.states = JSON.parse(JSON.stringify(state.inventory || {}));
        InventoryApiPage.detailContext = state.detail;
      }
      if (window.TempEntry) TempEntry.intent = state.intent;
      this.navigate(state.page, true, true);
      const route = state.modal;
      if (route && typeof InventoryApiPage !== 'undefined') {
        if (route.kind === 'item') {
          await InventoryApiPage.openItem(route.id);
          if (serial !== this.restoreSerial) return;
          if (state.detail) { InventoryApiPage.detailContext = {...state.detail}; await InventoryApiPage.loadItemDetail(); }
        }
        if (route.kind === 'receipt') await InventoryApiPage.openReceipt(route.id, route.cancel);
        if (route.kind === 'entry') await InventoryApiPage.openQaReceipt();
        if (route.kind === 'picker') await InventoryApiPage.openReceiptPicker(route);
      }
    } finally { if (serial === this.restoreSerial) this.restoringHistory = false; }
  },

  navigate(page, updateNav = true, fromHistory = false) {
    if (!page) return;
    // P16 R60·R70: 준비 전(불러오는 중·처음 설정·조회 실패)에는 이동하지 않고 기억만
    if (window.StartCheck && !StartCheck.ready()) { StartCheck.hold(page); return; }
    if (page === 'production-log') page = 'production-batches';
    if (page === 'inventory-overview') page = 'raw-materials'; // retired menu / old links
    if (!fromHistory) { this.restoreSerial = (this.restoreSerial || 0) + 1; this.restoringHistory = false; }
    this.closeModal(false);
    this.navigationIntent = window.TempEntry?.intent || null;
    this.currentPage = page;
    this.recordHistory();

    // 활성 nav 업데이트
    if (updateNav) {
      document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
      });
    }

    // 페이지 렌더링
    const container = document.getElementById('pageContainer');
    const breadcrumbs = {
      dashboard: '대시보드',
      'raw-materials': '원료 수불대장',
      'sub-materials': '부자재 수불대장',
      'finished-goods': '완제품 수불대장',
      'ccp-monitoring': 'CCP 모니터링',
      prerequisite: '선행요건 관리',
      'production-log': '생산 일지',
      'production-batches': '생산지시 · 실적',
      'quality-check': '자가품질검사',
      sanitation: '위생 관리 일지',
      training: '교육 훈련 관리',
      alerts: '알림 센터',
      reports: '보고서',
      standards: 'HACCP 기준서 관리',
      settings: '설정',
    };
    document.getElementById('breadcrumb').textContent = breadcrumbs[page] || page;
    // [임시 진입점 T3] 개발 검증 탭은 temp-entry 모듈이 그린다 (dev-notes/common/temp-entry.md).
    // P10: 문서함·결재함(doc-box·approval-box)도 같은 모듈 — 예전 temp-doc·temp-approval은 TempEntry가 바꿔 엶
    // P11: CCP 대시보드(ccp-dashboard)도 같은 모듈 — 시제품 'CCP 모니터링'(ccp-monitoring)과는 다른 화면 · P14: 역할 보기(role-view)
    if ((page.startsWith('temp-') || page === 'doc-box' || page === 'approval-box' || page === 'ccp-dashboard' || page === 'role-view' || page === 'prod-master') && window.TempEntry) { TempEntry.mount(page, container); return; }


    let html = '';
    switch(page) {
      case 'dashboard':      html = DashboardPage.render(); break;
      // 재고 메뉴는 API 연결 화면 (inventory-api.js). 기존 고정 데이터 화면(InventoryPage)은 보존
      case 'raw-materials':  html = InventoryApiPage.render('raw'); break;
      case 'sub-materials':  html = InventoryApiPage.render('sub'); break;
      case 'finished-goods': html = InventoryApiPage.render('finished'); break;
      case 'ccp-monitoring': html = CCPPage.render(); break;
      case 'prerequisite':   html = PrerequisitePage.render(); break;
      case 'production-log': html = ProductionApiPage.render(); break;
      // 제조배치: 생산 API 연결 화면 (production-api.js). 생산 일지(ProductionPage, 고정 데이터)는 보존
      case 'production-batches': html = ProductionApiPage.render(); break;
      case 'quality-check':  html = QualityPage.render(); break;
      case 'sanitation':     html = SanitationPage.render(); break;
      case 'training':       html = TrainingPage.render(); break;
      case 'alerts':         html = AlertsPage.render(); break;
      case 'reports':        html = ReportsPage.render(); break;
      case 'standards':      html = StandardsPage.render(); break;
      case 'settings':       html = this.renderSettings(); break;
      default: html = `<div class="empty-state"><div class="empty-state-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div><h3>준비 중</h3><p>해당 페이지는 준비 중입니다.</p></div>`;
    }

    container.innerHTML = html;
    container.scrollTop = 0;
    if (page === 'settings') this.mountStaffAdmin(container);
  },

  // P16 R50·R69: 설정 화면 직원 카드 = 직원 관리(ADM-SC-02, 문서 화면 코드 부품). 문서 화면을 끈 서버는 안내만
  mountStaffAdmin(container) {
    const card = container.querySelector('#settingsStaff');
    if (!card) return;
    if (window.TempEntry && window.TempEntryStaffAdmin) { TempEntryStaffAdmin.mount(card); return; }
    card.innerHTML = `<div class="card-header"><div class="card-title">👥 직원 관리</div></div>
      <p class="settings-off-note" style="font-size:0.8rem;color:var(--text-muted);margin:0 0 0.75rem;" id="settingsStaffOff">문서 관리 메뉴(<code>HACCP_DOC_MENU=haccp</code>)를 켜면 직원 관리·문서 권한·품목별 CCP를 쓸 수 있습니다.</p>`;
  },

  renderSettings() {
    this.versionTapCount = 0;
    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">시스템 설정</h1>
          <p class="page-desc">바이오닷 HACCP 시스템 환경 설정</p>
        </div>
      </div>

      <div class="grid-2">
        <!-- 회사 정보 -->
        <div class="card">
          <div class="card-header"><div class="card-title">🏢 회사 정보 <span class="badge badge-neutral settings-soon">준비 중</span></div></div>
          <p class="settings-off-note" style="font-size:0.8rem;color:var(--text-muted);margin:0 0 0.75rem;">시제품 화면이라 아직 저장되지 않습니다.</p>
          <fieldset disabled class="settings-soon-body" style="border:0;margin:0;padding:0;min-width:0;opacity:0.6;">
          <div class="form-group">
            <label class="form-label">회사명</label>
            <input type="text" class="form-control" value="${HACCP_DATA.company.name}" />
          </div>
          <div class="form-group">
            <label class="form-label">사업자 등록번호</label>
            <input type="text" class="form-control" value="${HACCP_DATA.company.businessNo}" />
          </div>
          <div class="form-group">
            <label class="form-label">주소</label>
            <input type="text" class="form-control" value="${HACCP_DATA.company.address}" />
          </div>
          <div class="form-group">
            <label class="form-label">HACCP 인증번호</label>
            <input type="text" class="form-control" value="${HACCP_DATA.company.haccpNo}" />
          </div>
          <button class="btn btn-primary">저장</button>
          </fieldset>
        </div>

        <!-- 알림 설정 -->
        <div class="card">
          <div class="card-header"><div class="card-title">🔔 알림 설정 <span class="badge badge-neutral settings-soon">준비 중</span></div></div>
          <p class="settings-off-note" style="font-size:0.8rem;color:var(--text-muted);margin:0 0 0.75rem;">시제품 화면이라 아직 저장되지 않습니다.</p>
          <fieldset disabled class="settings-soon-body" style="border:0;margin:0;padding:0;min-width:0;opacity:0.6;">
          ${[
            { label: 'CCP 한계기준 이탈 알림', enabled: true },
            { label: 'CCP 경고기준 접근 알림', enabled: true },
            { label: '재고 부족 알림', enabled: true },
            { label: '소비기한 임박 알림 (D-7)', enabled: true },
            { label: '보건증 만료 알림 (D-30)', enabled: true },
            { label: '선행요건 실시일 알림', enabled: true },
            { label: '교육훈련 일정 알림', enabled: false },
          ].map(s => `
          <div style="display:flex;align-items:center;justify-content:space-between;padding:0.6rem 0;border-bottom:1px solid var(--border-subtle);">
            <span style="font-size:0.82rem;">${s.label}</span>
            <label style="position:relative;display:inline-block;width:40px;height:22px;cursor:pointer;">
              <input type="checkbox" ${s.enabled ? 'checked' : ''} style="opacity:0;width:0;height:0;" />
              <span style="position:absolute;inset:0;background:${s.enabled ? 'var(--brand-primary)' : 'var(--bg-elevated)'};border-radius:11px;transition:all 0.2s;">
                <span style="position:absolute;width:16px;height:16px;background:white;border-radius:50%;top:3px;left:${s.enabled ? '21px' : '3px'};transition:left 0.2s;"></span>
              </span>
            </label>
          </div>`).join('')}
          </fieldset>
        </div>

        <!-- 직원 관리 — P16: 그린 뒤 mountStaffAdmin이 ADM-SC-02로 바꿈(R50) -->
        <div class="card" style="grid-column:1/-1;" id="settingsStaff"><div class="te-empty">불러오는 중…</div></div>
      </div>
      <footer class="settings-footer">
        <span>BIODOT HACCP</span>
        <button type="button" class="settings-version" onclick="App.tapVersion()">버전 1.0</button>
      </footer>
      <dialog id="teamCredits" class="team-credits" aria-labelledby="teamCreditsTitle" onclick="if(event.target===this)this.close()">
        <form method="dialog">
          <p class="team-credits-label">BIODOT HACCP</p>
          <h2 id="teamCreditsTitle">이 시스템을 함께 만든 사람들</h2>
          <ul class="team-credits-members"></ul>
          <p class="team-credits-message">바이오닷의 하루가 조금 더 편해지기를 바라며.</p>
          <button type="submit" class="btn btn-secondary" autofocus>닫기</button>
        </form>
      </dialog>
    </div>`;
  },

  tapVersion() {
    const dialog = document.getElementById('teamCredits');
    if (!dialog || dialog.open) return;
    this.versionTapCount = (this.versionTapCount || 0) + 1;
    if (this.versionTapCount < 3) return;
    this.versionTapCount = 0;
    const members = this.teamMembers.map(name => {
      const item = document.createElement('li');
      item.textContent = name;
      return item;
    });
    dialog.querySelector('.team-credits-members').replaceChildren(...members);
    dialog.showModal();
  },

  updateDateTime() {
    const now = new Date();
    const opts = { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short', hour: '2-digit', minute: '2-digit' };
    const dateEl = document.getElementById('currentDate');
    if (dateEl) dateEl.textContent = now.toLocaleString('ko-KR', opts);
  },

  // ===== 모달 =====
  showModal(title, bodyHtml, buttons = []) {
    this.inventoryModal = null;
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    container.classList.remove('inventory-detail-modal');

    const btnsHtml = buttons.map(b =>
      `<button class="btn ${b.class}" onclick="${b.action}">${b.text}</button>`
    ).join('');

    container.innerHTML = `
      <div class="modal-header">
        <div class="modal-title">${title}</div>
        <button class="modal-close" onclick="App.closeModal()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${btnsHtml ? `<div class="modal-footer">${btnsHtml}</div>` : ''}`;

    overlay.classList.add('active');
    container.classList.add('active');
    document.body.style.overflow = 'hidden';
  },

  closeModal(useHistory = true) {
    // Closing is distinct from Back: detail filters may have added many modal entries.
    // Cancel an in-flight history restore before it can render the detail a second time.
    if (useHistory) {
      this.restoreSerial = (this.restoreSerial || 0) + 1;
      this.restoringHistory = false;
      if (typeof InventoryApiPage !== 'undefined') {
        InventoryApiPage.itemSerial = (InventoryApiPage.itemSerial || 0) + 1;
        InventoryApiPage.detailContext = null;
      }
    }
    this.inventoryModal = null;
    document.getElementById('modalOverlay')?.classList.remove('active');
    document.getElementById('modalContainer')?.classList.remove('active');
    document.body.style.overflow = '';
    if (useHistory) this.recordHistory(true);
  },

  // ===== 토스트 알림 =====
  showToast(type, title, msg) {
    const container = document.getElementById('toastContainer');
    const id = 'toast-' + Date.now();

    const icons = {
      success: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
      warning: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      error:   '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
      info:    '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };

    const toastEl = document.createElement('div');
    toastEl.className = `toast ${type}`;
    toastEl.id = id;
    toastEl.innerHTML = `
      ${icons[type] || icons.info}
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        <div class="toast-msg">${msg}</div>
      </div>`;

    container.appendChild(toastEl);

    setTimeout(() => {
      toastEl.style.animation = 'fadeOut 0.3s ease forwards';
      setTimeout(() => toastEl.remove(), 300);
    }, 4000);
  },
};

// DOM 로드 완료 후 시작
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
