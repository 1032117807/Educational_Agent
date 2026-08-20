(() => {
  const nativeFetch = window.fetch.bind(window);
  const request = async (path, options = {}) => {
    const response = await fetch(`/v1${path}`, {
      ...options,
      headers: { Authorization: `Bearer ${state.token}`, ...(options.headers || {}) },
    });
    if (response.status === 204) return null;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  };

  const text = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  let dialog;
  let pendingResponse;

  const activityIcon = kind => ({ context: '▣', plan: '◇', think: '◎', generate: '✦', tool: '⌁', complete: '✓' }[kind] || '•');
  const activityLabel = value => ({
    'Context loaded': '上下文注入', 'Capability plan': '能力规划', 'Preparing response': '整理方案',
    'Generating response': '生成回复', 'Run complete': '本次运行完成',
    'Tool: learning data': '工具调用：学习数据', 'Tool: web search': '工具调用：网页搜索',
  }[value] || value);
  const appendActivity = payload => {
    const root = document.querySelector('#agent-messages');
    if (!root || !payload) return;
    let card = root.querySelector('.agent-trace[data-live="true"]');
    if (!card) {
      card = document.createElement('article'); card.className = 'agent-message assistant agent-trace'; card.dataset.live = 'true';
      card.innerHTML = '<strong>Agent 运行过程</strong><div class="agent-trace-list"></div>';
      root.appendChild(card);
    }
    const key = payload.key || payload.kind || payload.label || 'step';
    let row = card.querySelector(`[data-activity-key="${CSS.escape(String(key))}"]`);
    if (!row) row = document.createElement('div');
    row.dataset.activityKey = String(key);
    row.className = `agent-trace-row ${text(payload.state || 'running')}`;
    const icon = document.createElement('span'); icon.className = 'agent-trace-icon'; icon.textContent = activityIcon(payload.kind);
    const label = document.createElement('b'); label.textContent = activityLabel(payload.label || '运行步骤');
    const detail = document.createElement('span'); detail.className = 'agent-trace-detail'; detail.textContent = payload.detail || '';
    row.replaceChildren(icon, label, detail);
    if (!row.parentElement) card.querySelector('.agent-trace-list').appendChild(row);
    if (payload.kind === 'complete') card.dataset.live = 'false';
    root.scrollTop = root.scrollHeight;
  };

  const deferAssistantResponse = () => {
    const root = document.querySelector('#agent-messages');
    pendingResponse = root?.querySelector('.agent-message.assistant.thinking') || null;
    pendingResponse?.classList.add('agent-response-pending');
  };
  const revealAssistantResponse = () => {
    pendingResponse?.classList.remove('agent-response-pending');
    pendingResponse = null;
  };

  const appendAgentEvent = textValue => {
    const root = document.querySelector('#agent-messages');
    if (!root) return;
    const message = document.createElement('article');
    message.className = 'agent-message assistant';
    message.innerHTML = '<strong>Learning Agent</strong><div></div>';
    message.querySelector('div').textContent = textValue;
    root.appendChild(message); root.scrollTop = root.scrollHeight;
  };

  const appendSearchResults = payload => {
    const results = payload?.summary?.results;
    const root = document.querySelector('#agent-messages');
    if (!root || !Array.isArray(results) || !results.length) return;
    const message = document.createElement('article');
    message.className = 'agent-message assistant agent-search-results';
    const title = document.createElement('strong'); title.textContent = '可用资料来源'; message.appendChild(title);
    results.slice(0, 5).forEach((item, index) => {
      if (!item?.url) return;
      const row = document.createElement('div'); row.className = 'agent-source-row'; row.dataset.sourceUrl = item.url;
      const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = `${index + 1}. ${item.title || item.url}`;
      const detail = document.createElement('small'); detail.textContent = '正在由 Agent 解析来源内容与课程匹配度...';
      const importButton = document.createElement('button'); importButton.type = 'button'; importButton.className = 'secondary agent-import-source'; importButton.textContent = '下载并存入课程知识库';
      importButton.onclick = async () => {
        const course = document.querySelector('#agent-course')?.value;
        if (!course) { flash('请先选择课程，再导入资料'); return; }
        importButton.disabled = true; importButton.textContent = '正在下载并建立索引...';
        try {
          const result = await request(`/agent/sessions/${state.agentSessionId}/resources/import-url`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: item.url, course_id: Number(course), confirmed: true }) });
          appendAgentEvent(`已将资料存入课程知识库，资源 #${result.resource_id} 正在建立索引。`);
          importButton.textContent = '已提交索引';
        } catch (error) { importButton.disabled = false; importButton.textContent = '下载并存入课程知识库'; appendAgentEvent(`资料导入失败：${error.message}`); }
      };
      row.append(link, detail, importButton); message.appendChild(row);
    });
    root.appendChild(message); root.scrollTop = root.scrollHeight;
  };

  const applySourceSummaries = payload => {
    (payload?.items || []).forEach(item => {
      const row = document.querySelector(`.agent-source-row[data-source-url="${CSS.escape(item.url || '')}"]`);
      const detail = row?.querySelector('small');
      if (detail) detail.textContent = [item.summary, item.recommendation].filter(Boolean).join(' ');
    });
  };

  const appendToolFailure = payload => {
    if (!payload?.name || !payload?.error) return;
    appendAgentEvent(`${payload.name} 未能完成：${payload.error}`);
  };

  const startWebCodingAgent = async () => {
    const root = document.querySelector('#agent-messages');
    const userMessages = root?.querySelectorAll('.agent-message.user') || [];
    const requestText = userMessages.length ? userMessages[userMessages.length - 1].querySelector('div')?.textContent?.trim() : '';
    if (!root || !requestText || !state.agentSessionId) return;
    appendAgentEvent('Coding Agent 正在生成方案并校验代码，请稍候...');
    try {
      const course = document.querySelector('#agent-course')?.value;
      const created = await request(`/agent/sessions/${state.agentSessionId}/coding/proposals`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: requestText, course_id: course ? Number(course) : null }),
      });
      const card = document.createElement('article'); card.className = 'agent-message assistant agent-coding-proposal';
      const title = document.createElement('strong'); title.textContent = `Coding Agent: ${created.proposal.title}`;
      const detail = document.createElement('div'); detail.textContent = `已生成并校验代码方案。\n${created.proposal.explanation}\n预期结果：${created.proposal.expected_output || '输出 JSON 结果'}`;
      const steps = document.createElement('ol'); steps.className = 'agent-coding-steps';
      ['生成代码方案', '校验受限能力', '等待沙箱执行'].forEach(label => { const item = document.createElement('li'); item.textContent = label; steps.appendChild(item); });
      const code = document.createElement('details'); code.className = 'agent-code-preview';
      const summary = document.createElement('summary'); summary.textContent = '查看生成的临时代码';
      const pre = document.createElement('pre'); pre.textContent = created.proposal.python_code || '(代码内容为空)'; code.append(summary, pre);
      const run = document.createElement('button'); run.type = 'button'; run.className = 'primary'; run.textContent = '运行隔离测试';
      run.onclick = async () => {
        run.disabled = true; run.textContent = '正在运行...'; steps.children[2].textContent = '正在调用 coding.run_python 沙箱';
        try {
          const outcome = await request(`/agent/sessions/${state.agentSessionId}/coding/proposals/${created.id}/run`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true }),
          });
          const result = outcome.result || {}; const output = String(result.stdout || result.stderr || '任务完成');
          steps.children[2].textContent = outcome.status === 'completed' ? '沙箱执行完成，已读取输出' : '沙箱执行失败，已读取错误';
          detail.textContent = `${outcome.summary || '运行结束'}\n${output}`; run.textContent = outcome.status === 'completed' ? '测试已完成' : '测试失败';
        } catch (error) { detail.textContent = `运行失败：${error.message}`; run.disabled = false; run.textContent = '重新运行隔离测试'; }
      };
      card.append(title, steps, code, detail, run); root.appendChild(card); root.scrollTop = root.scrollHeight;
    } catch (error) { appendAgentEvent(`Coding Agent 方案生成失败：${error.message}`); }
  };

  const reportLatestCodingStatus = async () => {
    const root = document.querySelector('#agent-messages');
    const users = root?.querySelectorAll('.agent-message.user') || [];
    const message = users.length ? users[users.length - 1].textContent || '' : '';
    if (!/生成成功|执行成功|运行结果|测试结果|代码状态/.test(message) || !state.agentSessionId) return;
    try {
      const latest = await request(`/agent/sessions/${state.agentSessionId}/coding/proposals/latest`);
      if (latest.status === 'not_found') { appendAgentEvent('当前会话没有可执行的 Coding Agent 方案。请先提交具体的编程或 Skill 实现请求。'); return; }
      const result = latest.result || {}; const output = String(result.stdout || result.stderr || latest.error || '尚未执行');
      appendAgentEvent(`Coding Agent 状态：${latest.status}\n${latest.proposal?.title || ''}\n${output}`);
    } catch (error) { appendAgentEvent(`无法读取 Coding Agent 状态：${error.message}`); }
  };

  const updateRunPhase = payload => {
    const root = document.querySelector('#agent-messages');
    if (!root || !payload) return;
    let pending = root.querySelector('.agent-run-status');
    if (!pending) {
      pending = document.createElement('article'); pending.className = 'agent-message assistant agent-run-status thinking';
      pending.innerHTML = '<strong>Learning Agent</strong><div></div>'; root.appendChild(pending);
    }
    const body = pending.querySelector('div');
    if (!body) return;
    const seconds = ((Number(payload.elapsed_ms) || 0) / 1000).toFixed(1);
    body.innerHTML = `<span class="agent-phase-spinner" aria-hidden="true"></span><span>${text(payload.label || 'Agent is working')}</span><span class="agent-phase-time">${seconds}s</span>`;
    if (payload.state === 'completed' && payload.name === 'execution') {
      pending.classList.remove('thinking'); pending.classList.add('complete');
    }
    root.scrollTop = root.scrollHeight;
  };

  const appendConfirmation = payload => {
    const root = document.querySelector('#agent-messages');
    if (!root || !payload?.tool_name) return;
    const message = document.createElement('article');
    message.className = 'agent-message assistant agent-confirmation';
    const label = document.createElement('div');
    label.textContent = payload.message || 'This Agent action requires confirmation.';
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'secondary';
    button.textContent = `Review and confirm: ${payload.action || payload.tool_name}`;
    button.onclick = () => showTools({ tool_name: payload.tool_name, arguments: payload.arguments || {} });
    message.append(label, button); root.appendChild(message); root.scrollTop = root.scrollHeight;
  };

  const appendLearningLaunch = payload => {
    const root = document.querySelector('#agent-messages');
    if (!root || !state.agentSessionId) return;
    const card = document.createElement('article');
    card.className = 'agent-message assistant agent-confirmation';
    card.innerHTML = `<strong>已识别为完整学习启动</strong><div>将创建目标、生成具体计划、安排每日任务，并为课程生成练习题。</div><button type="button" class="primary">确认并开始</button>`;
    card.querySelector('button').onclick = async () => {
      const button = card.querySelector('button'); button.disabled = true; button.textContent = '正在创建目标和任务...';
      try {
        const result = await request(`/agent/sessions/${state.agentSessionId}/learning-launch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: payload.title || payload.request.slice(0, 120), request: payload.request, course_id: payload.course_id || null, target_date: payload.target_date, weekly_minutes: payload.weekly_minutes || 420, question_count: payload.question_count || 5, vocabulary_count: 10 }) });
        card.querySelector('div').textContent = `目标已创建，计划任务和题目正在生成。目标日期：${result.target_date}`;
        button.textContent = '已开始';
        if (result.plan_job_id) watchJob(result.plan_job_id);
        if (result.question_job_id) watchJob(result.question_job_id);
        if (result.vocabulary_job_id) watchJob(result.vocabulary_job_id);
      } catch (error) { button.disabled = false; button.textContent = '重试'; card.querySelector('div').textContent = `启动失败：${error.message}`; }
    };
    root.appendChild(card); root.scrollTop = root.scrollHeight;
    if (payload.auto_confirm) setTimeout(() => card.querySelector('button')?.click(), 80);
  };

  const appendDiagnosticLaunch = payload => {
    const root = document.querySelector('#agent-messages');
    const sessionId = state.agentSessionId;
    if (!root || !sessionId) return;
    const course = document.querySelector('#agent-course');
    const courseId = payload.course_id || (course?.value ? Number(course.value) : null);
    const card = document.createElement('article'); card.className = 'agent-message assistant agent-confirmation';
    card.innerHTML = `<strong>已准备好薄弱点诊断</strong><div>${courseId ? '将生成诊断题并自动打开练习。' : '请选择课程后开始诊断。'}</div><button type="button" class="primary">开始诊断</button>`;
    const button = card.querySelector('button');
    button.onclick = async () => {
      const selectedCourse = course?.value ? Number(course.value) : courseId;
      // Diagnostics may bootstrap a course from the learner's request.
      button.disabled = true; button.textContent = '正在生成诊断题...';
      try { const result = await request(`/agent/sessions/${sessionId}/diagnostic-launch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request: payload.request, course_id: selectedCourse || null, count: payload.count || 20 }) }); card.querySelector('div').textContent = '诊断题已提交，生成完成后会自动打开练习。'; button.textContent = '已开始'; watchJob(result.job_id, '诊断练习'); }
      catch (error) { button.disabled = false; button.textContent = '重试'; card.querySelector('div').textContent = `启动失败：${error.message}`; }
    };
    root.appendChild(card); root.scrollTop = root.scrollHeight;
    setTimeout(() => button.click(), 80);
  };

  const appendAgentDownload = payload => {
    const root = document.querySelector('#agent-messages');
    const message = root?.querySelector('.agent-message.assistant:last-child');
    if (!message || !payload?.url) return;
    const body = message.querySelector('div');
    if (!body || body.querySelector(`[data-download-url="${CSS.escape(payload.url)}"]`)) return;
    const link = document.createElement('a');
    link.className = 'download-link'; link.href = payload.url;
    link.dataset.downloadUrl = payload.url; link.textContent = payload.label || 'Download report';
    link.onclick = async event => {
      event.preventDefault();
      try {
        const response = await nativeFetch(payload.url, { headers: { Authorization: `Bearer ${state.token}` } });
        if (!response.ok) throw new Error('Download failed');
        const blob = await response.blob(); const anchor = document.createElement('a');
        anchor.href = URL.createObjectURL(blob); anchor.download = 'learning-report.md';
        document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(anchor.href);
      } catch (error) { flash(error.message); }
    };
    body.append(document.createElement('br'), link);
  };

  const appendHumanInput = payload => {
    const root = document.querySelector('#agent-messages');
    const form = document.querySelector('#agent-form');
    const input = form?.querySelector('[name="message"]');
    if (!root || !form || !input || !payload?.question) return;
    const card = document.createElement('article');
    card.className = 'agent-message assistant agent-human-input';
    const question = document.createElement('div'); question.textContent = payload.question;
    const choices = document.createElement('div'); choices.className = 'agent-choice-list';
    (payload.options || []).forEach(option => {
      if (!option?.label || !option?.message) return;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary';
      button.textContent = option.label;
      button.onclick = () => { input.value = option.message; form.requestSubmit(); };
      choices.appendChild(button);
    });
    const custom = document.createElement('input'); custom.type = 'text'; custom.maxLength = 4000;
    custom.placeholder = '输入你的处理方式或资料链接';
    const send = document.createElement('button'); send.type = 'button'; send.className = 'primary'; send.textContent = '发送';
    send.onclick = () => { if (!custom.value.trim()) return; input.value = custom.value.trim(); form.requestSubmit(); };
    card.append(question, choices, custom, send); root.appendChild(card); root.scrollTop = root.scrollHeight;
  };

  const watchJob = async jobId => {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      try {
        const job = await request(`/jobs/${jobId}`);
        appendActivity({ kind: 'execution', key: `job-${jobId}`, state: job.status === 'completed' ? 'completed' : job.status === 'failed' ? 'failed' : 'running', label: '执行后台任务', detail: job.status === 'completed' ? '后台任务已完成' : job.status === 'failed' ? (job.error || '后台任务失败') : 'Worker 正在处理' });
        if (job.status === 'completed') {
          const result = job.result || {};
          const root = document.querySelector('#agent-messages');
          if (root) {
            const card = document.createElement('article'); card.className = 'agent-message assistant agent-result-card';
            const parts = [];
            if (result.course_created) parts.push(`课程已创建：#${result.course_id}`);
            if (result.goal_id) parts.push(`学习目标已创建：#${result.goal_id}`);
            if (Number(result.created_task_count || 0)) parts.push(`已写入 ${result.created_task_count} 个学习任务`);
            if (Number(result.count || 0)) parts.push(`已生成 ${result.count} 道练习题`);
            if (result.practice_session_id) parts.push('练习已准备好，可直接开始作答');
            if (parts.length) { card.innerHTML = `<strong>执行结果</strong><div>${text(parts.join('；'))}</div>`; root.appendChild(card); root.scrollTop = root.scrollHeight; }
          }
          if (result.practice_session_id) window.dispatchEvent(new CustomEvent('practice-ready', { detail: result }));
          const pending = (result.actions || []).filter(action => action.status === 'needs_confirmation' || action.status === 'needs_input');
          if (pending.length) appendAgentEvent(pending.map(action => action.detail || action.feature).join('\n'));
          const planned = (result.actions || []).filter(action => action.status === 'completed' && action.result);
          const taskCount = planned.reduce((sum, action) => sum + Number(action.result?.created_task_count || 0), 0);
          if (taskCount) appendAgentEvent(`已生成并写入 ${taskCount} 个每日学习任务。请打开 Tasks 查看并完成今日任务。`);
          if (Number(result.count || 0) || taskCount) window.dispatchEvent(new CustomEvent('learning-data-updated', { detail: result }));
          if (result.practice_session_id) window.dispatchEvent(new CustomEvent('practice-ready', { detail: result }));
          return;
        }
        if (job.status === 'failed') {
          appendAgentEvent(`Execution failed: ${job.error || job.detail || 'Unknown error'}`);
          return;
        }
      } catch (error) { appendAgentEvent(`Unable to read execution status: ${error.message}`); return; }
    }
    appendAgentEvent('Execution is still running. Open Activity to check later.');
  };

  const watchAgentStream = async stream => {
    const reader = stream.getReader(); const decoder = new TextDecoder(); let buffer = '';
    while (true) {
      const part = await reader.read(); if (part.done) return;
      buffer += decoder.decode(part.value, { stream: true });
      const events = buffer.split('\n\n'); buffer = events.pop();
      for (const event of events) {
        const name = event.match(/^event: (.+)$/m)?.[1]; const raw = event.match(/^data: (.+)$/m)?.[1];
        if (!raw) continue;
        try {
          const payload = JSON.parse(raw);
          if (name === 'status') deferAssistantResponse();
          if (name === 'phase') updateRunPhase(payload);
          if (name === 'activity') appendActivity(payload);
          if (name === 'tool' && payload.job_id) watchJob(payload.job_id);
          if (name === 'tool' && payload.name === 'web.search') appendSearchResults(payload);
          if (name === 'tool' && payload.state === 'failed') appendToolFailure(payload);
          if (name === 'sources') applySourceSummaries(payload);
          if (name === 'intent' && (payload.actions || []).includes('meta_code')) startWebCodingAgent();
          if (name === 'intent') reportLatestCodingStatus();
          if (name === 'learning_launch') appendLearningLaunch(payload);
          if (name === 'diagnostic_launch') appendDiagnosticLaunch(payload);
          if (name === 'confirmation') appendConfirmation(payload);
          if (name === 'download') appendAgentDownload(payload);
          if (name === 'human_input') appendHumanInput(payload);
          if (name === 'memory_proposal') {
            const note = payload.content?.note || '';
            if (!confirm(`Save this Agent memory?\n\n${note}`)) continue;
            request('/agent/memories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...payload, confirmed: true }) })
              .then(() => appendAgentEvent('Confirmed memory saved.'))
              .catch(error => appendAgentEvent(`Unable to save memory: ${error.message}`));
          }
          if (name === 'done') revealAssistantResponse();
        } catch (_error) { /* Ignore malformed noncritical events. */ }
      }
    }
  };

  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const url = String(args[0] instanceof Request ? args[0].url : args[0]);
    if (!url.includes('/agent/sessions/') || !url.includes('/messages/stream') || !response.body) return response;
    const [appStream, observerStream] = response.body.tee();
    watchAgentStream(observerStream).catch(() => {});
    return new Response(appStream, { status: response.status, statusText: response.statusText, headers: response.headers });
  };

  const ensureDialog = () => {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.className = 'agent-runtime-dialog';
    document.body.appendChild(dialog);
    return dialog;
  };

  const showMemories = async () => {
    const root = ensureDialog();
    root.innerHTML = `<form method="dialog" class="agent-runtime-head"><h3>Agent memories</h3><button class="icon-button" aria-label="Close" title="Close">&#215;</button></form><div id="runtime-memory-list" class="list"></div><form id="runtime-memory-form" class="form-stack compact-form"><label>Scope<select name="scope"><option value="long_term">Long term</option><option value="course">Course</option></select></label><label>Category<select name="category"><option value="plan_preference">Plan preference</option><option value="goal">Goal</option><option value="weak_point">Weak point</option><option value="learning_pace">Learning pace</option></select></label><label>Memory<input name="content" maxlength="1000" required></label><label>Course ID <input name="course_id" type="number" min="1"></label><button class="primary" type="submit">Save confirmed memory</button></form>`;
    root.showModal();
    const list = root.querySelector('#runtime-memory-list');
    const render = async () => {
      const memories = await request('/agent/memories');
      list.innerHTML = memories.map(memory => `<article class="list-row"><div><strong>${text(memory.category)}</strong><div class="task-meta">${text(memory.scope)} · ${text(JSON.stringify(memory.content))}</div></div><button class="secondary" data-delete-memory="${memory.id}">Delete</button></article>`).join('') || '<p class="task-meta">No confirmed memories.</p>';
      list.querySelectorAll('[data-delete-memory]').forEach(button => button.onclick = async () => {
        if (!confirm('Delete this memory? The Agent will no longer use it.')) return;
        try { await request(`/agent/memories/${button.dataset.deleteMemory}`, { method: 'DELETE' }); await render(); } catch (error) { flash(error.message); }
      });
    };
    try { await render(); } catch (error) { list.textContent = error.message; }
    root.querySelector('#runtime-memory-form').onsubmit = async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target));
      const payload = { scope: values.scope, category: values.category, content: { note: values.content }, confirmed: true };
      if (values.scope === 'course') payload.course_id = Number(values.course_id);
      try { await request('/agent/memories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); event.target.reset(); await render(); } catch (error) { flash(error.message); }
    };
  };

  const showActivity = async () => {
    if (!state.agentSessionId) { flash('Create or select a conversation first.'); return; }
    const root = ensureDialog();
    root.innerHTML = `<form method="dialog" class="agent-runtime-head"><h3>Agent activity</h3><button class="icon-button" aria-label="Close" title="Close">&#215;</button></form><div id="runtime-tool-list" class="list"></div>`;
    root.showModal();
    const list = root.querySelector('#runtime-tool-list');
    try {
      const calls = await request(`/agent/sessions/${state.agentSessionId}/tool-calls`);
      list.innerHTML = calls.map(call => `<article class="list-row"><div><strong>${text(call.tool_name)}</strong><div class="task-meta">${text(call.status)}${call.detail ? ` · ${text(call.detail)}` : ''}</div>${call.error ? `<div class="error-text">${text(call.error)}</div>` : ''}<pre class="agent-tool-output">${text(JSON.stringify(call.output || {}, null, 2))}</pre></div></article>`).join('') || '<p class="task-meta">No tool activity in this conversation.</p>';
    } catch (error) { list.textContent = error.message; }
  };

  const showTools = async (preset = null) => {
    if (!state.agentSessionId) { flash('Create or select a conversation first.'); return; }
    const root = ensureDialog();
    root.innerHTML = `<form method="dialog" class="agent-runtime-head"><h3>Agent tools</h3><button class="icon-button" aria-label="Close" title="Close">&#215;</button></form><form id="runtime-tool-form" class="form-stack compact-form"><label>Tool<select name="tool_name" id="runtime-tool-select"></select></label><p id="runtime-tool-description" class="task-meta"></p><label id="runtime-companion-row" class="hidden">Desktop Companion ID<input name="companion_id" id="runtime-companion-id" maxlength="120" placeholder="my-desktop-01"></label><label>Arguments (JSON)<textarea name="arguments" rows="6">{}</textarea></label><label class="runtime-confirm"><input name="confirmed" type="checkbox"> I confirm this operation</label><button class="primary" type="submit">Run tool</button></form><pre id="runtime-tool-result" class="agent-tool-output"></pre>`;
    root.showModal();
    const select = root.querySelector('#runtime-tool-select');
    const description = root.querySelector('#runtime-tool-description');
    const confirm = root.querySelector('.runtime-confirm');
    const companionRow = root.querySelector('#runtime-companion-row');
    const companionId = root.querySelector('#runtime-companion-id');
    companionId.value = localStorage.getItem('learning.desktopCompanionId') || '';
    let tools = [];
    try {
      tools = await request('/agent/tools');
      select.innerHTML = tools.map(tool => `<option value="${text(tool.name)}">${text(tool.name)}</option>`).join('');
      const sync = () => {
        const tool = tools.find(item => item.name === select.value);
        description.textContent = tool ? tool.description : '';
        confirm.classList.toggle('hidden', !tool?.requires_confirmation);
        companionRow.classList.toggle('hidden', tool?.execution_target !== 'desktop_companion');
        confirm.querySelector('input').checked = false;
      };
      select.onchange = sync; sync();
      if (preset?.tool_name && tools.some(item => item.name === preset.tool_name)) {
        select.value = preset.tool_name; sync();
        root.querySelector('[name="arguments"]').value = JSON.stringify(preset.arguments || {}, null, 2);
      }
    } catch (error) { description.textContent = error.message; return; }
    root.querySelector('#runtime-tool-form').onsubmit = async event => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(event.target));
      let arguments;
      try { arguments = JSON.parse(data.arguments || '{}'); } catch (_error) { flash('Arguments must be valid JSON.'); return; }
      const tool = tools.find(item => item.name === data.tool_name);
      const confirmed = data.confirmed === 'on';
      if (tool?.requires_confirmation && !confirmed) { flash('This tool requires confirmation.'); return; }
      if (tool?.execution_target === 'desktop_companion') {
        const companion = String(data.companion_id || '').trim();
        if (!companion) { flash('Desktop Companion ID is required.'); return; }
        arguments.companion_id = companion;
        localStorage.setItem('learning.desktopCompanionId', companion);
      }
      const output = root.querySelector('#runtime-tool-result'); output.textContent = 'Running...';
      try {
        const result = await request(`/agent/sessions/${state.agentSessionId}/tools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool_name: data.tool_name, arguments, confirmed }) });
        output.textContent = JSON.stringify(result.result, null, 2);
      } catch (error) { output.textContent = `Error: ${error.message}`; }
    };
  };

  window.addEventListener('DOMContentLoaded', () => {
    const heading = document.querySelector('#ai-view .section-head');
    if (!heading || document.querySelector('#agent-memories')) return;
    const button = document.createElement('button');
    button.id = 'agent-memories'; button.className = 'secondary'; button.type = 'button'; button.textContent = 'Memories';
    button.onclick = showMemories;
    heading.insertBefore(button, heading.querySelector('#new-agent-session'));
    const activity = document.createElement('button');
    activity.id = 'agent-activity'; activity.className = 'secondary'; activity.type = 'button'; activity.textContent = 'Activity';
    activity.onclick = showActivity;
    heading.insertBefore(activity, heading.querySelector('#new-agent-session'));
    const tools = document.createElement('button');
    tools.id = 'agent-tools'; tools.className = 'secondary'; tools.type = 'button'; tools.textContent = 'Tools';
    tools.onclick = showTools;
    heading.insertBefore(tools, heading.querySelector('#new-agent-session'));
  });
})();
