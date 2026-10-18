(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const state = {health: null, currentDraft: null, currentDocument: null, activeView: 'home'};
  let token = sessionStorage.getItem('personal-agent-token') || '';

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function toast(message, type = 'ok') {
    const node = document.createElement('div');
    node.className = `toast${type === 'error' ? ' error' : ''}`;
    node.textContent = message;
    $('#toast-root').appendChild(node);
    window.setTimeout(() => node.remove(), 4400);
  }
  function setStatus(node, message, type = '') {
    if (!node) return;
    node.textContent = message || '';
    node.className = `inline-status${type ? ` ${type}` : ''}`;
  }
  function feedback(selector, message, isError = false) {
    const node = $(selector);
    if (!node) return;
    node.textContent = message;
    node.classList.remove('hidden', 'error');
    if (isError) node.classList.add('error');
  }
  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    let response;
    try {
      response = await fetch(path, {...options, headers});
    } catch (err) {
      throw new Error('无法连接后台服务。确认命令行中的服务仍在运行，且地址正确。');
    }
    if (response.status === 401 && path !== '/api/login') {
      token = '';
      sessionStorage.removeItem('personal-agent-token');
      showLogin('登录状态已失效，请重新输入密码。');
    }
    let body;
    const contentType = response.headers.get('content-type') || '';
    try { body = contentType.includes('application/json') ? await response.json() : await response.text(); }
    catch { body = null; }
    if (!response.ok) {
      const detail = body && typeof body === 'object' ? body.detail : body;
      throw new Error(detail || `请求失败（HTTP ${response.status}）`);
    }
    return body;
  }
  function showLogin(message = '') {
    $('#login-gate').classList.remove('hidden');
    $('#login-error').textContent = message;
    $('#login-password').focus();
  }
  function hideLogin() { $('#login-gate').classList.add('hidden'); $('#login-error').textContent = ''; }
  async function loadHealth() {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error('后台状态不可用');
    state.health = await response.json();
    if (state.health.auth_required && !token) { showLogin(); return false; }
    return true;
  }

  function go(view) {
    if (!$('#view-' + view)) return;
    state.activeView = view;
    $$('.view').forEach(node => node.classList.toggle('active', node.id === `view-${view}`));
    $$('.nav-item').forEach(node => node.classList.toggle('active', node.dataset.view === view));
    const titles = {home:'总览',ask:'知识问答',library:'资料库',mail:'邮箱工作台',rules:'长期规则',activity:'任务与记录'};
    $('#page-title').textContent = titles[view] || '个人 Agent';
    if (view === 'library') loadDocuments();
    if (view === 'mail') loadMail();
    if (view === 'rules') loadRules();
    if (view === 'activity') loadActivity();
    if (view === 'home') loadDashboard();
    window.scrollTo({top:0, behavior:'smooth'});
  }
  function renderReadyTag(isReady, readyText = '已配置', missingText = '未配置') {
    return `<span class="tag ${isReady ? 'good' : 'warn'}">${isReady ? readyText : missingText}</span>`;
  }
  async function loadDashboard() {
    try {
      const data = await request('/api/dashboard');
      $('#stat-docs').textContent = data.documents;
      $('#stat-rules').textContent = data.rules;
      $('#stat-emails').textContent = data.emails;
      $('#stat-drafts').textContent = data.drafts;
      $('#integration-status').innerHTML = [
        ['知识库索引', true, '已启用', '等待初始化', 'Markdown 文件 + SQLite 全文索引'],
        ['模型接口', data.llm_configured, '可生成回答', '未配置', data.llm_configured ? '问答与拟稿调用已配置模型' : '基础检索仍可使用；AI 综合回答需填写模型设置'],
        ['IMAP 邮箱读取', data.imap_configured, '后台同步已启用', '未连接', data.imap_configured ? '新邮件会由独立后台定期检查' : '在 .env 中填写 IMAP_HOST / IMAP_USER / IMAP_PASSWORD'],
        ['SMTP 邮件发送', data.smtp_configured, '确认后可发送', '未连接', data.smtp_configured ? '只有人工确认的当前版本才会发送' : '在 .env 中填写 SMTP_HOST / SMTP_USER / SMTP_PASSWORD / MAIL_FROM'],
      ].map(([name, ready, yes, no, detail]) => `<div class="integration-row"><div><b>${esc(name)}</b><small>${esc(detail)}</small></div>${renderReadyTag(ready, yes, no)}</div>`).join('');
      const statuses = [data.llm_configured, data.imap_configured, data.smtp_configured];
      $('#runtime-indicator').textContent = statuses.every(Boolean) ? '服务就绪' : '基础模式';
      $('#runtime-indicator').className = 'status-pill ' + (statuses.every(Boolean) ? 'ready' : 'warn');
      const notes = [];
      if (!data.llm_configured) notes.push('未配置模型：文件入库、关键词检索、手动修改和规则保存可用，但不会生成真正的模型回答。');
      if (!data.imap_configured) notes.push('未配置 IMAP：邮件同步未启动。');
      if (!data.smtp_configured) notes.push('未配置 SMTP：邮件可拟稿和编辑，但发送按钮不可用。');
      if (!notes.length) notes.push('模型、IMAP 与 SMTP 均已配置。建议先用一封测试邮件验证回复、线程关联与人工确认发送。');
      $('#setup-notice').textContent = notes.join(' ');
    } catch (err) { toast(err.message, 'error'); }
  }

  function docCard(row, compact = false) {
    const summary = row.summary || row.snippet || row.content || '';
    return `<article class="result-card"><h4>${esc(row.title || '未命名资料')}</h4><p>${esc(summary).slice(0, 1100)}</p><div class="result-meta"><span>${esc(row.source_type || 'note')} · ${esc(row.file_path || '')}</span><button class="text-link" data-open-doc="${esc(row.doc_id)}">打开原文 ↗</button></div>${row.snippet ? `<p class="muted" style="margin-top:10px">命中片段：${esc(row.snippet)}</p>` : ''}</article>`;
  }
  function bindDocButtons(root = document) {
    $$('[data-open-doc]', root).forEach(btn => btn.addEventListener('click', () => openDocument(btn.dataset.openDoc)));
  }
  async function askQuestion(question) {
    setStatus($('#ask-status'), '正在检索你的 Markdown 资料…');
    $('#ask-result').innerHTML = '';
    try {
      const result = await request('/api/ask', {method:'POST', body:JSON.stringify({question})});
      const invalidNotice = result.invalid_citations?.length ? `<p class="muted">模型产生了未能验证的来源 ID：${esc(result.invalid_citations.join(', '))}。请仅采用下方真实来源链接。</p>` : '';
      $('#ask-result').innerHTML = `<article class="answer-card"><h3>${result.model_used ? '知识库回答' : '检索说明'}</h3><div class="answer-body">${esc(result.answer)}</div>${invalidNotice}<div class="result-meta"><span>${result.model_used ? '已调用模型' : '未调用模型'} · 检索到 ${result.citations.length} 个来源</span></div></article><div class="citation-title">检索来源 / 可回到原文的引用</div>${result.citations.map(docCard).join('')}`;
      bindDocButtons($('#ask-result'));
      setStatus($('#ask-status'), '完成。来源引用来自本地知识库检索；打开资料可以查看和编辑完整 Markdown。');
    } catch (err) { setStatus($('#ask-status'), err.message); toast(err.message, 'error'); }
  }

  async function loadDocuments() {
    const list = $('#documents-list');
    list.innerHTML = '<div class="skeleton"></div>';
    try {
      const docs = await request('/api/documents?limit=80');
      if (!docs.length) { list.innerHTML = '<div class="empty-state">资料库目前为空。先上传一篇文章或粘贴一段笔记。</div>'; return; }
      list.innerHTML = docs.map(row => `<div class="document-row"><div class="doc-file-icon">${row.source_type === 'rule' ? '⚑' : 'MD'}</div><div class="document-row-main"><b>${esc(row.title)}</b><p>${esc((row.summary || '').slice(0, 220))}</p><small>${esc(row.file_path)} · 更新于 ${esc(row.updated_at || '')}</small></div><button class="button subtle small row-action" data-open-doc="${esc(row.doc_id)}">打开</button></div>`).join('');
      bindDocButtons(list);
    } catch (err) { list.innerHTML = `<div class="empty-state">${esc(err.message)}</div>`; }
  }
  async function searchLibrary(query) {
    $('#library-results').innerHTML = '<div class="skeleton"></div>';
    try {
      const rows = await request(`/api/search?q=${encodeURIComponent(query)}&limit=12`);
      $('#library-results').innerHTML = rows.length ? rows.map(docCard).join('') : '<div class="empty-state">没有找到相关资料。可以换一个词，或先导入资料。</div>';
      bindDocButtons($('#library-results'));
    } catch (err) { $('#library-results').innerHTML = `<div class="empty-state">${esc(err.message)}</div>`; }
  }
  async function openDocument(docId) {
    try {
      const item = await request(`/api/documents/${encodeURIComponent(docId)}`);
      state.currentDocument = item;
      createDocumentModal();
      $('#doc-modal-title').textContent = item.title;
      $('#doc-modal-path').textContent = item.file_path;
      $('#doc-modal-editor').value = item.markdown || '';
      $('#doc-modal').classList.remove('hidden');
      $('#doc-modal-editor').focus();
    } catch (err) { toast(err.message, 'error'); }
  }
  function createDocumentModal() {
    if ($('#doc-modal')) return;
    const modal = document.createElement('div');
    modal.id = 'doc-modal'; modal.className = 'login-gate hidden'; modal.setAttribute('role','dialog'); modal.setAttribute('aria-modal','true');
    modal.innerHTML = `<div class="login-card" style="width:min(1000px,100%);max-height:90vh;display:flex;flex-direction:column"><div style="display:flex;justify-content:space-between;gap:12px;align-items:start"><div><h1 id="doc-modal-title" style="font-size:19px"></h1><p id="doc-modal-path" style="overflow-wrap:anywhere"></p></div><button id="doc-modal-close" class="button subtle">关闭</button></div><p class="muted tiny">编辑的是实际 Markdown 源文件；保存后索引立即更新。保留最上方的 id 元数据以确保引用稳定。</p><textarea id="doc-modal-editor" spellcheck="false" style="min-height:48vh;flex:1;width:100%;resize:vertical;background:#0c1420;border:1px solid #30445d;border-radius:10px;padding:13px;color:#e7eff9;font:12px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace"></textarea><div style="display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap"><button id="doc-modal-save" class="button primary">保存并更新索引</button></div><p id="doc-modal-status" class="muted tiny"></p></div>`;
    document.body.appendChild(modal);
    $('#doc-modal-close').addEventListener('click', () => modal.classList.add('hidden'));
    modal.addEventListener('click', ev => { if (ev.target === modal) modal.classList.add('hidden'); });
    $('#doc-modal-save').addEventListener('click', async () => {
      if (!state.currentDocument) return;
      const btn = $('#doc-modal-save'); btn.disabled = true; $('#doc-modal-status').textContent = '正在保存…';
      try {
        await request(`/api/documents/${encodeURIComponent(state.currentDocument.doc_id)}`, {method:'PUT', body:JSON.stringify({markdown:$('#doc-modal-editor').value})});
        $('#doc-modal-status').textContent = '已保存，检索索引已更新。';
        toast('Markdown 已保存');
        await loadDocuments();
        if ($('#library-query').value.trim()) await searchLibrary($('#library-query').value.trim());
      } catch(err) { $('#doc-modal-status').textContent = err.message; toast(err.message,'error'); }
      finally { btn.disabled = false; }
    });
  }

  async function loadMail() {
    try {
      const [emails, drafts, dashboard] = await Promise.all([request('/api/emails?limit=80'), request('/api/drafts?limit=80'), request('/api/dashboard')]);
      $('#mail-count').textContent = emails.length;
      $('#draft-count').textContent = drafts.length;
      $('#mail-notice').classList.toggle('hidden', dashboard.imap_configured);
      if (!emails.length) $('#emails-list').innerHTML = '<div class="empty-state">还没有邮件记录。配置 IMAP 后会在后台获取新邮件。</div>';
      else $('#emails-list').innerHTML = emails.map(mail => `<button class="mail-row" data-open-email="${mail.id}"><div class="mail-row-head"><b>${esc(mail.subject || '(无主题)')}</b><span class="mail-status ${esc(mail.status)}">${esc(mail.status)}</span></div><p>${esc(mail.sender || '未知发件人')} ${mail.folder === 'OUTBOUND' ? '→ 已发送' : ''}</p><small>${esc(mail.sent_at || mail.created_at || '')}</small></button>`).join('');
      if (!drafts.length) $('#drafts-list').innerHTML = '<div class="empty-state">没有回复草稿。下一封新邮件同步后会自动拟稿（需要配置模型才能得到 AI 草稿）。</div>';
      else $('#drafts-list').innerHTML = drafts.map(draft => `<button class="mail-row" data-open-draft="${esc(draft.id)}"><div class="mail-row-head"><b>${esc(draft.original_subject || draft.subject || '(无主题)')}</b><span class="mail-status ${esc(draft.status)}">${esc(draft.status)}</span></div><p>${esc(draft.recipient || '')} · ${(esc(draft.body || '')).slice(0,100)}</p><small>版本 ${esc(draft.version)} · ${esc(draft.updated_at || '')}</small></button>`).join('');
      $$('[data-open-email]').forEach(btn => btn.addEventListener('click', () => loadEmailDetail(Number(btn.dataset.openEmail))));
      $$('[data-open-draft]').forEach(btn => btn.addEventListener('click', () => openDraft(btn.dataset.openDraft)));
      state.health = {...(state.health || {}), ...dashboard};
      $('#send-draft-btn').disabled = !dashboard.smtp_configured || (state.currentDraft && !['DRAFT','APPROVED'].includes(state.currentDraft.status));
      $('#draft-send-note').textContent = dashboard.smtp_configured ? '发送前会弹出包含收件人、主题和完整正文的确认窗口。若状态不确定，系统会锁定重试以避免重复发送。' : 'SMTP 尚未配置，因此发送按钮不可用；草稿仍可查看、编辑和保存。';
    } catch (err) { $('#mail-feedback').textContent = err.message; }
  }
  async function loadEmailDetail(id) {
    try {
      const result = await request(`/api/emails/${id}`);
      $('#email-detail-panel').classList.remove('hidden');
      $('#email-detail-title').textContent = result.email.subject || '(无主题)';
      $('#email-detail-meta').textContent = `${result.email.sender} · ${result.email.sent_at || result.email.created_at} · ${result.email.status}`;
      $('#email-thread').innerHTML = result.history.map(msg => `<article class="thread-message"><b>${esc(msg.sender || '未知发件人')} → ${esc(msg.recipients || '')}</b><small>${esc(msg.subject || '')} · ${esc(msg.sent_at || '')}</small><div class="thread-body">${esc(msg.body || '')}</div></article>`).join('');
      $('#email-detail-panel').scrollIntoView({behavior:'smooth',block:'start'});
    } catch (err) { toast(err.message,'error'); }
  }
  async function openDraft(id) {
    try {
      const drafts = await request('/api/drafts?limit=100');
      const draft = drafts.find(row => row.id === id);
      if (!draft) throw new Error('草稿不存在');
      state.currentDraft = draft;
      $('#draft-editor-panel').classList.remove('hidden');
      $('#draft-id').value = draft.id;
      $('#draft-recipient').value = draft.recipient || '';
      $('#draft-subject').value = draft.subject || '';
      $('#draft-body').value = draft.body || '';
      $('#draft-status').textContent = draft.status;
      $('#draft-editor-meta').textContent = `${draft.original_sender || ''} · 原邮件：${draft.original_subject || ''} · 版本 ${draft.version}`;
      $('#draft-original').innerHTML = `<b>原始来信（供核对）</b><p>${esc(draft.original_body || '没有可显示的原始正文')}</p>`;
      const editable = ['DRAFT','APPROVED'].includes(draft.status);
      $('#draft-recipient').disabled = !editable;
      $('#draft-subject').disabled = !editable;
      $('#draft-body').disabled = !editable;
      $('#save-draft-btn').disabled = !editable;
      $('#send-draft-btn').disabled = !editable || !((state.health || {}).smtp_configured);
      $('#send-draft-note').textContent = draft.status === 'SEND_UNCERTAIN' ? '发送结果不确定，系统已阻止自动重试。请先核对发件箱，再使用后续的人工核对流程。' : (draft.status === 'SENT' ? '此草稿已发送，不能重复发送。' : '确认窗口会展示完整最终版本。你确认后，后台只尝试发送一次；发生不确定错误时不会自动重试。');
      $('#draft-editor-panel').scrollIntoView({behavior:'smooth',block:'start'});
    } catch (err) { toast(err.message,'error'); }
  }
  async function saveDraft() {
    const id = $('#draft-id').value;
    if (!id) return;
    const payload = {recipient:$('#draft-recipient').value, subject:$('#draft-subject').value, body:$('#draft-body').value};
    try {
      const result = await request(`/api/drafts/${encodeURIComponent(id)}`, {method:'PUT', body:JSON.stringify(payload)});
      toast('草稿修改已保存；旧确认状态已清除。');
      await loadMail();
      await openDraft(id);
    } catch (err) { toast(err.message, 'error'); }
  }
  async function sendDraft() {
    const id = $('#draft-id').value;
    if (!id) return;
    const recipient = $('#draft-recipient').value.trim();
    const subject = $('#draft-subject').value.trim();
    const body = $('#draft-body').value;
    if (!recipient || !subject || !body.trim()) { toast('请填写收件人、主题和正文。','error'); return; }
    const approvedVersion = `收件人：${recipient}\n主题：${subject}\n\n正文：\n${body}\n\n只有确认后才会尝试发送，发送结果不确定时不会自动重试。`;
    if (!window.confirm(`请最后核对以下完整邮件版本：\n\n${approvedVersion}\n\n确认将此版本发送出去吗？`)) return;
    const btn = $('#send-draft-btn'); btn.disabled = true; btn.textContent = '正在提交发送…';
    try {
      const result = await request(`/api/drafts/${encodeURIComponent(id)}/send`, {method:'POST', body:JSON.stringify({recipient,subject,body,confirm:true})});
      toast(`发送已被 SMTP 接受。记录 ID：${result.outbound_message_id || result.draft_id}`);
      $('#draft-editor-panel').classList.add('hidden');
      state.currentDraft = null;
      await loadMail();
      await loadDashboard();
    } catch (err) { toast(err.message, 'error'); }
    finally { btn.textContent = '✓ 确认并发送此版本'; btn.disabled = false; }
  }

  async function loadRules() {
    try {
      const rules = await request('/api/rules');
      const list = $('#rules-list');
      if (!rules.length) { list.innerHTML = '<div class="empty-state">还没有长期规则。把你纠正过 Agent 的方式写下来，后续任务就可以重复使用。</div>'; return; }
      list.innerHTML = rules.map(rule => `<div class="document-row"><div class="doc-file-icon">⚑</div><div class="document-row-main"><b>${esc(rule.title)}</b><p>${esc(rule.content || rule.summary || '')}</p><small>${esc(rule.file_path)} · ${esc(rule.updated_at || '')}</small></div><button class="button subtle small row-action" data-open-doc="${esc(rule.doc_id)}">编辑规则</button></div>`).join('');
      bindDocButtons(list);
    } catch (err) { $('#rules-list').innerHTML = `<div class="empty-state">${esc(err.message)}</div>`; }
  }
  async function loadActivity() {
    try {
      const data = await request('/api/tasks?limit=50');
      $('#tasks-list').innerHTML = data.tasks.length ? data.tasks.map(task => `<div class="document-row"><div class="doc-file-icon">◷</div><div class="document-row-main"><b>${esc(task.title)} <span class="mail-status ${esc(task.status)}">${esc(task.status)}</span></b><p>${esc(task.error_text || JSON.stringify(task.result_json || {}))}</p><small>${esc(task.created_at)} · ${esc(task.id)}</small></div></div>`).join('') : '<div class="empty-state">当前没有后台任务记录。</div>';
      $('#operations-list').innerHTML = data.operations.length ? data.operations.map(item => `<div class="document-row"><div class="doc-file-icon">↗</div><div class="document-row-main"><b>${esc(item.action)} · ${esc(item.object_type)}</b><p>${esc(JSON.stringify(item.detail_json || {}))}</p><small>${esc(item.created_at)} · ${esc(item.object_id)}</small></div></div>`).join('') : '<div class="empty-state">还没有重要操作记录。</div>';
    } catch (err) { toast(err.message,'error'); }
  }

  $('#login-form').addEventListener('submit', async event => {
    event.preventDefault();
    const password = $('#login-password').value;
    $('#login-error').textContent = '正在验证…';
    try {
      const result = await request('/api/login', {method:'POST', body:JSON.stringify({password})});
      token = result.token || '';
      if (result.auth_required) sessionStorage.setItem('personal-agent-token', token);
      hideLogin();
      await loadAll();
    } catch (err) { $('#login-error').textContent = err.message; }
  });
  $('#main-nav').addEventListener('click', event => { const btn = event.target.closest('[data-view]'); if (btn) go(btn.dataset.view); });
  $$('[data-go]').forEach(btn => btn.addEventListener('click', () => go(btn.dataset.go)));
  $('#refresh-all').addEventListener('click', async () => { await loadAll(); toast('状态已刷新'); });
  $('#top-upload').addEventListener('click', () => { go('library'); $('#source-title').focus(); });
  $('#ask-form').addEventListener('submit', event => { event.preventDefault(); const q = $('#ask-question').value.trim(); if (q) askQuestion(q); });
  $('#text-ingest-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter || $('button[type="submit"]', event.currentTarget);
    button.disabled = true;
    try {
      const result = await request('/api/documents/text', {method:'POST', body:JSON.stringify({title:$('#source-title').value.trim(),content:$('#source-content').value,source_uri:$('#source-uri').value.trim()})});
      feedback('#ingest-feedback', `${result.message}\n标题：${result.title}\n路径：${result.file_path}${result.duplicate ? '\n已复用已有资料，没有创建重复文档。' : ''}`);
      $('#source-title').value=''; $('#source-content').value=''; $('#source-uri').value='';
      await loadDocuments(); await loadDashboard(); toast('资料已入库');
    } catch(err) { feedback('#ingest-feedback', err.message, true); }
    finally { button.disabled = false; }
  });
  $('#file-ingest-form').addEventListener('submit', async event => {
    event.preventDefault();
    const file = $('#source-file').files[0]; if (!file) return;
    const button = event.submitter || $('button[type="submit"]', event.currentTarget); button.disabled = true;
    const form = new FormData(); form.append('file', file); form.append('source_uri', $('#file-source-uri').value.trim());
    try {
      const result = await request('/api/documents/upload', {method:'POST', body:form});
      feedback('#ingest-feedback', `${result.message}\n标题：${result.title}\n路径：${result.file_path}${result.attachment ? '\n原始附件：' + result.attachment : ''}${result.summary ? '\n\n摘要：' + result.summary : ''}`);
      $('#source-file').value=''; $('#file-source-uri').value=''; await loadDocuments(); await loadDashboard(); toast('文件已处理');
    } catch(err) { feedback('#ingest-feedback', err.message, true); }
    finally { button.disabled = false; }
  });
  $$('.subtab').forEach(btn => btn.addEventListener('click', () => {
    $$('.subtab').forEach(x => x.classList.toggle('active', x === btn));
    $('#text-ingest-form').classList.toggle('hidden', btn.dataset.intake !== 'text');
    $('#file-ingest-form').classList.toggle('hidden', btn.dataset.intake !== 'file');
  }));
  $('#library-search-form').addEventListener('submit', event => { event.preventDefault(); const q = $('#library-query').value.trim(); if (q) searchLibrary(q); });
  $('#load-docs').addEventListener('click', loadDocuments);
  $('#reindex-btn').addEventListener('click', async () => { const btn = $('#reindex-btn'); btn.disabled = true; try { const result = await request('/api/reindex',{method:'POST'}); toast(`索引更新：新增 ${result.added}，更新 ${result.updated}，跳过 ${result.skipped}`); await loadDocuments(); await loadDashboard(); } catch(err) { toast(err.message,'error'); } finally { btn.disabled=false; } });
  $('#mail-sync-btn').addEventListener('click', async () => { const btn = $('#mail-sync-btn'); btn.disabled = true; setStatus($('#mail-feedback'),'正在联系 IMAP 服务器…'); try { const result = await request('/api/mail/sync',{method:'POST'}); setStatus($('#mail-feedback'), result.status === 'skipped' ? '未执行：' + (result.reason || '邮箱未配置') : `同步完成：新增 ${result.new_messages || 0} 封邮件，生成 ${result.drafts_created || 0} 份草稿。`); await loadMail(); await loadDashboard(); } catch(err) { setStatus($('#mail-feedback'),err.message); toast(err.message,'error'); } finally { btn.disabled=false; } });
  $('#close-email-detail').addEventListener('click', () => $('#email-detail-panel').classList.add('hidden'));
  $('#save-draft-btn').addEventListener('click', saveDraft);
  $('#send-draft-btn').addEventListener('click', sendDraft);
  async function resolveUncertainDraft(resolution) {
    const id = $('#draft-id').value;
    if (!id || !state.currentDraft || state.currentDraft.status !== 'SEND_UNCERTAIN') return;
    const prompt = resolution === 'sent'
      ? '请先确认你已在邮箱“已发送”文件夹核对到这封邮件。确认后将本地状态标记为已发送，并禁止再次发送。继续？'
      : '请先确认你已在邮箱“已发送”文件夹核对过，确实没有这封邮件。确认后会解锁草稿，允许你再次编辑并主动发送。继续？';
    if (!window.confirm(prompt)) return;
    try {
      await request(`/api/drafts/${encodeURIComponent(id)}/resolve`, {method:'POST', body:JSON.stringify({resolution,confirm:true})});
      toast(resolution === 'sent' ? '已标记为已发送，不可重复发送。' : '已解锁为草稿。请再次检查邮件内容后发送。');
      await loadMail();
      await openDraft(id);
    } catch (err) { toast(err.message, 'error'); }
  }
  $('#resolve-sent-btn').addEventListener('click', () => resolveUncertainDraft('sent'));
  $('#resolve-not-sent-btn').addEventListener('click', () => resolveUncertainDraft('not_sent'));
  $('#draft-form').addEventListener('submit', event => event.preventDefault());
  $('#rule-form').addEventListener('submit', async event => {
    event.preventDefault(); const btn = event.submitter; btn.disabled = true;
    try { const result = await request('/api/rules',{method:'POST',body:JSON.stringify({title:$('#rule-title').value.trim(),body:$('#rule-body').value.trim()})}); feedback('#rule-feedback',`${result.message}\n文件：${result.file_path}`); $('#rule-title').value=''; $('#rule-body').value=''; await loadRules(); await loadDashboard(); toast('长期规则已保存'); }
    catch(err) { feedback('#rule-feedback',err.message,true); }
    finally { btn.disabled=false; }
  });
  $('#refresh-activity').addEventListener('click',loadActivity);

  async function loadAll() {
    await loadDashboard();
    if (state.activeView === 'library') await loadDocuments();
    if (state.activeView === 'mail') await loadMail();
    if (state.activeView === 'rules') await loadRules();
    if (state.activeView === 'activity') await loadActivity();
  }
  async function start() {
    try {
      const canContinue = await loadHealth();
      if (!canContinue) return;
      hideLogin();
      await loadAll();
      if ('serviceWorker' in navigator && location.protocol.startsWith('http')) navigator.serviceWorker.register('/service-worker.js').catch(() => {});
    } catch (err) {
      $('#runtime-indicator').textContent = '后台未连接';
      $('#runtime-indicator').className = 'status-pill warn';
      toast(err.message, 'error');
    }
  }
  start();
})();
