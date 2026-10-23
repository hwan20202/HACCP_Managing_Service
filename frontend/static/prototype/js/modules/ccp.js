// =============================================
// BIODOT HACCP - CCP 모니터링 모듈 (기준서 서식 기반)
// CCP-1P: 쇳가루제거 | CCP-2B: 건조 | CCP-3P: 금속검출
// =============================================

const CCPPage = {
  currentTab: 'dashboard',

  ccpDefs: {
    'CCP-1P': {
      id:'CCP-1P', label:'쇳가루 제거', icon:'🧲', color:'#f59e0b',
      hazard:'물리적',
      limits:'자력 8,000가우스(G) 이상 / 자석봉 Φ42.7 / 분말투입량 1kg/min / 3,530rpm 속도고정',
      monitoring:'작업 시작 전·1시간마다·작업종료 후 가우스미터기로 자력 측정 + 자석봉 청소 확인',
      corrective:[
        '자력 미달(8,000G 미만) 시: 즉시 작업 중단 → 자석봉 재조정 → 이탈 제품 재검사 → 기록',
        '기계 고장 시: 즉시 작업 중단 → 수리 후 재가동 (즉각 수리 불가 시 부적합품 보관소 격리)',
        '공통: 문제 발생 시 HACCP팀장 보고 후 조치, 개선조치 후 모니터링 일지 기록 및 HACCP팀장 승인',
      ],
      // type:'gauss' — 가우스미터 측정 전용 폼
      type:'gauss',
      limitGauss: 8000,  // 한계기준: 8,000G 이상
    },
    'CCP-2B': {
      id:'CCP-2B', label:'건조 공정', icon:'🌡️', color:'#6366f1',
      hazard:'생물학적', limits:'건조온도 60~80°C / 건조시간 ≥ 4시간',
      monitoring:'건조 중 1시간마다 온도 측정·기록',
      corrective:['온도 60°C 미만: 즉시 온도 재설정 → 60°C 도달 후 건조시간 재산정','건조기 고장: 작업 중단 → 수리 후 재건조'],
      params:[
        {key:'temp', label:'건조온도(°C)', unit:'°C', critical_min:60, critical_max:80},
        {key:'time', label:'건조시간(hr)', unit:'hr', critical_min:4,  critical_max:null},
      ],
      type:'numeric',
    },
    'CCP-3P': {
      id:'CCP-3P', label:'금속검출기', icon:'⚡', color:'#10b981',
      hazard:'물리적', limits:'Fe ≤ Ø2.0mm 불검출 / SUS ≤ Ø2.5mm 불검출',
      monitoring:'작업 전 Test Piece 감도 확인 + 전수 검사',
      corrective:['Test Piece 감도 불합격: 금속검출기 재조정 후 재확인','금속 검출 시: 해당 제품 격리 → 재통과 검사 2회','금속검출기 고장: 전원 OFF → 서비스 요청 → 당일 생산품 격리'],
      type:'metal',
    },
  },

  // ─── 렌더링 ───────────────────────────────────────────────
  render() {
    const today = new Date('2026-03-21').toLocaleDateString('ko-KR', {month:'long',day:'numeric'});
    const pending = this.getPendingCount();
    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">🎯 CCP 모니터링</h1>
          <p class="page-desc">중요관리점 모니터링 일지 · ${today}</p>
        </div>
        <div class="page-actions">
          ${pending > 0 ? `<span style="background:var(--color-danger);color:#fff;padding:.4rem .8rem;border-radius:999px;font-size:.8rem;margin-right:.5rem;">⚠️ 미작성 ${pending}건</span>` : ''}
          <button class="btn btn-primary" onclick="CCPPage.switchTab('input')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            생산등록+CCP생성
          </button>
        </div>
      </div>
      <div class="tabs">
        <button class="tab-btn ${this.currentTab==='dashboard'?'active':''}" onclick="CCPPage.switchTab('dashboard')">📊 현황판</button>
        <button class="tab-btn ${this.currentTab==='journal'?'active':''}" onclick="CCPPage.switchTab('journal')">📋 일지 목록${pending>0?` <span style="background:var(--color-danger);color:#fff;border-radius:999px;padding:0 6px;font-size:.7rem;">${pending}</span>`:''}</button>
        <button class="tab-btn ${this.currentTab==='input'?'active':''}" onclick="CCPPage.switchTab('input')">✍️ 생산등록</button>
        <button class="tab-btn ${this.currentTab==='log'?'active':''}" onclick="CCPPage.switchTab('log')">🗒️ 이력</button>
      </div>
      <div id="ccpContent">${this.renderContent()}</div>
    </div>`;
  },

  renderContent() {
    switch(this.currentTab) {
      case 'dashboard': return this.renderDashboard();
      case 'journal':   return this.renderJournal();
      case 'input':     return this.renderInput();
      case 'log':       return this.renderLog();
      default:          return '';
    }
  },

  switchTab(tab) {
    this.currentTab = tab;
    const el = document.getElementById('ccpContent');
    if (el) el.innerHTML = this.renderContent();
  },

  // ─── localStorage 헬퍼 ──────────────────────────────────
  getCCPJournals() {
    try { return JSON.parse(localStorage.getItem('ccpJournals') || '[]'); } catch { return []; }
  },
  saveCCPJournals(j) { localStorage.setItem('ccpJournals', JSON.stringify(j)); },
  getPendingCount() { return this.getCCPJournals().filter(j=>j.status==='pending').length; },

  // ─── 생산 등록 시 CCP 일지 3개 자동 생성 ────────────────
  createJournalsForProduction(prod) {
    const journals = this.getCCPJournals();
    const created = [];
    ['CCP-1P','CCP-2B','CCP-3P'].forEach(ccpId => {
      const jId = `${ccpId}-${prod.lot}`;
      if (!journals.find(x=>x.id===jId)) {
        const j = {id:jId, ccpId, lot:prod.lot, productName:prod.productName,
          productionDate:prod.date, qty:prod.qty, unit:prod.unit,
          status:'pending', entries:[], inspector:'', confirmer:'', corrective:'',
          createdAt: new Date().toISOString()};
        journals.push(j);
        created.push(j);
      }
    });
    this.saveCCPJournals(journals);
    return created;
  },

  // ─── 현황판 ─────────────────────────────────────────────
  renderDashboard() {
    const journals = this.getCCPJournals();
    const pending   = journals.filter(j=>j.status==='pending').length;
    const completed = journals.filter(j=>j.status==='completed').length;
    const deviated  = journals.filter(j=>j.status==='deviated').length;
    const todayJ    = journals.filter(j=>j.productionDate==='2026-03-21');

    return `
    <div class="kpi-grid" style="margin-bottom:1.5rem;">
      <div class="kpi-card primary"><div class="kpi-value">3</div><div class="kpi-label">관리 CCP</div></div>
      <div class="kpi-card ${pending>0?'danger':'success'}"><div class="kpi-value">${pending}</div><div class="kpi-label">미작성 일지</div></div>
      <div class="kpi-card success"><div class="kpi-value">${completed}</div><div class="kpi-label">완료 일지</div></div>
      <div class="kpi-card ${deviated>0?'danger':'info'}"><div class="kpi-value">${deviated}</div><div class="kpi-label">이탈 발생</div></div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:1rem;margin-bottom:1.5rem;">
      ${Object.values(this.ccpDefs).map(def=>{
        const jList = journals.filter(j=>j.ccpId===def.id);
        const pend  = jList.filter(j=>j.status==='pending').length;
        const last  = jList.filter(j=>j.status!=='pending').sort((a,b)=>b.productionDate?.localeCompare(a.productionDate))[0];
        return `<div class="card" style="border-left:4px solid ${def.color};">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem;">
            <span style="font-size:1.5rem;">${def.icon}</span>
            <span style="background:${def.color}22;color:${def.color};padding:.2rem .6rem;border-radius:6px;font-size:.8rem;font-weight:700;">${def.id}</span>
          </div>
          <div style="font-weight:700;margin-bottom:.25rem;">${def.label}</div>
          <div style="font-size:.8rem;color:var(--text-secondary);margin-bottom:.5rem;">${def.hazard} 위해 관리</div>
          <div style="font-size:.8rem;background:var(--bg-soft);border-radius:6px;padding:.5rem;margin-bottom:.5rem;">${def.limits}</div>
          <div style="display:flex;justify-content:space-between;font-size:.8rem;">
            <span>${pend>0?`<span style="color:var(--color-danger);font-weight:600;">⚠️ 미작성 ${pend}건</span>`:'<span style="color:var(--color-success);">✅ 미작성 없음</span>'}</span>
            <span style="color:var(--text-secondary);">최근: ${last?last.productionDate.slice(5):'없음'}</span>
          </div>
        </div>`;
      }).join('')}
    </div>
    <div class="card">
      <h3 style="margin:0 0 1rem;font-size:1rem;">📅 오늘(03/21) CCP 현황</h3>
      ${todayJ.length===0?`<p style="color:var(--text-secondary);text-align:center;padding:1.5rem;">오늘 생산이 없습니다. <button class="btn btn-primary btn-sm" onclick="CCPPage.createTestJournals()">🧪 테스트 데이터 생성</button></p>`:`
      <table class="data-table">
        <thead><tr><th>CCP</th><th>제품명(LOT)</th><th>상태</th><th>작업</th></tr></thead>
        <tbody>${todayJ.map(j=>`<tr>
          <td><span style="background:${this.ccpDefs[j.ccpId]?.color+'22'};color:${this.ccpDefs[j.ccpId]?.color};padding:.15rem .5rem;border-radius:5px;font-size:.8rem;">${j.ccpId}</span></td>
          <td>${j.productName}<br><span style="font-size:.75rem;color:var(--text-secondary);">${j.lot}</span></td>
          <td>${this.statusBadge(j.status)}</td>
          <td><button class="btn btn-sm btn-primary" onclick="CCPPage.openJournal('${j.id}')">${j.status==='pending'?'작성':'보기'}</button></td>
        </tr>`).join('')}</tbody>
      </table>`}
    </div>`;
  },

  statusBadge(st) {
    const m={pending:'미작성',completed:'완료',deviated:'이탈발생'};
    const c={pending:'var(--color-danger)',completed:'var(--color-success)',deviated:'var(--color-warning)'};
    return `<span style="background:${c[st]||'#888'}22;color:${c[st]||'#888'};padding:.15rem .5rem;border-radius:5px;font-size:.75rem;font-weight:600;">${m[st]||st}</span>`;
  },

  // ─── 일지 목록 ─────────────────────────────────────────
  renderJournal() {
    const journals = this.getCCPJournals().sort((a,b)=>b.productionDate?.localeCompare(a.productionDate));
    if (journals.length===0) return `<div class="card" style="text-align:center;padding:3rem;">
      <p style="font-size:2rem;">📋</p>
      <p style="color:var(--text-secondary);">생산이 등록되면 CCP 일지가 자동 생성됩니다.</p>
      <button class="btn btn-primary" style="margin-top:1rem;" onclick="CCPPage.createTestJournals()">🧪 테스트 일지 생성</button>
    </div>`;
    return `
    <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:center;">
      <select id="ccpFilterSt" onchange="CCPPage.filterJournal()" style="padding:.4rem .75rem;border:var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-primary);">
        <option value="">전체 상태</option><option value="pending">미작성</option><option value="completed">완료</option><option value="deviated">이탈</option>
      </select>
      <select id="ccpFilterCp" onchange="CCPPage.filterJournal()" style="padding:.4rem .75rem;border:var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-primary);">
        <option value="">전체 CCP</option><option value="CCP-1P">CCP-1P 쇳가루제거</option><option value="CCP-2B">CCP-2B 건조</option><option value="CCP-3P">CCP-3P 금속검출</option>
      </select>
      <button class="btn btn-primary" style="margin-left:auto;" onclick="CCPPage.createTestJournals()">🧪 테스트 생성</button>
    </div>
    <div id="journalList" style="display:flex;flex-direction:column;gap:.75rem;">
      ${journals.map(j=>this.renderJCard(j)).join('')}
    </div>`;
  },

  filterJournal() {
    const st  = document.getElementById('ccpFilterSt')?.value||'';
    const ccp = document.getElementById('ccpFilterCp')?.value||'';
    let j = this.getCCPJournals().sort((a,b)=>b.productionDate?.localeCompare(a.productionDate));
    if(st)  j=j.filter(x=>x.status===st);
    if(ccp) j=j.filter(x=>x.ccpId===ccp);
    const el=document.getElementById('journalList');
    if(el) el.innerHTML=j.map(x=>this.renderJCard(x)).join('');
  },

  renderJCard(j) {
    const def=this.ccpDefs[j.ccpId]||{color:'#888',icon:'📋'};
    const bcolor=j.status==='pending'?'var(--color-danger)':j.status==='deviated'?'var(--color-warning)':'var(--color-success)';
    return `<div class="card" style="border-left:4px solid ${bcolor};">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem;flex-wrap:wrap;">
        <div>
          <div style="display:flex;gap:.5rem;align-items:center;margin-bottom:.25rem;flex-wrap:wrap;">
            <span style="background:${def.color}22;color:${def.color};padding:.15rem .5rem;border-radius:5px;font-size:.8rem;font-weight:700;">${j.ccpId}</span>
            ${this.statusBadge(j.status)}
            <span style="font-size:.8rem;color:var(--text-secondary);">${j.productionDate}</span>
          </div>
          <div style="font-weight:600;">${j.productName}</div>
          <div style="font-size:.8rem;color:var(--text-secondary);">LOT: ${j.lot} | ${j.qty}${j.unit}</div>
        </div>
        <div style="display:flex;gap:.5rem;">
          <button class="btn btn-sm btn-primary" onclick="CCPPage.openJournal('${j.id}')">${j.status==='pending'?'✍️ 작성':'👁 보기'}</button>
          ${j.status==='pending'?`<button class="btn btn-sm" style="background:var(--color-danger);color:#fff;" onclick="CCPPage.deleteJournal('${j.id}')">삭제</button>`:''}
        </div>
      </div>
      ${j.entries?.length?`<div style="margin-top:.5rem;font-size:.8rem;color:var(--text-secondary);">측정: ${j.entries.length}회 | 작성: ${j.inspector||'-'}</div>`:''}
    </div>`;
  },

  deleteJournal(id) {
    if(!confirm('삭제하시겠습니까?')) return;
    this.saveCCPJournals(this.getCCPJournals().filter(j=>j.id!==id));
    this.switchTab('journal');
  },

  // ─── 생산 등록 폼 ──────────────────────────────────────
  renderInput() {
    const prods = (HACCP_DATA.currentStock && HACCP_DATA.currentStock.finished) || [];
    const defs = Object.values(this.ccpDefs);
    return `<div class="card">
      <h3 style="margin:0 0 1.25rem;font-size:1rem;">🏭 생산 등록 + CCP 일지 자동 생성</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;">
        <div><label class="form-label">생산 날짜</label>
          <input type="date" id="newDate" class="form-input" value="2026-03-21"></div>
        <div><label class="form-label">생산 LOT번호</label>
          <input type="text" id="newLot" class="form-input" placeholder="예: BD001-260321"></div>
        <div><label class="form-label">제품명</label>
          <select id="newProduct" class="form-input">
            ${prods.map(p=>`<option value="${p.id}" data-unit="${p.unit}">${p.name}</option>`).join('')}
          </select></div>
        <div><label class="form-label">생산량</label>
          <div style="display:flex;gap:.5rem;">
            <input type="number" id="newQty" class="form-input" value="100">
            <select id="newUnit" class="form-input" style="max-width:80px;">
              <option>개</option><option>g</option><option>kg</option>
            </select>
          </div></div>
      </div>
      <div style="background:var(--bg-soft);border-radius:8px;padding:.75rem;margin-bottom:1rem;font-size:.875rem;">
        <strong>📌 생산 등록 시 자동 생성되는 CCP 일지:</strong>
        <div style="margin-top:.5rem;display:flex;gap:.5rem;flex-wrap:wrap;">
          ${defs.map(d=>`<span style="background:${d.color}22;color:${d.color};padding:.2rem .6rem;border-radius:6px;font-size:.85rem;">${d.id} ${d.label}</span>`).join('')}
        </div>
      </div>
      <button class="btn btn-primary" onclick="CCPPage.registerProduction()">
        🏭 생산 등록 + CCP 일지 3건 생성
      </button>
    </div>`;
  },

  registerProduction() {
    const date = document.getElementById('newDate')?.value;
    const lot  = (document.getElementById('newLot')?.value||'').trim();
    const pid  = document.getElementById('newProduct')?.value;
    const qty  = Number(document.getElementById('newQty')?.value||0);
    const unit = document.getElementById('newUnit')?.value||'개';
    if (!lot) { alert('LOT 번호를 입력하세요.'); return; }
    const pObj = (HACCP_DATA.currentStock.finished||[]).find(p=>p.id===pid);
    const created = this.createJournalsForProduction({lot,date,productId:pid,productName:pObj?.name||'',qty,unit});
    if (created.length===0) { alert('이미 해당 LOT의 CCP 일지가 존재합니다.'); }
    else { alert(`✅ CCP 일지 ${created.length}건 생성!\n${created.map(j=>j.ccpId+' ('+j.id+')').join('\n')}`); }
    this.switchTab('journal');
  },

  // ─── 일지 작성 모달 ────────────────────────────────────
  openJournal(jId) {
    const journals = this.getCCPJournals();
    const j = journals.find(x=>x.id===jId);
    if (!j) { alert('일지를 찾을 수 없습니다.'); return; }
    const def = this.ccpDefs[j.ccpId];
    if (!def) { alert('CCP 정의를 찾을 수 없습니다.'); return; }
    const isView = j.status !== 'pending';

    let bodyHtml = '';
    if (def.type==='check')   bodyHtml = this.renderCheckForm(j,def,isView);
    else if (def.type==='metal') bodyHtml = this.renderMetalForm(j,def,isView);
    else if (def.type==='gauss') bodyHtml = this.renderGaussForm(j,def,isView);
    else                      bodyHtml = this.renderNumericForm(j,def,isView);

    // 기존 모달 제거 후 새로 생성
    let mc = document.getElementById('ccpModal');
    if (!mc) {
      mc = document.createElement('div');
      mc.id = 'ccpModal';
      mc.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:1rem;';
      document.body.appendChild(mc);
    } else {
      mc.style.display = 'flex';
    }
    mc.innerHTML = `<div style="background:var(--bg-card,#1e1e2e);border-radius:16px;padding:1.5rem;max-width:820px;width:100%;max-height:90vh;overflow-y:auto;position:relative;box-shadow:0 25px 60px rgba(0,0,0,.4);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
        <h2 style="margin:0;font-size:1.1rem;">
          <span style="background:${def.color}22;color:${def.color};padding:.15rem .5rem;border-radius:6px;margin-right:.5rem;">${def.id}</span>
          ${def.label} 모니터링 일지
        </h2>
        <button onclick="CCPPage.closeModal()" style="background:none;border:none;font-size:1.4rem;cursor:pointer;color:var(--text-secondary);">×</button>
      </div>
      <div style="background:var(--bg-soft);border-radius:10px;padding:1rem;margin-bottom:1rem;display:grid;grid-template-columns:1fr 1fr;gap:.5rem;font-size:.875rem;">
        <div><span style="color:var(--text-secondary);">일지번호:</span> <strong style="font-family:monospace;font-size:.8rem;">${j.id}</strong></div>
        <div><span style="color:var(--text-secondary);">생산일자:</span> <strong>${j.productionDate}</strong></div>
        <div><span style="color:var(--text-secondary);">제품명:</span> <strong>${j.productName}</strong></div>
        <div><span style="color:var(--text-secondary);">LOT:</span> <strong>${j.lot}</strong></div>
        <div><span style="color:var(--text-secondary);">생산량:</span> <strong>${j.qty}${j.unit}</strong></div>
        <div><span style="color:var(--text-secondary);">상태:</span> ${this.statusBadge(j.status)}</div>
      </div>
      <div style="background:${def.color}11;border:1px solid ${def.color}33;border-radius:8px;padding:.75rem;margin-bottom:1rem;font-size:.875rem;">
        <strong style="color:${def.color};">📌 한계기준:</strong> ${def.limits}<br>
        <span style="color:var(--text-secondary);">모니터링: ${def.monitoring}</span>
      </div>
      <h3 style="margin:0 0 .75rem;font-size:.95rem;">측정 기록</h3>
      ${bodyHtml}
      ${!isView ? `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-top:1rem;">
        <div><label class="form-label">작업자/작성자</label><input type="text" id="jInspector" class="form-input" value="${j.inspector||''}" placeholder="이름"></div>
        <div><label class="form-label">확인자(HACCP팀장)</label><input type="text" id="jConfirmer" class="form-input" value="${j.confirmer||''}" placeholder="이름"></div>
      </div>
      <div style="margin-top:.75rem;"><label class="form-label">개선조치사항 (이탈 시)</label>
        <textarea id="jCorrective" class="form-input" rows="2" placeholder="한계기준 이탈 시 기록">${j.corrective||''}</textarea>
      </div>
      <div style="background:var(--bg-soft);border-radius:8px;padding:.75rem;margin-top:.75rem;font-size:.8rem;">
        <strong>📋 개선조치 기준:</strong>
        <ul style="margin:.25rem 0 0 1rem;padding:0;">${def.corrective.map(c=>`<li>${c}</li>`).join('')}</ul>
      </div>
      <div style="display:flex;gap:.75rem;margin-top:1rem;justify-content:flex-end;flex-wrap:wrap;">
        <button class="btn" onclick="CCPPage.closeModal()">취소</button>
        <button class="btn btn-primary" onclick="CCPPage.saveJournal('${jId}',false)">💾 임시저장</button>
        <button class="btn" style="background:var(--color-success);color:#fff;" onclick="CCPPage.saveJournal('${jId}',true)">✅ 완료처리</button>
      </div>` : `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:1rem;padding-top:.75rem;border-top:var(--border);font-size:.875rem;">
        <span style="color:var(--text-secondary);">작성자: ${j.inspector||'-'} | 확인자: ${j.confirmer||'-'}</span>
        <button class="btn" onclick="CCPPage.closeModal()">닫기</button>
      </div>`}
    </div>`;

    // 오버레이 클릭 닫기
    mc.onclick = (e) => { if(e.target===mc) CCPPage.closeModal(); };
  },

  closeModal() {
    const mc = document.getElementById('ccpModal');
    if (mc) mc.style.display = 'none';
  },

  // ─── CCP-1P 체크 폼 ────────────────────────────────────
  renderCheckForm(j, def, isView) {
    const times=['작업전','작업중(중간)','작업후'];
    const ex = j.entries||[];
    return `<div style="overflow-x:auto;"><table class="data-table">
      <thead><tr><th>점검시기</th>${def.checkItems.map(c=>`<th style="font-size:.75rem;min-width:85px;">${c.label}</th>`).join('')}<th>점검자</th><th>비고</th></tr></thead>
      <tbody>${times.map((t,ti)=>{
        const e=ex.find(x=>x.time===t)||{};
        if(isView) return `<tr><td><strong>${t}</strong></td>
          ${def.checkItems.map(c=>`<td style="text-align:center;">${e[c.key]==='O'?'<span style="color:var(--color-success);font-weight:700;">O</span>':'<span style="color:var(--color-danger);font-weight:700;">X</span>'}</td>`).join('')}
          <td>${e.checker||'-'}</td><td style="font-size:.8rem;">${e.note||''}</td></tr>`;
        return `<tr><td><strong>${t}</strong></td>
          ${def.checkItems.map(c=>`<td style="text-align:center;">
            <div style="display:flex;gap:4px;justify-content:center;">
              <label style="cursor:pointer;"><input type="radio" name="chk_${ti}_${c.key}" value="O" ${e[c.key]==='O'?'checked':''}> <span style="color:var(--color-success);font-weight:700;">O</span></label>
              <label style="cursor:pointer;"><input type="radio" name="chk_${ti}_${c.key}" value="X" ${e[c.key]==='X'?'checked':''}> <span style="color:var(--color-danger);font-weight:700;">X</span></label>
            </div></td>`).join('')}
          <td><input type="text" id="chk_ch_${ti}" value="${e.checker||''}" placeholder="이름" style="width:65px;padding:.2rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td>
          <td><input type="text" id="chk_nt_${ti}" value="${e.note||''}" placeholder="비고" style="width:85px;padding:.2rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td></tr>`;
      }).join('')}</tbody>
    </table></div>`;
  },

  // ─── CCP-2B 수치 폼 ────────────────────────────────────
  renderNumericForm(j, def, isView) {
    const times=['09:00','10:00','11:00','12:00','13:00','14:00'];
    const ex=j.entries||[];
    return `<div style="overflow-x:auto;"><table class="data-table">
      <thead><tr><th>측정시간</th>${def.params.map(p=>`<th>${p.label}</th>`).join('')}<th>판정</th><th>측정자</th><th>비고</th></tr></thead>
      <tbody>${times.map((t,ti)=>{
        const e=ex.find(x=>x.time===t)||{};
        if(isView){
          const ok=def.params.every(p=>{const v=Number(e[p.key]);if(!v)return true;if(p.critical_min&&v<p.critical_min)return false;if(p.critical_max&&v>p.critical_max)return false;return true;});
          return `<tr><td>${t}</td>
            ${def.params.map(p=>`<td style="text-align:center;">${e[p.key]||'-'}${e[p.key]?' '+p.unit:''}</td>`).join('')}
            <td>${ok?'<span style="color:var(--color-success);">✅적합</span>':'<span style="color:var(--color-danger);">❌이탈</span>'}</td>
            <td>${e.checker||'-'}</td><td style="font-size:.8rem;">${e.note||''}</td></tr>`;
        }
        return `<tr><td><strong>${t}</strong></td>
          ${def.params.map(p=>`<td>
            <div style="display:flex;align-items:center;gap:4px;">
              <input type="number" id="num_${ti}_${p.key}" value="${e[p.key]||''}" placeholder="-"
                style="width:70px;padding:.25rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);"
                oninput="CCPPage.checkLimitColor(this,${p.critical_min||0},${p.critical_max||9999})">
              <span style="font-size:.75rem;color:var(--text-secondary);">${p.unit}</span>
            </div></td>`).join('')}
          <td id="judge_${ti}" style="font-size:.8rem;text-align:center;color:var(--text-secondary);">-</td>
          <td><input type="text" id="num_ch_${ti}" value="${e.checker||''}" placeholder="이름" style="width:65px;padding:.25rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td>
          <td><input type="text" id="num_nt_${ti}" value="${e.note||''}" placeholder="비고" style="width:80px;padding:.25rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td></tr>`;
      }).join('')}</tbody>
    </table></div>`;
  },

  checkLimitColor(input, min, max) {
    const v=Number(input.value);
    const ok=(!min||v>=min)&&(!max||max>=9999||v<=max);
    input.style.borderColor=ok?'var(--color-success)':'var(--color-danger)';
  },


  // ─── CCP-1P 가우스미터 측정 폼 ─────────────────────────
  renderGaussForm(j, def, isView) {
    const times = ['작업시작 전', '1시간 후', '2시간 후', '3시간 후', '4시간 후', '작업종료 후'];
    const ex = j.entries || [];
    const limitG = def.limitGauss || 8000;
    return `
    <div style="margin-bottom:.75rem;padding:.6rem .9rem;background:#f59e0b11;border:1px solid #f59e0b44;border-radius:8px;font-size:.82rem;">
      <strong style="color:#f59e0b;">📌 한계기준:</strong> 자력 <strong>${limitG.toLocaleString()}G(가우스) 이상</strong>
      &nbsp;|&nbsp; 자석봉 Φ42.7 &nbsp;|&nbsp; 투입량 1kg/min &nbsp;|&nbsp; 3,530rpm
    </div>
    <div style="overflow-x:auto;"><table class="data-table">
      <thead><tr>
        <th>측정시점</th>
        <th>자력(G) <span style="font-size:.7rem;color:var(--text-secondary);">8,000G↑</span></th>
        <th>자석봉 청소</th>
        <th>판정</th>
        <th>측정자</th>
        <th>비고</th>
      </tr></thead>
      <tbody>${times.map((t,ti) => {
        const e = ex.find(x => x.time===t) || {};
        const gauss = Number(e.gauss) || 0;
        const pass = gauss >= limitG;
        if (isView) {
          return `<tr>
            <td><strong>${t}</strong></td>
            <td style="text-align:center;font-weight:700;color:${gauss&&pass?'var(--color-success)':'var(--color-danger)'};">
              ${gauss ? gauss.toLocaleString()+'G' : '-'}
            </td>
            <td style="text-align:center;">${e.clean==='O'?'<span style="color:var(--color-success);font-weight:700;">O</span>':'<span style="color:var(--color-danger);">X</span>'}</td>
            <td>${gauss?(pass?'<span style="color:var(--color-success);">✅적합</span>':'<span style="color:var(--color-danger);">❌이탈</span>'):'-'}</td>
            <td>${e.checker||'-'}</td>
            <td style="font-size:.8rem;">${e.note||''}</td>
          </tr>`;
        }
        return `<tr>
          <td><strong>${t}</strong></td>
          <td>
            <div style="display:flex;align-items:center;gap:4px;">
              <input type="number" id="gauss_val_${ti}" value="${e.gauss||''}" placeholder="예: 10500"
                style="width:90px;padding:.25rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);"
                oninput="CCPPage.checkGaussColor(this,${limitG})">
              <span style="font-size:.75rem;color:var(--text-secondary);">G</span>
            </div>
          </td>
          <td style="text-align:center;">
            <div style="display:flex;gap:6px;justify-content:center;">
              <label style="cursor:pointer;"><input type="radio" name="gauss_clean_${ti}" value="O" ${e.clean==='O'?'checked':''}> <span style="color:var(--color-success);font-weight:700;">O</span></label>
              <label style="cursor:pointer;"><input type="radio" name="gauss_clean_${ti}" value="X" ${e.clean==='X'?'checked':''}> <span style="color:var(--color-danger);font-weight:700;">X</span></label>
            </div>
          </td>
          <td id="gauss_judge_${ti}" style="font-size:.8rem;text-align:center;color:var(--text-secondary);">-</td>
          <td><input type="text" id="gauss_ch_${ti}" value="${e.checker||''}" placeholder="이름"
            style="width:65px;padding:.25rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td>
          <td><input type="text" id="gauss_nt_${ti}" value="${e.note||''}" placeholder="비고"
            style="width:80px;padding:.25rem .4rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td>
        </tr>`;
      }).join('')}</tbody>
    </table></div>`;
  },

  checkGaussColor(input, limit) {
    const v = Number(input.value);
    const ok = v >= limit;
    input.style.borderColor = v ? (ok ? 'var(--color-success)' : 'var(--color-danger)') : '';
    // 판정 셀 업데이트
    const row = input.closest('tr');
    if (row) {
      const cells = row.querySelectorAll('td');
      if (cells[3]) cells[3].innerHTML = v ? (ok ?
        '<span style="color:var(--color-success);">✅적합</span>' :
        '<span style="color:var(--color-danger);">❌이탈</span>') : '-';
    }
  },

  // ─── CCP-3P 금속검출 폼 ────────────────────────────────
  renderMetalForm(j, def, isView) {
    const ex=j.entries||[];
    const e0=ex.find(x=>x.time==='작업전감도')||{};
    const batches=['1배치','2배치','3배치','4배치','5배치'];
    return `
    <div style="margin-bottom:1rem;">
      <h4 style="margin:0 0 .5rem;font-size:.875rem;">① 작업 전 감도 확인 (Test Piece)</h4>
      <table class="data-table"><thead><tr><th>구분</th><th>기준</th><th>감도확인</th><th>판정</th><th>확인자</th></tr></thead>
      <tbody>
        <tr><td>Fe (철)</td><td>Ø 2.0mm 불검출</td>
          <td>${isView?e0.fe||'-':`<select id="mt_fe" style="padding:.25rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);"><option ${e0.fe==='정상'?'selected':''}>정상</option><option ${e0.fe==='이상'?'selected':''}>이상</option></select>`}</td>
          <td>${isView?(e0.fe==='정상'?'<span style="color:var(--color-success);">✅적합</span>':'<span style="color:var(--color-danger);">❌부적합</span>'):'-'}</td>
          <td>${isView?e0.checker||'-':`<input type="text" id="mt_checker" value="${e0.checker||''}" placeholder="이름" style="width:65px;padding:.25rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);">`}</td>
        </tr>
        <tr><td>SUS (스테인리스)</td><td>Ø 2.5mm 불검출</td>
          <td>${isView?e0.sus||'-':`<select id="mt_sus" style="padding:.25rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);"><option ${e0.sus==='정상'?'selected':''}>정상</option><option ${e0.sus==='이상'?'selected':''}>이상</option></select>`}</td>
          <td>-</td><td>-</td>
        </tr>
      </tbody></table>
    </div>
    <div>
      <h4 style="margin:0 0 .5rem;font-size:.875rem;">② 제품 통과 검사</h4>
      <table class="data-table"><thead><tr><th>배치</th><th>통과시간</th><th>검사결과</th><th>조치사항</th><th>검사자</th></tr></thead>
      <tbody>${batches.map((b,bi)=>{
        const eb=ex.find(x=>x.time===b)||{};
        if(isView) return `<tr><td>${b}</td><td>${eb.passTime||'-'}</td>
          <td>${eb.result==='합격'?'<span style="color:var(--color-success);">✅합격</span>':'<span style="color:var(--color-danger);">❌불합격</span>'}</td>
          <td style="font-size:.8rem;">${eb.action||''}</td><td>${eb.checker||'-'}</td></tr>`;
        return `<tr><td><strong>${b}</strong></td>
          <td><input type="time" id="mt_time_${bi}" value="${eb.passTime||''}" style="padding:.25rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td>
          <td><select id="mt_result_${bi}" style="padding:.25rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);">
            <option ${eb.result==='합격'?'selected':''}>합격</option><option ${eb.result==='불합격'?'selected':''}>불합격</option>
          </select></td>
          <td><input type="text" id="mt_action_${bi}" value="${eb.action||''}" placeholder="이물 발견 시 조치" style="width:110px;padding:.25rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td>
          <td><input type="text" id="mt_ch_${bi}" value="${eb.checker||''}" placeholder="이름" style="width:65px;padding:.25rem;border:var(--border);border-radius:5px;background:var(--bg-soft);color:var(--text-primary);font-size:.8rem;"></td></tr>`;
      }).join('')}</tbody></table>
    </div>`;
  },

  // ─── 일지 저장 ─────────────────────────────────────────
  saveJournal(jId, complete) {
    const journals = this.getCCPJournals();
    const idx = journals.findIndex(j=>j.id===jId);
    if (idx<0) return;
    const j = journals[idx];
    const def = this.ccpDefs[j.ccpId];

    j.inspector  = document.getElementById('jInspector')?.value || j.inspector;
    j.confirmer  = document.getElementById('jConfirmer')?.value || j.confirmer;
    j.corrective = document.getElementById('jCorrective')?.value || j.corrective;

    let deviated = false;

    if (def.type==='check') {
      const times=['작업전','작업중(중간)','작업후'];
      j.entries = times.map((t,ti)=>{
        const entry={time:t};
        def.checkItems.forEach(c=>{
          const r=document.querySelector(`input[name="chk_${ti}_${c.key}"]:checked`);
          entry[c.key]=r?r.value:'X';
          if(entry[c.key]==='X') deviated=true;
        });
        entry.checker=document.getElementById(`chk_ch_${ti}`)?.value||'';
        entry.note   =document.getElementById(`chk_nt_${ti}`)?.value||'';
        return entry;
      });
    } else if (def.type==='numeric') {
      const times=['09:00','10:00','11:00','12:00','13:00','14:00'];
      j.entries = times.map((t,ti)=>{
        const entry={time:t};
        def.params.forEach(p=>{entry[p.key]=document.getElementById(`num_${ti}_${p.key}`)?.value||'';});
        entry.checker=document.getElementById(`num_ch_${ti}`)?.value||'';
        entry.note   =document.getElementById(`num_nt_${ti}`)?.value||'';
        return entry;
      }).filter(e=>def.params.some(p=>e[p.key]));
      j.entries.forEach(e=>{
        def.params.forEach(p=>{
          const v=Number(e[p.key]);
          if(v && p.critical_min && v<p.critical_min) deviated=true;
          if(v && p.critical_max && v>p.critical_max) deviated=true;
        });
      });
    } else if (def.type==='gauss') {
      const times = ['작업시작 전','1시간 후','2시간 후','3시간 후','4시간 후','작업종료 후'];
      j.entries = times.map((t,ti) => {
        const gauss = Number(document.getElementById(`gauss_val_${ti}`)?.value || 0);
        const r = document.querySelector(`input[name="gauss_clean_${ti}"]:checked`);
        const clean = r?.value || 'X';
        if(gauss < def.limitGauss && gauss > 0) deviated = true;
        if(clean === 'X') deviated = true;
        return {
          time:t, gauss, clean,
          checker: document.getElementById(`gauss_ch_${ti}`)?.value || '',
          note:    document.getElementById(`gauss_nt_${ti}`)?.value || '',
        };
      }).filter(e => e.gauss || e.clean==='X');
    } else if (def.type==='metal') {
      j.entries=[{
        time:'작업전감도',
        fe:   document.getElementById('mt_fe')?.value||'정상',
        sus:  document.getElementById('mt_sus')?.value||'정상',
        checker: document.getElementById('mt_checker')?.value||'',
      }];
      if(j.entries[0].fe==='이상'||j.entries[0].sus==='이상') deviated=true;
      ['1배치','2배치','3배치','4배치','5배치'].forEach((b,bi)=>{
        const t=document.getElementById(`mt_time_${bi}`)?.value;
        if(t){
          const res=document.getElementById(`mt_result_${bi}`)?.value||'합격';
          if(res==='불합격') deviated=true;
          j.entries.push({time:b,passTime:t,result:res,
            action:document.getElementById(`mt_action_${bi}`)?.value||'',
            checker:document.getElementById(`mt_ch_${bi}`)?.value||''});
        }
      });
    }

    if (complete) {
      j.status = deviated ? 'deviated' : 'completed';
      j.completedAt = new Date().toISOString();
    }
    journals[idx]=j;
    this.saveCCPJournals(journals);
    this.closeModal();
    alert(complete ? `✅ 일지 ${deviated?'이탈발생':'완료'} 처리` : '💾 임시 저장 완료');
    this.switchTab('journal');
  },

  // ─── 테스트 데이터 ─────────────────────────────────────
  createTestJournals() {
    [
      {lot:'BD001-260321',date:'2026-03-21',productId:'FP001',productName:'혈맥천 영묘사향단',qty:850,unit:'개'},
      {lot:'BD010-260321',date:'2026-03-21',productId:'FP010',productName:'EXO-Boost 발효녹용',qty:200,unit:'kg'},
    ].forEach(p=>this.createJournalsForProduction(p));
    alert('✅ 테스트 CCP 일지 6건 생성');
    this.switchTab('journal');
  },

  // ─── 이력 ──────────────────────────────────────────────
  renderLog() {
    const j=this.getCCPJournals().filter(x=>x.status!=='pending');
    if(!j.length) return `<div class="card" style="text-align:center;padding:3rem;color:var(--text-secondary);">완료된 CCP 일지가 없습니다.</div>`;
    return `<div class="card"><h3 style="margin:0 0 1rem;font-size:1rem;">🗒️ 완료 CCP 일지 이력</h3>
    <table class="data-table"><thead><tr><th>CCP</th><th>생산일자</th><th>제품명</th><th>LOT</th><th>상태</th><th>작성자</th><th>보기</th></tr></thead>
    <tbody>${j.sort((a,b)=>b.productionDate?.localeCompare(a.productionDate)).map(x=>`<tr>
      <td><span style="background:${this.ccpDefs[x.ccpId]?.color+'22'};color:${this.ccpDefs[x.ccpId]?.color};padding:.15rem .5rem;border-radius:5px;font-size:.8rem;">${x.ccpId}</span></td>
      <td>${x.productionDate}</td><td>${x.productName}</td>
      <td style="font-size:.8rem;">${x.lot}</td><td>${this.statusBadge(x.status)}</td>
      <td>${x.inspector||'-'}</td>
      <td><button class="btn btn-sm btn-primary" onclick="CCPPage.openJournal('${x.id}')">보기</button></td>
    </tr>`).join('')}</tbody></table></div>`;
  },
};
