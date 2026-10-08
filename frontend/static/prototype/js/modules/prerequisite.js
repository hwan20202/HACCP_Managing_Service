// =============================================
// BIODOT HACCP - 선행요건 관리 모듈 (기준서 기반 완전판)
// 작업소위생 / 개인위생 / 방충방서 / 이물관리 / 설비점검 / 검교정
// =============================================

const PrerequisitePage = {
  currentCategory: 'all',
  currentJournal: null,  // 현재 열린 점검일지 유형

  // ─── 점검일지 정의 (기준서 기반) ─────────────────────────
  JOURNALS: {
    // 1. 작업소 위생점검표 (일 1회)
    sanitation: {
      id: 'sanitation',
      title: '작업소 위생점검표',
      icon: '🧹',
      freq: '매일 (작업 후)',
      color: 'success',
      evaluationBase: '양호: O / 불량: X',
      items: [
        '출입문은 항상 밀폐되어 있고 청결한가?',
        '작업대 등 작업도구는 청결한가?',
        '세정대, 손건조기, 손소독기는 정상작동하며 청결한가?',
        '천장, 작업장벽, 배관 등은 이물·먼지 없이 청결이 유지되고 있는가?',
        '발판소독조의 소독액은 적정량이 비치되어 있는가?',
        '배수로는 청결하게 관리되며 물고임·악취는 없는가?',
        '작업실 이탈(휴식, 화장실 등) 시 입/퇴실 기준을 준수하는가?',
        '식품을 오염되지 않도록 위생적으로 운반·처리·포장하는가?',
        '작업실 급/배기 등 환기시설은 정상작동하는가?',
        '작업 중 흡연·음식물섭취·껌씹는 행위 등을 하지 않는가?',
        '폐기물은 정해진 방법에 의해 처리하였는가?',
        '작업실의 정리정돈 상태는 양호한가?',
        '남아있는 내포장재는 외기에 노출되지 않게 밀폐보관하고 있는가?',
      ]
    },
    // 2. 개인위생점검표 (일 1회)
    personal: {
      id: 'personal',
      title: '개인위생점검표',
      icon: '👤',
      freq: '매일 (작업 전)',
      color: 'primary',
      evaluationBase: '양호: O / 불량: X',
      items: [
        '위생복: 소매·바지·상의 단추 등 개방하지 않는다',
        '위생모: 전체를 감싸 머리카락이 나오지 않게 착용',
        '토시: 위생장갑을 덮어 팔꿈치까지 착용',
        '장갑: 손목부위 작업복 소매를 덮어 착용',
        '마스크: 호흡기(입·코)를 완전히 가리도록 착용',
        '위생화: 꺾어 신거나 접어신지 않는다',
        '손 수세 (비누·소독액) 실시 여부',
        '손 청결 (손톱·매니큐어) 확인',
        '머리카락 정리 상태 확인',
        '장신구(패물) 미착용 확인',
        '과도한 화장 미실시 확인',
        '개인물품 미반입 확인',
        '호흡기질환(감기·기침) 이상없음',
        '피부질환(창상·화상) 이상없음',
      ]
    },
    // 3. 방충방서점검표 (주 1회)
    pestControl: {
      id: 'pestControl',
      title: '방충방서점검표',
      icon: '🐛',
      freq: '주 1회',
      color: 'warning',
      evaluationBase: '양호: O / 불량: X',
      items: [
        '포충등은 정상작동하며 청결한가?',
        '유인등은 꺼지거나 깜박임이 없이 양호한가?',
        '끈끈이에 포획된 개체수가 급격히 증가하지 않았나?',
        '음식물 등의 반입 흔적은 없는가?',
        '작업장 내부 트랩에 설치류가 발견되지 않았는가?',
        '트랩의 위치가 변경되거나 파손되지 않았는가?',
        '트랩에 설치류 포획 또는 섭식 흔적이 없는가?',
        '외부 트랩의 위치가 변경되거나 파손되지 않았는가?',
        '정해진 주기에 따라 외부 방역을 실시하였는가?',
        '건물 및 출입문에 해충 유입 틈새가 없는가?',
        '작업 외부로 연결되는 출입구는 항상 닫혀있는가?',
      ]
    },
    // 4. 이물관리점검표 (일 1회/작업 시)
    foreignMatter: {
      id: 'foreignMatter',
      title: '이물관리점검표',
      icon: '🔍',
      freq: '매일 (작업 중)',
      color: 'danger',
      evaluationBase: '적합: O / 부적합: X',
      items: [
        '[원료중의 이물혼입방지] 원부재료 반입 시 이물질흡입기로 이물 제거 확인',
        '[원료중의 이물혼입방지] 입고된 원부재료 검수 시 혼입 이물 없는지 확인',
        '[설비불량 이물혼입방지] 설비의 청소상태는 양호하며 습기 제거가 잘 되어있는가?',
        '[설비불량 이물혼입방지] 설비 틈새에 세척되지 않고 끼어있는 이물질이 없는가?',
        '[작업자 이물혼입방지] 볼펜 등 필기구는 제조라인에서 떨어진 장소에서만 사용',
        '[작업자 이물혼입방지] 입/출입 시 끈끈이 롤러를 사용하여 머리카락·이물 제거',
        '[작업자 이물혼입방지] 위생모 사이로 머리카락이 새어나온 경우 없는가?',
        '[작업 중 이물혼입방지] 비닐·테이프 등 폐기물 즉시 폐기물보관함에 처리',
        '[작업 중 이물혼입방지] 기계류 정기점검으로 느슨한 나사류 등 확인',
        '[작업 중 이물혼입방지] 기계류 분해 시 나사·볼트 수량 확인하여 누락방지',
        '[작업 중 이물혼입방지] 기계류 오일·기름때 혼입 여부 관리',
        '[포장 중 이물혼입방지] 내포장재(비닐) 조각이 파손되어 제품에 혼입될 우려 없는가?',
        '[해충 혼입방지] 건물 및 출입문에 해충 유입될 틈새 발생 없는가?',
      ]
    },
    // 5. 설비점검표 (설비별/수시)
    equipment: {
      id: 'equipment',
      title: '기계기구 점검표',
      icon: '⚙️',
      freq: '수시 / 정기점검',
      color: 'info',
      evaluationBase: '정상: O / 이상: X',
      items: [
        '[건조기] 내부 세척·소독 상태 확인',
        '[건조기] 온도센서 작동 및 표시값 정확성 확인',
        '[건조기] 도어·실링 상태 확인 (누기 없음)',
        '[금속검출기] 감도 확인 (Fe 1.5mm / SUS 2.0mm 테스트피스)',
        '[금속검출기] 이물 반응 시 자동 배출 기능 작동 확인',
        '[금속검출기] 외부 청소 및 이물 없음 확인',
        '[체망/이물제거기] 체망 청소 및 파손 여부 확인',
        '[체망/이물제거기] 망 눈금 규격 적합성 확인',
        '[저울] 영점 조정 및 정확도 확인',
        '[포장기] 밀봉 상태 및 실링 온도 확인',
        '[에어컴프레서] 에어필터 상태 확인 (오일·수분 없음)',
        '[작업도구] 세척·소독 후 지정 장소 보관 여부 확인',
      ]
    },
    // 6. 검교정관리대장 (연 1회)
    calibration: {
      id: 'calibration',
      title: '검·교정 관리대장',
      icon: '📐',
      freq: '연 1회',
      color: 'neutral',
      isCalibration: true,
      equipmentList: [
        { name:'건조기 온도계', model:'-', standard:'±1°C', lastDate:'2025-11-01', nextDate:'2026-11-01', result:'pass', resultNo:'CA-2025-001' },
        { name:'금속검출기', model:'-', standard:'Fe≤1.5mm / SUS≤2.0mm', lastDate:'2025-11-01', nextDate:'2026-11-01', result:'pass', resultNo:'CA-2025-002' },
        { name:'저울(계량용)', model:'-', standard:'±1%', lastDate:'2025-11-01', nextDate:'2026-11-01', result:'pass', resultNo:'CA-2025-003' },
        { name:'온도계(실온)', model:'-', standard:'±1°C', lastDate:'2025-11-01', nextDate:'2026-11-01', result:'pass', resultNo:'CA-2025-004' },
        { name:'체망', model:'-', standard:'규격적합', lastDate:'2025-11-01', nextDate:'2026-11-01', result:'pass', resultNo:'CA-2025-005' },
      ]
    }
  },

  // ─── 메인 렌더 ────────────────────────────────────────────
  render() {
    const today = new Date('2026-03-21').toLocaleDateString('ko-KR');
    const items = HACCP_DATA.prerequisiteItems || [];
    const categories = [...new Set(items.map(p => p.category))];
    const warningCount = items.filter(p => p.status === 'warning' || p.status === 'danger').length;

    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">✅ 선행요건 관리</h1>
          <p class="page-desc">HACCP 선행요건 점검일지 · ${today}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" onclick="PrerequisitePage.openAddModal()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            항목 추가
          </button>
        </div>
      </div>

      <!-- KPI -->
      <div class="kpi-grid" style="margin-bottom:1.25rem;">
        <div class="kpi-card success"><div class="kpi-value">${items.filter(p=>p.status==='ok').length}</div><div class="kpi-label">정상 항목</div></div>
        <div class="kpi-card ${warningCount>0?'warning':'success'}"><div class="kpi-value">${warningCount}</div><div class="kpi-label">주의/미이행</div></div>
        <div class="kpi-card primary"><div class="kpi-value">${items.length}</div><div class="kpi-label">전체 항목</div></div>
        <div class="kpi-card info">
          <div class="kpi-value">${new Date('2026-03-21').toLocaleDateString('ko-KR',{month:'long', day:'numeric'})}</div>
          <div class="kpi-label">오늘 점검 기준일</div>
        </div>
      </div>

      <!-- 점검일지 카드 그리드 -->
      <div style="margin-bottom:1.25rem;">
        <div style="font-weight:700;font-size:0.82rem;color:var(--text-secondary);margin-bottom:0.75rem;letter-spacing:0.05em;">
          📋 점검일지 바로 작성
        </div>
        <div class="grid-3">
          ${Object.values(this.JOURNALS).map(j => this.renderJournalCard(j)).join('')}
        </div>
      </div>

      <!-- 직원 보건증 현황 -->
      <div class="card" style="margin-bottom:1rem;">
        <div class="card-header">
          <div class="card-title">👥 직원 보건증 현황</div>
          <button class="btn btn-secondary btn-sm" onclick="PrerequisitePage.manageHealthCards()">갱신 안내</button>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:0.75rem;">
          ${HACCP_DATA.employees.map(emp => {
            const expiry = new Date(emp.healthCard);
            const today  = new Date('2026-03-21');
            const daysLeft = Math.ceil((expiry - today) / 86400000);
            const st = daysLeft < 0 ? 'expired' : daysLeft <= 14 ? 'danger' : daysLeft <= 60 ? 'warning' : 'ok';
            const bc = st === 'expired' || st === 'danger' ? 'badge-danger' : st === 'warning' ? 'badge-warning' : 'badge-success';
            const label = daysLeft < 0 ? '만료됨' : `D-${daysLeft}`;
            return `
            <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);border:1px solid ${st==='danger'||st==='expired'?'rgba(239,68,68,0.2)':st==='warning'?'rgba(245,158,11,0.2)':'var(--border-subtle)'};">
              <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem;">
                <div style="width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,var(--brand-primary),var(--brand-secondary));display:flex;align-items:center;justify-content:center;font-size:0.8rem;font-weight:700;color:white;flex-shrink:0;">${emp.name[0]}</div>
                <div>
                  <div style="font-size:0.82rem;font-weight:700;">${emp.name}</div>
                  <div style="font-size:0.65rem;color:var(--text-muted);">${emp.role}</div>
                </div>
              </div>
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="font-size:0.68rem;color:var(--text-muted);">${emp.healthCard}</div>
                <span class="badge ${bc}">${label}</span>
              </div>
            </div>`;
          }).join('')}
        </div>
      </div>

      <!-- 선행요건 관리 현황 테이블 -->
      <div class="card" style="padding:0;">
        <div style="padding:1rem 1.25rem 0.5rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
          <div style="font-weight:700;font-size:0.9rem;">📊 관리 현황</div>
          <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
            <button class="btn btn-sm ${this.currentCategory==='all'?'btn-primary':'btn-secondary'}"
              onclick="PrerequisitePage.filterCategory('all')">전체</button>
            ${categories.map(cat=>`
            <button class="btn btn-sm ${this.currentCategory===cat?'btn-primary':'btn-secondary'}"
              onclick="PrerequisitePage.filterCategory('${cat}')">${cat}</button>`).join('')}
          </div>
        </div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr><th>카테고리</th><th>관리항목</th><th>주기</th><th>최근 실시일</th><th>다음 예정일</th><th>담당자</th><th>상태</th><th>작업</th></tr>
            </thead>
            <tbody id="prereqBody">${this.renderTableBody()}</tbody>
          </table>
        </div>
      </div>
    </div>`;
  },

  renderJournalCard(j) {
    const colorMap = { success:'var(--color-success)', primary:'var(--brand-primary)', warning:'var(--color-warning)', danger:'var(--color-danger)', info:'#38bdf8', neutral:'var(--text-muted)' };
    const color = colorMap[j.color] || colorMap.primary;
    return `
    <div class="card" style="cursor:pointer;border:1px solid transparent;transition:all 0.2s;"
      onclick="PrerequisitePage.openJournal('${j.id}')"
      onmouseenter="this.style.border='1px solid ${color}';this.style.transform='translateY(-2px)'"
      onmouseleave="this.style.border='1px solid transparent';this.style.transform='translateY(0)'">
      <div style="display:flex;align-items:flex-start;gap:0.75rem;">
        <div style="width:44px;height:44px;border-radius:10px;background:${color}22;display:flex;align-items:center;justify-content:center;font-size:1.3rem;flex-shrink:0;">${j.icon}</div>
        <div style="flex:1;min-width:0;">
          <div style="font-weight:700;font-size:0.88rem;margin-bottom:0.25rem;">${j.title}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);">${j.freq}</div>
        </div>
      </div>
      <div style="margin-top:0.9rem;display:flex;justify-content:flex-end;">
        <button class="btn btn-sm" style="background:${color}22;color:${color};border:1px solid ${color}44;font-size:0.72rem;padding:0.2rem 0.65rem;" onclick="event.stopPropagation();PrerequisitePage.openJournal('${j.id}')">
          📝 작성하기
        </button>
      </div>
    </div>`;
  },

  renderTableBody() {
    const freqMap = { daily:'매일', weekly:'매주', monthly:'매월', yearly:'연1회', '6monthly':'반기' };
    const items = (HACCP_DATA.prerequisiteItems || []).filter(p =>
      this.currentCategory === 'all' || p.category === this.currentCategory
    );
    if (items.length === 0) return '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text-muted);">항목이 없습니다.</td></tr>';
    return items.map(p => {
      const sc = p.status==='ok'?'badge-success':p.status==='warning'?'badge-warning':'badge-danger';
      const sl = p.status==='ok'?'정상':p.status==='warning'?'주의':'긴급';
      return `
      <tr>
        <td><span class="badge badge-neutral">${p.category}</span></td>
        <td style="font-weight:600;">${p.name}</td>
        <td>${freqMap[p.frequency]||p.frequency}</td>
        <td class="no-wrap">${p.lastDate||'-'}</td>
        <td class="no-wrap">${p.nextDate||'-'}</td>
        <td>${p.assignee}</td>
        <td><span class="badge ${sc} badge-dot">${sl}</span></td>
        <td>
          <div class="d-flex gap-1">
            <button class="btn btn-secondary btn-sm" onclick="PrerequisitePage.recordExecution('${p.id}')">실시기록</button>
          </div>
        </td>
      </tr>`;
    }).join('');
  },

  filterCategory(cat) {
    this.currentCategory = cat;
    App.navigate('prerequisite');
  },

  // ─── 점검일지 열기 ─────────────────────────────────────────
  openJournal(journalId) {
    const j = this.JOURNALS[journalId];
    if (!j) return;
    if (j.isCalibration) { this.openCalibrationModal(j); return; }
    this.openChecklistModal(j);
  },

  // ─── 체크리스트형 점검일지 모달 ────────────────────────────
  openChecklistModal(j) {
    const today = new Date('2026-03-21').toISOString().split('T')[0];
    const colorMap = { success:'var(--color-success)', primary:'var(--brand-primary)', warning:'var(--color-warning)', danger:'var(--color-danger)', info:'#38bdf8' };
    const color = colorMap[j.color]||'var(--brand-primary)';

    const checklistHTML = j.items.map((item, i) => `
    <div style="display:flex;align-items:flex-start;gap:0.75rem;padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-subtle);transition:background 0.1s;"
         id="row-${j.id}-${i}">
      <div style="font-size:0.7rem;color:var(--text-muted);min-width:18px;padding-top:2px;">${i+1}</div>
      <div style="flex:1;font-size:0.82rem;line-height:1.5;color:var(--text-secondary);">${item}</div>
      <div style="display:flex;gap:0.4rem;flex-shrink:0;align-items:center;">
        <button class="prereq-btn" id="ok-${j.id}-${i}" data-val="O"
          onclick="PrerequisitePage.selectResult('${j.id}',${i},'O')"
          style="width:34px;height:28px;border-radius:5px;border:1px solid var(--border-strong);
            background:transparent;font-weight:700;font-size:0.82rem;cursor:pointer;transition:all 0.15s;color:var(--text-muted);">O</button>
        <button class="prereq-btn" id="ng-${j.id}-${i}" data-val="X"
          onclick="PrerequisitePage.selectResult('${j.id}',${i},'X')"
          style="width:34px;height:28px;border-radius:5px;border:1px solid var(--border-strong);
            background:transparent;font-weight:700;font-size:0.82rem;cursor:pointer;transition:all 0.15s;color:var(--text-muted);">X</button>
        <button class="prereq-btn" id="na-${j.id}-${i}" data-val="-"
          onclick="PrerequisitePage.selectResult('${j.id}',${i},'-')"
          style="width:34px;height:28px;border-radius:5px;border:1px solid var(--border-strong);
            background:transparent;font-size:0.75rem;cursor:pointer;transition:all 0.15s;color:var(--text-muted);">N/A</button>
      </div>
    </div>`).join('');

    App.showModal(`${j.icon} ${j.title}`,`
    <!-- 헤더 정보 -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem;margin-bottom:1rem;padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);">
      <div>
        <div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:0.2rem;">점검일자</div>
        <input type="date" id="jrnDate" class="form-control" value="${today}" style="font-size:0.8rem;padding:0.3rem 0.5rem;"/>
      </div>
      <div>
        <div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:0.2rem;">담당자</div>
        <select id="jrnWorker" class="form-control" style="font-size:0.8rem;padding:0.3rem 0.5rem;">
          ${HACCP_DATA.employees.map(e=>`<option>${e.name}</option>`).join('')}
        </select>
      </div>
      <div>
        <div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:0.2rem;">확인자 (HACCP팀장)</div>
        <select id="jrnApprover" class="form-control" style="font-size:0.8rem;padding:0.3rem 0.5rem;">
          ${HACCP_DATA.employees.map(e=>`<option ${e.role.includes('팀장')? 'selected':''}>${e.name}</option>`).join('')}
        </select>
      </div>
    </div>

    <!-- 평가기준 안내 -->
    <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.5rem;padding:0 0.25rem;">
      평가기준: <strong>${j.evaluationBase}</strong> &nbsp;|&nbsp; 점검주기: <strong>${j.freq}</strong>
    </div>

    <!-- 체크리스트 -->
    <div id="checklistBody-${j.id}" style="border:1px solid var(--border-subtle);border-radius:var(--radius-md);overflow:hidden;max-height:50vh;overflow-y:auto;margin-bottom:0.75rem;">
      ${checklistHTML}
    </div>

    <!-- 빠른 전체 선택 -->
    <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;">
      <button class="btn btn-sm" style="background:rgba(16,185,129,0.1);color:var(--color-success);border:1px solid rgba(16,185,129,0.3);"
        onclick="PrerequisitePage.selectAll('${j.id}','O')">✓ 전체 O (정상)</button>
      <button class="btn btn-sm" style="background:rgba(239,68,68,0.1);color:var(--color-danger);border:1px solid rgba(239,68,68,0.3);"
        onclick="PrerequisitePage.selectAll('${j.id}','X')">✗ 전체 X (불량)</button>
      <div style="flex:1;"></div>
      <span id="jrn-progress-${j.id}" style="font-size:0.75rem;color:var(--text-muted);padding:0.2rem 0;">0 / ${j.items.length} 완료</span>
    </div>

    <!-- 이탈 내용 및 개선 조치 -->
    <div class="form-group" style="margin-bottom:0.5rem;">
      <label class="form-label">이탈 내용 (X 항목 및 내용 기록)</label>
      <textarea id="jrnDeviation" class="form-control" rows="2" placeholder="이탈된 항목 내용을 기록하세요. (없으면 '해당없음')"></textarea>
    </div>
    <div class="form-group">
      <label class="form-label">개선 조치사항 및 결과</label>
      <textarea id="jrnAction" class="form-control" rows="2" placeholder="개선 조치 내용을 기록하세요. (없으면 '해당없음')"></textarea>
    </div>`,
    [
      { text:'취소', class:'btn-secondary', action:'App.closeModal()' },
      { text:'🖨 인쇄', class:'btn-secondary', action:`PrerequisitePage.printJournal('${j.id}')` },
      { text:'✔ 저장', class:'btn-primary', action:`PrerequisitePage.saveJournal('${j.id}')` }
    ]);

    // 상태 저장 객체 초기화
    window._prereqResults = window._prereqResults || {};
    window._prereqResults[j.id] = {};
  },

  // 개별 결과 선택
  selectResult(jid, idx, val) {
    if (!window._prereqResults) window._prereqResults = {};
    if (!window._prereqResults[jid]) window._prereqResults[jid] = {};
    window._prereqResults[jid][idx] = val;

    // 버튼 스타일
    ['ok','ng','na'].forEach(type => {
      const btn = document.getElementById(`${type}-${jid}-${idx}`);
      if (!btn) return;
      btn.style.background = 'transparent';
      btn.style.color = 'var(--text-muted)';
      btn.style.borderColor = 'var(--border-strong)';
    });
    const idMap = { 'O':'ok', 'X':'ng', '-':'na' };
    const activeBtn = document.getElementById(`${idMap[val]}-${jid}-${idx}`);
    if (activeBtn) {
      if (val === 'O') { activeBtn.style.background = 'rgba(16,185,129,0.15)'; activeBtn.style.color = 'var(--color-success)'; activeBtn.style.borderColor = 'var(--color-success)'; }
      if (val === 'X') { activeBtn.style.background = 'rgba(239,68,68,0.15)'; activeBtn.style.color = 'var(--color-danger)'; activeBtn.style.borderColor = 'var(--color-danger)'; }
      if (val === '-') { activeBtn.style.background = 'var(--bg-card-hover)'; activeBtn.style.color = 'var(--text-primary)'; }
    }

    // 행 배경색 (X이면 연한 빨강)
    const row = document.getElementById(`row-${jid}-${idx}`);
    if (row) {
      row.style.background = val === 'X' ? 'rgba(239,68,68,0.05)' : '';
    }

    // 진행률 업데이트
    const journal = this.JOURNALS[jid];
    if (journal) {
      const done = Object.keys(window._prereqResults[jid]).length;
      const prog = document.getElementById(`jrn-progress-${jid}`);
      if (prog) prog.textContent = `${done} / ${journal.items.length} 완료`;
    }
  },

  // 전체 선택
  selectAll(jid, val) {
    const journal = this.JOURNALS[jid];
    if (!journal) return;
    journal.items.forEach((_, i) => this.selectResult(jid, i, val));
  },

  // 저장
  saveJournal(jid) {
    const journal = this.JOURNALS[jid];
    const date   = document.getElementById('jrnDate')?.value || '';
    const worker = document.getElementById('jrnWorker')?.value || '';
    const approver = document.getElementById('jrnApprover')?.value || '';
    const results = window._prereqResults?.[jid] || {};
    const deviation = document.getElementById('jrnDeviation')?.value || '해당없음';
    const action    = document.getElementById('jrnAction')?.value || '해당없음';

    const total   = journal.items.length;
    const checked = Object.keys(results).length;
    const ngCount = Object.values(results).filter(v=>v==='X').length;

    if (checked < total) {
      if (!confirm(`아직 ${total-checked}개 항목이 미입력 상태입니다.\n계속 저장하시겠습니까?`)) return;
    }

    // 선행요건 이력 저장
    if (!HACCP_DATA.prereqLogs) HACCP_DATA.prereqLogs = [];
    HACCP_DATA.prereqLogs.unshift({
      id: `PL${Date.now()}`,
      journalId: jid,
      journalTitle: journal.title,
      date, worker, approver,
      results, deviation, action,
      ngCount, total,
      status: ngCount > 0 ? 'ng' : 'ok',
      savedAt: new Date().toLocaleString('ko-KR')
    });

    // 해당 선행요건 항목 최근 실시일 업데이트
    const catMap = {
      sanitation: '위생관리', personal: '위생관리',
      pestControl: '위생관리', foreignMatter: '위생관리',
      equipment: '설비관리', calibration: '설비관리'
    };
    const cat = catMap[jid];
    if (cat) {
      HACCP_DATA.prerequisiteItems?.forEach(p => {
        if (p.category === cat) {
          p.lastDate = date;
          p.status = ngCount > 0 ? 'warning' : 'ok';
        }
      });
    }

    App.closeModal();
    App.showToast(ngCount>0?'warning':'success',
      `${journal.title} 저장`,
      `${date} 점검 완료 (이탈: ${ngCount}건 / 전체: ${total}항목) - 담당: ${worker}`);

    App.navigate('prerequisite');
  },

  // 인쇄
  printJournal(jid) {
    const j = this.JOURNALS[jid];
    const date   = document.getElementById('jrnDate')?.value || '';
    const worker = document.getElementById('jrnWorker')?.value || '';
    const approver = document.getElementById('jrnApprover')?.value || '';
    const results = window._prereqResults?.[jid] || {};
    const deviation = document.getElementById('jrnDeviation')?.value || '해당없음';
    const action    = document.getElementById('jrnAction')?.value || '해당없음';

    const rows = j.items.map((item, i) => {
      const r = results[i] || '';
      const color = r==='O'?'#059669':r==='X'?'#dc2626':'#888';
      return `<tr>
        <td style="text-align:center;color:#888;font-size:8pt;">${i+1}</td>
        <td style="font-size:8.5pt;line-height:1.5;">${item}</td>
        <td style="text-align:center;font-weight:800;color:${color};font-size:11pt;">${r||''}</td>
      </tr>`;
    }).join('');

    const w = window.open('','_blank');
    w.document.write(`<!DOCTYPE html><html lang="ko"><head>
    <meta charset="UTF-8"/>
    <title>바이오닷 HACCP - ${j.title}</title>
    <style>
      @page{size:A4;margin:15mm 12mm;}
      *{box-sizing:border-box;margin:0;padding:0;}
      body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;font-size:9pt;color:#111;}
      .header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6mm;border-bottom:2px solid #000;padding-bottom:4mm;}
      .title{font-size:16pt;font-weight:900;letter-spacing:0.04em;}
      .subtitle{font-size:8.5pt;color:#555;margin-top:2px;}
      .company{text-align:right;font-size:8.5pt;color:#333;}
      .info-bar{display:flex;gap:6mm;margin-bottom:5mm;font-size:8.5pt;}
      .info-cell{border:1px solid #aaa;padding:3px 8px;border-radius:2px;}
      .info-cell b{color:#333;}
      table{width:100%;border-collapse:collapse;margin-bottom:5mm;}
      th{background:#f0f0f0;padding:5px 6px;text-align:center;border:1px solid #ccc;font-size:8pt;font-weight:600;}
      td{padding:5px 6px;border:1px solid #ddd;vertical-align:middle;}
      .section-title{font-size:9pt;font-weight:700;margin-bottom:3mm;color:#333;}
      .deviation-box{border:1px solid #ccc;border-radius:3px;padding:5mm;min-height:16mm;font-size:8.5pt;margin-bottom:4mm;}
      .sign-row{display:flex;gap:4mm;margin-top:5mm;}
      .sign-box{flex:1;border:1px solid #bbb;text-align:center;padding:5px;border-radius:3px;}
      .sign-box .ttl{font-size:8pt;color:#555;border-bottom:1px solid #ddd;padding-bottom:3px;margin-bottom:12px;}
      .sign-box .nm{font-size:9pt;font-weight:700;}
    </style>
    </head><body>
    <div class="header">
      <div>
        <div class="title">${j.title}</div>
        <div class="subtitle">평가기준: ${j.evaluationBase} &nbsp;|&nbsp; 점검주기: ${j.freq}</div>
      </div>
      <div class="company">
        <b>바이오닷</b><br/>
        점검일: ${date}<br/>
        출력일: ${new Date().toLocaleDateString('ko-KR')}
      </div>
    </div>
    <div class="info-bar">
      <div class="info-cell">점검일자: <b>${date}</b></div>
      <div class="info-cell">담당자: <b>${worker}</b></div>
      <div class="info-cell">확인자 (HACCP팀장): <b>${approver}</b></div>
    </div>
    <table>
      <thead><tr><th style="width:30px;">No</th><th>점검항목</th><th style="width:50px;">결과</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="section-title">● 이탈 내용 및 관리기준 이탈사항</div>
    <div class="deviation-box">${deviation}</div>
    <div class="section-title">● 개선 조치사항 및 결과</div>
    <div class="deviation-box">${action}</div>
    <div class="sign-row">
      <div class="sign-box"><div class="ttl">작성자 (담당자)</div><div class="nm">${worker}</div></div>
      <div class="sign-box"><div class="ttl">확인자 (HACCP팀장)</div><div class="nm">${approver}</div></div>
    </div>
    </body></html>`);
    w.document.close();
    setTimeout(()=>w.print(), 500);
  },

  // ─── 검교정 관리대장 모달 ──────────────────────────────────
  openCalibrationModal(j) {
    const today = new Date('2026-03-21').toISOString().split('T')[0];
    const rows = j.equipmentList.map((eq, i) => `
    <tr>
      <td style="font-weight:600;">${eq.name}</td>
      <td style="font-size:0.75rem;color:var(--text-muted);">${eq.standard}</td>
      <td class="no-wrap">${eq.lastDate}</td>
      <td class="no-wrap" style="${new Date(eq.nextDate) < new Date('2026-03-21')?'color:var(--color-danger);font-weight:700;':''}">${eq.nextDate}</td>
      <td><code style="font-size:0.72rem;">${eq.resultNo}</code></td>
      <td>
        <select class="form-control" id="cal-result-${i}" style="font-size:0.75rem;padding:0.2rem 0.4rem;width:auto;">
          <option value="pass" ${eq.result==='pass'?'selected':''}>적합</option>
          <option value="fail" ${eq.result==='fail'?'selected':''}>부적합</option>
        </select>
      </td>
    </tr>`).join('');

    App.showModal(`${j.icon} ${j.title}`,`
    <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);margin-bottom:1rem;font-size:0.8rem;color:var(--text-muted);">
      점검주기: <strong>${j.freq}</strong> &nbsp;|&nbsp; 허용오차: 저울 ±1%, 온도계 ±1°C
    </div>
    <div class="table-wrapper" style="margin-bottom:1rem;">
      <table class="data-table">
        <thead><tr><th>기기명</th><th>자체기준</th><th>최근교정일</th><th>차기예정일</th><th>성적서번호</th><th>결과</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">점검자</label>
        <select class="form-control" id="calWorker">
          ${HACCP_DATA.employees.map(e=>`<option>${e.name}</option>`).join('')}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">확인자 (HACCP팀장)</label>
        <select class="form-control" id="calApprover">
          ${HACCP_DATA.employees.map(e=>`<option ${e.role.includes('팀장')?'selected':''}>${e.name}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">특이사항</label>
      <textarea class="form-control" id="calNote" rows="2" placeholder="이상 발견 시 처리결과 기록"></textarea>
    </div>`,
    [
      { text:'취소', class:'btn-secondary', action:'App.closeModal()' },
      { text:'✔ 저장', class:'btn-primary', action:`PrerequisitePage.saveCalibration()` }
    ]);
  },

  saveCalibration() {
    const worker = document.getElementById('calWorker')?.value||'';
    const note   = document.getElementById('calNote')?.value||'';
    App.closeModal();
    App.showToast('success','검교정 저장',`검·교정 관리대장이 저장되었습니다. 담당: ${worker}`);
  },

  // ─── 실시기록 ─────────────────────────────────────────────
  recordExecution(id) {
    const item = HACCP_DATA.prerequisiteItems?.find(p=>p.id===id);
    if (!item) return;
    const today = new Date('2026-03-21').toISOString().split('T')[0];

    App.showModal(`실시기록 - ${item.name}`,`
    <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);margin-bottom:1rem;">
      <div style="font-size:0.72rem;color:var(--text-muted);">카테고리 / 주기</div>
      <div style="font-weight:700;margin-top:0.2rem;">${item.category} &nbsp;·&nbsp; ${item.frequency}</div>
    </div>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">실시일 *</label>
        <input type="date" class="form-control" id="recDate" value="${today}" required/>
      </div>
      <div class="form-group">
        <label class="form-label">담당자 *</label>
        <select class="form-control" id="recWorker" required>
          ${HACCP_DATA.employees.map(e=>`<option ${e.name===item.assignee?'selected':''}>${e.name}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">점검 결과 *</label>
      <select class="form-control" id="recResult">
        <option value="ok">정상</option>
        <option value="warning">이상 발견</option>
        <option value="ok">개선조치 완료</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">특이사항 / 개선조치</label>
      <textarea class="form-control" id="recNote" rows="3" placeholder="특이사항이 있으면 기록하세요. (없으면 '이상없음')"></textarea>
    </div>`,
    [
      { text:'취소', class:'btn-secondary', action:'App.closeModal()' },
      { text:'저장', class:'btn-primary', action:`PrerequisitePage.saveExecution('${id}')` }
    ]);
  },

  saveExecution(id) {
    const item   = HACCP_DATA.prerequisiteItems?.find(p=>p.id===id);
    if (!item) return;
    const date   = document.getElementById('recDate')?.value||'';
    const worker = document.getElementById('recWorker')?.value||'';
    const result = document.getElementById('recResult')?.value||'ok';
    const note   = document.getElementById('recNote')?.value||'이상없음';
    // 업데이트
    item.lastDate = date;
    item.status   = result;

    // 다음 예정일 계산
    const d = new Date(date);
    const freqDays = { daily:1, weekly:7, monthly:30, '6monthly':180, yearly:365 };
    d.setDate(d.getDate()+(freqDays[item.frequency]||1));
    item.nextDate = d.toISOString().split('T')[0];

    App.closeModal();
    App.showToast('success','실시기록 저장',`[${item.name}] ${date} 실시기록 완료 - ${worker}`);
    App.navigate('prerequisite');
  },

  openAddModal() {
    App.showModal('선행요건 관리항목 추가',`
    <div class="form-group">
      <label class="form-label">카테고리 *</label>
      <select class="form-control" id="addCat">
        <option>위생관리</option><option>설비관리</option>
        <option>교육훈련</option><option>보건증관리</option>
        <option>방충·방서</option><option>용수관리</option>
        <option>검교정</option><option>기타</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">관리항목명 *</label>
      <input type="text" class="form-control" id="addName" placeholder="항목명 입력" required/>
    </div>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">주기 *</label>
        <select class="form-control" id="addFreq">
          <option value="daily">매일</option><option value="weekly">매주</option>
          <option value="monthly">매월</option><option value="6monthly">반기</option>
          <option value="yearly">연1회</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">담당자 *</label>
        <select class="form-control" id="addAssignee">
          ${HACCP_DATA.employees.map(e=>`<option>${e.name}</option>`).join('')}
        </select>
      </div>
    </div>`,
    [
      { text:'취소', class:'btn-secondary', action:'App.closeModal()' },
      { text:'추가', class:'btn-primary', action:'PrerequisitePage.addItem()' }
    ]);
  },

  addItem() {
    const name     = document.getElementById('addName')?.value?.trim();
    const cat      = document.getElementById('addCat')?.value;
    const freq     = document.getElementById('addFreq')?.value;
    const assignee = document.getElementById('addAssignee')?.value;
    if (!name) { App.showToast('error','오류','항목명을 입력하세요.'); return; }
    const today = new Date('2026-03-21').toISOString().split('T')[0];
    HACCP_DATA.prerequisiteItems.push({
      id: `PR${Date.now()}`, category: cat, name, frequency: freq,
      lastDate: '', nextDate: today, assignee, status: 'ok'
    });
    App.closeModal();
    App.showToast('success','추가완료',`[${name}] 항목이 추가되었습니다.`);
    App.navigate('prerequisite');
  },

  manageHealthCards() {
    App.showToast('info','보건증 갱신','갱신 대상자에게 안내 알림이 발송되었습니다.');
  }
};
