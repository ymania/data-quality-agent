const $ = (id) => document.getElementById(id);
const sessionId = localStorage.getItem('dq-session-id') || (globalThis.crypto?.randomUUID?.() || `session-${Date.now()}`);
localStorage.setItem('dq-session-id', sessionId);
let schemaRows = [];
let toastTimer;
let ruleBeforeId = null;
let resultBeforeId = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`);
  return body;
}

function toast(text) {
  const target = $('toast');
  target.textContent = text;
  target.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => target.classList.remove('show'), 3500);
}

function setPill(id, good, text) {
  const target = $(id);
  target.textContent = text;
  target.className = `status-pill ${good ? 'good' : 'bad'}`;
}

async function loadHealth() {
  try {
    const health = await api('/api/health');
    setPill('db-status', health.database === 'ok', health.database === 'ok' ? '● MySQL 已连接' : '● MySQL 未连接');
    const modelText = {unconfigured: '● 模型待配置', untested: '● 模型尚未测试', ok: '● 模型已验证', error: '● 模型测试失败'};
    setPill('model-status', health.model_state === 'ok', modelText[health.model_state] || '● 模型状态未知');
  } catch (error) {
    setPill('db-status', false, '● 服务不可用');
    setPill('model-status', false, '● 状态未知');
  }
}

function formatValue(value) {
  if (value === null) return 'NULL';
  if (value === '') return '""（空字符串）';
  if (typeof value === 'string' && value.trim() === '') return `${JSON.stringify(value)}（${value.length} 个空格）`;
  return JSON.stringify(value);
}

function addMessage(role, content, traces = []) {
  const box = $('messages');
  box.querySelector('.welcome')?.remove();
  const message = el('article', `message ${role}`);
  message.append(el('span', 'role', role === 'user' ? '你' : 'Agent'));
  message.append(el('div', 'bubble', content));
  if (traces.length) {
    const list = el('div', 'trace-list');
    for (const trace of traces) {
      const detail = el('details');
      const summary = el('summary');
      summary.append(el('span', 'tool-name', trace.tool));
      summary.append(el('span', trace.status === 'error' ? 'error' : '', trace.summary || trace.status));
      detail.append(summary);
      const body = el('div', 'trace-body');
      body.append(el('pre', '', JSON.stringify(trace.output, null, 2)));
      const data = trace.output?.data;
      if (data?.execution_id) {
        const button = el('button', '', `查看执行 #${data.execution_id}`);
        button.type = 'button';
        button.addEventListener('click', () => openResult(data.execution_id));
        body.append(button);
      }
      if (data?.rule_id && trace.tool === 'create_quality_rule') {
        const button = el('button', '', `运行规则 #${data.rule_id}`);
        button.type = 'button';
        button.addEventListener('click', () => runRule(data.rule_id));
        body.append(button);
      }
      detail.append(body);
      list.append(detail);
    }
    message.append(list);
  }
  box.append(message);
  box.scrollTop = box.scrollHeight;
  return message;
}

async function loadChat() {
  try {
    const history = await api(`/api/sessions/${encodeURIComponent(sessionId)}/messages`);
    for (const item of history) addMessage(item.role, item.content, item.traces);
  } catch (error) {
    toast(error.message);
  }
}

async function loadRules(reset = true) {
  const target = $('rules');
  try {
    if (reset) { ruleBeforeId = null; target.replaceChildren(); }
    target.querySelector('.load-more')?.remove();
    const path = `/api/rules?limit=20${ruleBeforeId ? `&before_id=${ruleBeforeId}` : ''}`;
    const rules = await api(path);
    if (!rules.length && reset) return target.append(el('p', 'placeholder', '还没有规则。可在对话中创建，或使用下方表单。'));
    for (const rule of rules) {
      const card = el('article', 'rule-card');
      const top = el('div', 'card-top');
      top.append(el('div', 'card-title', rule.name), el('span', 'id', `#${rule.rule_id}`));
      card.append(top);
      card.append(el('div', 'card-meta', `${rule.table_name}${rule.dataset_id ? ` [数据集 #${rule.dataset_id}]` : ''}.${rule.column_name} · ${rule.rule_type}${rule.rule_type === 'ENUM' ? ` · ${rule.params.allowed_values.map(formatValue).join('、')}` : ''}`));
      const actions = el('div', 'card-actions');
      const run = el('button', '', '运行规则 →');
      run.type = 'button';
      run.addEventListener('click', () => runRule(rule.rule_id));
      const latest = el('button', '', '最近结果');
      latest.type = 'button';
      latest.addEventListener('click', async () => {
        try {
          const result = await api(`/api/rules/${rule.rule_id}/latest`);
          showResult(result);
        } catch (error) { toast(error.message); }
      });
      actions.append(run, latest);
      card.append(actions);
      target.append(card);
    }
    if (rules.length) ruleBeforeId = rules.at(-1).rule_id;
    if (rules.length === 20) {
      const more = el('button', 'secondary load-more', '查看更多规则');
      more.type = 'button';
      more.addEventListener('click', () => loadRules(false));
      target.append(more);
    }
  } catch (error) {
    target.replaceChildren(el('p', 'placeholder', error.message));
  }
}

async function loadResults(reset = true) {
  const target = $('results');
  try {
    if (reset) { resultBeforeId = null; target.replaceChildren(); }
    target.querySelector('.load-more')?.remove();
    const path = `/api/results?limit=20${resultBeforeId ? `&before_id=${resultBeforeId}` : ''}`;
    const results = await api(path);
    if (!results.length && reset) return target.append(el('p', 'placeholder', '尚无执行记录。运行规则后将在这里保留结果。'));
    for (const result of results) {
      const card = el('article', 'result-card');
      card.tabIndex = 0;
      card.setAttribute('role', 'button');
      const top = el('div', 'card-top');
      top.append(el('div', 'card-title', `#${result.execution_id} · ${result.rule_name}`),
                 el('span', `run-status ${result.status === 'FAILED' ? 'failed' : ''}`, result.status));
      card.append(top);
      card.append(el('div', 'card-meta', result.executed_at.replace('T', ' ')));
      card.append(el('div', 'result-stats', result.status === 'SUCCEEDED'
        ? `总数 ${result.total_count} · 不通过 ${result.failed_count} · 通过率 ${result.pass_rate ?? 'N/A'}${result.pass_rate === null ? '' : '%'}`
        : (result.error || '运行中；如长时间未变化，请核查数据库状态')));
      card.addEventListener('click', () => showResult(result));
      card.addEventListener('keydown', (event) => { if (event.key === 'Enter') showResult(result); });
      target.append(card);
    }
    if (results.length) resultBeforeId = results.at(-1).execution_id;
    if (results.length === 20) {
      const more = el('button', 'secondary load-more', '查看更多执行记录');
      more.type = 'button';
      more.addEventListener('click', () => loadResults(false));
      target.append(more);
    }
  } catch (error) {
    target.replaceChildren(el('p', 'placeholder', error.message));
  }
}

async function openResult(id) {
  try { showResult(await api(`/api/results/${id}`)); }
  catch (error) { toast(error.message); }
}

function showResult(result) {
  $('dialog-title').textContent = `执行 #${result.execution_id}`;
  const target = $('result-detail');
  target.replaceChildren();
  target.append(el('div', 'detail-name', result.rule_name));
  const snap = result.rule_snapshot;
  target.append(el('div', 'detail-meta',
    `规则 #${result.rule_id} · ${snap.table_name}${snap.dataset_id ? ` [数据集 #${snap.dataset_id}]` : ''}.${snap.column_name} · ${snap.rule_type} · ${result.executed_at.replace('T', ' ')}`));
  if (snap.rule_type === 'ENUM') target.append(el('div', 'detail-meta', `允许值：${snap.params.allowed_values.map(formatValue).join('、')}`));
  if (result.status === 'FAILED') target.append(el('div', 'error-box', result.error || '执行失败'));
  if (result.status === 'SUCCEEDED') {
    const metrics = el('div', 'metrics');
    for (const [label, value] of [
      ['总记录数', result.total_count], ['参与校验', result.checked_count], ['通过', result.passed_count],
      ['不通过', result.failed_count], ['跳过', result.skipped_count],
      ['通过率', result.pass_rate === null ? 'N/A' : `${result.pass_rate}%`],
    ]) {
      const item = el('div', 'metric');
      item.append(el('strong', '', String(value)), el('span', '', label));
      metrics.append(item);
    }
    target.append(metrics);
    target.append(el('div', 'sample-head', `异常样例 ${result.samples.length} 条（最多保存 20 条，统计覆盖全部记录）`));
    if (!result.samples.length) target.append(el('p', 'empty-result', result.checked_count === 0 ? '无可校验数据，也没有异常样例。' : '没有异常样例。'));
    else {
      const table = el('table', 'sample-table');
      const head = el('thead');
      const row = el('tr');
      row.append(el('th', '', '订单 ID'), el('th', '', snap.column_name));
      head.append(row);
      const body = el('tbody');
      for (const sample of result.samples) {
        const r = el('tr');
        r.append(el('td', 'mono', String(sample.order_id)), el('td', '', formatValue(sample.field_value)));
        body.append(r);
      }
      table.append(head, body);
      target.append(table);
    }
  }
  $('result-dialog').showModal();
}

async function runRule(ruleId) {
  toast(`正在运行规则 #${ruleId}…`);
  try {
    const result = await api(`/api/rules/${ruleId}/run`, {method: 'POST', body: JSON.stringify({session_id: sessionId})});
    addMessage('user', `页面运行规则 #${ruleId}`);
    addMessage('assistant', `执行 #${result.execution_id}：${result.status}`,
      [{tool: 'run_quality_rule', status: result.status === 'SUCCEEDED' ? 'ok' : 'error',
        summary: `执行 #${result.execution_id}：${result.status}`,
        output: {ok: result.status === 'SUCCEEDED', data: result}}]);
    await loadResults();
    showResult(result);
    toast(result.status === 'SUCCEEDED' ? `执行 #${result.execution_id} 已保存` : `执行 #${result.execution_id} 失败`);
  } catch (error) { toast(error.message); }
}

let datasets = [];
let selectedSource = localStorage.getItem(`dq-source-${sessionId}`) || 'demo_orders';
let previewed = null;
function selectedDatasetId() { return selectedSource.startsWith('upload:') ? Number(selectedSource.slice(7)) : null; }
function selectedTable() { return selectedDatasetId() ? 'uploaded_orders' : selectedSource; }
function applySource() {
  selectedSource = $('data-source').value;
  localStorage.setItem(`dq-source-${sessionId}`, selectedSource);
  $('rule-table').value = selectedTable();
  updateColumns();
}
async function loadSchema() {
  try {
    datasets = await api('/api/datasets');
    schemaRows = await api('/api/schema');
    const tables = [...new Set(schemaRows.map(row => row.table_name))];
    $('rule-table').replaceChildren(...tables.map(table => { const o = el('option', '', table); o.value = table; return o; }));
    // One source selector controls both chat and the manual form.
    $('rule-table').disabled = true;
    const options = tables.filter(t => t !== 'uploaded_orders').map(t => { const o = el('option', '', `MySQL · ${t}`); o.value = t; return o; });
    datasets.forEach(d => { const o = el('option', '', `上传 #${d.id} · ${d.name} · ${d.row_count} 行`); o.value = `upload:${d.id}`; options.push(o); });
    if (!options.some(o => o.value === selectedSource)) {
      if (selectedDatasetId()) {
        try { const d = await api(`/api/datasets/${selectedDatasetId()}`); const o = el('option', '', `上传 #${d.id} · ${d.name} · ${d.row_count} 行`); o.value = selectedSource; options.push(o); }
        catch { selectedSource = 'demo_orders'; }
      } else selectedSource = 'demo_orders';
    }
    $('data-source').replaceChildren(...options);
    $('data-source').value = selectedSource;
    applySource();
  } catch (error) { toast(error.message); $('upload-state').textContent = error.message; }
}
$('data-source').addEventListener('change', applySource);
$('data-file').addEventListener('change', () => { previewed = null; $('import-file').disabled = true; $('data-preview').replaceChildren(); $('upload-state').textContent = '请先预览所选文件。'; });
function renderPreview(data) {
  const table = el('table'); const header = el('tr');
  data.columns.forEach(c => header.append(el('th', '', c))); table.append(header);
  data.samples.forEach(row => { const tr = el('tr'); data.columns.forEach(c => tr.append(el('td', '', row[c] === null ? 'NULL' : JSON.stringify(row[c])))); table.append(tr); });
  $('data-preview').replaceChildren(table);
}
async function uploadFile(commit) {
  const file = $('data-file').files[0];
  if (!file) return toast('请选择文件');
  if (file.size > 5 * 1024 * 1024) return toast('文件最大 5 MiB');
  if (commit && (!previewed || previewed.file !== file)) return toast('请重新预览文件');
  const form = new FormData(); form.append('file', file);
  if (commit) form.append('expected_sha256', previewed.sha256);
  $('preview-file').disabled = true; $('import-file').disabled = true; $('data-file').disabled = true;
  $('upload-state').textContent = commit ? '正在导入…' : '正在校验整个文件…';
  try {
    const data = await api(commit ? '/api/datasets' : '/api/datasets/preview', {method:'POST', headers:{}, body:form});
    if (commit) {
      selectedSource = `upload:${data.id}`;
      await loadSchema();
      $('upload-state').textContent = `${data.reused ? '已复用相同文件' : '导入成功'}：数据集 #${data.id}，${data.row_count} 行。现在可以对话或手动创建规则。`;
      previewed = null;
    } else {
      previewed = {file, sha256:data.sha256}; renderPreview(data);
      $('upload-state').textContent = `格式检查通过：${data.row_count} 行，展示前 5 行。尚未写入数据库，请确认导入。`;
    }
  } catch (error) { previewed = null; $('upload-state').textContent = error.message; }
  finally { $('preview-file').disabled = false; $('import-file').disabled = !previewed; $('data-file').disabled = false; }
}
$('preview-file').addEventListener('click', () => uploadFile(false));
$('import-file').addEventListener('click', () => uploadFile(true));

function updateColumns() {
  const select = $('rule-column');
  const columns = schemaRows.filter(row => row.table_name === $('rule-table').value && row.column_name !== 'order_id' && ['char','varchar','text','tinytext','mediumtext','longtext'].includes(row.data_type));
  select.replaceChildren(...columns.map(row => { const o = el('option', '', row.column_name); o.value = row.column_name; return o; }));
  if (columns.some(row => row.column_name === 'customer_name')) select.value = 'customer_name';
}

$('chat-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = $('chat-input');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  addMessage('user', message);
  $('chat-state').textContent = '处理中…';
  $('chat-submit').disabled = true;
  try {
    const response = await api('/api/chat', {method: 'POST', body: JSON.stringify({session_id: sessionId, message, dataset_id: selectedDatasetId(), table_name: selectedTable()})});
    addMessage('assistant', response.reply, response.traces);
    $('chat-state').textContent = response.status === 'failed' ? '失败，已保留完成的操作' : '已完成';
    await Promise.all([loadRules(), loadResults(), loadHealth()]);
  } catch (error) {
    addMessage('assistant', `请求失败：${error.message}`);
    $('chat-state').textContent = '失败';
    await Promise.allSettled([loadRules(), loadResults(), loadHealth()]);
  } finally { $('chat-submit').disabled = false; input.focus(); }
});

$('chat-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('chat-form').requestSubmit(); }
});
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
  $('chat-input').value = button.dataset.prompt;
  $('chat-input').focus();
}));
$('refresh-rules').addEventListener('click', loadRules);
$('refresh-results').addEventListener('click', loadResults);
$('close-dialog').addEventListener('click', () => $('result-dialog').close());
$('rule-table').addEventListener('change', updateColumns);
$('rule-type').addEventListener('change', () => { $('allowed-wrap').hidden = $('rule-type').value !== 'ENUM'; });
$('rule-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const ruleType = $('rule-type').value;
  const rawAllowed = $('rule-allowed').value;
  if (ruleType === 'ENUM' && !rawAllowed.trim()) { $('rule-form-state').textContent = '请填写允许值'; return; }
  const values = rawAllowed.split(',').map(value => value.trim());
  const payload = {
    name: $('rule-name').value, table_name: selectedTable(), dataset_id: selectedDatasetId(),
    column_name: $('rule-column').value, rule_type: ruleType,
    params: ruleType === 'ENUM' ? {allowed_values: values} : {}, session_id: sessionId,
  };
  $('rule-form-state').textContent = '保存中…';
  try {
    const rule = await api('/api/rules', {method: 'POST', body: JSON.stringify(payload)});
    addMessage('user', '页面创建质量规则');
    addMessage('assistant', `已创建规则 #${rule.rule_id}`,
      [{tool: 'create_quality_rule', status: 'ok', summary: `规则 #${rule.rule_id}`,
        output: {ok: true, data: rule}}]);
    $('rule-form-state').textContent = `已保存 #${rule.rule_id}`;
    await loadRules();
    toast(`规则 #${rule.rule_id} 已创建`);
  } catch (error) { $('rule-form-state').textContent = error.message; }
});

Promise.allSettled([loadHealth(), loadSchema(), loadRules(), loadResults(), loadChat()]);
