const state = { token: sessionStorage.getItem('learning_access_token') || '', refreshToken: sessionStorage.getItem('learning_refresh_token') || '', refreshing: null, user: null, courses: [], questions: [], taskKnowledgePoints: [], practice: null, agentSessionId: null, agentSessions: [], tutorMode: 'Socratic' };
const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
function flash(message) { const root = $('#flash'); root.textContent = message; root.classList.remove('hidden'); setTimeout(() => root.classList.add('hidden'), 2800); }
function storeTokens(tokens) { state.token = tokens.access_token; state.refreshToken = tokens.refresh_token; sessionStorage.setItem('learning_access_token', state.token); sessionStorage.setItem('learning_refresh_token', state.refreshToken); }
function agentSessionStorageKey() { return state.user?.tenant_id ? `learning_agent_session_id:${state.user.tenant_id}` : ''; }
function restoreScopedAgentSession() { const key = agentSessionStorageKey(); state.agentSessionId = key ? (Number(localStorage.getItem(key)) || null) : null; }
function resetWorkspaceState() {
  state.courses = [];
  state.questions = [];
  state.taskKnowledgePoints = [];
  state.practice = null;
  state.activeCourseId = null;
  state.agentSessionId = null;
  state.agentSessions = [];
  window.resetAgentRuntime?.();
}
function resourceJobStorageKey() { return state.user?.tenant_id ? `learning_resource_job:${state.user.tenant_id}` : ''; }
function rememberResourceJob(jobId, label) {
  const key = resourceJobStorageKey();
  if (key && Number.isInteger(Number(jobId))) localStorage.setItem(key, JSON.stringify({ id: Number(jobId), label: String(label || '任务状态') }));
}
function restoreRememberedResourceJob() {
  const key = resourceJobStorageKey();
  if (!key) return;
  try {
    const remembered = JSON.parse(localStorage.getItem(key) || 'null');
    if (remembered?.id) void watchJob(Number(remembered.id), remembered.label || '任务状态');
  } catch (_) { localStorage.removeItem(key); }
}
async function refreshAccessToken() { if (!state.refreshToken) throw new Error('Session expired'); if (!state.refreshing) state.refreshing = fetch('/v1/auth/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: state.refreshToken }) }).then(async response => { if (!response.ok) throw new Error('Session expired'); return response.json(); }).then(storeTokens).finally(() => { state.refreshing = null; }); return state.refreshing; }
async function api(path, options = {}, retried = false) { const headers = { ...(options.headers || {}) }; if (state.token) headers.Authorization = `Bearer ${state.token}`; if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'; const response = await fetch(`/v1${path}`, { ...options, headers }); if (response.status === 401 && !retried && path !== '/auth/refresh') { try { await refreshAccessToken(); return api(path, options, true); } catch (error) { showAuth(); throw error; } } if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || 'Request failed'); } return response.status === 204 ? null : response.json(); }
function courseOptions(emptyLabel = '未选择课程') { return `<option value="">${emptyLabel}</option>${state.courses.map(course => `<option value="${course.id}">${escapeHtml(course.name)}</option>`).join('')}`; }
async function ensureCourses() { if (!state.courses.length) state.courses = await api('/courses'); }
function showAuth() { resetWorkspaceState(); state.token = ''; state.refreshToken = ''; state.user = null; sessionStorage.removeItem('learning_access_token'); sessionStorage.removeItem('learning_refresh_token'); $('#app-view').classList.add('hidden'); $('#auth-view').classList.remove('hidden'); }
function showApp() { restoreScopedAgentSession(); $('#auth-view').classList.add('hidden'); $('#app-view').classList.remove('hidden'); $('#user-label').textContent = state.user.display_name || state.user.email; $('#org-label').textContent = `${state.user.tenant_id.slice(0, 8)} · ${state.user.role}`; openView('today'); }
async function authenticate(path, form) { const tokens = await api(path, { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form))) }); resetWorkspaceState(); storeTokens(tokens); state.user = await api('/me'); showApp(); }

document.querySelectorAll('[data-auth-tab]').forEach(button => button.onclick = () => { document.querySelectorAll('[data-auth-tab]').forEach(item => item.classList.toggle('active', item === button)); $('#login-form').classList.toggle('hidden', button.dataset.authTab !== 'login'); $('#register-form').classList.toggle('hidden', button.dataset.authTab !== 'register'); $('#auth-error').textContent = ''; });
$('#login-form').onsubmit = async event => { event.preventDefault(); try { await authenticate('/auth/login', event.target); } catch (error) { $('#auth-error').textContent = error.message; } };
$('#register-form').onsubmit = async event => { event.preventDefault(); try { await authenticate('/auth/register', event.target); } catch (error) { $('#auth-error').textContent = error.message; } };
document.querySelectorAll('.sidebar .nav-item[data-view]').forEach(button => button.onclick = () => openView(button.dataset.view));
function openView(view) { const target = $(`#${view}-view`); if (!target) return; document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === view)); document.querySelectorAll('.view').forEach(item => item.classList.add('hidden')); target.classList.remove('hidden'); const title = ({ today: '今日学习', dashboard: '今日学习', courses: '我的课程', tasks: '学习任务', goals: '学习计划', practice: '练习与复习', mistakes: '错题本', analytics: '学习分析', vocabulary: '词汇复习', resources: '学习资料库', ai: 'AI 学习助手', members: '团队成员' })[view] || 'Learning Space'; document.title = `${title} · Learning Space`; void loadCurrentView(view); }
async function loadCurrentView(activeView) { const view = activeView || document.querySelector('.sidebar .nav-item.active')?.dataset.view; const loads = { today: async () => { await loadToday(); await loadTodayReminders(); }, dashboard: async () => { await loadToday(); await loadTodayReminders(); }, courses: loadCourses, tasks: loadTasks, goals: loadGoals, practice: async () => { await loadPractice(); await loadQuestionDrafts(); }, mistakes: loadMistakes, analytics: loadAnalytics, vocabulary: loadVocabulary, resources: async () => { await loadResources(); await loadKnowledgeDrafts(); }, ai: loadAiCenter, members: loadMembers }; const load = loads[view]; if (typeof load === 'function') await load(); }
async function loadVocabulary() { try { const [all, due] = await Promise.all([api('/vocabulary'), api('/vocabulary?due_only=true')]); const row = item => `<article class="list-row"><div><strong>${escapeHtml(item.word)}</strong><div class="task-meta">${escapeHtml(item.meaning)} · next ${item.next_review}</div>${item.example ? `<div>${escapeHtml(item.example)}</div>` : ''}</div><span class="task-meta">streak ${item.streak}</span></article>`; $('#vocabulary-list').innerHTML = all.map(row).join('') || '<span class="task-meta">No words yet.</span>'; $('#vocabulary-due').innerHTML = due.map(row).join('') || '<span class="task-meta">Nothing due today.</span>'; } catch (error) { flash(error.message); } }

function taskRow(task, selectable = false) { const context = [task.course_name ? `课程：${task.course_name}` : '未关联课程', task.knowledge_point_name ? `知识点：${task.knowledge_point_name}` : '未关联知识点', task.source ? `来源：${task.source}` : ''].filter(Boolean).join(' · '); return `<article class="list-row">${selectable ? `<label class="task-select"><input type="checkbox" data-task-select="${task.id}" aria-label="选择任务：${escapeHtml(task.title)}"></label>` : ''}<div><strong>${escapeHtml(task.title)}</strong><div class="task-meta">${task.planned_date} · ${task.duration_minutes} min${task.scheduled_time ? ` · reminder ${task.scheduled_time}` : ''}</div><div class="task-meta">${escapeHtml(context)}</div>${task.note ? `<div class="task-meta">备注：${escapeHtml(task.note)}</div>` : ''}</div>${task.completed ? '<span class="complete">Completed</span>' : `<div class="task-actions"><button class="secondary" data-task-action="complete" data-task-id="${task.id}">完成</button><button class="text-button" data-task-action="postpone" data-task-id="${task.id}">明天</button><button class="text-button" data-task-action="skip" data-task-id="${task.id}">跳过</button></div>`}</article>`; }
function todayTaskStatus(tasks) { const pending = tasks.filter(task => !task.completed); if (!pending.length) return '<div class="empty-state"><strong>今天没有待完成任务</strong><span>课程中的新任务会在这里显示状态。</span><button class="secondary" data-view="courses">查看课程</button></div>'; const courses = [...new Set(pending.map(task => task.course_name).filter(Boolean))]; return `<article class="list-row"><div><strong>今天有 ${pending.length} 项待完成任务</strong><div class="task-meta">${escapeHtml(courses.join(' · ') || '请在课程中查看任务详情')}</div></div><button class="secondary" data-view="courses">查看课程任务</button></article>`; }
function bindTaskActions(refresh) { document.querySelectorAll('[data-task-action]').forEach(button => { if (button.dataset.bound) return; button.dataset.bound = '1'; button.onclick = async () => { try { await api(`/tasks/${button.dataset.taskId}/action`, { method: 'POST', body: JSON.stringify({ action: button.dataset.taskAction }) }); flash(button.dataset.taskAction === 'complete' ? '任务已完成' : '任务状态已更新'); await refresh(); } catch (error) { flash(error.message); } }; }); }
async function loadToday() { try { const [today, rhythm] = await Promise.all([api('/today'), api('/dashboard')]); const metrics = [['今日计划', `${today.summary.planned_minutes} min`], ['已完成', `${today.summary.completed_minutes} min`], ['完成率', `${today.summary.completion_rate}%`], ['待复习', `${today.reviews.due} 项`]]; $('#today-metrics').innerHTML = metrics.map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join(''); $('#today-tasks').innerHTML = todayTaskStatus(today.tasks); $('#today-reviews').innerHTML = today.reviews.items.slice(0, 5).map(item => `<article class="list-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">错 ${item.wrong_count} 次 · ${item.next_review}</div></div><button class="text-button" data-view="practice">开始</button></article>`).join('') || '<span class="task-meta">今天没有到期复习，继续保持。</span>'; $('#today-weak-points').innerHTML = today.weak_points.map(point => `<article class="list-row"><div><strong>${escapeHtml(point.name)}</strong><div class="mastery-bar"><i style="width:${point.mastery}%"></i></div></div><span class="mastery-value">${point.mastery}%</span></article>`).join('') || '<span class="task-meta">完成练习后，系统会识别薄弱知识点。</span>'; $('#today-insight').innerHTML = `<strong>${escapeHtml(today.insight.text)}</strong><span class="task-meta">建议会随任务完成、练习和复习记录更新。</span>`; $('#daily-study').innerHTML = rhythm.daily_study_minutes.map(day => `<div class="bar-wrap"><div class="bar" style="height:${Math.min(150, Math.max(3, day.minutes * 2))}px"></div><div class="bar-label">${day.date.slice(5)}</div></div>`).join(''); bindViewButtons(); } catch (error) { flash(error.message); } }
function ensureTodayReminderPanel() { let root = $('#today-reminders'); if (root) return root; const grid = document.querySelector('#today-view .today-grid'); if (!grid) return null; const section = document.createElement('section'); section.className = 'data-section reminder-panel'; section.innerHTML = '<div class="section-head"><h3>提醒</h3><button class="text-button" data-view="tasks">管理任务</button></div><div id="today-reminders" class="list"></div>'; grid.insertAdjacentElement('afterend', section); bindViewButtons(); return $('#today-reminders'); }
async function loadTodayReminders() { const root = ensureTodayReminderPanel(); if (!root) return; try { const reminders = await api('/reminders'); root.innerHTML = reminders.map(item => `<article class="list-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">${escapeHtml(item.message)}</div></div><span class="task-meta">${escapeHtml(item.type)}</span></article>`).join('') || '<span class="task-meta">暂无需要处理的提醒。</span>'; } catch (error) { root.textContent = '提醒加载失败：' + error.message; } }
async function loadDashboard() { return loadToday(); }
async function loadMistakes() { try { const mistakes = await api('/mistakes'); $('#mistake-list').innerHTML = mistakes.map(item => `<article class="mistake-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">${escapeHtml(item.knowledge_point || '未关联知识点')} · ${escapeHtml(item.error_type)} · 错 ${item.wrong_count} 次</div><div class="task-meta">下次复习：${item.next_review}</div></div><button class="secondary" data-view="practice">开始复习</button></article>`).join('') || '<div class="empty-state"><strong>错题本还是空的</strong><span>完成练习后，答错的题目会自动进入这里，并参与后续复习。</span><button class="primary" data-view="practice">去做练习</button></div>'; bindViewButtons(); } catch (error) { flash(error.message); } }
async function loadAnalytics(days = 7) { try { const data = await api(`/analytics?days=${days}`); const summary = data.summary; $('#analytics-metrics').innerHTML = [['学习时间', `${summary.study_minutes} min`], ['任务完成', `${summary.tasks_completed}/${summary.tasks_total}`], ['练习正确率', `${summary.accuracy}%`], ['待复习', `${summary.due_reviews} 项`]].map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join(''); $('#analytics-daily').innerHTML = data.daily.map(item => `<article class="analytics-day"><div><strong>${item.date.slice(5)}</strong><span>${item.minutes} min · ${item.questions} 题</span></div><div class="analytics-track"><i style="width:${Math.min(100, item.minutes * 2)}%"></i></div><b>${item.accuracy}%</b></article>`).join(''); $('#analytics-errors').innerHTML = data.error_types.map(item => `<article class="list-row"><span>${escapeHtml(item.type)}</span><strong>${item.count}</strong></article>`).join('') || '<span class="task-meta">还没有足够的错题数据。</span>'; $('#analytics-weak').innerHTML = data.weak_points.map(item => `<article class="list-row"><span>${escapeHtml(item.name)}</span><strong>${item.mastery}%</strong></article>`).join('') || '<span class="task-meta">还没有识别出薄弱知识点。</span>'; document.querySelectorAll('.analytics-range').forEach(button => button.classList.toggle('active-range', Number(button.dataset.days) === days)); } catch (error) { flash(error.message); } }
async function loadCourses() { try { state.courses = await api('/courses'); $('#course-list').innerHTML = state.courses.map(course => `<article class="course-card" data-course-open="${course.id}"><div class="course-card-top"><span class="course-dot"></span><span class="task-meta">${escapeHtml(course.subject || 'Other')}</span></div><h4>${escapeHtml(course.name)}</h4><p>${escapeHtml(course.description || '打开课程工作区，查看目标、知识掌握度和练习进度。')}</p><button class="text-button">打开学习工作区 →</button></article>`).join('') || '<div class="empty-state"><strong>还没有课程</strong><span>创建第一门课程，把目标、资料、练习和进度放在同一个工作区。</span><button class="primary" id="new-course-empty">创建课程</button></div>'; document.querySelectorAll('[data-course-open]').forEach(card => card.onclick = () => openCourse(Number(card.dataset.courseOpen))); } catch (error) { flash(error.message); } }
function bindViewButtons() { document.querySelectorAll('[data-view]').forEach(button => { if (button.dataset.viewBound) return; button.dataset.viewBound = '1'; button.onclick = () => openView(button.dataset.view); }); }
async function openCourse(courseId) { try { const data = await api(`/courses/${courseId}/workspace`); const course = data.course; $('#course-list').innerHTML = `<section class="workspace-card"><button class="text-button" id="back-courses">← 返回课程</button><div class="course-hero"><div><p class="eyebrow">LEARNING WORKSPACE</p><h3>${escapeHtml(course.name)}</h3><p>${escapeHtml(course.description || course.subject)}</p></div><div class="course-progress"><strong>${course.progress}%</strong><span>课程进度</span></div></div><div class="workspace-tabs"><button class="primary" data-view="goals">查看计划与知识</button><button class="secondary" data-view="practice">开始练习</button><button class="secondary" data-view="mistakes">查看错题</button></div><div class="content-grid"><section><h4>课程任务</h4><div class="list">${data.recent_tasks.map(task => taskRow(task)).join('') || '<span class="task-meta">这门课程还没有任务。</span>'}</div></section><section><h4>知识掌握度</h4><div class="list">${data.knowledge.map(item => `<article class="list-row"><span>${escapeHtml(item.name)}</span><strong>${item.mastery}%</strong></article>`).join('') || '<span class="task-meta">还没有知识点。可在资料页或目标页建立知识结构。</span>'}</div></section><section><h4>课程目标</h4><div class="list">${data.goals.map(item => `<article class="list-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">${item.target_date} · ${item.progress}%</div></div></article>`).join('') || '<span class="task-meta">还没有课程目标。</span>'}</div></section></div></section>`; $('#back-courses').onclick = loadCourses; bindViewButtons(); bindTaskActions(() => openCourse(courseId)); } catch (error) { flash(error.message); } }
function renderTaskKnowledgeOptions() { const courseId = Number($('#task-course')?.value) || null; const options = state.taskKnowledgePoints.filter(point => !courseId || point.course_id === courseId); $('#task-knowledge').innerHTML = '<option value="">No linked knowledge point</option>' + options.map(point => `<option value="${point.id}">${escapeHtml(point.name)}</option>`).join(''); }
async function loadTasks() { try { await ensureCourses(); $('#task-course').innerHTML = courseOptions(); state.taskKnowledgePoints = await api('/knowledge-points'); renderTaskKnowledgeOptions(); const tasks = await api('/tasks'); $('#task-list').innerHTML = tasks.map(task => taskRow(task, true)).join('') || '<span class="task-meta">No tasks yet.</span>'; let bulk = $('#bulk-delete-tasks'); if (!bulk) { bulk = document.createElement('button'); bulk.id = 'bulk-delete-tasks'; bulk.type = 'button'; bulk.className = 'secondary'; bulk.textContent = '删除所选'; $('#new-task').insertAdjacentElement('beforebegin', bulk); } bulk.onclick = async () => { const ids = [...document.querySelectorAll('[data-task-select]:checked')].map(item => Number(item.dataset.taskSelect)); if (!ids.length) return flash('请先勾选要删除的任务'); if (!confirm(`确定删除 ${ids.length} 个任务吗？此操作无法撤销。`)) return; try { const result = await api('/tasks', { method: 'DELETE', body: JSON.stringify({ task_ids: ids }) }); flash(`已删除 ${result.deleted_count} 个任务`); await loadTasks(); } catch (error) { flash(error.message); } }; bindTaskActions(loadTasks); } catch (error) { flash(error.message); } }
async function loadGoals() { try { await ensureCourses(); $('#goal-course').innerHTML = courseOptions(); $('#knowledge-course').innerHTML = courseOptions('Select course'); const [goals, points] = await Promise.all([api('/goals'), api('/knowledge-points')]); const courseName = id => escapeHtml(state.courses.find(course => course.id === id)?.name || 'No course'); $('#goal-list').innerHTML = goals.map(goal => `<article class="list-row"><div><strong>${escapeHtml(goal.title)}</strong><div class="task-meta">Due ${goal.target_date} · ${goal.weekly_minutes} min/week${goal.target_score === null ? '' : ` · score ${goal.target_score}`}</div></div><div class="goal-actions"><span class="task-meta">${escapeHtml(goal.status)} · ${goal.progress}%</span>${goal.course_id ? `<button class="text-button" data-plan-goal="${goal.id}">生成计划</button>` : ''}</div></article>`).join('') || '<span class="task-meta">No goals yet.</span>'; $('#knowledge-point-list').innerHTML = points.map(point => `<article class="list-row"><div><strong>${escapeHtml(point.name)}</strong><div class="task-meta">${courseName(point.course_id)} · ${escapeHtml(point.category)} · difficulty ${point.difficulty}/5</div></div><span class="task-meta">Mastery ${point.mastery}% · ${point.practice_count || 0} 次练习 · ${point.mastery}%</span></article>`).join('') || '<span class="task-meta">No knowledge points yet.</span>'; document.querySelectorAll('[data-plan-goal]').forEach(button => button.onclick = () => queueLearningPlan(Number(button.dataset.planGoal))); } catch (error) { flash(error.message); } }
async function queueLearningPlan(goalId) { const root = $('#plan-job-status'); root.classList.remove('hidden'); root.innerHTML = '<strong>正在分析学习画像…</strong><p class="task-meta">系统会结合目标、掌握度、错题和历史任务生成可确认的学习计划。</p>'; try { const result = await api('/ai/jobs', { method: 'POST', body: JSON.stringify({ feature: 'learning_plan', goal_id: goalId, request: '根据当前学习数据生成可执行的阶段与每日学习计划。' }) }); watchPlanJob(result.job_id); } catch (error) { root.innerHTML = `<p class="error-text">计划生成失败：${escapeHtml(error.message)}</p>`; } }
async function watchPlanJob(jobId) { const root = $('#plan-job-status'); for (let count = 0; count < 60; count += 1) { const job = await api(`/jobs/${jobId}`); root.innerHTML = `<strong>AI 学习计划</strong><p class="task-meta">${escapeHtml(job.status)}${job.detail ? ` · ${escapeHtml(job.detail)}` : ''}${job.error ? ` · ${escapeHtml(job.error)}` : ''}</p>`; if (job.status === 'completed') { const result = job.result || {}; root.innerHTML = `<strong>计划已生成</strong><p class="task-meta">已写入 ${Number(result.created_task_count || 0)} 个学习任务。Today 会自动显示新的任务。</p>`; await loadToday(); return; } if (job.status === 'failed') return; await new Promise(resolve => setTimeout(resolve, 2000)); } }
async function loadPractice() { try { await ensureCourses(); $('#question-course').innerHTML = courseOptions(); state.questions = await api('/questions'); $('#question-list').innerHTML = state.questions.map(question => { const options = String(question.options || '').split('\\n').map(item => item.trim()).filter(Boolean); return `<label class="list-row question-row"><input type="checkbox" data-question-select="${question.id}"><div class="question-copy"><strong class="math-text">${mathHtml(question.prompt)}</strong>${options.length ? `<div class="question-options">${options.map(option => `<span class="math-text">${mathHtml(option)}</span>`).join('')}</div>` : ''}<div class="task-meta">${escapeHtml(question.kind)} · difficulty ${question.difficulty}</div></div></label>`; }).join('') || '<span class="task-meta">Add questions to start practice.</span>'; typesetMath($('#question-list')); const reviews = await api('/reviews?due_only=true'); $('#review-list').innerHTML = reviews.map(review => `<article class="list-row"><div><strong class="math-text">${mathHtml(review.title)}</strong><div class="task-meta">Wrong ${review.wrong_count} · ${review.next_review}</div></div><select data-review="${review.id}"><option value="correct">Mastered</option><option value="wrong">Not yet</option><option value="postpone">Tomorrow</option></select></article>`).join('') || '<span class="task-meta">No due reviews.</span>'; typesetMath($('#review-list')); document.querySelectorAll('[data-review]').forEach(select => select.onchange = async () => { try { await api(`/reviews/${select.dataset.review}/attempts`, { method: 'POST', body: JSON.stringify({ result: select.value }) }); flash('Review recorded'); loadPractice(); } catch (error) { flash(error.message); } }); renderPracticeRun(); } catch (error) { flash(error.message); } }
async function loadKnowledgeDrafts() { const root = $('#knowledge-draft-list'); try { const drafts = await api('/knowledge-drafts'); root.innerHTML = ''; if (!drafts.length) { root.innerHTML = '<span class="task-meta">没有待审核草稿。资料提取完成后会显示证据与确认入口。</span>'; return; } drafts.forEach(draft => { const article = document.createElement('article'); article.className = 'list-row'; const copy = document.createElement('div'); const title = document.createElement('strong'); title.textContent = draft.name; const detail = document.createElement('div'); detail.className = 'task-meta'; detail.textContent = draft.category + ' · 难度 ' + draft.difficulty + '/5 · 置信度 ' + Math.round(draft.confidence * 100) + '%'; const definition = document.createElement('div'); definition.className = 'task-meta'; definition.textContent = draft.definition || '暂无定义'; copy.append(title, detail, definition); if (draft.citations.length) { const citation = document.createElement('div'); citation.className = 'task-meta'; citation.textContent = '证据：' + draft.citations[0].source_name + ' · ' + draft.citations[0].quote_text.slice(0, 120); copy.append(citation); } const actions = document.createElement('div'); const accept = document.createElement('button'); accept.className = 'primary'; accept.textContent = '接受'; accept.onclick = () => reviewKnowledgeDraft(draft.id, 'accept'); const reject = document.createElement('button'); reject.className = 'secondary'; reject.textContent = '拒绝'; reject.onclick = () => reviewKnowledgeDraft(draft.id, 'reject'); actions.append(accept, reject); article.append(copy, actions); root.append(article); }); } catch (error) { root.textContent = '草稿加载失败：' + error.message; } }
async function reviewKnowledgeDraft(id, action) { try { await api('/knowledge-drafts/' + id + '/review', { method: 'POST', body: JSON.stringify({ action }) }); flash(action === 'accept' ? '知识点已加入课程知识库' : '草稿已拒绝'); await Promise.all([loadKnowledgeDrafts(), loadGoals()]); } catch (error) { flash(error.message); } }
function ensureQuestionDraftPanel() { let root = $('#question-draft-list'); if (root) return root; const job = $('#generation-job'); if (!job) return null; const heading = document.createElement('div'); heading.className = 'subhead section-head'; heading.innerHTML = '<h3>AI 题目草稿</h3><button id="refresh-question-drafts" class="text-button">刷新</button>'; root = document.createElement('div'); root.id = 'question-draft-list'; root.className = 'list'; job.insertAdjacentElement('afterend', root); job.insertAdjacentElement('afterend', heading); $('#refresh-question-drafts').onclick = loadQuestionDrafts; return root; }
async function loadQuestionDrafts() { const root = ensureQuestionDraftPanel(); if (!root) return; try { const drafts = await api('/question-drafts'); root.innerHTML = ''; if (!drafts.length) { root.innerHTML = '<span class="task-meta">没有待审核题目草稿。生成题目后会在这里显示证据与审核入口。</span>'; return; } drafts.forEach(draft => { const article = document.createElement('article'); article.className = 'list-row'; const copy = document.createElement('div'); const title = document.createElement('strong'); title.className = 'math-text'; title.textContent = draft.prompt; const meta = document.createElement('div'); meta.className = 'task-meta'; meta.textContent = draft.kind + ' · 难度 ' + draft.difficulty + '/5' + (draft.citations.length ? ' · 引用 ' + draft.citations.length + ' 条' : ''); const answer = document.createElement('div'); answer.className = 'task-meta'; answer.textContent = '标准答案：' + draft.answer; copy.append(title, meta, answer); if (draft.citations.length) { const citation = document.createElement('div'); citation.className = 'task-meta'; citation.textContent = '证据：' + draft.citations[0].source_name + ' · ' + draft.citations[0].quote_text.slice(0, 120); copy.append(citation); } const actions = document.createElement('div'); const accept = document.createElement('button'); accept.className = 'primary'; accept.textContent = '接受入题库'; accept.onclick = () => reviewQuestionDraft(draft.id, 'accept'); const reject = document.createElement('button'); reject.className = 'secondary'; reject.textContent = '拒绝'; reject.onclick = () => reviewQuestionDraft(draft.id, 'reject'); actions.append(accept, reject); article.append(copy, actions); root.append(article); }); typesetMath(root); } catch (error) { root.textContent = '题目草稿加载失败：' + error.message; } }
async function reviewQuestionDraft(id, action) { try { await api('/question-drafts/' + id + '/review', { method: 'POST', body: JSON.stringify({ action }) }); flash(action === 'accept' ? '题目已加入题库' : '题目草稿已拒绝'); await Promise.all([loadQuestionDrafts(), loadPractice()]); } catch (error) { flash(error.message); } }
async function startRecommendedPractice(ids = null) { try { const recommendation = ids ? { items: ids.map(id => ({ id })) } : await api('/practice/recommendations', { method: 'POST', body: JSON.stringify({ limit: 10 }) }); const questionIds = recommendation.items.map(item => item.id); if (!questionIds.length) return flash(recommendation.empty_reason || '暂无可推荐题目，请先创建题目。'); if (!state.questions.length) state.questions = await api('/questions'); const session = await api('/practice-sessions', { method: 'POST', body: JSON.stringify({ question_ids: questionIds }) }); state.practice = { id: session.id, questions: state.questions.filter(question => questionIds.includes(question.id)), index: 0 }; renderPracticeRun(); flash('已开始智能推荐练习'); } catch (error) { flash(error.message); } }
async function loadResources() { try { await ensureCourses(); $('#resource-course').innerHTML = courseOptions(); $('#rag-course').innerHTML = courseOptions('All courses'); const resources = await api('/resources'); $('#resource-list').innerHTML = resources.map(resource => `<article class="list-row"><div><strong>${escapeHtml(resource.name)}</strong><div class="task-meta">${Math.ceil(resource.size / 1024)} KB · ${resource.course_id ? `Course #${resource.course_id}` : 'No course'}</div></div>${resource.course_id ? `<button class="text-button" data-extract-resource="${resource.course_id}" data-resource-name="${escapeHtml(resource.name)}">提取知识</button>` : '<span class="task-meta">先关联课程</span>'}</article>`).join('') || '<div class="empty-state"><strong>还没有学习资料</strong><span>上传教材、讲义或题目资料，系统会建立可引用的个人知识库。</span></div>'; document.querySelectorAll('[data-extract-resource]').forEach(button => button.onclick = () => queueKnowledgeExtraction(Number(button.dataset.extractResource), button.dataset.resourceName)); } catch (error) { flash(error.message); } }
async function queueKnowledgeExtraction(courseId, resourceName) { const root = $('#rag-job'); root.innerHTML = `<strong>正在分析 ${escapeHtml(resourceName)}…</strong><p class="task-meta">AI 会从已索引证据中提取知识点草稿，确认后才进入正式知识库。</p>`; try { const result = await api('/ai/jobs', { method: 'POST', body: JSON.stringify({ feature: 'knowledge_extraction', course_id: courseId, request: `从资料 ${resourceName} 提取课程知识点，并为每个知识点保留证据引用。` }) }); watchJob(result.job_id, 'Knowledge extraction'); } catch (error) { root.innerHTML = `<p class="error-text">知识抽取失败：${escapeHtml(error.message)}</p>`; } }
async function downloadAgentReport(url) { const response = await fetch(url, { headers: { Authorization: `Bearer ${state.token}` } }); if (!response.ok) throw new Error('Download failed'); const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'learning-report.md'; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(link.href); }
function bindAgentDownloads(root) { root.querySelectorAll('[data-download-url]').forEach(link => link.onclick = async event => { event.preventDefault(); try { await downloadAgentReport(link.dataset.downloadUrl); } catch (error) { flash(error.message); } }); }
function renderRichBlocks(blocks, messageId = '') { return (blocks || []).map((block, index) => {
  if (block.type !== 'quiz') return `<div class="rich-markdown">${escapeHtml(block.content || '').replace(/\n/g, '<br>')}</div>`;
  const questions = Array.isArray(block.questions) ? block.questions : [];
  const quizId = `quiz-${messageId || Date.now()}-${index}`;
  return `<section class="rich-quiz" data-quiz="${quizId}"><div class="rich-quiz-head"><strong>Interactive practice</strong><span class="quiz-progress">0 / ${questions.length}</span></div>${questions.map((question, qIndex) => `<fieldset class="rich-question" data-q-index="${qIndex}"><legend>${qIndex + 1}. ${escapeHtml(question.prompt || '')}</legend><div class="rich-options">${(question.options || []).map(option => `<label class="rich-option"><input type="radio" name="${quizId}-${qIndex}" value="${escapeHtml(option.id || option.label || '')}"><span><b>${escapeHtml(option.id || '')}</b> ${escapeHtml(option.label || '')}</span></label>`).join('')}</div></fieldset>`).join('')}<div class="rich-quiz-actions"><button type="button" class="primary rich-finish">完成</button><button type="button" class="secondary rich-submit hidden">提交给 AI</button></div></section>`;
}).join(''); }
function bindRichQuizzes(root) { root.querySelectorAll('.rich-quiz').forEach(quiz => { if (quiz.dataset.bound) return; quiz.dataset.bound = '1'; const total = quiz.querySelectorAll('.rich-question').length; const progress = quiz.querySelector('.quiz-progress'); const update = () => { const done = [...quiz.querySelectorAll('.rich-question')].filter(q => q.querySelector('input:checked')).length; progress.textContent = `${done} / ${total}`; quiz.querySelector('.rich-finish').disabled = done < total; }; quiz.addEventListener('change', update); quiz.querySelector('.rich-finish').onclick = () => { quiz.classList.add('rich-review'); quiz.querySelector('.rich-finish').classList.add('hidden'); quiz.querySelector('.rich-submit').classList.remove('hidden'); }; quiz.querySelector('.rich-submit').onclick = async () => { const answers = [...quiz.querySelectorAll('.rich-question')].map((q, index) => ({ question_index: index + 1, answer: q.querySelector('input:checked')?.value || '' })); quiz.querySelector('.rich-submit').disabled = true; quiz.insertAdjacentHTML('beforeend', '<p class="task-meta rich-submit-status">已提交，Agent 正在批改并更新学习记录...</p>'); try { await sendAgentEvent('exercise_submission', { quiz_id: quiz.dataset.quiz, answers }); quiz.querySelector('.rich-submit-status').textContent = '已提交给 AI，会话中将继续给出解析。'; } catch (error) { quiz.querySelector('.rich-submit-status').textContent = `提交失败：${error.message}`; quiz.querySelector('.rich-submit').disabled = false; } }; update(); }); }
function renderAgentMessageContent(message) { const blocks = Array.isArray(message.blocks) ? message.blocks : [{ type: 'markdown', content: message.content }]; return renderRichBlocks(blocks, message.id); }
function renderAgentMessages(messages) { const root = $('#agent-messages'); root.innerHTML = messages.map(message => `<article class="agent-message ${escapeHtml(message.role)}" data-agent-message-id="${message.id}"><strong>${message.role === 'user' ? 'You' : 'Learning Agent'}</strong><div>${renderAgentMessageContent(message)}</div></article>`).join('') || '<p class="task-meta">Start a conversation with your learning agent.</p>'; window.restoreAgentSourceResults?.(root, messages); bindAgentDownloads(root); bindRichQuizzes(root); root.scrollTop = root.scrollHeight; }
async function sendAgentEvent(eventType, payload) { if (!state.agentSessionId) throw new Error('No active Agent conversation'); const response = await fetch(`/v1/agent/sessions/${normalizeAgentSessionId(state.agentSessionId)}/messages/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${state.token}` }, body: JSON.stringify({ message: 'Exercise submission', event_type: eventType, event_payload: payload }) }); if (!response.ok) throw new Error('Agent submission failed'); const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '', answer = ''; while (true) { const part = await reader.read(); if (part.done) break; buffer += decoder.decode(part.value, { stream: true }); const events = buffer.split('\n\n'); buffer = events.pop(); for (const event of events) { const name = event.match(/^event: (.+)$/m)?.[1]; const raw = event.match(/^data: (.+)$/m)?.[1]; if (!raw) continue; const data = JSON.parse(raw); if (name === 'token') answer += data.text || ''; } } if (answer) { const root = $('#agent-messages'); root.insertAdjacentHTML('beforeend', `<article class="agent-message assistant"><strong>Learning Agent</strong><div>${escapeHtml(answer).replace(/\n/g, '<br>')}</div></article>`); root.scrollTop = root.scrollHeight; } }
function renderAgentSessions() { $('#agent-session-list').innerHTML = state.agentSessions.map(item => `<button class="session-row ${item.id === state.agentSessionId ? 'active' : ''}" data-agent-session="${item.id}">${escapeHtml(item.title)}</button>`).join('') || '<p class="task-meta">还没有对话。</p>'; document.querySelectorAll('[data-agent-session]').forEach(button => button.onclick = () => selectAgentSession(Number(button.dataset.agentSession))); }
function normalizeAgentSessionId(value) { const id = typeof value === 'object' && value !== null ? value.id : value; const numeric = Number(id); if (!Number.isInteger(numeric) || numeric < 1) throw new Error('Invalid agent conversation. Create a new conversation and try again.'); return numeric; }
async function selectAgentSession(sessionId) { try { const id = normalizeAgentSessionId(sessionId); state.agentSessionId = id; const key = agentSessionStorageKey(); if (key) localStorage.setItem(key, String(id)); renderAgentSessions(); const [messages, launch] = await Promise.all([api(`/agent/sessions/${id}/messages`), api(`/agent/sessions/${id}/learning-launch-state`)]); renderAgentMessages(messages); window.restoreLearningLaunch?.(launch?.state); } catch (error) { flash(error.message); renderAgentMessages([{ role: 'assistant', content: `Unable to open this conversation: ${error.message}` }]); } }
async function createAgentSession() { const session = await api('/agent/sessions', { method: 'POST', body: JSON.stringify({ title: 'New session' }) }); state.agentSessions = [session, ...state.agentSessions]; await selectAgentSession(session); }
async function loadAiCenter() { try { await ensureCourses(); state.agentSessions = await api('/agent/sessions'); renderAgentSessions(); if (state.agentSessionId && state.agentSessions.some(item => item.id === state.agentSessionId)) await selectAgentSession(state.agentSessionId); else if (state.agentSessions[0]) await selectAgentSession(state.agentSessions[0]); } catch (error) { flash(error.message); } }
async function loadMembers() { try { const canManage = ['owner', 'admin'].includes(state.user.role); $('#new-member').classList.toggle('hidden', !canManage); const members = await api('/organization/members'); $('#member-list').innerHTML = members.map(member => { const editable = canManage && member.role !== 'owner' && member.user_id !== state.user.id; const control = editable ? `<div class="member-actions"><select data-member-role="${member.user_id}"><option value="member" ${member.role === 'member' ? 'selected' : ''}>Member</option><option value="admin" ${member.role === 'admin' ? 'selected' : ''}>Admin</option></select><button class="secondary" data-member-remove="${member.user_id}">Remove</button></div>` : `<span class="task-meta">${member.user_id === state.user.id ? 'Current user' : ''}</span>`; return `<article class="list-row"><div><strong>${escapeHtml(member.display_name || member.email)}</strong><div class="task-meta">${escapeHtml(member.email)} · ${escapeHtml(member.role)}</div></div>${control}</article>`; }).join('') || '<span class="task-meta">No members.</span>'; document.querySelectorAll('[data-member-role]').forEach(select => select.onchange = async () => { try { await api(`/organization/members/${select.dataset.memberRole}`, { method: 'PATCH', body: JSON.stringify({ role: select.value }) }); flash('Role updated'); loadMembers(); } catch (error) { flash(error.message); } }); document.querySelectorAll('[data-member-remove]').forEach(button => button.onclick = async () => { if (!confirm('Remove this member?')) return; try { await api(`/organization/members/${button.dataset.memberRemove}`, { method: 'DELETE' }); flash('Member removed'); loadMembers(); } catch (error) { flash(error.message); } }); } catch (error) { flash(error.message); } }
async function prepareQuestionGenerationForm() { await ensureCourses(); const form = $('#question-generation-form'); const course = $('#generation-course'); course.innerHTML = courseOptions('Select course'); let knowledge = $('#generation-knowledge'); if (!knowledge) { knowledge = document.createElement('select'); knowledge.id = 'generation-knowledge'; knowledge.name = 'knowledge_point_id'; knowledge.innerHTML = '<option value="">All knowledge points</option>'; course.insertAdjacentElement('afterend', knowledge); } let resources = $('#generation-resources'); if (!resources) { resources = document.createElement('select'); resources.id = 'generation-resources'; resources.name = 'resource_ids'; resources.multiple = true; resources.size = 3; resources.title = 'Optional: select source materials'; resources.innerHTML = '<option disabled>Select source materials (optional)</option>'; const request = form.querySelector('[name=request]'); request.insertAdjacentElement('beforebegin', resources); } const updateScope = async () => { const courseId = Number(course.value); if (!courseId) { knowledge.innerHTML = '<option value="">All knowledge points</option>'; resources.innerHTML = '<option disabled>Select a course first</option>'; return; } const [points, allResources] = await Promise.all([api('/knowledge-points?course_id=' + courseId), api('/resources')]); knowledge.innerHTML = '<option value="">All knowledge points</option>' + points.map(point => '<option value="' + point.id + '">' + escapeHtml(point.name) + '</option>').join(''); resources.innerHTML = allResources.filter(item => item.course_id === courseId).map(item => '<option value="' + item.id + '">' + escapeHtml(item.name) + '</option>').join('') || '<option disabled>No indexed resources for this course</option>'; }; course.onchange = updateScope; await updateScope(); }
function tutorInstruction(mode) { return { Explain: '请用清晰的分步解释，不直接跳过推理。', Hint: '请只给我下一步提示，不要直接给出答案。', Socratic: '请用苏格拉底式提问帮助我自己推导，并根据我的回答继续追问。', Example: '请先解释核心概念，再给一个由浅入深的例子。', 'Quiz Me': '请围绕当前内容给我一道小测题，等待我回答后再点评。' }[mode] || '请用适合学习的方式帮助我理解。'; }
function ensureTutorModeBar() { const form = $('#agent-form'); if (!form || $('#tutor-mode-bar')) return; const labels = { Explain: '讲解', Hint: '提示', Socratic: '启发式提问', Example: '举例', 'Quiz Me': '小测验' }; const bar = document.createElement('div'); bar.id = 'tutor-mode-bar'; bar.className = 'button-row tutor-mode-bar'; ['Explain', 'Hint', 'Socratic', 'Example', 'Quiz Me'].forEach(mode => { const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = labels[mode]; button.dataset.tutorMode = mode; button.onclick = () => { state.tutorMode = mode; document.querySelectorAll('[data-tutor-mode]').forEach(item => item.classList.toggle('active-range', item.dataset.tutorMode === mode)); const composer = $('#agent-form [name=message]'); if (composer) { composer.value = tutorInstruction(mode) + (composer.value.trim() ? `\n\n${composer.value.trim()}` : ''); composer.focus(); } }; bar.append(button); }); form.parentElement.insertBefore(bar, form); }
function openTutor(message, mode = state.tutorMode) { openView('ai'); ensureTutorModeBar(); const composer = $('#agent-form [name=message]'); if (composer) { composer.value = tutorInstruction(mode) + `\n\n${message}`; composer.focus(); } }
function renderPracticeRun() { const root = $('#practice-run'); if (!state.practice) { root.innerHTML = '<p class="task-meta">Select questions to begin.</p>'; return; } const current = state.practice.questions[state.practice.index]; if (!current) return; const options = String(current.options || '').split('\\n').map(item => item.trim()).filter(Boolean); root.innerHTML = `<p class="task-meta">${state.practice.index + 1} / ${state.practice.questions.length}</p><p class="practice-prompt math-text">${mathHtml(current.prompt)}</p>${options.length ? `<div class="practice-options">${options.map(option => `<label><input type="radio" name="choice" value="${escapeHtml(option)}"><span class="math-text">${mathHtml(option)}</span></label>`).join('')}</div>` : ''}<form id="practice-answer-form" class="practice-answer"><input name="response" autocomplete="off" placeholder="Answer" ${options.length ? '' : 'required'}><button class="primary">Submit</button></form>`; typesetMath(root); $('#practice-answer-form').onsubmit = async event => { event.preventDefault(); try { const formData = new FormData(event.target); const selected = root.querySelector('[name="choice"]:checked'); const response = selected ? selected.value : formData.get('response'); if (!response) { flash('Select an option or enter an answer.'); return; } const result = await api(`/practice-sessions/${state.practice.id}/questions/${current.id}/attempts`, { method: 'POST', body: JSON.stringify({ response, elapsed_seconds: 0 }) }); root.insertAdjacentHTML('beforeend', `<div class="practice-feedback ${result.correct ? 'correct' : 'incorrect'}"><strong>${result.correct ? 'Correct' : 'Recorded'}</strong>${current.explanation ? `<p class="math-text">${mathHtml(current.explanation)}</p>` : ''}<div class="practice-feedback-actions"><button type="button" class="secondary" id="ask-ai-practice">问 AI</button><button type="button" class="secondary" id="next-practice">${state.practice.index + 1 >= state.practice.questions.length ? 'Finish' : 'Next question'}</button></div></div>`); typesetMath(root); event.target.querySelector('button').disabled = true; $('#ask-ai-practice').onclick = () => openTutor(`我刚做完这道题：${current.prompt}\n我的答案是：${response}\n请用提示、举例和反问的方式帮助我理解，不要直接跳过推理。`); $('#next-practice').onclick = async () => { state.practice.index += 1; if (state.practice.index >= state.practice.questions.length) { const summary = await api(`/practice-sessions/${state.practice.id}/complete`, { method: 'POST' }); flash(`完成：${summary.correct}/${summary.total}，准确率 ${summary.accuracy}%`); if (summary.analysis_job_id) watchPracticeAnalysis(summary.analysis_job_id); state.practice = null; await loadPractice(); } else renderPracticeRun(); }; } catch (error) { flash(error.message); } }; }
async function watchJob(jobId, label) { const root = $('#rag-job'); for (let count = 0; count < 60; count += 1) { const job = await api(`/jobs/${jobId}`); root.innerHTML = `<strong>${escapeHtml(label)}</strong><p class="task-meta">Status: ${escapeHtml(job.status)}${job.detail ? ` · ${escapeHtml(job.detail)}` : ''}${job.error ? ` · ${escapeHtml(job.error)}` : ''}</p>`; if (job.status === 'completed') { const result = job.result || {}; if (result.ai_run_id) { const run = await api(`/ai-runs/${result.ai_run_id}`); const citations = (run.citations || []).map(citation => `<article class="citation"><strong>[${citation.number}]</strong> ${escapeHtml(citation.quote_text)}</article>`).join('') || '<p class="task-meta">No evidence found.</p>'; root.innerHTML = result.mode === 'generated' && result.answer ? `<strong>Answer</strong><p class="answer-text">${escapeHtml(result.answer)}</p><div class="citation-list">${citations}</div>` : `<strong>${escapeHtml(label)}</strong><p class="task-meta">Evidence search complete: ${result.evidence_count || 0} result(s). Configure an LLM to generate an answer.</p><div class="citation-list">${citations}</div>`; } return; } if (job.status === 'failed') return; await new Promise(resolve => setTimeout(resolve, 2000)); } root.innerHTML = `<strong>${escapeHtml(label)}</strong><p class="task-meta">Still processing. Refresh later.</p>`; }
async function watchGenerationJob(jobId) { const root = $('#generation-job'); for (let count = 0; count < 60; count += 1) { const job = await api(`/jobs/${jobId}`); root.innerHTML = `<strong>AI question generation</strong><p class="task-meta">Status: ${escapeHtml(job.status)}${job.detail ? ` · ${escapeHtml(job.detail)}` : ''}${job.error ? ` · ${escapeHtml(job.error)}` : ''}</p>`; if (job.status === 'completed') { const result = job.result || {}; root.innerHTML = `<strong>AI question generation</strong><p class="task-meta">Created ${Number(result.count || 0)} question draft(s) from ${Number(result.evidence_count || 0)} evidence chunk(s). Review them before practice.</p>`; await loadQuestionDrafts(); return; } if (job.status === 'failed') return; await new Promise(resolve => setTimeout(resolve, 2000)); } root.innerHTML = '<p class="task-meta">Still processing. Refresh later.</p>'; }
async function watchPracticeAnalysis(jobId) { const root = $('#practice-run'); for (let count = 0; count < 60; count += 1) { const job = await api(`/jobs/${jobId}`); if (job.status === 'completed') { const output = job.result?.output || {}; root.insertAdjacentHTML('beforeend', `<div class="practice-feedback"><strong>AI 学习分析已完成</strong><p>${escapeHtml(output.summary || output.answer || '已根据本次练习更新下一步建议。')}</p>${Array.isArray(output.recommendations) ? `<ul>${output.recommendations.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}</div>`); window.dispatchEvent(new CustomEvent('learning-data-updated', { detail: job.result })); if (job.result?.next_plan_job_id) watchAdaptivePlan(job.result.next_plan_job_id); return; } if (job.status === 'failed') { root.insertAdjacentHTML('beforeend', `<p class="error-text">学习分析失败：${escapeHtml(job.error || job.detail || '')}</p>`); return; } await new Promise(resolve => setTimeout(resolve, 2000)); } }
async function watchAdaptivePlan(jobId) { const root = $('#practice-run'); for (let count = 0; count < 60; count += 1) { const job = await api(`/jobs/${jobId}`); if (job.status === 'completed') { const count = Number(job.result?.created_task_count || 0); root.insertAdjacentHTML('beforeend', `<p class="task-meta">下一轮复习计划已写入 ${count} 个任务。</p>`); window.dispatchEvent(new CustomEvent('learning-data-updated', { detail: job.result })); return; } if (job.status === 'failed') return; await new Promise(resolve => setTimeout(resolve, 2000)); } }

$('#new-course').onclick = () => $('#course-form').classList.remove('hidden');
$('#new-task').onclick = () => { $('#task-form').classList.remove('hidden'); $('#task-form [name=planned_date]').value = new Date().toISOString().slice(0, 10); };
$('#new-goal').onclick = () => { $('#goal-form').classList.remove('hidden'); $('#goal-form [name=target_date]').value = new Date().toISOString().slice(0, 10); };
$('#new-knowledge-point').onclick = () => $('#knowledge-point-form').classList.remove('hidden');
$('#new-question').onclick = async () => { try { await ensureCourses(); $('#question-course').innerHTML = courseOptions(); const points = await api('/knowledge-points'); $('#question-knowledge').innerHTML = '<option value="">No linked knowledge point</option>' + points.map(point => '<option value="' + point.id + '">' + escapeHtml(point.name) + ' · ' + point.mastery + '%</option>').join(''); $('#question-form').classList.remove('hidden'); } catch (error) { flash(error.message); } };
$('#new-vocabulary').onclick = () => $('#vocabulary-form').classList.remove('hidden');
$('#generate-questions').onclick = () => { $('#generation-course').innerHTML = courseOptions('Select course'); $('#question-generation-form').classList.remove('hidden'); };
$('#start-recommended-practice').onclick = () => startRecommendedPractice();
$('#new-member').onclick = () => $('#member-form').classList.remove('hidden');
document.querySelectorAll('.analytics-range').forEach(button => button.onclick = () => loadAnalytics(Number(button.dataset.days)));
$('#generate-weekly-report').onclick = async () => { const root = $('#analytics-report'); root.classList.remove('hidden'); root.innerHTML = '<strong>正在生成学习周报…</strong><p class="task-meta">只使用你的真实学习记录，不会编造统计数据。</p>'; try { const result = await api('/ai/jobs', { method: 'POST', body: JSON.stringify({ feature: 'learning_report', request: '生成最近 7 天学习周报，包含学习时间、任务完成率、练习正确率、薄弱知识点和下周建议。', start_date: new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10), end_date: new Date().toISOString().slice(0, 10) }) }); watchAnalyticsReport(result.job_id); } catch (error) { root.innerHTML = `<p class="error-text">周报生成失败：${escapeHtml(error.message)}</p>`; } };
async function watchAnalyticsReport(jobId) { const root = $('#analytics-report'); for (let count = 0; count < 60; count += 1) { const job = await api(`/jobs/${jobId}`); root.innerHTML = `<strong>学习周报</strong><p class="task-meta">${escapeHtml(job.status)}${job.error ? ` · ${escapeHtml(job.error)}` : ''}</p>`; if (job.status === 'completed') { const output = job.result?.output || {}; root.innerHTML = `<strong>本周学习总结</strong><p>${escapeHtml(output.summary || '周报已生成。')}</p>${Array.isArray(output.recommendations) ? `<ul>${output.recommendations.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}`; return; } if (job.status === 'failed') return; await new Promise(resolve => setTimeout(resolve, 2000)); } }
async function showWeeklyReport() { const root = $('#analytics-report'); root.classList.remove('hidden'); root.textContent = '正在汇总真实学习记录…'; try { const report = await api('/weekly-report'); const stats = report.summary; root.innerHTML = ''; const heading = document.createElement('strong'); heading.textContent = '本周学习报告'; const detail = document.createElement('p'); detail.className = 'task-meta'; detail.textContent = report.range.start + ' 至 ' + report.range.end; const summary = document.createElement('p'); summary.textContent = '学习 ' + stats.study_minutes + ' min · 任务 ' + stats.tasks_completed + '/' + stats.tasks_total + ' · 练习 ' + stats.correct + '/' + stats.questions + '（' + stats.accuracy + '%）· 复习 ' + stats.reviews_correct + '/' + stats.reviews_total; const advice = document.createElement('p'); advice.textContent = report.recommendations[0] || '继续积累学习数据。'; root.append(heading, detail, summary, advice); if (report.weak_points.length) { const list = document.createElement('ul'); report.weak_points.slice(0, 3).forEach(point => { const item = document.createElement('li'); item.textContent = point.name + '：' + point.mastery + '%'; list.append(item); }); root.append(list); } return report; } catch (error) { root.textContent = '周报生成失败：' + error.message; return null; } }
async function generateWeeklyReportWithAi() {
  const report = await showWeeklyReport();
  if (!report) return;
  const root = $('#analytics-report');
  const dataSnapshot = root.innerHTML;
  root.insertAdjacentHTML('beforeend', '<p class="task-meta">AI 正在结合真实统计生成本周总结与下周建议…</p>');
  try {
    const result = await api('/ai/jobs', {
      method: 'POST',
      body: JSON.stringify({
        feature: 'learning_report',
        request: '基于最近 7 天的真实学习记录，生成简洁、可执行的学习总结，指出进步、风险和下周优先事项。',
        start_date: report.range.start,
        end_date: report.range.end,
      }),
    });
    for (let count = 0; count < 60; count += 1) {
      const job = await api(`/jobs/${result.job_id}`);
      if (job.status === 'completed') {
        const output = job.result?.output || {};
        const recommendations = Array.isArray(output.recommendations) ? output.recommendations : [];
        root.innerHTML = `${dataSnapshot}<section class="report-ai-insight"><h4>AI 解读与下周建议</h4><p>${escapeHtml(output.summary || 'AI 已根据本周学习数据完成解读。')}</p>${recommendations.length ? `<ul>${recommendations.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}</section>`;
        return;
      }
      if (job.status === 'failed') {
        root.innerHTML = `${dataSnapshot}<p class="error-text">AI 解读暂不可用：${escapeHtml(job.error || '任务失败')}</p>`;
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    root.innerHTML = `${dataSnapshot}<p class="task-meta">AI 解读仍在处理中，请稍后刷新查看。</p>`;
  } catch (error) {
    root.innerHTML = `${dataSnapshot}<p class="error-text">AI 解读暂不可用：${escapeHtml(error.message)}</p>`;
  }
}
$('#generate-weekly-report').onclick = generateWeeklyReportWithAi;
$('#new-agent-session').onclick = async () => { try { await createAgentSession(); } catch (error) { flash(error.message); } };
$('#refresh-resources').onclick = async () => { await loadResources(); await loadKnowledgeDrafts(); };
$('#refresh-knowledge-drafts').onclick = loadKnowledgeDrafts;
document.querySelectorAll('[data-close-form]').forEach(button => button.onclick = () => $(`#${button.dataset.closeForm}`).classList.add('hidden'));
$('#course-form').onsubmit = async event => { event.preventDefault(); try { await api('/courses', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) }); event.target.reset(); event.target.classList.add('hidden'); state.courses = []; flash('Course created'); loadCourses(); } catch (error) { flash(error.message); } };
$('#task-form').onsubmit = async event => { event.preventDefault(); try { const data = Object.fromEntries(new FormData(event.target)); data.duration_minutes = Number(data.duration_minutes); data.course_id = data.course_id ? Number(data.course_id) : null; await api('/tasks', { method: 'POST', body: JSON.stringify(data) }); event.target.classList.add('hidden'); flash('Task created'); loadTasks(); } catch (error) { flash(error.message); } };
setInterval(async () => { if (!state.token) return; try { const tasks = await api('/tasks?start=' + new Date().toISOString().slice(0, 10) + '&end=' + new Date().toISOString().slice(0, 10)); const now = new Date(); const key = `${now.toISOString().slice(0, 10)} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`; const task = tasks.find(item => !item.completed && item.scheduled_time && `${item.planned_date} ${item.scheduled_time}` === key); const noticeKey = task && `study-notice:${task.id}:${key}`; if (task && noticeKey && !localStorage.getItem(noticeKey) && 'Notification' in window) { localStorage.setItem(noticeKey, '1'); if (Notification.permission === 'default') await Notification.requestPermission(); if (Notification.permission === 'granted') new Notification('学习提醒', { body: task.title }); } } catch (_) {} }, 60000);
$('#goal-form').onsubmit = async event => { event.preventDefault(); try { const data = Object.fromEntries(new FormData(event.target)); data.weekly_minutes = Number(data.weekly_minutes); data.target_score = data.target_score ? Number(data.target_score) : null; data.course_id = data.course_id ? Number(data.course_id) : null; await api('/goals', { method: 'POST', body: JSON.stringify(data) }); event.target.reset(); event.target.classList.add('hidden'); flash('Goal created'); loadGoals(); } catch (error) { flash(error.message); } };
$('#knowledge-point-form').onsubmit = async event => { event.preventDefault(); try { const data = Object.fromEntries(new FormData(event.target)); data.course_id = Number(data.course_id); data.difficulty = Number(data.difficulty); data.importance = Number(data.importance); await api('/knowledge-points', { method: 'POST', body: JSON.stringify(data) }); event.target.reset(); event.target.classList.add('hidden'); flash('Knowledge point created'); loadGoals(); } catch (error) { flash(error.message); } };
$('#question-form').onsubmit = async event => { event.preventDefault(); try { const data = Object.fromEntries(new FormData(event.target)); data.course_id = data.course_id ? Number(data.course_id) : null; data.knowledge_point_id = data.knowledge_point_id ? Number(data.knowledge_point_id) : null; data.difficulty = Number(data.difficulty); await api('/questions', { method: 'POST', body: JSON.stringify(data) }); event.target.reset(); event.target.classList.add('hidden'); flash('Question saved'); loadPractice(); } catch (error) { flash(error.message); } };
$('#vocabulary-form').onsubmit = async event => { event.preventDefault(); try { await api('/vocabulary', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) }); event.target.reset(); event.target.classList.add('hidden'); flash('Word added to spaced review'); loadVocabulary(); } catch (error) { flash(error.message); } };
$('#question-generation-form').onsubmit = async event => { event.preventDefault(); try { const data = Object.fromEntries(new FormData(event.target)); data.course_id = Number(data.course_id); data.count = Number(data.count); data.difficulty = Number(data.difficulty); data.kinds = data.kinds === 'mixed' ? ['single_choice', 'short_answer'] : [data.kinds]; const result = await api('/ai/question-generation/jobs', { method: 'POST', body: JSON.stringify(data) }); event.target.classList.add('hidden'); flash('AI question generation submitted'); watchGenerationJob(result.job_id); } catch (error) { flash(error.message); } };
$('#start-practice').onclick = async () => { const ids = [...document.querySelectorAll('[data-question-select]:checked')].map(item => Number(item.dataset.questionSelect)); if (!ids.length) return flash('Select at least one question'); try { const session = await api('/practice-sessions', { method: 'POST', body: JSON.stringify({ question_ids: ids }) }); state.practice = { id: session.id, questions: state.questions.filter(question => ids.includes(question.id)), index: 0 }; renderPracticeRun(); flash('Practice started'); } catch (error) { flash(error.message); } };
$('#resource-form').onsubmit = async event => { event.preventDefault(); try { const data = new FormData(event.target); if (!data.get('course_id')) data.delete('course_id'); const result = await api('/resources', { method: 'POST', body: data }); flash('Resource uploaded; indexing started'); event.target.reset(); watchJob(result.job_id, 'Resource indexing'); loadResources(); } catch (error) { flash(error.message); } };
$('#rag-form').onsubmit = async event => { event.preventDefault(); try { const data = Object.fromEntries(new FormData(event.target)); data.course_id = data.course_id ? Number(data.course_id) : null; const result = await api('/rag/jobs', { method: 'POST', body: JSON.stringify(data) }); flash('Evidence search submitted'); watchJob(result.job_id, 'Evidence search'); } catch (error) { flash(error.message); } };
  $('#agent-form').onsubmit = async event => { event.preventDefault(); let pending = null; try { if (!state.agentSessionId) await createAgentSession(); const data = Object.fromEntries(new FormData(event.target)); const selectedCourseId = Number($('#agent-course')?.value) || state.activeCourseId || null; data.course_id = data.course_id ? Number(data.course_id) : selectedCourseId; const root = $('#agent-messages'); const user = data.message.trim(); root.insertAdjacentHTML('beforeend', `<article class="agent-message user"><strong>You</strong><div>${escapeHtml(user)}</div></article><article class="agent-message assistant thinking"><strong>Learning Agent</strong><div>Thinking...</div></article>`); pending = root.querySelector('.thinking'); root.scrollTop = root.scrollHeight; event.target.querySelector('[name=message]').value = ''; const sessionId = normalizeAgentSessionId(state.agentSessionId); const response = await fetch(`/v1/agent/sessions/${sessionId}/messages/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${state.token}` }, body: JSON.stringify(data) }); if (!response.ok || !response.body) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Agent request failed (${response.status})`); } const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '', answer = '', thinking = pending; while (true) { const part = await reader.read(); if (part.done) break; buffer += decoder.decode(part.value, { stream: true }); const events = buffer.split('\n\n'); buffer = events.pop(); for (const event of events) { const name = event.match(/^event: (.+)$/m)?.[1]; const raw = event.match(/^data: (.+)$/m)?.[1]; if (!raw) continue; const payload = JSON.parse(raw); if (name === 'token') { answer += payload.text; if (thinking) { thinking.classList.remove('thinking'); thinking.querySelector('div').textContent = answer; } } if (name === 'intent' && thinking) thinking.querySelector('div').textContent = `Understanding intent: ${(payload.actions || []).join(', ')}...`; if (name === 'done') { state.agentSessions = await api('/agent/sessions'); renderAgentSessions(); } } } } catch (error) { const message = `Error: ${error.message}`; flash(message); if (pending) { pending.classList.remove('thinking'); pending.classList.add('error'); pending.querySelector('div').textContent = message; } } };
$('#member-form').onsubmit = async event => { event.preventDefault(); try { await api('/organization/members', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) }); event.target.reset(); event.target.classList.add('hidden'); flash('Member added'); loadMembers(); } catch (error) { flash(error.message); } };
$('#logout').onclick = async () => { try { if (state.refreshToken) await fetch('/v1/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: state.refreshToken }) }); } finally { showAuth(); } };
ensureTutorModeBar();
const allAnalyticsButton = document.createElement('button'); allAnalyticsButton.type = 'button'; allAnalyticsButton.className = 'secondary analytics-range'; allAnalyticsButton.dataset.days = 'all'; allAnalyticsButton.textContent = 'All time'; allAnalyticsButton.onclick = () => loadAnalytics('all'); document.querySelector('.analytics-range[data-days="30"]')?.insertAdjacentElement('afterend', allAnalyticsButton);
$('#generate-questions').onclick = async () => { try { await prepareQuestionGenerationForm(); $('#question-generation-form').classList.remove('hidden'); } catch (error) { flash(error.message); } };
$('#question-generation-form').onsubmit = async event => { event.preventDefault(); try { const data = questionGenerationPayload(event.target); const result = await api('/ai/question-generation/jobs', { method: 'POST', body: JSON.stringify(data) }); event.target.classList.add('hidden'); flash('AI question generation submitted'); watchGenerationJob(result.job_id); } catch (error) { flash(error.message); } };
if (state.token) api('/me').then(user => { state.user = user; showApp(); }).catch(showAuth);
window.addEventListener('learning-data-updated', () => {
  const view = document.querySelector('.sidebar .nav-item.active')?.dataset.view;
  if (view) void loadCurrentView(view);
  void loadDashboard();
});
$('#task-course').onchange = renderTaskKnowledgeOptions;
$('#task-form').onsubmit = async event => { event.preventDefault(); try { const data = Object.fromEntries(new FormData(event.target)); data.duration_minutes = Number(data.duration_minutes); data.course_id = data.course_id ? Number(data.course_id) : null; data.knowledge_point_id = data.knowledge_point_id ? Number(data.knowledge_point_id) : null; await api('/tasks', { method: 'POST', body: JSON.stringify(data) }); event.target.reset(); event.target.classList.add('hidden'); renderTaskKnowledgeOptions(); flash('Task created'); loadTasks(); } catch (error) { flash(error.message); } };
const openCourseBase = openCourse;
openCourse = async courseId => { await openCourseBase(courseId); try { const data = await api(`/courses/${courseId}/workspace`); const grid = $('#course-list .content-grid'); if (!grid) return; const section = document.createElement('section'); section.innerHTML = `<h4>近期任务</h4><div class="list">${data.recent_tasks.map(taskRow).join('') || '<span class="task-meta">暂无近期任务。</span>'}</div>`; grid.append(section); bindTaskActions(() => openCourse(courseId)); } catch (error) { flash(error.message); } };
window.addEventListener('practice-ready', async event => {
  const result = event.detail || {};
  if (!result.practice_session_id || !Array.isArray(result.question_ids)) return;
  try {
    state.questions = await api('/questions');
    const questions = state.questions.filter(item => result.question_ids.includes(item.id));
    state.practice = { id: result.practice_session_id, questions, index: 0 };
    openView('practice');
    renderPracticeRun();
    flash('题目已生成，练习已自动开始');
  } catch (error) { flash(`无法打开自动练习：${error.message}`); }
});
function appendStreamDownload(target, payload) { if (!target || !payload?.url) return; const link = document.createElement('a'); link.className = 'download-link'; link.href = payload.url; link.textContent = payload.label || 'Download report'; link.onclick = async event => { event.preventDefault(); try { await downloadAgentReport(payload.url); } catch (error) { flash(error.message); } }; target.appendChild(document.createElement('br')); target.appendChild(link); }
const agentDownloadObserver = new MutationObserver(() => { const root = $('#agent-messages'); if (!root) return; root.querySelectorAll('.agent-message div').forEach(node => { if (node.dataset.downloadBound) return; const match = node.textContent.match(/(\/v1\/agent\/sessions\/\d+\/downloads\/\d+)/); if (!match) return; node.dataset.downloadBound = '1'; node.innerHTML = escapeHtml(node.textContent.replace(match[1], '')).replace(/\n/g, '<br>') + `<br><a class="download-link" href="${match[1]}" data-download-url="${match[1]}">Download report</a>`; bindAgentDownloads(root); }); });
agentDownloadObserver.observe(document.body, { subtree: true, childList: true, characterData: true });
function parseRichTextClient(text) { const source = String(text || ''); const classic = /(?:^|\n)\s*(\d+)\.\s+([^\n]+)\n((?:\s*[A-H][\.)]\s+[^\n]+\n?)+)/g; const classicMatches = [...source.matchAll(classic)]; if (classicMatches.length) { const questions = classicMatches.map(match => ({ number: Number(match[1]), prompt: match[2].trim(), options: [...match[3].matchAll(/^\s*([A-H])[\.)]\s+(.+?)\s*$/gm)].map(item => ({ id: item[1], label: item[2].trim() })) })).filter(question => question.options.length); return questions.length ? [{ type: 'markdown', content: source.slice(0, classicMatches[0].index || 0).trim() }, { type: 'quiz', questions }] : null; } const heading = /(?:^|\n)\s*(?:\*\*)?\s*(?:第\s*)?(\d+)\s*(?:题(?:[（(][^\n）)]*[）)])?|[\.)])\s*(?:\*\*)?\s*\n/gm; const matches = [...source.matchAll(heading)]; const questions = []; matches.forEach((match, index) => { const start = (match.index || 0) + match[0].length; const end = index + 1 < matches.length ? (matches[index + 1].index || source.length) : source.length; const body = source.slice(start, end).trim(); const optionMatches = [...body.matchAll(/^\s*([A-H])[\.)、]\s+(.+?)\s*$/gm)]; if (!optionMatches.length) return; const firstOption = optionMatches[0].index || 0; questions.push({ number: Number(match[1]), prompt: body.slice(0, firstOption).trim(), options: optionMatches.map(item => ({ id: item[1], label: item[2].trim() })) }); }); return questions.length ? [{ type: 'markdown', content: source.slice(0, matches[0].index || 0).trim() }, { type: 'quiz', questions }] : null; }
const richStreamObserver = new MutationObserver(() => { document.querySelectorAll('.agent-message.assistant:not([data-rich-bound])').forEach(node => { const body = node.querySelector('div'); if (!body || node.classList.contains('thinking')) return; const parsed = parseRichTextClient(body.textContent); if (!parsed) return; node.dataset.richBound = '1'; body.innerHTML = renderRichBlocks(parsed); bindRichQuizzes(node); }); });
richStreamObserver.observe(document.body, { subtree: true, childList: true, characterData: true });
taskRow = task => { const status = task.status || (task.completed ? 'completed' : 'planned'); const context = [task.course_name ? `课程：${task.course_name}` : '未关联课程', task.knowledge_point_name ? `知识点：${task.knowledge_point_name}` : '未关联知识点', task.source ? `来源：${task.source}` : ''].filter(Boolean).join(' · '); const actions = task.completed ? `<span class="complete">${status === 'skipped' ? '已跳过' : '已完成'}</span>` : `<div class="task-actions">${status === 'planned' ? `<button class="secondary" data-task-action="start" data-task-id="${task.id}">开始</button>` : '<span class="task-meta">进行中</span>'}<button class="primary" data-task-action="complete" data-task-id="${task.id}">完成</button><button class="text-button" data-task-action="postpone" data-task-id="${task.id}">明天</button><button class="text-button" data-task-action="skip" data-task-id="${task.id}">跳过</button><button class="text-button" data-task-adjust="${task.id}" data-task-date="${task.planned_date}">调整</button></div>`; return `<article class="list-row"><div><strong>${escapeHtml(task.title)}</strong><div class="task-meta">${task.planned_date} · ${task.duration_minutes} min${task.scheduled_time ? ` · reminder ${task.scheduled_time}` : ''}</div><div class="task-meta">${escapeHtml(context)}</div>${task.note ? `<div class="task-meta">备注：${escapeHtml(task.note)}</div>` : ''}<button type="button" class="text-button" data-task-learn="${task.id}">学习本任务</button><div class="task-learning-panel hidden" data-task-learning-panel="${task.id}"></div></div>${actions}</article>`; };
document.addEventListener('click', async event => { const learn = event.target.closest('[data-task-learn]'); if (learn) { openTaskLearning(Number(learn.dataset.taskLearn), Number(learn.closest('[data-course-id]')?.dataset.courseId || state.activeCourseId || 0)); return; } const button = event.target.closest('[data-task-adjust]'); if (!button || button.dataset.adjustBound) return; button.dataset.adjustBound = '1'; const plannedDate = window.prompt('调整任务日期（YYYY-MM-DD）', button.dataset.taskDate || new Date().toISOString().slice(0, 10)); if (!plannedDate) return; try { await api(`/tasks/${button.dataset.taskAdjust}`, { method: 'PATCH', body: JSON.stringify({ planned_date: plannedDate }) }); flash('任务已调整'); const view = document.querySelector('.sidebar .nav-item.active')?.dataset.view; await loadCurrentView(view); } catch (error) { flash(error.message); } });
const openCourseWorkspace = openCourse;
openCourse = async courseId => { state.activeCourseId = courseId; await openCourseWorkspace(courseId); try { const data = await api(`/courses/${courseId}/workspace`); const root = $('#course-list .workspace-card'); if (!root || root.querySelector('.course-workspace-nav')) return; const nav = document.createElement('div'); nav.className = 'workspace-tabs course-workspace-nav'; nav.innerHTML = '<button class="primary" data-course-view="overview">概览</button><button class="secondary" data-course-view="goals">计划</button><button class="secondary" data-course-view="knowledge">知识</button><button class="secondary" data-course-view="resources">资料</button><button class="secondary" data-course-view="practice">练习</button><button class="secondary" data-course-view="mistakes">错题</button><button class="secondary" data-course-view="analytics">分析</button>'; root.querySelector('.course-hero')?.insertAdjacentElement('afterend', nav); const metrics = document.createElement('div'); metrics.className = 'metrics course-workspace-metrics'; metrics.innerHTML = [['知识点', data.knowledge.length], ['资料', data.resource_count], ['题目', data.question_count], ['错题', data.mistake_count], ['练习正确率', `${data.practice.accuracy}%`]].map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join(''); nav.insertAdjacentElement('afterend', metrics); root.querySelectorAll('[data-course-view]').forEach(button => { button.onclick = () => { if (button.dataset.courseView === 'overview') return; openView(button.dataset.courseView); }; }); } catch (error) { flash(error.message); } };
function configureProductNavigation() { const nav = document.querySelector('.sidebar nav'); if (!nav || nav.dataset.configured) return; nav.dataset.configured = '1'; const labels = { today: '学习中心', courses: '学习内容', goals: '学习内容', practice: '练习复盘', mistakes: '练习复盘', analytics: '学习洞察', resources: '学习资料', vocabulary: '学习资料', ai: 'AI 助手', tasks: '学习管理', members: '学习管理' }; const names = { today: '今日学习', courses: '我的课程', tasks: '学习任务', goals: '学习计划', practice: '练习与复习', mistakes: '错题本', analytics: '学习分析', vocabulary: '词汇复习', resources: '学习资料库', ai: 'AI 学习助手', members: '团队成员' }; let current = ''; [...nav.querySelectorAll('.nav-item')].forEach(button => { const view = button.dataset.view; if (labels[view] !== current) { current = labels[view]; const label = document.createElement('span'); label.className = 'nav-group-label'; label.textContent = current; nav.insertBefore(label, button); } button.textContent = names[view] || view; button.setAttribute('aria-label', names[view] || view); }); }
configureProductNavigation();
function localizeStaticProductCopy() {
  const text = (selector, value) => { const node = document.querySelector(selector); if (node) node.textContent = value; };
  const labelText = (selector, value) => { const node = document.querySelector(selector); const textNode = node && [...node.childNodes].find(child => child.nodeType === Node.TEXT_NODE); if (textNode) textNode.nodeValue = value; };
  const placeholder = (selector, value) => { const node = document.querySelector(selector); if (node) node.setAttribute('placeholder', value); };
  const option = (selector, value) => { const node = document.querySelector(selector); if (node) node.textContent = value; };
  text('#logout', '退出登录');
  text('#mistakes-view .section-head h3', '错题本');
  text('#mistakes-view [data-view="practice"]', '复习错题');
  text('#analytics-view .section-head h3', '学习分析');
  text('#analytics-view .analytics-range[data-days="7"]', '近 7 天');
  text('#analytics-view .analytics-range[data-days="30"]', '近 30 天');
  text('#tasks-view .section-head h3', '学习任务');
  text('#new-task', '新建任务');
  placeholder('#task-form [name=title]', '任务名称');
  option('#task-course option[value=""]', '未选择课程');
  option('#task-knowledge option[value=""]', '未关联知识点');
  text('#goals-view .section-head h3', '学习计划与知识');
  text('#new-goal', '新建目标');
  text('#new-knowledge-point', '新增知识点');
  placeholder('#goal-form [name=title]', '学习目标');
  option('#goal-course option[value=""]', '未选择课程');
  option('#knowledge-course option[value=""]', '请选择课程');
  placeholder('#knowledge-point-form [name=name]', '知识点名称');
  placeholder('#knowledge-point-form [name=category]', '分类');
  placeholder('#knowledge-point-form [name=definition]', '定义或说明');
  text('#practice-view .section-head h3', '练习与复习');
  text('#generate-questions', 'AI 生成题目');
  text('#new-question', '新建题目');
  text('#start-practice', '开始所选练习');
  option('#generation-course option[value=""]', '请选择课程');
  placeholder('#question-generation-form [name=request]', '输入知识点或学习目标');
  placeholder('#question-form [name=prompt]', '题目内容');
  placeholder('#question-form [name=answer]', '参考答案');
  option('#question-course option[value=""]', '未选择课程');
  option('#question-knowledge option[value=""]', '未关联知识点');
  text('#practice-view .content-grid > section:first-child .section-head h3', '题库');
  text('#generation-job .task-meta', 'AI 生成完成后，题目会显示在这里。');
  text('#practice-view .content-grid > section:last-child .subhead', '当前练习');
  text('#practice-run .task-meta', '选择题目后开始练习。');
  $('#practice-view #review-list')?.previousElementSibling?.replaceChildren('待复习');
  text('#vocabulary-view .section-head h3', '词汇复习');
  text('#new-vocabulary', '新增词汇');
  placeholder('#vocabulary-form [name=word]', '单词');
  placeholder('#vocabulary-form [name=meaning]', '释义');
  placeholder('#vocabulary-form [name=example]', '例句');
  text('#resources-view .section-head > h3', '学习资料库');
  text('#resources-view .content-grid > section:first-child > h3', '上传学习资料');
  labelText('#resource-form label:first-child', '文件');
  labelText('#resource-form label:nth-child(2)', '课程');
  text('#resource-form button[type=submit]', '上传并建立索引');
  text('#resources-view .content-grid > section:first-child .subhead h3', '资料库');
  text('#refresh-resources', '刷新');
  text('#resources-view .content-grid > section:last-child > h3', '证据检索');
  labelText('#rag-form label:first-child', '问题');
  labelText('#rag-form label:nth-child(2)', '课程');
  placeholder('#rag-form [name=question]', '询问已索引的学习资料');
  option('#rag-course option[value=""]', '全部课程');
  text('#rag-form button[type=submit]', '检索证据');
  text('#resources-view .content-grid > section:last-child .subhead h3', '任务状态');
  text('#rag-job .task-meta', '提交的检索任务会显示在这里。');
  text('#ai-view .section-head h3', 'AI 学习助手');
  text('#new-agent-session', '新建对话');
  text('#agent-messages .task-meta', '创建一段对话，开始你的个性化学习。');
  const composer = $('#agent-form [name=message]');
  if (composer) composer.setAttribute('placeholder', '输入学习问题、目标或想让 AI 帮你完成的下一步…');
  text('#agent-form button[type=submit]', '发送');
  text('#members-view .section-head h3', '团队成员');
  text('#new-member', '添加成员');
}
localizeStaticProductCopy();
const productShowApp = showApp;
showApp = () => {
  productShowApp();
  const label = $('#org-label');
  if (label) label.textContent = state.user?.organization_name || 'Your learning space';
  // The base shell loads Today directly on sign-in, so synchronize the browser
  // title with the already-active sidebar item.
  const activeView = document.querySelector('.sidebar .nav-item.active')?.dataset.view || 'today';
  if (activeView === 'today' || activeView === 'dashboard') document.title = '今日学习 · Learning Space';
};
loadMistakes = async () => { try { const suffix = state.activeCourseId ? `?course_id=${state.activeCourseId}` : ''; const mistakes = await api(`/mistakes${suffix}`); $('#mistake-list').innerHTML = mistakes.map(item => `<article class="mistake-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">${escapeHtml(item.knowledge_point || '未关联知识点')} · ${escapeHtml(item.error_type)} · 错 ${item.wrong_count} 次</div><div class="task-meta">我的答案：${escapeHtml(item.user_answer || '未记录')} · 正确答案：${escapeHtml(item.correct_answer || '未记录')}</div><div class="task-meta">AI 分析：${escapeHtml(item.ai_analysis || '完成一次复习后，系统会补充分析。')}</div><div class="task-meta">创建：${escapeHtml(item.created_at ? item.created_at.slice(0, 10) : '未知')} · 下次复习：${escapeHtml(item.next_review)}</div></div><button class="secondary" data-view="practice">开始复习</button></article>`).join('') || '<div class="empty-state"><strong>还没有错题</strong><span>完成一次练习并答错题目后，系统会自动建立错题记录。</span><button class="primary" data-view="practice">去做练习</button></div>'; bindViewButtons(); } catch (error) { flash(error.message); } };
queueKnowledgeExtraction = async (resourceId, courseId, resourceName) => { const root = $('#rag-job'); root.innerHTML = `<strong>正在分析 ${escapeHtml(resourceName)}…</strong><p class="task-meta">AI 只会读取这份资料的已索引证据，生成的知识点仍需确认后才进入正式知识库。</p>`; try { const result = await api('/ai/jobs', { method: 'POST', body: JSON.stringify({ feature: 'knowledge_extraction', course_id: courseId, resource_ids: [resourceId], request: `从资料 ${resourceName} 提取课程知识点，并为每个知识点保留证据引用。` }) }); watchJob(result.job_id, 'Knowledge extraction'); } catch (error) { root.innerHTML = `<p class="error-text">知识抽取失败：${escapeHtml(error.message)}</p>`; } };
async function queueResourceSummary(resourceId, courseId, resourceName) {
  const root = $('#rag-job');
  root.innerHTML = `<strong>正在总结 ${escapeHtml(resourceName)}…</strong><p class="task-meta">系统会从已索引资料中检索证据，再生成可追溯的学习摘要。</p>`;
  try {
    const result = await api('/rag/jobs', { method: 'POST', body: JSON.stringify({ course_id: courseId, question: `请总结学习资料《${resourceName}》的核心概念、结构和下一步学习建议，并给出引用证据。` }) });
    watchJob(result.job_id, '资料 AI 总结');
  } catch (error) { root.innerHTML = `<p class="error-text">资料总结失败：${escapeHtml(error.message)}</p>`; }
}
async function queueResourcePractice(resourceId, courseId, resourceName) {
  try {
    const result = await api('/ai/question-generation/jobs', {
      method: 'POST',
      body: JSON.stringify({
        course_id: courseId,
        resource_ids: [resourceId],
        request: `根据资料《${resourceName}》生成一组覆盖核心概念的练习题。`,
        count: 5,
        difficulty: 3,
        kinds: ['single_choice', 'short_answer'],
      }),
    });
    flash('资料练习已提交，完成后请在 Practice 审核题目草稿。');
    openView('practice');
    watchGenerationJob(result.job_id);
  } catch (error) { flash(`资料练习生成失败：${error.message}`); }
}
loadResources = async () => { try { await ensureCourses(); $('#resource-course').innerHTML = courseOptions(); $('#rag-course').innerHTML = courseOptions('All courses'); const suffix = state.activeCourseId ? `?course_id=${state.activeCourseId}` : ''; const resources = await api(`/resources${suffix}`); $('#resource-list').innerHTML = resources.map(resource => `<article class="list-row"><div><strong>${escapeHtml(resource.name)}</strong><div class="task-meta">${Math.ceil(resource.size / 1024)} KB · ${resource.course_id ? `Course #${resource.course_id}` : 'No course'}</div></div>${resource.course_id ? `<div class="button-row resource-actions"><button class="text-button" data-resource-summary="${resource.id}" data-resource-course="${resource.course_id}" data-resource-name="${escapeHtml(resource.name)}">AI 总结</button><button class="text-button" data-extract-resource="${resource.id}" data-resource-course="${resource.course_id}" data-resource-name="${escapeHtml(resource.name)}">提取知识</button><button class="text-button" data-resource-practice="${resource.id}" data-resource-course="${resource.course_id}" data-resource-name="${escapeHtml(resource.name)}">生成练习</button><button class="text-button" data-resource-tutor="${resource.id}" data-resource-course="${resource.course_id}" data-resource-name="${escapeHtml(resource.name)}">问 AI</button></div>` : '<span class="task-meta">先关联课程</span>'}</article>`).join('') || '<div class="empty-state"><strong>还没有学习资料</strong><span>上传教材、讲义或题目资料，系统会建立可引用的个人知识库。</span></div>'; document.querySelectorAll('[data-extract-resource]').forEach(button => button.onclick = () => queueKnowledgeExtraction(Number(button.dataset.extractResource), Number(button.dataset.resourceCourse), button.dataset.resourceName)); document.querySelectorAll('[data-resource-summary]').forEach(button => button.onclick = () => queueResourceSummary(Number(button.dataset.resourceSummary), Number(button.dataset.resourceCourse), button.dataset.resourceName)); document.querySelectorAll('[data-resource-practice]').forEach(button => button.onclick = () => queueResourcePractice(Number(button.dataset.resourcePractice), Number(button.dataset.resourceCourse), button.dataset.resourceName)); document.querySelectorAll('[data-resource-tutor]').forEach(button => button.onclick = () => openTutor(`我正在学习资料《${button.dataset.resourceName}》。请先检索课程资料中的相关证据，再用 ${state.tutorMode} 模式帮助我理解并检查掌握情况。`)); restoreRememberedResourceJob(); } catch (error) { flash(error.message); } };
loadTasks = async () => { try { await ensureCourses(); $('#task-course').innerHTML = courseOptions(); const suffix = state.activeCourseId ? `?course_id=${state.activeCourseId}` : ''; state.taskKnowledgePoints = await api(`/knowledge-points${suffix}`); renderTaskKnowledgeOptions(); const tasks = await api(`/tasks${suffix}`); $('#task-list').innerHTML = tasks.map(taskRow).join('') || '<span class="task-meta">No tasks yet.</span>'; bindTaskActions(loadTasks); } catch (error) { flash(error.message); } };
loadGoals = async () => { try { await ensureCourses(); $('#goal-course').innerHTML = courseOptions(); $('#knowledge-course').innerHTML = courseOptions('Select course'); const suffix = state.activeCourseId ? `?course_id=${state.activeCourseId}` : ''; const [goals, points] = await Promise.all([api(`/goals${suffix}`), api(`/knowledge-points${suffix}`)]); const courseName = id => escapeHtml(state.courses.find(course => course.id === id)?.name || 'No course'); $('#goal-list').innerHTML = goals.map(goal => `<article class="list-row"><div><strong>${escapeHtml(goal.title)}</strong><div class="task-meta">Due ${goal.target_date} · ${goal.weekly_minutes} min/week${goal.target_score === null ? '' : ` · score ${goal.target_score}`}</div></div><div class="goal-actions"><span class="task-meta">${escapeHtml(goal.status)} · ${goal.progress}%</span>${goal.course_id ? `<button class="text-button" data-plan-goal="${goal.id}">生成计划</button>` : ''}</div></article>`).join('') || '<span class="task-meta">No goals yet.</span>'; $('#knowledge-point-list').innerHTML = points.map(point => `<article class="list-row"><div><strong>${escapeHtml(point.name)}</strong><div class="task-meta">${courseName(point.course_id)} · ${escapeHtml(point.category)} · difficulty ${point.difficulty}/5</div></div><span class="task-meta">Mastery ${point.mastery}% · ${point.practice_count || 0} 次练习</span></article>`).join('') || '<span class="task-meta">No knowledge points yet.</span>'; document.querySelectorAll('[data-plan-goal]').forEach(button => button.onclick = () => queueLearningPlan(Number(button.dataset.planGoal))); } catch (error) { flash(error.message); } };
loadAnalytics = async (days = 7) => { try { const suffix = state.activeCourseId ? `&course_id=${state.activeCourseId}` : ''; const data = await api(`/analytics?days=${days}${suffix}`); const summary = data.summary; $('#analytics-metrics').innerHTML = [['学习时间', `${summary.study_minutes} min`], ['任务完成', `${summary.tasks_completed}/${summary.tasks_total}`], ['练习正确率', `${summary.accuracy}%`], ['待复习', `${summary.due_reviews} 项`]].map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join(''); $('#analytics-daily').innerHTML = data.daily.map(item => `<article class="analytics-day"><div><strong>${item.date.slice(5)}</strong><span>${item.minutes} min · ${item.questions} 题</span></div><div class="analytics-track"><i style="width:${Math.min(100, item.minutes * 2)}%"></i></div><b>${item.accuracy}%</b></article>`).join(''); $('#analytics-errors').innerHTML = data.error_types.map(item => `<article class="list-row"><span>${escapeHtml(item.type)}</span><strong>${item.count}</strong></article>`).join('') || '<span class="task-meta">还没有足够的错题数据。</span>'; $('#analytics-weak').innerHTML = data.weak_points.map(item => `<article class="list-row"><span>${escapeHtml(item.name)}</span><strong>${item.mastery}%</strong></article>`).join('') || '<span class="task-meta">还没有识别出薄弱知识点。</span>'; document.querySelectorAll('.analytics-range').forEach(button => button.classList.toggle('active-range', String(button.dataset.days) === String(days))); } catch (error) { flash(error.message); } };
loadPractice = async () => { try { await ensureCourses(); $('#question-course').innerHTML = courseOptions(); const suffix = state.activeCourseId ? `?course_id=${state.activeCourseId}` : ''; state.questions = await api(`/questions${suffix}`); $('#question-list').innerHTML = state.questions.map(question => { const options = String(question.options || '').split('\\n').map(item => item.trim()).filter(Boolean); return `<label class="list-row question-row"><input type="checkbox" data-question-select="${question.id}"><div class="question-copy"><strong class="math-text">${mathHtml(question.prompt)}</strong>${options.length ? `<div class="question-options">${options.map(option => `<span class="math-text">${mathHtml(option)}</span>`).join('')}</div>` : ''}<div class="task-meta">${escapeHtml(question.kind)} · 难度 ${question.difficulty}</div></div></label>`; }).join('') || '<span class="task-meta">还没有题目，请新建题目或使用 AI 生成。</span>'; typesetMath($('#question-list')); const reviews = await api(`/reviews?due_only=true${state.activeCourseId ? `&course_id=${state.activeCourseId}` : ''}`); $('#review-list').innerHTML = reviews.map(review => `<article class="list-row"><div><strong class="math-text">${mathHtml(review.title)}</strong><div class="task-meta">错 ${review.wrong_count} 次 · ${review.next_review}</div></div><select data-review="${review.id}"><option value="correct">已掌握</option><option value="wrong">还未掌握</option><option value="postpone">明天复习</option></select></article>`).join('') || '<span class="task-meta">暂无到期复习。</span>'; typesetMath($('#review-list')); document.querySelectorAll('[data-review]').forEach(select => select.onchange = async () => { try { await api(`/reviews/${select.dataset.review}/attempts`, { method: 'POST', body: JSON.stringify({ result: select.value }) }); flash('已记录复习结果'); loadPractice(); } catch (error) { flash(error.message); } }); renderPracticeRun(); } catch (error) { flash(error.message); } };
function activeViewName() { return document.querySelector('.sidebar .nav-item.active')?.dataset.view || 'today'; }
function ensureViewStatus(view) { const root = document.querySelector(`#${view}-view`); if (!root) return null; let status = root.querySelector(':scope > .view-status'); if (!status) { status = document.createElement('div'); status.className = 'view-status'; status.hidden = true; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); root.insertBefore(status, root.firstChild); } return status; }
function setViewStatus(view, statusName, message = '') { const root = document.querySelector(`#${view}-view`); const status = ensureViewStatus(view); if (!root || !status) return; root.dataset.viewState = statusName; root.setAttribute('aria-busy', statusName === 'loading' ? 'true' : 'false'); status.className = `view-status ${statusName}`; status.hidden = !message; status.innerHTML = statusName === 'loading' ? `<span class="status-spinner" aria-hidden="true"></span><span class="status-copy">${escapeHtml(message || '正在加载…')}</span>` : `<span class="status-copy">${escapeHtml(message)}</span>${statusName === 'error' ? '<button type="button" class="secondary" data-view-retry="' + escapeHtml(view) + '">重试</button>' : ''}`; }
function normalizeEmptyState(view) { const root = document.querySelector(`#${view}-view`); if (!root) return; root.querySelectorAll('.list').forEach(list => { if (list.children.length === 1 && list.firstElementChild.matches('span.task-meta')) list.firstElementChild.classList.add('empty-state'); }); }
const productFlash = flash;
flash = message => { productFlash(message); const view = activeViewName(); if (state.uiLoadingView === view) { state.uiViewError = true; setViewStatus(view, 'error', message); } };
const productLoadCurrentView = loadCurrentView;
loadCurrentView = async activeView => { const view = activeView || activeViewName(); if (!view) return; state.uiLoadingView = view; state.uiViewError = false; setViewStatus(view, 'loading', '正在加载学习空间…'); try { await productLoadCurrentView(view); normalizeEmptyState(view); if (!state.uiViewError) { setViewStatus(view, 'success', ''); } } catch (error) { state.uiViewError = true; setViewStatus(view, 'error', error.message || '页面加载失败'); productFlash(error.message || '页面加载失败'); } finally { if (state.uiLoadingView === view) state.uiLoadingView = null; } };
document.addEventListener('click', event => { const button = event.target.closest('[data-view-retry]'); if (button) void loadCurrentView(button.dataset.viewRetry); });
function markJobState(root, statusName) { if (!root) return; root.dataset.jobState = statusName; root.setAttribute('aria-live', 'polite'); root.setAttribute('aria-busy', statusName === 'processing' ? 'true' : 'false'); }
const productWatchJob = watchJob;
watchJob = async (...args) => { const root = $('#rag-job'); rememberResourceJob(args[0], args[1]); markJobState(root, 'processing'); try { const result = await productWatchJob(...args); const failed = /failed|失败|error|错误/i.test(root?.textContent || ''); markJobState(root, failed ? 'failed' : 'completed'); return result; } catch (error) { markJobState(root, 'failed'); throw error; } };
const productWatchPlanJob = watchPlanJob;
watchPlanJob = async (...args) => { const root = $('#plan-job-status'); markJobState(root, 'processing'); try { const result = await productWatchPlanJob(...args); markJobState(root, /failed|失败|error|错误/i.test(root?.textContent || '') ? 'failed' : 'completed'); return result; } catch (error) { markJobState(root, 'failed'); throw error; } };
const productWatchGenerationJob = watchGenerationJob;
watchGenerationJob = async (...args) => { const root = $('#generation-job'); markJobState(root, 'processing'); try { const result = await productWatchGenerationJob(...args); markJobState(root, /failed|失败|error|错误/i.test(root?.textContent || '') ? 'failed' : 'completed'); return result; } catch (error) { markJobState(root, 'failed'); throw error; } };
const productWatchPracticeAnalysis = watchPracticeAnalysis;
watchPracticeAnalysis = async (...args) => { const root = $('#practice-run'); markJobState(root, 'processing'); try { const result = await productWatchPracticeAnalysis(...args); markJobState(root, /failed|失败|error|错误/i.test(root?.textContent || '') ? 'failed' : 'completed'); return result; } catch (error) { markJobState(root, 'failed'); throw error; } };
function ensureCourseScopeBanner(view) { const root = document.querySelector(`#${view}-view`); if (!root || !state.activeCourseId || view === 'courses') return; let banner = root.querySelector(':scope > .course-scope'); if (!banner) { banner = document.createElement('div'); banner.className = 'course-scope'; const status = root.querySelector(':scope > .view-status'); (status ? status.insertAdjacentElement('afterend', banner) : root.insertBefore(banner, root.firstChild)); } banner.innerHTML = `<span>当前课程：<strong>${escapeHtml(state.activeCourseName || '课程工作区')}</strong></span><button type="button" class="text-button" data-return-course="${state.activeCourseId}">返回课程工作区</button>`; }
const productOpenCourse = openCourse;
openCourse = async courseId => { state.activeCourseId = courseId; const result = await productOpenCourse(courseId); try { const data = await api(`/courses/${courseId}/workspace`); state.activeCourseName = data.course?.name || ''; } catch (_) {} return result; };
const productOpenView = openView;
openView = (view, ...args) => { if (view === 'courses') { state.activeCourseId = null; state.activeCourseName = ''; } return productOpenView(view, ...args); };
const productLoadCurrentViewWithScope = loadCurrentView;
loadCurrentView = async activeView => { const view = activeView || activeViewName(); const result = await productLoadCurrentViewWithScope(view); ensureCourseScopeBanner(view); return result; };
document.addEventListener('click', event => { const button = event.target.closest('[data-return-course]'); if (button) void openCourse(Number(button.dataset.returnCourse)); });

async function loadCourseNotes() {
  const root = $('#course-note-list');
  if (!root) return;
  if (!state.activeCourseId) {
    root.innerHTML = '<div class="empty-state"><strong>请先打开一门课程</strong><span>课程笔记会自动归档到当前课程。</span><button class="primary" data-view="courses">打开课程</button></div>';
    bindViewButtons();
    return;
  }
  const notes = await api(`/courses/${state.activeCourseId}/notes`);
  root.innerHTML = notes.map(note => `<article class="note-card" data-note-id="${note.id}"><div class="note-card-head"><div><h4>${escapeHtml(note.title)}</h4><div class="task-meta">更新于 ${escapeHtml((note.updated_at || '').replace('T', ' ').slice(0, 16))}</div></div><div class="button-row"><button class="text-button" data-edit-note="${note.id}">编辑</button><button class="text-button" data-delete-note="${note.id}">删除</button></div></div><div class="note-content">${escapeHtml(note.content || '（空笔记）').replace(/\n/g, '<br>')}</div></article>`).join('') || '<div class="empty-state"><strong>还没有课程笔记</strong><span>把课堂要点、疑问和下一步行动记录下来，形成可复习的知识沉淀。</span><button class="primary" id="new-course-note-empty">新建第一篇笔记</button></div>';
  document.querySelectorAll('[data-edit-note]').forEach(button => button.onclick = () => {
    const note = notes.find(item => item.id === Number(button.dataset.editNote));
    if (!note) return;
    const form = $('#course-note-form');
    form.dataset.noteId = String(note.id);
    form.querySelector('[name=title]').value = note.title;
    form.querySelector('[name=content]').value = note.content;
    form.classList.remove('hidden');
    form.querySelector('[name=title]').focus();
  });
  document.querySelectorAll('[data-delete-note]').forEach(button => button.onclick = async () => {
    if (!confirm('确定删除这篇笔记吗？')) return;
    try { await api(`/course-notes/${button.dataset.deleteNote}`, { method: 'DELETE' }); flash('笔记已删除'); await loadCourseNotes(); }
    catch (error) { flash(error.message); }
  });
  $('#new-course-note-empty')?.addEventListener('click', () => $('#new-course-note').click(), { once: true });
}

$('#new-course-note')?.addEventListener('click', () => {
  const form = $('#course-note-form');
  delete form.dataset.noteId;
  form.reset();
  form.classList.remove('hidden');
  form.querySelector('[name=title]').focus();
});
$('#course-note-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  if (!state.activeCourseId) return flash('请先打开一门课程');
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form));
  try {
    const noteId = form.dataset.noteId;
    await api(noteId ? `/course-notes/${noteId}` : `/courses/${state.activeCourseId}/notes`, { method: noteId ? 'PATCH' : 'POST', body: JSON.stringify(payload) });
    form.reset();
    delete form.dataset.noteId;
    form.classList.add('hidden');
    flash(noteId ? '笔记已更新' : '笔记已保存');
    await loadCourseNotes();
  } catch (error) { flash(error.message); }
});

const productOpenViewWithNotes = openView;
openView = (view, ...args) => {
  const result = productOpenViewWithNotes(view, ...args);
  if (view === 'notes') document.title = '课程笔记 · Learning Space';
  return result;
};
const productLoadCurrentViewWithNotes = loadCurrentView;
loadCurrentView = async activeView => {
  const view = activeView || activeViewName();
  if (view === 'notes') {
    setViewStatus(view, 'loading', '正在加载课程笔记…');
    try { await loadCourseNotes(); ensureCourseScopeBanner(view); setViewStatus(view, 'success', ''); }
    catch (error) { setViewStatus(view, 'error', error.message || '笔记加载失败'); productFlash(error.message || '笔记加载失败'); }
    return;
  }
  return productLoadCurrentViewWithNotes(view);
};
const productOpenCourseWithNotes = openCourse;
openCourse = async courseId => {
  const result = await productOpenCourseWithNotes(courseId);
  const nav = document.querySelector('#course-list .course-workspace-nav');
  if (nav && !nav.querySelector('[data-course-view="notes"]')) {
    const button = document.createElement('button');
    button.className = 'secondary';
    button.dataset.courseView = 'notes';
    button.textContent = '笔记';
    button.onclick = () => openView('notes');
    nav.insertBefore(button, nav.querySelector('[data-course-view="analytics"]'));
  }
  return result;
};

// A course workspace keeps the complete task cards. Checklists belong to a
// daily objective, not to the course-level recent-task history.
const productWorkspacePanel = workspacePanel;
workspacePanel = async (courseId, view, data) => {
  await productWorkspacePanel(courseId, view, data);
  if (view !== 'overview') return;
  const root = document.querySelector('#course-list .course-inline-content');
  if (!root) return;
  const taskList = root.querySelector('.course-todo-list');
  if (taskList) {
    taskList.className = 'list course-recent-task-list';
    taskList.innerHTML = (data.recent_tasks || []).map(taskRow).join('') || '<span class="task-meta">暂无近期任务。</span>';
    bindTaskActions(() => openCourse(courseId));
  }
};

function dailyGoalChecklist(tasks) {
  const groups = new Map();
  tasks.forEach(task => {
    const name = task.course_name || '今日自主学习';
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(task);
  });
  return [...groups.entries()].map(([name, items]) => {
    const done = items.filter(item => item.completed || item.status === 'completed').length;
    return `<article class="daily-goal-card"><div class="daily-goal-head"><div><strong>${escapeHtml(name)}</strong><div class="task-meta">今日目标 · ${done}/${items.length} 项已完成</div></div><span class="daily-goal-progress">${items.length ? Math.round(done * 100 / items.length) : 0}%</span></div><div class="course-todo-list">${items.map(workspaceTaskTodo).join('')}</div></article>`;
  }).join('');
}
function ensureDailyGoalPanel() {
  let panel = document.querySelector('#today-view .daily-goal-breakdown');
  if (panel) return panel;
  panel = document.createElement('section');
  panel.className = 'data-section daily-goal-breakdown';
  panel.innerHTML = '<div class="section-head"><div><p class="eyebrow">DAILY GOALS</p><h3>今日目标拆分</h3></div><span class="task-meta">勾选子项会同步完成对应学习任务</span></div><div class="daily-goal-list"></div>';
  document.querySelector('#today-view .today-grid')?.insertAdjacentElement('afterend', panel);
  return panel;
}
const productLoadTodayWithDailyGoals = loadToday;
loadToday = async () => {
  await productLoadTodayWithDailyGoals();
  const panel = ensureDailyGoalPanel();
  if (!panel) return;
  try {
    const today = await api('/today');
    const list = panel.querySelector('.daily-goal-list');
    list.innerHTML = today.tasks.length ? dailyGoalChecklist(today.tasks) : '<div class="workspace-empty">今天还没有安排学习目标。添加任务后，可以在这里按目标勾选子项。</div>';
    list.querySelectorAll('[data-workspace-task]').forEach(input => { input.onchange = async () => { if (!input.checked) return; input.disabled = true; try { await api(`/tasks/${input.dataset.workspaceTask}/action`, { method: 'POST', body: JSON.stringify({ action: 'complete' }) }); flash('子任务已完成，今日目标进度已更新'); await loadToday(); } catch (error) { input.checked = false; input.disabled = false; flash(error.message); } }; });
  } catch (error) { panel.querySelector('.daily-goal-list').innerHTML = `<div class="error-text">今日目标加载失败：${escapeHtml(error.message)}</div>`; }
};

// Dynamically inserted controls must not depend on a previous page render.
const productEnsureCourseScopeBanner = ensureCourseScopeBanner;
ensureCourseScopeBanner = view => {
  productEnsureCourseScopeBanner(view);
  const button = document.querySelector(`#${view}-view [data-return-course]`);
  if (button) button.onclick = () => void openCourse(Number(button.dataset.returnCourse));
};
document.addEventListener('click', event => {
  const viewButton = event.target.closest('[data-view]');
  if (viewButton && viewButton.dataset.view && !viewButton.dataset.viewBound) void openView(viewButton.dataset.view);
});

const taskRowWithSourceAction = taskRow;
taskRow = task => {
  const source = escapeHtml(task.source || 'user');
  const sourceButton = `<button class="text-button" data-task-source="${task.id}" data-task-source-course="${task.course_id || ''}" data-task-source-kind="${source}">查看来源</button>`;
  const courseButton = task.course_id
    ? `<button class="text-button" data-task-course="${task.course_id}">查看课程</button>` : '';
  const knowledgeButton = task.course_id && task.knowledge_point_id
    ? `<button class="text-button" data-task-knowledge="${task.knowledge_point_id}" data-task-knowledge-course="${task.course_id}">查看知识点</button>` : '';
  return taskRowWithSourceAction(task).replace('</article>', `${sourceButton}${courseButton}${knowledgeButton}</article>`);
};
document.addEventListener('click', event => {
  const button = event.target.closest('[data-task-source]');
  if (!button) return;
  const courseId = Number(button.dataset.taskSourceCourse) || 0;
  if (courseId) openCourse(courseId);
  else flash(`任务来源：${button.dataset.taskSourceKind || 'user'}`);
});
document.addEventListener('click', event => {
  const courseButton = event.target.closest('[data-task-course]');
  if (courseButton) {
    void openCourse(Number(courseButton.dataset.taskCourse));
    return;
  }
  const knowledgeButton = event.target.closest('[data-task-knowledge]');
  if (!knowledgeButton) return;
  void openCourse(Number(knowledgeButton.dataset.taskKnowledgeCourse)).then(() => openView('knowledge'));
});

const productLoadTodayWithInsight = loadToday;
loadToday = async () => {
  await productLoadTodayWithInsight();
  try {
    const today = await api('/today');
    const insight = today.insight || {};
    const focus = Array.isArray(insight.focus_areas) && insight.focus_areas.length
      ? `<div class="task-meta">重点：${insight.focus_areas.map(escapeHtml).join(' · ')}</div>` : '';
    const minutes = insight.recommended_minutes ? `<div class="task-meta">建议投入：${insight.recommended_minutes} 分钟</div>` : '';
    $('#today-insight').innerHTML = `<strong>${escapeHtml(insight.text || '今天继续完成一项学习任务。')}</strong>${focus}${minutes}<button type="button" class="text-button" id="ask-why-today">为什么今天这样安排？</button>`;
    $('#ask-why-today').onclick = () => openTutor(`请解释今天的学习安排。今日建议：${insight.text || '暂无建议'}。今日任务：${today.tasks.map(task => task.title).join('、') || '暂无任务'}。请基于目标、掌握度、错题和复习队列说明原因，并给出可调整方案。`);
  } catch (error) { flash(error.message); }
};

const productRenderPracticeRun = renderPracticeRun;
renderPracticeRun = () => {
  const root = $('#practice-run');
  if (!state.practice) {
    root.innerHTML = '<div class="empty-state"><strong>选择题目后开始练习</strong><span>系统会记录答题结果，并据此更新掌握度、错题与后续复习。</span></div>';
    return;
  }
  const current = state.practice.questions[state.practice.index];
  if (!current) return;
  const choiceKinds = new Set(['single_choice', 'multiple_choice', 'true_false']);
  const longAnswerKinds = new Set(['essay', 'reading']);
  let options = String(current.options || '').split('\n').map(item => item.trim()).filter(Boolean);
  if (current.kind === 'true_false' && !options.length) options = ['True', 'False'];
  const isChoice = choiceKinds.has(current.kind);
  const inputType = current.kind === 'multiple_choice' ? 'checkbox' : 'radio';
  const answerControl = isChoice
    ? `<div class="practice-options" role="group" aria-label="Answer options">${options.map(option => `<label class="practice-option"><input type="${inputType}" name="choice" value="${escapeHtml(option)}"><span class="math-text">${mathHtml(option)}</span></label>`).join('')}</div>`
    : longAnswerKinds.has(current.kind)
      ? '<textarea name="response" rows="7" maxlength="20000" placeholder="Write your response" required></textarea>'
      : '<input name="response" autocomplete="off" placeholder="Answer" required>';
  root.innerHTML = `<div class="practice-run-head"><span class="task-meta">Question ${state.practice.index + 1} / ${state.practice.questions.length}</span><span class="task-meta">${escapeHtml(current.kind.replace(/_/g, ' '))}</span></div><p class="practice-prompt math-text">${mathHtml(current.prompt)}</p><form id="practice-answer-form" class="practice-answer ${longAnswerKinds.has(current.kind) ? 'practice-answer-long' : ''}">${answerControl}<button class="primary" type="submit">提交答案</button></form>`;
  typesetMath(root);
  $('#practice-answer-form').onsubmit = async event => {
    event.preventDefault();
    try {
      const selected = [...root.querySelectorAll('[name="choice"]:checked')].map(item => item.value);
      const response = isChoice ? selected.join('\n') : String(new FormData(event.target).get('response') || '').trim();
      if (!response) { flash(current.kind === 'multiple_choice' ? '请至少选择一个选项。' : '请选择或填写答案。'); return; }
      const result = await api(`/practice-sessions/${state.practice.id}/questions/${current.id}/attempts`, { method: 'POST', body: JSON.stringify({ response, elapsed_seconds: 0 }) });
      root.insertAdjacentHTML('beforeend', `<div class="practice-feedback ${result.correct ? 'correct' : 'incorrect'}"><strong>${result.correct ? '回答正确' : '回答已记录'}</strong><div class="feedback-answer"><span>你的答案：${escapeHtml(response)}</span><span>正确答案：${escapeHtml(current.answer || '未提供')}</span></div>${current.explanation ? `<p class="math-text">${mathHtml(current.explanation)}</p>` : '<p class="task-meta">完成本题后，系统已更新学习记录。</p>'}<div class="practice-feedback-actions"><button type="button" class="secondary" id="ask-ai-practice">问 AI</button><button type="button" class="secondary" id="next-practice">${state.practice.index + 1 >= state.practice.questions.length ? '完成练习' : '下一题'}</button></div></div>`);
      typesetMath(root);
      event.target.querySelector('button[type="submit"]').disabled = true;
      root.querySelectorAll('input, textarea').forEach(control => control.disabled = true);
      $('#ask-ai-practice').onclick = () => openTutor(`我刚做完这道题：${current.prompt}\n我的答案是：${response}\n正确答案是：${current.answer || ''}\n请用提示、举例和反问的方式帮助我理解，不要直接跳过推理。`);
      $('#next-practice').onclick = async () => {
        state.practice.index += 1;
        if (state.practice.index >= state.practice.questions.length) {
          const summary = await api(`/practice-sessions/${state.practice.id}/complete`, { method: 'POST' });
          flash(`完成：${summary.correct}/${summary.total}，准确率 ${summary.accuracy}%`);
          if (summary.analysis_job_id) watchPracticeAnalysis(summary.analysis_job_id);
          state.practice = null;
          await loadPractice();
        } else renderPracticeRun();
      };
    } catch (error) { flash(error.message); }
  };
};

async function loadKnowledgeWorkspace() {
  const list = $('#knowledge-workspace-list');
  const summary = $('#knowledge-workspace-summary');
  if (!list || !summary) return;
  const suffix = state.activeCourseId ? `?course_id=${state.activeCourseId}` : '';
  const points = await api(`/knowledge-points${suffix}`);
  const practiced = points.filter(point => Number(point.practice_count || 0) > 0);
  const average = points.length ? Math.round(points.reduce((total, point) => total + Number(point.mastery || 0), 0) / points.length) : 0;
  const due = points.filter(point => point.next_review_at && point.next_review_at.slice(0, 10) <= new Date().toISOString().slice(0, 10)).length;
  summary.innerHTML = [['知识点', points.length], ['平均掌握度', `${average}%`], ['已练习', practiced.length], ['待复习', due]].map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join('');
  const relationNames = values => (Array.isArray(values) ? values : []).map(value => escapeHtml(typeof value === 'object' ? (value.name || value.id || '') : value)).filter(Boolean).join('、');
  list.innerHTML = points.map(point => {
    const accuracy = Number(point.practice_count || 0) ? Math.round(Number(point.correct_count || 0) * 100 / Number(point.practice_count || 1)) : null;
    const prerequisites = relationNames(point.prerequisites);
    const related = relationNames(point.related_points);
    return `<article class="knowledge-card"><div class="knowledge-card-head"><div><h4>${escapeHtml(point.name)}</h4><div class="task-meta">${escapeHtml(point.category || '知识点')} · 难度 ${Number(point.difficulty || 3)}/5 · 重要度 ${Number(point.importance || 3)}/5</div></div><strong class="mastery-value">${Number(point.mastery || 0)}%</strong></div><div class="mastery-bar knowledge-mastery-bar"><i style="width:${Math.max(0, Math.min(100, Number(point.mastery || 0)))}%"></i></div><div class="knowledge-stats"><span>练习 ${Number(point.practice_count || 0)} 次</span><span>正确率 ${accuracy === null ? '—' : `${accuracy}%`}</span><span>最近学习 ${escapeHtml(point.last_studied_at ? point.last_studied_at.slice(0, 10) : '未开始')}</span><span>下次复习 ${escapeHtml(point.next_review_at ? point.next_review_at.slice(0, 10) : '待安排')}</span></div>${point.definition ? `<p class="knowledge-definition">${escapeHtml(point.definition)}</p>` : ''}${prerequisites ? `<div class="task-meta">前置知识：${prerequisites}</div>` : ''}${related ? `<div class="task-meta">相关知识：${related}</div>` : ''}<button type="button" class="text-button" data-knowledge-tutor="${point.id}" data-knowledge-name="${escapeHtml(point.name)}" data-knowledge-mastery="${Number(point.mastery || 0)}" data-knowledge-accuracy="${accuracy === null ? '' : accuracy}">为什么掌握度这样？</button></article>`;
  }).join('') || '<div class="empty-state"><strong>还没有课程知识结构</strong><span>上传教材或大纲后可由 AI 提取知识点；也可以先手动添加一个关键知识点。</span><div class="button-row"><button class="secondary" data-knowledge-action="extract">从资料提取</button><button class="primary" data-knowledge-action="add">新增知识点</button></div></div>';
  document.querySelectorAll('[data-knowledge-action="extract"]').forEach(button => button.onclick = () => $('#knowledge-open-extraction').click());
  document.querySelectorAll('[data-knowledge-action="add"]').forEach(button => button.onclick = () => $('#knowledge-add-point').click());
  document.querySelectorAll('[data-knowledge-tutor]').forEach(button => button.onclick = () => openTutor(`请分析知识点“${button.dataset.knowledgeName}”当前掌握度为 ${button.dataset.knowledgeMastery}%${button.dataset.knowledgeAccuracy ? `，最近正确率 ${button.dataset.knowledgeAccuracy}%` : ''} 的原因，并给出一个可执行的补强练习与复习方案。`));
}

$('#knowledge-open-extraction')?.addEventListener('click', () => openView('resources'));
$('#knowledge-add-point')?.addEventListener('click', async () => {
  openView('goals');
  await loadGoals();
  const course = $('#knowledge-course');
  if (course && state.activeCourseId) course.value = String(state.activeCourseId);
  $('#knowledge-point-form')?.classList.remove('hidden');
  $('#knowledge-point-form [name=name]')?.focus();
});
const productOpenViewWithKnowledge = openView;
openView = (view, ...args) => {
  const result = productOpenViewWithKnowledge(view, ...args);
  if (view === 'knowledge') document.title = '知识结构 · Learning Space';
  return result;
};
const productLoadCurrentViewWithKnowledge = loadCurrentView;
loadCurrentView = async activeView => {
  const view = activeView || activeViewName();
  if (view === 'knowledge') {
    setViewStatus(view, 'loading', '正在加载课程知识结构…');
    try { await loadKnowledgeWorkspace(); ensureCourseScopeBanner(view); setViewStatus(view, 'success', ''); }
    catch (error) { setViewStatus(view, 'error', error.message || '知识结构加载失败'); productFlash(error.message || '知识结构加载失败'); }
    return;
  }
  return productLoadCurrentViewWithKnowledge(view);
};
const productOpenCourseWithKnowledge = openCourse;
openCourse = async courseId => {
  const result = await productOpenCourseWithKnowledge(courseId);
  const buttons = document.querySelectorAll('#course-list .course-workspace-nav [data-course-view="goals"]');
  if (buttons.length > 1) {
    const knowledgeButton = buttons[1];
    knowledgeButton.dataset.courseView = 'knowledge';
    knowledgeButton.onclick = () => openView('knowledge');
  }
  return result;
};

$('#analyze-mistakes')?.addEventListener('click', () => openTutor('请基于我的近期错题、错误类型、关联知识点和复习队列，分析最主要的错误模式，并给出一组优先练习建议。'));
const productOpenCourseWithTutor = openCourse;
openCourse = async courseId => {
  const result = await productOpenCourseWithTutor(courseId);
  const nav = document.querySelector('#course-list .course-workspace-nav');
  if (nav && !nav.querySelector('[data-course-tutor]')) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.dataset.courseTutor = String(courseId);
    button.textContent = 'AI 分析课程';
    button.onclick = () => openTutor(`请分析课程“${state.activeCourseName || '当前课程'}”的目标、任务完成情况、掌握度、错题和复习队列，并给出下一阶段最重要的学习调整。`);
    nav.append(button);
  }
  return result;
};

// Canonical course workspace entry point. Earlier compatibility wrappers add
// features incrementally; keeping the final rendering path here prevents one
// course click from fetching the same workspace data several times.
openCourse = async courseId => {
  state.activeCourseId = courseId;
  try {
    const data = await api(`/courses/${courseId}/workspace`);
    const course = data.course || {};
    state.activeCourseName = course.name || '';
    const tab = (view, label, primary = false) => `<button type="button" class="${primary ? 'primary' : 'secondary'}" data-course-view="${view}">${label}</button>`;
    $('#course-list').innerHTML = `
      <section class="workspace-card">
        <button type="button" class="text-button" id="back-courses">← 返回课程</button>
        <div class="course-hero"><div><p class="eyebrow">LEARNING WORKSPACE</p><h3>${escapeHtml(course.name || '课程')}</h3><p>${escapeHtml(course.description || course.subject || '围绕目标、知识、练习和复习持续推进。')}</p></div><div class="course-progress"><strong>${Number(course.progress || 0)}%</strong><span>课程进度</span></div></div>
        <div class="workspace-tabs course-workspace-nav">${tab('overview', '概览', true)}${tab('goals', '计划')}${tab('knowledge', '知识')}${tab('resources', '资料')}${tab('practice', '练习')}${tab('mistakes', '错题')}${tab('notes', '笔记')}${tab('analytics', '分析')}${tab('ai', 'AI 分析课程')}</div>
        <div class="metrics course-workspace-metrics">${[['知识点', (data.knowledge || []).length], ['资料', data.resource_count || 0], ['题目', data.question_count || 0], ['错题', data.mistake_count || 0], ['练习正确率', `${Number(data.practice?.accuracy || 0)}%`]].map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join('')}</div>
        <div class="content-grid">
          <section><h4>知识掌握度</h4><div class="list">${(data.knowledge || []).map(item => `<article class="list-row"><span>${escapeHtml(item.name)}</span><strong>${Number(item.mastery || 0)}%</strong></article>`).join('') || '<span class="task-meta">还没有知识点。可在资料页或目标页建立知识结构。</span>'}</div></section>
          <section><h4>目标与近期任务</h4><div class="list">${(data.goals || []).map(item => `<article class="list-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">${escapeHtml(item.target_date || '未设置日期')} · ${Number(item.progress || 0)}%</div></div></article>`).join('') || '<span class="task-meta">还没有课程目标。</span>'}</div><h4 class="subhead">近期任务</h4><div class="list">${(data.recent_tasks || []).map(taskRow).join('') || '<span class="task-meta">暂无近期任务。</span>'}</div></section>
        </div>
      </section>`;
    $('#back-courses').onclick = () => { state.activeCourseId = null; state.activeCourseName = ''; void loadCourses(); };
    document.querySelectorAll('#course-list [data-course-view]').forEach(button => {
      button.onclick = () => {
        const view = button.dataset.courseView;
        if (view === 'overview') return;
        if (view === 'ai') return openTutor(`请分析课程“${state.activeCourseName || '当前课程'}”的目标、任务完成情况、掌握度、错题和复习队列，并给出下一阶段最重要的学习调整。`);
        openView(view);
      };
    });
    bindTaskActions(() => openCourse(courseId));
  } catch (error) {
    flash(error.message || '课程工作区加载失败');
  }
};

const productLoadCoursesWithEmptyAction = loadCourses;
loadCourses = async () => {
  await productLoadCoursesWithEmptyAction();
  const view = $('#courses-view');
  view?.querySelector('.section-head h3')?.replaceChildren('课程列表');
  const create = $('#new-course');
  if (create) create.textContent = '新建课程';
  const form = $('#course-form');
  form?.querySelector('[name=name]')?.setAttribute('placeholder', '课程名称');
  form?.querySelector('[name=subject]')?.setAttribute('placeholder', '学科');
  form?.querySelector('[name=description]')?.setAttribute('placeholder', '课程说明（可选）');
  const submit = form?.querySelector('button.primary');
  if (submit) submit.textContent = '创建课程';
  const cancel = form?.querySelector('button.secondary');
  if (cancel) cancel.textContent = '取消';
  $('#new-course-empty')?.addEventListener('click', () => $('#new-course')?.click(), { once: true });
};

// The Agent can search globally, so give the learner an explicit destination
// when importing a source outside a course workspace. Agent runtime source
// actions also fall back to state.activeCourseId when a workspace is open.
const productLoadAiCenterWithCourseScope = loadAiCenter;
loadAiCenter = async () => {
  await productLoadAiCenterWithCourseScope();
  const heading = $('#ai-view .section-head');
  if (!heading) return;
  let select = $('#agent-course');
  if (!select) {
    select = document.createElement('select');
    select.id = 'agent-course';
    select.className = 'agent-course-select';
    select.setAttribute('aria-label', '资料导入课程');
    heading.insertBefore(select, $('#new-agent-session'));
  }
  select.innerHTML = courseOptions('选择导入课程');
  if (state.activeCourseId) select.value = String(state.activeCourseId);
};

function courseCategory(course) {
  const text = `${course.subject || ''} ${course.name || ''} ${course.description || ''}`.toLowerCase();
  const categories = [[/英语|english|cet|雅思|托福|词汇|听力|阅读|写作/, '英语'], [/数学|math|calculus|微积分|高数|线性代数|概率/, '数学'], [/电路|circuit|电子|模拟电路|数字电路/, '电路'], [/计算机|computer|python|java|编程|算法|agent|人工智能|\bai\b/, '计算机与 AI'], [/物理|physics/, '物理'], [/化学|chemistry/, '化学'], [/错题|错误|薄弱|诊断/, '错题专项']];
  return categories.find(([pattern]) => pattern.test(text))?.[1] || (String(course.subject || '').trim() && course.subject !== 'AI 自动创建' ? String(course.subject).trim().slice(0, 14) : '自主学习');
}
function shortCourseTitle(course) { const name = String(course.name || '').trim(); return (!name || name.length > 24 || /^请|我想|帮我|生成|根据/.test(name)) ? courseCategory(course) : (name.length > 18 ? `${name.slice(0, 18)}…` : name); }
function learningDate(value) { const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/); return match ? `${Number(match[2])}月${Number(match[3])}日` : (value || '未安排日期'); }
function workspaceTaskTodo(task) {
  const completed = Boolean(task.completed) || task.status === 'completed';
  const details = [task.knowledge_point_name ? `知识点：${task.knowledge_point_name}` : '', task.note ? `备注：${task.note}` : ''].filter(Boolean).join('\n');
  return `<article class="course-task-todo ${completed ? 'is-done' : ''}"><label class="course-task-check"><input type="checkbox" data-workspace-task="${task.id}" ${completed ? 'checked disabled' : ''} aria-label="完成任务：${escapeHtml(task.title)}"><span></span></label><div class="course-task-copy"><strong>${escapeHtml(task.title)}</strong><div class="task-meta">${learningDate(task.planned_date)} · ${Number(task.duration_minutes || 0)} 分钟${task.scheduled_time ? ` · ${escapeHtml(task.scheduled_time)}` : ''}</div>${details ? `<div class="course-task-detail">${escapeHtml(details)}</div>` : ''}<button type="button" class="text-button" data-task-learn="${task.id}">打开本任务内容</button><div class="task-learning-panel hidden" data-task-learning-panel="${task.id}"></div></div><span class="course-task-state">${completed ? '已完成' : (task.status === 'in_progress' ? '进行中' : '待完成')}</span></article>`;
}

async function openTaskLearning(taskId, courseId) {
  const panel = document.querySelector(`[data-task-learning-panel="${taskId}"]`); if (!panel) return;
  panel.classList.remove('hidden'); panel.textContent = '正在加载学习内容…';
  try {
    const data = await api(`/tasks/${taskId}/learning`);
    const knowledge = (data.knowledge || []).map(item => `<article class="list-row"><div><strong>${escapeHtml(item.name)}</strong><div>${escapeHtml(item.definition || item.note || '暂无讲解')}</div></div><span>${Number(item.mastery || 0)}%</span></article>`).join('');
    const questions = data.questions || [];
    panel.innerHTML = `${knowledge ? `<h5>本次知识点</h5>${knowledge}` : ''}${questions.length ? `<h5>本次题目</h5><div class="task-meta">共 ${questions.length} 题，完成作答且正确率达到 60% 后任务自动完成。</div><button type="button" class="primary" data-task-practice="${taskId}">开始本任务练习</button>` : ''}${(data.vocabulary || []).length ? `<h5>词汇复习</h5><div>${data.vocabulary.map(item => `<div>${escapeHtml(item.word)} · ${escapeHtml(item.meaning)}</div>`).join('')}</div>` : ''}${!knowledge && !questions.length && !(data.vocabulary || []).length ? '<div class="task-meta">该任务正在等待资料、知识点或题目生成；不会把空任务伪装为已完成。</div>' : ''}`;
    panel.querySelector('[data-task-practice]')?.addEventListener('click', async () => {
      const result = await api(`/tasks/${taskId}/practice`, { method: 'POST' });
      state.questions = await api('/questions'); const ids = new Set((await api(`/tasks/${taskId}/learning`)).questions.map(item => item.id));
      state.practice = { id: result.id, questions: state.questions.filter(item => ids.has(item.id)), index: 0, taskId };
      openView('practice'); renderPracticeRun();
    });
  } catch (error) { panel.textContent = `无法加载任务内容：${error.message}`; }
}
async function workspacePanel(courseId, view, data) {
  const root = document.querySelector('#course-list .course-inline-content'); if (!root) return; root.setAttribute('aria-busy', 'true');
  const empty = text => `<div class="workspace-empty">${text}</div>`;
  try {
    let content = '';
    if (view === 'overview') content = `<div class="workspace-overview"><section><h4>学习重点</h4><div class="list">${(data.knowledge || []).slice(0, 6).map(item => `<article class="list-row"><span>${escapeHtml(item.name)}</span><strong>${Number(item.mastery || 0)}%</strong></article>`).join('') || empty('暂未建立知识点。')}</div></section><section><h4>近期任务</h4><div class="course-todo-list">${(data.recent_tasks || []).map(workspaceTaskTodo).join('') || empty('暂无近期任务。')}</div></section></div>`;
    if (view === 'goals') { const items = await api(`/goals?course_id=${courseId}`); content = `<div class="section-head"><h4>学习计划</h4><button type="button" class="primary" data-workspace-action="add-goal">新建目标</button></div><div class="workspace-list">${items.map(item => `<article class="list-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">截止 ${learningDate(item.target_date)} · 每周 ${Number(item.weekly_minutes || 0)} 分钟</div></div><strong>${Number(item.progress || 0)}%</strong></article>`).join('') || empty('暂未设置计划。先创建一个学习目标，再生成每天可执行的任务。')}</div>`; }
    if (view === 'knowledge') { const items = await api(`/knowledge-points?course_id=${courseId}`); content = `<div class="section-head"><h4>知识结构</h4><button type="button" class="primary" data-workspace-action="add-knowledge">新增知识点</button></div><div class="workspace-list">${items.map(item => `<article class="list-row"><div><strong>${escapeHtml(item.name)}</strong><div class="task-meta">${escapeHtml(item.category || '未分类')} · 难度 ${Number(item.difficulty || 0)}/5</div></div><strong>${Number(item.mastery || 0)}%</strong></article>`).join('') || empty('暂未建立知识点。可以手动添加，也可以先上传资料后提取。')}</div>`; }
    if (view === 'resources') { const items = await api(`/resources?course_id=${courseId}`); content = `<div class="section-head"><h4>课程资料</h4><button type="button" class="primary" data-workspace-action="upload-resource">上传资料</button></div><div class="workspace-list">${items.map(item => `<article class="list-row"><div><strong>${escapeHtml(item.name)}</strong><div class="task-meta">${Math.ceil(Number(item.size || 0) / 1024)} KB · 已关联本课程</div></div><span class="task-meta">可在 AI 助手中提问</span></article>`).join('') || empty('还没有导入资料。上传并完成索引后，才能进行证据检索和出题。')}</div>`; }
    if (view === 'practice') { const items = await api(`/questions?course_id=${courseId}`); content = `<h4>练习题</h4><div class="workspace-list">${items.slice(0, 10).map(item => `<article class="list-row"><div><strong>${escapeHtml(item.prompt)}</strong><div class="task-meta">${escapeHtml(item.kind || '练习')} · 难度 ${Number(item.difficulty || 0)}</div></div></article>`).join('') || empty('暂无练习题。可让 AI 根据课程资料生成题目。')}</div>`; }
    if (view === 'mistakes') { const items = await api(`/mistakes?course_id=${courseId}`); content = `<h4>错题复盘</h4><div class="workspace-list">${items.map(item => `<article class="list-row"><div><strong>${escapeHtml(item.title)}</strong><div class="task-meta">${escapeHtml(item.error_type || '待分析')} · 错 ${Number(item.wrong_count || 0)} 次</div></div><span class="task-meta">${learningDate(item.next_review)}</span></article>`).join('') || empty('还没有错题记录。')}</div>`; }
    if (view === 'notes') { const items = await api(`/courses/${courseId}/notes`); content = `<h4>课程笔记</h4><div class="workspace-list">${items.map(item => `<article class="note-card"><strong>${escapeHtml(item.title || '未命名笔记')}</strong><div class="note-content">${escapeHtml(item.content || '')}</div></article>`).join('') || empty('还没有课程笔记。')}</div>`; }
    if (view === 'analytics') { const summary = (await api(`/analytics?days=30&course_id=${courseId}`)).summary || {}; content = `<h4>近 30 天学习分析</h4><div class="metrics compact-metrics">${[['学习时间', `${Number(summary.study_minutes || 0)} 分钟`], ['任务完成', `${Number(summary.tasks_completed || 0)}/${Number(summary.tasks_total || 0)}`], ['练习正确率', `${Number(summary.accuracy || 0)}%`], ['待复习', `${Number(summary.due_reviews || 0)} 项`]].map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join('')}</div>`; }
    root.innerHTML = content;
    root.querySelectorAll('[data-workspace-action]').forEach(button => {
      button.onclick = async () => {
        const action = button.dataset.workspaceAction;
        if (action === 'upload-resource') return openView('resources');
        openView('goals');
        await loadGoals();
        if (action === 'add-goal') {
          const course = $('#goal-course');
          if (course) course.value = String(courseId);
          $('#goal-form')?.classList.remove('hidden');
          $('#goal-form [name=title]')?.focus();
        }
        if (action === 'add-knowledge') {
          const course = $('#knowledge-course');
          if (course) course.value = String(courseId);
          $('#knowledge-point-form')?.classList.remove('hidden');
          $('#knowledge-point-form [name=name]')?.focus();
        }
      };
    });
    root.querySelectorAll('[data-workspace-task]').forEach(input => { input.onchange = async () => { if (!input.checked) return; input.disabled = true; try { await api(`/tasks/${input.dataset.workspaceTask}/action`, { method: 'POST', body: JSON.stringify({ action: 'complete' }) }); flash('任务已完成'); await openCourse(courseId); } catch (error) { input.checked = false; input.disabled = false; flash(error.message); } }; });
    root.querySelectorAll('[data-task-learn]').forEach(button => { button.onclick = () => openTaskLearning(Number(button.dataset.taskLearn), courseId); });
  } catch (error) { root.innerHTML = `<div class="workspace-empty error-text">加载失败：${escapeHtml(error.message)}</div>`; } finally { root.removeAttribute('aria-busy'); }
}
const conciseCourseCards = loadCourses;
loadCourses = async () => { await conciseCourseCards(); document.querySelectorAll('#course-list [data-course-open]').forEach(card => { const course = state.courses.find(item => String(item.id) === card.dataset.courseOpen); if (!course) return; const title = card.querySelector('h4'); const meta = card.querySelector('.course-card-top .task-meta'); const description = card.querySelector('p'); if (title) { title.textContent = shortCourseTitle(course); title.title = course.name || ''; } if (meta) meta.textContent = `自动归类 · ${courseCategory(course)}`; if (description) description.textContent = course.description ? String(course.description).slice(0, 72) : `围绕${courseCategory(course)}的目标、资料、练习和复习持续推进。`; }); };
openCourse = async courseId => {
  state.activeCourseId = courseId;
  try { const data = await api(`/courses/${courseId}/workspace`); const course = data.course || {}; state.activeCourseName = course.name || ''; const tabs = [['overview', '概览'], ['goals', '计划'], ['knowledge', '知识'], ['resources', '资料'], ['practice', '练习'], ['mistakes', '错题'], ['notes', '笔记'], ['analytics', '分析']]; $('#course-list').innerHTML = `<section class="workspace-card course-workspace-v2"><button type="button" class="text-button" id="back-courses">← 返回课程</button><div class="course-hero"><div><p class="eyebrow">LEARNING WORKSPACE · ${escapeHtml(courseCategory(course))}</p><h3>${escapeHtml(shortCourseTitle(course))}</h3><p title="${escapeHtml(course.name || '')}">${escapeHtml(course.description || '课程内容将由目标、资料、练习和复习共同推进。')}</p></div><div class="course-progress"><strong>${Number(course.progress || 0)}%</strong><span>课程进度</span></div></div><nav class="workspace-tabs course-workspace-nav">${tabs.map(([view, label], index) => `<button type="button" class="${index ? 'secondary' : 'primary'}" data-course-inline-view="${view}">${label}</button>`).join('')}<button type="button" class="secondary" data-course-ai>AI 分析课程</button></nav><div class="metrics course-workspace-metrics">${[['知识点', (data.knowledge || []).length], ['资料', data.resource_count || 0], ['题目', data.question_count || 0], ['错题', data.mistake_count || 0], ['练习正确率', `${Number(data.practice?.accuracy || 0)}%`]].map(([label, value]) => `<article class="metric"><div class="label">${label}</div><div class="value">${value}</div></article>`).join('')}</div><section class="course-inline-content" aria-live="polite"></section></section>`; $('#back-courses').onclick = () => { state.activeCourseId = null; state.activeCourseName = ''; void loadCourses(); }; document.querySelectorAll('[data-course-inline-view]').forEach(button => { button.onclick = async () => { document.querySelectorAll('[data-course-inline-view]').forEach(item => { item.className = 'secondary'; }); button.className = 'primary'; await workspacePanel(courseId, button.dataset.courseInlineView, data); }; }); document.querySelector('[data-course-ai]').onclick = () => openTutor(`请分析课程“${state.activeCourseName || '当前课程'}”的目标、任务完成情况、掌握度、错题和复习队列，并给出下一阶段最重要的学习调整。`); await workspacePanel(courseId, 'overview', data); } catch (error) { flash(error.message || '课程工作区加载失败'); }
};
