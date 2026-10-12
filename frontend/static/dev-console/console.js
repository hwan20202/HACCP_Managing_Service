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
    // ---- P3 WF (쓰기) / APR (조회) — document-workflow/s2-spec.md 2장
    submit: { label: 'WF 상신·재상신 (WF-A01)', method: 'POST', flow: 'WF-SUB', uses: ['id', 'body'], path: (s) => `documents/${s.id}/submit`, doc: (s) => s.id },
    decide: { label: 'WF 승인·반려 (WF-A02)', method: 'POST', uses: ['id', 'body', 'docId'], path: (s) => `approvals/${s.id}/decision`,
      flow: (record) => ({ approved: 'WF-DEC-APPROVED', rejected: 'WF-DEC-REJECTED' }[record.data && record.data.request_status] || 'WF-DEC-PROGRESS'),
      doc: (s, r) => s.docId || (r && r.ok && r.data.document_id) },
    inbox: { label: 'APR 결재함 (A01)', method: 'GET', flow: 'APR-INB', uses: ['query'], path: (s) => `approval-inbox${s.query ? `?${s.query}` : ''}` },
    request: { label: 'APR 결재 요청 상세 (A02)', method: 'GET', flow: 'APR-GET', uses: ['id'], path: (s) => `approval-requests/${s.id}` },
    history: { label: 'APR 문서별 회차 이력 (A03)', method: 'GET', flow: 'APR-HIS', uses: ['id'], path: (s) => `documents/${s.id}/approval-requests`, doc: (s) => s.id },
    // ---- P4 DOC 확장 — document/p4-s2-spec.md 4장
    complete: { label: '작성완료 (F12·A09)', method: 'POST', flow: 'DOC-CMP', uses: ['id', 'body'], path: (s) => `documents/${s.id}/complete`, doc: (s) => s.id },
    reopen: { label: '작성 재개 (F13·A10)', method: 'POST', flow: 'DOC-ROP', uses: ['id', 'body'], path: (s) => `documents/${s.id}/reopen`, doc: (s) => s.id },
    devCreate: { label: '개선조치 쓰기 (F19·A15)', method: 'POST', flow: 'DOC-DVC', uses: ['id', 'body'], path: (s) => `documents/${s.id}/deviations`, doc: (s) => s.id },
    devUpdate: { label: '개선조치 수정 (F20·A16)', method: 'PATCH', flow: 'DOC-DVU', uses: ['id', 'body', 'docId'], path: (s) => `deviations/${s.id}`, doc: (s) => s.docId },
    devDelete: { label: '개선조치 삭제 (F21·A17)', method: 'DELETE', flow: 'DOC-DVD', uses: ['id', 'query', 'docId'], path: (s) => `deviations/${s.id}${s.query ? `?${s.query}` : ''}`, doc: (s) => s.docId },
    // ---- P5 REQ 작성 요구 — doc-requirements/s2-spec.md 2.2. ④는 LOT·배치 단위 스냅샷(scope)
    // 새 LOT·배치를 만드는 호출은 실행 전 id가 없다 → 그날(입고일·생산일) 범위로 실행 전/후 비교(S6-39 K1)
    reqLot: { label: 'REQ 테스트 입고 + 작성 요구 (D04→F01)', method: 'POST', flow: 'REQ-DEV-LOT', uses: ['body'], path: () => '/api/dev/req/lots',
      creates: 'lot', scope: (s) => dayScope(s, 'received_date') },
    reqLotRe: { label: 'REQ 같은 LOT 다시 호출 (D06→F01)', method: 'POST', flow: 'REQ-DEV-RE-LOT', uses: ['id'], path: (s) => `/api/dev/req/lots/${s.id}/require`,
      scope: (s) => `lot_id=${s.id}` },
    reqBatch: { label: 'REQ 테스트 배치 + 작성 요구 (D05→F02)', method: 'POST', flow: 'REQ-DEV-BAT', uses: ['body'], path: () => '/api/dev/req/batches',
      creates: 'batch', scope: (s) => dayScope(s, 'manufactured_date') },
    reqBatchRe: { label: 'REQ 같은 배치 다시 호출 (D07→F02)', method: 'POST', flow: 'REQ-DEV-RE-BAT', uses: ['id'], path: (s) => `/api/dev/req/batches/${s.id}/require`,
      scope: (s) => `batch_id=${s.id}` },
    lotDocs: { label: 'REQ LOT별 연결 문서 (F03·A01)', method: 'GET', flow: 'REQ-FND', uses: ['id'], path: (s) => `lots/${s.id}/documents`, scope: (s) => `lot_id=${s.id}` },
    batchDocs: { label: 'REQ 배치별 연결 문서 (F04·A02)', method: 'GET', flow: 'REQ-FND-B', uses: ['id'], path: (s) => `batches/${s.id}/documents`, scope: (s) => `batch_id=${s.id}` },
  };
  function dayScope(spec, key) {
    try {
      const day = JSON.parse(spec.body || '{}')[key];
      return /^\d{4}-\d{2}-\d{2}$/.test(day || '') ? `${key}=${day}` : null;
    } catch (e) { return null; }
  }
  const flowOf = (fn, record) => (typeof fn.flow === 'function' ? fn.flow(record) : fn.flow);

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
      body, staff: api.staffId, docId: $('#dcDocId').value.trim(),
    };
  }

  const scopeSnapshot = (q) => (q ? devGet(`/api/dev/snapshot?${q}`) : Promise.resolve(null));

  async function execute(spec, { before } = {}) {
    const fn = FUNCS[spec.func];
    if (fn.scope) {
      // P5 REQ: 문서 하나가 아니라 LOT·배치 하나에 걸린 행(lots·입고 기록·document·doc_section·document_ref)
      const scopeBefore = fn.scope(spec, null);
      const snapBefore = before !== undefined ? before : await scopeSnapshot(scopeBefore);
      const record = await api.request(fn.method, fn.path(spec), spec.body, { staffId: spec.staff });
      let trace = record.data && typeof record.data === 'object' && record.data.trace;
      if (!trace && record.traceId) trace = await devGet(`/api/dev/traces/${record.traceId}`);
      const scope = fn.scope(spec, record) || scopeBefore;
      const snapAfter = await scopeSnapshot(scope);
      const entry = { spec, fn, record, trace, before: snapBefore, after: snapAfter, scope, preset: state.preset };
      addEntry(entry);
      return entry;
    }
    const docBefore = fn.doc ? fn.doc(spec, null) : null;
    const snapBefore = before !== undefined ? before : await snapshot(docBefore);
    const record = await api.request(fn.method, fn.path(spec), spec.body, { staffId: spec.staff });
    let trace = record.data && typeof record.data === 'object' && record.data.trace;
    if (!trace && record.traceId) trace = await devGet(`/api/dev/traces/${record.traceId}`);
    const docAfter = fn.doc ? fn.doc(spec, record) : null;
    const snapAfter = await snapshot(docAfter || docBefore);
    const entry = { spec, fn, record, trace, before: snapBefore, after: snapAfter, docId: docAfter || docBefore, preset: state.preset };
    addEntry(entry);
    return entry;
  }

  // 여러 호출 프리셋(PS-05·PS-08 등): 한 번의 [실행]에서 나온 호출을 묶어 ②③④ 위 [호출 n] 탭으로 고른다(S6-39 K2).
  // groupScope가 있으면 프리셋 전후 스냅샷을 따로 찍어 [합계] 탭에 최종 변화를 보인다.
  function addEntry(entry) {
    if (state.running) { entry.group = state.running; state.running.entries.push(entry); }
    state.history.push(entry);
  }

  async function run() {
    const btn = $('#dcRun');
    btn.disabled = true;
    $('#dcRunHint').textContent = '실행 중…';
    try {
      const preset = state.preset;
      if (preset && preset.script) {
        const group = { id: preset.id, entries: [], scope: preset.groupScope || null, concurrent: !!preset.concurrent };
        if (group.scope) group.before = await scopeSnapshot(group.scope);
        state.running = group;
        try { await preset.script(execute); } finally { state.running = null; }
        if (group.scope) group.after = await scopeSnapshot(group.scope);
        if (group.scope && group.entries.length > 1) { showTotal(group); $('#dcRunHint').textContent = ''; return; }
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
    // P5 REQ 흐름은 안에 DOC·APR 단계를 품고 반복(#n 번호·공정)이 있다(s2-flows 9장, D-070 G3):
    // 이 흐름의 단계만 골라 연속 반복을 하나로 줄여 비교하고, 안쪽 단계는 칩 대신 개수로만 보인다.
    // P6: DOC 생명주기 신호(DOC-SIG-01) 안의 받는 쪽 단계(EFF-…와 그 안의 DOC 조회)도 안쪽 단계다
    // (documents/flows.py와 같은 규칙).
    const reqFlow = flowId.startsWith('REQ-');
    const group = (id) => id.replace(/-[^-]+$/, '');
    const groups = new Set(expected.map(group));
    const byId = Object.fromEntries(steps.map((s) => [s.step_id, s]));
    const chips = expected.map((id) => ({ id, cls: byId[id] ? byId[id].result : 'none' }));
    // 신호(DOC-SIG-01) 안에서 실행된 단계만 안쪽으로 본다 — 다음에 이 흐름의 단계 묶음이 나오면 끝(S4b B1)
    const insideSignal = new Set();
    let inSignal = false;
    steps.forEach((s) => {
      if (s.step_id === 'DOC-SIG-01') { inSignal = true; return; }
      if (inSignal && groups.has(group(s.step_id)) && group(s.step_id) !== 'DOC-SIG') inSignal = false;
      if (inSignal) insideSignal.add(s);
    });
    const own = (s) => (reqFlow ? s.step_id.startsWith('REQ-') : !insideSignal.has(s));
    const inner = steps.filter((s) => !own(s));
    const nested = inner.length > 0;
    steps.filter((s) => own(s) && !expected.includes(s.step_id))
      .forEach((s) => chips.push({ id: s.step_id, cls: s.result === 'fail' ? 'fail extra' : 'extra' }));
    let mainRun = steps.filter(own).map((s) => s.step_id).filter((id) => (reqFlow ? expected.includes(id) : !id.endsWith('a')));
    if (reqFlow) mainRun = mainRun.filter((id, i) => i === 0 || mainRun[i - 1] !== id);
    const inOrder = mainRun.every((id, i) => expected[i] === id);
    const failed = steps.find((s) => s.result === 'fail' && own(s));
    const reached = expected.filter((id) => byId[id]).length;
    let summary;
    if (!inOrder) summary = `<span class="dc-status-err">⚠ 순서 불일치 — 도식(${flowId})과 실행 순서가 다릅니다</span>`;
    else if (failed) summary = `<span class="dc-status-err">실패 경로: ${esc(failed.step_id)}에서 중단 (${reached}/${expected.length} 단계)</span>`;
    else if (reached === expected.length) summary = `<span class="dc-status-ok">도식 일치 ✅ ${reached}/${expected.length}</span>`;
    else summary = `<span class="dc-status-err">⚠ 누락 단계 있음 (${reached}/${expected.length})</span>`;
    let innerHtml = '';
    if (nested && inner.length) {
      const innerFail = inner.filter((s) => s.result === 'fail').length;
      summary += ` <span class="te-hint">· 안쪽 단계(DOC·APR·EFF) ${inner.length}개${innerFail ? `(실패 ${innerFail})` : ''}</span>`;
      // S6-39 K3: 어떤 안쪽 단계가 돌았는지 상세 표를 읽지 않고 보도록 실행 순서대로 펼친다(같은 단계 연속은 ×n).
      const runs = [];
      steps.forEach((s) => {
        if (own(s)) { runs.push({ sep: s.step_id }); return; }
        const last = runs[runs.length - 1];
        if (last && !last.sep && last.id === s.step_id && last.cls === s.result) last.n += 1;
        else runs.push({ id: s.step_id, cls: s.result, n: 1 });
      });
      const parts = [];
      let group = [];
      const flush = (after) => { if (group.length) parts.push(`<div class="dc-inner-row"><span class="te-hint mono">${esc(after)} ›</span> ${group.join('')}</div>`); group = []; };
      let owner = '(시작)';
      runs.forEach((r) => {
        if (r.sep) { flush(owner); owner = r.sep; return; }
        group.push(`<span class="dc-chip ${r.cls}" title="${r.cls}">${esc(r.id)}${r.n > 1 ? ` ×${r.n}` : ''}</span>`);
      });
      flush(owner);
      innerHtml = `<details class="dc-inner"><summary>안쪽 단계 ${inner.length}개 펼치기${innerFail ? ` · 실패 ${innerFail}` : ''}</summary>${parts.join('')}</details>`;
    }
    return { chips, summary, innerHtml };
  }

  function renderTrace(entry) {
    const { trace, fn } = entry;
    if (!trace) {
      $('#dcFlowSummary').innerHTML = '';
      $('#dcFlowChips').innerHTML = '';
      $('#dcTraceBody').innerHTML = '<div class="dc-empty">trace가 없습니다(개발 콘솔 설정이 꺼져 있거나 만료됨).</div>';
      return;
    }
    const flowId = flowOf(fn, entry.record);
    const { chips, summary, innerHtml } = compareFlow(flowId, trace.steps);
    $('#dcFlowSummary').innerHTML = `${summary} <span class="te-hint">도식 ${esc(flowId)} · trace ${esc(trace.trace_id)}</span>`;
    $('#dcFlowChips').innerHTML = chips.map((c) => `<span class="dc-chip ${c.cls}" title="${c.cls}">${esc(c.id)}</span>`).join('') + innerHtml;
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
  const PK = {
    document: 'document_id', doc_section: 'section_id', document_template: 'template_id', staff: 'staff_id',
    approval_request: 'request_id', approval: 'approval_id',
    document_ref: 'ref_id', deviation_action: 'deviation_id',
    lots: 'id', production_batches: 'id', dev_lot_receipts: 'lot_id', dev_batch_plans: 'production_batch_id',
  };
  // 복합 PK 테이블 (ERD v5 A12)
  const keyOf = (name, row) => (name === 'deviation_checker' ? `${row.deviation_id}-${row.staff_id}` : row[PK[name]]);

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
    const before = Object.fromEntries((beforeRows || []).map((r) => [keyOf(name, r), r]));
    const after = Object.fromEntries((afterRows || []).map((r) => [keyOf(name, r), r]));
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
    if (entry.linked) {
      $('#dcDbTitle').textContent = '';
      $('#dcDbBody').innerHTML = '<div class="dc-empty">작성 요구 화면에서 연 trace라 실행 전/후 스냅샷이 없습니다. 같은 호출을 콘솔 프리셋(REQ-PS-…)으로 실행하면 비교할 수 있습니다.</div>';
      return;
    }
    const onlyChanged = $('#dcOnlyChanged').checked;
    const { before, after, docId } = entry;
    if (entry.scope !== undefined) {
      const { fn, record } = entry;
      const failedCreate = fn.creates && !record.ok;
      if (!entry.scope) {
        $('#dcDbTitle').textContent = '';
        $('#dcDbBody').innerHTML = failedCreate
          ? '<div class="dc-empty">새 LOT·배치가 만들어지지 않았습니다(실패 → 호출자 트랜잭션 롤백). LOT·문서·참조 모두 없음.</div>'
          : '<div class="dc-empty">비교 범위를 정할 수 없습니다(본문의 날짜를 확인하세요).</div>';
        return;
      }
      let made = '';
      if (fn.creates === 'lot' && record.ok) made = ` · 새 LOT ${esc(record.data.lot.lot_number)} (lot_id ${esc(record.data.lot.lot_id)})`;
      if (fn.creates === 'batch' && record.ok) made = ` · 새 배치 ${esc(record.data.batch.batch_number)} (batch_id ${esc(record.data.batch.production_batch_id)})`;
      const range = fn.creates ? ` <span class="te-hint">· 그날 ${fn.creates === 'lot' ? '입고 LOT' : '생산 배치'} 전부와 연결 문서</span>` : '';
      $('#dcDbTitle').innerHTML = `${groupLabel(entry)}${esc(entry.scope.replace('=', ' = '))}${made}${range} ${!fn.creates && (!before || !before.exists) ? '<span class="te-hint">· 실행 전 없음</span>' : ''}`;
      let note = '';
      if (failedCreate) note += '<div class="dc-empty">새 LOT·배치가 만들어지지 않았습니다(실패 → 호출자 트랜잭션 롤백). 그날 범위의 행은 실행 전과 같습니다.</div>';
      if (entry.group && entry.group.concurrent) note += '<div class="dc-empty">동시 호출이라 이 호출의 실행 전/후에 다른 호출의 변화가 섞일 수 있습니다. 최종 결과는 [합계] 탭에서 보세요.</div>';
      $('#dcDbBody').innerHTML = note + scopeTables(before, after, onlyChanged);
      return;
    }
    if (!docId) {
      $('#dcDbTitle').textContent = '';
      $('#dcDbBody').innerHTML = '<div class="dc-empty">문서 단위 기능이 아니라서(목록·양식·staff) 비교할 행이 없습니다. 조회 기능은 DB를 바꾸지 않습니다.</div>';
      return;
    }
    const b = (before && before.tables) || {};
    const a = (after && after.tables) || {};
    $('#dcDbTitle').innerHTML = `document_id = ${esc(docId)} ${after && after.deleted ? '<span class="dc-deleted-flag">· 논리 삭제됨 (업무 API는 404)</span>' : ''} ${!before || !before.exists ? '<span class="te-hint">· 실행 전 없음</span>' : ''}`;
    $('#dcDbBody').innerHTML = ['document', 'doc_section', 'document_ref', 'deviation_action', 'deviation_checker', 'approval_request', 'approval', 'document_template', 'staff'].map((t) => diffTable(t, b[t], a[t], onlyChanged)).join('');
  }

  function scopeTables(before, after, onlyChanged) {
    const sb = (before && before.tables) || {};
    const sa = (after && after.tables) || {};
    return ['lots', 'dev_lot_receipts', 'production_batches', 'dev_batch_plans', 'document', 'doc_section', 'document_ref']
      .filter((t) => t in sa || t in sb).map((t) => diffTable(t, sb[t], sa[t], onlyChanged)).join('');
  }

  // ---------------------------------------------------------------- 여러 호출 프리셋의 [호출 n]·[합계] 탭 (S6-39 K2)
  const groupOf = (x) => (x && x.entries ? x : x && x.group);
  function groupLabel(entry) {
    const g = entry.group;
    if (!g || g.entries.length < 2) return '';
    return `<span class="badge badge-info">호출 ${g.entries.indexOf(entry) + 1}/${g.entries.length}</span> `;
  }
  function renderTabs(active) {
    const g = groupOf(active);
    const box = $('#dcCallTabs');
    if (!g || g.entries.length < 2) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    const tab = (key, label, cls, on) => `<button type="button" class="dc-call-tab ${on ? 'active' : ''}" data-k="${key}"><span class="${cls}">${label}</span></button>`;
    box.innerHTML = `<span class="te-hint">${esc(g.id)}${g.concurrent ? ' · 동시' : ' · 순서대로'}</span>`
      + g.entries.map((e, i) => tab(i, `호출 ${i + 1} · ${e.record.status}`, e.record.ok ? 'dc-status-ok' : 'dc-status-err', active === e)).join('')
      + (g.scope ? tab('total', '합계', '', active === g) : '');
    box.querySelectorAll('.dc-call-tab').forEach((b) => b.addEventListener('click', () => {
      if (b.dataset.k === 'total') showTotal(g); else show(g.entries[Number(b.dataset.k)]);
    }));
  }

  function showTotal(g) {
    state.active = g;
    renderTabs(g);
    $('#dcApiBody').innerHTML = `<div class="dc-sub">이 프리셋의 호출 ${g.entries.length}개${g.concurrent ? ' (동시에 보냄)' : ''}</div>`
      + g.entries.map((e, i) => `<div class="dc-line"><span class="te-hint">호출 ${i + 1}</span><span class="dc-method">▶ ${esc(e.record.request.method)}</span><span class="dc-code">${esc(e.record.request.url)}</span>
        <span class="${e.record.ok ? 'dc-status-ok' : 'dc-status-err'}">◀ ${e.record.status}</span><span class="te-hint">${e.record.ms} ms</span></div>`).join('')
      + '<div class="te-hint" style="margin-top:.5rem">요청·응답 본문은 [호출 n] 탭에서 봅니다.</div>';
    $('#dcFlowSummary').innerHTML = '<span class="te-hint">호출별 도식 비교</span>';
    $('#dcFlowChips').innerHTML = '';
    $('#dcTraceBody').innerHTML = g.entries.map((e, i) => {
      if (!e.trace) return `<div class="dc-line"><span class="te-hint">호출 ${i + 1}</span> trace 없음</div>`;
      const flowId = flowOf(e.fn, e.record);
      return `<div class="dc-line"><span class="te-hint">호출 ${i + 1}</span>${compareFlow(flowId, e.trace.steps).summary} <span class="te-hint">도식 ${esc(flowId)}</span></div>`;
    }).join('');
    $('#dcDbTitle').innerHTML = `<span class="badge badge-info">합계</span> ${esc(g.scope.replace('=', ' = '))} <span class="te-hint">· 프리셋 실행 전 → 모든 호출이 끝난 뒤</span>`;
    $('#dcDbBody').innerHTML = scopeTables(g.before, g.after, $('#dcOnlyChanged').checked);
    renderHistory();
  }

  // ---------------------------------------------------------------- 이력
  function show(entry) {
    if (!entry) return;
    state.active = entry;
    renderTabs(entry);
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

  // ---------------------------------------------------------------- 프리셋 (document/s1-screens.md 6장 DOC-PS-01~15)
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
    { id: 'DOC-PS-02', label: '형식 오류 작성 (필수값 누락은 저장됨 — P4 C-2)', expect: '400 VALIDATION_ERROR · DOC-CRT-06 실패(온도 형식) · 필수값(lot) 누락은 오류가 아님 · DB 변화 없음',
      prepare: async () => { const b = ccpBody(await ccpTemplateId(), ['09:00']); delete b.sections[0].values.lot; b.sections[1].values.temp = 'abc'; return { func: 'create', body: J(b) }; } },
    { id: 'DOC-PS-03', label: '없는 staff로 요청', expect: '403 INVALID_STAFF · DOC-CRT-02 실패 · DB 변화 없음',
      prepare: async () => ({ func: 'create', staff: '999', body: J(ccpBody(await ccpTemplateId(), ['09:00'])) }) },
    { id: 'DOC-PS-04', label: '비활성 양식으로 작성', expect: '409 TEMPLATE_INACTIVE · DOC-CRT-03 실패',
      prepare: async () => ({ func: 'create', body: J(ccpBody(await inactiveTemplateId(), ['09:00'])) }) },
    { id: 'DOC-PS-05', label: '수정 정상(행 추가·삭제·변경)', expect: '200 · DOC-UPD 10단계 통과 · 보낸 행만 바뀜, 안 보낸 행은 recorded_at 그대로',
      prepare: async () => {
        const d = need(await docWithRounds(2), '행 2개 이상인 draft');
        const rounds = d.sections.filter((s) => s.section_def === 'rounds');
        return { func: 'update', id: d.document_id, body: J({
          expected_version: d.version,
          document: { subject: `${d.subject || ''} (수정)` },
          sections: {
            update: [{ section_id: rounds[0].section_id, values: { temp: 85.5, note: '콘솔 수정' } }],
            delete: [rounds[rounds.length - 1].section_id],
            add: [{ section_def: 'rounds', values: { round: freeRound(d), temp: 86, hold_sec: 15, measured_by: 3 } }],
          } }) };
      } },
    { id: 'DOC-PS-06', label: '결재중 문서 수정 거부', expect: '409 DOCUMENT_LOCKED · DOC-UPD-03(영향 0행) → 03a 실패 · DB 변화 없음',
      prepare: async () => { const d = need(await findDoc('submitted'), 'submitted'); return { func: 'update', id: d.document_id, body: J({ expected_version: d.version, document: { subject: '바뀌면 안 됨' } }) }; } },
    { id: 'DOC-PS-07', label: '반려 문서 수정', expect: '200 · 잠금 통과 · 상태는 rejected 유지',
      prepare: async () => { const d = need(await findDoc('rejected'), 'rejected'); return { func: 'update', id: d.document_id, body: J({ expected_version: d.version, document: { subject: '반려 후 수정' } }) }; } },
    { id: 'DOC-PS-08', label: '삭제 정상(논리)', expect: '204 · DOC-DEL 3단계 · document 행 유지, deleted_at/by 채워짐',
      prepare: async () => ({ func: 'delete', id: need(await findDoc('draft', (d) => !d.submitted_at && !d.record_key), '상신 이력 없는 draft(작성 요구 문서 제외 — 삭제 불가 C-3)').document_id }) },
    { id: 'DOC-PS-09', label: '삭제 거부(승인 문서)', expect: '409 DOCUMENT_NOT_DELETABLE · DOC-DEL-02a 실패',
      prepare: async () => ({ func: 'delete', id: need(await findDoc('approved'), 'approved').document_id }) },
    { id: 'DOC-PS-10', label: '없는 문서 조회', expect: '404 DOCUMENT_NOT_FOUND · DOC-GET-01 실패',
      prepare: async () => ({ func: 'get', id: '99999' }) },
    { id: 'DOC-PS-11', label: '목록 필터·페이지', expect: '200 · SELECT의 WHERE·LIMIT/OFFSET 확인 · DB 변화 없음',
      prepare: async () => { const d = new Date(); const to = d.toISOString().slice(0, 10); d.setDate(d.getDate() - 30); return { func: 'list', query: `from=${d.toISOString().slice(0, 10)}&to=${to}&status=draft&page=2` }; } },
    { id: 'DOC-PS-12', label: '같은 측정시점 중복 입력', expect: '409 DUPLICATE_ROUND · DOC-CRT-06(앱 검증)에서 막힘 · DB 변화 없음',
      prepare: async () => ({ func: 'create', body: J(ccpBody(await ccpTemplateId(), ['09:00', '09:00'])) }) },
    { id: 'DOC-PS-13', label: '동시 수정(같은 버전)', expect: '하나는 200, 하나는 409 VERSION_CONFLICT · 잠금으로 직렬 처리 · 먼저 처리된 변경만 반영 (ISS-001)',
      prepare: async () => {
        const d = need(await docWithRounds(2), '행 2개 이상인 draft');
        const rounds = d.sections.filter((s) => s.section_def === 'rounds');
        const body = (row, temp) => J({ expected_version: d.version, sections: { update: [{ section_id: row.section_id, values: { temp } }] } });
        return { func: 'update', id: d.document_id, body: body(rounds[0], 91),
          script: async (exec) => {
            const before = await snapshot(d.document_id);
            await Promise.all([
              exec({ func: 'update', id: d.document_id, body: body(rounds[0], 91), staff: api.staffId }, { before }),
              exec({ func: 'update', id: d.document_id, body: body(rounds[1], 92), staff: api.staffId }, { before }),
            ]);
          } };
      } },
    { id: 'DOC-PS-14', label: '이미 삭제된 행 수정', expect: '1번째 200(행 삭제) → 2번째(새 버전으로) 409 SECTION_ROW_NOT_FOUND · 2번째는 전체 롤백',
      prepare: async () => {
        const d = need(await docWithRounds(2), '행 2개 이상인 draft');
        const row = d.sections.filter((s) => s.section_def === 'rounds').pop();
        const del = J({ expected_version: d.version, sections: { delete: [row.section_id] } });
        const upd = (v) => J({ expected_version: v, sections: { update: [{ section_id: row.section_id, values: { temp: 99 } }] } });
        return { func: 'update', id: d.document_id, body: del,
          script: async (exec) => {
            const first = await exec({ func: 'update', id: d.document_id, body: del, staff: api.staffId });
            const next = first.record.ok ? first.record.data.version : d.version + 1;
            await exec({ func: 'update', id: d.document_id, body: upd(next), staff: api.staffId });
          } };
      } },
    { id: 'DOC-PS-15', label: '오래된 버전으로 수정(충돌)', expect: '1번째 200(버전 +1) → 2번째(같은 옛 버전) 409 VERSION_CONFLICT · DOC-UPD-03 영향 행 0 → 03a 실패 · DB 변화 없음',
      prepare: async () => {
        const d = need(await findDoc('draft', (x) => !x.submitted_at), '상신 이력 없는 draft');
        const body = (subject) => J({ expected_version: d.version, document: { subject } });
        return { func: 'update', id: d.document_id, body: body('먼저 저장'),
          script: async (exec) => {
            await exec({ func: 'update', id: d.document_id, body: body('먼저 저장'), staff: api.staffId });
            await exec({ func: 'update', id: d.document_id, body: body('나중 저장(덮어쓰기 시도)'), staff: '4' });
          } };
      } },
  ];

  // ---------------------------------------------------------------- 프리셋 WF-PS-01~13 (document-workflow/s1-screens.md 6장)
  async function quietGetAs(path, staff) {
    const r = await fetch(`/api/v1/${path}`, { headers: { Accept: 'application/json', 'X-Staff-Id': String(staff) } });
    return r.ok ? r.json() : null;
  }
  const SEED_HINT = 'seed_dev_workflow로 시드 데이터를 넣으세요';
  const SLOTS3 = [{ slot_no: 1, label: '담당', approver_id: 3 }, { slot_no: 2, label: '검토', approver_id: 2 }, { slot_no: 3, label: '승인', approver_id: 1 }];
  async function freshDraft(pred = () => true) {
    const d = await findDoc('draft', (x) => !x.submitted_at && !x.record_key && !(x.subject || '').includes('PS-05') && pred(x));
    if (!d) throw new Error(`상신 이력 없는 draft 문서가 없습니다. ${SEED_HINT}.`);
    return quietGet(`documents/${d.document_id}`);
  }
  // P4: 상신은 작성완료(completed) 문서만. draft를 먼저 작성완료한 뒤 상신하는 스크립트를 만든다.
  const completeSpec = (d) => ({ func: 'complete', id: d.document_id, body: J({ expected_version: d.version }), staff: api.staffId });
  async function pendingItem(staff, pred = () => true) {
    for (let page = 1; page <= 10; page += 1) {
      const r = await quietGetAs(`approval-inbox?box=pending&page=${page}`, staff);
      if (!r || !r.items.length) break;
      const hit = r.items.find(pred);
      if (hit) return hit;
    }
    throw new Error(`staff ${staff}의 결재 대기 칸이 없습니다. ${SEED_HINT}.`);
  }
  async function latestRequest(documentId) {
    const h = await quietGet(`documents/${documentId}/approval-requests`);
    return h && h.items[0];
  }
  const decideSpec = (item, staff, body, docId) => ({ func: 'decide', id: String(item.approval_id), staff: String(staff), docId: String(docId), body: J(body) });

  PRESETS.push(
    { id: 'WF-PS-01', label: '상신 정상 (작성완료 → 상신)', expect: '작성완료 200 → 상신 201 · WF-SUB 도식 일치(VAL→[LCK→GET→OPN]) · document completed→submitted·version+1, approval_request +1(1회차), approval +3(pending)',
      prepare: async () => {
        const d = await freshDraft();
        const submit = { func: 'submit', id: d.document_id, body: J({ expected_version: d.version + 1, slots: SLOTS3 }) };
        return { ...submit, script: async (exec) => { await exec(completeSpec(d)); await exec({ ...submit, staff: api.staffId }); } };
      } },
    { id: 'WF-PS-02', label: '잘못된 결재선(같은 결재자 2칸)', expect: '작성완료 200 → 상신 400 INVALID_SLOTS · WF-SUB-03(APR-VAL)에서 실패, 트랜잭션 단계(WF-SUB-04) 없음 · 상신 변화 없음(문서는 작성완료로 남음)',
      prepare: async () => {
        const d = await freshDraft();
        const submit = { func: 'submit', id: d.document_id, body: J({ expected_version: d.version + 1, slots: [{ slot_no: 1, approver_id: 2 }, { slot_no: 2, approver_id: 2 }] }) };
        return { ...submit, script: async (exec) => { await exec(completeSpec(d)); await exec({ ...submit, staff: api.staffId }); } };
      } },
    { id: 'WF-PS-03', label: '오래된 버전으로 상신', expect: '작성완료 200(version+1) → 작성완료 전 버전으로 상신 409 VERSION_CONFLICT · DOC-LCK-01 영향 0행 → 01a · WF-SUB-04 롤백 · 상신 변화 없음',
      prepare: async () => {
        const d = await freshDraft();
        const submit = J({ expected_version: d.version, slots: SLOTS3 });
        return { func: 'submit', id: d.document_id, body: submit,
          script: async (exec) => {
            await exec({ ...completeSpec(d), staff: '4' });
            await exec({ func: 'submit', id: d.document_id, body: submit, staff: api.staffId });
          } };
      } },
    { id: 'WF-PS-04', label: '결재 중 문서 상신', expect: '409 DOCUMENT_LOCKED · DOC-LCK-01 영향 0행 → 01a · WF-SUB-04 롤백 · DB 변화 없음',
      prepare: async () => { const d = need(await findDoc('submitted'), 'submitted'); return { func: 'submit', id: d.document_id, body: J({ expected_version: d.version, slots: SLOTS3 }) }; } },
    { id: 'WF-PS-05', label: '회차 생성 실패 → 잠금까지 롤백', expect: '409 OPEN_REQUEST_EXISTS · DOC-LCK-01 통과(잠금) → APR-OPN-02 실패 → WF-SUB-04 롤백 · document status·version 그대로(잠금도 되돌려짐)',
      prepare: async () => {
        const d = need(await findDoc('completed', (x) => (x.subject || '').includes('PS-05')), '시드의 어긋난 데이터(PS-05)');
        return { func: 'submit', id: d.document_id, body: J({ expected_version: d.version, slots: SLOTS3 }) };
      } },
    { id: 'WF-PS-06', label: '중간 승인', expect: '200 · WF-DEC-PROGRESS(WF-DEC-05 건너뜀) · approval 1행 pending→approved · document 변화 없음, 응답 document null',
      prepare: async () => { const it = await pendingItem(2, (x) => x.request.progress.pending >= 2); return decideSpec(it, 2, { result: 'approved' }, it.request.document_id); } },
    { id: 'WF-PS-07', label: '마지막 승인 = 결재 완료', expect: '대기 칸을 차례로 승인, 마지막 호출 200 · WF-DEC-APPROVED(DOC-APV) · 회차 approved·closed_at, document submitted→approved·version+1',
      prepare: async () => {
        const it = await pendingItem(1, (x) => x.request.progress.pending >= 1);
        const req = await quietGet(`approval-requests/${it.request.request_id}`);
        const pending = req.slots.filter((s) => s.state === 'pending');
        const last = pending[pending.length - 1];
        return { ...decideSpec(last, last.approver_id, { result: 'approved' }, req.document_id),
          script: async (exec) => {
            for (const slot of pending) {
              await exec(decideSpec(slot, slot.approver_id, { result: 'approved', comment: '콘솔 승인' }, req.document_id));
            }
          } };
      } },
    { id: 'WF-PS-08', label: '반려', expect: '200 · WF-DEC-REJECTED(DOC-RJT) · approval →rejected(사유), 남은 pending →skipped, 회차 rejected, document submitted→rejected·version+1',
      prepare: async () => { const it = await pendingItem(2); return decideSpec(it, 2, { result: 'rejected', comment: '온도 기록 누락(콘솔)' }, it.request.document_id); } },
    { id: 'WF-PS-09', label: '반려 사유 없음', expect: '400 COMMENT_REQUIRED · APR-DEC-01 실패 → WF-DEC-03 롤백 · DB 변화 없음',
      prepare: async () => { const it = await pendingItem(2); return decideSpec(it, 2, { result: 'rejected' }, it.request.document_id); } },
    { id: 'WF-PS-10', label: '남의 칸 처리', expect: '403 NOT_YOUR_SLOT · APR-DEC-02 영향 0행 → 02a · WF-DEC-03 롤백 · DB 변화 없음',
      prepare: async () => { const it = await pendingItem(2); return decideSpec(it, 4, { result: 'approved' }, it.request.document_id); } },
    { id: 'WF-PS-11', label: '종료된 회차의 칸 처리', expect: '409 REQUEST_CLOSED · 반려로 끝난 회차의 미처리 종료(skipped) 칸 · APR-DEC-02 영향 0행 → 02a · DB 변화 없음',
      prepare: async () => {
        const d = need(await findDoc('rejected'), 'rejected');
        const req = await latestRequest(d.document_id);
        const slot = req && req.slots.find((s) => s.state === 'skipped');
        if (!slot) throw new Error(`반려 회차에 미처리 종료 칸이 없습니다. ${SEED_HINT}.`);
        return decideSpec(slot, slot.approver_id, { result: 'approved' }, d.document_id);
      } },
    { id: 'WF-PS-12', label: '재상신(수정 → 작성완료 → 상신)', expect: 'PATCH 200 → 작성완료 200 → 상신 201 · DOC-LCK가 completed 통과 · approval_request +1(n+1회차), 이전 회차 행·스냅샷 그대로 · document rejected→completed→submitted',
      prepare: async () => {
        const d = need(await findDoc('rejected'), 'rejected');
        const req = await latestRequest(d.document_id);
        const slots = req ? req.slots.map((s) => ({ slot_no: s.slot_no, label: s.label || undefined, approver_id: s.approver_id })) : SLOTS3;
        return { func: 'submit', id: d.document_id, body: J({ expected_version: d.version + 2, slots }),
          script: async (exec) => {
            const first = await exec({ func: 'update', id: d.document_id, body: J({ expected_version: d.version, document: { subject: `${d.subject || ''} (반려 후 수정)` } }), staff: api.staffId });
            const version = first.record.ok ? first.record.data.version : d.version;
            const done = await exec({ func: 'complete', id: d.document_id, body: J({ expected_version: version }), staff: api.staffId });
            const ready = done.record.ok ? done.record.data.version : version;
            await exec({ func: 'submit', id: d.document_id, body: J({ expected_version: ready, slots }), staff: api.staffId });
          } };
      } },
    { id: 'WF-PS-13', label: '결재함 조회', expect: '200 · APR-INB 도식 일치 · SQL 3개(건수·목록·진행률) · DB 변화 없음(조회)',
      prepare: async () => ({ func: 'inbox', staff: '2', query: 'box=pending&page=1' }) },
  );

  // ---------------------------------------------------------------- 프리셋 DOC-PS-16~27 (document/p4-s1-screens.md 6장, P4·P6a)
  // 파일 프리셋(PS-23·24)은 스프린트 3(D-058). 시드: seed_dev_p4
  const P4_HINT = 'seed_dev_p4로 시드 데이터를 넣으세요';
  async function templateIdOf(code) {
    const t = await quietGet('templates');
    const hit = t && t.items.find((x) => x.type_code === code);
    if (!hit) throw new Error(`양식 ${code}가 없습니다. ${P4_HINT}.`);
    return hit.template_id;
  }
  async function p4Doc(code, status, pred = () => true) {
    const tid = await templateIdOf(code);
    for (let page = 1; page <= 10; page += 1) {
      const r = await quietGet(`documents?template_id=${tid}&status=${status}&page=${page}`);
      if (!r || !r.items.length) break;
      for (const item of r.items) {
        const full = await quietGet(`documents/${item.document_id}`);
        if (full && pred(full)) return full;
      }
    }
    throw new Error(`${code} ${status} 문서가 없습니다. ${P4_HINT}.`);
  }
  const rowsOf = (d, key) => d.sections.filter((x) => x.section_def === key);
  const infoOf = (d) => rowsOf(d, 'info')[0];
  // P6a: D03은 LOT 1건 문서 — 검사 값은 반복 없는 inspection 섹션 1개(D-088)
  const inspectionOf = (d) => rowsOf(d, 'inspection')[0];
  const unfilledD03 = (d) => !inspectionOf(d)?.values.verdict;
  const PASS_INSPECTION = { appearance: '양호', packaging: '양호', labeling: '양호', verdict: 'PASS' };

  PRESETS.push(
    { id: 'DOC-PS-16', unit: 'P4', label: '작성 요구 문서 저장(필수값 비어도 저장)', expect: '200 · DOC-UPD 통과(05 형식 검사만, 필수값 검사 없음) · doc_section 값 변경, version +1',
      prepare: async () => {
        const d = await p4Doc('D03', 'draft', unfilledD03);
        return { func: 'update', id: d.document_id, body: J({ expected_version: d.version, sections: { update: [{ section_id: inspectionOf(d).section_id, values: { appearance: '양호' } }] } }) };
      } },
    { id: 'DOC-PS-17', unit: 'P4', label: '작성완료 정상', expect: '수정 200(필수값 채움) → 작성완료 200 · DOC-CMP 도식 일치(02 잠금 → 03 검사 통과 → 04) · document draft→completed, completed_at/by, version +1',
      prepare: async () => {
        const d = await p4Doc('D03', 'draft', unfilledD03);
        const fill = { expected_version: d.version, sections: { update: [
          { section_id: infoOf(d).section_id, values: { inspector: 4 } },
          { section_id: inspectionOf(d).section_id, values: PASS_INSPECTION },
        ] } };
        const done = { func: 'complete', id: d.document_id, body: J({ expected_version: d.version + 1 }) };
        return { ...done, script: async (exec) => {
          await exec({ func: 'update', id: d.document_id, body: J(fill), staff: api.staffId });
          await exec({ ...done, staff: api.staffId });
        } };
      } },
    { id: 'DOC-PS-18', unit: 'P4', label: '작성완료 실패(필수값·개선조치 누락)', expect: '400 COMPLETION_INCOMPLETE · DOC-CMP-02 잠금 통과 → 03 검사 실패(점검자 required, deviation_required) · 롤백으로 DB 변화 없음',
      prepare: async () => {
        const d = await p4Doc('CCP-3P', 'draft', (x) => !x.deviations.length);
        return { func: 'complete', id: d.document_id, body: J({ expected_version: d.version }) };
      } },
    { id: 'DOC-PS-19', unit: 'P4', label: '작성 재개', expect: '200 · DOC-ROP 도식 일치(02 조건부 UPDATE completed→draft) · status draft, completed_at/by 비움, version +1',
      prepare: async () => { const d = await p4Doc('CCP-1P', 'completed'); return { func: 'reopen', id: d.document_id, body: J({ expected_version: d.version }) }; } },
    { id: 'DOC-PS-20', unit: 'P4', label: '작성완료 상태에서 수정 거부', expect: '409 DOCUMENT_LOCKED · DOC-UPD-03 영향 0행 → 03a 실패 · DB 변화 없음',
      prepare: async () => {
        const d = await p4Doc('CCP-1P', 'completed');
        return { func: 'update', id: d.document_id, body: J({ expected_version: d.version, sections: { update: [{ section_id: infoOf(d).section_id, values: { inspector: 5 } }] } }) };
      } },
    { id: 'DOC-PS-21', unit: 'P4', label: '작성 요구 문서 삭제 거부', expect: '409 DOCUMENT_NOT_DELETABLE(reason requirement) · DOC-DEL-02 영향 0행 → 02a 실패 · DB 변화 없음',
      prepare: async () => { const d = await p4Doc('D01', 'draft'); return { func: 'delete', id: d.document_id }; } },
    { id: 'DOC-PS-25', unit: 'P4', label: 'CCP 판정 계산', expect: '200 · DOC-UPD-05b(판정 재계산) 포함 도식 일치 · 새 행 values_json.verdict = 부적합(SUS 우 X), 판정은 서버가 저장',
      prepare: async () => {
        const d = await p4Doc('CCP-3P', 'draft', (x) => x.deviations.length > 0);
        const ok = { fe_l: '○', fe_c: '○', fe_r: '○', sus_l: '○', sus_c: '○', sus_r: 'X', product_only: 'X', product_fe: '○', product_sus: '○' };
        return { func: 'update', id: d.document_id, body: J({ expected_version: d.version, sections: { add: [{ section_def: 'checks', values: { phase: '중간', passed_at: `${d.work_date}T13:00`, ...ok } }] } }) };
      } },
    { id: 'DOC-PS-26', unit: 'P4', label: '승인된 문서의 개선조치 쓰기·수정', expect: '사전 조건: 승인된 D03(LOT 1건) · 쓰기 201 → 수정 200 · DOC-DVC·DOC-DVU 도식 일치, 문서 잠금 검사 없음 · deviation_action(관련 행 없음, section_id NULL)·checker만 변경, document 변화 없음',
      prepare: async () => {
        const d = await p4Doc('D03', 'approved');
        const create = { func: 'devCreate', id: d.document_id, body: J({ description: '입고 검사 후 포장 파손 1건 발견(콘솔)', actor_id: 4, checker_ids: [2, 5] }) };
        return { ...create, script: async (exec) => {
          const first = await exec({ ...create, staff: api.staffId });
          if (!first.record.ok) return;
          const dev = first.record.data;
          await exec({ func: 'devUpdate', id: String(dev.deviation_id), docId: String(d.document_id), staff: '2',
            body: J({ expected_version: dev.version, action_result: '공급사 반품, 재입고 검사 적합', checker_ids: [2] }) });
        } };
      } },
    // DOC-PS-22(LOT 행 추가·삭제)는 P6a에서 폐지 — 번호는 비워 둠(P6a-S1-Q4)
    { id: 'DOC-PS-27', unit: 'P4', label: 'D03 입고 정보(자동 값) 수정 거부', expect: '400 VALIDATION_ERROR(readonly) · DOC-UPD-05 실패 → 롤백 · DB 변화 없음',
      prepare: async () => {
        const d = await p4Doc('D03', 'draft');
        return { func: 'update', id: d.document_id, body: J({ expected_version: d.version, sections: {
          update: [{ section_id: infoOf(d).section_id, values: { item_name: '바꾸면 안 됨' } }],
        } }) };
      } },
  );

  // ---------------------------------------------------------------- 프리셋 REQ-PS-01~12 (doc-requirements/s1-screens.md 6장, P6a-S1 6장)
  const REQ_HINT = 'seed_dev_p4로 시드를 넣거나 작성 요구 화면에서 LOT 생성을 먼저 하세요';
  const reqList = async (kind, q = '') => { const r = await devGet(`/api/dev/req/${kind}${q}`); return r ? r.items : []; };
  const localDay = (offset = 0) => { const d = new Date(); d.setDate(d.getDate() + offset); return d.toLocaleDateString('sv-SE'); };
  async function freeDay() {
    // 그날 육안검사가 없는 날(테스트 입고가 없는 날)을 오늘-40일부터 거슬러 찾는다
    for (let back = 40; back < 400; back += 1) {
      const day = localDay(-back);
      if (!(await reqList('lots', `?date=${day}`)).length) return day;
    }
    throw new Error('빈 날짜를 찾지 못했습니다.');
  }
  async function itemId(name) {
    const items = await reqList('items');
    const hit = items.find((i) => i.name === name) || items[0];
    if (!hit) throw new Error(`개발 품목이 없습니다. ${REQ_HINT}.`);
    return hit.id;
  }
  const lotBody = async (day, extra = {}) => ({ item_id: await itemId('유자'), material_kind: '원료', supplier_name: '콘솔농협',
    received_date: day, quantity: 100, unit: 'kg', ...extra });
  const d03Of = (lot) => lot.documents.find((d) => d.type_code === 'D03');
  async function lotWhere(pred, what) {
    const hit = (await reqList('lots')).find(pred);
    if (!hit) throw new Error(`${what} LOT이 없습니다. ${REQ_HINT}.`);
    return hit;
  }

  PRESETS.push(
    { id: 'REQ-PS-01', label: '입고 정상', expect: '201 · REQ-DEV-LOT 도식 일치(안쪽 DOC-GOC ×3) · lots·dev_lot_receipts +1, document +3(D01·D02·D03 새로 만듦), doc_section(info 초기값), document_ref +3(모두 문서 단위)',
      prepare: async () => ({ func: 'reqLot', body: J(await lotBody(await freeDay())) }) },
    { id: 'REQ-PS-02', label: '같은 LOT 다시 호출', expect: '200 · REQ-DEV-RE-LOT 도식 일치 · 안쪽 DOC-GOC-01a(이미 있음) ×3 · 결과 이미 있음 ×3 · dev_lot_receipts.touched_at만 변경(자기 쓰기 먼저)',
      prepare: async () => ({ func: 'reqLotRe', id: String((await lotWhere((l) => d03Of(l), 'D03 문서가 있는')).lot_id) }) },
    { id: 'REQ-PS-05', label: '동시에 두 LOT 입고', expect: '두 요청 모두 201 · 두 트랜잭션이 직렬 처리(첫 SQL 쓰기 잠금) · 그날 D03 2건(LOT마다, 둘 다 새로 만듦) · [합계] ④ lots +2, document +6(D01·D02·D03 ×2), document_ref +6',
      prepare: async () => {
        const day = await freeDay();
        const a = { func: 'reqLot', body: J(await lotBody(day, { supplier_name: '콘솔농협(A)' })) };
        const b = { func: 'reqLot', body: J(await lotBody(day, { supplier_name: '콘솔농협(B)' })) };
        return { ...a, groupScope: `received_date=${day}`, concurrent: true,
          script: async (exec) => { await Promise.all([exec({ ...a, staff: api.staffId }), exec({ ...b, staff: api.staffId })]); } };
      } },
    { id: 'REQ-PS-06', label: '작성 요구 중 실패 → 롤백', expect: '500 SIMULATED_FAILURE · REQ-LOT 전체 통과 뒤 REQ-DEV-03 실패 → 호출자 트랜잭션 롤백 · LOT·입고 기록·문서(D01·D02·D03 문서)·참조 모두 없음',
      prepare: async () => ({ func: 'reqLot', body: J(await lotBody(await freeDay(), { fail_after: true })) }) },
    { id: 'REQ-PS-07', label: '생산 시작(제조)', expect: '201 · REQ-DEV-BAT 도식 일치(REQ-BAT-03 ×3) · production_batches·dev_batch_plans +1, document +3(CCP-1P·2B·3P), document_ref(배치 + 공정) +3',
      prepare: async () => ({ func: 'reqBatch', body: J({ item_id: await itemId('유자차'), process_type: 'MANUFACTURE', manufactured_date: localDay(0), quantity_kg: 900 }) }) },
    { id: 'REQ-PS-08', label: '같은 배치 다시 호출 / 포장 배치', expect: '[호출 1] 200 · 이미 있음 ×3 · ④ dev_batch_plans ~1(touched_at만) [호출 2] 201 · REQ-BAT-03 건너뜀(공정 없음) · ④ production_batches·dev_batch_plans +1, 문서 변화 없음',
      prepare: async () => {
        const batch = (await reqList('batches')).find((b) => b.process_type === 'MANUFACTURE' && b.status !== 'CANCELLED' && b.documents.length);
        if (!batch) throw new Error(`CCP 문서가 있는 제조 배치가 없습니다. ${REQ_HINT}.`);
        const re = { func: 'reqBatchRe', id: String(batch.production_batch_id) };
        const pack = { func: 'reqBatch', body: J({ item_id: await itemId('파우치'), process_type: 'PACKAGING', manufactured_date: localDay(0), quantity_kg: 50 }) };
        return { ...re, script: async (exec) => { await exec({ ...re, staff: api.staffId }); await exec({ ...pack, staff: api.staffId }); } };
      } },
    { id: 'REQ-PS-09', label: '없는 LOT id로 조회', expect: '404 LOT_NOT_FOUND · REQ-FND-01(입고 뷰 읽기)에서 실패 · DB 변화 없음',
      prepare: async () => ({ func: 'lotDocs', id: '99999' }) },
    { id: 'REQ-PS-10', label: 'LOT별 연결 문서', expect: '200 · REQ-FND 4단계(안쪽 DOC-FND-01, APR-LAT-01) · SQL 4개 · D03 문서의 승인본 기준 판정(작성중 값 안 씀) · DB 변화 없음',
      prepare: async () => {
        const lot = await lotWhere((l) => { const d = d03Of(l); return d && d.status === 'approved'; }, '육안검사가 승인된')
          .catch(() => lotWhere(() => true, '테스트 입고'));
        return { func: 'lotDocs', id: String(lot.lot_id) };
      } },
    // REQ-PS-03·04는 P6a에서 폐지 — 번호는 비워 둠(P6a-S1-Q4)
    { id: 'REQ-PS-12', label: '그날 다른 LOT의 D03이 승인돼 있어도 새 LOT은 새 D03', expect: '201 · REQ-DEV-LOT 도식 일치 · D01·D02·D03 모두 새로 만듦(요구 키 D03|lot:{id}) · 다른 LOT의 D03 변화 없음 · ④(그날 범위) lots·dev_lot_receipts +1, document +3, document_ref +3',
      prepare: async () => {
        const lot = await lotWhere((l) => { const d = d03Of(l); return d && ['completed', 'submitted', 'approved'].includes(d.status); }, '육안검사가 작성완료·결재중·승인인');
        return { func: 'reqLot', body: J(await lotBody(lot.received_date, { supplier_name: '콘솔농협(같은 날)' })) };
      } },
  );


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
      $('#dcDocId').value = spec.docId || '';
      if (spec.staff) { api.setStaff(spec.staff); $('#dcStaff').value = spec.staff; }
      else if (!api.staffId || api.staffId === '999') { api.setStaff('3'); $('#dcStaff').value = '3'; }
      state.preset = { id: p.id, script: spec.script, groupScope: spec.groupScope, concurrent: spec.concurrent };
      toggleInputs();
      $('#dcPresetDesc').innerHTML = `<b>${esc(p.id)} ${esc(p.label)}</b><br>기대: ${esc(p.expect)}${spec.script ? '<br><span class="te-hint">여러 호출을 순서/동시에 실행하는 프리셋입니다. [실행]을 누르세요.</span>' : ''}`;
    } catch (error) {
      state.preset = null;
      $('#dcPresetDesc').textContent = `${p.id}: ${error.message}`;
    }
  }

  // ---------------------------------------------------------------- 작성 요구 화면에서 연 trace (?trace=<id>, REQ-SC-04)
  function guessFlow(trace) {
    const path = (trace.path || '').split('?')[0];
    if (/\/api\/dev\/req\/lots\/\d+\/require$/.test(path)) return 'REQ-DEV-RE-LOT';
    if (/\/api\/dev\/req\/batches\/\d+\/require$/.test(path)) return 'REQ-DEV-RE-BAT';
    if (path.endsWith('/api/dev/req/lots')) return 'REQ-DEV-LOT';
    if (path.endsWith('/api/dev/req/batches')) return 'REQ-DEV-BAT';
    if (/\/api\/v1\/lots\/\d+\/documents$/.test(path)) return 'REQ-FND';
    if (/\/api\/v1\/batches\/\d+\/documents$/.test(path)) return 'REQ-FND-B';
    return '';
  }

  async function openTrace(id) {
    const trace = await devGet(`/api/dev/traces/${encodeURIComponent(id)}`);
    if (!trace) { $('#dcPresetDesc').textContent = `trace ${id}가 없거나 만료되었습니다(서버 메모리에 최근 200건만 보관).`; return; }
    const record = { at: new Date(), ok: trace.status < 400, status: trace.status, statusText: '', ms: '-', traceId: id, data: null,
      request: { method: trace.method, url: trace.path, headers: {}, body: null } };
    const entry = { spec: {}, fn: { flow: guessFlow(trace) }, record, trace, linked: true, preset: null };
    state.history.push(entry);
    $('#dcPresetDesc').innerHTML = '작성 요구 화면에서 연 호출입니다(<b>③ 처리 로직</b>). 요청·응답 본문과 ④ DB 비교는 콘솔에서 직접 실행한 호출에만 있습니다.';
    show(entry);
  }

  // ---------------------------------------------------------------- 초기화
  function toggleInputs() {
    const uses = FUNCS[$('#dcFunc').value].uses;
    $('#dcIdWrap').style.display = uses.includes('id') ? '' : 'none';
    $('#dcQueryWrap').style.display = uses.includes('query') ? '' : 'none';
    $('#dcBodyWrap').style.display = uses.includes('body') ? '' : 'none';
    $('#dcDocIdWrap').style.display = uses.includes('docId') ? '' : 'none';
  }

  async function init() {
    const staff = await quietGet('staff');
    $('#dcStaff').innerHTML = '<option value="">(헤더 없음)</option>' + (staff ? staff.items : [])
      .map((id) => `<option value="${id}" ${String(id) === api.staffId ? 'selected' : ''}>staff ${id}</option>`).join('') + '<option value="999">999 (없는 staff)</option>';
    $('#dcStaff').value = api.staffId || '';
    $('#dcStaff').addEventListener('change', (e) => api.setStaff(e.target.value));
    $('#dcFunc').innerHTML = Object.entries(FUNCS).map(([k, f]) => `<option value="${k}">${esc(f.label)}</option>`).join('');
    const group = (unit, label) => `<optgroup label="${label}">${PRESETS.filter((p) => (p.unit || p.id.split('-')[0]) === unit).map((p) => `<option value="${p.id}">${p.id} ${esc(p.label)}</option>`).join('')}</optgroup>`;
    $('#dcPreset').innerHTML = '<option value="">(직접 입력)</option>' + group('DOC', 'DOC 문서 도메인 (P1)') + group('WF', 'WF 결재 워크플로우 (P3)') + group('P4', 'DOC 확장 (P4·P6a)') + group('REQ', 'REQ 작성 요구 (P5)');
    $('#dcFunc').addEventListener('change', () => { state.preset = null; toggleInputs(); });
    ['#dcId', '#dcQuery', '#dcBody', '#dcDocId'].forEach((sel) => $(sel).addEventListener('input', () => { if (state.preset && state.preset.script) state.preset = null; }));
    $('#dcLoadPreset').addEventListener('click', loadPreset);
    $('#dcRun').addEventListener('click', run);
    $('#dcOnlyChanged').addEventListener('change', () => { if (!state.active) return; if (state.active.entries) showTotal(state.active); else renderDb(state.active); });
    const flows = await devGet('/api/dev/flows');
    state.flows = flows ? flows.flows : {};
    toggleInputs();
    renderHistory();
    const traceParam = new URLSearchParams(location.search).get('trace');
    if (traceParam) { openTrace(traceParam); return; }
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
