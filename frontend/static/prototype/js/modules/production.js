// =============================================
// BIODOT HACCP - 생산일지 + 전자동 문서 생성 페이지
// =============================================

const ProductionPage = {
  currentTab: 'wizard',   // wizard | history | logs

  render() {
    return `
    <div class="fade-in" style="display: flex; flex-direction: column; height: calc(100vh - 80px); overflow: hidden;">
      <div style="flex-shrink: 0; padding-bottom: 0.5rem;">
        <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">생산일지 · 자동 문서 생성</h1>
          <p class="page-desc">생산정보 입력 한 번으로 원료불출·부자재불출·CCP일지·품질검사·완제품 수불까지 <strong style="color:var(--brand-primary);">전자동 생성</strong></p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" onclick="ProductionPage.switchTab('history')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            생성 이력
          </button>
          <button class="btn btn-secondary" onclick="ProductionPage.switchTab('logs')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            생산일지 목록
          </button>
        </div>
      </div>

      <!-- 탭 -->
      <div class="tabs" style="margin-bottom:0.5rem;">
        <button class="tab-btn ${this.currentTab==='wizard'?'active':''}"  onclick="ProductionPage.switchTab('wizard')">
          ✨ 자동 생성 마법사
        </button>
        <button class="tab-btn ${this.currentTab==='history'?'active':''}" onclick="ProductionPage.switchTab('history')">
          📋 생성 이력
        </button>
        <button class="tab-btn ${this.currentTab==='logs'?'active':''}"    onclick="ProductionPage.switchTab('logs')">
          🏭 생산일지 목록
        </button>
      </div>

      ${this.currentTab === 'logs' ? `
      <!-- 검색 바 (1줄) -->
      <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.5rem;align-items:center;">
        <div class="search-input-wrap flex-1">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="text" class="form-control" placeholder="제품명, LOT번호 검색..." 
            value="${this.logFilter.keyword || ''}" oninput="ProductionPage.updateLogFilter('keyword', this.value)" />
        </div>
      </div>
      <!-- 날짜 빠른 선택 바 (2줄) -->
      <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:0.75rem;align-items:center;padding:0.5rem;background:#f8f9fa;border-radius:6px;border:1px solid var(--border-subtle);">
        <span style="font-size:0.72rem;color:var(--text-muted);font-weight:700;white-space:nowrap;">📅 기간:</span>
        <button onclick="ProductionPage.setDateRange('all')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid ${!this.logFilter.startDate&&!this.logFilter.endDate?'var(--brand-primary)':'var(--border-strong)'};background:${!this.logFilter.startDate&&!this.logFilter.endDate?'var(--brand-primary)':'#fff'};color:${!this.logFilter.startDate&&!this.logFilter.endDate?'#fff':'var(--text-secondary)'};cursor:pointer;font-weight:600;">전체</button>
        <button onclick="ProductionPage.setDateRange('2year')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">2년</button>
        <button onclick="ProductionPage.setDateRange('year')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">📆 올해</button>
        <button onclick="ProductionPage.setDateRange('6month')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">6개월</button>
        <button onclick="ProductionPage.setDateRange('month')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">이번 달</button>
        <span style="font-size:0.75rem;color:var(--border-strong);margin:0 0.15rem;">|</span>
        <input type="date" class="form-control" style="width:130px;font-size:0.78rem;padding:0.2rem 0.4rem;" value="${this.logFilter.startDate || ''}" onchange="ProductionPage.updateLogFilter('startDate', this.value)" />
        <span style="font-size:0.8rem;color:var(--text-muted);">~</span>
        <input type="date" class="form-control" style="width:130px;font-size:0.78rem;padding:0.2rem 0.4rem;" value="${this.logFilter.endDate || ''}" onchange="ProductionPage.updateLogFilter('endDate', this.value)" />
        ${(this.logFilter.startDate||this.logFilter.endDate)?`<button onclick="ProductionPage.setDateRange('all')" style="font-size:0.72rem;padding:0.2rem 0.5rem;border-radius:4px;border:1px solid var(--color-danger);background:transparent;color:var(--color-danger);cursor:pointer;">✕ 초기화</button>`:''}
      </div>
      ` : ''}
      </div> <!-- Fixed top area ends -->

      <div id="prodContent" style="flex: 1; overflow-y: auto; padding-right: 5px; padding-bottom: 2rem;">${this.renderContent()}</div>
    </div>`;
  },

  renderContent() {
    if (this.currentTab === 'wizard')  return this.renderWizard();
    if (this.currentTab === 'history') return this.renderHistory();
    return this.renderLogs();
  },

  // ───────────────────────────────────────
  // STEP 1: 생산정보 입력 폼
  // ───────────────────────────────────────
  renderWizard() {
    return `
    <!-- 프로세스 플로우 다이어그램 -->
    <div class="card" style="margin-bottom:1.25rem;padding:1.25rem;">
      <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:1rem;">자동 생성 워크플로우</div>
      <div style="display:flex;align-items:center;gap:0;overflow-x:auto;padding-bottom:0.25rem;">
        ${[
          { icon:'📝', label:'생산정보 입력', sub:'제품·수량·날짜', color:'var(--brand-primary)' },
          { icon:'📦', label:'원료 불출', sub:'BOM 자동계산·재고차감', color:'var(--color-info)' },
          { icon:'🗃️', label:'부자재 불출', sub:'포장재 자동계산', color:'var(--color-info)' },
          { icon:'⚠️', label:'CCP 일지', sub:'CCP별 측정슬롯 생성', color:'var(--color-warning)' },
          { icon:'🔬', label:'품질검사 목록', sub:'기준서 기반 자동생성', color:'var(--color-warning)' },
          { icon:'✅', label:'완제품 입고', sub:'수불대장 자동반영', color:'var(--color-success)' },
        ].map((s, i) => `
        <div style="display:flex;align-items:center;flex-shrink:0;">
          <div style="display:flex;flex-direction:column;align-items:center;gap:0.3rem;min-width:90px;">
            <div style="width:44px;height:44px;border-radius:50%;background:rgba(0,0,0,0.15);border:2px solid ${s.color};display:flex;align-items:center;justify-content:center;font-size:1.2rem;">${s.icon}</div>
            <div style="font-size:0.72rem;font-weight:700;color:var(--text-primary);text-align:center;line-height:1.3;">${s.label}</div>
            <div style="font-size:0.62rem;color:var(--text-muted);text-align:center;line-height:1.3;">${s.sub}</div>
          </div>
          ${i < 5 ? `<div style="width:32px;height:2px;background:linear-gradient(90deg,${s.color},var(--border-default));flex-shrink:0;margin:0 2px;margin-bottom:1.2rem;"></div>` : ''}
        </div>`).join('')}
      </div>
    </div>

    <!-- 단계별 입력 폼 -->
    <div class="grid-1-2" style="align-items:start;gap:1.25rem;">

      <!-- 좌: 입력 폼 -->
      <div class="card" id="wizardForm">
        <div class="card-header">
          <div>
            <div class="card-title">📝 생산 정보 입력</div>
            <div class="card-subtitle">필수 항목 입력 후 자동 생성 실행</div>
          </div>
          <span class="badge badge-brand">STEP 1</span>
        </div>

        <div class="form-group">
          <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:0.5rem;">
            <label class="form-label" style="margin:0;">제품 선택 * <span style="font-size:0.7rem;color:var(--brand-primary);font-weight:normal;">(검색)</span></label>
            <button class="btn btn-secondary btn-sm" onclick="ProductionPage.openNewBomModal()" style="font-weight:600;">+ 새 제품 (BOM) 등록</button>
          </div>
          <div class="search-input-wrap flex-1" style="margin-bottom:0.5rem;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input type="text" class="form-control" placeholder="제품명 검색..." oninput="ProductionPage.filterProducts(this.value)" autocomplete="off" />
          </div>
          <select class="form-control" id="prd_product" size="3" style="height:auto;" onchange="ProductionPage.onProductChange(this.value)" required>
            <option value="" disabled selected>-- 검색 후 아래에서 선택하세요 --</option>
            ${HACCP_DATA.products.map(p => `
            <option value="${p.id}">[${p.id}] ${p.name} (${p.code})</option>`).join('')}
          </select>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">생산 예정일 *</label>
            <input type="date" class="form-control" id="prd_date"
              value="${new Date('2026-03-18').toISOString().split('T')[0]}"
              onchange="ProductionPage.onDateChange(this.value)" />
          </div>
          <div class="form-group">
            <label class="form-label">생산 라인</label>
            <select class="form-control" id="prd_line">
              <option>A라인</option><option>B라인</option><option>C라인</option>
            </select>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">계획 생산 수량(개) *</label>
          <div style="position:relative;">
            <input type="number" class="form-control" id="prd_qty"
              placeholder="예: 3000" min="100" step="100"
              oninput="ProductionPage.onQtyChange(this.value)"
              style="padding-right:3rem;" />
            <span style="position:absolute;right:0.85rem;top:50%;transform:translateY(-50%);font-size:0.8rem;color:var(--text-muted);">개</span>
          </div>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">작업 시작시간</label>
            <input type="time" class="form-control" id="prd_startTime" value="08:00" />
          </div>
          <div class="form-group">
            <label class="form-label">작업 종료시간(예정)</label>
            <input type="time" class="form-control" id="prd_endTime" value="16:00" />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">작업 책임자 *</label>
          <select class="form-control" id="prd_operator" required>
            <option value="">-- 선택 --</option>
            ${HACCP_DATA.employees.filter(e => ['생산','품질관리'].includes(e.dept)).map(e =>
              `<option value="${e.name}">${e.name} (${e.role})</option>`).join('')}
          </select>
        </div>

        <div class="form-group">
          <label class="form-label">참여 작업자</label>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);">
            ${HACCP_DATA.employees.filter(e => e.dept === '생산').map(e => `
            <label style="display:flex;align-items:center;gap:0.4rem;font-size:0.8rem;cursor:pointer;">
              <input type="checkbox" class="prd_worker" value="${e.name}" /> ${e.name}
            </label>`).join('')}
          </div>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">식품 유형</label>
            <select class="form-control" id="prd_foodType">
              <option value="">기존 유형 유지 (변경 시 선택)</option>
              <option value="기타가공품">기타가공품</option>
              <option value="고형차">고형차</option>
              <option value="추출가공식품">추출가공식품</option>
              <option value="액상차">액상차</option>
              <option value="캔디류">캔디류</option>
              <option value="일반식품">일반식품</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">소비기한 <span style="font-size:.72rem;color:var(--text-muted);">(BOM자동계산 또는 직접 입력)</span></label>
            <input type="date" class="form-control" id="prd_expiryDate" />
            <div style="font-size:.72rem;color:var(--text-muted);margin-top:.25rem;">입력 안 하면 BOM의 shelf days 자동 계산</div>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">특이사항</label>
          <textarea class="form-control" id="prd_note" rows="2" placeholder="특이사항이 있으면 입력..."></textarea>
        </div>

        <!-- 생성 버튼 -->
        <button class="btn btn-primary" id="genBtn" style="width:100%;padding:0.875rem;font-size:1rem;"
          onclick="ProductionPage.runAutoGen()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:18px;height:18px;">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
          </svg>
          전자동 문서 생성 실행
        </button>
      </div>

      <!-- 우: 미리보기 패널 -->
      <div id="previewPanel">
        ${this.renderPreviewEmpty()}
      </div>
    </div>`;
  },

  renderPreviewEmpty() {
    return `
    <div class="card" style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:400px;border:2px dashed var(--border-default);">
      <div style="font-size:3rem;margin-bottom:0.75rem;">⚡</div>
      <div style="font-size:1rem;font-weight:700;color:var(--text-secondary);margin-bottom:0.4rem;">생산정보를 입력하면</div>
      <div style="font-size:0.85rem;color:var(--text-muted);text-align:center;line-height:1.6;">
        BOM 자동계산 결과와<br/>생성될 문서 목록이 여기에 표시됩니다
      </div>
    </div>`;
  },

  // 제품 목록 필터링
  filterProducts(query) {
    const q = query.toLowerCase();
    const select = document.getElementById('prd_product');
    if (!select) return;
    
    // 이전에 선택된 값 보존
    const currentVal = select.value;
    const filtered = HACCP_DATA.products.filter(p => 
      p.name.toLowerCase().includes(q) || 
      p.code.toLowerCase().includes(q) ||
      p.id.toLowerCase().includes(q)
    );
    
    select.innerHTML = '<option value="" disabled>-- 검색 후 아래에서 선택하세요 --</option>' + 
      filtered.map(p => `<option value="${p.id}">[${p.id}] ${p.name} (${p.code})</option>`).join('');
      
    if (filtered.find(p => p.id === currentVal)) {
      select.value = currentVal;
    } else if (currentVal && !q) { // 검색어가 지워졌고, 기존에 무언가 선택되어 있었다면 원래대로 복원 불가하므로, 어쨌든 value 유지는 위 로직으로 커버됨.
      select.value = '';
      this.onProductChange(''); // 선택 해제 시 미리보기 지우기
    }
  },

  // 제품 선택 시 미리보기 업데이트
  onProductChange(productId) {
    const qty = parseInt(document.getElementById('prd_qty')?.value || '0');
    if (productId && qty > 0) this.updatePreview(productId, qty);
    else this.showBomPreview(productId);
  },

  onQtyChange(qty) {
    const productId = document.getElementById('prd_product')?.value;
    if (productId && parseInt(qty) > 0) this.updatePreview(productId, parseInt(qty));
  },

  onDateChange(date) {
    const productId = document.getElementById('prd_product')?.value;
    const qty = parseInt(document.getElementById('prd_qty')?.value || '0');
    if (productId && qty > 0) this.updatePreview(productId, qty);
  },

  showBomPreview(productId) {
    const product = HACCP_DATA.products.find(p => p.id === productId);
    if (!product) return;
    const panel = document.getElementById('previewPanel');
    panel.innerHTML = `
    <div class="card">
      <div class="card-header">
        <div class="card-title">📐 배합비 (BOM) 정보</div>
        <span class="badge badge-neutral">1,000개 기준</span>
      </div>
      <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.75rem;">수량 입력 시 자동으로 투입량이 계산됩니다</div>
      <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
        <thead><tr style="border-bottom:1px solid var(--border-subtle);">
          <th style="text-align:left;padding:0.4rem 0.5rem;color:var(--text-muted);font-size:0.68rem;">원료명</th>
          <th style="text-align:right;padding:0.4rem 0.5rem;color:var(--text-muted);font-size:0.68rem;">1,000개 기준</th>
          <th style="text-align:right;padding:0.4rem 0.5rem;color:var(--text-muted);font-size:0.68rem;">손실률</th>
        </tr></thead>
        <tbody>
        ${product.rawBom.map(b => `<tr style="border-bottom:1px solid var(--border-subtle);">
          <td style="padding:0.4rem 0.5rem;font-weight:600;">${b.name}</td>
          <td style="padding:0.4rem 0.5rem;text-align:right;">${b.qty} ${b.unit}</td>
          <td style="padding:0.4rem 0.5rem;text-align:right;color:var(--color-warning);">${(b.lossRate*100).toFixed(0)}%</td>
        </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  },

  updatePreview(productId, qty) {
    const product = HACCP_DATA.products.find(p => p.id === productId);
    if (!product || !qty) return;

    this.currentRawNeeds = AutoDocEngine.calcRawNeeds(product, qty);
    this.currentSubNeeds = AutoDocEngine.calcSubNeeds(product, qty);
    const rawNeeds = this.currentRawNeeds;
    const subNeeds = this.currentSubNeeds;
    const warnings = AutoDocEngine.checkStock(rawNeeds, subNeeds);
    const date     = document.getElementById('prd_date')?.value || new Date().toISOString().split('T')[0];
    const lot      = AutoDocEngine.generateLot(productId, date);
    const expiry   = AutoDocEngine.calcExpiryDate(date, product.shelfDays);

    const panel = document.getElementById('previewPanel');
    panel.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:1rem;">

      <!-- LOT 미리보기 -->
      <div class="card" style="border-color:rgba(0,212,170,0.2);background:rgba(0,212,170,0.04);">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:0.2rem;">생성될 LOT 번호</div>
            <div style="font-size:1.5rem;font-weight:900;color:var(--brand-primary);letter-spacing:0.05em;">${lot}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:0.7rem;color:var(--text-muted);">유통기한</div>
            <div style="font-size:0.9rem;font-weight:700;color:var(--color-warning);">${expiry}</div>
            <div style="font-size:0.65rem;color:var(--text-muted);">(${product.shelfDays}일)</div>
          </div>
        </div>
      </div>

      <!-- 재고 경고 -->
      ${warnings.length > 0 ? `
      <div class="card" style="border-color:rgba(245,158,11,0.3);background:rgba(245,158,11,0.04);">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--color-warning)" stroke-width="2" style="width:16px;height:16px;flex-shrink:0;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <span style="font-size:0.8rem;font-weight:700;color:var(--color-warning);">재고 부족 경고 ${warnings.length}건</span>
        </div>
        ${warnings.map(w => `
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid var(--border-subtle);font-size:0.75rem;">
          <span style="font-weight:600;">${w.name}</span>
          <span style="color:var(--color-danger);">필요 ${w.need}${w.unit} / 현재 ${w.have}${w.unit}</span>
        </div>`).join('')}
      </div>` : `
      <div class="card" style="border-color:rgba(16,185,129,0.2);background:rgba(16,185,129,0.04);padding:0.875rem;">
        <div style="display:flex;align-items:center;gap:0.5rem;">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" stroke-width="2" style="width:16px;height:16px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <span style="font-size:0.8rem;font-weight:700;color:var(--color-success);">원료·부자재 재고 충분 ✓</span>
        </div>
      </div>`}

      <!-- 원료 투입량 -->
      <div class="card">
        <div class="card-header" style="margin-bottom:0.75rem;">
          <div class="card-title" style="font-size:0.85rem;">📦 원료 불출 예정량</div>
          <span class="badge badge-info">${rawNeeds.length}품목</span>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
          <thead><tr style="border-bottom:1px solid var(--border-subtle);">
            <th style="text-align:left;padding:0.35rem 0.5rem;color:var(--text-muted);font-size:0.68rem;">원료명</th>
            <th style="text-align:right;padding:0.35rem 0.5rem;color:var(--text-muted);font-size:0.68rem;">순투입</th>
            <th style="text-align:right;padding:0.35rem 0.5rem;color:var(--text-muted);font-size:0.68rem;">총불출(손실포함)</th>
            <th style="text-align:center;padding:0.35rem 0.5rem;color:var(--text-muted);font-size:0.68rem;">재고상태</th>
          </tr></thead>
          <tbody>
          ${rawNeeds.map(r => {
            const stock = HACCP_DATA.currentStock.raw.find(s => s.id === r.rmId);
            const ok = stock && stock.balance >= r.totalQty;
            return `<tr style="border-bottom:1px solid var(--border-subtle);">
              <td style="padding:0.35rem 0.5rem;font-weight:600;color:var(--text-primary);">${r.name}</td>
              <td style="padding:0.35rem 0.5rem;text-align:right;">${r.planQty} ${r.unit}</td>
              <td style="padding:0.35rem 0.5rem;text-align:right;">
                <input type="number" class="form-control" style="width:70px;text-align:right;padding:0.25rem;font-size:0.75rem;display:inline-block;" value="${r.totalQty}" step="0.01" oninput="ProductionPage.currentRawNeeds.find(x=>x.rmId==='${r.rmId}').totalQty = parseFloat(this.value);" /> ${r.unit}
              </td>
              <td style="padding:0.35rem 0.5rem;text-align:center;">
                <span class="badge ${ok?'badge-success':'badge-danger'}">${ok?'충분':'부족'}</span>
              </td>
            </tr>`;
          }).join('')}
          </tbody>
        </table>
      </div>

      <!-- 부자재 투입량 -->
      <div class="card">
        <div class="card-header" style="margin-bottom:0.75rem;">
          <div class="card-title" style="font-size:0.85rem;">🗃️ 부자재 불출 예정량</div>
          <span class="badge badge-info">${subNeeds.length}품목</span>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
          <thead><tr style="border-bottom:1px solid var(--border-subtle);">
            <th style="text-align:left;padding:0.35rem;color:var(--text-muted);font-size:0.68rem;">부자재명</th>
            <th style="text-align:right;padding:0.35rem;color:var(--text-muted);font-size:0.68rem;">불출량</th>
            <th style="text-align:center;padding:0.35rem;color:var(--text-muted);font-size:0.68rem;">재고상태</th>
          </tr></thead>
          <tbody>
          ${subNeeds.map(s => {
            const stock = HACCP_DATA.currentStock.sub.find(st => st.id === s.smId);
            const ok = stock && stock.balance >= s.qty;
            return `<tr style="border-bottom:1px solid var(--border-subtle);">
              <td style="padding:0.35rem;font-weight:600;color:var(--text-primary);">${s.name}</td>
              <td style="padding:0.35rem;text-align:right;font-weight:700;color:var(--brand-primary);">
                <input type="number" class="form-control" style="width:70px;text-align:right;padding:0.25rem;font-size:0.75rem;display:inline-block;" value="${s.qty}" oninput="ProductionPage.currentSubNeeds.find(x=>x.smId==='${s.smId}').qty = parseInt(this.value);" /> ${s.unit}
              </td>
              <td style="padding:0.35rem;text-align:center;">
                <span class="badge ${ok?'badge-success':'badge-danger'}">${ok?'충분':'부족'}</span>
              </td>
            </tr>`;
          }).join('')}
          </tbody>
        </table>
      </div>

      <!-- 생성될 문서 목록 -->
      <div class="card">
        <div class="card-header" style="margin-bottom:0.75rem;">
          <div class="card-title" style="font-size:0.85rem;">📄 자동 생성될 문서</div>
        </div>
        ${[
          { icon:'📦', label:'원료 수불대장 (불출)',   count: rawNeeds.length+'건', color:'var(--color-info)' },
          { icon:'🗃️', label:'부자재 수불대장 (불출)', count: subNeeds.length+'건', color:'var(--color-info)' },
          { icon:'⚠️', label:'CCP 모니터링 일지 슬롯', count: (product.ccpIds.length*5)+'개 슬롯', color:'var(--color-warning)' },
          { icon:'🔬', label:'자가품질검사 목록',       count: product.qualityStandards.length+'항목', color:'var(--color-warning)' },
          { icon:'✅', label:'완제품 수불 (생산입고)',  count: qty.toLocaleString()+'개', color:'var(--color-success)' },
        ].map(d => `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:0.5rem 0;border-bottom:1px solid var(--border-subtle);">
          <div style="display:flex;align-items:center;gap:0.6rem;">
            <span style="font-size:1rem;">${d.icon}</span>
            <span style="font-size:0.8rem;">${d.label}</span>
          </div>
          <span style="font-size:0.78rem;font-weight:700;color:${d.color};">${d.count}</span>
        </div>`).join('')}
      </div>
    </div>`;
  },

  // ───────────────────────────────────────
  // 자동 생성 실행!
  // ───────────────────────────────────────
  runAutoGen() {
    const productId  = document.getElementById('prd_product')?.value;
    const date       = document.getElementById('prd_date')?.value;
    const qty        = parseInt(document.getElementById('prd_qty')?.value || '0');
    const operator   = document.getElementById('prd_operator')?.value;
    const line       = document.getElementById('prd_line')?.value;
    const startTime  = document.getElementById('prd_startTime')?.value;
    const endTime    = document.getElementById('prd_endTime')?.value;
    const note       = document.getElementById('prd_note')?.value;
    const workers    = [...document.querySelectorAll('.prd_worker:checked')].map(c => c.value);
    const foodType   = document.getElementById('prd_foodType')?.value || '';
    const expiryDate = document.getElementById('prd_expiryDate')?.value || '';

    // 유효성 검사
    if (!productId) { App.showToast('error','입력 오류','제품을 선택해주세요.'); return; }
    if (!qty || qty < 100) { App.showToast('error','입력 오류','생산 수량을 입력해주세요. (최소 100개)'); return; }
    if (!operator) { App.showToast('error','입력 오류','작업 책임자를 선택해주세요.'); return; }

    // 로딩 표시
    const btn = document.getElementById('genBtn');
    btn.disabled = true;
    btn.innerHTML = `<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:18px;height:18px;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> 생성 중...`;

    // 약간의 딜레이로 UI 피드백 제공
    setTimeout(() => {
      const result = AutoDocEngine.generate({
        productId, date, planQty: qty, line, startTime, endTime,
        operator, workers, note, foodType, expiryDate,
        customRawNeeds: this.currentRawNeeds,
        customSubNeeds: this.currentSubNeeds
      });

      btn.disabled = false;
      btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:18px;height:18px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 전자동 문서 생성 실행`;

      if (result.success) {
        this.showResultModal(result);
      } else {
        App.showToast('error', '생성 실패', result.error);
      }
    }, 800);
  },

  // ───────────────────────────────────────
  // 생성 결과 모달
  // ───────────────────────────────────────
  showResultModal(result) {
    const { lot, product, planQty, rawNeeds, subNeeds, stockWarnings,
            ccpTemplate, qualityChecks, ledgerResult, historyEntry } = result;

    App.showModal(`✅ 전자동 문서 생성 완료`, `
      <!-- 성공 헤더 -->
      <div style="text-align:center;padding:1rem 0 1.5rem;">
        <div style="width:64px;height:64px;background:rgba(16,185,129,0.12);border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 0.75rem;">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" stroke-width="2" style="width:32px;height:32px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        </div>
        <div style="font-size:1.3rem;font-weight:900;color:var(--brand-primary);">${lot}</div>
        <div style="font-size:0.85rem;color:var(--text-muted);margin-top:0.25rem;">${product.name} · ${planQty.toLocaleString()}개 생산 문서</div>
      </div>

      <!-- 생성된 문서 요약 -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:1rem;">
        ${historyEntry.documents.map(doc => {
          const icons = { raw_ledger:'📦', sub_ledger:'🗃️', ccp_log:'⚠️', quality_check:'🔬', finished_ledger:'✅' };
          const colors = { done:'var(--color-success)', pending:'var(--color-warning)' };
          return `
          <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);border:1px solid ${doc.status==='done'?'rgba(16,185,129,0.2)':'rgba(245,158,11,0.2)'};">
            <div style="font-size:1.2rem;margin-bottom:0.3rem;">${icons[doc.type]||'📄'}</div>
            <div style="font-size:0.78rem;font-weight:700;color:var(--text-primary);">${doc.label}</div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin-top:0.3rem;">
              <span style="font-size:0.75rem;font-weight:800;color:${doc.status==='done'?'var(--brand-primary)':'var(--color-warning)'};">${doc.count}건</span>
              <span class="badge ${doc.status==='done'?'badge-success':'badge-warning'}">${doc.status==='done'?'자동완료':'입력필요'}</span>
            </div>
          </div>`;
        }).join('')}
      </div>

      ${stockWarnings.length > 0 ? `
      <div style="padding:0.75rem;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:var(--radius-md);margin-bottom:1rem;">
        <div style="font-size:0.8rem;font-weight:700;color:var(--color-warning);margin-bottom:0.4rem;">⚠️ 재고 부족 발생 - 추가 구매 필요</div>
        ${stockWarnings.map(w => `
        <div style="font-size:0.75rem;color:var(--text-secondary);">
          · ${w.name}: 필요 ${w.need}${w.unit} / 현재고 ${w.have}${w.unit}
        </div>`).join('')}
      </div>` : ''}

      <!-- 다음 할 일 -->
      <div style="padding:0.875rem;background:var(--bg-elevated);border-radius:var(--radius-md);">
        <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);margin-bottom:0.6rem;text-transform:uppercase;letter-spacing:0.05em;">다음 단계 (작업자 직접 입력 필요)</div>
        ${[
          { icon:'⚠️', text:'CCP 모니터링 일지 - 각 측정 슬롯에 실측값 입력', page:'ccp-monitoring' },
          { icon:'🔬', text:'자가품질검사 - 검사 후 결과값 및 판정 입력', page:'quality-check' },
          { icon:'🏭', text:'생산일지 - 종료 후 실 생산량·불량수 입력', page:'production-log' },
        ].map(t => `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid var(--border-subtle);">
          <div style="font-size:0.78rem;">${t.icon} ${t.text}</div>
          <button class="btn btn-secondary btn-sm" onclick="App.closeModal();App.navigate('${t.page}');">이동</button>
        </div>`).join('')}
      </div>`,
      [
        { text: '생성 이력 확인', class: 'btn-secondary', action: "App.closeModal();ProductionPage.switchTab('history');" },
        { text: '확인', class: 'btn-primary', action: 'App.closeModal();' }
      ]
    );
  },

  // ───────────────────────────────────────
  // 생성 이력 탭
  // ───────────────────────────────────────
  renderHistory() {
    const history = HACCP_DATA.autoGenHistory;
    if (history.length === 0) return `
      <div class="empty-state">
        <div class="empty-state-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
        <h3>생성 이력 없음</h3><p>자동 생성 마법사를 실행하면 이력이 쌓입니다.</p>
      </div>`;

    return `
    <div style="display:flex;flex-direction:column;gap:1rem;">
      ${history.map(h => `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;">
          <div>
            <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.25rem;">
              <span style="font-size:1.1rem;font-weight:900;color:var(--brand-primary);">${h.lot}</span>
              <span class="badge badge-success badge-dot">생성완료</span>
            </div>
            <div style="font-size:0.78rem;color:var(--text-muted);">${h.product} · ${h.qty.toLocaleString()}개 · 생성: ${h.generatedAt} · 책임자: ${h.operator}</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="ProductionPage.viewHistoryDetail('${h.id}')">상세보기</button>
        </div>

        <!-- 문서 상태 그리드 -->
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:0.5rem;">
          ${h.documents.map(doc => {
            const icons = { raw_ledger:'📦', sub_ledger:'🗃️', ccp_log:'⚠️', quality_check:'🔬', finished_ledger:'✅' };
            const labels = { raw_ledger:'원료수불', sub_ledger:'부자재', ccp_log:'CCP일지', quality_check:'품질검사', finished_ledger:'완제품' };
            return `
            <div style="text-align:center;padding:0.6rem 0.3rem;background:var(--bg-elevated);border-radius:var(--radius-md);border:1px solid ${doc.status==='done'?'rgba(16,185,129,0.2)':'rgba(245,158,11,0.2)'};">
              <div style="font-size:1.1rem;">${icons[doc.type]||'📄'}</div>
              <div style="font-size:0.62rem;color:var(--text-muted);margin-top:0.2rem;">${labels[doc.type]||doc.type}</div>
              <div style="font-size:0.72rem;font-weight:800;color:${doc.status==='done'?'var(--color-success)':'var(--color-warning)'};">${doc.count}건</div>
              <div style="margin-top:0.2rem;"><span class="badge ${doc.status==='done'?'badge-success':'badge-warning'}" style="font-size:0.55rem;">${doc.status==='done'?'완료':'대기'}</span></div>
            </div>`;
          }).join('')}
        </div>
      </div>`).join('')}
    </div>`;
  },

  viewHistoryDetail(id) {
    const h = HACCP_DATA.autoGenHistory.find(ag => ag.id === id);
    if (!h) return;
    // 해당 LOT의 수불 내역 추출
    const rawItems = HACCP_DATA.rawLedger.filter(r => r.note && r.note.includes(h.lot));
    const subItems = HACCP_DATA.subLedger.filter(s => s.note && s.note.includes(h.lot));

    App.showModal(`📋 자동생성 상세 - ${h.lot}`, `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:1rem;">
        <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);">
          <div style="font-size:0.65rem;color:var(--text-muted);">LOT 번호</div>
          <div style="font-weight:800;color:var(--brand-primary);">${h.lot}</div>
        </div>
        <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);">
          <div style="font-size:0.65rem;color:var(--text-muted);">생산 수량</div>
          <div style="font-weight:800;">${h.qty.toLocaleString()}개</div>
        </div>
      </div>

      <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);margin-bottom:0.5rem;">원료 불출 내역</div>
      ${rawItems.length > 0 ? rawItems.map(r => `
      <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid var(--border-subtle);font-size:0.78rem;">
        <span style="font-weight:600;">${r.name}</span>
        <span style="color:var(--color-danger);">-${r.qty} ${r.unit || ''}</span>
      </div>`).join('') : '<div style="font-size:0.75rem;color:var(--text-muted);padding:0.5rem 0;">내역 없음</div>'}

      <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);margin-top:0.75rem;margin-bottom:0.5rem;">부자재 불출 내역</div>
      ${subItems.length > 0 ? subItems.map(s => `
      <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid var(--border-subtle);font-size:0.78rem;">
        <span style="font-weight:600;">${s.name}</span>
        <span style="color:var(--color-danger);">-${s.qty.toLocaleString()}개</span>
      </div>`).join('') : '<div style="font-size:0.75rem;color:var(--text-muted);padding:0.5rem 0;">내역 없음</div>'}`,
      [{ text: '닫기', class: 'btn-secondary', action: 'App.closeModal()' }]
    );
  },

  // ───────────────────────────────────────
  // 생산일지 목록 탭
  // ───────────────────────────────────────
  logFilter: { keyword: '', startDate: '2024-01-01', endDate: new Date().toISOString().split('T')[0] },

  updateLogFilter(key, value) {
    this.logFilter[key] = value;
    if (key === 'startDate' || key === 'endDate') {
      const container = document.getElementById('pageContainer');
      if (container) container.innerHTML = this.render();
      this.switchTab('logs');
    } else {
      const content = document.getElementById('prodContent');
      if (content) content.innerHTML = this.renderContent();
    }
  },

  setDateRange(range) {
    const today = new Date('2026-03-20'); // 시스템 기준 날짜
    const fmt = d => d.toISOString().split('T')[0];
    if (range === 'all') {
      this.logFilter.startDate = ''; this.logFilter.endDate = '';
    } else if (range === '2year') {
      const from = new Date(today);
      from.setFullYear(from.getFullYear() - 2);
      this.logFilter.startDate = fmt(from); this.logFilter.endDate = fmt(today);
    } else if (range === 'year') {
      this.logFilter.startDate = `${today.getFullYear()}-01-01`;
      this.logFilter.endDate   = `${today.getFullYear()}-12-31`;
    } else if (range === '6month') {
      const from = new Date(today);
      from.setMonth(from.getMonth() - 6);
      this.logFilter.startDate = fmt(from); this.logFilter.endDate = fmt(today);
    } else if (range === 'month') {
      this.logFilter.startDate = fmt(new Date(today.getFullYear(), today.getMonth(), 1));
      this.logFilter.endDate   = fmt(new Date(today.getFullYear(), today.getMonth() + 1, 0));
    }
    const container = document.getElementById('pageContainer');
    if (container) container.innerHTML = this.render();
    this.switchTab('logs');
  },

  renderLogs() {
    const filter = this.logFilter;
    const logs = HACCP_DATA.productionLogs.filter(log => {
      const matchKeyword = !filter.keyword || 
        (log.product && log.product.toLowerCase().includes(filter.keyword.toLowerCase())) || 
        (log.lot && log.lot.toLowerCase().includes(filter.keyword.toLowerCase()));
      const matchStart = !filter.startDate || log.date >= filter.startDate;
      const matchEnd = !filter.endDate || log.date <= filter.endDate;
      return matchKeyword && matchStart && matchEnd;
    });

    return `
    ${logs.length === 0 ? '<div class="empty-state">검색결과가 없습니다.</div>' : logs.map(log => {
      const planQty   = log.planQty   ?? log.productionQty ?? 0;
      const actualQty = log.actualQty ?? log.productionQty ?? 0;
      const defectQty = log.defectQty ?? 0;
      const workers   = Array.isArray(log.workers) ? log.workers : (log.worker ? [log.worker] : []);
      const ccpList   = Array.isArray(log.ccp) ? log.ccp : [];
      const yieldPct  = planQty > 0 ? (((actualQty - defectQty) / planQty) * 100).toFixed(1) : '-';
      return `
    <div class="card" style="margin-bottom:1rem;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;">
        <div>
          <div style="display:flex;align-items:center;gap:0.75rem;">
            <h2 style="font-size:1rem;font-weight:800;">${log.product}</h2>
            <span class="badge ${log.status==='completed'?'badge-success':log.status==='in-progress'?'badge-info':'badge-neutral'} badge-dot">
              ${log.status==='completed'?'완료':log.status==='in-progress'?'진행중':'대기'}
            </span>
            ${log.autoGenerated ? '<span class="badge badge-brand">자동생성</span>' : ''}
          </div>
          <div style="font-size:0.78rem;color:var(--text-muted);margin-top:0.2rem;">
            LOT: <code style="color:var(--brand-primary);">${log.lot}</code> · ${log.date} · ${log.line} · ${log.startTime}${log.endTime?'~'+log.endTime:''}
          </div>
        </div>
        <div class="d-flex gap-1">
          ${log.status==='in-progress'?`<button class="btn btn-primary btn-sm" onclick="ProductionPage.completeLog('${log.id}')">생산완료 처리</button>`:''}
          <button class="btn btn-secondary btn-sm" onclick="ProductionPage.viewLogDetail('${log.id}')">상세</button>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.5rem;margin-bottom:0.75rem;">
        ${[
          { label:'계획', val: planQty ? planQty.toLocaleString() : '-', color:'var(--text-primary)' },
          { label:`생산(${log.unit||''})`, val: actualQty ? actualQty.toLocaleString() : '-', color:'var(--color-success)' },
          { label:'불량', val: String(defectQty), color:'var(--color-danger)' },
          { label:'수율', val: yieldPct !== '-' ? yieldPct + '%' : '-', color:'var(--color-info)' },
        ].map(s => `
        <div style="text-align:center;padding:0.6rem;background:var(--bg-elevated);border-radius:var(--radius-md);">
          <div style="font-size:1.1rem;font-weight:800;color:${s.color};">${s.val}</div>
          <div style="font-size:0.65rem;color:var(--text-muted);">${s.label}</div>
        </div>`).join('')}
      </div>

      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
        ${workers.length > 0 ? `<div>
          <span style="font-size:0.68rem;color:var(--text-muted);">작업자: </span>
          ${workers.map(w=>`<span class="badge badge-neutral" style="margin-right:0.25rem;">${w}</span>`).join('')}
        </div>` : ''}
        ${ccpList.length > 0 ? `<div>
          <span style="font-size:0.68rem;color:var(--text-muted);">CCP: </span>
          ${ccpList.map(c=>`<span class="badge badge-brand" style="margin-right:0.25rem;">${c}</span>`).join('')}
        </div>` : ''}
      </div>
    </div>`;
    }).join('')}`;
  },

  completeLog(id) {
    const log = HACCP_DATA.productionLogs.find(p => p.id === id);
    if (!log) return;
    App.showModal('생산 완료 처리', `
      <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);margin-bottom:1rem;">
        <div style="font-size:0.75rem;color:var(--text-muted);">LOT</div>
        <div style="font-weight:700;color:var(--brand-primary);">${log.lot}</div>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label class="form-label">실 생산량(개) *</label>
          <input type="number" class="form-control" id="comp_actual" value="${log.planQty}" />
        </div>
        <div class="form-group">
          <label class="form-label">불량수(개)</label>
          <input type="number" class="form-control" id="comp_defect" value="0" min="0" />
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">종료시간</label>
        <input type="time" class="form-control" id="comp_endTime" />
      </div>
      <div class="form-group">
        <label class="form-label">비고</label>
        <textarea class="form-control" rows="2" placeholder="특이사항..."></textarea>
      </div>`,
      [
        { text: '취소', class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '완료 처리', class: 'btn-primary', action: `
          const actual = parseInt(document.getElementById('comp_actual').value);
          const defect = parseInt(document.getElementById('comp_defect').value||0);
          const pl = HACCP_DATA.productionLogs.find(p => p.id === '${id}');
          if(pl){ pl.actualQty=actual; pl.defectQty=defect; pl.status='completed'; pl.endTime=document.getElementById('comp_endTime').value; }
          App.closeModal();
          ProductionPage.switchTab('logs');
          App.showToast('success','완료','생산 완료 처리되었습니다.');` }
      ]
    );
  },

  viewLogDetail(id) {
    const log = HACCP_DATA.productionLogs.find(p => p.id === id);
    if (!log) return;
    const mats = Array.isArray(log.materials) ? log.materials : [];
    const planQty   = log.planQty   ?? log.productionQty ?? 0;
    const actualQty = log.actualQty ?? log.productionQty ?? 0;
    const workers   = Array.isArray(log.workers) ? log.workers : (log.worker ? [log.worker] : []);
    App.showModal(`생산일지 상세 - ${log.product}`, `
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;margin-bottom:1rem;">
        <div style="padding:0.6rem;background:var(--bg-elevated);border-radius:6px;">
          <div style="font-size:0.65rem;color:var(--text-muted);">제조일</div>
          <div style="font-weight:700;">${log.date||'-'}</div>
        </div>
        <div style="padding:0.6rem;background:var(--bg-elevated);border-radius:6px;">
          <div style="font-size:0.65rem;color:var(--text-muted);">LOT</div>
          <div style="font-weight:700;color:var(--brand-primary);">${log.lot||'-'}</div>
        </div>
        <div style="padding:0.6rem;background:var(--bg-elevated);border-radius:6px;">
          <div style="font-size:0.65rem;color:var(--text-muted);">생산량</div>
          <div style="font-weight:700;color:var(--color-success);">${(actualQty||0).toLocaleString()} ${log.unit||''}</div>
        </div>
        ${log.expiryDate ? `<div style="padding:0.6rem;background:var(--bg-elevated);border-radius:6px;">
          <div style="font-size:0.65rem;color:var(--text-muted);">소비기한</div>
          <div style="font-weight:700;">${log.expiryDate}</div>
        </div>` : ''}
        ${workers.length > 0 ? `<div style="padding:0.6rem;background:var(--bg-elevated);border-radius:6px;grid-column:span 2;">
          <div style="font-size:0.65rem;color:var(--text-muted);">담당자</div>
          <div style="font-weight:700;">${workers.join(', ')}</div>
        </div>` : ''}
      </div>
      ${mats.length > 0 ? `
      <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);margin-bottom:0.5rem;">📦 투입원료</div>
      <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
        <thead><tr style="border-bottom:1px solid var(--border-subtle);">
          <th style="text-align:left;padding:0.4rem 0.5rem;color:var(--text-muted);">원료명</th>
          <th style="text-align:right;padding:0.4rem 0.5rem;color:var(--text-muted);">투입량</th>
        </tr></thead>
        <tbody>
        ${mats.map(m => `
        <tr style="border-bottom:1px solid var(--border-subtle);">
          <td style="padding:0.5rem;font-weight:600;">${m.name||'-'}</td>
          <td style="padding:0.5rem;text-align:right;color:var(--brand-primary);">
            ${m.actualQty !== undefined ? `계획 ${m.planQty||0}${m.unit} / 실투입 ${m.actualQty}${m.unit}` : `${(m.qty||0).toLocaleString()} ${m.unit||''}`}
          </td>
        </tr>`).join('')}
        </tbody>
      </table>` : '<div style="color:var(--text-muted);font-size:0.8rem;">투입원료 정보 없음</div>'}
      ${log.note ? `<div style="margin-top:0.75rem;padding:0.5rem;background:var(--bg-elevated);border-radius:6px;font-size:0.78rem;"><span style="color:var(--text-muted);">비고: </span>${log.note}</div>` : ''}`,
      [{ text: '닫기', class: 'btn-secondary', action: 'App.closeModal()' }]
    );
  },


  switchTab(tab) {
    this.currentTab = tab;
    App.navigate('production-log');
  }
};
