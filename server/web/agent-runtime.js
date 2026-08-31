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
  window.resetAgentRuntime = () => {
    pendingResponse = null;
    if (dialog) {
      dialog.close?.();
      dialog.remove();
      dialog = null;
    }
  };

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
    const key = payload.key || payload.call_id || (payload.tool_name ? `tool-${payload.tool_name}-${payload.sequence || Date.now()}` : payload.kind || payload.label || 'step');
    let row = card.querySelector(`[data-activity-key="${CSS.escape(String(key))}"]`);
    if (!row) row = document.createElement('div');
    row.dataset.activityKey = String(key);
    row.className = `agent-trace-row ${text(payload.state || 'running')}`;
    const icon = document.createElement('span'); icon.className = 'agent-trace-icon'; icon.textContent = activityIcon(payload.kind);
    const label = document.createElement('b'); label.textContent = payload.tool_name || activityLabel(payload.label || '运行步骤');
    const meta = [payload.state, payload.duration_ms != null ? `${payload.duration_ms} ms` : '', payload.result_summary || ''].filter(Boolean).join(' · ');
    const detail = document.createElement('span'); detail.className = 'agent-trace-detail'; detail.textContent = [payload.detail || '', meta].filter(Boolean).join(' | ');
    if (payload.error) detail.textContent += ` | 错误：${payload.error}`;
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

  const setLearningWorkflowStatus = (stateName, detail, action = null) => {
    const root = document.querySelector('#agent-messages');
    if (!root) return;
    let card = root.querySelector('#agent-learning-workflow-status');
    if (!card) {
      card = document.createElement('article');
      card.id = 'agent-learning-workflow-status';
      card.className = 'agent-message assistant agent-result-card';
      root.appendChild(card);
    }
    card.innerHTML = `<strong>学习任务流程：${text(stateName)}</strong><div>${text(detail)}</div>`;
    if (action) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary';
      button.textContent = action.label; button.onclick = action.onClick; card.appendChild(button);
    }
    root.scrollTop = root.scrollHeight;
  };

  const appendSearchResults = (payload, rootOverride = null, anchor = null) => {
    const results = payload?.summary?.results;
    const root = rootOverride || document.querySelector('#agent-messages');
    if (!root || !Array.isArray(results) || !results.length) return;
    const message = document.createElement('article');
    message.className = 'agent-message assistant agent-search-results';
    const title = document.createElement('strong'); title.textContent = '资料检索子 Agent：可用资料来源'; message.appendChild(title);
    results.slice(0, 5).forEach((item, index) => {
      if (!item?.url) return;
      const row = document.createElement('div'); row.className = 'agent-source-row'; row.dataset.sourceUrl = item.url;
      const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = `${index + 1}. ${item.title || item.url}`;
      const detail = document.createElement('small'); detail.textContent = '正在由 Agent 解析来源内容与课程匹配度...';
      const importButton = document.createElement('button'); importButton.type = 'button'; importButton.className = 'secondary agent-import-source'; importButton.textContent = '导入资料（自动解析 PDF）';
      importButton.onclick = async () => {
        const course = document.querySelector('#agent-course')?.value || state.activeCourseId;
        const userMessages = document.querySelectorAll('.agent-message.user div');
        const learningRequest = userMessages.length ? userMessages[userMessages.length - 1].textContent : '';
        importButton.disabled = true; importButton.textContent = '资料检索子 Agent 正在下载并建立索引...';
        try {
          const result = await request(`/agent/sessions/${state.agentSessionId}/resources/import-url`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: item.url, course_id: course ? Number(course) : null, request: learningRequest }) });
          appendAgentEvent(`资料检索子 Agent 已将资料存入课程知识库，资源 #${result.resource_id} 正在建立索引。`);
          importButton.textContent = '已提交索引';
        } catch (error) { importButton.disabled = false; importButton.textContent = '导入资料（自动解析 PDF）'; appendAgentEvent(`资料检索 Agent 未能从“${item.title || '该来源'}”找到可导入的学习文件；该链接已保留为参考页面，不会进入课程索引。`); }
      };
      row.append(link, detail, importButton); message.appendChild(row);
    });
    if (anchor?.parentElement === root) anchor.insertAdjacentElement('afterend', message);
    else root.appendChild(message);
    root.scrollTop = root.scrollHeight;
    return message;
  };

  const appendBrowserScreenshot = payload => {
    const data = payload?.summary || {};
    if (!data.image_base64) return;
    const root = document.querySelector('#agent-messages'); if (!root) return;
    const message = document.createElement('article'); message.className = 'agent-message assistant agent-browser-screenshot';
    const title = document.createElement('strong'); title.textContent = `网页截图：${data.title || data.url || '公开网页'}`;
    const image = document.createElement('img'); image.src = `data:${data.mime_type || 'image/png'};base64,${data.image_base64}`; image.alt = title.textContent; image.loading = 'lazy';
    const source = document.createElement('small'); source.textContent = data.url || '';
    message.append(title, image, source); root.appendChild(message); root.scrollTop = root.scrollHeight;
  };

  const applySourceSummaries = (payload, rootOverride = null) => {
    const root = rootOverride || document;
    (payload?.items || []).forEach(item => {
      const row = root.querySelector(`.agent-source-row[data-source-url="${CSS.escape(item.url || '')}"]`);
      const detail = row?.querySelector('small');
      if (detail) detail.textContent = [item.summary, item.recommendation].filter(Boolean).join(' ');
    });
  };

  window.restoreAgentSourceResults = (root, messages) => {
    (messages || []).forEach(item => {
      const sources = item?.web_sources;
      if (!sources || !Array.isArray(sources.results) || !sources.results.length) return;
      const anchor = root.querySelector(`[data-agent-message-id="${CSS.escape(String(item.id))}"]`);
      const card = appendSearchResults({ summary: { results: sources.results } }, root, anchor);
      if (card) applySourceSummaries({ items: sources.summaries || [] }, card);
    });
  };

  const appendToolFailure = payload => {
    if (!payload?.name || !payload?.error) return;
    appendAgentEvent(`${payload.name} 未能完成：${payload.error}`);
  };

  const autoImportMaterials = async payload => {
    let courseId = Number(payload?.course_id || document.querySelector('#agent-course')?.value || state.activeCourseId || 0);
    const items = Array.isArray(payload?.items) ? payload.items : [];
    if (!state.agentSessionId || !items.length) return;
    const userMessages = document.querySelectorAll('.agent-message.user div');
    const learningRequest = payload?.request || (userMessages.length ? userMessages[userMessages.length - 1].textContent : '');
    setLearningWorkflowStatus('正在导入资料', `资料检索 Agent 正在处理 ${items.length} 个候选来源。`);
    appendAgentEvent(`资料检索 Agent 正在自动下载 ${items.length} 份学习文件，并关联到匹配课程；没有匹配课程时会新建课程。`);
    let imported = 0;
    for (const item of items) {
      try {
        const result = await request(`/agent/sessions/${state.agentSessionId}/resources/import-url`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: item.url, course_id: courseId || null, request: learningRequest }) });
        courseId = Number(result.course_id || courseId);
        if (result.course_created) appendAgentEvent('已根据学习主题创建课程，并开始为资料建立索引。');
        appendAgentEvent(`已下载并排队索引：${item.title || item.url}（资源 #${result.resource_id}）。`);
        imported += 1;
        setLearningWorkflowStatus('正在建立索引', '资料已导入课程知识库。索引完成后会自动生成题目和每日任务，并在这里显示最终结果。');
        if (result.job_id) watchJob(result.job_id);
      } catch (_error) { appendAgentEvent(`资料检索 Agent 未从“${item.title || '候选来源'}”解析到可导入 PDF，已跳过该网页来源。`); }
    }
    if (!imported) {
      setLearningWorkflowStatus('流程已暂停', '没有从候选网页解析到可导入的 PDF，因此不能基于资料出题或编排每日任务。请上传本地学习资料后继续。', {
        label: '上传本地资料', onClick: () => openView('resources'),
      });
      appendAgentEvent('本次流程已结束：暂未找到可导入 PDF，未生成题目或每日任务。');
    }
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
      const isDiagram = created.proposal.artifact_type === 'mermaid';
      const source = created.proposal[isDiagram ? 'mermaid_code' : 'python_code'] || '';
      const summary = document.createElement('summary'); summary.textContent = isDiagram ? 'Mermaid 图表源代码' : '查看生成的临时代码';
      const pre = document.createElement('pre'); pre.textContent = source || '(代码内容为空)'; code.append(summary, pre);
      const workspace = document.createElement('section'); workspace.className = 'agent-coding-workspace';
      const filename = document.createElement('input'); filename.type = 'text'; filename.maxLength = 180;
      filename.value = isDiagram ? 'diagram.mmd' : 'analysis.py'; filename.setAttribute('aria-label', 'Workspace filename');
      const editor = document.createElement('textarea'); editor.className = 'agent-workspace-editor'; editor.spellcheck = false; editor.value = source;
      const fileList = document.createElement('div'); fileList.className = 'agent-workspace-files';
      const output = document.createElement('pre'); output.className = 'agent-workspace-output';
      const diagramPreview = document.createElement('div'); diagramPreview.className = 'agent-diagram-preview';
      const renderDiagram = () => {
        if (!isDiagram) return;
        const nodes = new Map(); const edges = [];
        const addNode = raw => {
          const match = raw.trim().match(/^([A-Za-z0-9_-]+)\s*(?:\[([^\]]+)\]|\(([^)]+)\)|\{([^}]+)\})?$/);
          if (!match) return null;
          const id = match[1]; if (!nodes.has(id)) nodes.set(id, (match[2] || match[3] || match[4] || id).trim().slice(0, 60));
          return id;
        };
        editor.value.split(/\r?\n/).slice(0, 32).forEach(line => {
          const match = line.match(/^\s*(.+?)\s+--\s+.+?\s+-->\s*(.+?)\s*$/) || line.match(/^\s*(.+?)\s*(?:-->|---)\s*(.+?)\s*$/); if (!match) return;
          const from = addNode(match[1]); const to = addNode(match[2].replace(/^\|[^|]*\|\s*/, ''));
          if (from && to) edges.push([from, to]);
        });
        diagramPreview.replaceChildren();
        if (!nodes.size) { diagramPreview.textContent = '图表源码还没有可预览的流程节点。'; return; }
        const entries = [...nodes.entries()]; const width = 760; const rowHeight = 86; const height = Math.max(160, Math.ceil(entries.length / 2) * rowHeight + 40);
        const positions = new Map(entries.map(([id], index) => [id, { x: 240 + (index % 2) * 280, y: 58 + Math.floor(index / 2) * rowHeight }]));
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Coding Agent 生成的流程图'); svg.classList.add('agent-diagram-image');
        const defs = document.createElementNS(svg.namespaceURI, 'defs'); const marker = document.createElementNS(svg.namespaceURI, 'marker');
        marker.setAttribute('id', 'agent-arrow'); marker.setAttribute('viewBox', '0 0 10 10'); marker.setAttribute('refX', '9'); marker.setAttribute('refY', '5'); marker.setAttribute('markerWidth', '7'); marker.setAttribute('markerHeight', '7'); marker.setAttribute('orient', 'auto');
        const arrow = document.createElementNS(svg.namespaceURI, 'path'); arrow.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z'); arrow.setAttribute('fill', '#4386a4'); marker.appendChild(arrow); defs.appendChild(marker); svg.appendChild(defs);
        edges.forEach(([from, to]) => { const a = positions.get(from); const b = positions.get(to); const line = document.createElementNS(svg.namespaceURI, 'line'); line.setAttribute('x1', String(a.x)); line.setAttribute('y1', String(a.y + 21)); line.setAttribute('x2', String(b.x)); line.setAttribute('y2', String(b.y - 21)); line.setAttribute('stroke', '#4386a4'); line.setAttribute('stroke-width', '2'); line.setAttribute('marker-end', 'url(#agent-arrow)'); svg.appendChild(line); });
        entries.forEach(([id, label]) => { const point = positions.get(id); const group = document.createElementNS(svg.namespaceURI, 'g'); const rect = document.createElementNS(svg.namespaceURI, 'rect'); rect.setAttribute('x', String(point.x - 105)); rect.setAttribute('y', String(point.y - 22)); rect.setAttribute('width', '210'); rect.setAttribute('height', '44'); rect.setAttribute('rx', '5'); rect.setAttribute('fill', '#edf7fb'); rect.setAttribute('stroke', '#4386a4'); const text = document.createElementNS(svg.namespaceURI, 'text'); text.setAttribute('x', String(point.x)); text.setAttribute('y', String(point.y + 5)); text.setAttribute('text-anchor', 'middle'); text.setAttribute('fill', '#18394a'); text.setAttribute('font-size', '14'); text.textContent = label; group.append(rect, text); svg.appendChild(group); });
        diagramPreview.appendChild(svg);
        const downloads = document.createElement('div'); downloads.className = 'agent-diagram-downloads';
        const svgLink = document.createElement('a'); svgLink.className = 'secondary'; svgLink.textContent = '下载 SVG'; svgLink.download = 'diagram.svg';
        svgLink.href = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml;charset=utf-8' }));
        const pngLink = document.createElement('a'); pngLink.className = 'secondary'; pngLink.textContent = '下载 PNG'; pngLink.download = 'diagram.png'; pngLink.href = '#';
        pngLink.onclick = event => { event.preventDefault(); const image = new Image(); image.onload = () => { const canvas = document.createElement('canvas'); canvas.width = width * 2; canvas.height = height * 2; const context = canvas.getContext('2d'); context.scale(2, 2); context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height); context.drawImage(image, 0, 0); const link = document.createElement('a'); link.download = 'diagram.png'; link.href = canvas.toDataURL('image/png'); link.click(); }; image.src = svgLink.href; };
        downloads.append(svgLink, pngLink); diagramPreview.appendChild(downloads);
      };
      const invokeTool = async (tool_name, arguments, confirmed = false) => request(`/agent/sessions/${state.agentSessionId}/tools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool_name, arguments, confirmed }) });
      const refreshFiles = async () => {
        try {
          const result = await invokeTool('mcp.list_workspace_files', { relative_path: '.', limit: 100 }); const files = result.result?.files || [];
          fileList.replaceChildren(); if (!files.length) fileList.textContent = '工作区为空。';
          files.forEach(path => {
            const row = document.createElement('div'); row.className = 'agent-workspace-file';
            const open = document.createElement('button'); open.type = 'button'; open.className = 'secondary'; open.textContent = path;
            open.onclick = async () => { const read = await invokeTool('mcp.read_workspace_file', { relative_path: path }); filename.value = path; editor.value = read.result?.content || ''; };
            const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary'; remove.textContent = '删除';
            remove.onclick = async () => { if (!confirm(`删除 ${path}？此操作不可恢复。`)) return; await invokeTool('coding.delete_workspace', { relative_path: path }, true); output.textContent = `已删除 ${path}`; refreshFiles(); };
            row.append(open, remove); fileList.appendChild(row);
          });
        } catch (error) { fileList.textContent = `无法读取工作区：${error.message}`; }
      };
      const save = document.createElement('button'); save.type = 'button'; save.className = 'secondary'; save.textContent = '保存到工作区';
      save.onclick = async () => { const path = filename.value.trim(); if (!path) { output.textContent = '请填写文件名。'; return; } if (!confirm(`将写入工作区文件 ${path}。确认保存？`)) return; try { await invokeTool('coding.write_workspace', { relative_path: path, content: editor.value }, true); output.textContent = `已保存 ${path}`; refreshFiles(); } catch (error) { output.textContent = `保存失败：${error.message}`; } };
      const runSaved = document.createElement('button'); runSaved.type = 'button'; runSaved.className = 'secondary'; runSaved.textContent = '运行已保存的 Python'; runSaved.disabled = isDiagram;
      runSaved.onclick = async () => { try { const result = await invokeTool('coding.run_workspace_python', { relative_path: filename.value.trim() }); output.textContent = String(result.result?.stdout || result.result?.stderr || '运行完成。'); } catch (error) { output.textContent = `运行失败：${error.message}`; } };
      const saveAndRun = document.createElement('button'); saveAndRun.type = 'button'; saveAndRun.className = 'secondary'; saveAndRun.textContent = '保存并运行'; saveAndRun.disabled = isDiagram;
      saveAndRun.onclick = async () => { const path = filename.value.trim(); if (!path) { output.textContent = '请填写文件名。'; return; } if (!confirm(`将保存并运行 ${path}。确认继续？`)) return; try { await invokeTool('coding.write_workspace', { relative_path: path, content: editor.value }, true); const result = await invokeTool('coding.run_workspace_python', { relative_path: path }); output.textContent = String(result.result?.stdout || result.result?.stderr || '运行完成。'); refreshFiles(); } catch (error) { output.textContent = `保存或运行失败：${error.message}`; } };
      editor.addEventListener('input', renderDiagram);
      if (isDiagram) { renderDiagram(); workspace.append(filename, save, editor, diagramPreview, fileList, output); }
      else workspace.append(filename, save, runSaved, saveAndRun, editor, fileList, output);
      refreshFiles();
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
      if (isDiagram) { run.disabled = true; run.textContent = 'Mermaid 图表无需 Python 运行'; }
      card.append(title, steps, code, workspace, detail, run); root.appendChild(card); root.scrollTop = root.scrollHeight;
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

  let runTimerId = null;
  let runStartedAt = 0;
  const formatElapsed = elapsedMs => `${(Math.max(0, elapsedMs) / 1000).toFixed(1)}s`;
  const stopRunTimer = (payload = {}) => {
    if (runTimerId) { clearInterval(runTimerId); runTimerId = null; }
    const root = document.querySelector('#agent-messages');
    const pending = root?.querySelector('.agent-run-status');
    if (!pending) return;
    const elapsed = Number(payload.elapsed_ms) || (runStartedAt ? Date.now() - runStartedAt : 0);
    const time = pending.querySelector('.agent-phase-time');
    if (time) time.textContent = `总耗时 ${formatElapsed(elapsed)}`;
    pending.classList.remove('thinking');
    pending.classList.toggle('waiting', pending.dataset.phaseState === 'waiting');
    pending.classList.toggle('complete', pending.dataset.phaseState !== 'waiting');
    runStartedAt = 0;
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
    const elapsed = Number(payload.elapsed_ms) || 0;
    if (!runStartedAt) runStartedAt = Date.now() - elapsed;
    pending.dataset.phaseState = payload.state || 'running';
    body.innerHTML = `<span class="agent-phase-spinner" aria-hidden="true"></span><span>${text(payload.label || 'Agent is working')}</span><span class="agent-phase-time">${formatElapsed(Date.now() - runStartedAt)}</span>`;
    if (runTimerId) clearInterval(runTimerId);
    runTimerId = setInterval(() => {
      const time = pending.querySelector('.agent-phase-time');
      if (time && runStartedAt) time.textContent = formatElapsed(Date.now() - runStartedAt);
    }, 100);
    if ((payload.state === 'completed' || payload.state === 'waiting') && payload.name === 'execution') stopRunTimer(payload);
    root.scrollTop = root.scrollHeight;
  };

  const appendConfirmation = payload => {
    const root = document.querySelector('#agent-messages');
    if (!root || !payload?.tool_name) return;
    // A learning launch has its own single, direct confirmation button.
    // Never append the legacy tool-dialog confirmation beside it.
    if (root.querySelector('.agent-learning-launch')) return;
    const message = document.createElement('article');
    message.className = 'agent-message assistant agent-confirmation agent-generic-confirmation';
    const labels = { create_goal: '创建学习目标', generate_plan: '生成学习计划', learning_plan: '生成学习计划', start_workflow: '启动学习流程' };
    const actionLabel = labels[payload.action] || labels[payload.tool_name?.replace('agent.', '')] || '执行学习操作';
    const label = document.createElement('div');
    label.innerHTML = `<strong>当前状态：等待你的确认</strong><br>尚未${actionLabel}，也没有写入任何课程或任务。确认后才会继续。`;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'secondary';
    button.textContent = `查看并确认：${actionLabel}`;
    button.onclick = () => showTools({ tool_name: payload.tool_name, arguments: payload.arguments || {} });
    message.append(label, button); root.appendChild(message); root.scrollTop = root.scrollHeight;
  };

  const appendLearningLaunch = (payload, restored = false) => {
    const root = document.querySelector('#agent-messages');
    const course = document.querySelector('#agent-course');
    if (!root || !state.agentSessionId || !payload?.request) return;
    if (root.querySelector('.agent-learning-launch')) return;
    root.querySelectorAll('.agent-generic-confirmation').forEach(item => item.remove());
    const card = document.createElement('article');
    card.className = 'agent-message assistant agent-confirmation agent-learning-launch';
    card.innerHTML = `<strong>已识别为“创建学习任务”</strong><div>正在自动匹配或创建课程，写入学习目标并导入、索引资料。练习题会作为独立任务生成，不会替代学习任务。</div><button type="button" class="primary">正在启动</button>`;
    const button = card.querySelector('button');
    if (payload.status === 'completed') {
      card.querySelector('div').textContent = '已确认完成。学习目标和后续任务已开始创建；运行状态会显示在下方“Agent 运行过程”。';
      button.textContent = '已启动';
      button.disabled = true;
      root.appendChild(card); root.scrollTop = root.scrollHeight;
      return;
    }
    const selectedCourseId = () => Number(course?.value || payload.course_id || state.activeCourseId || 0);
    if (!selectedCourseId()) card.querySelector('div').textContent = '未选择课程：系统会按学习主题匹配已有课程；没有匹配项时自动创建课程。';
    if (restored) card.querySelector('div').textContent = '正在恢复自动学习流程。';
    button.onclick = async () => {
      button.disabled = true; button.textContent = '正在启动...';
      try {
        const courseId = selectedCourseId();
        const result = await request(`/agent/sessions/${state.agentSessionId}/learning-launch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: payload.title || payload.request.slice(0, 120), request: payload.request, course_id: courseId || null, target_date: payload.target_date, weekly_minutes: payload.weekly_minutes || 420, question_count: payload.question_count || 5, vocabulary_count: 10 }) });
        const steps = (result.workflow_steps || []).map(step => `${step.agent}：${step.detail || step.status}`).join('；');
        card.querySelector('div').textContent = `目标已创建。${steps || `任务编排 Agent 正在生成每日任务。计划任务 #${result.plan_job_id || '—'}。`} ${result.question_job_id ? `出题任务 #${result.question_job_id} 已排队。` : '出题 Agent 会在资料检索并入库后，依据已索引资料出题。'} 运行状态会显示在下方“Agent 运行过程”。`;
        button.textContent = '已启动';
        if (Array.isArray(result.source_items) && result.source_items.length) {
          await autoImportMaterials({ course_id: result.course_id, items: result.source_items });
        }
        if (result.plan_job_id) watchJob(result.plan_job_id);
        if (result.question_job_id) watchJob(result.question_job_id);
        if (result.vocabulary_job_id) watchJob(result.vocabulary_job_id);
      } catch (error) { button.disabled = false; button.textContent = '重试'; card.querySelector('div').textContent = `启动失败：${error.message}`; }
    };
    root.appendChild(card); root.scrollTop = root.scrollHeight;
    setTimeout(() => button.click(), 0);
  };
  window.restoreLearningLaunch = payload => appendLearningLaunch(payload, true);

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
      if (attempt) await new Promise(resolve => setTimeout(resolve, 2000));
      try {
        const job = await request(`/jobs/${jobId}`);
        appendActivity({ kind: 'execution', key: `job-${jobId}`, state: job.status === 'completed' ? 'completed' : job.status === 'failed' ? 'failed' : 'running', label: '执行后台任务', detail: job.status === 'completed' ? '后台任务已完成' : job.status === 'failed' ? (job.error || job.detail || '后台任务失败') : (job.detail || 'Worker 正在处理') });
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
      const part = await reader.read(); if (part.done) { stopRunTimer(); return; }
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
          if (name === 'tool' && payload.name === 'web.browser_screenshot') appendBrowserScreenshot(payload);
          if (name === 'tool' && payload.state === 'failed') appendToolFailure(payload);
          if (name === 'sources') applySourceSummaries(payload);
          if (name === 'auto_import') autoImportMaterials(payload);
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
          if (name === 'done') { stopRunTimer(payload); revealAssistantResponse(); }
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
    root.innerHTML = `<form method="dialog" class="agent-runtime-head"><h3>确认学习操作</h3><button class="icon-button" aria-label="关闭" title="关闭">&#215;</button></form><form id="runtime-tool-form" class="form-stack compact-form"><label>操作<select name="tool_name" id="runtime-tool-select"></select></label><p id="runtime-tool-description" class="task-meta"></p><label id="runtime-companion-row" class="hidden">桌面协作端 ID<input name="companion_id" id="runtime-companion-id" maxlength="120" placeholder="my-desktop-01"></label><label>参数（通常无需修改）<textarea name="arguments" rows="6">{}</textarea></label><label class="runtime-confirm"><input name="confirmed" type="checkbox">我确认执行此操作</label><button class="primary" type="submit">确认并执行</button></form><pre id="runtime-tool-result" class="agent-tool-output"></pre>`;
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
      if (tool?.requires_confirmation && !confirmed) { flash('请先勾选“我确认执行此操作”。'); return; }
      if (tool?.execution_target === 'desktop_companion') {
        const companion = String(data.companion_id || '').trim();
        if (!companion) { flash('Desktop Companion ID is required.'); return; }
        arguments.companion_id = companion;
        localStorage.setItem('learning.desktopCompanionId', companion);
      }
      const output = root.querySelector('#runtime-tool-result'); output.textContent = '正在执行，请稍候…';
      try {
        const result = await request(`/agent/sessions/${state.agentSessionId}/tools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool_name: data.tool_name, arguments, confirmed }) });
        output.textContent = `执行成功：\n${JSON.stringify(result.result, null, 2)}`;
      } catch (error) { output.textContent = `执行失败：${error.message}`; }
    };
  };

  window.addEventListener('DOMContentLoaded', () => {
    const heading = document.querySelector('#ai-view .section-head');
    if (!heading || document.querySelector('#agent-memories')) return;
    const button = document.createElement('button');
    button.id = 'agent-memories'; button.className = 'secondary'; button.type = 'button'; button.textContent = '学习记忆';
    button.onclick = showMemories;
    heading.insertBefore(button, heading.querySelector('#new-agent-session'));
    const activity = document.createElement('button');
    activity.id = 'agent-activity'; activity.className = 'secondary'; activity.type = 'button'; activity.textContent = '动态';
    activity.onclick = showActivity;
    heading.insertBefore(activity, heading.querySelector('#new-agent-session'));
    const tools = document.createElement('button');
    tools.id = 'agent-tools'; tools.className = 'secondary'; tools.type = 'button'; tools.textContent = '工具';
    tools.onclick = showTools;
    heading.insertBefore(tools, heading.querySelector('#new-agent-session'));
  });
})();
