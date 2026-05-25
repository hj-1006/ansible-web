const API_BASE = '';
const STORAGE_KEY = 'ansible_web_api_key';

let apiKey = localStorage.getItem(STORAGE_KEY) || '';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'X-API-Key': apiKey,
    ...(options.headers || {}),
  };
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch (err) {
    const host = window.location.origin || '서버';
    throw new Error(
      `백엔드에 연결할 수 없습니다 (${host}).\n` +
        `Linux 서버에서 ./start-server.sh 또는 ./venv/bin/python run.py 를 실행했는지 확인하세요.\n` +
        `Windows에서 테스트 시 주소창은 http://리눅스서버IP:8080 이어야 합니다 (localhost 아님).`
    );
  }
  if (res.status === 401 || res.status === 403) {
    logout();
    throw new Error('API 키가 유효하지 않습니다.');
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function logout() {
  localStorage.removeItem(STORAGE_KEY);
  apiKey = '';
  $('#app-layout').classList.add('hidden');
  $('#auth-overlay').classList.remove('hidden');
}

function showApp() {
  $('#auth-overlay').classList.add('hidden');
  $('#app-layout').classList.remove('hidden');
}

function switchView(name) {
  $$('.nav-item').forEach((el) => el.classList.toggle('active', el.dataset.view === name));
  $$('.view').forEach((el) => el.classList.remove('active'));
  $(`#view-${name}`)?.classList.add('active');
  const titles = {
    dashboard: '대시보드',
    devices: '장비 관리',
    jobs: '작업 이력',
    'api-keys': 'API 키',
    'api-help': 'API 문서',
  };
  $('#page-title').textContent = titles[name] || name;
  if (name === 'devices') loadDevices();
  if (name === 'jobs') loadJobs();
  if (name === 'api-keys') loadApiKeys();
  if (name === 'api-help') renderApiHelp();
  if (name === 'dashboard') refreshDashboard();
}

async function checkHealth() {
  const el = $('#health-status');
  const dot = el?.querySelector('.status-dot');
  try {
    const h = await fetch(`${API_BASE}/api/v1/health`).then((r) => r.json());
    const ok = h.status === 'ok';
    el.innerHTML = `<span class="status-dot"></span>${ok ? '서버 정상' : '연결 저하'}`;
    el.classList.toggle('ok', ok);
  } catch {
    el.innerHTML = '<span class="status-dot"></span>서버 오프라인';
    el.classList.remove('ok');
  }
}

async function refreshDashboard() {
  try {
    const [devices, jobs] = await Promise.all([
      api('/api/v1/devices'),
      api('/api/v1/jobs?limit=10'),
    ]);
    $('#stat-devices').textContent = devices.length;
    $('#stat-jobs').textContent = jobs.length;
  } catch (e) {
    console.error(e);
  }
}

const PLATFORM_LABELS = {
  catalyst_2960: 'C2960',
  catalyst_3560: 'C3560',
  cisco_2821: 'ISR 2821',
  asa_5512: 'ASA 5512',
  generic_ios: 'IOS',
};

async function loadDevices() {
  const tbody = $('#devices-tbody');
  const emptyEl = $('#devices-empty');
  const table = tbody?.closest('table');
  tbody.innerHTML = '<tr><td colspan="6" class="loading-cell">로딩 중…</td></tr>';
  try {
    const devices = await api('/api/v1/devices');
    if (!devices.length) {
      tbody.innerHTML = '';
      emptyEl?.classList.remove('hidden');
      table?.classList.add('hidden');
      return;
    }
    emptyEl?.classList.add('hidden');
    table?.classList.remove('hidden');
    tbody.innerHTML = devices
      .map(
        (d) => `
      <tr>
        <td><span class="device-name">${esc(d.name)}</span></td>
        <td><code>${esc(d.host)}</code><span class="text-muted">:${d.port}</span></td>
        <td>${esc(d.device_type)}</td>
        <td>${esc(PLATFORM_LABELS[d.cisco_platform] || d.network_os)}</td>
        <td>${d.enabled ? '<span class="badge success">활성</span>' : '<span class="badge failed">비활성</span>'}</td>
        <td class="col-actions">
          <div class="btn-group">
            <button class="btn primary small" data-monitor="${d.id}" data-name="${esc(d.name)}">모니터</button>
            <button class="btn ghost small" data-test="${d.id}">테스트</button>
            <button class="btn ghost small" data-cmd="${d.id}">명령</button>
            <button class="btn ghost small" data-edit="${d.id}">수정</button>
            <button class="btn danger small" data-del="${d.id}">삭제</button>
          </div>
        </td>
      </tr>`
      )
      .join('');

    tbody.querySelectorAll('[data-monitor]').forEach((btn) =>
      btn.addEventListener('click', () => openDeviceMonitor(btn.dataset.monitor, btn.dataset.name))
    );
    tbody.querySelectorAll('[data-test]').forEach((btn) =>
      btn.addEventListener('click', () => testDevice(btn.dataset.test))
    );
    tbody.querySelectorAll('[data-cmd]').forEach((btn) =>
      btn.addEventListener('click', () => openCommandModal(btn.dataset.cmd))
    );
    tbody.querySelectorAll('[data-edit]').forEach((btn) =>
      btn.addEventListener('click', () => editDevice(btn.dataset.edit, devices))
    );
    tbody.querySelectorAll('[data-del]').forEach((btn) =>
      btn.addEventListener('click', () => deleteDevice(btn.dataset.del))
    );
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6">${esc(e.message)}</td></tr>`;
  }
}

async function loadJobs() {
  const tbody = $('#jobs-tbody');
  try {
    const jobs = await api('/api/v1/jobs?limit=50');
    tbody.innerHTML = jobs
      .map(
        (j) => `
      <tr>
        <td>${j.id}</td>
        <td>${esc(j.job_type)}</td>
        <td>${esc(j.target_hosts)}</td>
        <td><span class="badge ${j.status}">${esc(j.status)}</span></td>
        <td>${formatDate(j.created_at)}</td>
        <td><button class="btn small ghost" data-job="${j.id}">상세</button></td>
      </tr>`
      )
      .join('');
    tbody.querySelectorAll('[data-job]').forEach((btn) =>
      btn.addEventListener('click', () => showJobDetail(btn.dataset.job, jobs))
    );
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6">${esc(e.message)}</td></tr>`;
  }
}

async function loadApiKeys() {
  const tbody = $('#keys-tbody');
  try {
    const keys = await api('/api/v1/api-keys');
    tbody.innerHTML = keys
      .map(
        (k) => `
      <tr>
        <td>${esc(k.name)}</td>
        <td><code>${esc(k.key_prefix)}...</code></td>
        <td>${k.is_active ? '활성' : '비활성'}</td>
        <td>${formatDate(k.created_at)}</td>
        <td>${k.is_active ? `<button class="btn small danger" data-revoke="${k.id}">폐기</button>` : ''}</td>
      </tr>`
      )
      .join('');
    tbody.querySelectorAll('[data-revoke]').forEach((btn) =>
      btn.addEventListener('click', () => revokeKey(btn.dataset.revoke))
    );
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5">${esc(e.message)}</td></tr>`;
  }
}

function renderApiHelp() {
  const base = window.location.origin;
  $('#api-examples').textContent = `# 장비 목록
curl -H "X-API-Key: YOUR_KEY" ${base}/api/v1/devices

# 통신 테스트
curl -X POST -H "X-API-Key: YOUR_KEY" \\
  "${base}/api/v1/devices/1/test?ping_target=8.8.8.8"

# 명령 실행
curl -X POST -H "X-API-Key: YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"command":"show version"}' \\
  ${base}/api/v1/devices/1/command

# 전체 테스트
curl -X POST -H "X-API-Key: YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"ping_target":"1.1.1.1"}' \\
  ${base}/api/v1/devices/test/bulk`;
}

async function testDevice(id) {
  const target = $('#bulk-ping-target')?.value || '8.8.8.8';
  try {
    const job = await api(`/api/v1/devices/${id}/test?ping_target=${encodeURIComponent(target)}`, {
      method: 'POST',
    });
    showJobModal(job);
    loadJobs();
  } catch (e) {
    alert(e.message);
  }
}

async function deleteDevice(id) {
  if (!confirm('이 장비를 삭제할까요?')) return;
  await api(`/api/v1/devices/${id}`, { method: 'DELETE' });
  loadDevices();
  refreshDashboard();
}

function openCommandModal(deviceId) {
  $('#cmd-device-id').value = deviceId;
  $('#cmd-input').value = '';
  $('#command-modal').classList.remove('hidden');
}

async function runCommand() {
  const id = $('#cmd-device-id').value;
  const command = $('#cmd-input').value.trim();
  if (!command) return;
  try {
    const job = await api(`/api/v1/devices/${id}/command`, {
      method: 'POST',
      body: JSON.stringify({ command }),
    });
    $('#command-modal').classList.add('hidden');
    showJobModal(job);
  } catch (e) {
    alert(e.message);
  }
}

function showJobModal(job) {
  $('#job-detail').textContent = [
    `상태: ${job.status}`,
    `유형: ${job.job_type}`,
    `대상: ${job.target_hosts}`,
    job.command ? `명령: ${job.command}` : '',
    '--- stdout ---',
    job.result_stdout || '(없음)',
    '--- stderr ---',
    job.result_stderr || job.error_message || '(없음)',
  ].join('\n');
  $('#job-modal').classList.remove('hidden');
}

function showJobDetail(id, jobs) {
  const job = jobs.find((j) => String(j.id) === String(id));
  if (job) showJobModal(job);
}

function openDeviceModal(device = null) {
  $('#modal-title').textContent = device ? '장비 수정' : '장비 추가';
  const sub = document.querySelector('.modal-subtitle');
  if (sub) {
    sub.textContent = device
      ? `${device.host} — 접속·SNMP 설정 변경`
      : '접속 정보 및 SNMP 모니터링 설정';
  }
  $('#device-id').value = device?.id || '';
  const form = $('#device-form');
  form.name.value = device?.name || '';
  form.host.value = device?.host || '';
  form.port.value = device?.port || 22;
  form.username.value = device?.username || '';
  form.password.value = '';
  form.device_type.value = device?.device_type || 'network';
  form.network_os.value = device?.network_os || 'ios';
  if (form.cisco_platform) form.cisco_platform.value = device?.cisco_platform || 'catalyst_2960';
  if (form.snmp_enabled) form.snmp_enabled.checked = !!device?.snmp_enabled;
  if (form.snmp_monitor_enabled) form.snmp_monitor_enabled.checked = !!device?.snmp_monitor_enabled;
  if (form.snmp_community) form.snmp_community.value = device?.snmp_community || 'public';
  if (form.snmp_port) form.snmp_port.value = device?.snmp_port || 161;
  if (form.snmp_poll_interval) form.snmp_poll_interval.value = device?.snmp_poll_interval || 30;
  form.groups.value = device?.groups || '';
  form.description.value = device?.description || '';
  form.enabled.checked = device?.enabled !== false;
  $('#modal').classList.remove('hidden');
}

function editDevice(id, devices) {
  const device = devices.find((d) => String(d.id) === String(id));
  openDeviceModal(device);
}

async function saveDevice(e) {
  e.preventDefault();
  const form = e.target;
  const id = $('#device-id').value;
  const body = {
    name: form.name.value,
    host: form.host.value,
    port: parseInt(form.port.value, 10) || 22,
    username: form.username.value,
    password: form.password.value,
    device_type: form.device_type.value,
    network_os: form.network_os.value,
    cisco_platform: form.cisco_platform?.value || 'catalyst_2960',
    snmp_enabled: !!form.snmp_enabled?.checked,
    snmp_monitor_enabled: !!form.snmp_monitor_enabled?.checked,
    snmp_community: form.snmp_community?.value || 'public',
    snmp_port: parseInt(form.snmp_port?.value, 10) || 161,
    snmp_poll_interval: parseInt(form.snmp_poll_interval?.value, 10) || 30,
    groups: form.groups.value,
    description: form.description.value,
    enabled: form.enabled.checked,
  };
  try {
    if (id) {
      const patch = { ...body };
      if (!patch.password) delete patch.password;
      await api(`/api/v1/devices/${id}`, { method: 'PATCH', body: JSON.stringify(patch) });
    } else {
      await api('/api/v1/devices', { method: 'POST', body: JSON.stringify(body) });
    }
    $('#modal').classList.add('hidden');
    loadDevices();
    refreshDashboard();
  } catch (err) {
    alert(err.message);
  }
}

async function bulkTest() {
  const ping_target = $('#bulk-ping-target').value || '8.8.8.8';
  const el = $('#bulk-result');
  el.classList.remove('hidden');
  el.textContent = '테스트 실행 중... (시간이 걸릴 수 있습니다)';
  try {
    const jobs = await api('/api/v1/devices/test/bulk', {
      method: 'POST',
      body: JSON.stringify({ ping_target }),
    });
    el.textContent = jobs
      .map((j) => `[${j.target_hosts}] ${j.status}\n${j.result_stdout?.slice(0, 500) || j.error_message}`)
      .join('\n\n---\n\n');
    refreshDashboard();
  } catch (e) {
    el.textContent = e.message;
  }
}

async function createApiKey() {
  const name = prompt('API 키 이름 (예: remote-server-1)');
  if (!name) return;
  try {
    const res = await api('/api/v1/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    alert(`새 API 키 (한 번만 표시됩니다):\n\n${res.api_key}`);
    loadApiKeys();
  } catch (e) {
    alert(e.message);
  }
}

async function revokeKey(id) {
  if (!confirm('이 API 키를 폐기할까요?')) return;
  await api(`/api/v1/api-keys/${id}`, { method: 'DELETE' });
  loadApiKeys();
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
}

function formatDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('ko-KR');
}

function init() {
  $('#auth-save-btn').addEventListener('click', () => {
    const key = $('#api-key-input').value.trim();
    if (!key) return;
    apiKey = key;
    localStorage.setItem(STORAGE_KEY, key);
    showApp();
    checkHealth();
    refreshDashboard();
  });

  $('#logout-btn').addEventListener('click', logout);
  $$('.nav-item').forEach((btn) =>
    btn.addEventListener('click', () => switchView(btn.dataset.view))
  );

  const closeModal = () => $('#modal').classList.add('hidden');
  $('#add-device-btn').addEventListener('click', () => openDeviceModal());
  $('#empty-add-device')?.addEventListener('click', () => openDeviceModal());
  $('#device-form').addEventListener('submit', saveDevice);
  $('#modal-cancel').addEventListener('click', closeModal);
  $('#modal-cancel-x')?.addEventListener('click', closeModal);
  $$('[data-close="modal"]').forEach((el) => el.addEventListener('click', closeModal));
  $('#bulk-test-btn').addEventListener('click', bulkTest);
  $('#create-key-btn').addEventListener('click', createApiKey);
  $('#cmd-run').addEventListener('click', runCommand);
  $('#cmd-cancel').addEventListener('click', () => $('#command-modal').classList.add('hidden'));
  $('#cmd-cancel-x')?.addEventListener('click', () => $('#command-modal').classList.add('hidden'));
  $('#job-modal-close').addEventListener('click', () => $('#job-modal').classList.add('hidden'));
  $$('[data-close="job-modal"]').forEach((el) =>
    el.addEventListener('click', () => $('#job-modal').classList.add('hidden'))
  );
  $$('[data-close="command-modal"]').forEach((el) =>
    el.addEventListener('click', () => $('#command-modal').classList.add('hidden'))
  );

  if (apiKey) {
    showApp();
    checkHealth();
    refreshDashboard();
  }
}

init();
