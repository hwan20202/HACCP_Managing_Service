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
    // ---- P6 정정 — document-workflow/p6-s2-spec.md (DOC-A18·A19). 작성완료(A09)는 note(판정 변경 사유)도 받는다
    correction: { label: '정정 시작 (F22·A18)', method: 'POST', flow: 'DOC-COR', uses: ['id', 'body'], path: (s) => `documents/${s.id}/correction`, doc: (s) => s.id },
    correctionCancel: { label: '정정 취소 (F24·A19)', method: 'POST', flow: 'DOC-CCN', uses: ['id', 'body'], path: (s) => `documents/${s.id}/correction/cancel`, doc: (s) => s.id },
    devDelete: { label: '개선조치 삭제 (F21·A17)', method: 'DELETE', flow: 'DOC-DVD', uses: ['id', 'query', 'docId'], path: (s) => `deviations/${s.id}${s.query ? `?${s.query}` : ''}`, doc: (s) => s.docId },
    // ---- P5 REQ 작성 요구 — doc-requirements/s2-spec.md 2.2. ④는 LOT·배치 단위 스냅샷(scope)
    // 새 LOT·배치를 만드는 호출은 실행 전 id가 없다 → 그날(입고일·생산일) 범위로 실행 전/후 비교(S6-39 K1)
    // P6: 본문에 inspection이 있으면 육안검사 함께 입력 흐름(REQ-DEV-LOT-INSP, D-080)
    reqLot: { label: 'REQ 테스트 입고 + 작성 요구 (D04→F01)', method: 'POST', uses: ['body'], path: () => '/api/dev/req/lots',
      flow: (record) => (/"inspection"/.test((record && record.request && record.request.body) || '') ? 'REQ-DEV-LOT-INSP' : 'REQ-DEV-LOT'),
      creates: 'lot', scope: (s) => dayScope(s, 'received_date') },
    reqLotRe: { label: 'REQ 같은 LOT 다시 호출 (D06→F01)', method: 'POST', flow: 'REQ-DEV-RE-LOT', uses: ['id'], path: (s) => `/api/dev/req/lots/${s.id}/require`,
      scope: (s) => `lot_id=${s.id}` },
    reqBatch: { label: 'REQ 테스트 배치 + 작성 요구 (D05→F02)', method: 'POST', flow: 'REQ-DEV-BAT', uses: ['body'], path: () => '/api/dev/req/batches',
      creates: 'batch', scope: (s) => dayScope(s, 'manufactured_date') },
    reqBatchRe: { label: 'REQ 같은 배치 다시 호출 (D07→F02)', method: 'POST', flow: 'REQ-DEV-RE-BAT', uses: ['id'], path: (s) => `/api/dev/req/batches/${s.id}/require`,
      scope: (s) => `batch_id=${s.id}` },
    lotDocs: { label: 'REQ LOT별 연결 문서 (F03·A01)', method: 'GET', flow: 'REQ-FND', uses: ['id'], path: (s) => `lots/${s.id}/documents`, scope: (s) => `lot_id=${s.id}` },
    batchDocs: { label: 'REQ 배치별 연결 문서 (F04·A02)', method: 'GET', flow: 'REQ-FND-B', uses: ['id'], path: (s) => `batches/${s.id}/documents`, scope: (s) => `batch_id=${s.id}` },
    // ---- P7 일괄 — document-workflow/p7-s2-spec.md 3장. 일괄 쓰기는 ④에서 여러 문서를 비교한다(docs: 쉼표 목록)
    batchApprove: { label: 'WF 일괄 승인 (WF-A03)', method: 'POST', flow: 'WF-BAP', uses: ['body', 'docId'], path: () => 'approvals/batch-decision', docs: (s) => idList(s.docId) },
    batchSubmit: { label: 'WF 일괄 상신 (WF-A04)', method: 'POST', flow: 'WF-BSB', uses: ['body', 'docId'], path: () => 'documents/batch-submit', docs: (s) => idList(s.docId) || bodyDocs(s) },
    batchConfig: { label: 'WF 일괄 설정 (WF-A05)', method: 'GET', flow: 'WF-CFG', uses: [], path: () => 'workflow/batch-config' },
    batchInspector: { label: '점검자 일괄 지정 (F25·A20)', method: 'POST', flow: 'DOC-BIN', uses: ['body', 'docId'], path: () => 'documents/batch-inspector', docs: (s) => idList(s.docId) || bodyDocs(s) },
    brief: { label: '문서 요약 여러 건 (F26·A21)', method: 'GET', flow: 'DOC-BRF', uses: ['query'], path: (s) => `documents/brief${s.query ? `?${s.query}` : ''}` },
    incoming: { label: 'REQ 입고일 묶음 (F05·A03)', method: 'GET', flow: 'REQ-BDL', uses: ['query'], path: (s) => `incoming-inspections${s.query ? `?${s.query}` : ''}` },
    // ---- 스프린트 3 파일(D01·D02) — document-files/s4-basis.md, p4-s2-spec F14~F18·A11~A14
    // 올리기는 multipart: 본문 JSON {expected_version, name, kind: pdf|png|bad}를 견본 파일로 바꿔 보낸다(콘솔 전용)
    fileUpload: { label: '파일 올리기 (F14·A11)', method: 'POST', flow: 'DOC-FUP', uses: ['id', 'body'], path: (s) => `documents/${s.id}/files`, doc: (s) => s.id, multipart: true },
    fileLink: { label: '이전 파일 연결 (F15·A11)', method: 'POST', flow: 'DOC-FLK', uses: ['id', 'body'], path: (s) => `documents/${s.id}/files`, doc: (s) => s.id },
    // 끊기는 마지막 연결·보존 없음일 때만 05(커밋 뒤 파일 삭제)를 지난다 — trace로 도식을 고른다
    fileDetach: { label: '파일 연결 끊기 (F16·A12)', method: 'DELETE', uses: ['id', 'query'], doc: (s) => s.id,
      flow: (record, trace) => (trace && trace.steps.some((x) => x.step_id === 'DOC-FDT-05') ? 'DOC-FDT-DEL' : 'DOC-FDT'),
      path: (s) => { const q = new URLSearchParams(s.query); return `documents/${s.id}/files/${q.get('file')}?expected_version=${q.get('expected_version')}`; } },
    fileSearch: { label: '이전 파일 검색 (F18·A14)', method: 'GET', flow: 'DOC-FSR', uses: ['query'], path: (s) => `files${s.query ? `?${s.query}` : ''}` },
    // ---- P8 양식 확장 — document/p8-s2-spec.md 4장(+ D-136)
    batchSkip: { label: '작성 안 함 (F27·A24)', method: 'POST', flow: 'DOC-SKP', uses: ['body', 'docId'], path: () => 'documents/batch-skip', docs: (s) => idList(s.docId) || bodyDocs(s) },
    unskip: { label: '되돌리기 (F28·A25)', method: 'POST', flow: 'DOC-USK', uses: ['id', 'body'], path: (s) => `documents/${s.id}/unskip`, doc: (s) => s.id },
    recentValues: { label: '최근 값 (F29·A26)', method: 'GET', flow: 'DOC-RCV', uses: ['query'], path: (s) => `documents/recent-values${s.query ? `?${s.query}` : ''}` },
    periodicBundle: { label: 'REQ 주 묶음 (F06·A04)', method: 'GET', flow: 'REQ-PWB', uses: ['query'], path: (s) => `periodic-bundles${s.query ? `?${s.query}` : ''}` },
    // ---- P9 주기형 작성 요구 — doc-requirements/p9-s2-spec.md(+ 6.1 단계 ID). ④ = 기간의 주기 문서(개발 API periodic_from·to)
    // 만들 줄이 없으면(모두 대상 아님) 05가 없는 도식
    periodicRun: { label: 'REQ 주기 문서 만들기 (F07·A05)', method: 'POST', uses: ['body'], path: () => 'periodic-runs',
      flow: (record, trace) => (trace && !trace.steps.some((x) => x.step_id === 'REQ-PRN-05') && record.ok ? 'REQ-PRN-NONE' : 'REQ-PRN'),
      scope: (s) => periodicScope(s, 'date_from', 'date_to') },
    periodicOpen: { label: 'REQ 주기 문서 하나 (F08·A06)', method: 'POST', flow: 'REQ-POD', uses: ['body'], path: () => 'periodic-documents',
      scope: (s) => periodicScope(s, 'date', 'date') },
    periodicRules: { label: 'REQ 주기 규칙 목록 (F09·A07)', method: 'GET', flow: 'REQ-PRL', uses: [], path: () => 'periodic-rules' },
    // ---- P10 문서함·결재함 — document-workflow/p10-s2-spec.md(+ 5.1 단계 ID)
    todo: { label: 'REQ 작성 필요 목록 (F10·A08)', method: 'GET', flow: 'REQ-TDO', uses: ['query'], path: (s) => `todo${s.query ? `?${s.query}` : ''}` },
    cancelSubmission: { label: 'WF 상신 취소 (WF-F05)', method: 'POST', flow: 'WF-CAN', uses: ['id', 'docId'], path: (s) => `approval-requests/${s.id}/cancel`, doc: (s) => s.docId },
    // ---- P11 CCP 대시보드 — dashboard/p11-s2-spec.md(+ 5장 단계 ID). 확인 대기 흐름은 헤더 없음 DOC-PND-ANON · summary=1 DOC-PND-SUM
    ccpDashboard: { label: 'REQ CCP 현황 (F11·A09)', method: 'GET', flow: 'REQ-CCP', uses: ['query'], path: (s) => `ccp-dashboard${s.query ? `?${s.query}` : ''}` },
    deviationsPending: { label: 'DOC 개선조치 확인 대기 (F30·A22)', method: 'GET', flow: 'DOC-PND', uses: ['query'], path: (s) => `deviations/pending${s.query ? `?${s.query}` : ''}` },
    deviationCheck: { label: 'DOC 개선조치 확인 (F31·A23)', method: 'POST', flow: 'DOC-DVK', uses: ['id', 'body', 'docId'], path: (s) => `deviations/${s.id}/check`, doc: (s) => s.docId },
  };
  function periodicScope(spec, fromKey, toKey) {
    try {
      const b = JSON.parse(spec.body || '{}');
      const ok = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v || '');
      return ok(b[fromKey]) && ok(b[toKey]) && b[fromKey] <= b[toKey] ? `periodic_from=${b[fromKey]}&periodic_to=${b[toKey]}` : null;
    } catch (e) { return null; }
  }
  // 견본 파일(콘솔 전용): 서명만 맞으면 서버 검사(DOC-VR-20)를 통과한다. bad = 이름은 .pdf, 내용은 글자
  const SAMPLE = {
    pdf: () => new Blob(['%PDF-1.4\n% console sample\n%%EOF\n'], { type: 'application/pdf' }),
    png: () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0])], { type: 'image/png' }),
    bad: () => new Blob(['not a pdf'], { type: 'application/pdf' }),
  };
  function multipartBody(spec) {
    const b = JSON.parse(spec.body || '{}');
    const fd = new FormData();
    const kind = b.kind || 'pdf';
    fd.append('file', new File([SAMPLE[kind] ? SAMPLE[kind]() : SAMPLE.pdf()], b.name || `콘솔_견본.${kind === 'png' ? 'png' : 'pdf'}`));
    fd.append('expected_version', String(b.expected_version ?? ''));
    return fd;
  }
  const payloadOf = (fn, spec) => (fn.multipart && spec.body ? multipartBody(spec) : spec.body);
  const idList = (text) => {
    const ids = String(text || '').split(',').map((x) => x.trim()).filter((x) => /^\d+$/.test(x));
    return ids.length ? ids : null;
  };
  function bodyDocs(spec) {
    try {
      const items = JSON.parse(spec.body || '{}').items || [];
      const ids = items.map((x) => x && x.document_id).filter((x) => Number.isInteger(x)).map(String);
      return ids.length ? ids : null;
    } catch (e) { return null; }
  }
  function dayScope(spec, key) {
    try {
      const day = JSON.parse(spec.body || '{}')[key];
      return /^\d{4}-\d{2}-\d{2}$/.test(day || '') ? `${key}=${day}` : null;
    } catch (e) { return null; }
  }
  const flowOf = (fn, record, trace) => (typeof fn.flow === 'function' ? fn.flow(record, trace) : fn.flow);

  const state = { flows: {}, batch: {}, history: [], active: null, preset: null };

  // ---------------------------------------------------------------- 개발 API (기록하지 않는 직접 호출)
  async function devGet(path) {
    const r = await fetch(path, { headers: { Accept: 'application/json' } });
    return r.ok ? r.json() : null;
  }
  const snapshot = (id) => (id ? devGet(`/api/dev/snapshot?document_id=${id}`) : Promise.resolve(null));
  // P6 S5 프리셋 사전 조건(ISS-019): 기록하지 않는 개발 API 쓰기 — /api/dev/fixtures/*
  async function devPost(path, body) {
    const r = await fetch(path, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`사전 조건을 만들지 못했습니다: ${(data && (data.message || data.code)) || r.status}${r.status === 404 ? ' (개발 콘솔이 꺼진 설정)' : ''}`);
    return data;
  }
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
      const record = await api.request(fn.method, fn.path(spec), payloadOf(fn, spec), { staffId: spec.staff });
      let trace = record.data && typeof record.data === 'object' && record.data.trace;
      if (!trace && record.traceId) trace = await devGet(`/api/dev/traces/${record.traceId}`);
      const scope = fn.scope(spec, record) || scopeBefore;
      const snapAfter = await scopeSnapshot(scope);
      const entry = { spec, fn, record, trace, before: snapBefore, after: snapAfter, scope, preset: state.preset };
      addEntry(entry);
      return entry;
    }
    if (fn.docs) {
      // P7 일괄: 문서 여러 건의 실행 전/후(④는 문서마다 표)
      const ids = fn.docs(spec) || [];
      const snaps = async () => Object.fromEntries(await Promise.all(ids.map(async (id) => [id, await snapshot(id)])));
      const multiBefore = await snaps();
      const record = await api.request(fn.method, fn.path(spec), payloadOf(fn, spec), { staffId: spec.staff });
      let trace = record.data && typeof record.data === 'object' && record.data.trace;
      if (!trace && record.traceId) trace = await devGet(`/api/dev/traces/${record.traceId}`);
      const entry = { spec, fn, record, trace, multi: { ids, before: multiBefore, after: await snaps() }, preset: state.preset };
      addEntry(entry);
      return entry;
    }
    const docBefore = fn.doc ? fn.doc(spec, null) : null;
    const snapBefore = before !== undefined ? before : await snapshot(docBefore);
    const record = await api.request(fn.method, fn.path(spec), payloadOf(fn, spec), { staffId: spec.staff });
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
    // 실패 분기 단계(…-02a, P6 …-02b 등 숫자 뒤 글자)는 도식에 없으면 순서 비교에서 뺀다
    const branch = (id) => /\d[a-z]$/.test(id) && !expected.includes(id);
    let mainRun = steps.filter(own).map((s) => s.step_id).filter((id) => (reqFlow ? expected.includes(id) : !branch(id)));
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

  // ---- P7 일괄 흐름(NFR-05): 머리 → 항목 단계 묶음 × n → 꼬리. 서버 flows.matches_batch와 같은 방식
  // (document_workflow/flows.py BATCH, documents/flows.py BATCH — /api/dev/flows의 batch로 받음).
  // 항목은 항목 시작 단계(묶음들의 첫 단계)마다 끊고, 끝이 a인 실패 분기 단계를 뺀 순서가
  //   성공 항목: 묶음 중 하나와 같아야, 실패 항목(fail 단계 있음): 묶음 중 하나의 앞부분과 같아야 한다.
  // 머리·꼬리는 길이까지 같아야 하고, 항목마다 trace의 성공·실패가 응답 결과 줄(results[i].ok)과 같아야 한다(P7 S5 검토 B1).
  // 입력 검사에서 멈추면(400) 항목·꼬리 없이 머리만.
  const compare = (flowId, steps, record) => (state.batch[flowId] ? compareBatch(flowId, steps, record) : compareFlow(flowId, steps));
  function compareBatch(flowId, steps, record) {
    const spec = state.batch[flowId];
    const kinds = Object.entries(spec.items);
    const start = kinds[0][1][0];
    const ids = steps.map((s) => s.step_id);
    const first = ids.indexOf(start);
    const tailAt = ids.lastIndexOf(spec.tail[0]);
    const plain = (list) => list.map((s) => s.step_id).filter((id) => !/\da$/.test(id));
    const chip = (id, cls) => `<span class="dc-chip ${cls}" title="${cls}">${esc(id)}</span>`;
    const headSteps = steps.slice(0, first >= 0 ? first : (tailAt >= 0 ? tailAt : steps.length));
    const byId = Object.fromEntries(headSteps.map((s) => [s.step_id, s]));
    const sameList = (a, b) => a.length === b.length && a.every((id, i) => id === b[i]);
    const headOk = sameList(plain(headSteps), spec.head);
    const headChips = spec.head.map((id) => chip(id, byId[id] ? byId[id].result : 'none')).join('')
      + headSteps.filter((s) => !spec.head.includes(s.step_id)).map((s) => chip(s.step_id, s.result === 'fail' ? 'fail extra' : 'extra')).join('');
    const headFail = headSteps.find((s) => s.result === 'fail');
    if (first < 0) {
      const reached = spec.head.filter((id) => byId[id]).length;
      const summary = headFail
        ? `<span class="dc-status-err">입력 검사에서 중단: ${esc(headFail.step_id)} (머리 ${reached}/${spec.head.length}) · 항목 처리 없음</span>`
        : `<span class="dc-status-err">⚠ 항목 단계가 없습니다 (머리 ${reached}/${spec.head.length})</span>`;
      return { chips: [], summary, innerHtml: `<div class="dc-batch-row"><span class="te-hint">머리</span> ${headChips}</div>` };
    }
    const body = steps.slice(first, tailAt >= 0 ? tailAt : steps.length);
    const items = [];
    body.forEach((s) => { if (s.step_id === start) items.push([]); items[items.length - 1].push(s); });
    const results = (record && record.data && record.data.results) || [];
    const checked = items.map((list, i) => {
      const fail = list.find((s) => s.result === 'fail');
      const run = plain(list);
      const kind = fail ? null : (kinds.find(([, want]) => sameList(run, want)) || [])[0];
      // 실패 항목: 도식 묶음의 앞부분까지 순서대로 돌다 멈춰야 한다
      const prefixOk = !!fail && run.length > 0 && kinds.some(([, want]) => run.length <= want.length && run.every((id, j) => id === want[j]));
      const result = results[i];
      const resultOk = !!result && result.ok === !fail;  // 응답 결과 줄과 성공·실패가 같아야
      const why = !result ? '응답 결과 줄 없음' : !resultOk ? `응답은 ${result.ok ? '성공' : '실패'}` : (fail ? (prefixOk ? '' : '실패 전 단계 순서 다름') : (kind ? '' : '단계 순서 다름'));
      return { list, fail, kind, result, ok: !why, why };
    });
    const tailSteps = tailAt >= 0 ? steps.slice(tailAt) : [];
    const tailOk = sameList(plain(tailSteps), spec.tail);
    const bad = checked.filter((x) => !x.ok);
    const countOk = results.length === checked.length;
    const failed = checked.filter((x) => x.fail).length;
    const count = {};
    checked.filter((x) => x.kind).forEach((x) => { count[x.kind] = (count[x.kind] || 0) + 1; });
    const kindText = Object.entries(count).map(([k, n]) => `${k} ${n}`).concat(failed ? [`실패 ${failed}`] : []).join(' · ');
    let summary;
    if (!headOk || !tailOk || bad.length || !countOk) {
      const where = !headOk ? '머리' : !tailOk ? '꼬리' : bad.length ? `항목 ${bad.map((x) => `${checked.indexOf(x) + 1}(${x.why})`).join(', ')}` : `항목 수(trace ${checked.length} · 응답 ${results.length})`;
      summary = `<span class="dc-status-err">⚠ 불일치 — ${esc(where)}이(가) 도식(${esc(flowId)})·응답과 다릅니다</span>`;
    } else {
      summary = `<span class="dc-status-ok">도식 일치 ✅ 머리 ${spec.head.length} → 항목 ${checked.length}(${esc(kindText)}) → 꼬리 ${spec.tail.length}</span>`;
      if (failed) summary += ` <span class="te-hint">· 실패 항목은 그 항목만 되돌림(부분 실패)</span>`;
    }
    const itemRows = checked.map((x, i) => {
      const r = x.result || {};
      const who = r.document_id ? `#${esc(r.document_id)}` : (r.approval_id ? `칸 #${esc(r.approval_id)}` : '');
      let tag = x.fail
        ? `${chip('실패', 'fail')} <span class="te-hint">${esc(x.fail.step_id)}${r.error ? ` · ${esc(r.error.code)}` : ''}</span>`
        : (x.kind ? chip(x.kind, 'pass') : '');
      if (!x.ok) tag += ` ${chip('불일치', 'fail extra')} <span class="te-hint">${esc(x.why)}</span>`;
      return `<div class="dc-batch-row" data-item="${i + 1}"><span class="te-hint">항목 ${i + 1}</span> <b class="mono">${who}</b> ${tag}
        <details class="dc-inner"><summary>단계 ${x.list.length}개</summary><div class="dc-inner-row">${x.list.map((s) => chip(s.step_id, s.result)).join('')}</div></details></div>`;
    }).join('');
    const tailChips = spec.tail.map((id) => chip(id, tailSteps.find((s) => s.step_id === id)?.result || 'none')).join('');
    return {
      chips: [],
      summary,
      innerHtml: `<div class="dc-batch-row"><span class="te-hint">머리</span> ${headChips}</div>${itemRows}<div class="dc-batch-row"><span class="te-hint">꼬리</span> ${tailChips}</div>`,
    };
  }

  function renderTrace(entry) {
    const { trace, fn } = entry;
    if (!trace) {
      $('#dcFlowSummary').innerHTML = '';
      $('#dcFlowChips').innerHTML = '';
      $('#dcTraceBody').innerHTML = '<div class="dc-empty">trace가 없습니다(개발 콘솔 설정이 꺼져 있거나 만료됨).</div>';
      return;
    }
    const flowId = flowOf(fn, entry.record, trace);
    const { chips, summary, innerHtml } = compare(flowId, trace.steps, entry.record);
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
    document: 'document_id', doc_section: 'section_id', document_template: 'template_id', staff: 'id',
    approval_request: 'request_id', approval: 'approval_id',
    document_ref: 'ref_id', deviation_action: 'deviation_id',
    lots: 'id', production_batches: 'id', incoming_receipts: 'id',  // 수불 테이블(C2)
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
    if (entry.multi) {
      const { ids, before: mb, after: ma } = entry.multi;
      if (!ids.length) {
        $('#dcDbTitle').textContent = '';
        $('#dcDbBody').innerHTML = '<div class="dc-empty">비교할 문서가 없습니다. "④ 비교할 문서 id"에 문서 id를 쉼표로 넣으세요.</div>';
        return;
      }
      $('#dcDbTitle').innerHTML = `${groupLabel(entry)}문서 ${ids.length}건 · document_id = ${ids.map(esc).join(', ')} <span class="te-hint">· 문서마다 실행 전/후</span>`;
      $('#dcDbBody').innerHTML = ids.map((id) => {
        const b = (mb[id] && mb[id].tables) || {};
        const a = (ma[id] && ma[id].tables) || {};
        return `<div class="dc-doc-block" data-doc-block="${esc(id)}"><div class="dc-sub">document_id = ${esc(id)}</div>${docTables(b, a, onlyChanged)}</div>`;
      }).join('');
      return;
    }
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
    $('#dcDbBody').innerHTML = docTables(b, a, onlyChanged);
  }
  const docTables = (b, a, onlyChanged) => ['document', 'doc_section', 'document_ref', 'deviation_action', 'deviation_checker', 'approval_request', 'approval', 'document_correction', 'lots', 'document_template', 'staff']
    .filter((t) => t in a || t in b).map((t) => diffTable(t, b[t], a[t], onlyChanged)).join('');

  function scopeTables(before, after, onlyChanged) {
    const sb = (before && before.tables) || {};
    const sa = (after && after.tables) || {};
    return ['lots', 'incoming_receipts', 'production_batches', 'document', 'doc_section', 'document_ref']
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
      const flowId = flowOf(e.fn, e.record, e.trace);
      return `<div class="dc-line"><span class="te-hint">호출 ${i + 1}</span>${compare(flowId, e.trace.steps, e.record).summary} <span class="te-hint">도식 ${esc(flowId)}</span></div>`;
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
  // P7: 목록에 육안검사 묶음 줄(kind bundle — 문서 id 없음)이 섞이므로 문서 줄만 본다
  async function findDoc(status, pred = () => true) {
    const r = await quietGet(`documents?status=${status}`);
    let page = 1;
    let items = r ? r.items : [];
    while (items.length) {
      const hit = items.find((x) => x.kind !== 'bundle' && pred(x));
      if (hit) return hit;
      page += 1;
      const next = await quietGet(`documents?status=${status}&page=${page}`);
      items = next ? next.items : [];
    }
    return null;
  }
  // P7 S6(ISS-019): 첫 페이지만 보면 작성 요구·콘솔 준비 문서(작성중)가 많을 때 CCP 가열 문서를 못 찾는다
  // → CCP 가열 양식으로 거르고 페이지를 넘기며 찾는다(findDoc과 같은 방식)
  async function docWithRounds(min = 2) {
    const tid = await ccpTemplateId();
    for (let page = 1; page <= 50; page += 1) {
      const r = await quietGet(`documents?status=draft&template_id=${tid}&page=${page}`);
      const items = r ? r.items : [];
      if (!items.length) break;
      for (const d of items) {
        if (d.kind === 'bundle' || d.submitted_at) continue;
        const full = await quietGet(`documents/${d.document_id}`);
        if (full && full.template.type_code === 'CCP_MONITORING' && full.sections.filter((s) => s.section_def === 'rounds').length >= min) return full;
      }
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
  const need = (doc, what) => { if (!doc) throw new Error(`${what} 문서가 없습니다. 개발 DB를 다시 만드세요(init → seed_dev_workflow → seed_dev_p4).`); return doc; };
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
        // C3 S6(ISS-032): 파일 필수 양식(D01·D02)의 반려 문서는 파일을 끊었으면 작성완료가 files_required로 막힌다 → 빼고 고름
        const d = need(await findDoc('rejected', (x) => !['D01', 'D02'].includes(x.template && x.template.type_code)), 'rejected');
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
  // P7: D03은 목록에서 입고일 묶음 줄(kind bundle)로 온다 → 그 입고일 묶음 조회(REQ-A03)로 문서 id를 푼다
  async function docIdsOf(item, status) {
    if (item.kind !== 'bundle') return [item.document_id];
    const b = await quietGetAs(`incoming-inspections?received_date=${item.work_date}`, 3);
    return b ? b.lots.filter((l) => l.document && (!status || l.document.status === status)).map((l) => l.document.document_id) : [];
  }
  async function p4Doc(code, status, pred = () => true) {
    const tid = await templateIdOf(code);
    for (let page = 1; page <= 10; page += 1) {
      const r = await quietGet(`documents?template_id=${tid}&status=${status}&page=${page}`);
      if (!r || !r.items.length) break;
      for (const item of r.items) {
        for (const id of await docIdsOf(item, status)) {
          const full = await quietGet(`documents/${id}`);
          if (full && pred(full)) return full;
        }
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
  // C2: 수불 입고 서비스로 입고 — 구분·단위·원산지는 품목 값(보내지 않음)
  const lotBody = async (day, extra = {}) => ({ item_id: await itemId('유자'), supplier_name: '콘솔농협',
    received_date: day, quantity: 100, expiration_status: 'NONE', ...extra });  // 원료: 소비기한 유무 명시(수불 0007)
  const d03Of = (lot) => lot.documents.find((d) => d.type_code === 'D03');
  async function lotWhere(pred, what) {
    const hit = (await reqList('lots')).find(pred);
    if (!hit) throw new Error(`${what} LOT이 없습니다. ${REQ_HINT}.`);
    return hit;
  }

  PRESETS.push(
    { id: 'REQ-PS-01', label: '입고 정상', expect: '201 · REQ-DEV-LOT 도식 일치(안쪽 DOC-GOC ×3) · lots·incoming_receipts +1(수불 입고 서비스), document +3(D01·D02·D03 새로 만듦), doc_section(info 초기값), document_ref +3(모두 문서 단위)',
      prepare: async () => ({ func: 'reqLot', body: J(await lotBody(await freeDay())) }) },
    { id: 'REQ-PS-02', label: '같은 LOT 다시 호출', expect: '200 · REQ-DEV-RE-LOT 도식 일치 · 안쪽 DOC-GOC-01a(이미 있음) ×3 · 결과 이미 있음 ×3 · lots.updated_at만 변경(자기 쓰기 먼저)',
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
    { id: 'REQ-PS-07', label: '생산 시작(제조)', expect: '201 · REQ-DEV-BAT 도식 일치(REQ-BAT-03 ×3) · production_batches +1(개발 전용 INSERT), document +3(CCP-1P·2B·3P), document_ref(배치 + 공정) +3',
      prepare: async () => ({ func: 'reqBatch', body: J({ item_id: await itemId('유자차'), process_type: 'MANUFACTURE', manufactured_date: localDay(0), quantity_kg: 900 }) }) },
    { id: 'REQ-PS-08', label: '같은 배치 다시 호출 / 포장 배치', expect: '[호출 1] 200 · 이미 있음 ×3 · ④ production_batches ~1(updated_at만) [호출 2] 201 · REQ-BAT-03 건너뜀(공정 없음) · ④ production_batches +1, 문서 변화 없음',
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
    { id: 'REQ-PS-12', label: '그날 다른 LOT의 D03이 승인돼 있어도 새 LOT은 새 D03', expect: '201 · REQ-DEV-LOT 도식 일치 · D01·D02·D03 모두 새로 만듦(요구 키 D03|lot:{id}) · 다른 LOT의 D03 변화 없음 · ④(그날 범위) lots·incoming_receipts +1, document +3, document_ref +3',
      prepare: async () => {
        const lot = await lotWhere((l) => { const d = d03Of(l); return d && ['completed', 'submitted', 'approved'].includes(d.status); }, '육안검사가 작성완료·결재중·승인인');
        return { func: 'reqLot', body: J(await lotBody(lot.received_date, { supplier_name: '콘솔농협(같은 날)' })) };
      } },
  );


  // ---------------------------------------------------------------- 프리셋 WF-PS-14~22 · EFF-PS-01~05 · REQ-PS-11 (document-workflow/p6-s1-screens.md 6장, P6a 6장)
  // 사전 조건은 시드에 기대지 않고 프리셋을 불러올 때 새 LOT·D03을 만든다(ISS-019, POST /api/dev/fixtures/d03).
  // 그래서 같은 프리셋을 여러 번 실행할 수 있다. 결재선은 2칸(staff 3·1).
  // 불러오기 때 만든 준비 데이터(설명란에 표시 — P6 S5 검토 A4)
  let prepared = [];
  const fixture = async (body) => {
    const made = await devPost('/api/dev/fixtures/d03', body);
    prepared.push(made);
    return made;
  };
  const FIX_SLOTS = [{ slot_no: 1, label: '담당', approver_id: 3 }, { slot_no: 2, label: 'HACCP팀장', approver_id: 1 }];
  const FIX_REASON = '판정 오기 정정(콘솔)';
  const p6 = (preset) => ({ unit: 'P6', ...preset });
  async function fixtureDoc(body) {
    const made = await fixture(body);
    return { made, d: await quietGet(`documents/${made.document_id}`) };
  }
  // 대기 칸을 결재자로 차례로 처리(마지막 칸만 result)
  async function decideAll(exec, documentId, last) {
    const req = await latestRequest(documentId);
    const pending = req ? req.slots.filter((x) => x.state === 'pending') : [];
    for (let i = 0; i < pending.length; i += 1) {
      const result = i === pending.length - 1 ? last : { result: 'approved' };
      await exec(decideSpec(pending[i], pending[i].approver_id, result, documentId));
    }
  }

  PRESETS.push(
    p6({ id: 'WF-PS-14', label: '정정 시작', expect: '200 · DOC-COR 도식 일치(01 입력 → 02 정정 기록 INSERT…SELECT → 03 조건부 UPDATE approved → 04 → SIG-01 → 05) · document approved→correcting·version+1, document_correction +1(사유, closed_at 비움)',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'approved' }); return { func: 'correction', id: String(d.document_id), body: J({ expected_version: d.version, reason: FIX_REASON }) }; } }),
    p6({ id: 'WF-PS-15', label: '정정 사유 없음', expect: '400 VALIDATION_ERROR(reason) · DOC-COR-01 입력 확인에서 실패 · DB 변화 없음',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'approved' }); return { func: 'correction', id: String(d.document_id), body: J({ expected_version: d.version, reason: '   ' }) }; } }),
    p6({ id: 'WF-PS-16', label: '승인 아닌 문서 정정', expect: '409 INVALID_TRANSITION · 결재중 문서 · DOC-COR 조건부 단계 0행 → 실패 단계 · 롤백으로 DB 변화 없음(정정 기록도 없음)',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'submitted' }); return { func: 'correction', id: String(d.document_id), body: J({ expected_version: d.version, reason: FIX_REASON }) }; } }),
    p6({ id: 'WF-PS-17', label: '정정 중 작성완료', expect: '200 · DOC-CMP 도식 일치(SIG-01 안쪽 EFF-JDG: 같은 판정 → 변화 없음) · document correcting→completed·version+1, 정정 기록 열린 채 유지(closed_at 비움)',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'correcting', edited: true }); return { func: 'complete', id: String(d.document_id), body: J({ expected_version: d.version }) }; } }),
    p6({ id: 'WF-PS-18', label: '정정 재상신 → 승인', expect: '상신 201 → 승인 200 ×2(마지막 WF-DEC-APPROVED, DOC-APV + SIG-01) · approval_request +1(2회차, 정정 상신), document approved, 정정 기록 closed·approved · 회차 이력(F: APR 문서별 회차)에서 1회차 superseded_by 2',
      prepare: async () => {
        const { d } = await fixtureDoc({ state: 'correction_completed', edited: true });
        const sub = { func: 'submit', id: String(d.document_id), body: J({ expected_version: d.version, slots: FIX_SLOTS }) };
        return { ...sub, script: async (exec) => {
          const first = await exec({ ...sub, staff: '3' });
          if (!first.record.ok) return;
          await decideAll(exec, d.document_id, { result: 'approved', comment: '정정 승인(콘솔)' });
          await exec({ func: 'history', id: String(d.document_id), staff: '3' });
        } };
      } }),
    p6({ id: 'WF-PS-19', label: '정정 회차 반려', expect: '200 · WF-DEC-REJECTED(DOC-RJT CASE: 열린 정정 → correcting) · document submitted→correcting(rejected 아님), completed_at/by 비움 · 회차 rejected · 유효 승인본(1회차) 그대로',
      prepare: async () => {
        const { d } = await fixtureDoc({ state: 'correction_submitted', edited: true });
        const req = await latestRequest(d.document_id);
        const slot = req.slots.find((x) => x.state === 'pending');
        return decideSpec(slot, slot.approver_id, { result: 'rejected', comment: '정정 내용 확인 필요(콘솔)' }, d.document_id);
      } }),
    p6({ id: 'WF-PS-20', label: '유효 승인본 조회(A8)', expect: '200 · REQ-FND(안쪽 APR-LAT-01 = A8) · 정정 중 D03(판정 FAIL로 고침)이어도 승인본 기준 판정 PASS, 정정 중 열에 사유 · DB 변화 없음',
      prepare: async () => { const { made } = await fixtureDoc({ state: 'correcting', change_to: 'FAIL' }); return { func: 'lotDocs', id: String(made.lot_id) }; } }),
    p6({ id: 'WF-PS-21', label: '정정 취소(수정 전)', expect: '200 · DOC-CCN 도식 일치(02 조건부 UPDATE correcting·버전·수정 없음 → 03 정정 기록 닫기) · document correcting→approved·version+1, 작성완료 기록 복원 · document_correction closed_at·outcome cancelled',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'correcting' }); return { func: 'correctionCancel', id: String(d.document_id), body: J({ expected_version: d.version }) }; } }),
    p6({ id: 'WF-PS-22', label: '수정 뒤 정정 취소', expect: '409 CORRECTION_HAS_CHANGES · DOC-CCN-02 영향 0행 → 실패 단계 DOC-CCN-02b · DB 변화 없음',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'correcting', edited: true }); return { func: 'correctionCancel', id: String(d.document_id), body: J({ expected_version: d.version }) }; } }),
    // ---- 판정 연동(EFF, D-079·D-080). LOT 상태는 ④의 lots 표(문서가 참조하는 개발 LOT)
    p6({ id: 'EFF-PS-01', label: 'D03 작성완료 → 판정 전달 (적합·부적합 2건)', expect: '[호출 1·2] 200 · DOC-CMP 안쪽 DOC-SIG-01 → EFF-JDG 01~04 · document completed · lots QUARANTINE→AVAILABLE(적합) / →REJECTED(부적합)',
      prepare: async () => {
        const pass = (await fixtureDoc({ state: 'draft', verdict: 'PASS' })).d;
        const fail = (await fixtureDoc({ state: 'draft', verdict: 'FAIL' })).d;
        const a = { func: 'complete', id: String(pass.document_id), body: J({ expected_version: pass.version }) };
        return { ...a, script: async (exec) => {
          await exec({ ...a, staff: '3' });
          await exec({ func: 'complete', id: String(fail.document_id), body: J({ expected_version: fail.version }), staff: '3' });
        } };
      } }),
    p6({ id: 'EFF-PS-02', label: '같은 판정으로 다시 작성완료', expect: '작성 재개 200 → 작성완료 200 · EFF-JDG 통과(같은 판정 = 변화 없음) · lots 그대로(AVAILABLE)',
      prepare: async () => {
        const { d } = await fixtureDoc({ state: 'completed', verdict: 'PASS' });
        const re = { func: 'reopen', id: String(d.document_id), body: J({ expected_version: d.version }) };
        return { ...re, script: async (exec) => {
          const first = await exec({ ...re, staff: '3' });
          if (!first.record.ok) return;
          await exec({ func: 'complete', id: String(d.document_id), body: J({ expected_version: first.record.data.version }), staff: '3' });
        } };
      } }),
    p6({ id: 'EFF-PS-03', label: '사유 없이 판정 변경', expect: '작성 재개·수정(PASS→FAIL)·개선조치 200 → 작성완료 409 INVENTORY_REJECTED(details 1건: 판정 변경에는 사유) · EFF-JDG-02 거부 → 롤백 · 문서 작성중 그대로, lots AVAILABLE 그대로',
      prepare: async () => {
        const { d } = await fixtureDoc({ state: 'completed', verdict: 'PASS' });
        const re = { func: 'reopen', id: String(d.document_id), body: J({ expected_version: d.version }) };
        const insp = d.sections.find((x) => x.section_def === 'inspection');
        return { ...re, script: async (exec) => {
          const first = await exec({ ...re, staff: '3' });
          if (!first.record.ok) return;
          const upd = await exec({ func: 'update', id: String(d.document_id), staff: '3',
            body: J({ expected_version: first.record.data.version, sections: { update: [{ section_id: insp.section_id, values: { packaging: '불량', verdict: 'FAIL' } }] } }) });
          if (!upd.record.ok) return;
          await exec({ func: 'devCreate', id: String(d.document_id), staff: '4', body: J({ description: '외포장 파손(콘솔)', actor_id: 4, checker_ids: [2] }) });
          await exec({ func: 'complete', id: String(d.document_id), body: J({ expected_version: upd.record.data.version }), staff: '3' });
        } };
      } }),
    p6({ id: 'EFF-PS-04', label: '정정 사유로 판정 변경', expect: '200 · DOC-CMP → SIG-01 → EFF-JDG(note 없음 → 정정 사유가 reason) · document correcting→completed(정정 열린 채) · lots AVAILABLE→REJECTED',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'correcting', change_to: 'FAIL' }); return { func: 'complete', id: String(d.document_id), body: J({ expected_version: d.version }) }; } }),
    p6({ id: 'EFF-PS-05', label: '사용된 LOT 판정 변경', expect: '409 INVENTORY_REJECTED(사용된 LOT) · EFF-JDG 거부 → 롤백 · 문서 정정 중 그대로, lots AVAILABLE 그대로(사용됨 = 입고 외 수불 이동, C2)',
      prepare: async () => { const { d } = await fixtureDoc({ state: 'correcting', change_to: 'FAIL', used: true }); return { func: 'complete', id: String(d.document_id), body: J({ expected_version: d.version, note: '사용 뒤 판정 변경 시도(콘솔)' }) }; } }),
    p6({ id: 'REQ-PS-11', label: '입고 + 육안검사 함께', expect: '201 · REQ-DEV-LOT-INSP 도식 일치(REQ-LOT-00b 형식 검사 → … → REQ-DEV-02b 수불 판정 함수) · D03 inspection 값 채움(작성중), 결과 inspection_applied true · lots AVAILABLE',
      prepare: async () => ({ func: 'reqLot', body: J(await lotBody(await freeDay(), { inspection: { appearance: '양호', packaging: '양호', labeling: '양호', verdict: 'PASS' } })) }) }),
  );

  // ---------------------------------------------------------------- 프리셋 P7 (document-workflow/p7-s1-screens.md 6장, p7-s2-spec 3.5)
  // WF-PS-23~33 · DOC-PS-28·29 · REQ-PS-13. 사전 조건은 모두 개발 API(fixtures/d03 — received_date·count·inspector·
  // submitted_partial·rejected·lot_only)로 불러올 때 만든다(ISS-019). 준비 문서는 프리셋마다 빈 입고일(freeDays)에 만들어
  // 서로·오늘 묶음과 섞이지 않는다(WF-PS-33은 빈 입고일 2개).
  // 일괄 쓰기의 ④는 문서마다 실행 전/후(④ 비교할 문서 id = 쉼표 목록). ③은 항목별 묶음 비교(compareBatch).
  const p7 = (preset) => ({ unit: 'P7', ...preset });
  // 입고일을 안 주면 프리셋마다 빈 입고일 하나(오늘 묶음·결재함에 콘솔 준비 문서가 섞이지 않게)
  let p7DayCache = null;
  async function p7Day() {
    if (!p7DayCache) [p7DayCache] = await freeDays(1);
    return p7DayCache;
  }
  // count > 1이면 {items}로 온다 → 항상 목록으로
  async function fixtures(body) {
    const made = await devPost('/api/dev/fixtures/d03', { received_date: await p7Day(), ...body });
    const list = made.items || [made];
    prepared.push(...list);
    return list;
  }
  const one = async (body) => (await fixtures(body))[0];
  async function freeDays(n) {
    const out = [];
    for (let back = 40; back < 400 && out.length < n; back += 1) {
      const day = localDay(-back);
      if (!(await reqList('lots', `?date=${day}`)).length) out.push(day);
    }
    if (out.length < n) throw new Error('빈 날짜를 찾지 못했습니다.');
    return out;
  }
  async function slotOf(documentId, approver) {
    const req = await latestRequest(documentId);
    const slot = req && req.slots.find((x) => x.approver_id === approver && x.state === 'pending');
    if (!slot) throw new Error(`문서 #${documentId}에 staff ${approver}의 대기 칸이 없습니다.`);
    return slot.approval_id;
  }
  async function quietPostAs(path, body, staff) {
    const r = await fetch(`/api/v1/${path}`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Staff-Id': String(staff) }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`사전 조건을 만들지 못했습니다: ${(data && (data.message || data.code)) || r.status}`);
    return data;
  }
  async function d03TemplateId() {
    const t = await quietGet('templates');
    const hit = t && t.items.find((x) => x.type_code === 'D03');
    if (!hit) throw new Error('D03 양식이 없습니다.');
    return hit.template_id;
  }
  const ids = (list) => list.map((m) => m.document_id).join(',');
  const items = (list) => list.map((m) => ({ document_id: m.document_id, expected_version: m.version }));

  PRESETS.push(
    p7({ id: 'WF-PS-23', label: '일괄 승인 정상', expect: '200 · succeeded 3 · ③ WF-BAP 도식 일치(머리 7 → 항목 3: approved 1 · progress 2 → 꼬리) · ④ 문서 3건: approval 3행 approved, 마지막 칸이던 문서 1건만 document approved(나머지 submitted 그대로)',
      prepare: async () => {
        const list = [...await fixtures({ state: 'submitted', count: 2 }), await one({ state: 'submitted_partial' })];
        const slots = await Promise.all(list.map((m) => slotOf(m.document_id, 1)));
        return { func: 'batchApprove', staff: '1', docId: ids(list), body: J({ approval_ids: slots, comment: '일괄 확인(콘솔)' }) };
      } }),
    p7({ id: 'WF-PS-24', label: '일괄 승인 일부 실패', expect: '200 · succeeded 2 · failed 1(REQUEST_CLOSED — 다른 결재자 반려로 회차 종료) · ③ 항목 3(progress 2 · 실패 1) · ④ 성공 2건만 approval approved, 실패 문서 변화 없음',
      prepare: async () => {
        const ok = await fixtures({ state: 'submitted', count: 2 });
        const closed = await one({ state: 'rejected' });
        const req = await latestRequest(closed.document_id);
        const mine = req.slots.find((x) => x.approver_id === 3);
        const slots = [...await Promise.all(ok.map((m) => slotOf(m.document_id, 3))), mine.approval_id];
        return { func: 'batchApprove', staff: '3', docId: ids([...ok, closed]), body: J({ approval_ids: slots }) };
      } }),
    p7({ id: 'WF-PS-25', label: '대상 양식 아님(승인)', expect: '400 INVALID_REQUEST(details not_batchable, path approval_ids[1]) · ③ 입력 검사(WF-BAP-04)에서 중단, 항목 처리 없음 · ④ 변화 없음',
      prepare: async () => {
        const d03 = await one({ state: 'submitted' });
        const other = await pendingItem(2, (x) => x.request.template_id !== undefined);
        const t = await quietGet(`templates/${other.request.template_id}`);
        if (t && t.type_code === 'D03') throw new Error('D03이 아닌 결재 대기 칸을 찾지 못했습니다(seed_dev_workflow).');
        return { func: 'batchApprove', staff: '3', docId: `${d03.document_id},${other.request.document_id}`, body: J({ approval_ids: [await slotOf(d03.document_id, 3), other.approval_id] }) };
      } }),
    p7({ id: 'WF-PS-30', label: '대상 양식 아님(상신)', expect: '400 INVALID_REQUEST(not_batchable, path items[1]) · ③ 입력 검사(WF-BSB-04, DOC-BRF)에서 중단 · ④ 변화 없음(D03도 작성완료 그대로)',
      prepare: async () => {
        const d03 = await one({ state: 'completed' });
        const other = need(await findDoc('draft', (d) => d.template.type_code !== 'D03'), 'D03이 아닌 draft');
        return { func: 'batchSubmit', staff: '3', docId: `${d03.document_id},${other.document_id}`,
          body: J({ items: [...items([d03]), { document_id: other.document_id, expected_version: other.version }], slots: FIX_SLOTS }) };
      } }),
    p7({ id: 'WF-PS-31', label: '일괄 상신 버전 충돌', expect: '[호출 1·2] 작성 재개·작성완료 200(문서 B 버전 +2) → [호출 3] 일괄 상신 200 · succeeded 1 · failed 1(VERSION_CONFLICT, 문서 B) · ④ 문서 A만 submitted + approval_request +1',
      prepare: async () => {
        const [a, b] = await fixtures({ state: 'completed', count: 2 });
        const submit = { func: 'batchSubmit', docId: ids([a, b]), body: J({ items: items([a, b]), slots: FIX_SLOTS }) };
        return { ...submit, script: async (exec) => {
          const re = await exec({ func: 'reopen', id: String(b.document_id), body: J({ expected_version: b.version }), staff: '3' });
          if (!re.record.ok) return;
          await exec({ func: 'complete', id: String(b.document_id), body: J({ expected_version: re.record.data.version }), staff: '3' });
          await exec({ ...submit, staff: '3' });
        } };
      } }),
    p7({ id: 'WF-PS-32', label: '남의 칸 섞임', expect: '200 · succeeded 1 · failed 1(NOT_YOUR_SLOT — staff 1 칸) · ③ 항목 2(progress 1 · 실패 1) · ④ 내 칸(staff 3)만 approved',
      prepare: async () => {
        const [a, b] = await fixtures({ state: 'submitted', count: 2 });
        return { func: 'batchApprove', staff: '3', docId: ids([a, b]), body: J({ approval_ids: [await slotOf(a.document_id, 3), await slotOf(b.document_id, 1)] }) };
      } }),
    p7({ id: 'WF-PS-33', label: '결재함 입고일 필터(컷 ②)', expect: '200 · APR-INB(template_id = D03 + from = to = 입고일, D-098) · 입고일 다른 결재중 D03 2건 중 그 입고일 1건만 · DB 변화 없음',
      prepare: async () => {
        const [day1, day2] = await freeDays(2);
        await one({ state: 'submitted', received_date: day1 });
        await one({ state: 'submitted', received_date: day2 });
        return { func: 'inbox', staff: '3', query: `box=pending&template_id=${await d03TemplateId()}&from=${day1}&to=${day1}` };
      } }),
    p7({ id: 'WF-PS-26', label: '건수 초과(51개)', expect: '400 INVALID_REQUEST(details max, path approval_ids) · ③ 입력 형식(WF-BAP-01, API)에서 중단 · DB 변화 없음. 상신·점검자 지정도 같은 상한(S4 테스트)',
      prepare: async () => ({ func: 'batchApprove', staff: '3', docId: '', body: J({ approval_ids: Array.from({ length: 51 }, (_, i) => 900000 + i) }) }) }),
    p7({ id: 'WF-PS-27', label: '일괄 상신 정상', expect: '200 · succeeded 2 · ③ WF-BSB 도식 일치(머리 12 → 항목 2: submitted → 꼬리) · ④ 문서마다 completed→submitted, approval_request +1(각 1회차, subject = LOT … · 품명 · 매입처 — ISS-018), approval +2',
      prepare: async () => {
        const list = await fixtures({ state: 'completed', count: 2 });
        return { func: 'batchSubmit', staff: '3', docId: ids(list), body: J({ items: items(list), slots: FIX_SLOTS }) };
      } }),
    p7({ id: 'WF-PS-28', label: '일괄 상신 일부 실패', expect: '200 · succeeded 1 · failed 1(DOCUMENT_LOCKED, details code draft — 화면 문구 "작성완료 상태가 아닙니다") · ④ 작성완료 문서만 submitted, 작성중 문서 변화 없음',
      prepare: async () => {
        const ok = await one({ state: 'completed' });
        const draft = await one({ state: 'draft' });
        return { func: 'batchSubmit', staff: '3', docId: ids([ok, draft]), body: J({ items: items([ok, draft]), slots: FIX_SLOTS }) };
      } }),
    p7({ id: 'DOC-PS-28', label: '점검자 일괄 지정', expect: '200 · succeeded 2(changed) · failed 1(DOCUMENT_LOCKED, details code completed) · ③ DOC-BIN 도식 일치(머리 3 → 항목 3: changed 2 · 실패 1 → 꼬리) · ④ 작성중 2건 doc_section info.inspector → 5·version+1, 작성완료 1건 변화 없음',
      prepare: async () => {
        const list = [...await fixtures({ state: 'draft', count: 2, inspector: null }), await one({ state: 'completed' })];
        return { func: 'batchInspector', staff: '3', docId: ids(list), body: J({ items: items(list), inspector_id: 5 }) };
      } }),
    p7({ id: 'REQ-PS-13', label: '입고일 묶음 조회', expect: '200 · REQ-BDL 도식 일치(뷰 → N4 → F26 → A8 → A10) · SQL 8개 이하 · lots 4줄(작성중·작성완료·결재중 + 문서 없음 1줄 document null), summary documents 3 · DB 변화 없음',
      prepare: async () => {
        const [day] = await freeDays(1);
        for (const state of ['draft', 'completed', 'submitted']) await one({ state, received_date: day });
        prepared.push(await devPost('/api/dev/fixtures/d03', { lot_only: true, received_date: day }));  // 문서 없는 LOT
        return { func: 'incoming', staff: '3', query: `received_date=${day}` };
      } }),
    p7({ id: 'DOC-PS-29', label: '문서 목록 묶음 줄', expect: '200 · DOC-LST 도식 일치(01~07) · SQL 6개 이하 · 묶음 줄 1개(kind bundle, count 3, status_counts 작성중·작성완료·결재중 각 1) + CCP 1줄, total 2 · DB 변화 없음',
      prepare: async () => {
        const [day] = await freeDays(1);
        for (const state of ['draft', 'completed', 'submitted']) await one({ state, received_date: day });
        const ccp = await quietPostAs('documents', { ...ccpBody(await ccpTemplateId(), ['09:00']), work_date: day }, 3);
        prepared.push({ lot_number: '-', document_id: ccp.document_id, status: `${ccp.status} CCP` });
        return { func: 'list', staff: '3', query: `from=${day}&to=${day}` };
      } }),
    p7({ id: 'WF-PS-29', label: '결재 대상 요약(ISS-018)', expect: '201 · WF-SUB 도식 일치 · 응답 request.subject = "LOT AYJ… · 유자 · 콘솔준비농협"(상세 target_summary) · ④ approval_request.subject 같은 값',
      prepare: async () => {
        const m = await one({ state: 'completed' });
        return { func: 'submit', staff: '3', id: String(m.document_id), body: J({ expected_version: m.version, slots: FIX_SLOTS }) };
      } }),
  );

  // ---------------------------------------------------------------- 프리셋 FILE-PS-01~08 · P8-PS-01~10 (C3 S5, D-135)
  // 사전 조건은 불러올 때 개발 API로 만든다(ISS-019): fixtures/file-doc(새 LOT의 D01·D02 + 견본 파일),
  // fixtures/periodic(빈 주에 D10·D12·D11 — N1, 주기 작성 요구 형식 record_key)
  const filePs = (preset) => ({ unit: 'FILE', ...preset });
  const p8 = (preset) => ({ unit: 'P8', ...preset });
  async function fileDoc(body) {
    const made = await devPost('/api/dev/fixtures/file-doc', body);
    prepared.push({ lot_number: made.lot_number, document_id: made.document_id, status: `${made.status} · 파일 ${made.files.length}개`, kind: body.type_code || 'D01' });
    return made;
  }
  async function periodicWeek(body) {
    const made = await devPost('/api/dev/fixtures/periodic', body);
    made.items.forEach((x) => prepared.push({ lot_number: '-', document_id: x.document_id, status: `${body.type_code || 'D10'} ${x.work_date} ${x.status}` }));
    return made;
  }
  const UP = (doc, extra) => J({ expected_version: doc.version, name: '콘솔_성적서.pdf', kind: 'pdf', ...extra });
  const dayAfter = (day, n) => { const d = new Date(`${day}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  async function typeTemplateId(code) {
    const t = await quietGet('templates');
    const hit = t && t.items.find((x) => x.type_code === code);
    if (!hit) throw new Error(`${code} 양식이 없습니다(seed_dev_p4 — C3 양식 포함).`);
    return hit.template_id;
  }
  async function quietPatchAs(path, body, staff) {
    const r = await fetch(`/api/v1/${path}`, { method: 'PATCH', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Staff-Id': String(staff) }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`사전 조건을 만들지 못했습니다: ${(data && (data.message || data.code)) || r.status}`);
    return data;
  }

  PRESETS.push(
    filePs({ id: 'FILE-PS-01', label: '파일 올리기 정상(D01)', expect: '201 · DOC-FUP 도식 일치(01~06: 형식 → 파일 쓰기(트랜잭션 밖) → 문서 잠금 → file·document_file INSERT → 결과) · ④ file +1, document_file +1, document version +1',
      prepare: async () => { const m = await fileDoc({}); return { func: 'fileUpload', staff: '3', id: String(m.document_id), body: UP(m) }; } }),
    filePs({ id: 'FILE-PS-02', label: '형식이 다른 파일 거부', expect: '400 FILE_REJECTED(details code type — "파일 내용이 확장자와 맞지 않습니다") · DOC-FUP-02 실패 · ④ 변화 없음(디스크에도 남지 않음)',
      prepare: async () => { const m = await fileDoc({}); return { func: 'fileUpload', staff: '3', id: String(m.document_id), body: UP(m, { name: '가짜.pdf', kind: 'bad' }) }; } }),
    filePs({ id: 'FILE-PS-03', label: '작성완료 문서에 올리기 거부', expect: '409 DOCUMENT_LOCKED(details code completed) · 문서 잠금 영향 0행 → 실패 사유 · 쓴 파일은 지움 · ④ 변화 없음',
      prepare: async () => { const m = await fileDoc({ state: 'completed', files: 1 }); return { func: 'fileUpload', staff: '3', id: String(m.document_id), body: UP(m) }; } }),
    filePs({ id: 'FILE-PS-04', label: '이전 파일 연결(SC-08)', expect: '201 · DOC-FLK 도식 일치(01~05) · ④ document_file +1(같은 file_id — 복사 없음), file 변화 없음, version +1',
      prepare: async () => {
        const from = await fileDoc({ files: 1 });
        const to = await fileDoc({});
        return { func: 'fileLink', staff: '3', id: String(to.document_id), body: J({ expected_version: to.version, link_file_id: from.files[0] }) };
      } }),
    filePs({ id: 'FILE-PS-05', label: '연결 끊기 — 마지막 연결이라 파일도 지움', expect: '200 · DOC-FDT-DEL 도식 일치(01~05, 05 = 커밋 뒤 파일 삭제 — 마지막 연결) · ④ document_file −1, file −1, version +1',
      prepare: async () => { const m = await fileDoc({ files: 1 }); return { func: 'fileDetach', staff: '3', id: String(m.document_id), query: `file=${m.files[0]}&expected_version=${m.version}` }; } }),
    filePs({ id: 'FILE-PS-06', label: '연결 끊기 — 다른 문서가 쓰는 파일은 남음', expect: '200 · DOC-FDT 01~04(파일 삭제 없음) · ④ 이 문서 document_file −1, file 그대로(다른 문서 연결 남음)',
      prepare: async () => {
        const from = await fileDoc({ files: 1 });
        const to = await fileDoc({});
        const linked = await quietPostAs(`documents/${to.document_id}/files`, { expected_version: to.version, link_file_id: from.files[0] }, 3);
        return { func: 'fileDetach', staff: '3', id: String(to.document_id), query: `file=${from.files[0]}&expected_version=${linked.document_version}` };
      } }),
    filePs({ id: 'FILE-PS-07', label: '이전 파일 검색', expect: '200 · DOC-FSR 도식 일치(01~02) · items에 방금 만든 D01 파일 2개(최신순), documents[0].target_summary = LOT … · 유자(목록과 같은 대상 표시) · DB 변화 없음',
      prepare: async () => { await fileDoc({ files: 2 }); return { func: 'fileSearch', staff: '3', query: 'type_code=D01&item=유자&supplier=콘솔준비&days=30' }; } }),
    filePs({ id: 'FILE-PS-08', label: '파일 없이 작성완료 거부(D02)', expect: '400 COMPLETION_INCOMPLETE(details path files, code files_required) · DOC-CMP-03 실패 → 롤백 · ④ 변화 없음',
      prepare: async () => { const m = await fileDoc({ type_code: 'D02' }); return { func: 'complete', staff: '3', id: String(m.document_id), body: J({ expected_version: m.version }) }; } }),

    p8({ id: 'P8-PS-01', label: '작성 안 함 일괄 정상(D10 3일)', expect: '200 · succeeded 3 · ③ DOC-SKP 도식 일치(머리 3 → 항목 3: skipped → 꼬리) · ④ 문서마다 status draft→skipped, skipped_at·by·reason(휴무), version +1, 값 그대로',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D10', days: [{ weekday: 1 }, { weekday: 2 }, { weekday: 3 }] });
        return { func: 'batchSkip', staff: '3', docId: ids(w.items), body: J({ items: items(w.items), reason: '휴무' }) };
      } }),
    p8({ id: 'P8-PS-02', label: '작성 안 함 일부 실패', expect: '200 · succeeded 1 · failed 2(INVALID_TRANSITION — 작성완료 D10, DOCUMENT_NOT_SKIPPABLE — D03) · ③ 항목 3(skipped 1 · 실패 2) · ④ 작성중 D10 1건만 skipped',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D10', days: [{ weekday: 1, state: 'completed' }, { weekday: 2 }] });
        const d03 = await one({ state: 'draft' });
        const list = [w.items[0], d03, w.items[1]];
        return { func: 'batchSkip', staff: '3', docId: ids(list), body: J({ items: items(list), reason: '작업 없음' }) };
      } }),
    p8({ id: 'P8-PS-03', label: '되돌리기', expect: '200 · DOC-USK 도식 일치(01~03) · ④ status skipped→draft, skipped_* 비움, version +1, 값 그대로',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D10', days: [{ weekday: 2, state: 'skipped' }] });
        return { func: 'unskip', staff: '3', id: String(w.items[0].document_id), body: J({ expected_version: w.items[0].version }) };
      } }),
    p8({ id: 'P8-PS-04', label: '작성 안 함 문서 작성완료 거부', expect: '409 INVALID_TRANSITION(details code skipped) · DOC-CMP-02 영향 0행 → 02a · ④ 변화 없음',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D12', days: [{ weekday: 1, state: 'skipped' }] });
        return { func: 'complete', staff: '3', id: String(w.items[0].document_id), body: J({ expected_version: w.items[0].version }) };
      } }),
    p8({ id: 'P8-PS-05', label: '주 묶음 조회(D10)', expect: '200 · REQ-PWB 도식 일치(01~06: DOC N10 → F26 → APR A10) · SQL 8개 이하 · days 5칸(목 null), 칸마다 check_counts·nonconforming(월 X 1 → true), summary documents 4, 결재중 1(내 칸 — staff 3) · DB 변화 없음',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D10', days: [{ weekday: 1, state: 'submitted', x: true }, { weekday: 2, state: 'skipped' }, { weekday: 3, state: 'filled' }, { weekday: 5 }] });
        return { func: 'periodicBundle', staff: '3', query: `type_code=D10&week_start=${w.week_start}` };
      } }),
    p8({ id: 'P8-PS-06', label: '문서 목록 주 묶음 줄', expect: '200 · DOC-LST 도식 일치(01~07) · 그 주 D10 줄 1개(kind bundle, bundle_unit week, work_date 월·period_end 금, count 5, status_counts 작성완료 2·작성 안 함 1·작성중 2, requirement periodic) · DB 변화 없음',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D10', days: [{ weekday: 1, state: 'completed' }, { weekday: 2, state: 'skipped' }, { weekday: 3, state: 'completed' }, { weekday: 4 }, { weekday: 5 }] });
        return { func: 'list', staff: '3', query: `from=${w.week_start}&to=${dayAfter(w.week_start, 6)}&template_id=${await typeTemplateId('D10')}` };
      } }),
    p8({ id: 'P8-PS-07', label: '최근 값(D12 공정명)', expect: '200 · DOC-RCV 도식 일치(01~02) · items에 "내포장"(최근 작업일 순, 서로 다른 값) · DB 변화 없음',
      prepare: async () => { await periodicWeek({ type_code: 'D12', days: [{ weekday: 1, state: 'filled' }] }); return { func: 'recentValues', staff: '3', query: 'type_code=D12&field=process_name' }; } }),
    p8({ id: 'P8-PS-08', label: '점검일 범위 밖 저장(D11)', expect: '400 VALIDATION_ERROR(details code date_window — 점검일은 그 주 월~일 안) · DOC-UPD-05 실패 → 롤백 · ④ 변화 없음',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D11', days: [{ weekday: 1 }] });
        const d = await quietGet(`documents/${w.items[0].document_id}`);
        const info = d.sections.find((x) => x.section_def === 'info');
        return { func: 'update', staff: '3', id: String(d.document_id), body: J({ expected_version: d.version, sections: { update: [{ section_id: info.section_id, values: { checked_on: dayAfter(w.week_start, 7) } }] } }) };
      } }),
    p8({ id: 'P8-PS-09', label: 'X 있는데 개선조치 없이 작성완료', expect: '400 COMPLETION_INCOMPLETE(details path deviations, code deviation_required) · DOC-CMP-03 실패 → 롤백 · ④ 변화 없음',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D12', days: [{ weekday: 1, state: 'filled' }] });
        const d = await quietGet(`documents/${w.items[0].document_id}`);
        const checks = d.sections.find((x) => x.section_def === 'checks');
        const changed = await quietPatchAs(`documents/${d.document_id}`, { expected_version: d.version, sections: { update: [{ section_id: checks.section_id, values: { pack_film: 'X' } }] } }, 3);
        return { func: 'complete', staff: '3', id: String(d.document_id), body: J({ expected_version: changed.version }) };
      } }),
    p8({ id: 'P8-PS-10', label: 'D10 일괄 상신(같은 주 3일)', expect: '200 · succeeded 3 · ③ WF-BSB 도식 일치(항목 3: submitted) · ④ 문서마다 completed→submitted, approval_request +1, approval +2(일괄 대상 D10 — HACCP_BATCH_TYPES 기본)',
      prepare: async () => {
        const w = await periodicWeek({ type_code: 'D10', days: [{ weekday: 1, state: 'completed' }, { weekday: 2, state: 'completed' }, { weekday: 3, state: 'completed' }] });
        return { func: 'batchSubmit', staff: '3', docId: ids(w.items), body: J({ items: items(w.items), slots: FIX_SLOTS }) };
      } }),
  );

  // ---------------------------------------------------------------- 프리셋 REQ-PS-14~16 · DOC-PS-30·31 (C4 S5 — p9-s1-screens 8장)
  // 날짜는 실행하는 날 기준(Asia/Seoul). 같은 날 다시 실행하면 이미 있는 문서는 existing — 기대 문구도 그 경우를 포함한다(D-146 Q2).
  const p9 = (preset) => ({ unit: 'P9', ...preset });
  const seoulToday = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  const isoDow = (day) => { const n = new Date(`${day}T00:00:00Z`).getUTCDay(); return n === 0 ? 7 : n; };
  // 오늘이 주말이면 지난 금요일(REQ-PS-14 — 평일 날짜)
  const lastWeekday = () => { const t = seoulToday(); const n = isoDow(t); return n > 5 ? dayAfter(t, 5 - n) : t; };
  const nextSaturday = () => { const t = seoulToday(); return dayAfter(t, 13 - isoDow(t)); };  // 다음 주 토요일
  async function quietPostAs(path, body, staff) {
    const r = await fetch(`/api/v1/${path}`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Staff-Id': String(staff) }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`사전 조건을 만들지 못했습니다: ${(data && (data.message || data.code)) || r.status}`);
    return data;
  }

  PRESETS.push(
    p9({ id: 'REQ-PS-14', label: '주기 문서 오늘 두 번', expect: '1회 200 · REQ-PRN 도식 일치(01~06, 05는 줄마다) · D10·D12 그날 문서와 D11 그 주 문서 3줄 — 없던 것은 created, 있던 것은 existing / 2회 200 · 3줄 모두 existing, ④ 문서 수 그대로(document·doc_section 변화 없음)',
      prepare: async () => {
        const day = lastWeekday();
        const body = J({ date_from: day, date_to: day });
        return { func: 'periodicRun', staff: '3', body,
          script: async (exec) => {
            await exec({ func: 'periodicRun', body, staff: '3' });
            await exec({ func: 'periodicRun', body, staff: '3' });
          } };
      } }),
    p9({ id: 'REQ-PS-15', label: '기간 보충과 주말', expect: '200 · REQ-PRN 도식 일치 · 14일: 토·일 D10·D12 줄은 skipped_rule(reason weekday), 규칙 시작일(periodic_rules.json start_date) 전 날은 skipped_rule(before_start), D11은 주마다 1줄(work_date 월요일) · ④ created 줄만큼 document +, 이미 있던 문서는 그대로',
      prepare: async () => {
        const end = seoulToday();
        return { func: 'periodicRun', staff: '3', body: J({ date_from: dayAfter(end, -13), date_to: end }) };
      } }),
    p9({ id: 'REQ-PS-16', label: '입력 거절(미래 · 32일 · 시작>끝)', expect: '3번 모두 400 VALIDATION_ERROR(details: date_to future / date_to max / date_from order) · REQ-PRN-02 실패, 03 이후 없음 · ④ 변화 없음',
      prepare: async () => {
        const t = seoulToday();
        const cases = [{ date_from: t, date_to: dayAfter(t, 1) }, { date_from: dayAfter(t, -31), date_to: t }, { date_from: t, date_to: dayAfter(t, -1) }];
        return { func: 'periodicRun', staff: '3', body: J(cases[0]),
          script: async (exec) => { for (const c of cases) await exec({ func: 'periodicRun', body: J(c), staff: '3' }); } };
      } }),
    p9({ id: 'DOC-PS-30', label: '새 문서 → 이미 있는 날', expect: '200 · REQ-POD 도식 일치(01~04) · result existing, 준비에서 만든(또는 있던) 그날 D10과 같은 document_id · ④ 변화 없음',
      prepare: async () => {
        const day = lastWeekday();
        const made = await quietPostAs('periodic-runs', { date_from: day, date_to: day, type_codes: ['D10'] }, 3);
        const line = made.lines[0];
        prepared.push({ lot_number: '-', document_id: line.document_id, status: `D10 ${day} ${line.status} — ${line.result}` });
        return { func: 'periodicOpen', staff: '3', body: J({ type_code: 'D10', date: day }) };
      } }),
    p9({ id: 'DOC-PS-31', label: '새 문서 → 미래·주말(다음 주 토요일 D12) → 삭제', expect: '1번째 200(created) → 2번째 삭제 204 · 1번째 REQ-POD 도식 일치, record_key D12|day:<토요일>, ④ document +1 · 2번째 DOC-DEL 도식 일치, ④ deleted_at·by 채워지고 record_key 비움(주기 문서는 작성중·상신 전이면 삭제 — D-149, ISS-028) → 다시 실행해도 다시 created',
      prepare: async () => {
        const body = J({ type_code: 'D12', date: nextSaturday() });
        return { func: 'periodicOpen', staff: '3', body,
          script: async (exec) => {
            const first = await exec({ func: 'periodicOpen', body, staff: '3' });
            const id = first.record.ok ? String(first.record.data.document_id) : '0';
            await exec({ func: 'delete', id, staff: '3' });
          } };
      } }),
  );

  // ---------------------------------------------------------------- 프리셋 DOC-PS-32~34 · WF-PS-34~36 (C5 S5 — p10-s1-screens 7장)
  // 작성 필요는 실행하는 날 기준(Asia/Seoul). 상신 취소는 불러올 때 새 D03을 만든다(P6 픽스처 — 결재선 staff 3·1, 상신자 staff 3).
  const p10 = (preset) => ({ unit: 'P10', ...preset });
  const todoRows = (t) => t.groups.flatMap((g) => [...g.rows, ...g.past.rows]);
  async function quietTodo() {
    const t = await quietGetAs(`todo?date=${seoulToday()}`, 3);
    if (!t) throw new Error('작성 필요 목록을 읽지 못했습니다(현재 사용자 staff 3 필요).');
    return t;
  }
  async function quietDelete(path, staff) {
    const r = await fetch(`/api/v1/${path}`, { method: 'DELETE', headers: { Accept: 'application/json', 'X-Staff-Id': String(staff) } });
    if (!r.ok) throw new Error(`사전 조건을 만들지 못했습니다: 삭제 ${r.status}`);
  }

  PRESETS.push(
    p10({ id: 'DOC-PS-32', label: '작성 필요 기본', expect: '200 · REQ-TDO 도식 일치(01~06, 04 안쪽 DOC-RQD) · groups 순서 오늘·주간·월간·연간·수시(월간·연간·수시 has_forms false) · 준비에서 만든 그날 D10·D12는 작성 필요 상태면 오늘 칸, D11은 주간 칸 · 시작일(10-12) 이후 빠진 평일은 지난 미완료의 "문서 없음" · ④ 변화 없음',
      prepare: async () => {
        const day = lastWeekday();
        const made = await quietPostAs('periodic-runs', { date_from: day, date_to: day }, 3);
        made.lines.forEach((line) => prepared.push({ lot_number: '-', document_id: line.document_id, status: `${line.type_code} ${line.work_date} ${line.status} — ${line.result}` }));
        return { func: 'todo', staff: '3', query: `date=${seoulToday()}` };
      } }),
    p10({ id: 'DOC-PS-33', label: '문서 없음 → 만들기', expect: '1번째 200(REQ-POD created) → 2번째 200(REQ-TDO) · 준비에서 고른 "문서 없음" 줄(없으면 작성중 주기 문서를 지워 만듦 — D-149)이 다시 조회하면 작성중 문서 줄 · ④(그 날짜) document +1',
      prepare: async () => {
        let t = await quietTodo();
        let line = todoRows(t).find((r) => r.kind === 'missing');
        if (!line) {
          const draft = todoRows(t).find((r) => r.kind === 'document' && r.requirement === 'periodic' && r.status === 'draft');
          if (!draft) throw new Error('문서 없음 줄도, 지울 수 있는 작성중 주기 문서도 없습니다.');
          await quietDelete(`documents/${draft.document_id}`, 3);
          prepared.push({ lot_number: '-', document_id: draft.document_id, status: `${draft.type_code} ${draft.work_date} 작성중 → 삭제(문서 없음 만들기)` });
          t = await quietTodo();
          line = todoRows(t).find((r) => r.kind === 'missing' && r.type_code === draft.type_code && r.work_date === draft.work_date);
        }
        const body = J({ type_code: line.type_code, date: line.work_date });
        const query = `date=${seoulToday()}`;
        return { func: 'periodicOpen', staff: '3', body,
          script: async (exec) => {
            await exec({ func: 'periodicOpen', body, staff: '3' });
            await exec({ func: 'todo', query, staff: '3' });
          } };
      } }),
    p10({ id: 'DOC-PS-34', label: '작성 안 함은 빠짐', expect: '1번째 200(DOC-SKP) → 2번째 200(REQ-TDO) · 준비한 작성중 D10이 작성 안 함 → 그 날 D10 줄 없음(문서 없음도 아님) · ④ document skipped',
      prepare: async () => {
        const t = await quietTodo();
        let row = todoRows(t).find((r) => r.kind === 'document' && r.type_code === 'D10' && r.status === 'draft');
        if (!row) {
          const missing = todoRows(t).find((r) => r.kind === 'missing' && r.type_code === 'D10');
          if (!missing) throw new Error('작성중 D10도, D10 문서 없음 줄도 없습니다.');
          const made = await quietPostAs('periodic-documents', { type_code: 'D10', date: missing.work_date }, 3);
          row = { document_id: made.document_id, version: made.version, work_date: made.work_date };
        }
        prepared.push({ lot_number: '-', document_id: row.document_id, status: `D10 ${row.work_date} 작성중` });
        const skip = { func: 'batchSkip', staff: '3', docId: String(row.document_id), body: J({ items: [{ document_id: row.document_id, expected_version: row.version }], reason: '휴무' }) };
        const query = `date=${seoulToday()}`;
        return { ...skip,
          script: async (exec) => {
            await exec(skip);
            await exec({ func: 'todo', query, staff: '3' });
          } };
      } }),
    p10({ id: 'WF-PS-34', label: '상신 취소(받은 승인 1)', expect: '200 · WF-CAN 도식 일치(01~05, 안쪽 APR-CAN-00~03 · DOC-ULK-00~02) · approval_request in_progress→cancelled·closed_at, 승인 칸(staff 3) 그대로·대기 칸(staff 1) skipped, document submitted→completed·version+1 · 수불 신호 없음(DOC-SIG 없음)',
      prepare: async () => {
        const { d } = await fixtureDoc({ state: 'submitted_partial' });
        const req = await latestRequest(d.document_id);
        return { func: 'cancelSubmission', staff: '3', id: String(req.request_id), docId: String(d.document_id) };
      } }),
    p10({ id: 'WF-PS-35', label: '상신 취소 거절(다른 사용자 · 결재 완료)', expect: '1번째 403 NOT_REQUESTER → 2번째 409 REQUEST_CLOSED · 둘 다 APR-CAN-01 0행 → 01a 실패 사유 · 롤백으로 ④ 변화 없음',
      prepare: async () => {
        const open = (await fixtureDoc({ state: 'submitted' })).d;
        const done = (await fixtureDoc({ state: 'approved' })).d;
        const a = await latestRequest(open.document_id);
        const b = await latestRequest(done.document_id);
        const first = { func: 'cancelSubmission', staff: '2', id: String(a.request_id), docId: String(open.document_id) };
        return { ...first,
          script: async (exec) => {
            await exec(first);
            await exec({ func: 'cancelSubmission', staff: '3', id: String(b.request_id), docId: String(done.document_id) });
          } };
      } }),
    p10({ id: 'WF-PS-36', label: '취소 뒤 재상신', expect: '1번째 200(WF-CAN) → 2번째 201(WF-SUB) · 새 회차 attempt+1 · 이전 회차 cancelled 그대로 · document completed→submitted',
      prepare: async () => {
        const { d } = await fixtureDoc({ state: 'submitted' });
        const req = await latestRequest(d.document_id);
        const cancel = { func: 'cancelSubmission', staff: '3', id: String(req.request_id), docId: String(d.document_id) };
        return { ...cancel,
          script: async (exec) => {
            await exec(cancel);
            await exec({ func: 'submit', staff: '3', id: String(d.document_id), body: J({ expected_version: d.version + 1, slots: FIX_SLOTS }) });
          } };
      } }),
  );

  // ---------------------------------------------------------------- 프리셋 DSH-PS-01~08 (P11 S5 — p11-s1-screens 6장)
  // 사전 조건은 불러올 때 개발 API(fixtures/ccp — 새 배치 → REQ-F02 → 행·개선조치·확인)로 만든다(ISS-019). 기준일 = 실행하는 날(Asia/Seoul)
  const p11 = (preset) => ({ unit: 'P11', ...preset });
  async function ccpFixture(body) {
    const made = await devPost('/api/dev/fixtures/ccp', body);
    made.batches.forEach((b) => Object.entries(b.documents).forEach(([proc, id]) => prepared.push({ lot_number: '-', document_id: id, status: `배치 ${b.label} CCP-${proc}` })));
    return made;
  }
  // fixtures/ccp 응답의 개선조치 id → 그 문서의 개선조치(version·확인 기록)
  async function ccpDeviation(made, process, deviationId, batch = 1) {
    const documentId = made.batches[batch - 1].documents[process];
    const d = await quietGet(`documents/${documentId}`);
    const x = d && d.deviations.find((y) => y.deviation_id === deviationId);
    if (!x) throw new Error(`개선조치 #${deviationId}를 찾지 못했습니다.`);
    return { documentId, deviation: x };
  }
  const BAD_2B = { process: '2B', values: { temp_c: 73.5 } };

  PRESETS.push(
    p11({ id: 'DSH-PS-01', label: '대시보드 기본', expect: '200 · REQ-CCP 도식 일치(01~05, 04 안쪽 DOC-MSM-01~05) · SQL 6개 이하(MSM) · cards 3개(CCP-1P·2B·3P 순서) · 준비한 배치 2개: 1P·2B는 측정 행 1개씩(최근 측정 값), 3P는 행 없음(no_rows · "측정 없음") · 작성중이라 todo · ④ 변화 없음',
      prepare: async () => {
        await ccpFixture({ rows: [{ process: '1P' }, { process: '2B' }] });
        return { func: 'ccpDashboard', staff: '3', query: `date=${seoulToday()}` };
      } }),
    p11({ id: 'DSH-PS-02', label: '이탈 + 개선조치 없음', expect: '200 · REQ-CCP 도식 일치 · deviations에 준비한 2B 행(건조온도 73.5, reasons temp_c expect min 68·max 72) 1줄, deviation.state none("개선조치 없음") · CCP-2B 카드 counts.deviation_rows ≥ 1 · ④ 변화 없음',
      prepare: async () => {
        await ccpFixture({ rows: [BAD_2B] });
        return { func: 'ccpDashboard', staff: '3', query: `date=${seoulToday()}` };
      } }),
    p11({ id: 'DSH-PS-03', label: 'CCP 개선조치 즉시 노출', expect: '200 · DOC-PND 도식 일치(00~05) · 준비한 2B 개선조치(확인자 staff 3)가 rows에 있음 — 문서는 작성중(CCP check_visibility immediate) · can_check true · counts.mine ≥ 1 · ④ 변화 없음',
      prepare: async () => {
        await ccpFixture({ rows: [BAD_2B], deviations: [{ process: '2B', row: 1, checker_ids: [3] }] });
        return { func: 'deviationsPending', staff: '3', query: `date=${seoulToday()}` };
      } }),
    p11({ id: 'DSH-PS-04', label: '일반 양식은 작성완료 뒤', expect: '1번째 200(DOC-PND) → 2번째 200(DOC-CMP) → 3번째 200(DOC-PND) · 준비한 D03(작성중, 개선조치 확인자 staff 3)은 1번째 rows에 없고, 작성완료 뒤 3번째 rows에 있음(after_complete) · ④ document draft→completed',
      prepare: async () => {
        const { d } = await fixtureDoc({ state: 'draft', inspector: 4, received_date: seoulToday() });
        await quietPostAs(`documents/${d.document_id}/deviations`, { description: '포장 파손(콘솔 준비)', action_result: '반품 처리', checker_ids: [3] }, 3);
        const fresh = await quietGet(`documents/${d.document_id}`);
        const query = `date=${seoulToday()}`;
        const complete = { func: 'complete', staff: '3', id: String(d.document_id), body: J({ expected_version: fresh.version }) };
        return { func: 'deviationsPending', staff: '3', query, docId: String(d.document_id),
          script: async (exec) => {
            await exec({ func: 'deviationsPending', staff: '3', query });
            await exec(complete);
            await exec({ func: 'deviationsPending', staff: '3', query });
          } };
      } }),
    p11({ id: 'DSH-PS-05', label: '확인 성공', expect: '200 · DOC-DVK 도식 일치(00~02) · 02 조건부 UPDATE 영향 1행 · ④ deviation_action checked_by 3·checked_at 채움·version+1, updated_by·updated_at 그대로, document version 그대로 · 대시보드를 다시 보면 확인 대기에서 빠지고 이탈 줄 "확인됨"',
      prepare: async () => {
        const made = await ccpFixture({ rows: [BAD_2B], deviations: [{ process: '2B', row: 1, checker_ids: [3] }] });
        const { documentId, deviation } = await ccpDeviation(made, '2B', made.deviations[0]);
        return { func: 'deviationCheck', staff: '3', id: String(deviation.deviation_id), docId: String(documentId), body: J({ expected_version: deviation.version }) };
      } }),
    p11({ id: 'DSH-PS-06', label: '확인 거절(확인자 아님 · 이미 확인됨)', expect: '1번째 403 NOT_CHECKER(staff 4) → 2번째 409 ALREADY_CHECKED(details checked_by 3·checked_at) · 둘 다 DOC-DVK-02 영향 0행 → 02a 실패 사유 · ④ 변화 없음',
      prepare: async () => {
        const made = await ccpFixture({ rows: [BAD_2B, { process: '2B' }], deviations: [{ process: '2B', row: 1, checker_ids: [3] }, { process: '2B', row: 2, checker_ids: [3], checked_by: 3 }] });
        const open = await ccpDeviation(made, '2B', made.deviations[0]);
        const done = await ccpDeviation(made, '2B', made.deviations[1]);
        const first = { func: 'deviationCheck', staff: '4', id: String(open.deviation.deviation_id), docId: String(open.documentId), body: J({ expected_version: open.deviation.version }) };
        return { ...first,
          script: async (exec) => {
            await exec(first);
            await exec({ func: 'deviationCheck', staff: '3', id: String(done.deviation.deviation_id), docId: String(done.documentId), body: J({ expected_version: done.deviation.version }) });
          } };
      } }),
    p11({ id: 'DSH-PS-07', label: '확인 뒤 수정', expect: '200 · DOC-DVU 도식 일치 · ④ deviation_action action_result 바뀜·version+1·updated_* 바뀜, checked_by 3·checked_at 그대로(확인 기록 남음)',
      prepare: async () => {
        const made = await ccpFixture({ rows: [BAD_2B], deviations: [{ process: '2B', row: 1, checker_ids: [3], checked_by: 3 }] });
        const { documentId, deviation } = await ccpDeviation(made, '2B', made.deviations[0]);
        return { func: 'devUpdate', staff: '3', id: String(deviation.deviation_id), docId: String(documentId), body: J({ expected_version: deviation.version, action_result: '재측정 70.2℃, 적합(확인 뒤 수정)' }) };
      } }),
    p11({ id: 'DSH-PS-08', label: '확인자 없음', expect: '200 · DOC-PND 도식 일치 · 준비한 개선조치(확인자 비움)는 rows에 없고 no_checker.rows에 있음, no_checker.count ≥ 1 · 배지 합계(my_total)에 들지 않음 · ④ 변화 없음',
      prepare: async () => {
        await ccpFixture({ rows: [BAD_2B], deviations: [{ process: '2B', row: 1, checker_ids: [] }] });
        return { func: 'deviationsPending', staff: '3', query: `date=${seoulToday()}` };
      } }),
  );

  function preparedText(m) {
    if (m.document_id === null) return `새 LOT ${esc(m.lot_number)} · 문서 없음(작성 요구 안 부름)`;
    if (m.lot_number === '-') return `문서 #${esc(m.document_id)}(${esc(m.status)})`;
    if (m.kind) return `새 LOT ${esc(m.lot_number)} · ${esc(m.kind)} 문서 #${esc(m.document_id)}(${esc(m.status)})`;
    return `새 LOT ${esc(m.lot_number)} · D03 문서 #${esc(m.document_id)}(${esc(m.status)}${m.correction ? ' · 정정' : ''})`;
  }

  async function loadPreset() {
    const p = PRESETS.find((x) => x.id === $('#dcPreset').value);
    if (!p) { state.preset = null; $('#dcPresetDesc').textContent = '기능을 고르고 실행하세요. 프리셋을 불러오면 입력이 채워집니다.'; return; }
    $('#dcPresetDesc').textContent = `${p.id} 준비 중…`;
    prepared = [];
    p7DayCache = null;
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
      $('#dcPresetDesc').innerHTML = `<b>${esc(p.id)} ${esc(p.label)}</b><br>기대: ${esc(p.expect)}${spec.script ? '<br><span class="te-hint">여러 호출을 순서/동시에 실행하는 프리셋입니다. [실행]을 누르세요.</span>' : ''}${prepared.length ? `<br><span class="te-hint" id="dcPrepared">준비(불러오기 때 만듦): ${prepared.map(preparedText).join(', ')}</span>` : ''}`;
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
    $('#dcPreset').innerHTML = '<option value="">(직접 입력)</option>' + group('DOC', 'DOC 문서 도메인 (P1)') + group('WF', 'WF 결재 워크플로우 (P3)') + group('P4', 'DOC 확장 (P4·P6a)') + group('REQ', 'REQ 작성 요구 (P5)') + group('P6', '정정·판정 연동 (P6)') + group('P7', '일괄 결재·육안검사 묶음 (P7)') + group('FILE', '파일 업로드 (스프린트 3)') + group('P8', '점검표·작성 안 함 (P8)') + group('P9', '주기형 작성 요구 (P9)') + group('P10', '문서함·결재함 (P10)') + group('P11', 'CCP 대시보드 (P11)');
    $('#dcFunc').addEventListener('change', () => { state.preset = null; toggleInputs(); });
    ['#dcId', '#dcQuery', '#dcBody', '#dcDocId'].forEach((sel) => $(sel).addEventListener('input', () => { if (state.preset && state.preset.script) state.preset = null; }));
    $('#dcLoadPreset').addEventListener('click', loadPreset);
    $('#dcRun').addEventListener('click', run);
    $('#dcOnlyChanged').addEventListener('change', () => { if (!state.active) return; if (state.active.entries) showTotal(state.active); else renderDb(state.active); });
    const flows = await devGet('/api/dev/flows');
    state.flows = flows ? flows.flows : {};
    state.batch = (flows && flows.batch) || {};
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

  window.DevConsole = { state, run, execute, PRESETS, compare };
  init();
})();
