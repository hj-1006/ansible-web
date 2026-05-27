/** Aion 솔루션 인프라 모니터링 — 고정밀 타임라인 드래그 및 격자 보정 제어 엔진 */

let monitorDeviceId = null;
let monitorPollTimer = null;
let trafficChart = null;
let cpuChart = null;
let expandedChart = null; 
let selectedIfIndex = null;

let currentPortsData = [];
let currentSortColumn = 'name'; 
let currentSortOrder = 'asc';   

let cachedRecentMetrics = [];
let cachedTrafficSamples = [];

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

function parseUtcDate(dateStr) {
  if (!dateStr) return new Date();
  const cleanStr = dateStr.includes('Z') || dateStr.includes('+') ? dateStr : dateStr.replace(' ', 'T') + 'Z';
  return new Date(cleanStr);
}

function formatChartLabel(dateObj, totalMinutes) {
  if (totalMinutes <= 1440) { 
    return dateObj.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
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

function fillTimelineGaps(samples, totalMinutes, valueKeys) {
  const now = new Date();
  let startTime;
  if ($('#monitor-time-select')?.value === 'today') {
    startTime = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
  } else {
    startTime = new Date(now.getTime() - totalMinutes * 60 * 1000);
  }
  const endTime = now;
  const totalMs = endTime - startTime;

  let numBuckets = 60;
  if (totalMinutes <= 60) numBuckets = 60;
  else if (totalMinutes <= 360) numBuckets = 120;
  else if (totalMinutes <= 1440) numBuckets = 144;
  else if (totalMinutes <= 10080) numBuckets = 168;
  else numBuckets = 200;

  const bucketMs = totalMs / numBuckets;
  const buckets = [];

  for (let i = 0; i < numBuckets; i++) {
    const bucketTime = new Date(startTime.getTime() + (i * bucketMs) + (bucketMs / 2));
    const bucketObj = {
      time: bucketTime,
      label: formatChartLabel(bucketTime, totalMinutes),
      count: 0
    };
    valueKeys.forEach(k => bucketObj[k] = 0);
    buckets.push(bucketObj);
  }

  samples.forEach(s => {
    const sTime = parseUtcDate(s.recorded_at || s.timestamp);
    if (sTime >= startTime && sTime <= endTime) {
      const pct = (sTime - startTime) / totalMs;
      let bIdx = Math.floor(pct * numBuckets);
      if (bIdx >= numBuckets) bIdx = numBuckets - 1;
      if (bIdx < 0) bIdx = 0;

      valueKeys.forEach(k => {
        const val = parseFloat(s[k]);
        if (!isNaN(val)) {
          buckets[bIdx][k] += val;
        }
      });
      buckets[bIdx].count += 1;
    }
  });

  buckets.forEach(b => {
    if (b.count > 1) {
      valueKeys.forEach(k => {
        b[k] = b[k] / b.count;
      });
    }
  });

  return buckets;
}

async function openDeviceMonitor(deviceId, deviceName) {
  monitorDeviceId = deviceId;
  selectedIfIndex = null;
  currentSortColumn = 'name';
  currentSortOrder = 'asc';
  
  if ($('#port-search-input')) $('#port-search-input').value = '';
  if ($('#monitor-time-select')) $('#monitor-time-select').value = 'today';
  if ($('#cpu-chart-hint')) $('#cpu-chart-hint').textContent = '오늘 하루 (클릭 시 세부 격자 분석 패널 확장)';

  $('#page-title').textContent = `모니터링 · ${deviceName}`;
  $$('.view').forEach((el) => el.classList.remove('active'));
  $('#view-monitor').classList.add('active');
  $$('.nav-item').forEach((el) => el.classList.remove('active'));

  if (trafficChart) { trafficChart.destroy(); trafficChart = null; }
  if (cpuChart) { cpuChart.destroy(); cpuChart = null; }
  closeZoomChartModal();

  await refreshMonitor();
  if (monitorPollTimer) clearInterval(monitorPollTimer);
  monitorPollTimer = setInterval(refreshMonitor, 10000);
}

function closeDeviceMonitor() {
  if (monitorPollTimer) { clearInterval(monitorPollTimer); monitorPollTimer = null; }
  monitorDeviceId = null;
  closeZoomChartModal();
  switchView('devices');
}

async function refreshMonitor() {
  if (!monitorDeviceId) return;
  try {
    const mins = getSelectedMinutes();
    const data = await api(`/api/v1/devices/${monitorDeviceId}/monitor/overview?minutes=${mins}`);
    cachedRecentMetrics = data.recent_metrics || [];
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
  
  const latestMetric = data.recent_metrics && data.recent_metrics.length ? data.recent_metrics[data.recent_metrics.length - 1] : null;
  const cpuVal = latestMetric && latestMetric.cpu_percent != null ? latestMetric.cpu_percent : d.last_cpu_percent;
  const memVal = latestMetric && latestMetric.memory_percent != null ? latestMetric.memory_percent : d.last_memory_percent;

  $('#mon-cpu').textContent = cpuVal != null ? `${cpuVal.toFixed(1)}%` : '—';
  $('#mon-mem').textContent = memVal != null ? `${memVal.toFixed(1)}%` : '—';
  
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
      const timeStr = parseUtcDate(m.recorded_at).toLocaleString('ko-KR');
      const cpuStr = m.cpu_percent != null ? `${m.cpu_percent.toFixed(1)}%` : '—';
      const memStr = m.memory_percent != null ? `${m.memory_percent.toFixed(1)}%` : '—';
      return `<tr><td style="text-align: left; padding-left: 20px; font-variant-numeric: tabular-nums; color: #94a3b8;">${timeStr}</td><td style="text-align: right; font-variant-numeric: tabular-nums; font-weight: 500; color: #3b82f6;">${cpuStr}</td><td style="text-align: right; padding-right: 20px; font-variant-numeric: tabular-nums; font-weight: 500; color: #22c55e;">${memStr}</td></tr>`;
    }).join('');
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
  return name.includes(expanded);
}

function displayPortsTable() {
  const tbody = $('#mon-ports-tbody');
  if (!tbody) return;
  const searchVal = $('#port-search-input')?.value.trim() || '';
  let filtered = currentPortsData.filter((p) => {
    if (!searchVal) return true;
    return matchCiscoPortName(p.name, searchVal) || (p.alias && p.alias.toLowerCase().includes(searchVal.toLowerCase()));
  });

  filtered.sort((a, b) => {
    if (currentSortColumn === 'name') {
      return currentSortOrder === 'asc' ? a.name.localeCompare(b.name, undefined, { numeric: true }) : b.name.localeCompare(a.name, undefined, { numeric: true });
    }
    let valA = a[currentSortColumn === 'status' ? 'status' : `last_${currentSortColumn}_bps`] || 0;
    let valB = b[currentSortColumn === 'status' ? 'status' : `last_${currentSortColumn}_bps`] || 0;
    return currentSortOrder === 'asc' ? (valA > valB ? 1 : -1) : (valA < valB ? 1 : -1);
  });

  tbody.innerHTML = filtered.map(p => `
    <tr class="port-row ${selectedIfIndex === p.if_index ? 'selected' : ''}" data-if="${p.if_index}" data-name="${esc(p.name)}">
      <td style="text-align: left; padding-left: 20px;"><strong>${esc(p.name)}</strong>${p.alias ? `<br><small style="color: #748094;">${esc(p.alias)}</small>` : ''}</td>
      <td>${portStatusBadge(p)}<br><small style="color:#94a3b8;">${formatBps(p.speed_bps)}</small></td>
      <td class="num">${formatBps(p.last_in_bps)}</td><td class="num">${formatBps(p.last_out_bps)}</td>
      <td class="num muted">${formatBps(p.last_in_avg_bps)}</td><td class="num muted" style="padding-right:20px;">${formatBps(p.last_out_avg_bps)}</td>
    </tr>`).join('');

  tbody.querySelectorAll('.port-row').forEach(row => {
    row.addEventListener('click', () => {
      selectedIfIndex = parseInt(row.dataset.if, 10);
      $('#mon-port-title').textContent = row.dataset.name;
      tbody.querySelectorAll('.port-row').forEach(r => r.classList.remove('selected'));
      row.classList.add('selected');
      loadPortTrafficChart(selectedIfIndex);
    });
  });
  updateSortIcons();
}

function updateSortIcons() {
  document.querySelectorAll('.ports-table th.sortable').forEach(th => {
    const col = th.dataset.sort;
    const iconEl = th.querySelector('.sort-icon');
    if (iconEl) {
      if (currentSortColumn === col) {
        iconEl.textContent = currentSortOrder === 'asc' ? '▲' : '▼';
        th.style.color = '#3b82f6';
      } else { iconEl.textContent = '↕'; th.style.color = ''; }
    }
  });
}

function renderCpuChart(metrics) {
  const ctx = document.getElementById('cpu-chart');
  if (!ctx || typeof Chart === 'undefined') return;
  const mins = getSelectedMinutes();
  const timelineData = fillTimelineGaps(metrics, mins, ['cpu_percent', 'memory_percent']);

  if (cpuChart) cpuChart.destroy();
  cpuChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: timelineData.map(b => b.label),
      datasets: [
        { label: 'CPU %', data: timelineData.map(b => b.cpu_percent), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.15)', fill: true, tension: 0.1, spanGaps: true },
        { label: 'Memory %', data: timelineData.map(b => b.memory_percent), borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.1, spanGaps: true }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#9aa3b2' } } },
      scales: {
        x: { ticks: { color: '#6b7280', maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,0.06)' } },
        y: { min: 0, max: 100, ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.06)' } }
      }
    }
  });
}

async function loadPortTrafficChart(ifIndex) {
  const mins = getSelectedMinutes();
  const history = await api(`/api/v1/devices/${monitorDeviceId}/monitor/ports/${ifIndex}/traffic?minutes=${mins}`);
  cachedTrafficSamples = history.samples || [];
  const ctx = document.getElementById('traffic-chart');
  if (!ctx) return;
  const timelineData = fillTimelineGaps(cachedTrafficSamples, mins, ['in_bps', 'out_bps', 'in_avg_bps', 'out_avg_bps']);

  if (trafficChart) trafficChart.destroy();
  trafficChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: timelineData.map(b => b.label),
      datasets: [
        { label: 'Inbound', data: timelineData.map(b => b.in_bps), borderColor: '#60a5fa', backgroundColor: 'rgba(96,165,250,0.1----)', fill: true, tension: 0.1, spanGaps: true },
        { label: 'Outbound', data: timelineData.map(b => b.out_bps), borderColor: '#f472b6', backgroundColor: 'rgba(244,114,182,0.08)', fill: true, tension: 0.1, spanGaps: true },
        { label: 'In (avg)', data: timelineData.map(b => b.in_avg_bps), borderColor: '#94a3b8', borderDash: [4, 4], pointRadius: 0, tension: 0.1, spanGaps: true },
        { label: 'Out (avg)', data: timelineData.map(b => b.out_avg_bps), borderColor: '#64748b', borderDash: [4, 4], pointRadius: 0, tension: 0.1, spanGaps: true }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#9aa3b2' } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatBps(ctx.parsed.y)}` } }
      },
      scales: {
        x: { ticks: { color: '#6b7280', maxTicksLimit: 10 }, grid: { color: 'rgba(255,255,255,0.06)' } },
        y: { ticks: { color: '#6b7280', callback: (v) => formatBps(v) }, grid: { color: 'rgba(255,255,255,0.06)' } }
      }
    }
  });
}

function openZoomChartModal(chartType) {
  const modal = $('#zoom-chart-modal');
  const canvas = document.getElementById('expanded-interactive-canvas');
  if (!modal || !canvas) return;

  modal.classList.remove('hidden');
  if (expandedChart) { expandedChart.destroy(); expandedChart = null; }

  // [UI 편의성 보정] 모달이 열리자마자 캔버스에 마우스 grab 커서 적용
  canvas.style.cursor = 'grab';

  const mins = getSelectedMinutes();
  let chartDataSets = [];
  let chartLabels = [];
  let yOptions = {};

  if (chartType === 'cpu') {
    $('#zoom-modal-title').textContent = "CORE SYSTEM METRIC EXTENSION (CPU / MEMORY)";
    const timeline = fillTimelineGaps(cachedRecentMetrics, mins, ['cpu_percent', 'memory_percent']);
    chartLabels = timeline.map(b => b.label);
    chartDataSets = [
      { label: 'CPU Resource (%)', data: timeline.map(b => b.cpu_percent), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.12)', fill: true, tension: 0.05, pointRadius: 1.5, spanGaps: true },
      { label: 'Memory Allocation (%)', data: timeline.map(b => b.memory_percent), borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.08)', fill: true, tension: 0.05, pointRadius: 1.5, spanGaps: true }
    ];
    yOptions = { min: 0, max: 100, ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } };
  } else {
    const portName = $('#mon-port-title').textContent || 'Interface';
    $('#zoom-modal-title').textContent = `INTERFACE TELEMETRY REALTIME METRIC (${portName})`;
    const timeline = fillTimelineGaps(cachedTrafficSamples, mins, ['in_bps', 'out_bps', 'in_avg_bps', 'out_avg_bps']);
    chartLabels = timeline.map(b => b.label);
    chartDataSets = [
      { label: 'Inbound Stream', data: timeline.map(b => b.in_bps), borderColor: '#60a5fa', backgroundColor: 'rgba(96,165,250,0.1)', fill: true, tension: 0.05, spanGaps: true },
      { label: 'Outbound Stream', data: timeline.map(b => b.out_bps), borderColor: '#f472b6', backgroundColor: 'rgba(244,114,182,0.08)', fill: true, tension: 0.05, spanGaps: true },
      { label: 'In Bound (Avg)', data: timeline.map(b => b.in_avg_bps), borderColor: '#94a3b8', borderDash: [4, 4], pointRadius: 0, tension: 0.05, spanGaps: true },
      { label: 'Out Bound (Avg)', data: timeline.map(b => b.out_avg_bps), borderColor: '#64748b', borderDash: [4, 4], pointRadius: 0, tension: 0.05, spanGaps: true }
    ];
    yOptions = { ticks: { color: '#94a3b8', callback: (v) => formatBps(v) }, grid: { color: 'rgba(255,255,255,0.05)' } };
  }

  expandedChart = new Chart(canvas, {
    type: 'line',
    data: { labels: chartLabels, datasets: chartDataSets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#cbd5e1', font: { size: 12 } } },
        tooltip: { callbacks: { label: (ctx) => `Value: ${chartType === 'cpu' ? ctx.parsed.y.toFixed(1) + ' %' : formatBps(ctx.parsed.y)}` } },
        // [핵심 교정 패치] 마우스 드래그 및 스크롤을 이용한 타임라인 무브먼트 연동 파트
        zoom: {
          pan: {
            enabled: true,
            mode: 'x',
            threshold: 0, // 미세한 드래그 마우스 조작에도 유연하게 무브먼트가 즉각 반응하도록 보정
            onPanStart: function({chart}) {
              chart.canvas.style.cursor = 'grabbing'; // 클릭하여 드래그 중일 때 움켜쥐는 손 모양으로 실시간 변경
            },
            onPanComplete: function({chart}) {
              chart.canvas.style.cursor = 'grab'; // 마우스를 떼면 원래 grab 모양으로 원복
            }
          },
          zoom: {
            wheel: { enabled: true, speed: 0.05 },
            pinch: { enabled: true },
            mode: 'x'
          }
        }
      },
      scales: {
        x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: 'rgba(255,255,255,0.03)' } },
        y: yOptions
      }
    }
  });
}

function closeZoomChartModal() {
  if (expandedChart) { expandedChart.destroy(); expandedChart = null; }
  $('#zoom-chart-modal')?.classList.add('hidden');
}

async function monitorDiscover() {
  if (!monitorDeviceId) return;
  try {
    const r = await api(`/api/v1/devices/${monitorDeviceId}/monitor/discover`, { method: 'POST' });
    alert(`포트 ${r.ports_discovered}개 탐색 완료`); await refreshMonitor();
  } catch (e) { alert(e.message); }
}

async function monitorPollNow() {
  if (!monitorDeviceId) return;
  try {
    await api(`/api/v1/devices/${monitorDeviceId}/monitor/poll`, { method: 'POST' }); await refreshMonitor();
  } catch (e) { alert(e.message); }
}

function initMonitor() {
  $('#mon-back-btn')?.addEventListener('click', closeDeviceMonitor);
  $('#mon-discover-btn')?.addEventListener('click', monitorDiscover);
  $('#mon-poll-btn')?.addEventListener('click', monitorPollNow);
  $('#port-search-input')?.addEventListener('input', () => displayPortsTable());

  $('#monitor-time-select')?.addEventListener('change', () => {
    if ($('#cpu-chart-hint')) $('#cpu-chart-hint').textContent = $('#monitor-time-select').options[$('#monitor-time-select').selectedIndex].text + " (클릭 시 세부 격자 분석 패널 확장)";
    refreshMonitor();
  });

  document.getElementById('cpu-chart')?.parentElement.parentElement.addEventListener('click', () => openZoomChartModal('cpu'));
  document.getElementById('traffic-chart')?.parentElement.parentElement.addEventListener('click', () => {
    if (selectedIfIndex == null) { alert("상세 분석을 진행할 포트를 아래 인터페이스 테이블에서 먼저 마우스로 클릭해 주세요!"); return; }
    openZoomChartModal('traffic');
  });

  $('#zoom-modal-close-x')?.addEventListener('click', closeZoomChartModal);
  $('#zoom-modal-backdrop')?.addEventListener('click', closeZoomChartModal);
  $('#zoom-reset-axis-btn')?.addEventListener('click', () => { if (expandedChart) expandedChart.resetZoom(); });

  // 상단 제어 바 컴포넌트 버튼 클릭 연동
  $('#btn-nav-zoom-in')?.addEventListener('click', () => { if (expandedChart) expandedChart.zoom(1.15); });
  $('#btn-nav-zoom-out')?.addEventListener('click', () => { if (expandedChart) expandedChart.zoom(0.85); });
  $('#btn-nav-left')?.addEventListener('click', () => { if (expandedChart) expandedChart.pan({x: 80}); });
  $('#btn-nav-right')?.addEventListener('click', () => { if (expandedChart) expandedChart.pan({x: -80}); });

  document.querySelectorAll('.ports-table th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      currentSortOrder = (currentSortColumn === col && currentSortOrder === 'asc') ? 'desc' : 'asc';
      currentSortColumn = col; displayPortsTable();
    });
  });
}

document.addEventListener('DOMContentLoaded', initMonitor);