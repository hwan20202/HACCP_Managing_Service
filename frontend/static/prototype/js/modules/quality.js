// =============================================
// BIODOT HACCP - 품질검사 / 위생관리 / 교육훈련 / 알림 모듈
// =============================================

// ===== 자가품질검사 =====
const QualityPage = {
  render() {
    const checks = HACCP_DATA.qualityChecks || [];
    const today  = new Date().toLocaleDateString('ko-KR');
    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">🔬 자가품질검사</h1>
          <p class="page-desc">LOT별 품질 검사 기록 및 결과 관리 · ${today}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-primary" onclick="QualityPage.openModal()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            검사 결과 등록
          </button>
        </div>
      </div>

      <!-- KPI 요약 -->
      <div class="kpi-grid" style="margin-bottom:1rem;">
        <div class="kpi-card primary">
          <div class="kpi-value">${checks.length}</div>
          <div class="kpi-label">총 검사 건수</div>
        </div>
        <div class="kpi-card success">
          <div class="kpi-value">${checks.filter(c=>c.status==='pass').length}</div>
          <div class="kpi-label">적합</div>
        </div>
        <div class="kpi-card danger">
          <div class="kpi-value">${checks.filter(c=>c.status==='fail').length}</div>
          <div class="kpi-label">부적합</div>
        </div>
        <div class="kpi-card warning">
          <div class="kpi-value">${checks.filter(c=>c.status==='pending').length}</div>
          <div class="kpi-label">검사 대기</div>
        </div>
      </div>

      <!-- 검사 내역 테이블 -->
      <div class="card" style="padding:0;">
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>날짜</th><th>제품명</th><th>LOT번호</th>
                <th>검사항목</th><th>기준</th><th>결과값</th>
                <th>판정</th><th>검사자</th><th>작업</th>
              </tr>
            </thead>
            <tbody>
              ${checks.length === 0
                ? '<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--text-muted);">검사 내역이 없습니다.</td></tr>'
                : checks.map(c => `
                <tr>
                  <td class="no-wrap">${c.date}</td>
                  <td style="font-weight:600;">${c.product}</td>
                  <td><code style="font-size:0.72rem;color:var(--brand-primary);">${c.lot}</code></td>
                  <td>${c.testItem}</td>
                  <td style="font-size:0.75rem;color:var(--text-muted);">${c.standard}</td>
                  <td style="font-weight:700;">${c.result||'<span style="color:var(--text-muted);">미입력</span>'}</td>
                  <td>
                    <span class="badge ${c.status==='pass'?'badge-success':c.status==='fail'?'badge-danger':'badge-neutral'} badge-dot">
                      ${c.status==='pass'?'적합':c.status==='fail'?'부적합':'대기'}
                    </span>
                  </td>
                  <td>${c.tester||'-'}</td>
                   <td style="display:flex;gap:0.3rem;flex-wrap:wrap;">
                     <button class="btn btn-secondary btn-sm" onclick="QualityPage.editResult('${c.id}')">결과 입력</button>
                     <button class="btn btn-sm ${c.status === 'pass' ? 'btn-cert' : 'btn-cert-disabled'}"
                       onclick="${c.status === 'pass' ? `QualityPage.issueCertificate('${c.lot}')` : ''}"
                       ${c.status !== 'pass' ? 'disabled title="적합 판정 후 발행 가능"' : 'title="성적서 발행"'}>
                       📄 성적서
                     </button>
                   </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>`;
  },

  openModal() {
    const today = new Date().toISOString().split('T')[0];
    App.showModal('자가품질검사 결과 등록', `
      <div class="grid-2">
        <div class="form-group">
          <label class="form-label">검사일 *</label>
          <input type="date" class="form-control" id="qcDate" value="${today}" required/>
        </div>
        <div class="form-group">
          <label class="form-label">LOT번호 *</label>
          <input type="text" class="form-control" id="qcLot" placeholder="예) BD001-260320" required/>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">제품 선택 *</label>
        <select class="form-control" id="qcProduct" required>
          <option value="">-- 선택 --</option>
          ${HACCP_DATA.products.map(p=>`<option value="${p.id}">${p.name}</option>`).join('')}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">검사항목 *</label>
        <select class="form-control" id="qcItem">
          <option>일반세균수</option><option>대장균군</option>
          <option>수분함량</option><option>외관검사</option>
          <option>중금속(납)</option><option>잔류농약</option>
        </select>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label class="form-label">검사결과 *</label>
          <input type="text" class="form-control" id="qcResult" placeholder="예) 1.0×10² CFU/g, 음성, 5.2%" required/>
        </div>
        <div class="form-group">
          <label class="form-label">판정</label>
          <select class="form-control" id="qcStatus">
            <option value="pass">적합</option>
            <option value="fail">부적합</option>
            <option value="pending">대기</option>
          </select>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">검사자 *</label>
        <select class="form-control" id="qcTester" required>
          <option value="">-- 선택 --</option>
          ${HACCP_DATA.employees.map(e=>`<option>${e.name}</option>`).join('')}
        </select>
      </div>`,
      [
        { text: '취소', class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '등록', class: 'btn-primary', action: 'QualityPage.submitResult()' }
      ]
    );
  },

  submitResult() {
    const date    = document.getElementById('qcDate')?.value;
    const lot     = document.getElementById('qcLot')?.value;
    const prodId  = document.getElementById('qcProduct')?.value;
    const item    = document.getElementById('qcItem')?.value;
    const result  = document.getElementById('qcResult')?.value;
    const status  = document.getElementById('qcStatus')?.value;
    const tester  = document.getElementById('qcTester')?.value;

    if (!date||!lot||!prodId||!result||!tester) {
      App.showToast('error','입력오류','필수 항목을 모두 입력해주세요.'); return;
    }
    const prod = HACCP_DATA.products.find(p=>p.id===prodId);
    const standard = prod?.qualityStandards.find(s=>s.item===item)?.standard || '-';

    HACCP_DATA.qualityChecks.unshift({
      id: 'QC'+Date.now(), date, lot,
      product: prod?.name||prodId, productId: prodId,
      testItem: item, standard, result, status, tester
    });
    App.closeModal();
    App.showToast('success','등록완료','검사 결과가 등록되었습니다.');
    App.navigate('quality-check');
  },

  editResult(id) {
    const check = HACCP_DATA.qualityChecks.find(c=>c.id===id);
    if (!check) return;
    App.showModal(`검사 결과 수정 - ${check.testItem}`, `
      <div class="form-group">
        <label class="form-label">결과값</label>
        <input type="text" class="form-control" id="editQcResult" value="${check.result||''}" placeholder="결과값 입력"/>
      </div>
      <div class="form-group">
        <label class="form-label">판정</label>
        <select class="form-control" id="editQcStatus">
          <option value="pass" ${check.status==='pass'?'selected':''}>적합</option>
          <option value="fail" ${check.status==='fail'?'selected':''}>부적합</option>
          <option value="pending" ${check.status==='pending'?'selected':''}>대기</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">검사자</label>
        <select class="form-control" id="editQcTester">
          ${HACCP_DATA.employees.map(e=>`<option ${e.name===check.tester?'selected':''}>${e.name}</option>`).join('')}
        </select>
      </div>`,
      [
        { text: '취소', class:'btn-secondary', action:'App.closeModal()' },
        { text: '저장', class:'btn-primary', action:`QualityPage.saveEdit('${id}')` }
      ]
    );
  },

  saveEdit(id) {
    const check = HACCP_DATA.qualityChecks.find(c=>c.id===id);
    if (!check) return;
    check.result = document.getElementById('editQcResult')?.value||'';
    check.status = document.getElementById('editQcStatus')?.value||'pending';
    check.tester = document.getElementById('editQcTester')?.value||'';
    App.closeModal();
    App.showToast('success','수정완료','검사 결과가 수정되었습니다.');
    App.navigate('quality-check');
  },

  // ===== 성적서 발행 =====
  issueCertificate(lot) {
    // 해당 LOT의 완료된 검사 결과 집계
    const checks = HACCP_DATA.qualityChecks.filter(c => c.lot === lot && c.status !== 'pending');
    if (checks.length === 0) {
      App.showToast('warning', '성적서 발행 불가', '검사 완료된 항목이 없습니다.'); return;
    }

    const first   = checks[0];
    const product = HACCP_DATA.products.find(p => p.id === first.productId);
    const company = HACCP_DATA.company;

    // 성적서 번호 생성: CERT-YYYYMMDD-LOT축약
    const now     = new Date();
    const certNo  = `CERT-${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}-${lot.replace(/[^A-Z0-9]/gi,'').slice(0,8).toUpperCase()}`;
    const issueDate = now.toLocaleDateString('ko-KR', { year:'numeric', month:'2-digit', day:'2-digit' });

    // 전체 적합 여부
    const allPass   = checks.every(c => c.status === 'pass');
    const hasPass   = checks.some(c => c.status === 'pass');
    const overallLabel = allPass ? '적합' : hasPass ? '일부 부적합' : '부적합';
    const overallColor = allPass ? '#16a34a' : '#dc2626';

    // 검사자 목록 (중복 제거)
    const testers = [...new Set(checks.map(c => c.tester).filter(Boolean))].join(', ');

    // qualityStandards에서 검사방법 보완
    const getMethod = (item) => {
      return product?.qualityStandards?.find(s => s.item === item)?.method || '-';
    };

    const certHtml = `
      <div id="certPrintArea" class="cert-wrap">

        <!-- 성적서 헤더 -->
        <div class="cert-header">
          <div class="cert-logo-area">
            <div class="cert-logo-icon">
              <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" width="36" height="36">
                <circle cx="20" cy="20" r="18" fill="url(#cLogoGrad)"/>
                <path d="M12 20 C12 14, 20 10, 20 10 C20 10, 28 14, 28 20 C28 26, 20 30, 20 30 C20 30, 12 26, 12 20Z" fill="white" fill-opacity="0.9"/>
                <path d="M16 20 C16 17, 20 14.5, 20 14.5 C20 14.5, 24 17, 24 20 C24 23, 20 25.5, 20 25.5 C20 25.5, 16 23, 16 20Z" fill="url(#cLogoGrad)"/>
                <defs>
                  <linearGradient id="cLogoGrad" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
                    <stop offset="0%" stop-color="#00d4aa"/>
                    <stop offset="100%" stop-color="#0066ff"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div>
              <div class="cert-company">${company.name}</div>
              <div class="cert-company-sub">HACCP 인증 식품안전관리 사업장</div>
            </div>
          </div>
          <div class="cert-title-block">
            <div class="cert-title">자가품질검사 성적서</div>
            <div class="cert-title-en">Certificate of Analysis</div>
          </div>
        </div>

        <!-- 기본 정보 테이블 -->
        <table class="cert-info-table">
          <tr>
            <th>성적서 번호</th><td><strong>${certNo}</strong></td>
            <th>발행일자</th><td>${issueDate}</td>
          </tr>
          <tr>
            <th>제 품 명</th><td>${first.product}</td>
            <th>제품코드</th><td>${product?.code || '-'}</td>
          </tr>
          <tr>
            <th>LOT 번호</th><td><strong>${lot}</strong></td>
            <th>검사일자</th><td>${first.date}</td>
          </tr>
          <tr>
            <th>검 사 자</th><td>${testers}</td>
            <th>HACCP 인증번호</th><td>${company.haccpNo}</td>
          </tr>
        </table>

        <!-- 검사 결과 테이블 -->
        <div class="cert-section-title">■ 검사 결과</div>
        <table class="cert-result-table">
          <thead>
            <tr>
              <th>검사항목</th>
              <th>기준 (규격)</th>
              <th>검사방법</th>
              <th>검사결과</th>
              <th>판정</th>
            </tr>
          </thead>
          <tbody>
            ${checks.map(c => `
            <tr>
              <td>${c.testItem}</td>
              <td>${c.standard}</td>
              <td>${c.method || getMethod(c.testItem)}</td>
              <td><strong>${c.result || '-'}</strong></td>
              <td class="cert-judge ${c.status === 'pass' ? 'cert-pass' : 'cert-fail'}">
                ${c.status === 'pass' ? '✓ 적합' : '✗ 부적합'}
              </td>
            </tr>`).join('')}
          </tbody>
        </table>

        <!-- 종합판정 -->
        <div class="cert-overall" style="border-color:${overallColor};color:${overallColor};">
          종합 판정 : <strong>${overallLabel}</strong>
        </div>

        <!-- 서명란 -->
        <div class="cert-sign-area">
          <div class="cert-sign-box">
            <div class="cert-sign-label">검사자</div>
            <div class="cert-sign-name">${testers}</div>
            <div class="cert-sign-line">(서명)</div>
          ${thead}
          <tbody>${microChecks.length>0 ? microChecks.map(toRow).join('') : '<tr><td colspan="4" style="text-align:center;color:#aaa;padding:8px;">-</td></tr>'}</tbody>
        </table>

        <div class="cert-section-header">Packing and Storage</div>
        <table class="cert-info-table">
          <tr><th>Storage</th><td>Store at room temperature, avoid direct sunlight and high temperature and humidity places.</td></tr>
          <tr><th>Shelf Life</th><td>${product?.shelfDays ? (product.shelfDays/365)+' years' : '-'}</td></tr>
        </table>

        <div class="cert-auth-area">
          <div class="cert-auth-label">Authorized by:</div>
          <div class="cert-auth-name">${authorizedName}</div>
          <div class="cert-auth-role">Authorized Representative</div>
          <div class="cert-auth-company">${company.name}</div>
        </div>

        <div class="cert-footer">
          <div>${company.name} · ${company.address}</div>
          <div>© ${now.getFullYear()} ${company.name}. All Rights Reserved.</div>
        </div>
      </div>`;

    App.showModal(
      `📄 CERTIFICATE of ANALYSIS — ${lot}`,
      certHtml,
      [
        { text: '닫기',               class: 'btn-secondary', action: 'App.closeModal()' },
        { text: '🖨️ 인쇄 / PDF 저장', class: 'btn-primary',   action: 'QualityPage.printCert()' },
      ]
    );
  },

  printCert() {
    const area = document.getElementById('certPrintArea');
    if (!area) return;
    const printWin = window.open('', '_blank', 'width=860,height=750');
    const CSS = `
      *{box-sizing:border-box;margin:0;padding:0;}
      body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:11.5px;color:#111;background:#fff;padding:28px 36px;}
      .cert-wrap{max-width:760px;margin:0 auto;}
      .cert-header{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:18px;padding-bottom:10px;border-bottom:3px solid #111;}
      .cert-title{font-size:23px;font-weight:800;letter-spacing:0.5px;color:#111;}
      .cert-issue-date{font-size:12px;color:#555;}
      .cert-section-header{font-size:11.5px;font-weight:700;background:#111;color:#fff;padding:5px 10px;margin:14px 0 0;}
      .cert-info-table{width:100%;border-collapse:collapse;font-size:11px;}
      .cert-info-table th,.cert-info-table td{border:1px solid #bbb;padding:5px 8px;}
      .cert-info-table th{background:#f0f0f0;font-weight:600;white-space:nowrap;width:18%;}
      .cert-result-table{width:100%;border-collapse:collapse;font-size:11px;}
      .cert-result-table thead tr{background:#111;color:#fff;}
      .cert-result-table th{padding:6px 8px;font-weight:600;text-align:left;border:1px solid #444;}
      .cert-result-table td{border:1px solid #bbb;padding:5px 8px;}
      .cert-result-table tbody tr:nth-child(even){background:#f9f9f9;}
      .cert-judge{font-weight:700;}
      .cert-pass{color:#16a34a;}
      .cert-fail{color:#dc2626;}
      .cert-auth-area{margin-top:22px;padding-bottom:6px;}
      .cert-auth-label{font-size:11px;color:#333;margin-bottom:6px;}
      .cert-auth-name{font-size:17px;font-weight:700;margin-bottom:2px;}
      .cert-auth-role{font-size:11px;color:#555;}
      .cert-auth-company{font-size:12px;font-weight:600;margin-top:4px;}
      .cert-footer{font-size:9px;color:#888;margin-top:18px;border-top:1px solid #ddd;padding-top:7px;line-height:1.9;}
      @media print{
        body{padding:10px 15px;}
        @page{margin:8mm;size:A4;}
      }
    `;
    printWin.document.write(`<!DOCTYPE html><html lang="ko"><head>
      <meta charset="UTF-8"/>
      <title>Certificate of Analysis</title>
      <style>${CSS}</style>
    </head><body>${area.outerHTML}</body></html>`);
    printWin.document.close();
    printWin.focus();
    setTimeout(() => { printWin.print(); }, 400);
  },
};

// ===== 위생 관리 일지 =====
const SanitationPage = {
  render() {
    const today = new Date().toLocaleDateString('ko-KR');
    const items = [
      { id:'S01', zone:'작업장 전체', task:'바닥 청소·소독', freq:'매일', lastDate:'2026-03-20', status:'ok' },
      { id:'S02', zone:'건조기',      task:'내부 세척·소독', freq:'작업 후', lastDate:'2026-03-20', status:'ok' },
      { id:'S03', zone:'금속검출기',  task:'외부 청소 및 감도 확인', freq:'매일', lastDate:'2026-03-20', status:'ok' },
      { id:'S04', zone:'체망/이물제거기', task:'체망 청소·파손확인', freq:'작업 중', lastDate:'2026-03-20', status:'ok' },
      { id:'S05', zone:'작업 도구',   task:'세척·열탕소독', freq:'매일', lastDate:'2026-03-19', status:'warning' },
      { id:'S06', zone:'화장실/탈의실', task:'청소·소독', freq:'매일', lastDate:'2026-03-20', status:'ok' },
      { id:'S07', zone:'창고',        task:'정리정돈·청소', freq:'주 1회', lastDate:'2026-03-15', status:'ok' },
      { id:'S08', zone:'배수로',      task:'이물 제거·소독', freq:'매일', lastDate:'2026-03-20', status:'ok' },
    ];
    const okCount = items.filter(i=>i.status==='ok').length;

    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">🧹 위생 관리 일지</h1>
          <p class="page-desc">작업장 청소·소독 이행 현황 · ${today}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-primary" onclick="SanitationPage.recordAll()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            오늘 일괄 이행 등록
          </button>
        </div>
      </div>

      <div class="kpi-grid" style="margin-bottom:1rem;">
        <div class="kpi-card primary"><div class="kpi-value">${items.length}</div><div class="kpi-label">총 점검 항목</div></div>
        <div class="kpi-card success"><div class="kpi-value">${okCount}</div><div class="kpi-label">이행 완료</div></div>
        <div class="kpi-card ${items.length-okCount>0?'warning':'success'}"><div class="kpi-value">${items.length-okCount}</div><div class="kpi-label">미이행/주의</div></div>
        <div class="kpi-card info"><div class="kpi-value">${Math.round(okCount/items.length*100)}%</div><div class="kpi-label">이행률</div></div>
      </div>

      <div class="card" style="padding:0;">
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr><th>구역</th><th>점검 항목</th><th>주기</th><th>최종 이행일</th><th>상태</th><th>작업</th></tr>
            </thead>
            <tbody>
              ${items.map(item => `
              <tr>
                <td style="font-weight:600;">${item.zone}</td>
                <td>${item.task}</td>
                <td><span class="badge badge-neutral">${item.freq}</span></td>
                <td class="no-wrap">${item.lastDate}</td>
                <td><span class="badge ${item.status==='ok'?'badge-success':'badge-warning'} badge-dot">${item.status==='ok'?'이행':'미이행'}</span></td>
                <td>
                  <button class="btn btn-secondary btn-sm" onclick="SanitationPage.record('${item.id}','${item.zone}')">이행 등록</button>
                </td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>`;
  },

  record(id, zone) {
    App.showToast('success', '위생 이행 등록', `[${zone}] 오늘 날짜로 이행 기록되었습니다.`);
  },

  recordAll() {
    App.showToast('success', '일괄 이행 등록', `오늘(${new Date().toLocaleDateString('ko-KR')}) 전체 위생 점검 항목이 이행 완료로 기록되었습니다.`);
  }
};

// ===== 교육훈련 관리 =====
const TrainingPage = {
  render() {
    const today = new Date().toLocaleDateString('ko-KR');
    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">📚 교육 훈련 관리</h1>
          <p class="page-desc">HACCP 및 위생 교육 이력 관리 · ${today}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-primary" onclick="TrainingPage.openModal()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            교육 등록
          </button>
        </div>
      </div>

      <!-- 직원별 교육 현황 -->
      <div class="card" style="margin-bottom:1rem;">
        <div class="card-header">
          <div class="card-title">👥 직원별 교육 현황</div>
        </div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr><th>직원명</th><th>부서/역할</th><th>최근 교육일</th><th>다음 예정</th><th>보건증 만료</th><th>상태</th></tr>
            </thead>
            <tbody>
              ${HACCP_DATA.employees.map(e => {
                const expiry = new Date(e.healthCard);
                const today  = new Date('2026-03-20');
                const daysLeft = Math.ceil((expiry - today) / 86400000);
                const cardStatus = daysLeft < 30 ? 'danger' : daysLeft < 90 ? 'warning' : 'success';
                return `
                <tr>
                  <td>
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                      <div style="width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,var(--brand-primary),var(--brand-secondary));display:flex;align-items:center;justify-content:center;font-size:0.8rem;font-weight:700;color:white;">${e.name[0]}</div>
                      <span style="font-weight:600;">${e.name}</span>
                    </div>
                  </td>
                  <td>${e.role}</td>
                  <td>${e.education}</td>
                  <td>2026-12-17</td>
                  <td><span class="badge badge-${cardStatus}">${e.healthCard} (D-${daysLeft})</span></td>
                  <td><span class="badge badge-success badge-dot">이수</span></td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <!-- 교육 이력 -->
      <div class="card">
        <div class="card-header"><div class="card-title">📋 교육 이력</div></div>
        ${[
          { date:'2025-12-17', type:'HACCP 정기교육 (보수)',     trainees:'전직원',   hours:8, instructor:'외부강사(식품안전관리원)', note:'연간 의무교육' },
          { date:'2025-05-22', type:'CCP 담당자 집중교육',       trainees:'김선현·최종순', hours:4, instructor:'상상분',        note:'CCP 측정·기록 실습' },
          { date:'2026-03-05', type:'월례 위생교육',             trainees:'전직원',   hours:1, instructor:'상상분',        note:'3월 위생점검 교육' },
          { date:'2026-02-05', type:'월례 위생교육',             trainees:'전직원',   hours:1, instructor:'상상분',        note:'2월 위생점검 교육' },
        ].map(t => `
        <div style="display:flex;align-items:center;gap:1rem;padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);margin-bottom:0.5rem;">
          <div style="width:52px;height:52px;background:rgba(0,212,170,0.1);border-radius:var(--radius-md);display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0;">
            <span style="font-size:0.62rem;color:var(--text-muted);">${t.date.slice(0,7)}</span>
            <span style="font-size:1rem;font-weight:800;color:var(--brand-primary);">${t.date.slice(8)}</span>
          </div>
          <div style="flex:1;">
            <div style="font-weight:700;margin-bottom:0.2rem;">${t.type}</div>
            <div style="font-size:0.75rem;color:var(--text-muted);">${t.trainees} · ${t.hours}시간 · ${t.instructor}</div>
            <div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.1rem;">${t.note}</div>
          </div>
          <span class="badge badge-success badge-dot">완료</span>
        </div>`).join('')}
      </div>
    </div>`;
  },

  openModal() {
    const today = new Date().toISOString().split('T')[0];
    App.showModal('교육 등록', `
      <div class="grid-2">
        <div class="form-group">
          <label class="form-label">교육일 *</label>
          <input type="date" class="form-control" value="${today}" id="trDate" required/>
        </div>
        <div class="form-group">
          <label class="form-label">교육시간 *</label>
          <input type="number" class="form-control" id="trHours" placeholder="시간" min="0.5" step="0.5" required/>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">교육 구분 *</label>
        <select class="form-control" id="trType">
          <option>HACCP 정기교육</option><option>CCP 담당자 교육</option>
          <option>월례 위생교육</option><option>신규직원 교육</option>
          <option>식품위생법 교육</option><option>기타</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">교육강사</label>
        <input type="text" class="form-control" id="trInstructor" placeholder="강사명 또는 외부기관명"/>
      </div>
      <div class="form-group">
        <label class="form-label">교육 대상자 *</label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);">
          ${HACCP_DATA.employees.map(e=>`
          <label style="display:flex;align-items:center;gap:0.4rem;font-size:0.82rem;cursor:pointer;">
            <input type="checkbox" checked/> ${e.name}
          </label>`).join('')}
        </div>
      </div>`,
      [
        { text:'취소', class:'btn-secondary', action:'App.closeModal()' },
        { text:'등록', class:'btn-primary', action:'App.showToast("success","교육 등록","교육이 기록되었습니다."); App.closeModal();' }
      ]
    );
  }
};

// ===== 알림 센터 =====
const AlertsPage = {
  render() {
    const byType = { danger: [], warning: [], info: [] };
    HACCP_DATA.alerts.forEach(a => byType[a.type]?.push(a));
    const today = new Date().toLocaleDateString('ko-KR');

    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">🔔 알림 센터</h1>
          <p class="page-desc">시스템 전반의 주의사항 및 조치 필요 알림 · ${today}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" onclick="AlertsPage.markAllRead()">모두 읽음 처리</button>
        </div>
      </div>

      ${byType.danger.length > 0 ? `
      <div class="card" style="margin-bottom:1rem;border-color:rgba(239,68,68,0.25);">
        <div class="card-header">
          <div class="card-title" style="color:var(--color-danger);">🚨 긴급 알림</div>
          <span class="badge badge-danger">${byType.danger.length}</span>
        </div>
        ${byType.danger.map(a => this.renderAlertItem(a)).join('')}
      </div>` : ''}

      ${byType.warning.length > 0 ? `
      <div class="card" style="margin-bottom:1rem;border-color:rgba(245,158,11,0.25);">
        <div class="card-header">
          <div class="card-title" style="color:var(--color-warning);">⚠️ 주의 알림</div>
          <span class="badge badge-warning">${byType.warning.length}</span>
        </div>
        ${byType.warning.map(a => this.renderAlertItem(a)).join('')}
      </div>` : ''}

      <div class="card">
        <div class="card-header">
          <div class="card-title">ℹ️ 일반 알림</div>
          <span class="badge badge-neutral">${byType.info.length}</span>
        </div>
        ${byType.info.length === 0
          ? '<div style="text-align:center;padding:1.5rem;color:var(--text-muted);">일반 알림이 없습니다.</div>'
          : byType.info.map(a => this.renderAlertItem(a)).join('')}
      </div>
    </div>`;
  },

  renderAlertItem(a) {
    return `
    <div class="alert-item a-${a.type}" style="${a.isRead?'opacity:0.55;':''}margin-bottom:0.5rem;">
      <div class="alert-item-icon">
        ${a.type==='danger'
          ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
          : a.type==='warning'
          ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
          : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'}
      </div>
      <div class="alert-item-body">
        <div class="alert-item-title">${a.title}</div>
        <div class="alert-item-desc">${a.desc}</div>
        <div class="alert-item-time">${a.date} ${a.time}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:0.3rem;align-items:flex-end;">
        ${!a.isRead ? '<span class="badge badge-danger">NEW</span>' : ''}
        <button class="btn btn-secondary btn-sm" onclick="AlertsPage.handleAlert('${a.id}')">조치</button>
      </div>
    </div>`;
  },

  handleAlert(id) {
    const alert = HACCP_DATA.alerts.find(a=>a.id===id);
    if (alert) alert.isRead = true;
    App.showToast('success','조치 완료','알림 조치 내용이 기록되었습니다.');
    App.navigate('alerts');
  },

  markAllRead() {
    HACCP_DATA.alerts.forEach(a=>a.isRead=true);
    App.showToast('success','읽음 처리','모든 알림을 읽음 처리했습니다.');
    App.navigate('alerts');
  }
};
