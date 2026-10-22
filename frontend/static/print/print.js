// P12 인쇄용 페이지 (PRT-SC-01~03) — GET /api/v1/print/sheet 를 종이 칸 배치로 그린다.
// ?document_id= (CCP 단건, D03 문서면 그 입고일 장, D10 문서면 그 주) · ?kind=receiving&type=D03&date= (D03 입고일 묶음)
// · ?kind=weekly&type=D10|D12&date= (D10·D12 주 — 그 주 아무 날) · ?kind=monthly&type=D11&month=YYYY-MM (D11 월)
// 정책: dev-notes/print/p12-ccp-policy.md (DP-01~03), p12-d03-policy.md (DP-10·11). 출력 기록 없음, 사용자 헤더 없이 읽기만.
(function () {
  'use strict';

  const MIN_ROWS = 6; // 종이 측정 줄(T5 a) — 적으면 빈 줄, 넘치면 다음 쪽(표 머리 반복)
  const MIN_SUMMARY = 5; // 3P 제품 통과 줄
  const MIN_DEVIATIONS = 2; // 개선조치 없으면 빈 줄 2개(DP-01 Q2 a)

  const $ = (sel) => document.querySelector(sel);
  const esc = (v) => String(v === undefined || v === null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const pad = (list, n) => list.concat(Array(Math.max(0, n - list.length)).fill(null));
  // 종이의 "왼쪽 합친 칸"(품명·중량). rowspan은 쪽을 못 나눠 표가 통째로 다음 쪽으로 밀리므로
  // 행마다 칸을 두고 첫 행에만 내용, 사이 가로선은 지운다(매트릭스 1P-05).
  // 내용은 첫 행 칸 위에 겹쳐 그려(position:absolute) 행 높이를 바꾸지 않는다(행 높이 고르게 — 매트릭스 R1)
  const merged = (i, count, html) => `<td class="merge${i === 0 ? ' first' : ''}${i === count - 1 ? ' last' : ''}">${i === 0 ? `<div class="merge-body">${html}</div>` : ''}</td>`;
  // 서명 칸: 한 줄 고정, 긴 이름은 글씨만 작게(R3)
  const sign = (id) => {
    const name = who(id);
    const size = name.length > 8 ? 'tighter' : name.length > 6 ? 'tight' : '';
    return name ? `<span class="${size}">${esc(name)}</span>` : '';
  };

  let people = {};
  const who = (id) => (id === null || id === undefined ? '' : people[String(id)] || `staff ${id}`);
  const mmdd = (iso) => (iso ? `${iso.slice(5, 7)}-${iso.slice(8, 10)}` : '');
  const dateKo = (iso) => (iso ? `${iso.slice(0, 4)} 년 ${Number(iso.slice(5, 7))} 월 ${Number(iso.slice(8, 10))} 일` : '20   년    월    일');
  const monthDayKo = (iso) => `${Number(iso.slice(5, 7))} 월 ${Number(iso.slice(8, 10))} 일`;
  // 측정 일시: 작업일과 같은 날이면 HH:MM, 다르면 MM-DD HH:MM
  const clock = (dt, workDate) => {
    if (!dt) return '';
    const hm = dt.slice(11, 16);
    return dt.slice(0, 10) === workDate ? hm : `${mmdd(dt)} ${hm}`;
  };
  const ox = (value, options) => options.map((o) => `<span class="ox${value === o ? ' on' : ''}">${esc(o)}</span>`).join(' ');
  const verdict = (v) => `<span class="chk${v === '부적합' ? ' bad' : ''}">적합${v === '적합' ? '☑' : '☐'}/부적합${v === '부적합' ? '☑' : '☐'}</span>`;
  const minutesHm = (m) => (m === null || m === undefined || m === '' ? '' : `${Math.floor(Number(m) / 60)}시간 ${Number(m) % 60}분`);
  const num = (v) => (v === null || v === undefined || v === '' ? '' : Number(v).toLocaleString('ko-KR'));

  function message(text, detail) {
    $('#prtRoot').innerHTML = `<div class="prt-msg">${esc(text)}${detail ? `<small>${esc(detail)}</small>` : ''}</div>`;
    $('#prtPrint').disabled = true;
  }

  // ---------------------------------------------------------------- 머리(제목·결재 칸)·작성일자 줄
  function headHtml(data) {
    const boxes = data.boxes || [];
    const doc = data.document;
    const until = doc.measured_until ? ` ~ ${monthDayKo(doc.measured_until)}` : '';
    const batch = doc.batch_label ? ` <span class="sm muted">(배치 ${esc(doc.batch_label)})</span>` : '';
    return `
      <table class="prt prt-head">
        <colgroup><col><col style="width:9mm">${boxes.map(() => '<col style="width:24mm">').join('')}</colgroup>
        <tr>
          <td class="title" rowspan="2"><div class="t1">${esc(data.title)}</div><div class="t2">( ${esc(data.subtitle)} )</div></td>
          <th class="vert" rowspan="2">기록<br>확인</th>
          ${boxes.map((b) => `<th class="box">${esc(b.label)}</th>`).join('')}
        </tr>
        <tr>${boxes.map((b) => `<td class="sign">${b.staff_id ? `<div class="who">${esc(who(b.staff_id))}</div>` : ''}</td>`).join('')}</tr>
      </table>
      <table class="prt">
        <colgroup><col style="width:24mm"><col><col style="width:22mm"><col style="width:40mm"></colgroup>
        <tr><th>작성일자</th><td>${dateKo(doc.work_date)}${until}${batch}</td>
          <th>점검자</th><td>${esc(who(doc.info.inspector))}</td></tr>
      </table>`;
  }

  // ---------------------------------------------------------------- 고정 안내
  const group = (data, title) => (data.guide || []).find((g) => g.title === title) || { rows: [] };

  function guideRowsHtml(rows) {
    return rows.length ? `
      <table class="prt">
        <colgroup><col style="width:24mm"><col></colgroup>
        ${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td class="pre">${esc(v)}</td></tr>`).join('')}
      </table>` : '';
  }

  // CCP-3P v2(캔디류): 한계기준 유형별 표 · 점검주기 · 방법 ①~⑤ 표
  function guide3pHtml(data) {
    const rows = group(data, '관리기준').rows;
    const limits = rows.filter(([k]) => /^한계기준\(/.test(k)).map(([k, v]) => {
      const type = k.replace(/^한계기준\((.*)\)$/, '$1');
      const parts = v.split(/,\s*/);
      const fe = (parts.find((p) => /^Fe/.test(p)) || '').replace(/^Fe\(철\)\s*/, '');
      const sus = (parts.find((p) => /^SUS/.test(p)) || '').replace(/^SUS\(스테인리스\)\s*/, '');
      return { type, fe, sus };
    });
    const cycle = rows.find(([k]) => k === '점검주기');
    const steps = rows.filter(([k]) => /^[①②③④⑤]/.test(k));
    const note = rows.find(([k]) => k === '※');
    return `
      <table class="prt">
        <colgroup><col style="width:24mm"><col style="width:26mm"><col><col></colgroup>
        <tr><th rowspan="${limits.length + 1}">한계기준</th><th>유형</th><th>Fe (철)</th><th>SUS (스테인리스)</th></tr>
        ${limits.map((x) => `<tr><td>${esc(x.type)}</td><td>${esc(x.fe)}</td><td>${esc(x.sus)}</td></tr>`).join('')}
        ${cycle ? `<tr><th>점검주기</th><td colspan="3">${esc(cycle[1])}</td></tr>` : ''}
      </table>
      <table class="prt guide3p">
        <colgroup><col style="width:24mm"><col style="width:58mm"><col></colgroup>
        ${steps.map(([k, v], i) => `<tr>${i === 0 ? `<th rowspan="${steps.length + (note ? 1 : 0)}">방법</th>` : ''}<td class="l">${esc(k)}</td><td class="l">${esc(v)}</td></tr>`).join('')}
        ${note ? `<tr><td class="l" colspan="2">※ ${esc(note[1])}</td></tr>` : ''}
      </table>`;
  }

  // 개선조치방법: 1P·2B는 종이 문구(줄바꿈 그대로), 3P v2는 항목별 → "○ 항목" + "- 문장"
  function actionHtml(data, is3p) {
    const rows = group(data, '개선조치방법').rows;
    if (!rows.length) return '';
    const text = is3p
      ? rows.map(([k, v]) => (k === '☆' ? `☆ ${v}` : `○ ${k}\n${v.split(/(?<=다\.)\s+/).map((s) => `- ${s}`).join('\n')}`)).join('\n')
      : rows.map(([, v]) => v).join('\n');
    return `<table class="prt"><colgroup><col style="width:24mm"><col></colgroup>
      <tr><th>개선조치방법</th><td class="pre sm">${esc(text)}</td></tr></table>`;
  }

  // ---------------------------------------------------------------- 측정 표
  function rows1pHtml(doc) {
    const rows = pad(doc.sections.rounds || [], MIN_ROWS);
    const firstPhase = '작업시작 전';
    const lastPhase = '작업종료 후';
    const left = `<div class="bold">${esc(doc.info.item_name)}</div><br>중량<br>( ${esc(num(doc.info.batch_qty_kg))} kg)`;
    const body = rows.map((r, i) => {
      const v = r ? r.values : {};
      // 다른 날 행(MM-DD HH:MM)은 칸이 좁아 구분을 줄여 씀: 작업시작 전 → 시작, 작업종료 후 → 종료
      const otherDay = !!v.measured_at && v.measured_at.slice(0, 10) !== doc.work_date;
      const label = otherDay ? { [firstPhase]: '시작', [lastPhase]: '종료' }[v.phase] : v.phase;
      const phase = v.phase === firstPhase || v.phase === lastPhase ? `<span class="sm">${esc(label)}</span> ` : '';
      return `<tr>${merged(i, rows.length, left)}
        <td>${r ? `${phase}${esc(clock(v.measured_at, doc.work_date))}` : ':'}</td>
        <td>${esc(num(v.gauss))}</td>
        <td>${ox(v.rod_cleaned, ['O', 'X'])}</td>
        <td>${verdict(v.verdict)}</td>
        <td class="signer">${r ? sign(r.recorded_by) : ''}</td>
        <td class="l sm">${esc(v.note)}</td></tr>`;
    }).join('');
    return `<table class="prt rows">
      <colgroup><col style="width:22mm"><col style="width:30mm"><col><col style="width:22mm"><col style="width:28mm"><col style="width:25mm"><col style="width:26mm"></colgroup>
      <thead><tr><th>품명</th><th>측정시간</th><th>자력(가우스)</th><th>자석봉 청소</th><th>판정</th><th>작업자서명</th><th>비고</th></tr></thead>
      <tbody>${body}</tbody></table>`;
  }

  function rows2bHtml(doc) {
    const rows = pad(doc.sections.rounds || [], MIN_ROWS);
    const left = `<div class="bold">${esc(doc.info.item_name)}</div>`;
    const body = rows.map((r, i) => {
      const v = r ? r.values : {};
      return `<tr>${merged(i, rows.length, left)}
        <td>${r ? esc(clock(v.measured_at, doc.work_date)) : ':'}</td>
        <td>${r ? `${esc(v.temp_c)} ℃` : '℃'}</td>
        <td>${r ? esc(minutesHm(v.dry_minutes)) : '시간 &nbsp; 분'}</td>
        <td>${verdict(v.verdict)}</td>
        <td class="signer">${r ? sign(r.recorded_by) : ''}</td>
        <td class="l sm">${esc(v.note)}</td></tr>`;
    }).join('');
    return `<table class="prt rows">
      <colgroup><col style="width:22mm"><col style="width:30mm"><col><col style="width:24mm"><col style="width:28mm"><col style="width:25mm"><col style="width:26mm"></colgroup>
      <thead><tr><th>품명</th><th>측정시간</th><th>건조온도<br>(판넬온도)</th><th>건조시간</th><th>판정</th><th>서명</th><th>비고</th></tr></thead>
      <tbody>${body}</tbody></table>`;
  }

  function rows3pHtml(data) {
    const doc = data.document;
    const rows = pad(doc.sections.checks || [], MIN_ROWS);
    const judge = (group(data, '관리기준').rows.find(([k]) => k === '판정') || [, '검출 ○ / 불검출 X'])[1];
    const keys = ['fe_only', 'sts_only', 'product_only', 'product_fe', 'product_sus'];
    const labels = Object.fromEntries((doc.fields.checks || []).map((f) => [f.key, f.label]));
    const head = keys.map((k) => `<th class="sm">${esc((labels[k] || k).replace(/ 통과$/, ''))}<br>통과</th>`).join('');
    const body = rows.map((r) => {
      const v = r ? r.values : {};
      return `<tr>
        <td>${r ? esc(doc.info.item_name) : ''}</td>
        <td>${r ? `<span class="sm">(${esc(v.phase)})</span> ${esc(clock(v.passed_at, doc.work_date))}` : ':'}</td>
        ${keys.map((k) => `<td>${esc(v[k])}</td>`).join('')}
        <td class="${v.verdict === '부적합' ? 'bad' : ''}">${esc(v.verdict)}</td>
        <td class="signer">${r ? sign(r.recorded_by) : ''}</td></tr>`;
    }).join('');
    const sums = pad(doc.sections.summary || [], MIN_SUMMARY);
    const sumBody = sums.map((r) => {
      const v = r ? r.values : {};
      return `<tr><td>${esc(v.item_name)}</td><td>${esc(num(v.passed_qty))}</td><td class="${Number(v.detected_qty) > 0 ? 'bad' : ''}">${esc(num(v.detected_qty))}</td><td class="l sm">${esc(v.note)}</td></tr>`;
    }).join('');
    return `<table class="prt rows">
      <colgroup><col style="width:22mm"><col style="width:30mm"><col><col><col><col><col><col style="width:16mm"><col style="width:25mm"></colgroup>
      <thead>
        <tr><th colspan="9" class="cap">금속검출기 감도 모니터링(판정 - ${esc(judge.replace('○', 'O'))})</th></tr>
        <tr><th>품 명</th><th>통과시간</th>${head}<th>판 정</th><th>서 명</th></tr>
      </thead>
      <tbody>${body}</tbody></table>
      <table class="prt sum">
        <colgroup><col style="width:44mm"><col style="width:30mm"><col style="width:22mm"><col></colgroup>
        <thead><tr><th colspan="4" class="cap">금속검출기 제품 통과</th></tr>
          <tr><th>품명</th><th>통과량</th><th>검출량</th><th>특이사항</th></tr></thead>
        <tbody>${sumBody}</tbody></table>`;
  }

  // ---------------------------------------------------------------- 이탈·개선조치 표
  function deviationsHtml(doc) {
    const list = doc.deviations || [];
    const rows = list.length ? list : pad([], MIN_DEVIATIONS);
    return `<table class="prt devs">
      <colgroup><col style="width:52mm"><col><col style="width:24mm"><col style="width:26mm"></colgroup>
      <thead><tr><th>한계기준 이탈내용</th><th>개선조치 및 결과</th><th>조 치 자</th><th>확 인</th></tr></thead>
      <tbody>${rows.map((d) => (d ? `<tr><td class="l">${esc(d.description)}</td><td class="l">${esc(d.action_result)}</td>
        <td>${esc(who(d.actor_id))}</td><td>${d.checked_by ? esc(who(d.checked_by)) : ''}</td></tr>`
        : '<tr><td></td><td></td><td></td><td></td></tr>')).join('')}</tbody></table>`;
  }

  // ---------------------------------------------------------------- D03 입고일 묶음(가로, p12-d03-policy.md · DP-11)
  // 종이(표준 PDF 6쪽): 머리 = 제목만(U1) · 9줄/쪽(넘치면 다음 쪽, 머리·표 머리 반복) · 체크칸은 두 보기 다 찍고
  // 고른 쪽만 ■(U3, 부적합은 굵게) · LOT 번호 안 찍음(U5) · 결재 칸 = 이름만(U8 b) ·
  // 항목·관리기준 표와 이탈 표는 마지막 쪽에만(U7) · 이탈 표 일자 MM/DD, 이탈사항 앞 [품명](U6)
  const D03_LINES = 9;
  const D03_KINDS = [['원료', '원 료'], ['부자재', '부자재']];
  const D03_GOOD = [['양호', '양호'], ['불량', '불량']];
  const D03_COA = [['유', '유'], ['무', '무']];
  // 검사 항목 열: 필드 키 · 종이 표 머리
  const D03_CHECKS = [
    ['appearance', '성상 및<br>이물혼입'],
    ['packaging', '외/내포장 오염<br>및 파손없음'],
    ['labeling', '표시사항<br>기재여부'],
    ['verdict', '최종판정'],
  ];
  const slash = (iso) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}` : '');
  // 한 칸 두 보기(종이 "양호□ / 불량□"): 고른 쪽만 ■
  const picks = (value, options, boldValue) => options.map(([v, label]) => {
    const on = value !== null && value !== undefined && value === v;
    return `<div class="pick${on ? ' on' : ''}${on && v === boldValue ? ' bad' : ''}">${esc(label)}${on ? '■' : '□'}</div>`;
  }).join('');
  // 긴 글자(매입처·품명·중량·사유): 행 높이는 고정, 길이에 따라 글씨를 줄이고 줄 수를 늘림
  // (~9자 9pt 2줄 · ~18자 8pt 2줄 · ~30자 6.8pt 3줄 · 그 이상 6pt 4줄). 그래도 넘치면 끝을 "…"로 자름
  // 중량(20mm, 숫자·단위)은 더 일찍 줄임(~7자 · ~11자 · 그 이상)
  const clip = (text, steps = [9, 18, 30]) => {
    const t = String(text === null || text === undefined ? '' : text);
    const n = t.length;
    const size = n > steps[2] ? ' tiniest' : n > steps[1] ? ' tighter' : n > steps[0] ? ' tight' : '';
    return `<div class="clip${size}" title="${esc(t)}">${esc(t)}</div>`;
  };
  const QTY_STEPS = [7, 11, 18];
  // 서명(이름) 칸 — 이름은 자르지 않게. 5자까지는 글씨를 줄여서라도 한 줄(one, n4·n5 단계 — 사용자 2026-10-20),
  // 6~12자 두 줄 · 그 이상 더 작게(칸 폭별 크기는 print.css)
  const signD03 = (id) => {
    const name = who(id);
    const n = name.length;
    const size = n > 12 ? ' tiniest' : n > 5 ? ' tighter' : n === 5 ? ' one n5' : n === 4 ? ' one n4' : ' one';
    return `<div class="name${size}" title="${esc(name)}">${esc(name)}</div>`;
  };

  function d03Options(data) {
    const field = (key) => (data.fields || []).find((f) => f.key === key) || {};
    const verdict = field('verdict');
    const labels = verdict.option_labels || { PASS: '적합', FAIL: '부적합' };
    return {
      appearance: D03_GOOD, packaging: D03_GOOD, labeling: D03_GOOD,
      verdict: (verdict.options || ['PASS', 'FAIL']).map((v) => [v, labels[v] || v]),
    };
  }

  function d03LineHtml(line, boxes, options) {
    if (!line) {
      return `<tr><td></td><td></td><td class="pk">${picks(null, D03_KINDS)}</td><td></td><td></td><td></td>
        ${D03_CHECKS.map(([k]) => `<td class="pk">${picks(null, options[k])}</td>`).join('')}
        <td class="pk">${picks(null, D03_COA)}</td>${boxes.map(() => '<td></td>').join('')}</tr>`;
    }
    const lot = line.lot || {};
    let checks;
    if (line.printable) {
      const v = line.values || {};
      checks = D03_CHECKS.map(([k]) => `<td class="pk">${picks(v[k], options[k], k === 'verdict' ? 'FAIL' : null)}</td>`).join('')
        + `<td class="pk">${picks(v.has_coa, D03_COA)}</td>`;
    } else {
      checks = line.state === 'skipped'
        ? `<td colspan="${D03_CHECKS.length + 1}" class="none skip"><div class="clip reason${(line.skip_reason || '').length > 60 ? ' long' : ''}" title="${esc(line.skip_reason)}"><b>작성 안 함</b>${line.skip_reason ? ` · ${esc(line.skip_reason)}` : ''}</div></td>`
        : `<td colspan="${D03_CHECKS.length + 1}" class="none">미작성</td>`;
    }
    const signs = (line.approval || []).map((b) => `<td class="signer">${b.staff_id ? signD03(b.staff_id) : ''}</td>`).join('');
    return `<tr data-doc="${esc(line.document_id)}">
      <td class="sm">${esc(lot.received_date)}</td>
      <td>${clip(lot.supplier_name)}</td>
      <td class="pk">${picks(lot.material_kind, D03_KINDS)}</td>
      <td>${clip(lot.item_name)}</td>
      <td>${clip(lot.quantity, QTY_STEPS)}</td>
      <td class="sm">${esc(lot.expiration_date)}</td>
      ${checks}${signs}</tr>`;
  }

  function d03LinesHtml(data, chunk, options) {
    const boxes = data.boxes || [];
    const rows = pad(chunk, D03_LINES);
    return `<table class="prt d03-lines">
      <colgroup><col style="width:21mm"><col style="width:27mm"><col style="width:17mm"><col><col style="width:20mm"><col style="width:21mm">
        <col style="width:17mm"><col style="width:21mm"><col style="width:18mm"><col style="width:18mm"><col style="width:15mm">
        ${boxes.map(() => '<col style="width:17mm">').join('')}</colgroup>
      <thead>
        <tr><th rowspan="2">입고일</th><th rowspan="2">매입처</th><th rowspan="2">구 분</th><th rowspan="2">품 명</th>
          <th rowspan="2">중 량</th><th rowspan="2">소비기한</th><th colspan="${D03_CHECKS.length}">검 사 항 목</th>
          <th rowspan="2">시험<br>성적서</th>${boxes.length ? `<th colspan="${boxes.length}">${esc(data.box_group || '')}</th>` : ''}</tr>
        <tr>${D03_CHECKS.map(([, label]) => `<th class="sm">${label}</th>`).join('')}${boxes.map((b) => `<th>${esc(b.label)}</th>`).join('')}</tr>
      </thead>
      <tbody>${rows.map((line) => d03LineHtml(line, boxes, options)).join('')}</tbody></table>`;
  }

  // 항목·관리기준: 종이처럼 두 쌍(왼쪽 앞 절반, 오른쪽 나머지)
  function d03GuideHtml(data) {
    const rows = (data.guide || []).flatMap((g) => g.rows);
    if (!rows.length) return '';
    const half = Math.ceil(rows.length / 2);
    const left = rows.slice(0, half);
    const right = rows.slice(half);
    const cell = (r) => (r ? `<td>${esc(r[0])}</td><td class="l">${esc(r[1])}</td>` : '<td></td><td></td>');
    return `<table class="prt d03-guide">
      <colgroup><col style="width:21mm"><col><col style="width:21mm"><col></colgroup>
      <tr><th>항 목</th><th>관 리 기 준</th><th>항 목</th><th>관 리 기 준</th></tr>
      ${left.map((r, i) => `<tr>${cell(r)}${cell(right[i])}</tr>`).join('')}</table>`;
  }

  function d03DeviationsHtml(data) {
    const items = Object.fromEntries((data.lines || []).map((l) => [l.document_id, (l.lot || {}).item_name]));
    const list = data.deviations || [];
    const rows = list.length ? list : pad([], MIN_DEVIATIONS);
    return `<table class="prt devs d03-devs">
      <colgroup><col style="width:21mm"><col><col style="width:80mm"><col style="width:34mm"></colgroup>
      <thead><tr><th>일자</th><th>관리기준 이탈사항</th><th>개선조치 및 결과</th><th>확인</th></tr></thead>
      <tbody>${rows.map((d) => (d ? `<tr><td>${esc(slash(d.work_date))}</td>
        <td class="l">${items[d.document_id] ? `[${esc(items[d.document_id])}] ` : ''}${esc(d.description)}</td>
        <td class="l">${esc(d.action_result)}</td>
        <td>${d.checked_by ? esc(who(d.checked_by)) : ''}</td></tr>`
        : '<tr><td>/</td><td></td><td></td><td></td></tr>')).join('')}</tbody></table>`;
  }

  function receivingHtml(data) {
    const lines = data.lines || [];
    const options = d03Options(data);
    const chunks = [];
    for (let i = 0; i < lines.length; i += D03_LINES) chunks.push(lines.slice(i, i + D03_LINES));
    if (!chunks.length) chunks.push([]);
    const head = `<table class="prt d03-title"><tr><td class="title"><div class="t1">${esc(data.title)}</div></td></tr></table>`;
    return chunks.map((chunk, i) => {
      const last = i === chunks.length - 1;
      const body = d03LinesHtml(data, chunk, options) + (last ? d03GuideHtml(data) + d03DeviationsHtml(data) : '');
      return `<div class="prt-sheet" data-type="D03" data-kind="receiving" data-page="${i + 1}">
        <table class="prt-page">
          <thead><tr><td>${head}</td></tr></thead>
          <tbody><tr><td>${body}</td></tr></tbody>
        </table></div>`;
    }).join('');
  }

  // ---------------------------------------------------------------- D10 주 묶음(세로, p12-d10-policy.md · DP-12)
  // 종이(표준 PDF 4쪽): 머리 = 제목 · 결재(작성자·HACCP팀장 — 그 주 가장 최근 승인자, 이름만) ·
  // 작성일자(첫 칸 ~ 마지막 칸) · 점검자(가장 늦은 요일 문서). 요일 칸 = 월~금 + 문서 있는 토·일.
  // 값 O / X(굵게) / 해당 없음 "-" · 출력 불가·없음·오늘 뒤 칸은 빈칸(ISP-02 보류) · 연간 2줄은 합친 칸에 가장 늦은 날짜
  const WEEK_VALUE = { O: 'O', X: 'X', NA: '-' };
  // 세로 칸 글자(주기 "매일 작업 전후" → 한 글자씩, "(금)"은 한 덩어리)
  const stack = (text) => (String(text || '').match(/\([^)]*\)|\S/g) || []).map(esc).join('<br>');
  // 관리 칸: 4글자면 2줄(개인/위생), 그 밖 그대로
  const pair2 = (text) => {
    const t = String(text || '');
    return t.length === 4 ? `${esc(t.slice(0, 2))}<br>${esc(t.slice(2))}` : esc(t);
  };
  const dotDate = (iso) => (iso ? `${iso.slice(0, 4)}. ${Number(iso.slice(5, 7))}. ${Number(iso.slice(8, 10))}.` : '20 &nbsp; . &nbsp; &nbsp; .');
  function periodKo(period) {
    if (!period || !period.from) return '20 &nbsp; 년 &nbsp; 월 &nbsp; 일 ~ &nbsp; 일';
    const [y1, m1, d1] = period.from.split('-').map(Number);
    const [y2, m2, d2] = period.to.split('-').map(Number);
    const end = y1 !== y2 ? `${y2} 년 ${m2} 월 ${d2} 일` : m1 !== m2 ? `${m2} 월 ${d2} 일` : `${d2} 일`;
    return `${y1} 년 &nbsp;${m1} 월 &nbsp;${d1} 일 &nbsp;~&nbsp; ${end}`;
  }

  function weeklyHeadHtml(data) {
    const boxes = data.boxes || [];
    return `
      <table class="prt prt-head d10-head">
        <colgroup><col><col style="width:8mm">${boxes.map(() => '<col style="width:25mm">').join('')}</colgroup>
        <tr>
          <td class="title" rowspan="2"><div class="t1">${esc(data.title)}</div></td>
          <th class="vert" rowspan="2">결<br>재</th>
          ${boxes.map((b) => `<th class="box">${esc(b.label)}</th>`).join('')}
        </tr>
        <tr>${boxes.map((b) => `<td class="sign">${b.staff_id ? signD03(b.staff_id) : ''}</td>`).join('')}</tr>
      </table>
      <table class="prt d10-meta">
        <colgroup><col style="width:24mm"><col><col style="width:24mm"><col style="width:${25 * boxes.length + 8 - 24}mm"></colgroup>
        <tr><th>작성일자</th><td>${periodKo(data.period)}</td><th>점검자</th><td>${data.inspector_id ? signD03(data.inspector_id) : ''}</td></tr>
      </table>`;
  }

  function weeklyRowsHtml(data) {
    const days = data.days || [];
    const fields = data.fields || [];
    // 주기·관리 칸 합치기(같은 주기 연속 → 주기 칸, 그 안에서 같은 관리 연속 → 관리 칸)
    const spans = fields.map((f, i) => {
      const startCadence = i === 0 || fields[i - 1].cadence !== f.cadence;
      const startGroup = startCadence || fields[i - 1].group !== f.group;
      let cad = 0;
      let grp = 0;
      if (startCadence) for (let j = i; j < fields.length && fields[j].cadence === f.cadence; j += 1) cad += 1;
      if (startGroup) {
        for (let j = i; j < fields.length && fields[j].cadence === f.cadence && fields[j].group === f.group; j += 1) grp += 1;
      }
      return { cad, grp };
    });
    const body = fields.map((f, i) => {
      const { cad, grp } = spans[i];
      const head = `${cad ? `<td class="cad" rowspan="${cad}">${stack(f.cadence)}</td>` : ''}${grp ? `<td class="grp" rowspan="${grp}">${pair2(f.group)}</td>` : ''}`;
      let cells;
      if (f.type === 'date') {
        cells = `<td class="yr" colspan="${days.length}">${dotDate((data.latest_dates || {})[f.key])}</td>`;
      } else {
        cells = days.map((d) => {
          const v = d.printable && d.values ? d.values[f.key] : null;
          return `<td class="v${v === 'X' ? ' bad' : ''}">${v ? esc(WEEK_VALUE[v] || v) : ''}</td>`;
        }).join('');
      }
      return `<tr>${head}<td class="l q">${esc(f.label)}</td>${cells}</tr>`;
    }).join('');
    return `<table class="prt d10-rows">
      <colgroup><col style="width:11mm"><col style="width:12mm"><col>${days.map(() => '<col style="width:9mm">').join('')}</colgroup>
      <thead>
        <tr><th rowspan="2">주기</th><th rowspan="2">관리</th><th rowspan="2">검증 내용</th>
          <th colspan="${days.length}" class="legend">양호 (O) &nbsp; 불량 (X)</th></tr>
        <tr>${days.map((d) => `<th>${esc(d.weekday)}</th>`).join('')}</tr>
      </thead>
      <tbody>${body}</tbody></table>`;
  }

  function weeklyDeviationsHtml(data) {
    const weekday = Object.fromEntries((data.days || []).map((d) => [d.date, d.weekday]));
    const list = data.deviations || [];
    const rows = list.length ? list : pad([], MIN_DEVIATIONS);
    return `<table class="prt devs d10-devs">
      <colgroup><col><col style="width:62mm"><col style="width:20mm"><col style="width:24mm"></colgroup>
      <thead><tr><th>한계기준 이탈내용</th><th>개선조치 및 결과</th><th>조치자</th><th>확 인</th></tr></thead>
      <tbody>${rows.map((d) => (d ? `<tr>
        <td class="l"><span class="day">[${esc(weekday[d.work_date] || '')} ${esc(slash(d.work_date))}]</span> ${esc(d.description)}</td>
        <td class="l">${esc(d.action_result)}</td>
        <td>${d.actor_id ? signD03(d.actor_id) : ''}</td>
        <td>${d.checked_by ? signD03(d.checked_by) : ''}</td></tr>`
        : '<tr><td></td><td></td><td></td><td></td></tr>')).join('')}</tbody></table>`;
  }

  // ---------------------------------------------------------------- D12 공정별 이물관리 점검표(세로, p12-d12-policy.md · DP-13)
  // 종이(표준 PDF 5쪽): 제목만(공정명 칸 없음) · 점검일자(첫 칸 ~ 마지막 칸)·점검결과·점검방법·점검주기 ·
  // 요일 아래 줄에 그날 공정명(날짜는 점검일자 칸 — DP-15) · 요일마다 기록확인 담당자·HACCP팀장(이름만) ·
  // 이탈 표 확인 = 이름만(DP-15) · 점검자 없음
  const guideValue = (data, key, fallback) => {
    const row = (data.guide || []).flatMap((g) => g.rows).find(([k]) => k === key);
    return row ? String(row[1]).replace(/\s*·\s*/g, ' / ') : fallback;
  };

  function d12HeadHtml(data) {
    return `
      <table class="prt d12-title"><tr><td class="title"><div class="t1">${esc(data.title)}</div></td></tr></table>
      <table class="prt d10-meta d12-meta">
        <colgroup><col style="width:26mm"><col><col style="width:26mm"><col style="width:46mm"></colgroup>
        <tr><th>점검일자</th><td>${periodKo(data.period)}</td><th>점검결과</th><td>${esc(guideValue(data, '점검결과', 'O 적합 / X 부적합'))}</td></tr>
        <tr><th>점검방법</th><td>${esc(guideValue(data, '점검방법', '육안확인'))}</td><th>점검주기</th><td>${esc(guideValue(data, '점검주기', '1회/일(작업 시)'))}</td></tr>
      </table>`;
  }

  function d12RowsHtml(data) {
    const days = data.days || [];
    const fields = (data.fields || []).filter((f) => f.type === 'select');
    const body = fields.map((f, i) => {
      let grp = 0;
      if (i === 0 || fields[i - 1].group !== f.group) for (let j = i; j < fields.length && fields[j].group === f.group; j += 1) grp += 1;
      const cells = days.map((d) => {
        const v = d.printable && d.values ? d.values[f.key] : null;
        return `<td class="v${v === 'X' ? ' bad' : ''}">${v ? esc(v) : ''}</td>`;
      }).join('');
      return `<tr>${grp ? `<td class="grp" rowspan="${grp}">${esc(f.group)}</td>` : ''}<td class="l q">${esc(f.label)}</td>${cells}</tr>`;
    }).join('');
    const boxes = data.boxes || [];
    const signs = boxes.map((b, i) => `<tr>${i === 0 ? `<td class="grp rec" rowspan="${boxes.length}">기록<br>확인</td>` : ''}<td class="box">${esc(b.label)}</td>
      ${days.map((d) => {
        const slot = (d.approval || [])[i];
        return `<td class="signer">${slot && slot.staff_id ? signD03(slot.staff_id) : ''}</td>`;
      }).join('')}</tr>`).join('');
    return `<table class="prt d10-rows d12-rows">
      <colgroup><col style="width:24mm"><col>${days.map(() => '<col style="width:11.5mm">').join('')}</colgroup>
      <thead>
        <tr><th rowspan="2">공정명/<br>관리항목</th><th rowspan="2">관 리 기 준</th>
          ${days.map((d) => `<th class="wd">${esc(d.weekday)}</th>`).join('')}</tr>
        <tr>${days.map((d) => `<th class="proc">${d.printable && d.process_name ? clip(d.process_name, [3, 6, 10]) : ''}</th>`).join('')}</tr>
      </thead>
      <tbody>${body}${signs}</tbody></table>`;
  }

  function d12DeviationsHtml(data) {
    const list = data.deviations || [];
    const rows = list.length ? list : pad([], MIN_DEVIATIONS);
    return `<table class="prt devs d10-devs d12-devs">
      <colgroup><col style="width:24mm"><col><col style="width:64mm"><col style="width:24mm"></colgroup>
      <thead><tr><th>일자</th><th>관리기준 이탈사항</th><th>개선조치사항 및 결과</th><th>확인</th></tr></thead>
      <tbody>${rows.map((d) => (d ? `<tr><td>${esc(slash(d.work_date))}</td>
        <td class="l">${esc(d.description)}</td>
        <td class="l">${esc(d.action_result)}</td>
        <td>${d.checked_by ? signD03(d.checked_by) : ''}</td></tr>`
        : '<tr><td></td><td></td><td></td><td></td></tr>')).join('')}</tbody></table>`;
  }

  function weeklyHtml(data) {
    const d12 = data.type_code === 'D12';
    const head = d12 ? d12HeadHtml(data) : weeklyHeadHtml(data);
    const body = d12 ? d12RowsHtml(data) + d12DeviationsHtml(data) : weeklyRowsHtml(data) + weeklyDeviationsHtml(data);
    return `<div class="prt-sheet" data-type="${esc(data.type_code)}" data-kind="weekly">
      <table class="prt-page">
        <thead><tr><td>${head}</td></tr></thead>
        <tbody><tr><td>${body}</td></tr></tbody>
      </table></div>`;
  }

  // ---------------------------------------------------------------- D11 방충방서점검표(가로, p12-d11-policy.md · DP-17)
  // 종이(표준 PDF 7쪽): 제목 · 점검주기·점검일자(그 달) · 작업소명·평가기준 · 1~5주(월요일 수만큼, 4개면 5주 칸 없음)
  // 아래 "/" = 그 주 점검일 · O / X(굵게) · 출력 불가·없음·오늘 뒤 빈칸 · 특이사항(주별 줄) 옆에 결재 칸(이름만) ·
  // 자체 소모품 점검사항 빈 표 2줄(데이터 없음 — 손으로 적음)
  const WEEK_AREA = 88;  // 주 칸 전체 폭(mm) — 4주면 칸이 넓어짐
  function monthKo(month) {
    const [y, m] = String(month || '').split('-').map(Number);
    return y ? `${y} 년 &nbsp;${m} 월` : '202 &nbsp; 년 &nbsp; &nbsp; 월';
  }
  const guideRow = (data, key, fallback) => {
    const row = (data.guide || []).flatMap((g) => g.rows).find(([k]) => k === key);
    return row ? String(row[1]) : fallback;
  };

  function monthlyHtml(data) {
    const weeks = data.weeks || [];
    const fields = (data.fields || []).filter((f) => f.type === 'select');
    const colW = (WEEK_AREA / Math.max(weeks.length, 1)).toFixed(2);
    const legend = guideRow(data, '평가기준', '양호 O · 상태불량 X').replace(/양호\s*O/, '양호: O').replace(/\s*·\s*/, ' &nbsp; ').replace(/상태불량\s*X/, '상태불량 : X');
    const cycle = guideRow(data, '점검주기', '주/1회').replace('/', ' / ');
    const head = `
      <table class="prt d11-head">
        <colgroup><col style="width:42mm"><col><col style="width:34mm"><col style="width:${WEEK_AREA - 34}mm"></colgroup>
        <tr><td class="title" colspan="2" rowspan="2"><div class="t1">${esc(data.title)}</div></td><th>점검주기</th><td>${esc(cycle)}</td></tr>
        <tr><th>점검일자</th><td>${monthKo(data.month)}</td></tr>
        <tr><th>작업소명</th><td class="l">${esc(guideRow(data, '작업소명', '청결구역'))}</td><th>평가기준</th><td>${legend}</td></tr>
      </table>`;
    const body = fields.map((f, i) => {
      let grp = 0;
      if (i === 0 || fields[i - 1].group !== f.group) for (let j = i; j < fields.length && fields[j].group === f.group; j += 1) grp += 1;
      const cells = weeks.map((w) => {
        const v = w.printable && w.values ? w.values[f.key] : null;
        return `<td class="v${v === 'X' ? ' bad' : ''}">${v ? esc(v) : ''}</td>`;
      }).join('');
      return `<tr>${grp ? `<td class="grp" rowspan="${grp}">${esc(f.group)}</td>` : ''}<td class="l q">${esc(f.label)}</td>${cells}</tr>`;
    }).join('');
    const rows = `
      <table class="prt d11-rows">
        <colgroup><col style="width:42mm"><col>${weeks.map(() => `<col style="width:${colW}mm">`).join('')}</colgroup>
        <thead>
          <tr><th rowspan="2">구 &nbsp; &nbsp; 분</th><th rowspan="2">점 &nbsp; 검 &nbsp; 항 &nbsp; 목</th>${weeks.map((w) => `<th>${w.week_no}주</th>`).join('')}</tr>
          <tr>${weeks.map((w) => `<th class="md">${w.printable && w.checked_on ? esc(slash(w.checked_on)) : '/'}</th>`).join('')}</tr>
        </thead>
        <tbody>${body}</tbody>
      </table>`;
    const boxes = data.boxes || [];
    const remarks = (data.remarks || []).map((r) => `<div class="rm"><b>${r.week_no}주${r.checked_on ? `(${esc(slash(r.checked_on))})` : ''}</b> ${esc(r.remark)}</div>`).join('');
    // 특이사항이 길면(합계 400자·1000자 넘음) 글씨를 줄이고, 그 줄이 쪽 중간에서 이어지게(빈 쪽 방지)
    const total = (data.remarks || []).reduce((n, r) => n + String(r.remark || '').length, 0);
    const remarkSize = total > 1000 ? ' huge' : total > 400 ? ' long' : '';
    const remarkTable = `
      <table class="prt d11-remark${remarkSize}">
        <colgroup><col style="width:42mm"><col>${boxes.map(() => '<col style="width:23mm">').join('')}</colgroup>
        <tr><th rowspan="2">특이사항</th><td class="l rms" rowspan="2">${remarks}</td>${boxes.map((b) => `<th class="box">${esc(b.label)}</th>`).join('')}</tr>
        <tr>${boxes.map((b) => `<td class="signer">${b.staff_id ? signD03(b.staff_id) : ''}</td>`).join('')}</tr>
      </table>`;
    const blankDate = '20 &nbsp; &nbsp; 년 &nbsp; &nbsp; 월 &nbsp; &nbsp; 일';
    const supplyRow = `<tr><td></td><td>□끈끈이 / □등</td><td></td><td>${blankDate}</td><td>${blankDate}</td><td></td></tr>`;
    const supplies = `
      <table class="prt d11-supply">
        <colgroup><col style="width:14mm"><col style="width:31mm"><col style="width:28mm"><col style="width:54mm"><col style="width:94mm"><col></colgroup>
        <tr><th colspan="6" class="cap">자 체 소 모 품 &nbsp;점 검 사 항</th></tr>
        <tr><th colspan="2">소모품 사용현황</th><th>위치</th><th>교체실시일자</th><th>교체예정일자</th><th>비 &nbsp; 고</th></tr>
        ${supplyRow}${supplyRow}
      </table>`;
    return `<div class="prt-sheet" data-type="${esc(data.type_code)}" data-kind="monthly">
      <table class="prt-page">
        <thead><tr><td>${head}</td></tr></thead>
        <tbody><tr><td>${rows}${remarkTable}${supplies}</td></tr></tbody>
      </table></div>`;
  }

  // A4 가로 — 묶음 종이만(CCP는 세로 그대로)
  function landscape() {
    if (document.getElementById('prtLandscape')) return;
    const style = document.createElement('style');
    style.id = 'prtLandscape';
    style.textContent = '@page { size: A4 landscape; }';
    document.head.appendChild(style);
  }

  // ---------------------------------------------------------------- 한 장
  function sheetHtml(data) {
    const doc = data.document;
    const is3p = data.type_code === 'CCP-3P';
    let body;
    if (is3p) body = guide3pHtml(data) + rows3pHtml(data);
    else if (data.type_code === 'CCP-2B') body = guideRowsHtml(group(data, '관리기준').rows) + rows2bHtml(doc);
    else body = guideRowsHtml(group(data, '관리기준').rows) + rows1pHtml(doc);
    body += actionHtml(data, is3p) + deviationsHtml(doc);
    return `<div class="prt-sheet" data-type="${esc(data.type_code)}">
      <table class="prt-page">
        <thead><tr><td>${headHtml(data)}</td></tr></thead>
        <tbody><tr><td>${body}</td></tr></tbody>
      </table></div>`;
  }

  // 주소 → API 조건: 문서로 열기(document_id) 또는 묶음(kind·type·date)
  function queryOf(params) {
    const id = params.get('document_id');
    if (id) return { query: `document_id=${encodeURIComponent(id)}`, label: `문서 #${id}` };
    if (params.get('kind')) {
      const q = new URLSearchParams();
      ['kind', 'type', 'date', 'month'].forEach((k) => { if (params.get(k) !== null) q.set(k, params.get(k)); });
      return { query: q.toString(), label: `${params.get('type') || ''} ${params.get('date') || params.get('month') || ''}`.trim() };
    }
    return null;
  }

  // ---------------------------------------------------------------- 첨부 사진 원본(P12 DP-19 — D01·D02 증빙 파일)
  // ?files=1,2(&auto=1): 사진만 A4 한 쪽에 하나씩, 쪽에 맞춰 축소(회전 없음). 머리·바닥글 없이 원본 그대로
  function loadFiles(params) {
    const ids = String(params.get('files') || '').split(',').map((x) => x.trim()).filter((x) => /^\d+$/.test(x));
    if (!ids.length) return message('인쇄할 파일이 없습니다.', '주소에 ?files=파일번호 가 필요합니다.');
    document.body.classList.add('prt-files-mode');
    const style = document.createElement('style');  // 원본 그대로 — 쪽 번호 안 찍음
    style.textContent = '@page { size: A4 portrait; margin: 10mm; @bottom-center { content: none; } }';
    document.head.appendChild(style);
    document.title = `첨부 인쇄 (${ids.length}장)`;
    $('#prtTitle').textContent = `첨부 원본 인쇄 · 사진 ${ids.length}장`;
    $('#prtRoot').innerHTML = ids.map((id) => `<div class="prt-file-page"><img src="/api/v1/files/${id}" alt="첨부 ${id}"></div>`).join('');
    const imgs = [...document.querySelectorAll('.prt-file-page img')];
    let left = imgs.length;
    let failed = 0;
    const done = () => {
      left -= 1;
      if (left > 0) return;
      if (failed === imgs.length) return message('파일을 불러오지 못했습니다.', '파일이 없거나 사진이 아닙니다.');
      $('#prtPrint').disabled = false;
      if (params.get('auto') === '1') setTimeout(() => window.print(), 200);
    };
    imgs.forEach((img) => {
      if (img.complete && img.naturalWidth) { done(); return; }
      img.addEventListener('load', done);
      img.addEventListener('error', () => { failed += 1; img.closest('.prt-file-page').classList.add('prt-file-missing'); done(); });
    });
    return undefined;
  }

  async function load() {
    const search = new URLSearchParams(location.search);
    if (search.get('files') !== null) return loadFiles(search);
    const target = queryOf(search);
    if (!target) return message('출력할 문서를 지정하세요.', '주소에 ?document_id=문서번호 또는 ?kind=receiving&type=D03&date=YYYY-MM-DD 가 필요합니다.');
    let response;
    let data;
    try {
      response = await fetch(`/api/v1/print/sheet?${target.query}`, { headers: { Accept: 'application/json' } });
      data = await response.json();
    } catch (error) {
      return message('출력 데이터를 불러오지 못했습니다.', String(error));
    }
    if (!response.ok) return message(data.message || '출력할 수 없습니다.', `${data.code || response.status} · ${target.label}`);
    people = data.people || {};
    if (data.kind === 'receiving') {
      const lines = data.lines || [];
      document.title = `${data.title} ${data.date}`;
      $('#prtTitle').textContent = `${data.title} · 입고일 ${data.date} · ${lines.length}줄(출력 가능 ${data.printable_count})`;
      if (!data.printable_count) {
        return message('출력할 문서가 없습니다.', `입고일 ${data.date} · D03 ${lines.length}건${lines.length ? ' — 모두 작성완료 전' : ''}`);
      }
      landscape();
      $('#prtRoot').innerHTML = receivingHtml(data);
      $('#prtPrint').disabled = false;
      return undefined;
    }
    if (data.kind === 'monthly') {
      const weeks = data.weeks || [];
      document.title = `${data.title} ${data.month}`;
      $('#prtTitle').textContent = `${data.title} · ${data.month} · ${weeks.length}주(출력 가능 ${data.printable_count})`;
      if (!data.printable_count) {
        return message('출력할 문서가 없습니다.', `${data.month} · ${data.type_code} ${weeks.filter((w) => w.document_id).length}건${weeks.some((w) => w.document_id) ? ' — 모두 작성완료 전' : ''}`);
      }
      landscape();
      $('#prtRoot').innerHTML = monthlyHtml(data);
      $('#prtPrint').disabled = false;
      return undefined;
    }
    if (data.kind === 'weekly') {
      const days = data.days || [];
      document.title = `${data.title} ${data.week_start}`;
      $('#prtTitle').textContent = `${data.title} · ${data.period.from} ~ ${data.period.to} · ${days.length}칸(출력 가능 ${data.printable_count})`;
      if (!data.printable_count) {
        return message('출력할 문서가 없습니다.', `${data.week_start} 주 · ${data.type_code} ${days.filter((d) => d.document_id).length}건${days.some((d) => d.document_id) ? ' — 모두 작성완료 전' : ''}`);
      }
      $('#prtRoot').innerHTML = weeklyHtml(data);
      $('#prtPrint').disabled = false;
      return undefined;
    }
    document.title = `${data.title} #${data.document.document_id}`;
    $('#prtTitle').textContent = `${data.title} · 문서 #${data.document.document_id}`;
    $('#prtRoot').innerHTML = sheetHtml(data);
    $('#prtPrint').disabled = false;
    return undefined;
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('#prtPrint').addEventListener('click', () => window.print());
    $('#prtClose').addEventListener('click', () => {
      window.close();
      setTimeout(() => { if (!window.closed) history.length > 1 ? history.back() : (location.href = '/'); }, 150);
    });
    load();
  });
}());
