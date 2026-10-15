// =============================================
// BIODOT HACCP System - 메인 앱 컨트롤러
// =============================================

const App = {
  currentPage: 'dashboard',

  init() {
    this.setupSidebar();
    this.updateDateTime();
    setInterval(() => this.updateDateTime(), 60000);
    this.navigate('dashboard');
    this.setupEvents();
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

  navigate(page, updateNav = true) {
    if (!page) return;
    this.currentPage = page;

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
      'production-batches': '제조배치',
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
    if ((page.startsWith('temp-') || page === 'doc-box' || page === 'approval-box') && window.TempEntry) { TempEntry.mount(page, container); return; }


    let html = '';
    switch(page) {
      case 'dashboard':      html = DashboardPage.render(); break;
      // 재고 메뉴는 API 연결 화면 (inventory-api.js). 기존 고정 데이터 화면(InventoryPage)은 보존
      case 'raw-materials':  html = InventoryApiPage.render('raw'); break;
      case 'sub-materials':  html = InventoryApiPage.render('sub'); break;
      case 'finished-goods': html = InventoryApiPage.render('finished'); break;
      case 'ccp-monitoring': html = CCPPage.render(); break;
      case 'prerequisite':   html = PrerequisitePage.render(); break;
      case 'production-log': html = ProductionPage.render(); break;
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
  },

  renderSettings() {
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
          <div class="card-header"><div class="card-title">🏢 회사 정보</div></div>
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
          <button class="btn btn-primary" onclick="App.showToast('success','저장','회사 정보가 저장되었습니다.')">저장</button>
        </div>

        <!-- 알림 설정 -->
        <div class="card">
          <div class="card-header"><div class="card-title">🔔 알림 설정</div></div>
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
        </div>

        <!-- 직원 관리 -->
        <div class="card" style="grid-column:1/-1;">
          <div class="card-header">
            <div class="card-title">👥 직원 관리</div>
            <button class="btn btn-primary btn-sm" onclick="App.showToast('info','추가','직원 추가 기능.')">직원 추가</button>
          </div>
          <div class="table-wrapper">
            <table class="data-table">
              <thead>
                <tr><th>직원코드</th><th>성명</th><th>부서</th><th>역할</th><th>보건증기간</th><th>교육최근일</th><th>작업</th></tr>
              </thead>
              <tbody>
                ${HACCP_DATA.employees.map(e => `
                <tr>
                  <td><code style="font-size:0.75rem;color:var(--text-muted);">${e.id}</code></td>
                  <td style="font-weight:600;">${e.name}</td>
                  <td>${e.dept}</td>
                  <td>${e.role}</td>
                  <td>${e.healthCard}</td>
                  <td>${e.education}</td>
                  <td>
                    <button class="btn btn-secondary btn-sm" onclick="App.showToast('info','수정','직원 정보 수정.')">수정</button>
                  </td>
                </tr>`).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;
  },

  updateDateTime() {
    const now = new Date();
    const opts = { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short', hour: '2-digit', minute: '2-digit' };
    const dateEl = document.getElementById('currentDate');
    if (dateEl) dateEl.textContent = now.toLocaleString('ko-KR', opts);
  },

  // ===== 모달 =====
  showModal(title, bodyHtml, buttons = []) {
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');

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

  closeModal() {
    document.getElementById('modalOverlay')?.classList.remove('active');
    document.getElementById('modalContainer')?.classList.remove('active');
    document.body.style.overflow = '';
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
