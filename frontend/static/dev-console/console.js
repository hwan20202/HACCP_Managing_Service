// =============================================
// 개발 콘솔 (개발 설정 전용) — dev-notes/common/dev-console.md
// ① 조작 → ② API(요청/응답) → ③ 처리 로직(trace, 도식 비교) → ④ DB 반영(실행 전/후)
// =============================================
(function () {
  const api = window.HaccpApi;
  const $ = (sel) => document.querySelector(sel);
  const esc = (v) => String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const pretty = (v) => {
    if (v === null || v === undefined || v === '') return '';
    if (typeof v === 'string') { try { return JSON.stringify(JSON.parse(v), null, 2); } catch (e) { return v; } }
    return JSON.stringify(v, null, 2);
  };

  // ---------------------------------------------------------------- 기능 정의
  const FUNCS = {
    list: { label: '문서 목록 (F04)', method: 'GET', flow: 'DOC-LST', uses: ['query'], path: (s) => `documents${s.query ? `?${s.query}` : ''}` },
    get: { label: '문서 상세 (F05)', method: 'GET', flow: 'DOC-GET', uses: ['id'], path: (s) => `documents/${s.id}`, doc: (s) => s.id },
    create: { label: '문서 작성 (F06)', method: 'POST', flow: 'DOC-CRT', uses: ['body'], path: () => 'documents', doc: (s, r) => r && r.ok && r.data.document_id },
    update: { label: '문서 수정 (F07)', method: 'PATCH', flow: 'DOC-UPD', uses: ['id', 'body'], path: (s) => `documents/${s.id}`, doc: (s) => s.id },
    delete: { label: '문서 삭제 (F08)', method: 'DELETE', flow: 'DOC-DEL', uses: ['id'], path: (s) => `documents/${s.id}`, doc: (s) => s.id },
    staff: { label: 'staff 목록 (F01)', method: 'GET', flow: 'DOC-STF', uses: [], path: () => 'staff' },
    templates: { label: '양식 목록 (F02)', method: 'GET', flow: 'DOC-TPL-LIST', uses: [], path: () => 'templates' },
    template: { label: '양식 상세 (F03)', method: 'GET', flow: 'DOC-TPL-GET', uses: ['id'], path: (s) => `templates/${s.id}` },
  };

  const state = { flows: {}, history: [], active: null, preset: null };

  // ---------------------------------------------------------------- 개발 API (기록하지 않는 직접 호출)
  async function devGet(path) {
    const r = await fetch(path, { headers: { Accept: 'application/json' } });
    return r.ok ? r.json() : null;
  }
  const snapshot = (id) => (id ? devGet(`/api/dev/snapshot?document_id=${id}`) : Promise.resolve(null));
  async function quietGet(path) {
    const r = await fetch(`/api/v1/${path}`, { headers: { Accept: 'application/json' } });
    return r.ok ? r.json() : null;
  }

  // ---------------------------------------------------------------- 실행
  function readSpec() {
    let body = null;
    const raw = $('#dcBody').value.trim();
    if (FUNCS[$('#dcFunc').value].uses.includes('body') && raw) body = raw;
    return {
      func: $('#dcFunc').value, id: $('#dcId').value.trim(), query: $('#dcQuery').value.trim(),
      body, staff: api.staffId,
    };
  }

  async function execute(spec, { before } = {}) {
    const fn = FUNCS[spec.func];
    const docBefore = fn.doc ? fn.doc(spec, null) : null;
    const snapBefore = before !== undefined ? before : await snapshot(docBefore);
    const record = await api.request(fn.method, fn.path(spec), spec.body, { staffId: spec.staff });
    let trace = record.data && typeof record.data === 'object' && record.data.trace;
    if (!trace && record.traceId) trace = await devGet(`/api/dev/traces/${record.traceId}`);
    const docAfter = fn.doc ? fn.doc(spec, record) : null;
    const snapAfter = await snapshot(docAfter || docBefore);
    const entry = { spec, fn, record, trace, before: snapBefore, after: snapAfter, docId: docAfter || docBefore, preset: state.preset };
    state.history.push(entry);
    return entry;
  }

  async function run() {
    const btn = $('#dcRun');
    btn.disabled = true;
    $('#dcRunHint').textContent = '실행 중…';
    try {
      const preset = state.preset;
      if (preset && preset.script) {
        await preset.script(execute);
      } else {
        const spec = readSpec();
        if (spec.body) { try { JSON.parse(spec.body); } catch (e) { $('#dcRunHint').textContent = '본문 JSON 형식 오류'; return; } }
        await execute(spec);
      }
      show(state.history[state.history.length - 1]);
      $('#dcRunHint').textContent = '';
    } finally {
      btn.disabled = false;
      renderHistory();
    }
  }

  // ---------------------------------------------------------------- ② API
  function renderApi(entry) {
    const { record } = entry;
    const reqHeaders = Object.entries(record.request.headers).map(([k, v]) => `${k}: ${v}`).join('\n');
    let resBody = record.data;
    if (resBody && typeof resBody === 'object' && resBody.trace) { resBody = { ...resBody }; delete resBody.trace; }
    $('#dcApiBody').innerHTML = `
      <div class="dc-line"><span class="dc-method">▶ ${esc(record.request.method)}</span><span class="dc-code">${esc(record.request.url)}</span></div>
      <div class="dc-sub">요청 헤더</div><pre class="dc-pre">${esc(reqHeaders)}</pre>
      ${record.request.body ? `<div class="dc-sub">요청 본문</div><pre class="dc-pre">${esc(pretty(record.request.body))}</pre>` : ''}
      <div class="dc-line" style="margin-top:.5rem"><span class="${record.ok ? 'dc-status-ok' : 'dc-status-err'}">◀ ${record.status} ${esc(record.statusText || '')}</span>
        <span class="te-hint">${record.ms} ms</span>${record.traceId ? `<span class="te-hint">X-Trace-Id: ${esc(record.traceId)}</span>` : ''}</div>
      <div class="dc-sub">응답 본문 ${record.data && record.data.trace ? '(trace는 ③ 패널)' : ''}</div>
      <pre class="dc-pre">${record.status === 204 ? '(본문 없음 — 204 No Content)' : esc(pretty(resBody))}</pre>`;
  }

  // ---------------------------------------------------------------- ③ 처리 로직
  function compareFlow(flowId, steps) {
    const expected = state.flows[flowId] || [];
    const byId = Object.fromEntries(steps.map((s) => [s.step_id, s]));
    const chips = expected.map((id) => ({ id, cls: byId[id] ? byId[id].result : 'none' }));
    steps.filter((s) => !expected.includes(s.step_id)).forEach((s) => chips.push({ id: s.step_id, cls: s.result === 'fail' ? 'fail extra' : 'extra' }));
    const mainRun = steps.map((s) => s.step_id).filter((id) => !id.endsWith('a'));
    const inOrder = mainRun.every((id, i) => expected[i] === id);
    const failed = steps.find((s) => s.result === 'fail');
    const reached = expected.filter((id) => byId[id]).length;
    let summary;
    if (!inOrder) summary = `<span class="dc-status-err">⚠ 순서 불일치 — 도식(${flowId})과 실행 순서가 다릅니다</span>`;
    else if (failed) summary = `<span class="dc-status-err">실패 경로: ${esc(failed.step_id)}에서 중단 (${reached}/${expected.length} 단계)</span>`;
    else if (reached === expected.length) summary = `<span class="dc-status-ok">도식 일치 ✅ ${reached}/${expected.length}</span>`;
    else summary = `<span class="dc-status-err">⚠ 누락 단계 있음 (${reached}/${expected.length})</span>`;
    return { chips, summary };
  }

  function renderTrace(entry) {
    const { trace, fn } = entry;
    if (!trace) {
      $('#dcFlowSummary').innerHTML = '';
      $('#dcFlowChips').innerHTML = '';
      $('#dcTraceBody').innerHTML = '<div class="dc-empty">trace가 없습니다(개발 콘솔 설정이 꺼져 있거나 만료됨).</div>';
      return;
    }
    const { chips, summary } = compareFlow(fn.flow, trace.steps);
    $('#dcFlowSummary').innerHTML = `${summary} <span class="te-hint">도식 ${esc(fn.flow)} · trace ${esc(trace.trace_id)}</span>`;
    $('#dcFlowChips').innerHTML = chips.map((c) => `<span class="dc-chip ${c.cls}" title="${c.cls}">${esc(c.id)}</span>`).join('');
    const rows = trace.steps.map((s, i) => `
      <tr>
        <td>${i + 1}</td><td class="mono">${esc(s.step_id)}</td>
        <td><span class="dc-layer ${esc(s.layer)}">${esc(s.layer)}</span></td>
        <td>${esc(s.name)}</td>
        <td class="dc-res-${esc(s.result)}">${{ pass: '통과', skip: '건너뜀', fail: '실패' }[s.result] || esc(s.result)}${s.detail ? `<div class="te-hint">${esc(s.detail)}</div>` : ''}</td>
        <td class="mono">${s.sql.length ? `<ol class="dc-sql">${s.sql.map((q) => `<li><details><summary>${esc(q.sql.slice(0, 110))}${q.sql.length > 110 ? '…' : ''} <span class="te-hint">${q.ms}ms</span></summary><pre class="dc-pre">${esc(q.sql)}\n\nparams: ${esc(JSON.stringify(q.params))}</pre></details></li>`).join('')}</ol>` : '<span class="te-hint">-</span>'}</td>
      </tr>`).join('');
    const extra = trace.unassigned_sql.length ? `<div class="te-hint">단계 밖 SQL ${trace.unassigned_sql.length}건: ${trace.unassigned_sql.map((q) => esc(q.sql)).join(' / ')}</div>` : '';
    $('#dcTraceBody').innerHTML = `<table class="dc-table"><thead><tr><th>#</th><th>단계 ID</th><th>계층</th><th>이름</th><th>결과</th><th>SQL</th></tr></thead><tbody>${rows || '<tr><td colspan="6">기록된 단계 없음</td></tr>'}</tbody></table>${extra}`;
  }

  // ---------------------------------------------------------------- ④ DB 반영
  const PK = { document: 'document_id', doc_section: 'section_id', document_template: 'template_id', staff: 'staff_id' };

  function cellDiff(a, b) {
    if (a && b && typeof a === 'object' && typeof b === 'object') {
      const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
      const parts = keys.filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k])).map((k) => {
        if (!(k in a)) return `<span class="dc-new">+${esc(k)}: ${esc(JSON.stringify(b[k]))}</span>`;
        if (!(k in b)) return `<span class="dc-old">${esc(k)}: ${esc(JSON.stringify(a[k]))}</span>`;
        return `${esc(k)}: <span class="dc-old">${esc(JSON.stringify(a[k]))}</span> → <span class="dc-new">${esc(JSON.stringify(b[k]))}</span>`;
      });
      return parts.join('<br>');
    }
    return `<span class="dc-old">${esc(fmt(a))}</span> → <span class="dc-new">${esc(fmt(b))}</span>`;
  }
  const fmt = (v) => (v === null || v === undefined ? 'NULL' : typeof v === 'object' ? JSON.stringify(v) : String(v));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  function diffTable(name, beforeRows, afterRows, onlyChanged) {
    const pk = PK[name];
    const before = Object.fromEntries((beforeRows || []).map((r) => [r[pk], r]));
    const after = Object.fromEntries((afterRows || []).map((r) => [r[pk], r]));
    const ids = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    const cols = [...new Set([...(beforeRows || []), ...(afterRows || [])].flatMap((r) => Object.keys(r)))];
    let counts = { added: 0, removed: 0, changed: 0 };
    const rows = ids.map((id) => {
      const a = before[id]; const b = after[id];
      let kind = '';
      if (!a) kind = 'added'; else if (!b) kind = 'removed'; else if (cols.some((c) => !same(a[c], b[c]))) kind = 'changed';
      if (kind) counts[kind] += 1;
      if (onlyChanged && !kind) return '';
      const cells = cols.map((c) => {
        if (kind === 'changed' && !same(a[c], b[c])) return `<td class="dc-cell-changed mono">${cellDiff(a[c], b[c])}</td>`;
        return `<td class="mono">${esc(fmt((b || a)[c]))}</td>`;
      }).join('');
      return `<tr class="${kind ? `dc-${kind}` : ''}"><td>${{ added: '+ 추가', removed: '− 삭제', changed: '~ 변경' }[kind] || ''}</td>${cells}</tr>`;
    }).join('');
    const label = `+${counts.added} −${counts.removed} ~${counts.changed}`;
    if (!rows) return `<div class="dc-db-table"><div class="dc-db-name">${name} <span class="te-hint">변화 없음 (${(afterRows || beforeRows || []).length}행)</span></div></div>`;
    return `<div class="dc-db-table"><div class="dc-db-name">${name} <span class="te-hint">${label}</span></div>
      <div class="te-table-wrap"><table class="dc-table"><thead><tr><th></th>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  function renderDb(entry) {
    const onlyChanged = $('#dcOnlyChanged').checked;
    const { before, after, docId } = entry;
    if (!docId) {
      $('#dcDbTitle').textContent = '';
      $('#dcDbBody').innerHTML = '<div class="dc-empty">문서 단위 기능이 아니라서(목록·양식·staff) 비교할 행이 없습니다. 조회 기능은 DB를 바꾸지 않습니다.</div>';
      return;
    }
    const b = (before && before.tables) || {};
    const a = (after && after.tables) || {};
    $('#dcDbTitle').innerHTML = `document_id = ${esc(docId)} ${after && after.deleted ? '<span class="dc-deleted-flag">· 논리 삭제됨 (업무 API는 404)</span>' : ''} ${!before || !before.exists ? '<span class="te-hint">· 실행 전 없음</span>' : ''}`;
    $('#dcDbBody').innerHTML = ['document', 'doc_section', 'document_template', 'staff'].map((t) => diffTable(t, b[t], a[t], onlyChanged)).join('');
  }

  // ---------------------------------------------------------------- 이력
  function show(entry) {
    if (!entry) return;
    state.active = entry;
    renderApi(entry);
    renderTrace(entry);
    renderDb(entry);
    renderHistory();
  }

  function renderHistory() {
    $('#dcHistoryBody').innerHTML = state.history.slice().reverse().map((e) => {
      const i = state.history.indexOf(e);
      const t = e.record.at.toTimeString().slice(0, 8);
      return `<div class="dc-tl-item ${e === state.active ? 'active' : ''}" data-i="${i}">
        <span class="te-hint">${t}</span><span class="dc-method">${esc(e.record.request.method)}</span>
        <span class="${e.record.ok ? 'dc-status-ok' : 'dc-status-err'}">${e.record.status}</span>
        <span class="mono">${esc(e.record.request.url)}</span>
        ${e.preset ? `<span class="badge badge-info">${esc(e.preset.id)}</span>` : ''}</div>`;
    }).join('') || '<div class="dc-empty">호출이 없습니다.</div>';
    document.querySelectorAll('.dc-tl-item').forEach((el) => el.addEventListener('click', () => show(state.history[Number(el.dataset.i)])));
  }

  // ---------------------------------------------------------------- 프리셋 (s1-screens.md 6장 DOC-PS-01~14)
  async function ccpTemplateId() {
    const t = await quietGet('templates');
    const ccp = t && t.items.find((x) => x.type_code === 'CCP_MONITORING');
    return ccp ? ccp.template_id : 1;
  }
  async function inactiveTemplateId() {
    for (let i = 1; i <= 30; i += 1) {
      const t = await quietGet(`templates/${i}`);
      if (t && !t.is_active) return i;
    }
    return null;
  }
  async function findDoc(status, pred = () => true) {
    const r = await quietGet(`documents?status=${status}`);
    let page = 1;
    let items = r ? r.items : [];
    while (items.length) {
      const hit = items.find(pred);
      if (hit) return hit;
      page += 1;
      const next = await quietGet(`documents?status=${status}&page=${page}`);
      items = next ? next.items : [];
    }
    return null;
  }
  async function docWithRounds(min = 2) {
    const r = await quietGet('documents?status=draft');
    for (const d of (r ? r.items : [])) {
      if (d.submitted_at) continue;
      const full = await quietGet(`documents/${d.document_id}`);
      if (full && full.template.type_code === 'CCP_MONITORING' && full.sections.filter((s) => s.section_def === 'rounds').length >= min) return full;
    }
    return null;
  }
  function freeRound(doc, offset = 0) {
    const used = new Set(doc.sections.filter((s) => s.section_def === 'rounds').map((s) => s.values.round));
    let n = 0;
    for (let h = 0; h < 24; h += 1) for (const m of ['00', '15', '30', '45']) {
      const v = `${String(h).padStart(2, '0')}:${m}`;
      if (!used.has(v) && n++ === offset) return v;
    }
    return '23:59';
  }
  function ccpBody(tid, rounds) {
    return {
      template_id: tid, subject: 'CCP-2B/라인A(콘솔)', work_date: new Date().toISOString().slice(0, 10), assignee_id: 2,
      sections: [
        { section_def: 'info', values: { product: '유자차', lot: 'LOT-CONSOLE' } },
        ...rounds.map((r) => ({ section_def: 'rounds', values: { round: r, temp: 87.0, hold_sec: 16, measured_by: 3 } })),
      ],
    };
  }
  const need = (doc, what) => { if (!doc) throw new Error(`${what} 문서가 없습니다. seed_dev_documents로 시드 데이터를 넣으세요.`); return doc; };
  const J = (o) => JSON.stringify(o, null, 2);

  const PRESETS = [
    { id: 'DOC-PS-01', label: '문서 작성 정상', expect: '201 · DOC-CRT 9단계 통과 · document +1(draft), doc_section +3',
      prepare: async () => ({ func: 'create', body: J(ccpBody(await ccpTemplateId(), ['09:00', '10:00'])) }) },
    { id: 'DOC-PS-02', label: '필수값 누락 작성', expect: '400 VALIDATION_ERROR · DOC-CRT-06 실패 · DB 변화 없음',
      prepare: async () => { const b = ccpBody(await ccpTemplateId(), ['09:00']); delete b.sections[0].values.lot; delete b.sections[1].values.temp; return { func: 'create', body: J(b) }; } },
    { id: 'DOC-PS-03', label: '없는 staff로 요청', expect: '403 INVALID_STAFF · DOC-CRT-02 실패 · DB 변화 없음',
      prepare: async () => ({ func: 'create', staff: '999', body: J(ccpBody(await ccpTemplateId(), ['09:00'])) }) },
    { id: 'DOC-PS-04', label: '비활성 양식으로 작성', expect: '409 TEMPLATE_INACTIVE · DOC-CRT-03 실패',
      prepare: async () => ({ func: 'create', body: J(ccpBody(await inactiveTemplateId(), ['09:00'])) }) },
    { id: 'DOC-PS-05', label: '수정 정상(행 추가·삭제·변경)', expect: '200 · DOC-UPD 10단계 통과 · 보낸 행만 바뀜, 안 보낸 행은 recorded_at 그대로',
      prepare: async () => {
        const d = need(await docWithRounds(2), '행 2개 이상인 draft');
        const rounds = d.sections.filter((s) => s.section_def === 'rounds');
        return { func: 'update', id: d.document_id, body: J({
          document: { subject: `${d.subject || ''} (수정)` },
          sections: {
            update: [{ section_id: rounds[0].section_id, values: { temp: 85.5, note: '콘솔 수정' } }],
            delete: [rounds[rounds.length - 1].section_id],
            add: [{ section_def: 'rounds', values: { round: freeRound(d), temp: 86, hold_sec: 15, measured_by: 3 } }],
          } }) };
      } },
    { id: 'DOC-PS-06', label: '결재중 문서 수정 거부', expect: '409 DOCUMENT_LOCKED · DOC-UPD-03(영향 0행) → 03a 실패 · DB 변화 없음',
      prepare: async () => ({ func: 'update', id: need(await findDoc('submitted'), 'submitted').document_id, body: J({ document: { subject: '바뀌면 안 됨' } }) }) },
    { id: 'DOC-PS-07', label: '반려 문서 수정', expect: '200 · 잠금 통과 · 상태는 rejected 유지',
      prepare: async () => ({ func: 'update', id: need(await findDoc('rejected'), 'rejected').document_id, body: J({ document: { subject: '반려 후 수정' } }) }) },
    { id: 'DOC-PS-08', label: '삭제 정상(논리)', expect: '204 · DOC-DEL 3단계 · document 행 유지, deleted_at/by 채워짐',
      prepare: async () => ({ func: 'delete', id: need(await findDoc('draft', (d) => !d.submitted_at), '상신 이력 없는 draft').document_id }) },
    { id: 'DOC-PS-09', label: '삭제 거부(승인 문서)', expect: '409 DOCUMENT_NOT_DELETABLE · DOC-DEL-02a 실패',
      prepare: async () => ({ func: 'delete', id: need(await findDoc('approved'), 'approved').document_id }) },
    { id: 'DOC-PS-10', label: '없는 문서 조회', expect: '404 DOCUMENT_NOT_FOUND · DOC-GET-01 실패',
      prepare: async () => ({ func: 'get', id: '99999' }) },
    { id: 'DOC-PS-11', label: '목록 필터·페이지', expect: '200 · SELECT의 WHERE·LIMIT/OFFSET 확인 · DB 변화 없음',
      prepare: async () => { const d = new Date(); const to = d.toISOString().slice(0, 10); d.setDate(d.getDate() - 30); return { func: 'list', query: `from=${d.toISOString().slice(0, 10)}&to=${to}&status=draft&page=2` }; } },
    { id: 'DOC-PS-12', label: '같은 측정시점 중복 입력', expect: '409 DUPLICATE_ROUND · DOC-CRT-06(앱 검증)에서 막힘 · DB 변화 없음',
      prepare: async () => ({ func: 'create', body: J(ccpBody(await ccpTemplateId(), ['09:00', '09:00'])) }) },
    { id: 'DOC-PS-13', label: '동시 수정(서로 다른 행)', expect: '두 요청 모두 200 · 잠금으로 직렬 처리 · 두 변경 모두 반영 (같은 필드 충돌 감지는 ISS-001)',
      prepare: async () => {
        const d = need(await docWithRounds(2), '행 2개 이상인 draft');
        const rounds = d.sections.filter((s) => s.section_def === 'rounds');
        const body = (row, temp) => J({ sections: { update: [{ section_id: row.section_id, values: { temp } }] } });
        return { func: 'update', id: d.document_id, body: body(rounds[0], 91),
          script: async (exec) => {
            const before = await snapshot(d.document_id);
            await Promise.all([
              exec({ func: 'update', id: d.document_id, body: body(rounds[0], 91), staff: api.staffId }, { before }),
              exec({ func: 'update', id: d.document_id, body: body(rounds[1], 92), staff: api.staffId }, { before }),
            ]);
          } };
      } },
    { id: 'DOC-PS-14', label: '이미 삭제된 행 수정', expect: '1번째 200(행 삭제) → 2번째 409 SECTION_ROW_NOT_FOUND · 2번째는 전체 롤백',
      prepare: async () => {
        const d = need(await docWithRounds(2), '행 2개 이상인 draft');
        const row = d.sections.filter((s) => s.section_def === 'rounds').pop();
        const del = J({ sections: { delete: [row.section_id] } });
        const upd = J({ sections: { update: [{ section_id: row.section_id, values: { temp: 99 } }] } });
        return { func: 'update', id: d.document_id, body: upd,
          script: async (exec) => {
            await exec({ func: 'update', id: d.document_id, body: del, staff: api.staffId });
            await exec({ func: 'update', id: d.document_id, body: upd, staff: api.staffId });
          } };
      } },
  ];

  async function loadPreset() {
    const p = PRESETS.find((x) => x.id === $('#dcPreset').value);
    if (!p) { state.preset = null; $('#dcPresetDesc').textContent = '기능을 고르고 실행하세요. 프리셋을 불러오면 입력이 채워집니다.'; return; }
    $('#dcPresetDesc').textContent = `${p.id} 준비 중…`;
    try {
      const spec = await p.prepare();
      $('#dcFunc').value = spec.func;
      $('#dcId').value = spec.id || '';
      $('#dcQuery').value = spec.query || '';
      $('#dcBody').value = spec.body || '';
      if (spec.staff) { api.setStaff(spec.staff); $('#dcStaff').value = spec.staff; }
      else if (!api.staffId || api.staffId === '999') { api.setStaff('3'); $('#dcStaff').value = '3'; }
      state.preset = { id: p.id, script: spec.script };
      toggleInputs();
      $('#dcPresetDesc').innerHTML = `<b>${esc(p.id)} ${esc(p.label)}</b><br>기대: ${esc(p.expect)}${spec.script ? '<br><span class="te-hint">여러 호출을 순서/동시에 실행하는 프리셋입니다. [실행]을 누르세요.</span>' : ''}`;
    } catch (error) {
      state.preset = null;
      $('#dcPresetDesc').textContent = `${p.id}: ${error.message}`;
    }
  }

  // ---------------------------------------------------------------- 초기화
  function toggleInputs() {
    const uses = FUNCS[$('#dcFunc').value].uses;
    $('#dcIdWrap').style.display = uses.includes('id') ? '' : 'none';
    $('#dcQueryWrap').style.display = uses.includes('query') ? '' : 'none';
    $('#dcBodyWrap').style.display = uses.includes('body') ? '' : 'none';
  }

  async function init() {
    const staff = await quietGet('staff');
    $('#dcStaff').innerHTML = '<option value="">(헤더 없음)</option>' + (staff ? staff.items : [])
      .map((id) => `<option value="${id}" ${String(id) === api.staffId ? 'selected' : ''}>staff ${id}</option>`).join('') + '<option value="999">999 (없는 staff)</option>';
    $('#dcStaff').value = api.staffId || '';
    $('#dcStaff').addEventListener('change', (e) => api.setStaff(e.target.value));
    $('#dcFunc').innerHTML = Object.entries(FUNCS).map(([k, f]) => `<option value="${k}">${esc(f.label)}</option>`).join('');
    $('#dcPreset').innerHTML = '<option value="">(직접 입력)</option>' + PRESETS.map((p) => `<option value="${p.id}">${p.id} ${esc(p.label)}</option>`).join('');
    $('#dcFunc').addEventListener('change', () => { state.preset = null; toggleInputs(); });
    ['#dcId', '#dcQuery', '#dcBody'].forEach((sel) => $(sel).addEventListener('input', () => { if (state.preset && state.preset.script) state.preset = null; }));
    $('#dcLoadPreset').addEventListener('click', loadPreset);
    $('#dcRun').addEventListener('click', run);
    $('#dcOnlyChanged').addEventListener('change', () => state.active && renderDb(state.active));
    const flows = await devGet('/api/dev/flows');
    state.flows = flows ? flows.flows : {};
    toggleInputs();
    renderHistory();
    const docId = new URLSearchParams(location.search).get('document_id');
    if (docId) {
      $('#dcFunc').value = 'get';
      $('#dcId').value = docId;
      toggleInputs();
      run();
    }
  }

  window.DevConsole = { state, run, execute, PRESETS };
  init();
})();
