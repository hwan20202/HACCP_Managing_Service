// 최소 XLSX 작성기 (외부 라이브러리 없음)
// 엑셀 다운로드용으로 시트 여러 개, 머리글 굵게·배경, 숫자 셀, 열 너비, 머리글 고정, 자동 필터만 지원한다.
// ZIP은 무압축(store) 방식으로 묶는다. 수만 행 규모까지는 크기·속도 모두 문제없다.
//
// 사용: XlsxWriter.download('파일명.xlsx', [{ name: '시트', title: '문서 제목', subtitle: '부제', columns: [{ header, width, type: 'number'|'text' }], rows: [[...], ...] }])
//   - number 열: 숫자 또는 숫자 문자열('12.500000')은 숫자 셀로, 빈 값은 빈 셀로 저장
//   - text 열: 그대로 문자열(품목코드·LOT처럼 앞자리 0이 있는 값도 보존)
//   - auto 열: JS number 값만 숫자 셀, 나머지는 문자열(요약표처럼 항목마다 형식이 다른 열)
const XlsxWriter = {
  _crcTable: null,

  crc32(bytes) {
    if (!this._crcTable) {
      this._crcTable = new Uint32Array(256);
      for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
        this._crcTable[n] = c >>> 0;
      }
    }
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) crc = this._crcTable[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
  },

  // XML에 넣을 수 없는 제어문자를 지우고 특수문자를 이스케이프한다.
  xml(value) {
    return String(value)
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F￾￿]/g, '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },

  columnName(index) {
    let name = '';
    for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
    return name;
  },

  sheetName(name, used) {
    let base = String(name || 'Sheet').replace(/[\[\]:*?/\\]/g, ' ').trim().slice(0, 31) || 'Sheet';
    let candidate = base;
    for (let i = 2; used.has(candidate.toLowerCase()); i++) candidate = `${base.slice(0, 31 - String(i).length - 1)}_${i}`;
    used.add(candidate.toLowerCase());
    return candidate;
  },

  cell(ref, value, type, style) {
    if (value === null || value === undefined || value === '') return style ? `<c r="${ref}" s="${style}"/>` : '';
    if (type === 'auto' && typeof value === 'number' && Number.isFinite(value)) return `<c r="${ref}" s="${style || 2}"><v>${value}</v></c>`;
    if (type === 'number') {
      const n = typeof value === 'number' ? value : Number(value);
      if (Number.isFinite(n)) return `<c r="${ref}" s="${style || 2}"><v>${n}</v></c>`;
    }
    // 숫자 열인데 숫자가 아닌 값은 숫자 서식 없이 문자열로 둔다.
    const textStyle = style === 2 ? 0 : style;
    return `<c r="${ref}" t="inlineStr"${textStyle ? ` s="${textStyle}"` : ''}><is><t xml:space="preserve">${this.xml(value)}</t></is></c>`;
  },

  // 시트 상단 제목 영역: title(1행, 굵게·크게, 열 전체 병합) + subtitle(2행, 회색 작은 글씨) + 빈 행.
  // 제목이 있으면 머리글·데이터가 그만큼 아래로 내려가고, 고정·필터 범위도 따라 내려간다.
  layout(sheet) {
    const columns = sheet.columns || [];
    const rows = sheet.rows || [];
    const titleRows = sheet.title ? (sheet.subtitle ? 3 : 2) : 0;
    const hasHeader = columns.length > 0 && sheet.header !== false;
    const headerRow = hasHeader ? titleRows + 1 : null;
    const firstDataRow = titleRows + (hasHeader ? 2 : 1);
    const lastRow = Math.max(firstDataRow + rows.length - 1, headerRow || titleRows || 1);
    const lastCol = this.columnName(Math.max(columns.length, 1) - 1);
    const filter = hasHeader && sheet.autoFilter !== false ? `A${headerRow}:${lastCol}${Math.max(headerRow + rows.length, headerRow)}` : null;
    const footerRow = sheet.footer ? firstDataRow + rows.length : null; // 합계 행은 필터 범위 밖(데이터 바로 아래)
    return { columns, rows, titleRows, hasHeader, headerRow, firstDataRow, lastRow: footerRow || lastRow, lastCol, filter, footerRow };
  },

  worksheet(sheet) {
    const L = this.layout(sheet);
    const cols = L.columns.map((c, i) => `<col min="${i + 1}" max="${i + 1}" width="${c.width || 14}" customWidth="1"/>`).join('');
    const titleXml = sheet.title
      ? `<row r="1" ht="24" customHeight="1">${this.cell('A1', sheet.title, 'text', 3)}</row>` +
        (sheet.subtitle ? `<row r="2">${this.cell('A2', sheet.subtitle, 'text', 4)}</row>` : '')
      : '';
    const header = L.hasHeader ? `<row r="${L.headerRow}">${L.columns.map((c, i) => this.cell(`${this.columnName(i)}${L.headerRow}`, c.header, 'text', 1)).join('')}</row>` : '';
    const body = L.rows.map((row, r) => `<row r="${r + L.firstDataRow}">${L.columns.map((c, i) => this.cell(`${this.columnName(i)}${r + L.firstDataRow}`, row[i], c.type, c.type === 'number' ? 2 : 0)).join('')}</row>`).join('');
    // 합계 행: footer = { label, span(라벨이 차지할 앞쪽 열 수), values: [[열 번호, 값], ...] }. 모든 칸에 배경·테두리
    let footerXml = '';
    if (L.footerRow) {
      const values = new Map(sheet.footer.values || []);
      const span = Math.max(1, sheet.footer.span || 1);
      footerXml = `<row r="${L.footerRow}" ht="20" customHeight="1">${L.columns.map((c, i) => {
        const ref = `${this.columnName(i)}${L.footerRow}`;
        if (i === 0) return this.cell(ref, sheet.footer.label || '합계', 'text', 5);
        if (i < span) return `<c r="${ref}" s="5"/>`;
        return values.has(i) ? this.cell(ref, values.get(i), 'number', 6) : `<c r="${ref}" s="5"/>`;
      }).join('')}</row>`;
    }
    const merges = [
      ...(sheet.title && L.columns.length > 1 ? [`A1:${L.lastCol}1`, ...(sheet.subtitle ? [`A2:${L.lastCol}2`] : [])] : []),
      ...(L.footerRow && (sheet.footer.span || 1) > 1 ? [`A${L.footerRow}:${this.columnName(sheet.footer.span - 1)}${L.footerRow}`] : []),
    ];
    const pane = L.hasHeader
      ? `<sheetViews><sheetView workbookViewId="0"><pane ySplit="${L.headerRow}" topLeftCell="A${L.headerRow + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>` : '';
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
${pane}
${cols ? `<cols>${cols}</cols>` : ''}<sheetData>${titleXml}${header}${body}${footerXml}</sheetData>
${L.filter ? `<autoFilter ref="${L.filter}"/>` : ''}
${merges.length ? `<mergeCells count="${merges.length}">${merges.map(m => `<mergeCell ref="${m}"/>`).join('')}</mergeCells>` : ''}
</worksheet>`;
  },

  build(sheets) {
    if (!Array.isArray(sheets) || sheets.length === 0) throw new Error('시트가 없습니다.');
    const used = new Set();
    const names = sheets.map(s => this.sheetName(s.name, used));
    const files = [
      ['[Content_Types].xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
${names.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('\n')}
</Types>`],
      ['_rels/.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`],
      ['xl/workbook.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>${names.map((n, i) => `<sheet name="${this.xml(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets>
${sheets.some(s => this.layout(s).filter) ? `<definedNames>${sheets.map((s, i) => {
  const filter = this.layout(s).filter;
  if (!filter) return '';
  const [from, to] = filter.split(':').map(ref => ref.replace(/^([A-Z]+)(\d+)$/, '$$$1$$$2'));
  return `<definedName name="_xlnm._FilterDatabase" localSheetId="${i}" hidden="1">'${this.xml(names[i].replace(/'/g, "''"))}'!${from}:${to}</definedName>`;
}).join('')}</definedNames>` : ''}
</workbook>`],
      ['xl/_rels/workbook.xml.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
${names.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('\n')}
<Relationship Id="rId${names.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`],
      // 스타일: 0 기본, 1 머리글(굵게·회색 배경·테두리), 2 숫자(#,##0.###### — 소수 6자리까지, 불필요한 0 없음), 3 문서 제목, 4 부제(회색), 5 합계 라벨(굵게·하늘색·가운데), 6 합계 숫자(#,##0.000###)
      ['xl/styles.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.######"/><numFmt numFmtId="165" formatCode="#,##0.000###"/></numFmts>
<fonts count="4"><font><sz val="10"/><name val="맑은 고딕"/></font><font><b/><sz val="10"/><name val="맑은 고딕"/></font><font><b/><sz val="15"/><name val="맑은 고딕"/></font><font><sz val="9"/><color rgb="FF6B7280"/><name val="맑은 고딕"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE9EEF3"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFDDEBF7"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFB0B7BF"/></left><right style="thin"><color rgb="FFB0B7BF"/></right><top style="thin"><color rgb="FFB0B7BF"/></top><bottom style="thin"><color rgb="FFB0B7BF"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="7"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment vertical="center"/></xf><xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf numFmtId="165" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`],
      ...sheets.map((s, i) => [`xl/worksheets/sheet${i + 1}.xml`, this.worksheet(s)]),
    ];
    return this.zip(files);
  },

  // 무압축 ZIP. 파일명은 UTF-8 플래그(bit 11)로 저장한다.
  zip(files) {
    const encoder = new TextEncoder();
    const chunks = [];
    const central = [];
    let offset = 0;
    const now = new Date();
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    for (const [name, content] of files) {
      const nameBytes = encoder.encode(name);
      const data = encoder.encode(content);
      const crc = this.crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
      local.setUint16(8, 0, true); local.setUint16(10, dosTime, true); local.setUint16(12, dosDate, true);
      local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
      local.setUint16(26, nameBytes.length, true); local.setUint16(28, 0, true);
      chunks.push(new Uint8Array(local.buffer), nameBytes, data);
      const entry = new DataView(new ArrayBuffer(46));
      entry.setUint32(0, 0x02014b50, true); entry.setUint16(4, 20, true); entry.setUint16(6, 20, true); entry.setUint16(8, 0x0800, true);
      entry.setUint16(10, 0, true); entry.setUint16(12, dosTime, true); entry.setUint16(14, dosDate, true);
      entry.setUint32(16, crc, true); entry.setUint32(20, data.length, true); entry.setUint32(24, data.length, true);
      entry.setUint16(28, nameBytes.length, true); entry.setUint32(42, offset, true);
      central.push(new Uint8Array(entry.buffer), nameBytes);
      offset += 30 + nameBytes.length + data.length;
    }
    const centralSize = central.reduce((n, c) => n + c.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, centralSize, true); end.setUint32(16, offset, true);
    const parts = [...chunks, ...central, new Uint8Array(end.buffer)];
    const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
    let pos = 0;
    for (const p of parts) { out.set(p, pos); pos += p.length; }
    return out;
  },

  // 파일명에 쓸 수 없는 문자를 바꾼다.
  fileName(name) {
    return String(name).replace(/[\\/:*?"<>|\u0000-\u001F]/g, '_').replace(/\s+/g, '_').slice(0, 150);
  },

  download(filename, sheets) {
    const bytes = this.build(sheets);
    const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = this.fileName(filename);
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    return bytes.length;
  },
};
