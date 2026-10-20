// P12 인쇄용 페이지 (PRT-SC-01·02) — GET /api/v1/print/sheet?document_id= 를 종이 칸 배치로 그린다.
// 정책: dev-notes/print/p12-ccp-policy.md (DP-01~03). 출력 기록 없음, 사용자 헤더 없이 읽기만.
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
        <tr>${boxes.map((b) => `<td class="sign">${b.staff_id ? `<div class="who">${esc(who(b.staff_id))}</div><div class="sm">${esc(mmdd(b.date))}</div>` : ''}</td>`).join('')}</tr>
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
        <td>${esc(who(d.actor_id))}</td><td>${d.checked_by ? `${esc(who(d.checked_by))}<div class="sm">${esc(mmdd(d.checked_on))}</div>` : ''}</td></tr>`
        : '<tr><td></td><td></td><td></td><td></td></tr>')).join('')}</tbody></table>`;
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

  async function load() {
    const params = new URLSearchParams(location.search);
    const id = params.get('document_id');
    if (!id) return message('출력할 문서를 지정하세요.', '주소에 ?document_id=문서번호 가 필요합니다.');
    let response;
    let data;
    try {
      response = await fetch(`/api/v1/print/sheet?document_id=${encodeURIComponent(id)}`, { headers: { Accept: 'application/json' } });
      data = await response.json();
    } catch (error) {
      return message('출력 데이터를 불러오지 못했습니다.', String(error));
    }
    if (!response.ok) return message(data.message || '출력할 수 없습니다.', `${data.code || response.status} · 문서 #${id}`);
    people = data.people || {};
    document.title = `${data.title} #${data.document.document_id}`;
    $('#prtTitle').textContent = `${data.title} · 문서 #${data.document.document_id}`;
    $('#prtRoot').innerHTML = sheetHtml(data);
    $('#prtPrint').disabled = false;
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
