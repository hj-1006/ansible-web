/** 장비 SNMP 모니터 — 실시간 트래픽 그래프 */

let monitorDeviceId = null;
let monitorPollTimer = null;
let trafficChart = null;
let cpuChart = null;
let selectedIfIndex = null;

function formatBps(bps) {
  if (bps == null || bps === 0) return '0 bps';
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(2)} Gbps`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(2)} Mbps`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(1)} Kbps`;
  return `${bps.toFixed(0)} bps`;
}

function portStatusBadge(port) {
  // 포트 상태에 따른 직관적인 클래스 배정
  const cls = port.status === 'up' ? 'success' : port.status === 'shutdown' ? 'failed' : 'running';
  const label = port.status === 'shutdown' ? 'Shutdown' : port.status === 'up' ? 'Up' : 'Down';
  return `<span class="badge ${cls}">${label}</span>`;
}

async function openDeviceMonitor(deviceId, deviceName) {
  monitorDeviceId = deviceId;
  selectedIfIndex = null;
  $('#page-title').textContent = `모니터링 · ${deviceName}`;
  $$('.view').forEach((el) => el.classList.remove('active'));
  $('#view-monitor').classList.add('active');
  $$('.nav-item').forEach((el) => el.classList.remove('active'));

  if (trafficChart) {
    trafficChart.destroy();
    trafficChart = null;
  }
  if (cpuChart) {
    cpuChart.destroy();
    cpuChart = null;
  }

  await refreshMonitor();
  if (monitorPollTimer) clearInterval(monitorPollTimer);
  monitorPollTimer = setInterval(refreshMonitor, 10000);
}

function closeDeviceMonitor() {
  if (monitorPollTimer) {
    clearInterval(monitorPollTimer);
    monitorPollTimer = null;
  }
  monitorDeviceId = null;
  switchView('devices');
}

async function refreshMonitor() {
  if (!monitorDeviceId) return;
  try {
    const data = await api(`/api/v1/devices/${monitorDeviceId}/monitor/overview`);
    renderMonitorOverview(data);
    if (selectedIfIndex != null) {
      await loadPortTrafficChart(selectedIfIndex);
    }
  } catch (e) {
    console.error(e);
  }
}

function renderMonitorOverview(data) {
  const d = data.device;
  $('#mon-device-name').textContent = d.name;
  $('#mon-device-host').textContent = `${d.host} · ${d.cisco_platform || 'ios'}`;
  $('#mon-cpu').textContent = d.last_cpu_percent != null ? `${d.last_cpu_percent.toFixed(1)}%` : '—';
  $('#mon-mem').textContent = d.last_memory_percent != null ? `${d.last_memory_percent.toFixed(1)}%` : '—';
  $('#mon-snmp-status').textContent = d.snmp_last_status || '—';
  $('#mon-snmp-status').className = `metric-pill ${d.snmp_last_status === 'success' ? 'ok' : ''}`;

  const tbody = $('#mon-ports-tbody');
  if (!data.ports.length) {
    tbody.innerHTML = '<tr><td colspan="6">포트 없음 — SNMP 탐색을 실행하세요.</td></tr>';
    return;
  }
  
  // 대역폭(speed_bps) 및 세부 활성화 상태 유무 데이터를 컬럼 내부에 완벽히 녹여냄
  tbody.innerHTML = data.ports
    .map(
      (p) => `
    <tr class="port-row ${selectedIfIndex === p.if_index ? 'selected' : ''}" data-if="${p.if_index}" data-name="${esc(p.name)}">
      <td>
        <strong>${esc(p.name)}</strong>
        ${p.alias ? `<br><small style="color: #748094; font-size: 11px; display: block; margin-top: 2px;">${esc(p.alias)}</small>` : ''}
      </td>
      <td>
        ${portStatusBadge(p)}
        <small style="color: #94a3b8; font-size: 11px; display: block; margin-top: 2px; font-weight: 500;">${formatBps(p.speed_bps)}</small>
      </td>
      <td class="num">${formatBps(p.last_in_bps)}</td>
      <td class="num">${formatBps(p.last_out_bps)}</td>
      <td class="num muted">${formatBps(p.last_in_avg_bps)}</td>
      <td class="num muted">${formatBps(p.last_out_avg_bps)}</td>
    </tr>`
    )
    .join('');

  tbody.querySelectorAll('.port-row').forEach((row) => {
    row.addEventListener('click', () => {
      selectedIfIndex = parseInt(row.dataset.if, 10);
      $('#mon-port-title').textContent = row.dataset.name;
      tbody.querySelectorAll('.port-row').forEach((r) => r.classList.remove('selected'));
      row.classList.add('selected');
      loadPortTrafficChart(selectedIfIndex);
    });
  });

  renderCpuChart(data.recent_metrics);
}

function renderCpuChart(metrics) {
  const ctx = document.getElementById('cpu-chart');
  if (!ctx || typeof Chart === 'undefined') return;
  const labels = metrics.map((m) => new Date(m.recorded_at).toLocaleTimeString('ko-KR'));
  const cpu = metrics.map((m) => m.cpu_percent ?? null);
  const mem = metrics.map((m) => m.memory_percent ?? null);
  if (cpuChart) cpuChart.destroy();
  cpuChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'CPU %',
          data: cpu,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.15)',
          fill: true,
          tension: 0.3,
        },
        {
          label: 'Memory %',
          data: mem,
          borderColor: '#22c55e',
          backgroundColor: 'rgba(34,197,94,0.1)',
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#9aa3b2' } } },
      scales: {
        x: { ticks: { color: '#6b7280', maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,0.06)' } },
        y: { min: 0, max: 100, ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.06)' } },
      },
    },
  });
}

async function loadPortTrafficChart(ifIndex) {
  const history = await api(
    `/api/v1/devices/${monitorDeviceId}/monitor/ports/${ifIndex}/traffic?minutes=60`
  );
  const ctx = document.getElementById('traffic-chart');
  if (!ctx) return;
  const labels = history.samples.map((s) =>
    new Date(s.recorded_at).toLocaleTimeString('ko-KR')
  );
  if (trafficChart) trafficChart.destroy();
  trafficChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Inbound',
          data: history.samples.map((s) => s.in_bps),
          borderColor: '#60a5fa',
          backgroundColor: 'rgba(96,165,250,0.12)',
          fill: true,
          tension: 0.25,
        },
        {
          label: 'Outbound',
          data: history.samples.map((s) => s.out_bps),
          borderColor: '#f472b6',
          backgroundColor: 'rgba(244,114,182,0.1)',
          fill: true,
          tension: 0.25,
        },
        {
          label: 'In (avg)',
          data: history.samples.map((s) => s.in_avg_bps),
          borderColor: '#94a3b8',
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.25,
        },
        {
          label: 'Out (avg)',
          data: history.samples.map((s) => s.out_avg_bps),
          borderColor: '#64748b',
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#9aa3b2' } },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${formatBps(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: '#6b7280', maxTicksLimit: 10 }, grid: { color: 'rgba(255,255,255,0.06)' } },
        y: {
          ticks: {
            color: '#6b7280',
            callback: (v) => formatBps(v),
          },
          grid: { color: 'rgba(255,255,255,0.06)' },
        },
      },
    },
  });
}

async function monitorDiscover() {
  if (!monitorDeviceId) return;
  try {
    const r = await api(`/api/v1/devices/${monitorDeviceId}/monitor/discover`, { method: 'POST' });
    alert(`포트 ${r.ports_discovered}개 탐색 완료`);
    await refreshMonitor();
  } catch (e) {
    alert(e.message);
  }
}

async function monitorPollNow() {
  if (!monitorDeviceId) return;
  try {
    await api(`/api/v1/devices/${monitorDeviceId}/monitor/poll`, { method: 'POST' });
    await refreshMonitor();
  } catch (e) {
    alert(e.message);
  }
}

function initMonitor() {
  $('#mon-back-btn')?.addEventListener('click', closeDeviceMonitor);
  $('#mon-discover-btn')?.addEventListener('click', monitorDiscover);
  $('#mon-poll-btn')?.addEventListener('click', monitorPollNow);
}

document.addEventListener('DOMContentLoaded', initMonitor);