// =============================================
// BIODOT HACCP - 기준서 관리 모듈
// PDF 뷰어 + 할일(기준서 갱신) 관리
// =============================================

const StandardsPage = {
  currentTab: 'docs',
  currentFilter: 'all',

  render() {
    const todoUrgent = (HACCP_DATA.todoItems||[]).filter(t => t.status==='pending' && t.priority==='urgent').length;
    const todoHigh   = (HACCP_DATA.todoItems||[]).filter(t => t.status==='pending' && t.priority==='high').length;

    return `
    <div class="fade-in">
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">📚 HACCP 기준서 관리</h1>
          <p class="page-desc">기준서 열람 · 갱신 스케줄 · 할일 관리</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" onclick="StandardsPage.openNewDocModal()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            기준서 등록
          </button>
        </div>
      </div>

      <!-- 긴급 할일 배너 -->
      ${todoUrgent > 0 ? `
      <div style="padding:0.75rem 1rem;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);border-radius:var(--radius-md);margin-bottom:1rem;display:flex;align-items:center;gap:0.75rem;">
        <span style="font-size:1.2rem;">🚨</span>
        <div style="flex:1;">
          <div style="font-weight:700;color:var(--color-danger);">긴급 처리 필요 항목 ${todoUrgent}건</div>
          <div style="font-size:0.78rem;color:var(--text-muted);">할일 탭에서 즉시 확인하세요.</div>
        </div>
        <button class="btn btn-sm" style="background:var(--color-danger);color:white;" onclick="StandardsPage.switchTab('todo')">확인</button>
      </div>` : ''}

      <div class="tabs">
        <button class="tab-btn ${this.currentTab==='docs'?'active':''}" onclick="StandardsPage.switchTab('docs')">📄 기준서 목록</button>
        <button class="tab-btn ${this.currentTab==='viewer'?'active':''}" onclick="StandardsPage.switchTab('viewer')">🔍 기준서 열람</button>
        <button class="tab-btn ${this.currentTab==='todo'?'active':''}" onclick="StandardsPage.switchTab('todo')">
          ✅ 할일·갱신 스케줄
          ${(todoUrgent+todoHigh)>0?`<span style="margin-left:4px;background:var(--color-danger);color:white;border-radius:10px;padding:0 5px;font-size:0.68rem;">${todoUrgent+todoHigh}</span>`:''}
        </button>
      </div>

      <div id="standardsContent">${this.renderContent()}</div>
    </div>`;
  },

  renderContent() {
    if (this.currentTab === 'docs')   return this.renderDocs();
    if (this.currentTab === 'viewer') return this.renderViewer();
    return this.renderTodo();
  },

  // ─── 기준서 목록 ─────────────────────────────────────────────
  renderDocs() {
    const docs = HACCP_DATA.standardsDocs || [];
    const today = new Date('2026-03-21');

    return `
    <!-- KPI -->
    <div class="kpi-grid" style="margin-bottom:1.25rem;">
      <div class="kpi-card primary"><div class="kpi-value">${docs.length}</div><div class="kpi-label">총 기준서</div></div>
      <div class="kpi-card success"><div class="kpi-value">${docs.filter(d=>d.status==='current').length}</div><div class="kpi-label">현행 기준서</div></div>
      <div class="kpi-card warning"><div class="kpi-value">${docs.filter(d=>d.status==='pending').length}</div><div class="kpi-label">작성 예정</div></div>
      <div class="kpi-card ${docs.some(d=>new Date(d.nextReviewDate)<today)?'danger':'info'}">
        <div class="kpi-value">${docs.filter(d=>new Date(d.nextReviewDate)<today).length}</div>
        <div class="kpi-label">갱신 초과</div>
      </div>
    </div>

    <div style="display:grid;gap:1rem;">
      ${docs.map(doc => {
        const reviewDate = new Date(doc.nextReviewDate);
        const daysLeft = Math.ceil((reviewDate - today) / 86400000);
        const isOverdue = daysLeft < 0;
        const isSoon    = daysLeft >= 0 && daysLeft <= 90;
        const statusColor = isOverdue ? 'var(--color-danger)' : isSoon ? 'var(--color-warning)' : 'var(--color-success)';
        const statusLabel = isOverdue ? `D+${Math.abs(daysLeft)} 초과` : `D-${daysLeft}`;
        const catColor = doc.category === '핵심기준서' ? 'var(--brand-primary)' : 'var(--text-muted)';

        return `
        <div class="card" style="border-left:4px solid ${doc.status==='current'?'var(--color-success)':'var(--border-subtle)'};">
          <div style="display:flex;align-items:flex-start;gap:1rem;flex-wrap:wrap;">
            <!-- 아이콘 -->
            <div style="width:52px;height:60px;background:${doc.status==='current'?'rgba(16,185,129,0.1)':'var(--bg-elevated)'};border-radius:var(--radius-md);display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0;font-size:1.5rem;">
              ${doc.status==='current'?'📋':'📝'}
            </div>
            <!-- 정보 -->
            <div style="flex:1;min-width:200px;">
              <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.3rem;">
                <span style="font-weight:800;font-size:0.95rem;">${doc.title}</span>
                <span style="font-size:0.68rem;padding:0.15rem 0.5rem;border-radius:10px;background:${catColor}22;color:${catColor};font-weight:600;">${doc.category}</span>
                <span class="badge ${doc.status==='current'?'badge-success':'badge-neutral'}">${doc.status==='current'?'현행':'작성예정'}</span>
              </div>
              <div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.5rem;">${doc.description}</div>
              <div style="display:flex;gap:1rem;flex-wrap:wrap;font-size:0.72rem;color:var(--text-muted);">
                <span>버전: <strong>${doc.version}</strong></span>
                <span>승인일: <strong>${doc.approvedDate}</strong></span>
                <span>승인자: <strong>${doc.approver}</strong></span>
                ${doc.pages > 0 ? `<span>페이지: <strong>${doc.pages}p</strong></span>` : ''}
              </div>
            </div>
            <!-- 갱신일 + 액션 -->
            <div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.5rem;flex-shrink:0;">
              <div style="text-align:right;">
                <div style="font-size:0.68rem;color:var(--text-muted);">다음 검토일</div>
                <div style="font-weight:700;color:${statusColor};">${doc.nextReviewDate}</div>
                <div style="font-size:0.72rem;color:${statusColor};font-weight:600;">${statusLabel}</div>
              </div>
              <div style="display:flex;gap:0.4rem;">
                ${doc.path ? `
                <button class="btn btn-primary btn-sm" onclick="StandardsPage.viewDoc('${doc.id}')">
                  🔍 열람
                </button>` : `
                <button class="btn btn-secondary btn-sm" onclick="StandardsPage.openNewDocModal('${doc.id}')">
                  📎 파일 등록
                </button>`}
                <button class="btn btn-secondary btn-sm" onclick="StandardsPage.openRenewModal('${doc.id}')">
                  🔄 갱신 기록
                </button>
              </div>
            </div>
          </div>
          ${doc.chapters.length > 0 ? `
          <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid var(--border-subtle);">
            <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.4rem;">목차</div>
            <div style="display:flex;flex-wrap:wrap;gap:0.3rem;">
              ${doc.chapters.map(ch => `
              <span style="font-size:0.7rem;padding:0.15rem 0.5rem;background:var(--bg-elevated);border-radius:4px;cursor:pointer;"
                onclick="StandardsPage.viewDocChapter('${doc.id}','${ch.no}')"
                title="${ch.pages}페이지">
                ${ch.no}. ${ch.title}
              </span>`).join('')}
            </div>
          </div>` : ''}
        </div>`;
      }).join('')}
    </div>`;
  },

  // ─── 기준서 열람 (PDF iframe) ────────────────────────────────
  renderViewer(docId) {
    const doc = docId
      ? HACCP_DATA.standardsDocs.find(d => d.id === docId)
      : HACCP_DATA.standardsDocs.find(d => d.status === 'current');

    if (!doc || !doc.path) {
      return `
      <div class="empty-state">
        <div style="font-size:3rem;margin-bottom:1rem;">📋</div>
        <h3>열람할 기준서를 선택하세요</h3>
        <p>기준서 목록에서 "열람" 버튼을 클릭하거나, 아래에서 선택하세요.</p>
        <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:0.5rem;margin-top:1rem;">
          ${HACCP_DATA.standardsDocs.filter(d=>d.path).map(d=>`
          <button class="btn btn-primary" onclick="StandardsPage.viewDoc('${d.id}')">${d.title}</button>`).join('')}
        </div>
      </div>`;
    }

    this._viewingDocId = doc.id;
    const pdfPath = doc.path;

    return `
    <div style="display:flex;gap:0.75rem;height:calc(100vh - 280px);">
      <!-- 사이드 목차 -->
      <div style="width:200px;flex-shrink:0;background:var(--bg-elevated);border-radius:var(--radius-md);padding:0.75rem;overflow-y:auto;">
        <div style="font-size:0.72rem;font-weight:700;color:var(--text-muted);margin-bottom:0.5rem;">📋 ${doc.title}</div>
        <div style="font-size:0.68rem;color:var(--text-muted);margin-bottom:0.75rem;">${doc.version} · ${doc.pages}p</div>
        ${doc.chapters.map(ch => `
        <div style="padding:0.4rem 0.5rem;border-radius:4px;cursor:pointer;font-size:0.76rem;margin-bottom:2px;transition:background 0.1s;"
          onclick="StandardsPage.gotoChapter('${ch.pages}')"
          onmouseenter="this.style.background='var(--bg-card-hover)'"
          onmouseleave="this.style.background='transparent'">
          <span style="color:var(--text-muted);margin-right:0.3rem;">${ch.no}.</span>${ch.title}
          <div style="font-size:0.65rem;color:var(--text-muted);">p.${ch.pages}</div>
        </div>`).join('')}
        <hr style="margin:0.75rem 0;border-color:var(--border-subtle);">
        <button class="btn btn-secondary btn-sm" style="width:100%;font-size:0.72rem;"
          onclick="StandardsPage.openRenewModal('${doc.id}')">🔄 갱신 기록</button>
        <button class="btn btn-secondary btn-sm" style="width:100%;margin-top:0.4rem;font-size:0.72rem;"
          onclick="window.open('${pdfPath}','_blank')">⬇️ PDF 다운로드</button>
      </div>

      <!-- PDF 뷰어 -->
      <div style="flex:1;border-radius:var(--radius-md);overflow:hidden;border:1px solid var(--border-subtle);">
        <div id="pdfViewerBar" style="padding:0.4rem 0.75rem;background:var(--bg-elevated);border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;gap:0.5rem;flex-shrink:0;">
          <span style="font-size:0.75rem;font-weight:600;">${doc.title}</span>
          <span style="font-size:0.68rem;color:var(--text-muted);margin-left:auto;">${doc.approvedDate} 승인 · ${doc.approver}</span>
        </div>
        <iframe id="pdfFrame"
          src="${pdfPath}"
          style="width:100%;height:calc(100% - 36px);border:none;"
          title="${doc.title}">
          <p>PDF를 표시할 수 없습니다.
            <a href="${pdfPath}" target="_blank">여기서 직접 열기</a>
          </p>
        </iframe>
      </div>
    </div>`;
  },

  // ─── 할일 / 갱신 스케줄 ──────────────────────────────────────
  renderTodo() {
    const todos = HACCP_DATA.todoItems || [];
    const categories = [...new Set(todos.map(t=>t.category))];
    const today = new Date('2026-03-21');

    const priorityMeta = {
      urgent: { label:'긴급', color:'var(--color-danger)',  badge:'badge-danger'  },
      high:   { label:'높음', color:'var(--color-warning)', badge:'badge-warning' },
      medium: { label:'보통', color:'var(--brand-primary)', badge:'badge-neutral' },
      low:    { label:'낮음', color:'var(--text-muted)',    badge:'badge-neutral' },
    };

    const catFilter = this.currentFilter;
    const filtered = catFilter === 'all' ? todos : todos.filter(t=>t.category===catFilter);
    const pending  = filtered.filter(t=>t.status==='pending');
    const done     = filtered.filter(t=>t.status==='done');

    return `
    <!-- 필터 -->
    <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-bottom:1rem;">
      ${['all',...categories].map(cat=>`
      <button class="btn btn-sm ${this.currentFilter===cat?'btn-primary':'btn-secondary'}"
        onclick="StandardsPage.setFilter('${cat}')">
        ${cat==='all'?'전체':cat}
      </button>`).join('')}
      <div style="flex:1;"></div>
      <button class="btn btn-primary btn-sm" onclick="StandardsPage.openAddTodoModal()">
        + 할일 추가
      </button>
    </div>

    <!-- 미완료 -->
    <div style="font-weight:700;font-size:0.82rem;color:var(--text-secondary);margin-bottom:0.5rem;">
      📌 미완료 (${pending.length}건)
    </div>
    <div style="display:grid;gap:0.5rem;margin-bottom:1.25rem;">
      ${pending.length === 0
        ? `<div style="padding:1.5rem;text-align:center;color:var(--text-muted);font-size:0.85rem;">🎉 미완료 할일이 없습니다!</div>`
        : pending.sort((a,b) => {
            const pOrd = {urgent:0,high:1,medium:2,low:3};
            return (pOrd[a.priority]||2) - (pOrd[b.priority]||2) || a.dueDate.localeCompare(b.dueDate);
          }).map(todo => {
          const pm = priorityMeta[todo.priority] || priorityMeta.medium;
          const dueDate = new Date(todo.dueDate);
          const daysLeft = Math.ceil((dueDate - today) / 86400000);
          const isOverdue = daysLeft < 0;
          const dueLbl = isOverdue ? `${Math.abs(daysLeft)}일 초과` : daysLeft === 0 ? '오늘 마감' : `D-${daysLeft}`;
          const dueColor = isOverdue ? 'var(--color-danger)' : daysLeft <= 7 ? 'var(--color-warning)' : 'var(--text-muted)';
          const relDoc = todo.relatedDoc ? HACCP_DATA.standardsDocs?.find(d=>d.id===todo.relatedDoc) : null;

          return `
          <div style="display:flex;align-items:flex-start;gap:0.75rem;padding:0.85rem;background:var(--bg-card);border:1px solid var(--border-subtle);border-left:4px solid ${pm.color};border-radius:var(--radius-md);transition:all 0.15s;"
            onmouseenter="this.style.background='var(--bg-card-hover)'" onmouseleave="this.style.background='var(--bg-card)'">
            <!-- 체크 -->
            <button onclick="StandardsPage.completeTodo('${todo.id}')"
              style="width:22px;height:22px;border-radius:50%;border:2px solid ${pm.color};background:transparent;cursor:pointer;flex-shrink:0;margin-top:1px;transition:all 0.15s;"
              title="완료 처리"
              onmouseenter="this.style.background='${pm.color}33'"
              onmouseleave="this.style.background='transparent'">
            </button>
            <!-- 내용 -->
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.25rem;">
                <span style="font-weight:700;font-size:0.88rem;">${todo.title}</span>
                <span class="badge ${pm.badge}" style="font-size:0.65rem;">${pm.label}</span>
                <span style="font-size:0.68rem;padding:0.1rem 0.4rem;border-radius:4px;background:var(--bg-elevated);">${todo.category}</span>
                ${todo.repeat !== 'once' ? `<span style="font-size:0.65rem;color:var(--text-muted);">🔁 ${todo.repeat==='yearly'?'연간':todo.repeat==='monthly'?'월간':'반복'}</span>` : ''}
              </div>
              <div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.35rem;">${todo.desc}</div>
              <div style="display:flex;gap:0.75rem;font-size:0.7rem;align-items:center;flex-wrap:wrap;">
                <span>📅 <span style="color:${dueColor};font-weight:600;">${todo.dueDate} (${dueLbl})</span></span>
                <span>👤 ${todo.assignee}</span>
                ${relDoc ? `<span>📋 <a href="#" onclick="StandardsPage.viewDoc('${relDoc.id}');return false;" style="color:var(--brand-primary);text-decoration:none;">${relDoc.title}</a></span>` : ''}
              </div>
            </div>
            <!-- 액션 -->
            <div style="display:flex;gap:0.3rem;flex-shrink:0;">
              <button class="btn btn-secondary btn-sm" onclick="StandardsPage.editTodo('${todo.id}')" style="font-size:0.7rem;padding:0.2rem 0.45rem;">수정</button>
            </div>
          </div>`;
        }).join('')}
    </div>

    <!-- 완료 -->
    ${done.length > 0 ? `
    <div style="font-weight:700;font-size:0.82rem;color:var(--text-muted);margin-bottom:0.5rem;">
      ✅ 완료 (${done.length}건)
    </div>
    <div style="display:grid;gap:0.4rem;">
      ${done.map(todo => `
      <div style="display:flex;align-items:center;gap:0.75rem;padding:0.6rem 0.85rem;background:var(--bg-elevated);border-radius:var(--radius-md);opacity:0.65;">
        <span style="font-size:1rem;flex-shrink:0;">✅</span>
        <div style="flex:1;">
          <span style="font-size:0.82rem;text-decoration:line-through;">${todo.title}</span>
          <span style="font-size:0.68rem;color:var(--text-muted);margin-left:0.5rem;">${todo.category}</span>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="StandardsPage.undoTodo('${todo.id}')" style="font-size:0.68rem;padding:0.15rem 0.4rem;">되돌리기</button>
      </div>`).join('')}
    </div>` : ''}`;
  },

  // ─── 탭 전환 ────────────────────────────────────────────────
  switchTab(tab) {
    this.currentTab = tab;
    document.querySelectorAll('.tab-btn').forEach((btn,i)=>{
      btn.classList.toggle('active', ['docs','viewer','todo'][i]===tab);
    });
    document.getElementById('standardsContent').innerHTML = this.renderContent();
  },

  setFilter(cat) {
    this.currentFilter = cat;
    document.getElementById('standardsContent').innerHTML = this.renderContent();
  },

  // ─── 기준서 열람 ─────────────────────────────────────────────
  viewDoc(docId) {
    this.currentTab = 'viewer';
    this._viewingDocId = docId;
    document.querySelectorAll('.tab-btn').forEach((btn,i)=>{
      btn.classList.toggle('active', i===1);
    });
    document.getElementById('standardsContent').innerHTML = this.renderViewer(docId);
  },

  viewDocChapter(docId, chapterNo) {
    this.viewDoc(docId);
    // iframe 로드 후 페이지 이동은 브라우저 PDF 뷰어에서 지원 안 될 수 있음
  },

  gotoChapter(pages) {
    const frame = document.getElementById('pdfFrame');
    if (!frame) return;
    const startPage = parseInt(pages.split('~')[0]);
    if (!isNaN(startPage)) {
      const src = frame.src.split('#')[0];
      frame.src = `${src}#page=${startPage}`;
    }
  },

  // ─── 할일 완료/되돌리기 ──────────────────────────────────────
  completeTodo(id) {
    const todo = HACCP_DATA.todoItems?.find(t=>t.id===id);
    if (!todo) return;
    todo.status = 'done';
    todo.completedAt = new Date('2026-03-21').toISOString().split('T')[0];
    App.showToast('success','완료','할일이 완료 처리되었습니다.');
    document.getElementById('standardsContent').innerHTML = this.renderContent();
  },

  undoTodo(id) {
    const todo = HACCP_DATA.todoItems?.find(t=>t.id===id);
    if (!todo) return;
    todo.status = 'pending';
    document.getElementById('standardsContent').innerHTML = this.renderContent();
  },

  // ─── 할일 추가 모달 ─────────────────────────────────────────
  openAddTodoModal() {
    App.showModal('✅ 할일 추가',`
    <div class="form-group">
      <label class="form-label">제목 *</label>
      <input type="text" class="form-control" id="tdTitle" placeholder="할일 제목"/>
    </div>
    <div class="form-group">
      <label class="form-label">내용·설명</label>
      <textarea class="form-control" id="tdDesc" rows="2" placeholder="상세 내용"></textarea>
    </div>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">카테고리</label>
        <select class="form-control" id="tdCat">
          <option>기준서갱신</option><option>정기점검</option><option>검교정</option><option>교육훈련</option><option>기타</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">우선순위</label>
        <select class="form-control" id="tdPri">
          <option value="urgent">긴급</option><option value="high">높음</option>
          <option value="medium" selected>보통</option><option value="low">낮음</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">마감일 *</label>
        <input type="date" class="form-control" id="tdDue" value="2026-04-30"/>
      </div>
      <div class="form-group">
        <label class="form-label">담당자</label>
        <select class="form-control" id="tdAssignee">
          ${HACCP_DATA.employees.map(e=>`<option>${e.name}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">반복 주기</label>
      <select class="form-control" id="tdRepeat">
        <option value="once">1회성</option><option value="monthly">매월</option>
        <option value="yearly">연간</option>
      </select>
    </div>`,
    [
      { text:'취소', class:'btn-secondary', action:'App.closeModal()' },
      { text:'추가', class:'btn-primary', action:'StandardsPage.saveTodo()' }
    ]);
  },

  saveTodo() {
    const title = document.getElementById('tdTitle')?.value?.trim();
    if (!title) { App.showToast('error','오류','제목을 입력하세요.'); return; }
    HACCP_DATA.todoItems.push({
      id: `TD${Date.now()}`,
      category: document.getElementById('tdCat')?.value || '기타',
      title,
      desc: document.getElementById('tdDesc')?.value || '',
      dueDate: document.getElementById('tdDue')?.value || '',
      assignee: document.getElementById('tdAssignee')?.value || '',
      priority: document.getElementById('tdPri')?.value || 'medium',
      status: 'pending',
      relatedDoc: null,
      repeat: document.getElementById('tdRepeat')?.value || 'once'
    });
    App.closeModal();
    App.showToast('success','추가 완료','할일이 추가되었습니다.');
    this.currentTab = 'todo';
    document.getElementById('standardsContent').innerHTML = this.renderContent();
  },

  editTodo(id) {
    App.showToast('info','수정','할일 수정 기능 (추후 구현)');
  },

  // ─── 기준서 갱신 기록 모달 ───────────────────────────────────
  openRenewModal(docId) {
    const doc = HACCP_DATA.standardsDocs?.find(d=>d.id===docId);
    if (!doc) return;
    App.showModal(`🔄 기준서 갱신 기록 - ${doc.title}`,`
    <div style="padding:0.75rem;background:var(--bg-elevated);border-radius:var(--radius-md);margin-bottom:1rem;">
      <div style="font-size:0.72rem;color:var(--text-muted);">현재 버전</div>
      <div style="font-weight:700;">${doc.version} · 승인일 ${doc.approvedDate}</div>
    </div>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">신규 버전명 *</label>
        <input type="text" class="form-control" id="rnVersion" placeholder="예: v2026.08" value="${doc.version}"/>
      </div>
      <div class="form-group">
        <label class="form-label">갱신 승인일 *</label>
        <input type="date" class="form-control" id="rnDate" value="2026-03-21"/>
      </div>
      <div class="form-group">
        <label class="form-label">다음 검토 예정일 *</label>
        <input type="date" class="form-control" id="rnNext" value="${doc.nextReviewDate}"/>
      </div>
      <div class="form-group">
        <label class="form-label">승인자</label>
        <input type="text" class="form-control" id="rnApprover" value="${doc.approver}"/>
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">주요 변경사항 *</label>
      <textarea class="form-control" id="rnChanges" rows="3" placeholder="변경된 내용을 기록하세요…"></textarea>
    </div>`,
    [
      { text:'취소', class:'btn-secondary', action:'App.closeModal()' },
      { text:'갱신 완료', class:'btn-primary', action:`StandardsPage.saveRenew('${docId}')` }
    ]);
  },

  saveRenew(docId) {
    const doc = HACCP_DATA.standardsDocs?.find(d=>d.id===docId);
    if (!doc) return;
    const ver     = document.getElementById('rnVersion')?.value?.trim();
    const date    = document.getElementById('rnDate')?.value;
    const next    = document.getElementById('rnNext')?.value;
    const approver= document.getElementById('rnApprover')?.value;
    const changes = document.getElementById('rnChanges')?.value;
    if (!ver || !date || !next) { App.showToast('error','오류','필수 항목을 입력하세요.'); return; }
    doc.version = ver;
    doc.approvedDate = date;
    doc.nextReviewDate = next;
    doc.approver = approver;
    doc.status = 'current';
    App.closeModal();
    App.showToast('success','갱신 완료',`[${doc.title}] ${ver}으로 갱신되었습니다.`);
    document.getElementById('standardsContent').innerHTML = this.renderContent();
  },

  openNewDocModal(docId) {
    App.showToast('info','기준서 등록','파일 업로드 기능은 다음 버전에서 지원됩니다.');
  }
};
