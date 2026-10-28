(() => {
  'use strict';
  const body = document.body, content = document.getElementById('content'), message = document.getElementById('message');
  const csrf = document.getElementById('csrf').value, page = body.dataset.page;
  const groupId = body.dataset.groupId, fileId = body.dataset.fileId;
  const groupApi = `/api/groups/${groupId}/`, filesApi = `${groupApi}files/`;
  const node = (tag, text, className) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = String(text); if (className) e.className = className; return e; };
  const link = (text, href) => { const e = node('a', text); e.href = href; return e; };
  const add = (parent, ...children) => { children.forEach(child => parent.append(child)); return parent; };
  const clear = element => element.replaceChildren();
  const notice = (text, error = false) => { message.textContent = text; message.className = `notice${error ? ' error' : ''}`; message.hidden = false; };
  const details = data => { if (!data || typeof data !== 'object') return '요청을 처리하지 못했습니다.'; return Object.values(data).flat().join(' ') || '요청을 처리하지 못했습니다.'; };
  async function api(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.method && options.method !== 'GET') headers['X-CSRFToken'] = csrf;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    let response;
    try {
      response = await fetch(url, { credentials: 'same-origin', ...options, headers, signal: controller.signal });
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('서버 응답 시간이 초과되었습니다. 잠시 후 새로고침해 주세요.');
      throw error;
    } finally {
      clearTimeout(timeout);
    }
    if (!response.ok) {
      let data; try { data = await response.json(); } catch (_) { data = null; }
      const error = new Error(response.status === 401 ? '세션이 만료되었습니다. 다시 로그인해 주세요.' : response.status === 403 ? '이 작업을 할 권한이 없습니다.' : response.status === 404 ? '항목을 찾을 수 없거나 접근 권한이 없습니다.' : details(data));
      error.status = response.status; throw error;
    }
    if (response.status === 204) return null;
    return response;
  }
  const json = async (url, options) => (await api(url, options)).json();
  const handle = error => { notice(error.message || '서버에 연결하지 못했습니다. 다시 시도해 주세요.', true); if (error.status === 401) add(message, node('span', ' '), link('로그인으로 이동', '/web/login/')); };
  const heading = (title, subtitle) => { const box = node('div', undefined, 'hero'); add(box, node('h1', title), node('p', subtitle, 'muted')); return box; };
  const indexLabel = state => ({ PENDING: '색인 대기', RUNNING: '처리 중', READY: '검색 준비 완료', FAILED: '색인 실패', CANCELED: '처리 취소', DISABLED: '색인 비활성' })[state.status] || '상태 확인 중';
  const indexText = state => `${indexLabel(state)}${state.provider === 'fake' && state.status === 'READY' ? ' · 검증용 임베딩' : ''}${state.searchable_version_number ? ` · 검색 가능한 버전 ${state.searchable_version_number}` : ' · 검색 준비 전'}`;
  async function pollIndex(url, target) {
    if (!target.isConnected) return;
    try { const state = await json(url); target.textContent = indexText(state); if ((state.status === 'PENDING' || state.status === 'RUNNING') && target.isConnected) setTimeout(() => pollIndex(url, target), 3000); }
    catch (error) { target.textContent = error.message; }
  }
  const panel = title => add(node('section', undefined, 'panel'), node('h2', title));
  const form = (submit, fields) => { const f = node('form', undefined, 'stack'); fields.forEach(([label, name, type, attrs = {}]) => { const id = `field-${name}`; const input = node('input'); input.id = id; input.name = name; input.type = type; input.required = true; Object.assign(input, attrs); add(f, add(node('label', label), input)); f.lastChild.htmlFor = id; }); const button = node('button', submit, 'primary'); button.type = 'submit'; f.append(button); return f; };
  const submit = (formElement, action, busy = '처리 중…') => { formElement.addEventListener('submit', async event => { event.preventDefault(); const button = formElement.querySelector('button[type=submit]'); const original = button.textContent; button.disabled = true; button.textContent = busy; message.hidden = true; try { await action(new FormData(formElement)); } catch (error) { handle(error); } finally { button.disabled = false; button.textContent = original; } }); };
  async function home() {
    const groups = await json('/api/groups/'); clear(content);
    content.append(heading('내 그룹', '내가 참여한 그룹의 문서와 변경 이력을 확인하세요.'));
    const grid = node('div', undefined, 'grid'), list = panel('참여 중인 그룹');
    if (!groups.length) list.append(node('p', '아직 참여한 그룹이 없습니다. 그룹을 만들거나 초대 코드를 입력해 주세요.', 'muted'));
    else { const ul = node('ul', undefined, 'list'); groups.forEach(g => { const li = node('li'); add(li, add(node('div'), link(g.name, `/web/groups/${g.id}/`), node('span', ` · ${new Date(g.created_at).toLocaleDateString('ko-KR')}`, 'small')), link('열기 →', `/web/groups/${g.id}/`)); ul.append(li); }); list.append(ul); }
    const side = node('div'), create = panel('새 그룹 만들기'), createForm = form('그룹 생성', [['그룹 이름', 'name', 'text', { maxLength: 100 }]]);
    create.append(createForm); submit(createForm, async data => { const g = await json('/api/groups/', { method: 'POST', body: data }); location.href = `/web/groups/${g.id}/`; });
    const join = panel('초대 코드로 가입'), joinForm = form('그룹 가입', [['초대 코드', 'code', 'text', { maxLength: 20 }]]);
    join.append(joinForm); submit(joinForm, async data => { const result = await json('/api/groups/join/', { method: 'POST', body: data }); location.href = `/web/groups/${result.group_id}/`; });
    add(side, create, join); add(grid, list, side); content.append(grid);
  }
  async function group() {
    const [g, files] = await Promise.all([json(groupApi), json(filesApi)]); clear(content);
    add(document.getElementById('crumb'), node('span', ` / ${g.name}`)); content.append(heading(g.name, '팀 문서를 업로드하고 이전 버전을 확인하세요.'));
    const grid = node('div', undefined, 'grid'), list = panel('문서 목록');
    if (!files.length) list.append(node('p', '아직 문서가 없습니다. 첫 문서를 업로드해 주세요.', 'muted'));
    else { const ul = node('ul', undefined, 'list'); files.forEach(f => { const li = node('li'), info = node('div'); add(info, link(f.name, `/web/groups/${g.id}/files/${f.id}/`), node('div', `최신 버전 ${f.current_version_number || '미확인'} · ${new Date(f.uploaded_at).toLocaleDateString('ko-KR')}`, 'small')); const stateLine = node('div', '색인 상태 확인 중…', 'small'); info.append(stateLine); json(`${filesApi}${f.id}/versions/`).then(versions => { const latest = versions.find(v => v.version_number === f.current_version_number); if (latest) pollIndex(`${filesApi}${f.id}/versions/${latest.id}/index/`, stateLine); else stateLine.textContent = '색인 상태 미확인'; }).catch(error => { stateLine.textContent = error.message; }); add(li, info, link('버전 보기 →', `/web/groups/${g.id}/files/${f.id}/`)); ul.append(li); }); list.append(ul); }
    const side = node('div'), uploadPanel = panel('문서 업로드'); uploadPanel.append(node('p', 'UTF-8 TXT 또는 Markdown · 파일당 최대 5MB. 저장 후 AI 분석은 아직 진행되지 않습니다.', 'muted'));
    const uploadForm = form('파일 저장', [['파일 선택', 'file', 'file', { accept: '.txt,.md,.markdown,text/plain,text/markdown' }]]);
    uploadPanel.append(uploadForm); submit(uploadForm, async data => { const file = data.get('file'); if (!file || !file.size || file.size > 5 * 1024 * 1024) throw new Error('비어 있지 않은 5MB 이하의 파일을 선택해 주세요.'); await json(filesApi, { method: 'POST', body: data }); notice('원본 파일이 저장되었습니다.'); await group(); }, '업로드 중…');
    side.append(uploadPanel);
    if (g.owner_id === Number(body.dataset.userId)) {
      const invite = panel('초대 코드'), button = node('button', '초대 코드 생성'); button.type = 'button'; button.addEventListener('click', async () => { button.disabled = true; try { const result = await json(`${groupApi}invites/`, { method: 'POST' }); invite.append(node('p', `${result.code} · ${new Date(result.expires_at).toLocaleString('ko-KR')} 만료`)); } catch (error) { handle(error); } finally { button.disabled = false; } }); invite.append(button); side.append(invite);
    }
    add(grid, list, side); content.append(grid);
  }
  async function download(version, documentName) {
    try { const response = await api(`${filesApi}${fileId}/versions/${version.id}/download/`); const blob = await response.blob(), url = URL.createObjectURL(blob), a = node('a'); a.href = url; a.download = version.original_name || documentName; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000); } catch (error) { handle(error); }
  }
  async function file() {
    const [g, f, versions] = await Promise.all([json(groupApi), json(`${filesApi}${fileId}/`), json(`${filesApi}${fileId}/versions/`)]); clear(content);
    add(document.getElementById('crumb'), node('span', ' / '), link(g.name, `/web/groups/${groupId}/`), node('span', ` / ${f.name}`));
    content.append(heading(f.name, `현재 버전 ${f.current_version_number || '미확인'} · 이전 버전은 그대로 보존됩니다.`));
    const grid = node('div', undefined, 'grid'), list = panel('버전 기록'), ul = node('ul', undefined, 'list');
    versions.forEach(v => { const li = node('li'), info = node('div'); add(info, node('strong', `버전 ${v.version_number} · ${v.original_name || f.name}`), node('span', `${v.size ?? '크기 미확인'} bytes · ${new Date(v.uploaded_at).toLocaleString('ko-KR')}`, 'small')); const stateLine = node('div', '색인 상태 확인 중…', 'small'); info.append(stateLine); const button = node('button', '다운로드'); button.type = 'button'; button.addEventListener('click', () => download(v, f.name)); add(li, info, button); ul.append(li); const indexUrl = `${filesApi}${fileId}/versions/${v.id}/index/`; json(indexUrl).then(state => { stateLine.textContent = indexText(state); if (state.status === 'PENDING' || state.status === 'RUNNING') setTimeout(() => pollIndex(indexUrl, stateLine), 3000); if (state.status === 'FAILED') { const reason = node('span', ' · 처리에 실패했습니다. 원본 파일은 사용할 수 있습니다.', 'small'); info.append(reason); if (f.created_by === Number(body.dataset.userId) || g.owner_id === Number(body.dataset.userId)) { const retry = node('button', '색인 재시도'); retry.type = 'button'; retry.addEventListener('click', async () => { retry.disabled = true; try { await json(`${filesApi}${fileId}/versions/${v.id}/index/retry/`, { method: 'POST' }); notice('색인 재시도를 요청했습니다.'); await file(); } catch (error) { handle(error); retry.disabled = false; } }); info.append(retry); } } }).catch(error => { stateLine.textContent = error.message; }); }); list.append(ul);
    const side = node('div'), update = panel('새 버전 저장'); update.append(node('p', 'UTF-8 TXT 또는 Markdown · 최대 5MB. 현재 원본은 덮어쓰지 않습니다.', 'muted'));
    const updateForm = form('새 버전 업로드', [['파일 선택', 'file', 'file', { accept: '.txt,.md,.markdown,text/plain,text/markdown' }]]); update.append(updateForm);
    submit(updateForm, async data => { const selected = data.get('file'); if (!selected || !selected.size || selected.size > 5 * 1024 * 1024) throw new Error('비어 있지 않은 5MB 이하의 파일을 선택해 주세요.'); await json(`${filesApi}${fileId}/versions/`, { method: 'POST', body: data }); notice('새 버전이 저장되었습니다.'); await file(); }, '업로드 중…'); side.append(update);
    if (f.created_by === Number(body.dataset.userId) || g.owner_id === Number(body.dataset.userId)) { const remove = panel('문서 관리'), button = node('button', '문서 삭제', 'danger'); button.type = 'button'; button.addEventListener('click', async () => { if (!confirm('문서를 목록에서 삭제하시겠습니까? 저장된 원본은 보존됩니다.')) return; button.disabled = true; try { await api(`${filesApi}${fileId}/`, { method: 'DELETE' }); location.href = `/web/groups/${groupId}/`; } catch (error) { handle(error); button.disabled = false; } }); remove.append(button); side.append(remove); }
    add(grid, list, side); content.append(grid);
  }
  async function ask() {
    const group = await json(groupApi);
    clear(content);
    add(document.getElementById('crumb'), node('span', ` / ${group.name} / 질문`));
    content.append(heading(`${group.name}에 질문하기`, '검색 가능한 문서 버전의 근거로 답합니다. 근거가 부족하면 답변을 유보합니다.'));
    const questionPanel = panel('질문'), label = node('label', '질문 내용'), input = node('textarea');
    input.id = 'question-text'; input.maxLength = 1000; input.required = true; input.rows = 4;
    label.htmlFor = input.id;
    const formElement = node('form', undefined, 'stack'), button = node('button', '질문 접수', 'primary');
    button.type = 'submit'; add(formElement, label, input, button); questionPanel.append(formElement);
    const resultPanel = panel('답변 상태'); resultPanel.append(node('p', '질문을 입력해 주세요.', 'muted'));
    content.append(questionPanel, resultPanel);
    let requestKey = null, polling = false;
    const show = data => {
      clear(resultPanel); resultPanel.append(node('h2', '답변 상태'));
      if (data.status === 'SOURCE_UNAVAILABLE') { resultPanel.append(node('p', '출처가 삭제되었거나 현재 검색 버전에서 제외되어 답변을 표시할 수 없습니다.')); return true; }
      if (data.status === 'FAILED') {
        const reasons = {
          invalid_citation: '생성된 인용이 원문과 일치하지 않아 답변을 저장하지 않았습니다.',
          answer_not_in_citation: '답변이 인용 구간으로 확인되지 않아 답변을 저장하지 않았습니다.',
          invalid_answer_format: '답변 형식을 확인할 수 없어 저장하지 않았습니다.',
          invalid_provider_response: 'AI 응답을 확인할 수 없어 답변을 저장하지 않았습니다.',
          provider_unavailable: 'AI 제공자에 일시적으로 연결할 수 없었습니다.',
          temporary_failure: '처리 중 일시적인 오류가 발생했습니다.',
          source_changed: '답변 생성 중 문서 버전이나 접근 권한이 변경됐습니다.',
          access_revoked: '현재 그룹 접근 권한이 없습니다.'
        };
        resultPanel.append(node('p', reasons[data.error_code] || '답변 생성에 실패했습니다. 문서 조회와 다운로드는 계속 사용할 수 있습니다.'));
        return true;
      }
      if (data.status === 'COMPLETED') {
        if (data.answer_status === 'insufficient_evidence') resultPanel.append(node('p', '현재 접근 가능한 문서에 답을 뒷받침할 근거가 부족합니다.'));
        else {
          resultPanel.append(node('p', data.answer || ''));
          const list = node('ul', undefined, 'list');
          (data.citations || []).forEach(citation => {
            const item = node('li');
            add(item, node('strong', `${citation.document_name} · 버전 ${citation.version_number}`), node('p', citation.quote));
            const downloadButton = node('button', '원문 다운로드'); downloadButton.type = 'button';
            downloadButton.addEventListener('click', async () => {
              try {
                const response = await api(citation.download_url), blob = await response.blob();
                const url = URL.createObjectURL(blob), anchor = node('a'); anchor.href = url;
                anchor.download = citation.document_name; document.body.append(anchor); anchor.click(); anchor.remove();
                setTimeout(() => URL.revokeObjectURL(url), 60000);
              } catch (error) { handle(error); }
            });
            item.append(downloadButton); list.append(item);
          }); resultPanel.append(list);
        }
        const feedback = node('div');
        [[1, '도움이 됐어요'], [-1, '개선이 필요해요']].forEach(([rating, text]) => {
          const choice = node('button', text); choice.type = 'button';
          choice.addEventListener('click', async () => {
            choice.disabled = true;
            try { await json(`${groupApi}ai/questions/${data.id}/feedback/`, {
              method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({rating})
            }); notice('평가를 저장했습니다.'); } catch (error) { handle(error); choice.disabled = false; }
          }); feedback.append(choice);
        }); resultPanel.append(feedback); return true;
      }
      resultPanel.append(node('p', data.status === 'GENERATING' ? '답변 생성 중…' : '질문 접수됨…'));
      return false;
    };
    async function poll(questionId) {
      polling = true;
      for (let attempt = 0; attempt < 12 && document.body.dataset.page === 'ask'; attempt++) {
        try {
          const data = await json(`${groupApi}ai/questions/${questionId}/`);
          if (show(data)) { polling = false; return; }
        } catch (error) { handle(error); polling = false; return; }
        await new Promise(resolve => setTimeout(resolve, Math.min(2000 + attempt * 500, 5000)));
      }
      polling = false; resultPanel.append(node('p', '처리가 계속 진행 중입니다. 잠시 뒤 다시 확인해 주세요.'));
    }
    formElement.addEventListener('submit', async event => {
      event.preventDefault(); if (polling) return;
      const value = input.value.trim(); if (!value) return;
      requestKey ||= crypto.randomUUID(); button.disabled = true; button.textContent = '접수 중…';
      try {
        const data = await json(`${groupApi}ai/questions/`, {method: 'POST',
          headers: {'Content-Type': 'application/json', 'Idempotency-Key': requestKey},
          body: JSON.stringify({question: value})});
        history.replaceState(null, '', `/web/groups/${groupId}/ask/?question_id=${data.question_id}`);
        notice('질문을 접수했습니다.'); await poll(data.question_id);
      } catch (error) { handle(error); }
      finally { button.disabled = false; button.textContent = '질문 접수'; }
    });
    input.addEventListener('input', () => { requestKey = null; });
    const existingId = new URLSearchParams(location.search).get('question_id');
    if (existingId && /^\d+$/.test(existingId)) poll(existingId);
  }
  const runner = page === 'home' ? home : page === 'group' ? group : page === 'ask' ? ask : file;
  runner().catch(error => {
    clear(content);
    content.append(node('p', '화면을 불러오지 못했습니다. 아래 오류를 확인한 뒤 새로고침해 주세요.', 'muted'));
    handle(error);
  });
})();
