// =============================================
// BIODOT HACCP - 수불대장 모듈
// =============================================

const InventoryPage = {
  currentType: 'raw',
  currentTab: 'ledger',
  searchQuery: '',
  filterType: '',       // '' | 'in' | 'out'
  filterFoodType: '',   // '' | '기타가공품' | '고형차' | '추출가공식품' | '액상차' | '캔디류' | '일반식품'
  dateFrom: (() => { const d = new Date(); d.setFullYear(d.getFullYear() - 2); return d.toISOString().split('T')[0]; })(),
  dateTo: '',
  displayUnit: null,
  stockSortField: '',   // '' | 'name' | 'stock'
  stockSortOrder: 'asc',// 'asc' | 'desc'

  // ============================================
  // 단위 변환 유틸리티
  // ============================================
  UNIT_GROUPS: {
    weight: ['kg', 'g', 'mg'],
    volume: ['L', 'mL', 'cc']
  },
  // 기준 단위(kg, L)-> 먹스 변수(g=1000, kg=1)
  UNIT_TO_BASE: { 'kg': 1, 'g': 0.001, 'mg': 0.000001, 'L': 1, 'mL': 0.001, 'cc': 0.001 },

  // 해당 단위가 어떤 그룹인지 리턴
  getUnitGroup(unit) {
    if (!unit) return null;
    const u = unit.trim();
    if (['kg','g','mg'].includes(u)) return 'weight';
    if (['L','mL','cc','ml'].includes(u)) return 'volume';
    return null;
  },

  // from 단위의 qty를 to 단위로 변환
  convertQty(qty, fromUnit, toUnit) {
    if (!fromUnit || !toUnit || fromUnit === toUnit) return qty;
    const fromBase = this.UNIT_TO_BASE[fromUnit] || this.UNIT_TO_BASE[fromUnit.replace('ml','mL')];
    const toBase   = this.UNIT_TO_BASE[toUnit]   || this.UNIT_TO_BASE[toUnit.replace('ml','mL')];
    if (!fromBase || !toBase) return qty;
    const group1 = this.getUnitGroup(fromUnit);
    const group2 = this.getUnitGroup(toUnit);
    if (group1 !== group2) return qty; // 다른 그룹은 변환 방지
    return parseFloat((qty * fromBase / toBase).toPrecision(10));
  },

  // ex) '1.5 kg', '500 mL' 형식으로 포매팅
  formatQty(qty, unit, targetUnit) {
    const converted = targetUnit ? this.convertQty(qty, unit, targetUnit) : qty;
    const displayU = targetUnit || unit || '';
    const num = parseFloat(converted.toFixed(4));
    // 소수점 정리: 영이면 정수 표시
    const formatted = Number.isInteger(num) ? num.toLocaleString() : num.toLocaleString();
    return `${formatted} <span style="font-size:0.75rem;color:var(--text-muted);">${displayU}</span>`;
  },

  // 해당 단위에서 전환 가능한 다른 단위 목록 리턴
  getAltUnits(unit) {
    const group = this.getUnitGroup(unit);
    if (group === 'weight') return ['kg', 'g', 'mg'];
    if (group === 'volume') return ['L', 'mL'];
    return [];
  },

  render(type = 'raw') {
    this.currentType = type;
    const titles = { raw: '원료 수불대장', sub: '부자재 수불대장', finished: '완제품 수불대장' };
    const descs = { raw: '원재료 입출고 내역 및 현재고 관리', sub: '포장재 및 부자재 입출고 현황', finished: '완제품 생산입고 및 출하 관리' };

    return `
    <div class="fade-in" style="display: flex; flex-direction: column; height: calc(100vh - 80px); overflow: hidden;">
      <div style="flex-shrink: 0; padding-bottom: 0.5rem;"><div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">${titles[type]}</h1>
          <p class="page-desc">${descs[type]}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" onclick="InventoryPage.exportExcel()" style="color:var(--text-primary);border:1px solid var(--border-strong);">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            엑셀 다운로드
          </button>
          <button class="btn btn-secondary" onclick="InventoryPage.openBulkUploadModal()" style="background:var(--bg-elevated);color:var(--brand-primary);border:1px solid var(--brand-primary);font-weight:600;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            일괄 업로드
          </button>
          <button class="btn btn-secondary" onclick="InventoryPage.openNewItemModal('${type}')" style="background:#f8f9fa;color:var(--text-primary);border:1px solid var(--border-strong);">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            새 품목 등록
          </button>
          <button class="btn btn-primary" onclick="InventoryPage.openModal()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            ${type === 'finished' ? '출하/입고 등록' : '입출고 등록'}
          </button>
        </div>
      </div>

      <!-- 탭 -->
      <div class="tabs">
        <button class="tab-btn ${this.currentTab === 'ledger' ? 'active' : ''}" onclick="InventoryPage.switchTab('ledger')">📋 수불 내역</button>
        <button class="tab-btn ${this.currentTab === 'stock' ? 'active' : ''}" onclick="InventoryPage.switchTab('stock')">📦 현재고</button>
      </div>

      <!-- 검색 바 (1줄) -->
      <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.5rem;align-items:center;">
        <div class="search-input-wrap" style="flex:1;min-width:180px;">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="text" class="form-control" id="invSearch" placeholder="품목명, LOT, 거래처 검색..." oninput="InventoryPage.onSearch(this.value)" />
        </div>
        <select class="form-control" style="width:auto;" onchange="InventoryPage.onFilter(this.value)">
          <option value="" ${!this.filterType?'selected':''}>전체</option>
          <option value="in" ${this.filterType==='in'?'selected':''}>↑ 입고만</option>
          <option value="out" ${this.filterType==='out'?'selected':''}>↓ 출고만</option>
        </select>
        ${this.currentType === 'finished' ? `
        <select class="form-control" style="width:auto;min-width:120px;" onchange="InventoryPage.onFilterFoodType(this.value)">
          <option value="" ${!this.filterFoodType?'selected':''}>🏷️ 식품유형 전체</option>
          <option value="기타가공품" ${this.filterFoodType==='기타가공품'?'selected':''}>기타가공품</option>
          <option value="고형차" ${this.filterFoodType==='고형차'?'selected':''}>고형차</option>
          <option value="추출가공식품" ${this.filterFoodType==='추출가공식품'?'selected':''}>추출가공식품</option>
          <option value="액상차" ${this.filterFoodType==='액상차'?'selected':''}>액상차</option>
          <option value="캔디류" ${this.filterFoodType==='캔디류'?'selected':''}>캔디류</option>
          <option value="일반식품" ${this.filterFoodType==='일반식품'?'selected':''}>일반식품</option>
        </select>` : ''}
      </div>
      <!-- 날짜 빠른 선택 바 (2줄) -->
      <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:0.75rem;align-items:center;padding:0.5rem;background:#f8f9fa;border-radius:6px;border:1px solid var(--border-subtle);">
        <span style="font-size:0.72rem;color:var(--text-muted);font-weight:700;white-space:nowrap;">📅 기간:</span>
        <button onclick="InventoryPage.setDateRange('all')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid ${!this.dateFrom&&!this.dateTo?'var(--brand-primary)':'var(--border-strong)'};background:${!this.dateFrom&&!this.dateTo?'var(--brand-primary)':'#fff'};color:${!this.dateFrom&&!this.dateTo?'#fff':'var(--text-secondary)'};cursor:pointer;font-weight:600;">전체</button>
        <button onclick="InventoryPage.setDateRange('2year')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">2년</button>
        <button onclick="InventoryPage.setDateRange('year')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">📆 올해</button>
        <button onclick="InventoryPage.setDateRange('6month')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">6개월</button>
        <button onclick="InventoryPage.setDateRange('month')" style="font-size:0.72rem;padding:0.2rem 0.55rem;border-radius:20px;border:1px solid var(--border-strong);background:#fff;color:var(--text-secondary);cursor:pointer;font-weight:600;">이번 달</button>
        <span style="font-size:0.75rem;color:var(--border-strong);margin:0 0.15rem;">|</span>
        <input type="date" id="invDateFrom" class="form-control" style="width:130px;font-size:0.78rem;padding:0.2rem 0.4rem;" value="${this.dateFrom}" onchange="InventoryPage.onDateChange('from', this.value)" />
        <span style="font-size:0.8rem;color:var(--text-muted);">~</span>
        <input type="date" id="invDateTo"   class="form-control" style="width:130px;font-size:0.78rem;padding:0.2rem 0.4rem;" value="${this.dateTo}"   onchange="InventoryPage.onDateChange('to',   this.value)" />
        ${(this.dateFrom||this.dateTo)?`<button onclick="InventoryPage.setDateRange('all')" style="font-size:0.72rem;padding:0.2rem 0.5rem;border-radius:4px;border:1px solid var(--color-danger);background:transparent;color:var(--color-danger);cursor:pointer;">✕ 초기화</button>`:''}
      </div>

      </div><!-- 컨텐츠 -->
      <div id="invContent" style="flex: 1; overflow-y: auto; padding-right: 5px;">${this.renderContent()}</div>
    </div>`;
  },

  renderContent() {
    if (this.currentTab === 'ledger') return this.renderLedger();
    return this.renderStock();
  },

  renderLedger() {
    const ledger = this.currentType === 'raw' ? HACCP_DATA.rawLedger
                 : this.currentType === 'sub' ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;

    const filtered = ledger.filter(r => {
      // 텍스트 검색
      if (this.searchQuery) {
        const q = this.searchQuery.toLowerCase().replace(/\s+/g, '');
        const match = (r.name && String(r.name).toLowerCase().replace(/\s+/g, '').includes(q)) || 
                      (r.lot && String(r.lot).toLowerCase().replace(/\s+/g, '').includes(q)) || 
                      (r.supplier && String(r.supplier).toLowerCase().replace(/\s+/g, '').includes(q)) || 
                      (r.customer && String(r.customer).toLowerCase().replace(/\s+/g, '').includes(q));
        if (!match) return false;
      }
      // 타입 필터 (입고/출고)
      if (this.filterType && r.type !== this.filterType) return false;
      // 식품유형 필터 (완제품 전용)
      if (this.currentType === 'finished' && this.filterFoodType) {
        const name = r.name || '';
        const stock = HACCP_DATA.currentStock.finished.find(s => s.name === name);
        if (!stock || stock.foodType !== this.filterFoodType) return false;
      }
      // 날짜 필터
      if (this.dateFrom && r.date < this.dateFrom) return false;
      if (this.dateTo && r.date > this.dateTo) return false;
      return true;
    });

    filtered.sort((a, b) => {
      const dateA = a.date || '';
      const dateB = b.date || '';
      if (dateA !== dateB) return dateB.localeCompare(dateA);
      const idA = a.id || '';
      const idB = b.id || '';
      return idB.localeCompare(idA);
    });

    const isFinished = this.currentType === 'finished';

    return `
    <div class="card" style="padding:0;">
      <div class="table-wrapper">
        <table class="data-table">
          <thead style="position: sticky; top: 0; z-index: 10; background: var(--bg-surface); box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
            <tr>
              <th>날짜</th>
              ${isFinished ? '<th>식품유형</th>' : ''}
              <th>품목명 / 규격</th>
              <th>입고량 (+) <span style="font-size:0.6rem;font-weight:400;color:var(--brand-primary);">클릭=수정</span></th>
              <th>출고량 (-) <span style="font-size:0.6rem;font-weight:400;color:var(--brand-primary);">클릭=수정</span></th>
              <th>현재고</th>
              ${this.currentType !== 'finished' ? '<th>소비기한</th>' : '<th>유통기한</th>'}
              <th>LOT번호</th>
              <th>${isFinished ? '거래처' : '공급업체'}</th>
              <th>담당자</th>
              <th>비고</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.map(r => {
              // 원료/부자재 마스터에서 spec 조회
              const masterList = this.currentType === 'raw' ? HACCP_DATA.rawMaterials
                               : this.currentType === 'sub' ? HACCP_DATA.subMaterials : [];
              const master = masterList.find(m => m.id === (r.rmId || r.smId));
              const spec = master?.spec || '';
              const unit = r.unit || master?.unit || '';
              const FOOD_TYPES = ['기타가공품','고형차','추출가공식품','액상차','캔디류','일반식품'];
              const ftColor = {'기타가공품':'#6366f1','고형차':'#10b981','추출가공식품':'#f59e0b','액상차':'#3b82f6','캔디류':'#ec4899','일반식품':'#8b5cf6'};
              return `
             <tr>
              <td class="no-wrap"><input type="date" value="${r.date}" onchange="InventoryPage.updateField('${r.id}', 'date', this.value)" class="excel-input" style="width:110px;" /></td>
              ${isFinished ? `<td>
                <select class="excel-input" style="width:100px;" onchange="InventoryPage.updateField('${r.id}','foodType',this.value)">
                  <option value="">-- 선택 --</option>
                  ${FOOD_TYPES.map(ft=>`<option value="${ft}" ${r.foodType===ft?'selected':''}>${ft}</option>`).join('')}
                </select>
              </td>` : ''}
              <td>
                <span style="font-weight:700;color:var(--brand-primary);cursor:pointer;text-decoration:underline;" onclick="InventoryPage.viewItemHistory('${r.name}')" title="이 품목의 입출고 상세 내역 보기">${r.name}</span>
                ${spec ? `<div style="font-size:0.65rem;color:var(--text-muted);margin-top:0.1rem;">${spec}</div>` : ''}
                ${isFinished && r.foodType ? `<div style="font-size:0.65rem;margin-top:2px;"><span style="background:${ftColor[r.foodType]||'#888'}22;color:${ftColor[r.foodType]||'#888'};padding:0 5px;border-radius:4px;">${r.foodType}</span></div>` : ''}
              </td>
              <td>${r.type==='in'  ? InventoryPage.renderQtyCell(r.id, 'in',  r.qty,     unit) : '<span style="color:var(--text-muted);">-</span>'}</td>
              <td>${r.type==='out' ? InventoryPage.renderQtyCell(r.id, 'out', r.qty,     unit) : '<span style="color:var(--text-muted);">-</span>'}</td>
              <td>${InventoryPage.renderQtyCell(r.id, 'bal', r.balance, unit)}</td>
              <td class="no-wrap"><input type="date" value="${r.expiryDate || ''}" onchange="InventoryPage.updateField('${r.id}', 'expiryDate', this.value)" class="excel-input" style="width:110px;" /></td>
              <td><input type="text" value="${r.lot || ''}" onchange="InventoryPage.updateField('${r.id}', 'lot', this.value)" class="excel-input" style="width:90px;font-family:monospace;color:var(--brand-primary);" placeholder="LOT" /></td>
              <td><input type="text" value="${r.supplier || r.customer || ''}" onchange="InventoryPage.updateField('${r.id}', '${isFinished ? 'customer' : 'supplier'}', this.value)" class="excel-input" style="width:90px;" placeholder="업체명" /></td>
              <td><input type="text" value="${r.inspector||''}" onchange="InventoryPage.updateField('${r.id}', 'inspector', this.value)" class="excel-input" style="width:70px;" /></td>
              <td><input type="text" value="${r.note || ''}" onchange="InventoryPage.updateField('${r.id}', 'note', this.value)" class="excel-input" style="width:120px;" placeholder="비고 입력" /></td>
              <td>
                <div class="d-flex gap-1">
                  <button class="btn btn-secondary btn-sm btn-icon" title="상세보기" onclick="InventoryPage.viewDetail('${r.id}')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                  </button>
                </div>
              </td>
            </tr>`;}).join('')}
          </tbody>
        </table>
      </div>
      <div style="padding:0.75rem 1rem;border-top:1px solid var(--border-subtle);display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:0.75rem;color:var(--text-muted);">총 ${filtered.length}건</span>
        <div class="d-flex gap-1">
          <button class="btn btn-secondary btn-sm">이전</button>
          <button class="btn btn-primary btn-sm">1</button>
          <button class="btn btn-secondary btn-sm">다음</button>
        </div>
      </div>
    </div>`;
  },

  renderStock() {
    let stock = this.currentType === 'raw' ? HACCP_DATA.currentStock.raw
              : this.currentType === 'sub' ? HACCP_DATA.currentStock.sub
              : HACCP_DATA.currentStock.finished;

    // 원본 데이터 보호를 위한 얕은 복사
    stock = [...stock];

    // 검색어 필터
    if (this.searchQuery) {
      const q = this.searchQuery.toLowerCase();
      stock = stock.filter(s =>
        (s.name && s.name.toLowerCase().includes(q)) ||
        (s.id   && s.id.toLowerCase().includes(q))   ||
        (s.lot  && s.lot.toLowerCase().includes(q))
      );
    }
    // 식품유형 필터 (완제품 전용)
    if (this.currentType === 'finished' && this.filterFoodType) {
      stock = stock.filter(s => s.foodType === this.filterFoodType);
    }

    // 정렬 적용
    if (this.stockSortField) {
      stock.sort((a, b) => {
        let val1, val2;
        if (this.stockSortField === 'name') {
          val1 = a.name || '';
          val2 = b.name || '';
          return this.stockSortOrder === 'asc' ? val1.localeCompare(val2) : val2.localeCompare(val1);
        } else if (this.stockSortField === 'stock') {
          // balance를 기준으로 하되 기저 단위로 치환해 비교
          const getBase = (bal, unit) => InventoryPage.convertQty(bal, unit, InventoryPage.getUnitGroup(unit) === 'weight' ? 'kg' : 'L');
          const base1 = getBase(a.balance, a.unit);
          const base2 = getBase(b.balance, b.unit);
          return this.stockSortOrder === 'asc' ? base1 - base2 : base2 - base1;
        }
        return 0;
      });
    }

    return `
    <!-- 요약 -->
    <div class="kpi-grid" style="margin-bottom:1rem;">
      <div class="kpi-card primary">
        <div class="kpi-value">${stock.length}</div>
        <div class="kpi-label">총 품목수</div>
      </div>
      <div class="kpi-card ${stock.filter(s => s.balance <= (s.minStock||0)*1.5).length > 0 ? 'warning' : 'success'}">
        <div class="kpi-value">${stock.filter(s => s.balance <= (s.minStock||0)*1.5).length}</div>
        <div class="kpi-label">부족 품목</div>
      </div>
      ${this.currentType === 'raw' ? `
      <div class="kpi-card danger">
        <div class="kpi-value">${stock.filter(s => s.expiryAlert).length}</div>
        <div class="kpi-label">소비기한 임박</div>
      </div>` : this.currentType === 'finished' ? `
      <div class="kpi-card info">
        <div class="kpi-value">${stock.reduce((s,f) => s+f.balance, 0).toLocaleString()}</div>
        <div class="kpi-label">총 재고(개)</div>
      </div>` : ''}
    </div>

    <div class="card" style="padding:0;">
      <div class="table-wrapper">
        <table class="data-table">
          <thead style="position: sticky; top: 0; z-index: 10; background: var(--bg-surface); box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
            <tr>
              <th>품목코드</th>
              <th style="cursor:pointer;" onclick="InventoryPage.toggleSortStock('name')">
                품목명 / 규격
                ${this.stockSortField==='name' ? (this.stockSortOrder==='asc' ? '↑':'↓') : ''}
              </th>
              ${this.currentType === 'finished' ? '<th>식품유형</th>' : ''}
              <th colspan="2" style="cursor:pointer;" onclick="InventoryPage.toggleSortStock('stock')">
                현재고 ${this.stockSortField==='stock' ? (this.stockSortOrder==='asc' ? '↑':'↓') : ''}
                <div style="margin-top:2px;">
                  <select onchange="InventoryPage.bulkConvertStockUnit(this.value); event.stopPropagation();" onclick="event.stopPropagation();" style="font-size:0.7rem; padding:2px 4px; border-radius:4px; border:1px solid #ccc; background:#fff; color:#333; cursor:pointer;">
                    <option value="">일괄 단위 변경</option>
                    <option value="kg">kg (일괄)</option>
                    <option value="g">g (일괄)</option>
                    <option value="mg">mg (일괄)</option>
                    <option value="L">L (일괄)</option>
                    <option value="mL">mL (일괄)</option>
                  </select>
                </div>
              </th>
              ${this.currentType !== 'finished' ? '<th>최소재고</th><th>재고상태</th>' : '<th>LOT</th><th>유통기한</th>'}
              ${this.currentType === 'raw' ? '<th>소비기한 임박</th>' : ''}
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            ${stock.map(s => {
              const isLow = s.minStock && s.balance <= s.minStock * 1.5;
              const isCritical = s.minStock && s.balance <= s.minStock;
              const statusClass = isCritical ? 'badge-danger' : isLow ? 'badge-warning' : 'badge-success';
              const statusText = isCritical ? '부족' : isLow ? '주의' : '정상';
              // 마스터에서 spec 조회
              const masterList = this.currentType === 'raw' ? HACCP_DATA.rawMaterials
                               : this.currentType === 'sub' ? HACCP_DATA.subMaterials : [];
              const master = masterList.find(m => m.id === s.id);
              const spec = master?.spec || '';
              const FOOD_TYPES_S = ['기타가공품','고형차','추출가공식품','액상차','캔디류','일반식품'];
              const ftColorS = {'기타가공품':'#6366f1','고형차':'#10b981','추출가공식품':'#f59e0b','액상차':'#3b82f6','캔디류':'#ec4899','일반식품':'#8b5cf6'};
              return `
             <tr>
                <td><code style="color:var(--text-muted);font-size:0.75rem;cursor:pointer;" onclick="InventoryPage.viewItemHistory('${s.name}')">${s.id}</code></td>
                <td>
                  <span style="font-weight:700;color:var(--brand-primary);cursor:pointer;text-decoration:underline;" onclick="InventoryPage.viewItemHistory('${s.name}')">${s.name}</span>
                  ${spec ? `<div style="font-size:0.65rem;color:var(--text-muted);margin-top:0.1rem;">${spec}</div>` : ''}
                </td>
                ${this.currentType === 'finished' ? `<td>
                  <select class="excel-input" style="width:100px;" onchange="InventoryPage.updateStockFoodType('${s.id}',this.value)">
                    <option value="">-- 선택 --</option>
                    ${FOOD_TYPES_S.map(ft=>`<option value="${ft}" ${s.foodType===ft?'selected':''}>${ft}</option>`).join('')}
                  </select>
                  ${s.foodType ? `<div style="margin-top:2px;"><span style="font-size:.7rem;background:${ftColorS[s.foodType]||'#888'}22;color:${ftColorS[s.foodType]||'#888'};padding:1px 6px;border-radius:4px;">${s.foodType}</span></div>` : ''}
                </td>` : ''}
                <td colspan="2">
                  ${UnitConverter.renderStockCell(s.balance, s.unit, s.minStock)}
                </td>
                ${this.currentType !== 'finished' ? `
                  <td>${UnitConverter.renderToggleBadge(s.minStock || 0, s.unit, s.id+'-min')}</td>
                  <td><span class="badge ${statusClass} badge-dot">${statusText}</span></td>
                ` : `
                  <td><code style="font-size:0.75rem;color:var(--brand-primary);">${s.lot || '-'}</code></td>
                  <td>${s.expiryDate || '-'}</td>
                `}
                ${this.currentType === 'raw' ? `<td>${s.expiryAlert ? `<span class="badge badge-warning">⚠ ${s.expiryAlert}</span>` : '-'}</td>` : ''}
                <td>
                  <div class="d-flex gap-1">
                    <button class="btn btn-secondary btn-sm" onclick="InventoryPage.openModal('${s.id}','in')">입고</button>
                    <button class="btn btn-secondary btn-sm" onclick="InventoryPage.openModal('${s.id}','out')">출고</button>
                  </div>
                </td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
  },

  toggleSortStock(field) {
    if (this.stockSortField === field) {
      this.stockSortOrder = this.stockSortOrder === 'asc' ? 'desc' : 'asc';
    } else {
      this.stockSortField = field;
      this.stockSortOrder = 'asc';
    }
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  bulkConvertStockUnit(targetUnit) {
    if (!targetUnit) return;
    const stocks = this.currentType === 'raw' ? HACCP_DATA.currentStock.raw
                 : this.currentType === 'sub' ? HACCP_DATA.currentStock.sub
                 : HACCP_DATA.currentStock.finished;
                 
    const targetGroup = this.getUnitGroup(targetUnit);

    let count = 0;
    stocks.forEach(s => {
      if (s.unit && this.getUnitGroup(s.unit) === targetGroup && s.unit !== targetUnit) {
        s.balance = this.convertQty(s.balance, s.unit, targetUnit);
        s.unit = targetUnit;
        count++;
      }
    });

    document.getElementById('invContent').innerHTML = this.renderContent();
    if (count > 0) {
      App.showToast('success', '일괄 변환', `총 ${count}개 품목의 단위가 ${targetUnit}로 변환되었습니다.`);
    }
  },

  switchTab(tab) {
    this.currentTab = tab;
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  // ─────────────────────────────────────────────
  // 인라인 수량 편집 셀 렌더
  // ─────────────────────────────────────────────
  renderQtyCell(recordId, field, value, unit) {
    const typeClass = field === 'in' ? 'type-in' : field === 'out' ? 'type-out' : '';
    const canConvert = UnitConverter.canConvert(unit);
    const nextUnit   = UnitConverter.nextUnit(unit);
    const displayVal = UnitConverter.format(value, unit);

    return `<div class="qty-cell" id="qtyCell-${recordId}-${field}">
      <span class="qty-display ${typeClass}" onclick="InventoryPage.startEditQty('${recordId}','${field}','${value}','${unit}')" title="클릭하여 수정">${displayVal}</span>
      ${ canConvert ? `<button class="unit-btn" data-rid="${recordId}" data-field="${field}" data-val="${value}" data-unit="${unit}" data-next="${nextUnit}" onclick="InventoryPage.cycleUnit(this)" title="${unit}↔${nextUnit}">${unit}</button>` : `<span class="unit-label-fixed">${unit}</span>` }
    </div>`;
  },

  // 수량 셀 → input으로 전환
  startEditQty(recordId, field, currentVal, unit) {
    const cell = document.getElementById(`qtyCell-${recordId}-${field}`);
    if (!cell) return;
    const canConvert = UnitConverter.canConvert(unit);
    const nextUnit   = UnitConverter.nextUnit(unit);
    cell.innerHTML = `
      <input type="number" class="qty-input" id="qtyInput-${recordId}-${field}"
        value="${currentVal}" step="any" min="0"
        onkeydown="InventoryPage.qtyKeydown(event,'${recordId}','${field}','${unit}')"
        onblur="InventoryPage.saveQtyFromCell('${recordId}','${field}','${unit}')"
        style="width:80px;"
      />
      ${ canConvert ? `<button class="unit-btn" data-rid="${recordId}" data-field="${field}" data-val="${currentVal}" data-unit="${unit}" data-next="${nextUnit}" onclick="InventoryPage.cycleUnitInput(this)" title="${unit}↔${nextUnit}">${unit}</button>` : `<span class="unit-label-fixed">${unit}</span>` }
    `;
    const inp = document.getElementById(`qtyInput-${recordId}-${field}`);
    if (inp) { inp.focus(); inp.select(); }
  },

  // Enter → 저장, Escape → 취소
  qtyKeydown(e, recordId, field, unit) {
    if (e.key === 'Enter')  { e.preventDefault(); this.saveQtyFromCell(recordId, field, unit); }
    if (e.key === 'Escape') { document.getElementById('invContent').innerHTML = this.renderContent(); }
  },

  // blur/enter 시 값 저장
  saveQtyFromCell(recordId, field, unit) {
    const inp = document.getElementById(`qtyInput-${recordId}-${field}`);
    if (!inp) return;
    const newVal = parseFloat(inp.value);
    if (isNaN(newVal) || newVal < 0) {
      document.getElementById('invContent').innerHTML = this.renderContent();
      return;
    }
    const ledger = this.currentType === 'raw'      ? HACCP_DATA.rawLedger
                 : this.currentType === 'sub'      ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;
    const record = ledger.find(r => r.id === recordId);
    if (!record) return;

    if (field === 'bal') {
      record.balance = newVal;
    } else {
      // qty 변경 → stock 재고도 반영
      const stocks   = this.currentType === 'raw' ? HACCP_DATA.currentStock.raw
                     : this.currentType === 'sub' ? HACCP_DATA.currentStock.sub
                     : HACCP_DATA.currentStock.finished;
      const stockItem = stocks.find(s => s.name === record.name);
      const oldQty = record.qty;
      if (stockItem) {
        if (record.type === 'in') {
          stockItem.balance = stockItem.balance - oldQty + newVal;
        } else {
          stockItem.balance = stockItem.balance + oldQty - newVal;
        }
        record.balance = stockItem.balance;
      }
      record.qty  = newVal;
      record.unit = unit;   // 현재 표시 단위를 저장
    }

    // 셀을 다시 표시 모드로 복원
    const cell = document.getElementById(`qtyCell-${recordId}-${field}`);
    if (cell) cell.outerHTML = this.renderQtyCell(recordId, field, newVal, unit)
                                   .replace('id="qty', 'id="qty');
    document.getElementById('invContent').innerHTML = this.renderContent();
    App.showToast('success', '수정 완료', `${newVal.toLocaleString()} ${unit} 저장됨`);
  },

  // 단위 토글 (표시 중) — 값도 변환
  cycleUnit(btn) {
    const recordId = btn.dataset.rid;
    const field    = btn.dataset.field;
    const unit     = btn.dataset.unit;
    const nextUnit = btn.dataset.next;
    const val      = parseFloat(btn.dataset.val);

    const converted = UnitConverter.convert(val, unit, nextUnit);

    // 저장
    const ledger = this.currentType === 'raw' ? HACCP_DATA.rawLedger
                 : this.currentType === 'sub' ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;
    const record = ledger.find(r => r.id === recordId);
    if (record) {
      if (field === 'bal') { record.balance = converted; }
      else                 { record.qty = converted; }
      record.unit = nextUnit;
    }
    document.getElementById('invContent').innerHTML = this.renderContent();
    App.showToast('info', '단위 변환', `${UnitConverter.format(val, unit)} ${unit} → ${UnitConverter.format(converted, nextUnit)} ${nextUnit}`);
  },

  // 현재고 식품유형 직접 수정
  updateStockFoodType(id, foodType) {
    const item = HACCP_DATA.currentStock.finished.find(s => s.id === id);
    if (item) {
      item.foodType = foodType;
      HACCP_DATA.finishedLedger.filter(r => r.productId === id).forEach(r => r.foodType = foodType);
    }
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  // 단위 토글 (편집 중) — input 값도 변환

  cycleUnitInput(btn) {
    const inp = btn.closest('.qty-cell')?.querySelector('.qty-input');
    const unit     = btn.dataset.unit;
    const nextUnit = btn.dataset.next;
    const val      = parseFloat(inp?.value || btn.dataset.val);
    const converted = UnitConverter.convert(val, unit, nextUnit);

    btn.dataset.unit = nextUnit;
    btn.dataset.next = UnitConverter.nextUnit(nextUnit);
    btn.dataset.val  = converted;
    btn.textContent  = nextUnit;
    if (inp) { inp.value = converted; inp.focus(); }
  },

  onSearch(q) {
    this.searchQuery = q;
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  onFilter(type) {
    this.filterType = type;
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  onFilterFoodType(ft) {
    this.filterFoodType = ft;
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  onDateChange(which, val) {
    if (which === 'from') this.dateFrom = val;
    else this.dateTo = val;
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  setDateRange(range) {
    const today = new Date('2026-03-20'); // 현재 시스템 날짜
    const fmt = d => d.toISOString().split('T')[0];
    if (range === 'all') {
      this.dateFrom = ''; this.dateTo = '';
    } else if (range === 'year') {
      this.dateFrom = `${today.getFullYear()}-01-01`;
      this.dateTo   = `${today.getFullYear()}-12-31`;
    } else if (range === '6month') {
      const from = new Date(today);
      from.setMonth(from.getMonth() - 6);
      this.dateFrom = fmt(from); this.dateTo = fmt(today);
    } else if (range === 'month') {
      this.dateFrom = fmt(new Date(today.getFullYear(), today.getMonth(), 1));
      this.dateTo   = fmt(new Date(today.getFullYear(), today.getMonth() + 1, 0));
    }
    // 화면 전체 다시렌더링 (버튼 하이라이트 업데이트)
    document.getElementById('pageContainer').innerHTML = this.render(this.currentType);
    this.switchTab(this.currentTab);
  },

  // 수량+단위 입력 시 자동 변환 제안문 표시
  onQtyUnitChange() {
    const qty = parseFloat(document.getElementById('invQty')?.value);
    const unit = document.getElementById('invQtyUnit')?.value;
    const el = document.getElementById('invQtyConvert');
    if (!el) return;
    if (!qty || !unit) { el.innerHTML = ''; return; }
    const alts = this.getAltUnits(unit).filter(u => u !== unit);
    if (alts.length === 0) { el.innerHTML = ''; return; }
    const conversions = alts.map(u => `<strong>${this.convertQty(qty, unit, u).toLocaleString()}&nbsp;${u}</strong>`).join(' &nbsp;/&nbsp; ');
    el.innerHTML = `⇒ ${conversions}`;
  },

  // 현재고 테이블에서 단위 드롭다운 변경 시 해당 원소 값 실시간 변환 표시
  changeStockDisplayUnit(itemId, toUnit, origBalance, origUnit) {
    const converted = this.convertQty(origBalance, origUnit, toUnit);
    // 가장 가까운 <td>의 <span>을 찾아 업데이트
    const row = event.target.closest('tr');
    if (!row) return;
    const span = row.querySelector('td:nth-child(3) span');
    if (span) {
      span.textContent = converted.toLocaleString();
      // tooltip 업데이트
      const alts = this.getAltUnits(toUnit).filter(u => u !== toUnit);
      span.title = alts.map(u => `${this.convertQty(converted, toUnit, u).toLocaleString()} ${u}`).join(' / ');
    }
  },

  openModal(itemId = null, transType = 'in') {
    const type = this.currentType;
    const items = type === 'raw' ? HACCP_DATA.rawMaterials
                : type === 'sub' ? HACCP_DATA.subMaterials
                : HACCP_DATA.currentStock.finished;
    const selectedItem = itemId ? items.find(i => i.id === itemId) : null;

    App.showModal(
      `${type === 'finished' ? '완제품 ' : ''}${transType === 'in' ? '입고' : '출고/사용'} 등록`,
      `<form id="invForm" onsubmit="InventoryPage.submitForm(event)">
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">날짜 *</label>
            <input type="date" class="form-control" id="invDate" value="${new Date().toISOString().split('T')[0]}" required />
          </div>
          <div class="form-group">
            <label class="form-label">구분 *</label>
            <select class="form-control" id="invType" required>
              <option value="in" ${transType === 'in' ? 'selected' : ''}>입고</option>
              <option value="out" ${transType === 'out' ? 'selected' : ''}>출고/사용</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">품목 선택 * <span style="font-size:0.7rem;color:var(--brand-primary);font-weight:normal;">(검색하여 빠르게 찾기)</span></label>
          <div class="search-input-wrap flex-1" style="margin-bottom:0.5rem;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input type="text" class="form-control" placeholder="품목명, 코드 검색..." oninput="InventoryPage.filterItems(this.value)" autocomplete="off" />
          </div>
          <select class="form-control" id="invItem" size="4" style="height:auto;" required>
            <option value="" disabled>-- 검색 후 아래에서 선택하세요 --</option>
            ${items.map(i => `<option value="${i.id}" ${selectedItem?.id === i.id ? 'selected' : ''}>[${i.id}] ${i.name}${i.spec ? ' ('+i.spec+')' : ''}</option>`).join('')}
          </select>
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">수량 *</label>
            <div class="d-flex gap-1" style="align-items:center;">
              <input type="number" class="form-control" id="invQty" placeholder="수량 입력" min="0.01" step="0.01" required oninput="InventoryPage.onQtyUnitChange()" />
              <select class="form-control" id="invQtyUnit" style="width:80px;flex-shrink:0;" onchange="InventoryPage.onQtyUnitChange()">
                <option value="kg">kg</option>
                <option value="g">g</option>
                <option value="mg">mg</option>
                <option value="L">L</option>
                <option value="mL">mL</option>
                <option value="개">개</option>
                <option value="장">장</option>
                <option value="보">보</option>
              </select>
            </div>
            <div id="invQtyConvert" style="font-size:0.75rem;color:var(--brand-primary);margin-top:0.3rem;min-height:1rem;"></div>
          </div>
          <div class="form-group">
            <label class="form-label">LOT 번호</label>
            <input type="text" class="form-control" id="invLot" placeholder="LOT 번호 입력" />
          </div>
        </div>
        ${type !== 'finished' ? `
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">소비기한</label>
            <input type="date" class="form-control" id="invExpiry" />
          </div>
          <div class="form-group">
            <label class="form-label">공급업체</label>
            <input type="text" class="form-control" id="invSupplier" placeholder="공급업체명" />
          </div>
        </div>` : `
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">유통기한</label>
            <input type="date" class="form-control" id="invExpiry" />
          </div>
          <div class="form-group">
            <label class="form-label">거래처</label>
            <input type="text" class="form-control" id="invCustomer" placeholder="거래처명" />
          </div>
        </div>`}
        <div class="form-group">
          <label class="form-label">담당자 *</label>
          <select class="form-control" id="invInspector" required>
            <option value="">-- 선택 --</option>
            ${HACCP_DATA.employees.map(e => `<option value="${e.name}">${e.name} (${e.dept})</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">비고</label>
          <input type="text" class="form-control" id="invNote" placeholder="특이사항 입력" />
        </div>
      </form>`,
      [
        { text: '취소', class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '등록', class: 'btn-primary', action: 'InventoryPage.submitForm(event)' }
      ]
    );
  },

  filterItems(query) {
    const q = query.toLowerCase();
    const select = document.getElementById('invItem');
    if (!select) return;

    const type = this.currentType;
    const items = type === 'raw' ? HACCP_DATA.rawMaterials
                : type === 'sub' ? HACCP_DATA.subMaterials
                : HACCP_DATA.currentStock.finished;
    
    const currentVal = select.value;
    const qClean = q.replace(/\s+/g, '');
    const filtered = items.filter(i => {
      return String(i.name).toLowerCase().replace(/\s+/g, '').includes(qClean) ||
             String(i.id).toLowerCase().replace(/\s+/g, '').includes(qClean) ||
             (i.spec && String(i.spec).toLowerCase().replace(/\s+/g, '').includes(qClean));
    });
    
    select.innerHTML = '<option value="" disabled>-- 검색 후 아래에서 선택하세요 --</option>' + 
      filtered.map(i => `<option value="${i.id}">[${i.id}] ${i.name}${i.spec ? ' ('+i.spec+')' : ''}</option>`).join('');
      
    if (filtered.find(i => i.id === currentVal)) select.value = currentVal;
  },

  submitForm(e) {
    if (e) e.preventDefault();
    
    const type = this.currentType;
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger : type === 'sub' ? HACCP_DATA.subLedger : HACCP_DATA.finishedLedger;
    const stocks = type === 'raw' ? HACCP_DATA.currentStock.raw : type === 'sub' ? HACCP_DATA.currentStock.sub : HACCP_DATA.currentStock.finished;
    
    const date = document.getElementById('invDate').value;
    const transType = document.getElementById('invType').value;
    const itemId = document.getElementById('invItem').value;
    const qty = parseFloat(document.getElementById('invQty').value);
    const unit = document.getElementById('invQtyUnit').value;
    const lot = document.getElementById('invLot').value;
    const inspector = document.getElementById('invInspector').value;
    
    if (!itemId || isNaN(qty) || qty <= 0 || !inspector) {
      App.showToast('error', '입력 오류', '필수 항목을 모두 입력해주세요.');
      return;
    }

    const item = stocks.find(s => s.id === itemId);
    if (!item) return;

    // 단위 변환: 사용자가 입력한 단위를 기초 단위로 변환하여 balance에 반영
    const qtyInBase = this.convertQty(qty, unit, item.unit);
    
    if (transType === 'in') item.balance += qtyInBase;
    else item.balance -= qtyInBase;

    const newRecord = {
      id: 'L' + Date.now(),
      date,
      rmId: type === 'raw' ? itemId : undefined,
      smId: type === 'sub' ? itemId : undefined,
      productId: type === 'finished' ? itemId : undefined,
      name: item.name,
      type: transType,
      qty,
      unit, // 사용자가 입력한 시점의 단위 저장
      balance: item.balance,
      expiryDate: document.getElementById('invExpiry')?.value || '',
      lot,
      supplier: type !== 'finished' ? (document.getElementById('invSupplier')?.value || '') : '',
      customer: type === 'finished' ? (document.getElementById('invCustomer')?.value || '') : '',
      inspector,
      note: document.getElementById('invNote').value
    };

    ledger.unshift(newRecord);
    
    App.showToast('success', '등록 완료', `[${item.name}] 내역이 장부에 기록되었습니다.`);
    App.closeModal();
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  viewDetail(id) {
    const type = this.currentType;
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger
                 : type === 'sub' ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;
    const record = ledger.find(r => r.id === id);
    if (!record) {
      App.showToast('error', '오류', '해당 내역을 찾을 수 없습니다.');
      return;
    }

    App.showModal(
      `수불 내역 수정 - ${record.name}`,
      `<form id="invEditForm" onsubmit="InventoryPage.submitEditForm(event, '${id}')">
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">날짜</label>
            <input type="date" class="form-control" id="editDate" value="${record.date}" required />
          </div>
          <div class="form-group">
            <label class="form-label">구분 (입출고)</label>
            <select class="form-control" id="editType" required>
              <option value="in" ${record.type === 'in' ? 'selected' : ''}>입고</option>
              <option value="out" ${record.type === 'out' ? 'selected' : ''}>출고/사용</option>
            </select>
          </div>
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">수량</label>
            <input type="number" class="form-control" id="editQty" value="${record.qty}" min="0.01" step="0.01" required />
          </div>
          <div class="form-group">
            <label class="form-label">LOT 번호</label>
            <input type="text" class="form-control" id="editLot" value="${record.lot || ''}" />
          </div>
        </div>
        ${type !== 'finished' ? `
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">소비기한</label>
            <input type="date" class="form-control" id="editExpiry" value="${record.expiryDate || ''}" />
          </div>
          <div class="form-group">
            <label class="form-label">공급업체</label>
            <input type="text" class="form-control" id="editSupplier" value="${record.supplier || ''}" />
          </div>
        </div>` : `
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">유통기한</label>
            <input type="date" class="form-control" id="editExpiry" value="${record.expiryDate || ''}" />
          </div>
          <div class="form-group">
            <label class="form-label">거래처</label>
            <input type="text" class="form-control" id="editCustomer" value="${record.customer || ''}" />
          </div>
        </div>`}
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">담당자</label>
            <input type="text" class="form-control" id="editInspector" value="${record.inspector || ''}" required />
          </div>
          <div class="form-group">
            <label class="form-label">비고</label>
            <input type="text" class="form-control" id="editNote" value="${record.note || ''}" />
          </div>
        </div>
      </form>`,
      [
        { text: '닫기', class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '수정 저장', class: 'btn-primary', action: `InventoryPage.submitEditForm(event, '${id}')` }
      ]
    );
  },

  updateField(id, field, value) {
    const type = this.currentType;
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger
                 : type === 'sub' ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;
    const record = ledger.find(r => r.id === id);
    if (!record) return;

    if (field === 'qty') record[field] = parseFloat(value) || 0;
    else record[field] = value;

    // TODO: (고도화용) 수량이 변경되면 이후 내역들의 잔고(balance)를 다시 계산하는 로직이 필요할 수 있습니다.
    App.showToast('success', '저장됨', '엑셀처럼 값이 즉시 수정되었습니다.', 1500);
  },

  updateQtyField(id, newType, valueStr) {
    const val = parseFloat(valueStr);
    if (!isNaN(val) && val > 0) {
      // 값 입력 시, 해당 타입으로 자동 덮어쓰기 및 값 반영
      const type = this.currentType;
      const ledger = type === 'raw' ? HACCP_DATA.rawLedger : type === 'sub' ? HACCP_DATA.subLedger : HACCP_DATA.finishedLedger;
      const record = ledger.find(r => r.id === id);
      if (record) {
        record.type = newType;
        record.qty = val;
        // 다른 필드 인풋 초기화를 위해 다시 렌더링
        document.getElementById('invContent').innerHTML = this.renderContent();
        App.showToast('success', '수량/구분 반영', '입출고 수량이 정상 반영되었습니다.', 1500);
      }
    } else {
      this.updateField(id, 'qty', 0);
    }
  },

  submitEditForm(e, id) {
    if (e) e.preventDefault();
    const type = this.currentType;
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger : type === 'sub' ? HACCP_DATA.subLedger : HACCP_DATA.finishedLedger;
    const stocks = type === 'raw' ? HACCP_DATA.currentStock.raw : type === 'sub' ? HACCP_DATA.currentStock.sub : HACCP_DATA.currentStock.finished;
    
    const record = ledger.find(r => r.id === id);
    if (!record) return;

    const oldQtyInBase = this.convertQty(record.qty, record.unit || 'kg', 'kg'); // 단순화를 위해 우선 kg 기준 가정 (개선 필요시 item.unit 사용)
    const newDate = document.getElementById('editDate').value;
    const newType = document.getElementById('editType').value;
    const newQty = parseFloat(document.getElementById('editQty').value);
    
    // 재고 반영 (현재는 단순 가산 방식, 실무에서는 전체 balance 재계산 로직 권장)
    const item = stocks.find(s => s.name === record.name);
    if (item) {
       const newQtyInBase = this.convertQty(newQty, record.unit || item.unit, item.unit);
       // 이전 값 취소
       if (record.type === 'in') item.balance -= oldQtyInBase;
       else item.balance += oldQtyInBase;
       // 새 값 반영
       if (newType === 'in') item.balance += newQtyInBase;
       else item.balance -= newQtyInBase;
       
       record.balance = item.balance; // 단순 표시용
    }

    record.date = newDate;
    record.type = newType;
    record.qty = newQty;
    record.lot = document.getElementById('editLot').value;
    record.expiryDate = document.getElementById('editExpiry')?.value || '';
    if (type === 'finished') {
      record.customer = document.getElementById('editCustomer')?.value || '';
    } else {
      record.supplier = document.getElementById('editSupplier')?.value || '';
    }
    record.inspector = document.getElementById('editInspector').value;
    record.note = document.getElementById('editNote').value;

    document.getElementById('invContent').innerHTML = this.renderContent();
    App.showToast('success', '수정 완료', '수불 내역이 변경되고 현재고에 반영되었습니다.');
    App.closeModal();
  },

  exportExcel() {
    const type = this.currentType;
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger
                 : type === 'sub' ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;
                 
    let csv = '\uFEFF'; // UTF-8 BOM for Excel
    csv += '날짜,품목명,구분,수량,현재고,기한,LOT번호,업체,담당자,비고\n';
    
    ledger.forEach(r => {
      const gubun = r.type === 'in' ? '입고' : '출고';
      const company = (r.supplier || r.customer || '').replace(/,/g, ' ');
      const note = (r.note || '').replace(/,/g, ' ');
      csv += `${r.date},${r.name},${gubun},${r.qty},${r.balance},${r.expiryDate||''},${r.lot||''},${company},${r.inspector},${note}\n`;
    });
    
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `수불대장_${type}_${new Date().toISOString().slice(0,10)}.csv`;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    App.showToast('success', '엑셀 내보내기 완료', '수불대장 내용을 엑셀(CSV) 파일로 저장했습니다.');
  },

  viewItemHistory(itemName, targetUnit = null) {
    const type = this.currentType;
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger
                 : type === 'sub' ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;
                 
    // 품목의 모든 내역 필터링 및 시간순 정렬
    const filtered = ledger.filter(r => r.name === itemName).sort((a,b) => new Date(a.date) - new Date(b.date));
    
    // 기본 단위 찾기
    const stocks = type === 'raw' ? HACCP_DATA.currentStock.raw
                 : type === 'sub' ? HACCP_DATA.currentStock.sub
                 : HACCP_DATA.currentStock.finished;
    const stockItem = stocks.find(s => s.name === itemName);
    const baseUnit = filtered[0]?.unit || stockItem?.unit || 'kg';
    
    // 현재 표시 단위
    const displayUnit = targetUnit || baseUnit;
    
    // 변환 가능한 단위 목록 (kg, g 등)
    let altUnits = [];
    if (this.currentType === 'raw') {
        const haccpItem = HACCP_DATA.rawMaterials.find(rm => rm.name === itemName);
        altUnits = haccpItem?.unitAlts || [baseUnit];
    } else {
        altUnits = this.getAltUnits(baseUnit);
    }
    // 배열에 displayUnit 추가
    if (!altUnits.includes(displayUnit) && displayUnit) altUnits.push(displayUnit);

    const unitOptions = altUnits.map(u => `<option value="${u}" ${u === displayUnit ? 'selected' : ''}>${u}</option>`).join('');
    
    const unitSelectorHtml = altUnits.length > 1 ? 
      `<div style="display:flex; justify-content:flex-end; padding:4px 8px; align-items:center; gap:8px;">
         <span style="font-size:0.75rem; font-weight:bold; color:var(--text-muted);">표시 단위:</span>
         <select class="form-control" style="width:70px; padding: 2px 4px; font-size:0.75rem;" onchange="InventoryPage.viewItemHistory('${itemName.replace(/'/g,"\\'").replace(/"/g,'&quot;')}', this.value)">${unitOptions}</select>
       </div>` : '';

    const tableHTML = `
      ${unitSelectorHtml}
      <div style="max-height:55vh;overflow-y:auto;background:var(--bg-elevated);border-radius:4px;border:1px solid var(--border-subtle);margin-bottom:1rem;">
        <table class="data-table" style="font-size:0.75rem;margin:0;">
          <thead style="position:sticky;top:0;background:var(--bg-elevated);z-index:2;box-shadow:0 1px 2px rgba(0,0,0,0.05);">
            <tr>
              <th style="padding:0.5rem;">날짜</th>
              <th style="padding:0.5rem;text-align:right;">입고(${displayUnit})</th>
              <th style="padding:0.5rem;text-align:right;">출고(${displayUnit})</th>
              <th style="padding:0.5rem;text-align:right;">현재고(${displayUnit})</th>
              ${type !== 'finished' ? '<th style="padding:0.5rem;">기한(소비)</th><th style="padding:0.5rem;">공급업체</th>' : '<th style="padding:0.5rem;">기한(유통)</th><th style="padding:0.5rem;">거래처</th>'}
              <th style="padding:0.5rem;">LOT번호</th>
              <th style="padding:0.5rem;">담당자</th>
              <th style="padding:0.5rem;">비고</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.length === 0 ? '<tr><td colspan="9" style="text-align:center;padding:1.5rem;color:var(--text-muted);">조회된 내역이 없습니다.</td></tr>' : ''}
            ${filtered.map(r => {
                const rUnit = r.unit || baseUnit;
                const qtyVal = this.convertQty(r.qty, rUnit, displayUnit);
                const balVal = this.convertQty(r.balance, rUnit, displayUnit);
                return `
            <tr>
              <td class="no-wrap" style="padding:0.4rem 0.6rem;">${r.date}</td>
              <td style="padding:0.4rem 0.6rem;text-align:right;color:var(--color-success);font-weight:700;">${r.type === 'in' ? '+' + qtyVal.toLocaleString() : '-'}</td>
              <td style="padding:0.4rem 0.6rem;text-align:right;color:var(--color-danger);font-weight:700;">${r.type === 'out' ? '-' + qtyVal.toLocaleString() : '-'}</td>
              <td style="padding:0.4rem 0.6rem;text-align:right;font-weight:800;color:var(--text-primary);">${balVal.toLocaleString()}</td>
              <td style="padding:0.4rem 0.6rem;" class="no-wrap">${r.expiryDate||'-'}</td>
              <td style="padding:0.4rem 0.6rem;max-width:80px;overflow:hidden;text-overflow:ellipsis;" class="no-wrap" title="${type!=='finished'?r.supplier:r.customer}">${type!=='finished'?(r.supplier||'-'):(r.customer||'-')}</td>
              <td style="padding:0.4rem 0.6rem;"><code style="font-size:0.7rem;color:var(--brand-primary);">${r.lot||'-'}</code></td>
              <td style="padding:0.4rem 0.6rem;">${r.inspector}</td>
              <td style="padding:0.4rem 0.6rem;max-width:100px;overflow:hidden;text-overflow:ellipsis;" class="no-wrap" title="${r.note||''}">${r.note||'-'}</td>
            </tr>
            `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;

    App.showModal(
      `📦 [${itemName}] 상세 입/출고 이력`,
      tableHTML,
      [
        { text: '닫기', class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '🖨 인쇄', class: 'btn-secondary', action: `InventoryPage.printItemHistory('${itemName.replace(/'/g,"\\'")}', '${displayUnit}')` },
        { text: '수불 내역으로 이동', class: 'btn-primary', action: `InventoryPage.onSearch('${itemName.replace(/'/g,"\\'")}'); App.closeModal(); InventoryPage.switchTab('ledger');` }
      ]
    );
  },

  // =============================================
  // 인쇄 기능
  // =============================================
  printItemHistory(itemName, targetUnit = null) {
    const type   = this.currentType;
    const typeLbl = type === 'raw' ? '원료' : type === 'sub' ? '부자재' : '완제품';
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger
                 : type === 'sub' ? HACCP_DATA.subLedger
                 : HACCP_DATA.finishedLedger;

    const filtered = ledger
      .filter(r => r.name === itemName)
      .sort((a, b) => new Date(a.date) - new Date(b.date));

    // 현재고 조회
    const stocks = type === 'raw' ? HACCP_DATA.currentStock.raw
                 : type === 'sub' ? HACCP_DATA.currentStock.sub
                 : HACCP_DATA.currentStock.finished;
    const stockItem = stocks.find(s => s.name === itemName);
    const baseUnit  = filtered[0]?.unit || stockItem?.unit || 'kg';
    const unit      = targetUnit || baseUnit;

    const company   = HACCP_DATA.company || { name: 'BIODOT(주)', address: '', tel: '' };
    const printDate = new Date().toLocaleDateString('ko-KR', { year:'numeric', month:'2-digit', day:'2-digit' });
    const dateRange = filtered.length
      ? `${filtered[0].date} ~ ${filtered[filtered.length-1].date}`
      : '내역 없음';

    // 행 카운터용 누계
    let runIn = 0, runOut = 0;
    const rows = filtered.map((r, i) => {
      const rUnit = r.unit || baseUnit;
      const qtyVal = this.convertQty(r.qty, rUnit, unit);
      const balVal = this.convertQty(r.balance, rUnit, unit);
      
      const isIn  = r.type === 'in';
      if (isIn) runIn  += qtyVal; else runOut += qtyVal;
      
      const qty   = qtyVal.toLocaleString();
      const bal   = balVal.toLocaleString();
      const inOut = isIn
        ? `<td class="num green">+${qty} ${unit}</td><td class="num">-</td>`
        : `<td class="num">-</td><td class="num red">-${qty} ${unit}</td>`;
      const comp  = type !== 'finished' ? (r.supplier || '-') : (r.customer || '-');
      const expLbl = type !== 'finished' ? '소비기한' : '유통기한';
      return `
        <tr class="${i % 2 === 1 ? 'alt' : ''}">
          <td class="center">${i + 1}</td>
          <td class="center">${r.date}</td>
          <td class="center">${isIn ? '입 고' : '출 고'}</td>
          ${inOut}
          <td class="num bold">${bal} ${unit}</td>
          <td class="center">${r.lot || '-'}</td>
          <td class="center">${r.expiryDate || '-'}</td>
          <td class="center">${comp}</td>
          <td class="center">${r.inspector}</td>
          <td>${r.note || ''}</td>
        </tr>`;
    }).join('');

    const finalBal = stockItem ? this.convertQty(stockItem.balance, stockItem.unit, unit) : (runIn - runOut);

    const html = `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<title>${typeLbl} 수불대장 - ${itemName}</title>
<style>
  @page { size: A4 landscape; margin: 15mm 12mm; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Malgun Gothic', '맑은 고딕', sans-serif; font-size: 9pt; color: #111; background: #fff; }

  /* 헤더 */
  .print-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6mm; }
  .company-info h1 { font-size: 11pt; font-weight: 700; margin-bottom: 2px; }
  .company-info p  { font-size: 8pt; color: #555; line-height: 1.5; }
  .doc-title { text-align: center; flex: 1; }
  .doc-title h2 { font-size: 16pt; font-weight: 900; letter-spacing: 0.06em; border-bottom: 2.5px solid #000; padding-bottom: 3px; display: inline-block; }
  .doc-title p  { font-size: 8.5pt; color: #444; margin-top: 3px; }
  .approval-box { display: flex; border: 1px solid #bbb; font-size: 8pt; }
  .approval-col { text-align: center; width: 42px; }
  .approval-col .ttl { background: #f0f0f0; padding: 2px 4px; border-bottom: 1px solid #bbb; font-weight: 600; }
  .approval-col .sig { height: 28px; border-right: 1px solid #bbb; display: flex; align-items: center; justify-content: center; }
  .approval-col:last-child .sig { border-right: none; }

  /* 품목 정보 */
  .item-info { display: flex; gap: 4mm; margin-bottom: 4mm; font-size: 8.5pt; }
  .item-info .cell { border: 1px solid #aaa; padding: 2px 6px; border-radius: 2px; }
  .item-info .cell strong { color: #1a1a1a; }
  .item-info .cell span  { color: #555; margin-right: 4px; }

  /* 테이블 */
  table { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
  thead th {
    background: #1e293b;
    color: #fff;
    padding: 4px 3px;
    text-align: center;
    border: 1px solid #1e293b;
    font-weight: 600;
    font-size: 8pt;
    white-space: nowrap;
  }
  tbody td {
    padding: 3px 4px;
    border: 1px solid #ccc;
    vertical-align: middle;
  }
  tbody tr.alt td { background: #f9fafb; }
  tbody tr:hover td { background: #eef9f6; }

  /* 정렬 */
  .center { text-align: center; }
  .num    { text-align: right; font-weight: 600; font-family: 'Courier New', monospace; }
  .bold   { font-weight: 800; }
  .green  { color: #15803d; }
  .red    { color: #b91c1c; }

  /* 합계행 */
  .total-row td {
    background: #f0f6ff;
    font-weight: 800;
    border-top: 2px solid #1e293b;
  }

  /* 푸터 */
  .print-footer { margin-top: 6mm; display: flex; justify-content: space-between; align-items: flex-end; }
  .sign-table { border-collapse: collapse; font-size: 8pt; }
  .sign-table td { border: 1px solid #aaa; padding: 2px 8px; text-align: center; }
  .sign-table .ttl { background: #f0f0f0; font-weight: 600; }
  .sign-table .sig { height: 20mm; width: 30mm; vertical-align: top; padding-top: 3px; }
  .footnote { font-size: 7.5pt; color: #888; line-height: 1.6; }

  @media print {
    .no-print { display: none !important; }
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
</head>
<body>

<!-- 인쇄 버튼 (화면 전용) -->
<div class="no-print" style="text-align:right;margin-bottom:8mm;">
  <button onclick="window.print()" style="padding:6px 18px;background:#0ea5e9;color:#fff;border:none;border-radius:4px;font-size:10pt;cursor:pointer;font-weight:700;">🖨 인쇄</button>
  <button onclick="window.close()" style="padding:6px 14px;background:#e2e8f0;border:none;border-radius:4px;font-size:10pt;cursor:pointer;margin-left:6px;">✕ 닫기</button>
</div>

<!-- 헤더 -->
<div class="print-header">
  <div class="company-info">
    <h1>${company.name || 'BIODOT(주)'}</h1>
    <p>
      ${company.address || ''}<br>
      Tel: ${company.tel || '-'} &nbsp;|&nbsp; 사업자: ${company.businessNo || ''}<br>
      HACCP 인증번호: ${company.haccpNo || ''}
    </p>
  </div>
  <div class="doc-title">
    <h2>${typeLbl} 수 불 대 장</h2>
    <p>조회기간: ${dateRange} &nbsp;|&nbsp; 출력일: ${printDate}</p>
  </div>
  <div class="approval-box">
    <div class="approval-col"><div class="ttl">담당</div><div class="sig"></div></div>
    <div class="approval-col"><div class="ttl">팀장</div><div class="sig"></div></div>
    <div class="approval-col"><div class="ttl">대표</div><div class="sig"></div></div>
  </div>
</div>

<!-- 품목 정보 -->
<div class="item-info">
  <div class="cell"><span>품목명</span><strong>${itemName}</strong></div>
  <div class="cell"><span>단위</span><strong>${unit}</strong></div>
  <div class="cell"><span>현재고</span><strong>${finalBal.toLocaleString()} ${unit}</strong></div>
  <div class="cell"><span>총 건수</span><strong>${filtered.length} 건</strong></div>
  <div class="cell"><span>총 입고</span><strong style="color:#15803d">+${runIn.toLocaleString()} ${unit}</strong></div>
  <div class="cell"><span>총 출고</span><strong style="color:#b91c1c">-${runOut.toLocaleString()} ${unit}</strong></div>
</div>

<!-- 수불 테이블 -->
<table>
  <thead>
    <tr>
      <th style="width:28px">No</th>
      <th style="width:72px">날짜</th>
      <th style="width:44px">구분</th>
      <th style="width:80px">입고(+) [${unit}]</th>
      <th style="width:80px">출고(-) [${unit}]</th>
      <th style="width:80px">현재고 [${unit}]</th>
      <th style="width:80px">LOT 번호</th>
      <th style="width:68px">${type !== 'finished' ? '소비기한' : '유통기한'}</th>
      <th style="width:70px">${type !== 'finished' ? '공급업체' : '거래처'}</th>
      <th style="width:50px">담당자</th>
      <th>비고</th>
    </tr>
  </thead>
  <tbody>
    ${rows || '<tr><td colspan="11" style="text-align:center;padding:8px;color:#999;">내역이 없습니다.</td></tr>'}
    <tr class="total-row">
      <td colspan="3" class="center">합 계</td>
      <td class="num green">+${runIn.toLocaleString()} ${unit}</td>
      <td class="num red">-${runOut.toLocaleString()} ${unit}</td>
      <td class="num bold">${finalBal.toLocaleString()} ${unit}</td>
      <td colspan="5"></td>
    </tr>
  </tbody>
</table>

<!-- 푸터 -->
<div class="print-footer">
  <div class="footnote">
    ※ 본 수불대장은 BIODOT HACCP 시스템에서 자동 생성된 문서입니다.<br>
    ※ 출력일시: ${printDate} &nbsp;|&nbsp; K-HACCP 관련 규정에 따라 보관하시기 바랍니다.
  </div>

</div>

</body>
</html>`;

    const win = window.open('', '_blank', 'width=1100,height=780,scrollbars=yes');
    if (!win) { App.showToast('error', '팝업 차단', '팝업을 허용해 주세요.'); return; }
    win.document.open();
    win.document.write(html);
    win.document.close();
    // 렌더링 후 자동 인쇄 대화상자 열기
    win.onload = () => win.print();
  },

  // =============================================
  // 신규 품목 등록 로직 (수불대장 및 타 모듈 공용)
  // =============================================
  openNewItemModal(targetType = null, callback = null) {
    const type = targetType || this.currentType;
    const typeNm = type === 'raw' ? '원료' : type === 'sub' ? '부자재' : '완제품';
    
    // Store callback if provided
    this._newItemCallback = callback;
    this._newItemType = type;

    App.showModal(
      `📦 신규 ${typeNm} 품목 등록`,
      `<form id="newItemForm" onsubmit="InventoryPage.submitNewItem(event)">
        <div class="form-group">
          <label class="form-label">${typeNm} 코드 (선택/자동부여)</label>
          <input type="text" class="form-control" id="niCode" placeholder="미입력시 자동 생성 (예: ${type==='raw'?'RM':type==='sub'?'SM':'FP'}001)" />
        </div>
        <div class="form-group">
          <label class="form-label">${typeNm}명 (필수)</label>
          <input type="text" class="form-control" id="niName" placeholder="품목명 입력" required />
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">단위 (필수)</label>
            <input type="text" class="form-control" id="niUnit" placeholder="예: kg, g, 장, 개" required />
          </div>
          ${type !== 'finished' ? `
          <div class="form-group">
            <label class="form-label">최소 적정 재고</label>
            <input type="number" class="form-control" id="niMinStock" placeholder="경고 기준 재고량" value="0" />
          </div>` : `
          <div class="form-group">
            <label class="form-label">식품 유형</label>
            <select class="form-control" id="niFoodType">
              <option value="">-- 선택 (선택사항) --</option>
              <option value="기타가공품">기타가공품</option>
              <option value="고형차">고형차</option>
              <option value="추출가공식품">추출가공식품</option>
              <option value="액상차">액상차</option>
              <option value="캔디류">캔디류</option>
              <option value="일반식품">일반식품</option>
            </select>
          </div>`}
        </div>
      </form>`,
      [
        { text: '취소', class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '저장 및 생성', class: 'btn-primary', action: 'InventoryPage.submitNewItem(event)' }
      ]
    );
  },

  submitNewItem(e) {
    if(e) e.preventDefault();
    const type = this._newItemType || this.currentType;
    const items = type === 'raw' ? HACCP_DATA.rawMaterials : type === 'sub' ? HACCP_DATA.subMaterials : null;
    const stocks = type === 'raw' ? HACCP_DATA.currentStock.raw : type === 'sub' ? HACCP_DATA.currentStock.sub : HACCP_DATA.currentStock.finished;
    
    let code = document.getElementById('niCode').value.trim();
    if (!code) {
       const pfx = type === 'raw' ? 'RM' : type === 'sub' ? 'SM' : 'FP';
       code = pfx + String(stocks.length + 1).padStart(3, '0');
    }
    
    const minStock = type !== 'finished' ? parseFloat(document.getElementById('niMinStock').value) : 0;
    const foodType = type === 'finished' ? (document.getElementById('niFoodType')?.value || '') : '';
    
    const newItem = {
      id: code,
      name: document.getElementById('niName').value.trim(),
      unit: document.getElementById('niUnit').value.trim(),
      minStock: minStock,
      balance: 0,
      ...(type === 'finished' && foodType ? { foodType } : {})
    };
    
    // 재고 및 기초 정보에 둥록
    stocks.unshift(newItem);
    if (items) {
      items.unshift({
        id: newItem.id, name: newItem.name, unit: newItem.unit, spec: ''
      });
    }
    
    App.closeModal();
    App.showToast('success', '신규 등록 완료', `[${code}] ${newItem.name} 품목이 등록되었습니다.`);
    
    // 콜백이 존재하면 실행 후 종료 (예: BOM에서 호출한 경우)
    if (this._newItemCallback && typeof this._newItemCallback === 'function') {
       this._newItemCallback(newItem);
       this._newItemCallback = null;
       return;
    }
    
    // 수불대장 메뉴에서 등록한 경우 화면 즉각 갱신 및 탭 이동
    this.switchTab('stock');
    document.getElementById('invContent').innerHTML = this.renderContent();
  },

  // =============================================
  // 일괄 업로드 로직 (Excel 복붙 & CSV)
  // =============================================
  openBulkUploadModal() {
    App.showModal(
      `⬆️ 수불대장 초기 데이터 일괄 업로드`,
      `
      <div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem; padding:0.75rem; background:#e9f2ff; border:1px solid #b6d4fe; border-radius:4px; line-height:1.5;">
        💡 <strong>초기 재고 및 수불 내역 일괄 등록 안내</strong><br/>
        기존에 사용하시던 엑셀의 데이터(작업일자, 품목명, 구분, 수량, 비고 순)를 복사해서 바로 붙여넣거나,<br/>
        아래 [양식 다운로드] 버튼을 통해 CSV 파일을 작성하여 첨부해주세요.<br/>
        <span style="color:var(--color-danger);font-size:0.75rem;">(*등록되지 않은 '품목명'을 입력하면 시스템이 자동으로 기초 정보를 신규 생성합니다.)</span>
      </div>
      
      <div class="form-group">
        <label class="form-label" style="font-weight:700;">1. CSV 파일 선택</label>
        <input type="file" id="bulkFile" class="form-control" accept=".csv" />
      </div>

      <div style="text-align:center; margin:1rem 0; font-weight:700; color:var(--text-muted); font-size:0.85rem;">----- 또는 -----</div>

      <div class="form-group">
        <label class="form-label" style="font-weight:700;">2. 엑셀 데이터 직접 붙여넣기 (권장)</label>
        <textarea id="bulkText" class="form-control" rows="8" style="font-family:monospace; font-size:0.8rem; white-space:pre;" placeholder="2026-03-20	사과농축액	입고	500	초기재고 설정\n2026-03-20	수용성키토산	입고	150	초기재고 설정"></textarea>
      </div>
      `,
      [
        { text: '닫기', class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '양식 다운로드', class: 'btn-info', action: 'InventoryPage.downloadBulkTemplate()' },
        { text: '업로드 실행', class: 'btn-primary', action: 'InventoryPage.submitBulkUpload()' }
      ]
    );
  },

  downloadBulkTemplate() {
    let csv = '\uFEFF날짜(YYYY-MM-DD),품목명(필수),구분(입고/출고),수량(숫자),비고\n2026-03-20,정제수,입고,1000,초기재고설정\n2026-03-20,사과농축액,입고,500,초기재고설정\n';
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `HACCP_일괄업로드양식.csv`;
    link.click();
    App.showToast('info', '다운로드 완료', '작성용 CSV 양식 파일이 다운로드 되었습니다.');
  },

  submitBulkUpload() {
    const fileInput = document.getElementById('bulkFile');
    const textData = document.getElementById('bulkText').value.trim();

    if (fileInput.files.length > 0) {
       const file = fileInput.files[0];
       const reader = new FileReader();
       reader.onload = (e) => {
          this.processBulkData(e.target.result, 'csv');
       };
       reader.readAsText(file, 'utf-8');
    } else if (textData) {
       this.processBulkData(textData, 'tsv');
    } else {
       App.showToast('error', '입력 오류', '파일을 첨부하거나 텍스트 영역에 데이터를 붙여넣어 주세요.');
    }
  },

  processBulkData(data, format) {
    const type = this.currentType;
    const ledger = type === 'raw' ? HACCP_DATA.rawLedger : type === 'sub' ? HACCP_DATA.subLedger : HACCP_DATA.finishedLedger;
    const stocks = type === 'raw' ? HACCP_DATA.currentStock.raw : type === 'sub' ? HACCP_DATA.currentStock.sub : HACCP_DATA.currentStock.finished;
    const items = type === 'raw' ? HACCP_DATA.rawMaterials : type === 'sub' ? HACCP_DATA.subMaterials : HACCP_DATA.products;

    const lines = data.split('\n').filter(l => l.trim().length > 0);
    if (lines.length === 0) return App.showToast('error', '오류', '데이터가 비어있습니다.');
    
    // 첫 줄 헤더 스킵 처리
    let startIndex = (lines[0].includes('날짜') || lines[0].includes('품목') || lines[0].includes('구분')) ? 1 : 0;
    let successCount = 0;
    
    const sep = format === 'csv' ? ',' : '\t';

    for (let i = startIndex; i < lines.length; i++) {
       const cols = lines[i].split(sep).map(s => s.trim().replace(/^"|"$/g, ''));
       if (cols.length < 4) continue;

       const [dateStr, name, typeStr, qtyStr, note] = cols;
       const qty = parseFloat(qtyStr.replace(/,/g,'')); // 콤마 제거 후 파싱
       if (!name || isNaN(qty) || qty <= 0) continue;

       const t = (typeStr.includes('입고') || typeStr.toLowerCase() === 'in') ? 'in' : 'out';
       const date = dateStr || new Date().toISOString().split('T')[0];
       
       // 품목 검증 및 자동 생성 (초기 업로드의 핵심 기능)
       let stockItem = stocks.find(s => s.name === name);
       if (!stockItem) {
          const pfx = type === 'raw' ? 'RM' : type === 'sub' ? 'SM' : 'FP';
          const newCode = pfx + String(stocks.length + 1).padStart(3, '0');
          stockItem = { id: newCode, name: name, unit: '자동생성', minStock: 0, balance: 0 };
          stocks.unshift(stockItem); 
          if(items) items.unshift({id: newCode, name: name, unit: '자동생성', spec: ''});
       }

       // 잔고 계산
       if (t === 'in') stockItem.balance += qty;
       else stockItem.balance -= qty;

       // 장부 기록
       const record = {
         id: 'L' + Date.now() + i + Math.floor(Math.random()*100),
         date: date,
         name: stockItem.name,
         type: t,
         qty: qty,
         balance: stockItem.balance,
         expiryDate: '',
         lot: '',
         supplier: '-',
         customer: '-',
         inspector: HACCP_DATA.employees[0].name,
         note: note || '시스템 일괄 업로드'
       };
       ledger.unshift(record);
       successCount++;
    }

    App.closeModal();
    if(successCount > 0) {
      App.showToast('success', '업로드 완료', `총 ${successCount}건의 데이터가 성공적으로 처리되었습니다.`);
      this.switchTab('ledger'); // 업로드 후 장부 탭으로 전환
      document.getElementById('invContent').innerHTML = this.renderContent();
    } else {
      App.showToast('error', '업로드 실패', '형식에 맞는 데이터를 찾지 못했습니다. 엑셀을 확인하세요.');
    }
  }
};
