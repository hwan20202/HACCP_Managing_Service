// =============================================
// BIODOT HACCP - 대시보드 페이지
// =============================================

const DashboardPage = {
  render() {
    const alerts = HACCP_DATA.alerts.filter(a => !a.isRead);
    const ccpWarnings = HACCP_DATA.ccpPoints.filter(c => c.status !== 'ok');
    const prereqDanger = HACCP_DATA.prerequisiteItems.filter(p => p.status === 'danger');
    const prereqWarning = HACCP_DATA.prerequisiteItems.filter(p => p.status === 'warning');
    const today = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });

    const totalRawStock = HACCP_DATA.currentStock.raw.reduce((s, r) => s + (r.balance||0), 0);
    const totalFinished = HACCP_DATA.currentStock.finished.reduce((s, f) => s + (f.balance||0), 0);
    // 가장 최근 제조일 탐색
    const allDates = HACCP_DATA.productionLogs.map(p => p.date).filter(Boolean).sort();
    const latestDate = allDates.length > 0 ? allDates[allDates.length - 1] : new Date().toISOString().split('T')[0];
    const todayProduction = HACCP_DATA.productionLogs.filter(p => p.date === latestDate);
    const todayProdQty = todayProduction.reduce((s, p) => s + (p.actualQty || p.productionQty || 0), 0);

    return `
    <div class="fade-in">
      <!-- 페이지 헤더 -->
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">대시보드</h1>
          <p class="page-desc">바이오닷 HACCP 식품안전관리 현황 · ${today}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" onclick="App.showToast('info','인쇄','인쇄 기능은 준비 중입니다.')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
            인쇄
          </button>
          <button class="btn btn-primary" onclick="App.navigate('production-log')" style="background:linear-gradient(135deg,var(--brand-primary),var(--brand-dark));box-shadow:0 4px 14px rgba(0,123,255,0.3);">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            ⚡ 자동 문서 생성
          </button>
        </div>
      </div>

      <!-- KPI 카드 -->
      <div class="kpi-grid">
        <div class="kpi-card primary">
          <div class="kpi-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg></div>
          <div class="kpi-value">${todayProdQty.toLocaleString()}</div>
          <div class="kpi-label">오늘 생산량 (개)</div>
          <div class="kpi-change up">▲ 목표 3,000개 달성</div>
        </div>
        <div class="kpi-card ${ccpWarnings.length > 0 ? 'danger' : 'success'}">
          <div class="kpi-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></div>
          <div class="kpi-value">${HACCP_DATA.ccpPoints.length - ccpWarnings.length}<small style="font-size:1rem;color:var(--text-muted)">/${HACCP_DATA.ccpPoints.length}</small></div>
          <div class="kpi-label">CCP 정상 관리점</div>
          <div class="kpi-change ${ccpWarnings.length > 0 ? 'down' : 'up'}">${ccpWarnings.length > 0 ? `▼ ${ccpWarnings.length}개 이탈/경고` : '▲ 전체 정상'}</div>
        </div>
        <div class="kpi-card info">
          <div class="kpi-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg></div>
          <div class="kpi-value">${totalFinished.toLocaleString()}</div>
          <div class="kpi-label">완제품 현재고 (개)</div>
          <div class="kpi-change up">▲ 3개 품목</div>
        </div>
        <div class="kpi-card ${HACCP_DATA.periodicTasks.filter(t => t.status==='danger'||t.status==='warning').length > 0 ? 'danger' : 'success'}">
          <div class="kpi-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></div>
          <div class="kpi-value">${HACCP_DATA.periodicTasks.filter(t => t.status==='pending'||t.status==='danger'||t.status==='warning').length}</div>
          <div class="kpi-label">필수 점검 누락/대기</div>
          <div class="kpi-change ${HACCP_DATA.periodicTasks.filter(t => t.status==='danger').length > 0 ? 'down' : 'up'}">${HACCP_DATA.periodicTasks.filter(t => t.status==='danger').length > 0 ? `▼ 긴급 ${HACCP_DATA.periodicTasks.filter(t => t.status==='danger').length}건 확인 요망` : '▲ 누락 없이 진행중'}</div>
        </div>
        <div class="kpi-card warning">
          <div class="kpi-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg></div>
          <div class="kpi-value">${alerts.length}</div>
          <div class="kpi-label">미확인 알림</div>
          <div class="kpi-change down">▼ 즉시 확인 필요</div>
        </div>
      </div>

      </div>

      <!-- K-HACCP 주기별 점검 현황 (Matrix Calendar) - 최상단 메인 배치 -->
      <div class="card" style="padding-bottom:0;margin-bottom:1rem;border:1px solid var(--brand-primary);box-shadow:0 8px 24px rgba(0,212,170,0.15);">
        <div class="card-header" style="margin-bottom:0.5rem;">
          <div>
            <div class="card-title" style="color:var(--brand-primary);">🗓️ 주기별 점검 일지 (통합 캘린더)</div>
            <div class="card-subtitle">2026년 3월 일정표 및 결재 상태</div>
          </div>
          <div style="display:flex;gap:0.75rem;font-size:0.65rem;font-weight:600;">
            <span style="display:flex;align-items:center;gap:0.2rem;"><span style="width:10px;height:10px;border-radius:50%;background:var(--color-success);"></span>작성/결재완료</span>
            <span style="display:flex;align-items:center;gap:0.2rem;"><span style="width:10px;height:10px;border-radius:50%;background:var(--color-warning);"></span>결재대기</span>
            <span style="display:flex;align-items:center;gap:0.2rem;"><span style="width:10px;height:10px;border-radius:50%;background:var(--color-danger);"></span>미작성(누락)</span>
          </div>
        </div>
        
        <div style="overflow-x:auto;padding-bottom:1rem;margin:0 -1.25rem;padding-left:1.25rem;padding-right:1.25rem;">
          <table style="width:max-content;min-width:100%;border-collapse:separate;border-spacing:0;font-size:0.75rem;text-align:center;">
            <thead>
              <tr>
                <th style="position:sticky;left:0;background:var(--bg-elevated);padding:0.6rem;min-width:140px;border-bottom:2px solid var(--border-subtle);border-right:1px solid var(--border-subtle);z-index:2;text-align:left;font-weight:700;">일지 목록</th>
                ${Array(31).fill(0).map((_,i) => `<th style="padding:0.6rem 0.3rem;width:28px;border-bottom:2px solid var(--border-subtle);color:${i===18?'var(--brand-primary)':'var(--text-muted)'};font-weight:${i===18?800:600};">${i+1}</th>`).join('')}
              </tr>
            </thead>
            <tbody>
              ${[
                { name: '1. 생산 일지', freq: 1, type: 'daily' },
                { name: '2. 작업장위생점검표', freq: 1, type: 'daily' },
                { name: '3. 금속검출기(CCP-3P)', freq: 1, type: 'daily' },
                { name: '4. 자력선별기(CCP-1P)', freq: 1, type: 'daily' },
                { name: '5. 건조기기록(CCP-2B)', freq: 1, type: 'daily' },
                { name: '6. 원료수불대장', freq: 1, type: 'daily' },
                { name: '7. 완제품수불대장', freq: 1, type: 'daily' },
                { name: '8. 폐기물처리대장', freq: 7, type: 'weekly' },
                { name: '9. 방충방서점검표', freq: 30, type: 'monthly' }
              ].map(row => `
                <tr>
                  <td style="position:sticky;left:0;background:var(--bg-base);padding:0.5rem 0.6rem;border-bottom:1px solid var(--border-subtle);border-right:1px solid var(--border-subtle);text-align:left;font-weight:600;z-index:1;white-space:nowrap;box-shadow: 2px 0 5px rgba(0,0,0,0.02);">${row.name}</td>
                  ${Array(31).fill(0).map((_,i) => {
                    const d = i + 1;
                    const today = 19;
                    let content = '';
                    let shouldCheck = false;
                    if (row.type === 'daily') shouldCheck = (d % 7 !== 1);
                    else if (row.type === 'weekly') shouldCheck = (d % 7 === 6);
                    else if (row.type === 'monthly') shouldCheck = (d === 5);
                    
                    if (shouldCheck) {
                      if (d < today) {
                        if (d === 16 && row.name.includes('CCP-2B')) content = `<div style="width:14px;height:14px;border-radius:50%;background:var(--color-danger);margin:0 auto;" title="미작성"></div>`;
                        else content = `<div style="width:14px;height:14px;border-radius:50%;background:var(--color-success);margin:0 auto;" title="작성/결재완료"></div>`;
                      } else if (d === today) {
                        if (row.name.includes('생산') || row.name.includes('위생')) content = `<div style="width:14px;height:14px;border-radius:50%;background:var(--color-success);margin:0 auto;" title="제출됨"></div>`;
                        else if (row.name.includes('CCP')) content = `<div style="width:14px;height:14px;border-radius:50%;background:var(--color-warning);margin:0 auto;" title="결재대기"></div>`;
                        else content = `<div style="width:14px;height:14px;border-radius:50%;border:2px solid var(--color-danger);background:transparent;margin:0 auto;" title="작성필요"></div>`;
                      } else {
                        content = `<div style="width:12px;height:12px;border-radius:50%;border:1px dashed var(--border-default);margin:0 auto;" title="예정"></div>`;
                      }
                    }
                    return `<td style="border-bottom:1px solid var(--border-subtle);background:${d===today?'rgba(0,212,170,0.05)':'transparent'};">${content}</td>`;
                  }).join('')}
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <!-- 메인 그리드 -->
      <div class="grid-2-1" style="align-items:start;">
        <!-- 좌측 -->
        <div style="display:flex;flex-direction:column;gap:1rem;">

          <!-- CCP 현황 -->
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">⚠️ 오늘의 CCP 점검 현황</div>
                <div class="card-subtitle">기록 대기 중인 모니터링 단위</div>
              </div>
              <button class="btn btn-secondary btn-sm" onclick="App.navigate('ccp-monitoring')">입력 이동</button>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0.75rem;">
              ${HACCP_DATA.ccpPoints.map(ccp => {
                const todayLogs = HACCP_DATA.ccpLogs.filter(l => l.ccpId === ccp.id && l.date.includes(new Date().toISOString().split('T')[0]));
                // Fallback to specific date for demo
                const demoLogs = todayLogs.length > 0 ? todayLogs : HACCP_DATA.ccpLogs.filter(l => l.ccpId === ccp.id && l.date === '2026-03-18');
                const pending = demoLogs.filter(l => l.status === 'pending').length;
                const total = demoLogs.length;
                const isComplete = total > 0 && pending === 0;

                return `
                <div class="ccp-card ${pending > 0 ? 'near-limit' : (isComplete ? 'in-range' : '')}" style="${total===0?'opacity:0.6;background:transparent;border:1px dashed var(--border-default);':''}">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.75rem;">
                    <div>
                      <div style="font-size:0.75rem;color:var(--text-muted);font-weight:600;">${ccp.id}</div>
                      <div style="font-size:0.9rem;font-weight:800;margin-top:0.2rem;">${ccp.name}</div>
                    </div>
                    <span class="badge ${pending > 0 ? 'badge-warning' : (isComplete ? 'badge-success' : 'badge-neutral')} badge-dot">
                      ${pending > 0 ? '입력대기' : (isComplete ? '완료' : '일정없음')}
                    </span>
                  </div>
                  <div style="display:flex;align-items:flex-end;gap:0.3rem;">
                    <span style="font-size:1.6rem;font-weight:900;color:${pending > 0 ? 'var(--color-warning)' : 'var(--color-success)'};">${pending > 0 ? pending : total}</span>
                    <span style="font-size:0.8rem;color:var(--text-muted);margin-bottom:0.3rem;">/ ${total} 건</span>
                  </div>
                  <div style="font-size:0.7rem;color:var(--text-muted);margin-top:0.25rem;">
                    ${pending > 0 ? `<span style="color:var(--color-warning);">⚠️ ${pending}건 기록 필요</span>` : (isComplete ? '✓ 모든 기록 완료' : '-')}
                  </div>
                </div>
              `}).join('')}
            </div>
          </div>

          <!-- 수불 요약 -->
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">📦 재고 현황 요약</div>
                <div class="card-subtitle">원료/부자재/완제품 현재고</div>
              </div>
              <div class="d-flex gap-1">
                <button class="btn btn-secondary btn-sm" onclick="App.navigate('raw-materials')">원료</button>
                <button class="btn btn-secondary btn-sm" onclick="App.navigate('finished-goods')">완제품</button>
              </div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
              <div>
                <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);margin-bottom:0.6rem;text-transform:uppercase;letter-spacing:0.05em;">원료 재고</div>
                ${HACCP_DATA.currentStock.raw.map(r => {
                  const pct = Math.min(100, (r.balance / (r.minStock * 5)) * 100);
                  const isLow = r.balance <= r.minStock * 1.5;
                  const cls = isLow ? 'warning' : 'primary';
                  return `
                  <div class="progress-bar-wrap">
                    <div class="progress-label">
                      <span>${r.name}</span>
                      <span style="color:${isLow ? 'var(--color-warning)' : 'var(--text-secondary)'};">${r.balance.toLocaleString()} ${r.unit}</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill ${cls}" style="width:${pct}%"></div></div>
                  </div>`;
                }).join('')}
              </div>
              <div>
                <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);margin-bottom:0.6rem;text-transform:uppercase;letter-spacing:0.05em;">완제품 재고</div>
                ${HACCP_DATA.currentStock.finished.map(f => {
                  const pct = Math.min(100, (f.balance / 8000) * 100);
                  return `
                  <div class="progress-bar-wrap">
                    <div class="progress-label">
                      <span>${f.name.replace('유산균','').replace('음료','').trim()}</span>
                      <span>${f.balance.toLocaleString()}개</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill primary" style="width:${pct}%"></div></div>
                  </div>`;
                }).join('')}
                <div style="margin-top:0.75rem;">
                  <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);margin-bottom:0.5rem;">소비기한 임박</div>
                  ${HACCP_DATA.currentStock.raw.filter(r => r.expiryAlert).map(r => `
                  <div style="display:flex;justify-content:space-between;align-items:center;padding:0.3rem 0;border-bottom:1px solid var(--border-subtle);">
                    <span style="font-size:0.75rem;">${r.name}</span>
                    <span class="badge badge-warning">${r.expiryAlert}</span>
                  </div>`).join('')}
                </div>
              </div>
            </div>
          </div>


        </div>

        <!-- 우측 -->
        <div style="display:flex;flex-direction:column;gap:1rem;">

          <!-- 알림 -->
          <div class="card">
            <div class="card-header">
              <div class="card-title">🔔 미처리 알림</div>
              <button class="btn btn-secondary btn-sm" onclick="App.navigate('alerts')">모두보기</button>
            </div>
            ${HACCP_DATA.alerts.map(a => `
            <div class="alert-item a-${a.type}" style="${a.isRead ? 'opacity:0.5;' : ''}">
              <div class="alert-item-icon">
                ${a.type === 'danger' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
                : a.type === 'warning' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
                : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="8"/><line x1="12" y1="12" x2="12" y2="16"/></svg>'}
              </div>
              <div class="alert-item-body">
                <div class="alert-item-title">${a.title}</div>
                <div class="alert-item-desc">${a.desc}</div>
                <div class="alert-item-time">${a.time}</div>
              </div>
              ${!a.isRead ? '<span class="badge badge-danger" style="font-size:0.6rem;">NEW</span>' : ''}
            </div>`).join('')}
          </div>

          <!-- 기준서 기반 필수 점검 누락 방지 -->
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">📅 기준서 정기 점검 (누락 방지)</div>
                <div class="card-subtitle">제조·수불·위생 주기적 점검 사항</div>
              </div>
              <button class="btn btn-secondary btn-sm" onclick="App.showToast('info','일정 열기','상세 캘린더 화면이 뜹니다.')">전체</button>
            </div>
            
            ${[
              { arr: HACCP_DATA.periodicTasks.filter(t=>t.type==='daily'),  label: "일일 점검" },
              { arr: HACCP_DATA.periodicTasks.filter(t=>t.type==='weekly'), label: "주간 점검" },
              { arr: HACCP_DATA.periodicTasks.filter(t=>t.type==='monthly' || t.type==='yearly'), label: "월간 / 소모성(연간) 점검" },
            ].map(group => `
              <div class="dashboard-task-group">
                <div class="dashboard-task-group-title">${group.label}</div>
                <div class="dashboard-task-list">
                ${group.arr.map(t => `
                  <div class="dashboard-task-item t-${t.status}">
                    <!-- 체크박스 (완료/미완료 토글) -->
                    <div class="dashboard-task-checkbox ${t.status==='completed'?'checked':''}" onclick="DashboardPage.completeTask('${t.id}')" title="클릭하여 완료 처리">
                      ${t.status==='completed'?'<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" style="width:12px;height:12px;"><polyline points="20 6 9 17 4 12"/></svg>':''}
                    </div>
                    <!-- 텍스트 영역 (해당 문서/페이지로 이동) -->
                    <div class="dashboard-task-content" onclick="App.navigate('${t.link}')" title="클릭하여 해당 문서 작성화면으로 이동">
                      <div class="dashboard-task-title-row">
                        <span class="dashboard-task-category">${t.category}</span>
                        <span>${t.title}</span>
                        <span style="font-size:0.65rem;opacity:0.5;margin-left:auto;">↗</span>
                      </div>
                      ${t.status!=='completed' ? `
                      <div class="dashboard-task-meta-row">
                        <span class="dashboard-task-deadline ${t.status==='danger'?'d-danger':(t.status==='warning'?'d-warning':'')}">기한: ${t.deadline}</span>
                        ${t.status==='danger' ? '<span class="badge badge-danger" style="font-size:0.55rem;padding:0.1rem 0.3rem;">긴급</span>' : ''}
                      </div>`:''}
                    </div>
                  </div>
                `).join('')}
                </div>
              </div>
            `).join('')}
          </div>

          <!-- 오늘 생산 현황 -->
          <div class="card">
            <div class="card-header">
              <div class="card-title">🏭 오늘의 생산</div>
              <span class="badge badge-success badge-dot">진행중</span>
            </div>
            ${HACCP_DATA.productionLogs.filter(p => p.date === latestDate).map(p => {
              const aqty = p.actualQty || p.productionQty || 0;
              const dqty = p.defectQty || 0;
              const yld  = aqty > 0 ? (((aqty - dqty) / aqty) * 100).toFixed(1) : '-';
              return `
            <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);margin-bottom:0.5rem;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.5rem;">
                <div>
                  <div style="font-size:0.85rem;font-weight:700;">${p.product}</div>
                  <div style="font-size:0.72rem;color:var(--text-muted);">LOT: ${p.lot||'-'} · ${p.line||''} ${p.worker||''}</div>
                </div>
                <span class="badge badge-success">완료</span>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;text-align:center;">
                <div><div style="font-size:1rem;font-weight:800;color:var(--brand-primary);">${aqty.toLocaleString()}</div><div style="font-size:0.65rem;color:var(--text-muted);">생산량(${p.unit||''})</div></div>
                <div><div style="font-size:1rem;font-weight:800;color:var(--color-danger);">${dqty}</div><div style="font-size:0.65rem;color:var(--text-muted);">불량</div></div>
                <div><div style="font-size:1rem;font-weight:800;color:var(--color-success);">${yld !== '-' ? yld + '%' : '-'}</div><div style="font-size:0.65rem;color:var(--text-muted);">수율</div></div>
              </div>
            </div>`;
            }).join('')}
          </div>
        </div>
      </div>
    </div>`;
  },

  completeTask(taskId) {
    const task = HACCP_DATA.periodicTasks.find(t => t.id === taskId);
    if (!task) return;
    
    if (task.status === 'completed') {
      task.status = 'pending'; // or maybe restore to its proper logical state, but 'pending' is fine for toggle
    } else {
      task.status = 'completed';
    }
    
    // 다시 렌더링
    const container = document.getElementById('pageContainer');
    if (container) {
      container.innerHTML = this.render();
    }
    
    if (task.status === 'completed') {
      App.showToast('success', '점검 완료', `[${task.category}] ${task.title} 항목을 확인했습니다.`);
    }
  }
};
