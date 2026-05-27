/** 장비 SNMP 모니터 — 실시간 트래픽 그래프 및 동적 정렬/검색 기능 */

let monitorDeviceId = null;
let monitorPollTimer = null;
let trafficChart = null;
let cpuChart = null;
let selectedIfIndex = null;

let currentPortsData = [];
let currentSortColumn = 'name'; 
let currentSortOrder = 'asc';   

function formatBps(bps) {
  if (bps == null || bps === 0) return '0 bps';
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(2)} Gbps`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(2)} Mbps`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(1)} Kbps`;
  return `${bps.toFixed(0)} bps`;
}

function portStatusBadge(port) {
  const cls = port.status === 'up' ? 'success' : port.status === 'shutdown' ? 'failed' : 'running';
  const label = port.status === 'shutdown' ? 'Shutdown' : port.status === 'up' ? 'Up' : 'Down';
  return `<span class="badge ${cls}">${label}</span>`;
}

/** [패치] DB에서 수신된 무타임존 UTC 원본 날짜를 브라우저 로컬 타임존(KST)으로 9시간 자동 보정하는 변환기 */
function parseUtcDate(dateStr) {
  if (!dateStr) return new Date();
  // 문자열 끝에 Z나 타임존 오프셋이 존재하지 않는 경우 강제로 'Z'(UTC 표준시)를 바인딩하여 9시간 시차 유실 원천 방지
  const cleanStr = dateStr.includes('Z') || dateStr.includes('+') ? dateStr : dateStr.replace(' ', 'T') + 'Z';
  return new Date(cleanStr);
}

/** [패치] 주식 변동창 스타일 지능형 가변 차트 레이블 포매터 */
function formatChartLabel(dateObj, totalMinutes) {
  if (totalMinutes <= 1440) { 
    // 24시간 이하 조건일 경우 단순 '시:분:초' 형식 가동
    return dateObj.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  // 1주일, 1개월 장기 조회일 경우 구분이 가능하도록 '월-일 시:분' 멀티 세그먼트 형식 자동 전환
  const mm = String(dateObj.getMonth() + 1).padStart(2, '0');
  const dd = String(dateObj.getDate()).padStart(2, '0');
  const hh = String(dateObj.getHours()).padStart(2, '0');
  const min = String(dateObj.getMinutes()).padStart(2, '0');
  return `${mm}-${dd} ${hh}:${min}`;
}

function getSelectedMinutes() {
  const val = $('#monitor-time-select')?.value || 'today';
  if (val === 'today') {
    const now = new Date();
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
    const diffMinutes = Math.floor((now - midnight) / 60000);
    return diffMinutes > 60 ? diffMinutes : 60;
  }
  return parseInt(val, 10);
}

async function openDeviceMonitor(deviceId, deviceName) {
  monitorDeviceId = deviceId;
  selectedIfIndex = null;
  currentSortColumn = 'name';
  currentSortOrder = 'asc';
  
  if ($('#port-search-input')) $('#port-search-input').value = '';
  if ($('#monitor-time-select')) $('#monitor-time-select').value = 'today';
  if ($('#cpu-chart-hint')) $('#cpu-chart-hint').textContent = '오늘 하루';

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
    const mins = getSelectedMinutes();
    const data = await api(`/api/v1/devices/${monitorDeviceId}/monitor/overview?minutes=${mins}`);
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

  currentPortsData = data.ports || [];
  displayPortsTable();

  renderCpuChart(data.recent_metrics);
  renderRawMetricsTable(data.recent_metrics);
}

function renderRawMetricsTable(metrics) {
  const rawTbody = $('#mon-raw-metrics-tbody');
  if (!rawTbody) return;

  if (!metrics || !metrics.length) {
    rawTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; padding: 24px;">수집 완료된 메트릭 이력이 없습니다.</td></tr>';
    return;
  }

  const sortedMetrics = [...metrics].reverse();

  rawTbody.innerHTML = sortedMetrics
    .map((m) => {
      // 로깅 테이블 타임스탬프 파싱단 동적 교정 적용
      const timeStr = parseUtcDate(m.recorded_at).toLocaleString('ko-KR');
      const cpuStr = m.cpu_percent != null ? `${m.cpu_percent.toFixed(1)}%` : '—';
      const memStr = m.memory_percent != null ? `${m.memory_percent.toFixed(1)}%` : '—';
      
      return `
        <tr>
          <td style="text-align: left; padding-left: 20px; font-variant-numeric: tabular-nums; color: #94a3b8;">${timeStr}</td>
          <td style="text-align: right; font-variant-numeric: tabular-nums; font-weight: 500; color: #3b82f6;">${cpuStr}</td>
          <td style="text-align: right; padding-right: 20px; font-variant-numeric: tabular-nums; font-weight: 500; color: #22c55e;">${memStr}</td>
        </tr>
      `;
    })
    .join('');
}

function matchCiscoPortName(portName, searchVal) {
  const name = portName.toLowerCase().replace(/\s+/g, '');
  const query = searchVal.toLowerCase().replace(/\s+/g, '');
  
  if (name.includes(query)) return true;
  
  let expanded = query;
  if (/^f\d/.test(query)) expanded = query.replace(/^f/, 'fastethernet');
  else if (/^fa\d/.test(query)) expanded = query.replace(/^fa/, 'fastethernet');
  else if (/^g\d/.test(query)) expanded = query.replace(/^g/, 'gigabitethernet');
  else if (/^gi\d/.test(query)) expanded = query.replace(/^gi/, 'gigabitethernet');
  else if (/^te\d/.test(query)) expanded = query.replace(/^te/, 'tengigabitethernet');
  else if (/^po\d/.test(query)) expanded = query.replace(/^po/, 'port-channel');
  else if (/^e\d/.test(query)) expanded = query.replace(/^e/, 'ethernet');

  return name.includes(expanded);
}

function displayPortsTable() {
  const tbody = $('#mon-ports-tbody');
  if (!tbody) return;

  const searchVal = $('#port-search-input')?.value.trim() || '';

  let filtered = currentPortsData.filter((p) => {
    if (!searchVal) return true;
    const matchesName = matchCiscoPortName(p.name, searchVal);
    const matchesAlias = p.alias && p.alias.toLowerCase().includes(searchVal.toLowerCase());
    return matchesName || matchesAlias;
  });

  filtered.sort((a, b) => {
    if (currentSortColumn === 'name') {
      const valA = a.name || '';
      const valB = b.name || '';
      return currentSortOrder === 'asc' 
        ? valA.localeCompare(valB, undefined, { numeric: true, sensitivity: 'base' }) 
        : valB.localeCompare(valA, undefined, { numeric: true, sensitivity: 'base' });
    }

    let valA, valB;
    switch (currentSortColumn) {
      case 'status':
        valA = a.status || ''; valB = b.status || '';
        break;
      case 'in':
        valA = a.last_in_bps || 0; valB = b.last_in_bps || 0;
        break;
      case 'out':
        valA = a.last_out_bps || 0; valB = b.last_out_bps || 0;
        break;
      case 'in_avg':
        valA = a.last_in_avg_bps || 0; valB = b.last_in_avg_bps || 0;
        break;
      case 'out_avg':
        valA = a.last_out_avg_bps || 0; valB = b.last_out_avg_bps || 0;
        break;
      default:
        valA = 0; valB = 0;
    }

    if (typeof valA === 'string') {
      return currentSortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
    } else {
      return currentSortOrder === 'asc' ? valA - valB : valB - valA;
    }
  });

  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 24px;">검색 결과와 일치하는 포트 정보가 없습니다.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered
    .map(
      (p) => `
    <tr class="port-row ${selectedIfIndex === p.if_index ? 'selected' : ''}" data-if="${p.if_index}" data-name="${esc(p.name)}">
      <td style="text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-left: 20px;">
        <strong>${esc(p.name)}</strong>
        ${p.alias ? `<br><small style="color: #748094; font-size: 11px; display: block; margin-top: 2px;">${esc(p.alias)}</small>` : ''}
      </td>
      <td style="text-align: left;">
        ${portStatusBadge(p)}
        <small style="color: #94a3b8; font-size: 11px; display: block; margin-top: 2px; font-weight: 500;">${formatBps(p.speed_bps)}</small>
      </td>
      <td class="num" style="text-align: right; font-variant-numeric: tabular-nums;">${formatBps(p.last_in_bps)}</td>
      <td class="num" style="text-align: right; font-variant-numeric: tabular-nums;">${formatBps(p.last_out_bps)}</td>
      <td class="num muted" style="text-align: right; font-variant-numeric: tabular-nums;">${formatBps(p.last_in_avg_bps)}</td>
      <td class="num muted" style="text-align: right; font-variant-numeric: tabular-nums; padding-right: 20px;">${formatBps(p.last_out_avg_bps)}</td>
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

  updateSortIcons();
}

function updateSortIcons() {
  document.querySelectorAll('.ports-table th.sortable').forEach((th) => {
    const col = th.dataset.sort;
    const iconEl = th.querySelector('.sort-icon');
    if (iconEl) {
      if (currentSortColumn === col) {
        iconEl.textContent = currentSortOrder === 'asc' ? '▲' : '▼';
        th.style.color = '#3b82f6'; 
      } else {
        iconEl.textContent = '↕';
        th.style.color = '';
      }
    }
  });
}

function renderCpuChart(metrics) {
  const ctx = document.getElementById('cpu-chart');
  if (!ctx || typeof Chart === 'undefined') return;
  
  // 차트 축 레이블 시차 연동 보정
  const mins = getSelectedMinutes();
  const labels = metrics.map((m) => formatChartLabel(parseUtcDate(m.recorded_at), mins));
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
  const mins = getSelectedMinutes();
  const history = await api(
    `/api/v1/devices/${monitorDeviceId}/monitor/ports/${ifIndex}/traffic?minutes=${mins}`
  );
  const ctx = document.getElementById('traffic-chart');
  if (!ctx) return;
  
  // 포트 트래픽 그래프 레이블 시차 보정
  const labels = history.samples.map((s) => formatChartLabel(parseUtcDate(s.recorded_at), mins));
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

  $('#port-search-input')?.addEventListener('input', () => {
    displayPortsTable();
  });

  $('#monitor-time-select')?.addEventListener('change', () => {
    const selectedText = $('#monitor-time-select').options[$('#monitor-time-select').selectedIndex].text;
    if ($('#cpu-chart-hint')) $('#cpu-chart-hint').textContent = selectedText;
    refreshMonitor();
  });

  document.querySelectorAll('.ports-table th.sortable').forEach((th) => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (currentSortColumn === col) {
        currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
      } else {
        currentSortColumn = col;
        currentSortOrder = 'asc';
      }
      displayPortsTable();
    });
  });
}

document.addEventListener('DOMContentLoaded', initMonitor);