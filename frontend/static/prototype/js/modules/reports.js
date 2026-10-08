// =============================================
// BIODOT HACCP - 보고서 모듈
// =============================================

const ReportsPage = {

  currentReport: null,

  render() {
    const today = new Date().toLocaleDateString('ko-KR');
    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">📊 보고서</h1>
          <p class="page-desc">HACCP 주요 기록 보고서 생성 · ${today}</p>
        </div>
      </div>

      <!-- 보고서 카드 그리드 -->
      <div class="grid-3" style="margin-bottom:1.5rem;">
        ${this.renderReportCard('production','생산일지 보고서','📋','이번 달 생산 내역, LOT별 실적 및 자재 투입 현황','primary')}
        ${this.renderReportCard('ccp','CCP 모니터링 보고서','⚠️','CCP 측정값 이력 및 이탈 현황 분석','warning')}
        ${this.renderReportCard('inventory','수불대장 보고서','📦','원료·부자재·완제품 입출고 및 재고 현황','info')}
        ${this.renderReportCard('quality','자가품질검사 보고서','🔬','검사 항목별 결과 및 부적합 현황','success')}
        ${this.renderReportCard('prerequisite','선행요건 이행 보고서','✅','위생·설비·교육 이행 현황 및 미이행 항목','danger')}
        ${this.renderReportCard('monthly','월별 종합 보고서','📈','생산·품질·CCP 월별 통합 현황','primary')}
      </div>

      <!-- 보고서 미리보기 영역 -->
      <div id="reportPreview">
        ${this.renderWelcome()}
      </div>
    </div>`;
  },

  renderReportCard(type, title, icon, desc, color) {
    return `
    <div class="card glow" style="cursor:pointer;transition:all 0.2s;"
         onclick="ReportsPage.selectReport('${type}')"
         onmouseenter="this.style.transform='translateY(-3px)'"
         onmouseleave="this.style.transform='translateY(0)'">
      <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem;">
        <div class="kpi-icon kpi-card ${color}" style="width:44px;height:44px;border-radius:10px;font-size:1.2rem;display:flex;align-items:center;justify-content:center;">
          ${icon}
        </div>
        <div>
          <div style="font-weight:700;font-size:0.9rem;">${title}</div>
        </div>
      </div>
      <p style="font-size:0.75rem;color:var(--text-muted);line-height:1.5;">${desc}</p>
      <div style="margin-top:1rem;display:flex;justify-content:flex-end;">
        <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();ReportsPage.generateReport('${type}')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          생성
        </button>
      </div>
    </div>`;
  },

  renderWelcome() {
    return `
    <div class="card" style="text-align:center;padding:3rem 2rem;">
      <div style="font-size:3rem;margin-bottom:1rem;">📊</div>
      <h3 style="font-size:1.1rem;color:var(--text-primary);margin-bottom:0.5rem;">보고서를 선택하세요</h3>
      <p style="font-size:0.8rem;color:var(--text-muted);">위 카드에서 원하는 보고서를 클릭하거나 생성 버튼을 누르세요.</p>
    </div>`;
  },

  selectReport(type) {
    this.generateReport(type);
  },

  generateReport(type) {
    const container = document.getElementById('reportPreview');
    if (!container) return;

    container.innerHTML = `<div class="gen-loading"><div class="gen-loading-ring"></div><p style="color:var(--text-muted);font-size:0.85rem;">보고서 생성 중...</p></div>`;

    setTimeout(() => {
      let html = '';
      switch(type) {
        case 'production':   html = this.buildProductionReport(); break;
        case 'ccp':          html = this.buildCCPReport(); break;
        case 'inventory':    html = this.buildInventoryReport(); break;
        case 'quality':      html = this.buildQualityReport(); break;
        case 'prerequisite': html = this.buildPrerequisiteReport(); break;
        case 'monthly':      html = this.buildMonthlyReport(); break;
        default: html = this.renderWelcome();
      }
      container.innerHTML = html;
    }, 600);
  },

  // ── 생산일지 보고서 ──────────────────────────
  buildProductionReport() {
    const logs = HACCP_DATA.productionLogs;
    const totalQty = logs.reduce((s,l) => s + (l.actualQty||0), 0);
    const defects  = logs.reduce((s,l) => s + (l.defectQty||0), 0);
    return `
    <div class="card fade-in">
      <div class="card-header">
        <div>
          <div class="card-title">📋 생산일지 보고서</div>
          <div class="card-subtitle">전체 생산 내역 요약</div>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="ReportsPage.printReport('production')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px;"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
          인쇄
        </button>
      </div>

      <div class="kpi-grid" style="margin-bottom:1rem;">
        <div class="kpi-card primary"><div class="kpi-value">${logs.length}</div><div class="kpi-label">총 생산 배치</div></div>
        <div class="kpi-card success"><div class="kpi-value">${totalQty.toLocaleString()}</div><div class="kpi-label">총 생산량 (개)</div></div>
        <div class="kpi-card ${defects>0?'warning':'success'}"><div class="kpi-value">${defects}</div><div class="kpi-label">총 불량수</div></div>
        <div class="kpi-card info"><div class="kpi-value">${logs.filter(l=>l.status==='completed').length}</div><div class="kpi-label">완료 배치</div></div>
      </div>

      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr>
            <th>생산일</th><th>LOT번호</th><th>제품명</th>
            <th>계획수량</th><th>실생산</th><th>불량</th><th>담당자</th><th>상태</th>
          </tr></thead>
          <tbody>
            ${logs.map(l => `<tr>
              <td class="no-wrap">${l.date}</td>
              <td><code style="font-size:0.75rem;color:var(--brand-primary);">${l.lot}</code></td>
              <td style="font-weight:600;">${l.product}</td>
              <td style="text-align:right;">${(l.planQty||0).toLocaleString()}</td>
              <td style="text-align:right;color:var(--color-success);font-weight:700;">${(l.actualQty||0).toLocaleString()}</td>
              <td style="text-align:right;color:${l.defectQty>0?'var(--color-danger)':'var(--text-muted)'};">${l.defectQty||0}</td>
              <td>${(l.workers||[]).join(', ')}</td>
              <td><span class="badge ${l.status==='completed'?'badge-success':'badge-warning'} badge-dot">${l.status==='completed'?'완료':'진행중'}</span></td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
  },

  // ── CCP 모니터링 보고서 ──────────────────────
  buildCCPReport() {
    const logs = HACCP_DATA.ccpLogs;
    const deviations = logs.filter(l => l.status === 'danger' || l.status === 'warning');
    return `
    <div class="card fade-in">
      <div class="card-header">
        <div>
          <div class="card-title">⚠️ CCP 모니터링 보고서</div>
          <div class="card-subtitle">중요관리점 측정 이력 및 이탈 현황</div>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="ReportsPage.printReport('ccp')">인쇄</button>
      </div>

      <div class="kpi-grid" style="margin-bottom:1rem;">
        <div class="kpi-card primary"><div class="kpi-value">${logs.length}</div><div class="kpi-label">총 측정 건수</div></div>
        <div class="kpi-card success"><div class="kpi-value">${logs.filter(l=>l.status==='ok').length}</div><div class="kpi-label">정상</div></div>
        <div class="kpi-card danger"><div class="kpi-value">${deviations.length}</div><div class="kpi-label">이탈/경고</div></div>
        <div class="kpi-card info"><div class="kpi-value">${HACCP_DATA.ccpPoints.length}</div><div class="kpi-label">관리 CCP 수</div></div>
      </div>

      ${deviations.length > 0 ? `
      <div style="background:rgba(239,68,68,0.05);border:1px solid rgba(239,68,68,0.2);border-radius:8px;padding:1rem;margin-bottom:1rem;">
        <div style="font-weight:700;color:var(--color-danger);margin-bottom:0.5rem;">⚠️ 이탈 발생 내역 (${deviations.length}건)</div>
        ${deviations.map(d => `
        <div style="padding:0.5rem;border-bottom:1px solid rgba(239,68,68,0.1);font-size:0.8rem;">
          <span style="color:var(--text-muted);">${d.date} ${d.time}</span> |
          <strong>${d.ccpId}</strong> |
          측정값: <strong style="color:var(--color-danger);">${d.value ?? '-'} ${d.unit||''}</strong> |
          조치: ${d.action || '조치 없음'}
        </div>`).join('')}
      </div>` : `<div style="color:var(--color-success);padding:1rem;background:rgba(16,185,129,0.05);border-radius:8px;margin-bottom:1rem;text-align:center;">✅ 이탈 없음 - 모든 CCP 정상 범위</div>`}

      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr><th>날짜</th><th>시간</th><th>CCP</th><th>측정값</th><th>상태</th><th>조치사항</th><th>기록자</th></tr></thead>
          <tbody>
            ${logs.map(l => `<tr>
              <td class="no-wrap">${l.date}</td>
              <td>${l.time}</td>
              <td><span class="badge badge-brand">${l.ccpId}</span></td>
              <td style="font-weight:700;">${l.value !== null ? l.value + ' ' + (l.unit||'') : '미입력'}</td>
              <td><span class="badge ${l.status==='ok'?'badge-success':l.status==='danger'?'badge-danger':'badge-warning'} badge-dot">${l.status==='ok'?'정상':l.status==='danger'?'이탈':'경고'}</span></td>
              <td style="font-size:0.75rem;">${l.action||'-'}</td>
              <td>${l.recorder||'-'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
  },

  // ── 수불대장 보고서 ──────────────────────────
  buildInventoryReport() {
    const rawStock = HACCP_DATA.currentStock.raw;
    const subStock = HACCP_DATA.currentStock.sub;
    const finStock = HACCP_DATA.currentStock.finished;
    const lowRaw   = rawStock.filter(s => s.balance <= s.minStock * 1.5);

    return `
    <div class="card fade-in">
      <div class="card-header">
        <div>
          <div class="card-title">📦 수불대장 보고서</div>
          <div class="card-subtitle">현재고 및 입출고 요약</div>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="ReportsPage.printReport('inventory')">인쇄</button>
      </div>

      ${lowRaw.length>0 ? `
      <div style="background:rgba(245,158,11,0.07);border:1px solid rgba(245,158,11,0.25);border-radius:8px;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.8rem;">
        ⚠️ <strong>부족 주의 원료:</strong> ${lowRaw.map(s=>`${s.name}(${s.balance.toLocaleString()}${s.unit})`).join(', ')}
      </div>` : ''}

      <div style="font-weight:700;margin-bottom:0.5rem;font-size:0.85rem;">📌 원료 현재고</div>
      <div class="table-wrapper" style="margin-bottom:1rem;">
        <table class="data-table">
          <thead><tr><th>품목코드</th><th>품목명</th><th>현재고</th><th>단위</th><th>최소재고</th><th>상태</th></tr></thead>
          <tbody>
            ${rawStock.map(s => {
              const isCrit = s.balance <= s.minStock;
              const isLow  = s.balance <= s.minStock * 1.5;
              return `<tr>
                <td><code style="font-size:0.75rem;">${s.id}</code></td>
                <td style="font-weight:600;">${s.name}</td>
                <td style="text-align:right;font-weight:800;">${s.balance.toLocaleString()}</td>
                <td>${s.unit}</td>
                <td style="text-align:right;color:var(--text-muted);">${(s.minStock||0).toLocaleString()}</td>
                <td><span class="badge ${isCrit?'badge-danger':isLow?'badge-warning':'badge-success'} badge-dot">${isCrit?'부족':isLow?'주의':'정상'}</span></td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>

      <div style="font-weight:700;margin-bottom:0.5rem;font-size:0.85rem;">📦 완제품 현재고</div>
      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr><th>제품명</th><th>현재고 (개)</th><th>LOT</th><th>유통기한</th></tr></thead>
          <tbody>
            ${finStock.map(s => `<tr>
              <td style="font-weight:600;">${s.name}</td>
              <td style="text-align:right;font-weight:800;color:var(--brand-primary);">${s.balance.toLocaleString()}</td>
              <td><code style="font-size:0.75rem;">${s.lot||'-'}</code></td>
              <td>${s.expiryDate||'-'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
  },

  // ── 자가품질검사 보고서 ──────────────────────
  buildQualityReport() {
    const checks = HACCP_DATA.qualityChecks || [];
    const passed = checks.filter(c => c.status === 'pass');
    const failed = checks.filter(c => c.status === 'fail');

    return `
    <div class="card fade-in">
      <div class="card-header">
        <div>
          <div class="card-title">🔬 자가품질검사 보고서</div>
          <div class="card-subtitle">검사 결과 현황</div>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="ReportsPage.printReport('quality')">인쇄</button>
      </div>

      <div class="kpi-grid" style="margin-bottom:1rem;">
        <div class="kpi-card primary"><div class="kpi-value">${checks.length}</div><div class="kpi-label">총 검사 건수</div></div>
        <div class="kpi-card success"><div class="kpi-value">${passed.length}</div><div class="kpi-label">적합</div></div>
        <div class="kpi-card danger"><div class="kpi-value">${failed.length}</div><div class="kpi-label">부적합</div></div>
        <div class="kpi-card warning"><div class="kpi-value">${checks.filter(c=>c.status==='pending').length}</div><div class="kpi-label">검사 대기</div></div>
      </div>

      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr><th>날짜</th><th>제품명</th><th>LOT</th><th>검사항목</th><th>기준</th><th>결과값</th><th>판정</th><th>검사자</th></tr></thead>
          <tbody>
            ${checks.length === 0 ? '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text-muted);">검사 내역이 없습니다.</td></tr>' :
            checks.map(c => `<tr>
              <td class="no-wrap">${c.date}</td>
              <td style="font-weight:600;">${c.product}</td>
              <td><code style="font-size:0.7rem;">${c.lot}</code></td>
              <td>${c.testItem}</td>
              <td style="font-size:0.75rem;color:var(--text-muted);">${c.standard}</td>
              <td style="font-weight:700;">${c.result||'-'}</td>
              <td><span class="badge ${c.status==='pass'?'badge-success':c.status==='fail'?'badge-danger':'badge-neutral'} badge-dot">${c.status==='pass'?'적합':c.status==='fail'?'부적합':'대기'}</span></td>
              <td>${c.tester||'-'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
  },

  // ── 선행요건 이행 보고서 ─────────────────────
  buildPrerequisiteReport() {
    const items = HACCP_DATA.prerequisiteItems || [];
    const byCategory = {};
    items.forEach(i => {
      if (!byCategory[i.category]) byCategory[i.category] = [];
      byCategory[i.category].push(i);
    });

    const warnings = items.filter(i => i.status === 'warning' || i.status === 'danger');

    return `
    <div class="card fade-in">
      <div class="card-header">
        <div>
          <div class="card-title">✅ 선행요건 이행 보고서</div>
          <div class="card-subtitle">위생·설비·교육 이행 현황</div>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="ReportsPage.printReport('prerequisite')">인쇄</button>
      </div>

      <div class="kpi-grid" style="margin-bottom:1rem;">
        <div class="kpi-card primary"><div class="kpi-value">${items.length}</div><div class="kpi-label">총 관리 항목</div></div>
        <div class="kpi-card success"><div class="kpi-value">${items.filter(i=>i.status==='ok').length}</div><div class="kpi-label">정상</div></div>
        <div class="kpi-card ${warnings.length>0?'warning':'success'}"><div class="kpi-value">${warnings.length}</div><div class="kpi-label">주의/미이행</div></div>
        <div class="kpi-card info"><div class="kpi-value">${Object.keys(byCategory).length}</div><div class="kpi-label">카테고리 수</div></div>
      </div>

      ${warnings.length > 0 ? `
      <div style="background:rgba(245,158,11,0.05);border:1px solid rgba(245,158,11,0.2);border-radius:8px;padding:0.75rem 1rem;margin-bottom:1rem;">
        <div style="font-weight:700;color:var(--color-warning);margin-bottom:0.5rem;">⚠️ 주의 항목 (${warnings.length}건)</div>
        ${warnings.map(w => `<div style="font-size:0.8rem;padding:0.3rem 0;">[${w.category}] ${w.name} - 다음 점검일: ${w.nextDate}</div>`).join('')}
      </div>` : ''}

      ${Object.entries(byCategory).map(([cat, list]) => `
      <div style="margin-bottom:1rem;">
        <div style="font-weight:700;font-size:0.85rem;margin-bottom:0.5rem;color:var(--text-secondary);">📌 ${cat}</div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead><tr><th>항목명</th><th>주기</th><th>최종점검일</th><th>다음점검일</th><th>담당자</th><th>상태</th></tr></thead>
            <tbody>
              ${list.map(i => `<tr>
                <td style="font-weight:600;">${i.name}</td>
                <td><span class="badge badge-neutral">${{daily:'매일',weekly:'매주',monthly:'매월',yearly:'매년'}[i.frequency]||i.frequency}</span></td>
                <td class="no-wrap">${i.lastDate||'-'}</td>
                <td class="no-wrap">${i.nextDate||'-'}</td>
                <td>${i.assignee||'-'}</td>
                <td><span class="badge ${i.status==='ok'?'badge-success':'badge-warning'} badge-dot">${i.status==='ok'?'정상':'주의'}</span></td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>`).join('')}
    </div>`;
  },

  // ── 월별 종합 보고서 ─────────────────────────
  buildMonthlyReport() {
    const monthly = HACCP_DATA.monthlyProduction || [];
    const lastMonth = monthly[monthly.length - 1] || {};
    const prevMonth = monthly[monthly.length - 2] || {};
    const growthRate = prevMonth.finished
      ? (((lastMonth.finished - prevMonth.finished) / prevMonth.finished) * 100).toFixed(1)
      : '0';

    const maxFinish = Math.max(...monthly.map(m => m.finished));

    return `
    <div class="card fade-in">
      <div class="card-header">
        <div>
          <div class="card-title">📈 월별 종합 보고서</div>
          <div class="card-subtitle">최근 6개월 생산·품질·재고 통합 현황</div>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="ReportsPage.printReport('monthly')">인쇄</button>
      </div>

      <div class="kpi-grid" style="margin-bottom:1.5rem;">
        <div class="kpi-card primary">
          <div class="kpi-value">${(lastMonth.finished||0).toLocaleString()}</div>
          <div class="kpi-label">이번달 완제품 생산 (개)</div>
          <div class="kpi-change ${parseFloat(growthRate)>=0?'up':'down'}">${parseFloat(growthRate)>=0?'▲':'▼'} ${Math.abs(growthRate)}% vs 전월</div>
        </div>
        <div class="kpi-card success">
          <div class="kpi-value">${HACCP_DATA.qualityChecks?.filter(c=>c.status==='pass').length||0}</div>
          <div class="kpi-label">이번달 품질검사 적합</div>
        </div>
        <div class="kpi-card ${HACCP_DATA.ccpLogs?.some(l=>l.status==='danger')?'danger':'success'}">
          <div class="kpi-value">${HACCP_DATA.ccpLogs?.filter(l=>l.status==='danger').length||0}</div>
          <div class="kpi-label">CCP 이탈 건수</div>
        </div>
        <div class="kpi-card warning">
          <div class="kpi-value">${HACCP_DATA.alerts?.filter(a=>!a.isRead).length||0}</div>
          <div class="kpi-label">미처리 알림</div>
        </div>
      </div>

      <!-- 월별 생산 추이 차트 (CSS 바 차트) -->
      <div style="margin-bottom:1.5rem;">
        <div style="font-weight:700;font-size:0.85rem;margin-bottom:1rem;color:var(--text-secondary);">📊 월별 완제품 생산량 추이</div>
        <div style="display:flex;align-items:flex-end;gap:0.75rem;height:120px;padding:0 1rem;">
          ${monthly.map(m => {
            const pct = Math.round((m.finished / maxFinish) * 100);
            const isLast = m === lastMonth;
            return `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:0.3rem;">
              <div style="font-size:0.65rem;color:var(--text-muted);">${m.finished.toLocaleString()}</div>
              <div style="width:100%;height:${pct}%;background:${isLast?'linear-gradient(to top,var(--brand-primary),var(--brand-secondary))':'var(--bg-elevated)'};
                border-radius:4px 4px 0 0;transition:height 0.5s ease;min-height:4px;
                ${isLast?'box-shadow:0 0 12px rgba(0,212,170,0.3);':''}"></div>
              <div style="font-size:0.7rem;color:${isLast?'var(--brand-primary)':'var(--text-muted)'};font-weight:${isLast?'700':'400'};">${m.month}</div>
            </div>`;
          }).join('')}
        </div>
      </div>

      <!-- 월별 상세 테이블 -->
      <div class="table-wrapper">
        <table class="data-table">
          <thead><tr><th>월</th><th>원료 투입 (g)</th><th>완제품 생산 (개)</th><th>전월 대비</th></tr></thead>
          <tbody>
            ${monthly.map((m, i) => {
              const prev = monthly[i-1];
              const diff = prev ? m.finished - prev.finished : 0;
              return `<tr>
                <td style="font-weight:${m===lastMonth?'800':'400'};color:${m===lastMonth?'var(--brand-primary)':''};">${m.month}${m===lastMonth?' ★':''}</td>
                <td style="text-align:right;">${m.raw.toLocaleString()}</td>
                <td style="text-align:right;font-weight:700;">${m.finished.toLocaleString()}</td>
                <td style="text-align:right;color:${diff>0?'var(--color-success)':diff<0?'var(--color-danger)':'var(--text-muted)'};">
                  ${i===0?'-':diff>0?'▲ +':'▼ '}${i===0?'':Math.abs(diff).toLocaleString()}
                </td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
  },

  // ── 인쇄 ─────────────────────────────────────
  printReport(type) {
    const titles = {
      production: '생산일지 보고서', ccp: 'CCP 모니터링 보고서',
      inventory: '수불대장 보고서', quality: '자가품질검사 보고서',
      prerequisite: '선행요건 이행 보고서', monthly: '월별 종합 보고서'
    };
    const content = document.getElementById('reportPreview');
    if (!content) return;

    const w = window.open('', '_blank');
    w.document.write(`<!DOCTYPE html><html lang="ko"><head>
      <meta charset="UTF-8"/>
      <title>바이오닷 HACCP - ${titles[type]||'보고서'}</title>
      <style>
        @page{size:A4;margin:15mm 12mm;}
        body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;font-size:9pt;color:#111;}
        table{width:100%;border-collapse:collapse;font-size:8.5pt;}
        th{background:#f0f0f0;padding:6px 8px;text-align:left;border:1px solid #ccc;font-weight:600;}
        td{padding:5px 8px;border:1px solid #ddd;}
        tr:nth-child(even) td{background:#fafafa;}
        h1{font-size:14pt;margin-bottom:4px;}
        .kpi-row{display:flex;gap:8px;margin-bottom:12px;}
        .kpi-box{flex:1;border:1px solid #ccc;border-radius:4px;padding:8px;text-align:center;}
        .kpi-box .v{font-size:18pt;font-weight:800;}
        .kpi-box .l{font-size:7.5pt;color:#555;margin-top:2px;}
      </style>
    </head><body>
      <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
        <div><h1>바이오닷 HACCP · ${titles[type]||'보고서'}</h1></div>
        <div style="font-size:8pt;color:#666;text-align:right;">출력일: ${new Date().toLocaleDateString('ko-KR')}<br>담당: HACCP팀</div>
      </div>
      <hr style="border:1.5px solid #000;margin-bottom:10px;"/>
      ${content.innerHTML}
    </body></html>`);
    w.document.close();
    setTimeout(() => w.print(), 600);
    App.showToast('success', '인쇄', `${titles[type]||'보고서'} 인쇄 창을 열었습니다.`);
  }
};
