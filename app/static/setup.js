const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    cache: 'no-store',
    headers: {'Content-Type': 'application/json'},
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`);
  return body;
}

function state(id, text, good = false) {
  const node = $(id);
  node.textContent = text;
  node.className = `status-pill ${good ? 'good' : 'bad'}`;
}

function showConfig(config) {
  $('mysql-host').value = config.mysql_host;
  $('mysql-port').value = config.mysql_port;
  $('mysql-user').value = config.mysql_user;
  $('model-base-url').value = config.model_base_url && !config.model_base_url.includes('your-provider.example') ? config.model_base_url : 'https://api.deepseek.com';
  $('model-name').value = config.model_name && config.model_name !== 'your-tool-calling-model' ? config.model_name : 'deepseek-flash';
  $('model-provider').value = config.model_base_url.startsWith('https://api.deepseek.com') || !config.model_base_url ? 'deepseek' : 'custom';
  $('model-proxy-mode').value = config.model_proxy_mode || 'auto';
  $('model-proxy-url').value = config.model_proxy_url || '';
  $('model-proxy-wrap').hidden = $('model-proxy-mode').value !== 'custom';
  $('key-hint').textContent = config.model_api_key_set ? '已保存；留空则保持原密钥' : '尚未保存';
  $('password-hint').textContent = config.mysql_password_set ? '已保存；留空则保持原密码' : '尚未保存';
}

async function refreshStatus() {
  try {
    const health = await api('/api/health');
    state('setup-db-status', health.database === 'ok' ? '● MySQL 已连接' : '● MySQL 待连接', health.database === 'ok');
    const labels = {unconfigured: '● 模型待配置', untested: '● 模型已填写，尚未测试', ok: '● 模型工具调用已通过', error: '● 模型测试失败'};
    state('setup-model-status', labels[health.model_state] || '● 状态未知', health.model_state === 'ok');
  } catch (error) {
    state('setup-db-status', '● 服务不可用');
    state('setup-model-status', '● 状态未知');
  }
}

$('model-provider').addEventListener('change', () => {
  if ($('model-provider').value === 'deepseek') {
    $('model-base-url').value = 'https://api.deepseek.com';
    $('model-name').value = 'deepseek-flash';
  } else {
    $('model-base-url').value = '';
    $('model-name').value = '';
  }
});

$('model-proxy-mode').addEventListener('change', () => {
  $('model-proxy-wrap').hidden = $('model-proxy-mode').value !== 'custom';
});

$('model-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type=submit]');
  button.disabled = true;
  $('model-save-state').textContent = '保存中…';
  try {
    const config = await api('/api/settings', {method: 'POST', body: JSON.stringify({
      model_base_url: $('model-base-url').value.trim(),
      model_name: $('model-name').value.trim(),
      model_api_key: $('model-key').value,
      model_proxy_mode: $('model-proxy-mode').value,
      model_proxy_url: $('model-proxy-url').value.trim(),
    })});
    $('model-key').value = '';
    showConfig(config);
    $('model-save-state').textContent = '已保存；请测试模型和工具调用';
    await refreshStatus();
  } catch (error) { $('model-save-state').textContent = error.message; }
  finally { button.disabled = false; }
});

$('test-model').addEventListener('click', async () => {
  $('test-model').disabled = true;
  $('model-save-state').textContent = '正在测试模型与工具调用…';
  try {
    await api('/api/settings/test-model', {method: 'POST', body: '{}'});
    $('model-save-state').textContent = '测试通过：模型已返回工具调用';
  } catch (error) { $('model-save-state').textContent = error.message; }
  finally { $('test-model').disabled = false; await refreshStatus(); }
});

$('database-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type=submit]');
  button.disabled = true;
  $('database-save-state').textContent = '保存中…';
  try {
    const config = await api('/api/settings', {method: 'POST', body: JSON.stringify({
      mysql_host: $('mysql-host').value.trim(),
      mysql_port: Number($('mysql-port').value),
      mysql_user: $('mysql-user').value.trim(),
      mysql_password: $('mysql-password').value,
    })});
    $('mysql-password').value = '';
    showConfig(config);
    $('database-save-state').textContent = '已保存；点击“检测连接”验证数据库';
    await refreshStatus();
  } catch (error) { $('database-save-state').textContent = error.message; }
  finally { button.disabled = false; }
});

$('test-db').addEventListener('click', async () => {
  $('test-db').disabled = true;
  $('database-save-state').textContent = '正在检测…';
  try {
    const result = await api('/api/settings/test-database', {method: 'POST', body: '{}'});
    $('database-save-state').textContent = `连接成功：订单表有 ${result.demo_orders} 条记录`;
  } catch (error) { $('database-save-state').textContent = error.message; }
  finally { $('test-db').disabled = false; await refreshStatus(); }
});

$('init-db').addEventListener('click', async () => {
  $('init-db').disabled = true;
  $('init-state').textContent = '正在检查并初始化…';
  const admin = {admin_user: $('admin-user').value.trim() || null, admin_password: $('admin-password').value || null};
  $('admin-password').value = '';
  try {
    const result = await api('/api/settings/initialize-database', {method: 'POST', body: JSON.stringify(admin)});
    $('init-state').textContent = result.message;
  } catch (error) { $('init-state').textContent = error.message; }
  finally { $('init-db').disabled = false; await refreshStatus(); }
});

Promise.allSettled([
  api('/api/settings').then(showConfig).catch((error) => { $('model-save-state').textContent = error.message; }),
  refreshStatus(),
]);
