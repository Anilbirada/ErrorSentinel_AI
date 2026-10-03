// RSR ErrorSentinel AI — Dashboard Frontend Application

let errorFilter = 'all';
let rawErrorsList = [];
let eventSource = null;

document.addEventListener('DOMContentLoaded', () => {
    initClock();
    refreshAllData();
    initSSE();
    setInterval(refreshAllData, 15000); // 15s polling fallback
});

function initClock() {
    function updateClock() {
        const now = new Date();
        const clockEl = document.getElementById('live-clock');
        if (clockEl) {
            clockEl.textContent = now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
        }
    }
    updateClock();
    setInterval(updateClock, 1000);
}

function initSSE() {
    try {
        eventSource = new EventSource('/api/events');
        eventSource.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                handleLiveEvent(data);
            } catch (err) {
                console.error('SSE parse error:', err);
            }
        };
        eventSource.onerror = () => {
            console.warn('SSE connection closed. Will retry automatically.');
        };
    } catch (e) {
        console.warn('SSE not supported or failed to connect:', e);
    }
}

function handleLiveEvent(data) {
    if (data.event === 'job_created') {
        appendLog(`[JOB] Started: ${data.job.job_type} (ID: ${data.job.job_id})`, 'info');
        setAgentRunning(true);
    } else if (data.event === 'job_updated') {
        const cls = data.status === 'SUCCESS' ? 'success' : data.status === 'FAILED' ? 'error' : 'info';
        appendLog(`[JOB] ${data.job_id} -> ${data.status} ${data.error ? '(' + data.error + ')' : ''}`, cls);
        if (data.status === 'SUCCESS' || data.status === 'FAILED') {
            refreshAllData();
        }
    }
}

function appendLog(msg, type = 'info') {
    const stream = document.getElementById('log-stream');
    if (!stream) return;
    const div = document.createElement('div');
    div.className = `log-line ${type}`;
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    stream.appendChild(div);
    stream.scrollTop = stream.scrollHeight;
}

function setAgentRunning(isRunning) {
    const pulse = document.getElementById('agent-pulse');
    const stateText = document.getElementById('agent-state-text');
    const badge = document.getElementById('live-badge');
    const detailStatus = document.getElementById('agent-detail-status');
    const btn = document.getElementById('btn-run-now');

    if (isRunning) {
        if (pulse) pulse.className = 'pulse-dot running';
        if (stateText) stateText.textContent = 'Agent Scanning...';
        if (badge) { badge.className = 'badge badge-warning'; badge.textContent = 'Active Scan'; }
        if (detailStatus) detailStatus.textContent = 'RUNNING';
        if (btn) { btn.disabled = true; btn.innerHTML = '⏳ Scanning...'; }
    } else {
        if (pulse) pulse.className = 'pulse-dot idle';
        if (stateText) stateText.textContent = 'Agent Idle';
        if (badge) { badge.className = 'badge badge-success'; badge.textContent = 'Standby'; }
        if (detailStatus) detailStatus.textContent = 'IDLE';
        if (btn) { btn.disabled = false; btn.innerHTML = '<span id="btn-icon">⚡</span> Run Monitoring Now'; }
    }
}

async function triggerRunNow() {
    try {
        setAgentRunning(true);
        appendLog('[SYS] User triggered manual run-now.', 'warn');
        const res = await fetch('/api/run-now', { method: 'POST' });
        const data = await res.json();
        if (res.status === 202) {
            appendLog(`[SYS] Run accepted by worker pool. Job ID: ${data.job_id}`, 'success');
        } else if (data.status === 'already_running') {
            appendLog('[SYS] A monitoring cycle is already active.', 'warn');
        } else {
            appendLog(`[SYS] Trigger response: ${JSON.stringify(data)}`, 'info');
        }
    } catch (e) {
        appendLog(`[SYS] Failed to trigger run: ${e.message}`, 'error');
        setAgentRunning(false);
    }
}

async function refreshAllData() {
    await Promise.all([
        fetchStats(),
        fetchStatus(),
        fetchConfig(),
        fetchRuns(),
        fetchErrors(),
        fetchMetrics()
    ]);
}

async function fetchStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('stat-emails').textContent = data.emails_processed || 0;
        document.getElementById('stat-new-codes').textContent = data.new_codes || 0;
        document.getElementById('stat-registered').textContent = data.new_codes || 0;
        document.getElementById('stat-alerts').textContent = data.alerts_sent || 0;
    } catch (e) {
        console.error('Failed fetching stats:', e);
    }
}

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        const isRunning = data.monitoring === 'RUNNING';
        setAgentRunning(isRunning);

        if (data.last_run) {
            document.getElementById('last-run-id').textContent = data.last_run.id;
            document.getElementById('last-run-time').textContent = data.last_run.completed_at
                ? new Date(data.last_run.completed_at).toLocaleString()
                : 'In Progress';
        }
        if (data.provider) {
            document.getElementById('provider-badge-text').textContent = `Provider: ${data.provider.toUpperCase()}`;
            document.getElementById('cfg-provider').textContent = `${data.provider.toUpperCase()} Provider`;
        }
    } catch (e) {
        console.error('Failed fetching status:', e);
    }
}

async function fetchConfig() {
    try {
        const res = await fetch('/api/config/status');
        const data = await res.json();
        if (data.llm_provider) {
            document.getElementById('cfg-ai').textContent = `${data.llm_provider.toUpperCase()} (${data.llm_model || 'default'})`;
        }
        if (data.monitor_interval_minutes) {
            document.getElementById('next-run-time').textContent = `Every ${data.monitor_interval_minutes} minutes`;
        }
    } catch (e) {
        console.error('Failed fetching config:', e);
    }
}

async function fetchRuns() {
    try {
        const res = await fetch('/api/runs?limit=15');
        const runs = await res.json();
        const tbody = document.getElementById('runs-tbody');
        if (!tbody) return;

        if (!runs || runs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center">No execution runs recorded yet.</td></tr>';
            return;
        }

        tbody.innerHTML = runs.map(r => {
            const statusClass = r.status === 'SUCCESS' ? 'badge-success' : r.status === 'FAILED' ? 'badge-danger' : 'badge-warning';
            const notifClass = r.notification_status === 'SENT' ? 'badge-success' : r.notification_status === 'FAILED' ? 'badge-danger' : 'badge-blue';
            const regClass = r.registry_status === 'COMMITTED' ? 'badge-success' : 'badge-warning';

            return `
                <tr>
                    <td><strong class="code-badge">${escapeHtml(r.id)}</strong></td>
                    <td><span class="badge ${statusClass}">${escapeHtml(r.status)}</span></td>
                    <td>${r.emails_scanned || 0}</td>
                    <td>${r.emails_processed || 0}</td>
                    <td>${r.attachments_processed || 0}</td>
                    <td><strong style="color: ${r.new_codes > 0 ? '#f87171' : '#34d399'}">${r.new_codes || 0}</strong></td>
                    <td><span class="badge ${notifClass}">${escapeHtml(r.notification_status || 'N/A')}</span></td>
                    <td><span class="badge ${regClass}">${escapeHtml(r.registry_status || 'N/A')}</span></td>
                    <td>${r.duration_ms ? (r.duration_ms / 1000).toFixed(2) + 's' : '--'}</td>
                    <td style="font-size:12px; color:#9ca3af;">${r.started_at ? new Date(r.started_at).toLocaleTimeString() : '--'}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('Failed fetching runs:', e);
    }
}

async function fetchErrors() {
    try {
        const res = await fetch('/api/errors?limit=300');
        rawErrorsList = await res.json();
        renderErrorsTable();
    } catch (e) {
        console.error('Failed fetching errors:', e);
    }
}

function filterErrors(filter) {
    errorFilter = filter;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    renderErrorsTable();
}

function renderErrorsTable() {
    const tbody = document.getElementById('errors-tbody');
    if (!tbody) return;

    const searchTerm = (document.getElementById('error-search')?.value || '').toLowerCase();

    const filtered = rawErrorsList.filter(item => {
        if (errorFilter === 'new' && item.in_registry) return false;
        if (errorFilter === 'existing' && !item.in_registry) return false;
        if (searchTerm) {
            const matchesCode = (item.code || '').toLowerCase().includes(searchTerm);
            const matchesMsg = (item.message || '').toLowerCase().includes(searchTerm);
            return matchesCode || matchesMsg;
        }
        return true;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">No error signatures match the current filter.</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(item => {
        const isNew = !item.in_registry;
        const statusBadge = isNew
            ? '<span class="badge badge-danger">NEW CODE</span>'
            : '<span class="badge badge-success">EXISTING</span>';

        const sevClass = item.severity === 'CRITICAL' ? 'badge-danger' : item.severity === 'HIGH' ? 'badge-warning' : 'badge-blue';

        return `
            <tr>
                <td><strong class="code-badge" style="font-size:13px;">${escapeHtml(item.code || item.raw_code)}</strong></td>
                <td>${statusBadge}</td>
                <td><span class="badge ${sevClass}">${escapeHtml(item.severity || 'MEDIUM')}</span></td>
                <td style="text-align:center;"><strong>${item.occurrence_count || 1}</strong></td>
                <td>${escapeHtml(item.message || item.raw_code)}</td>
                <td><div style="max-width:260px; font-family:var(--font-mono); font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#9ca3af;" title="${escapeHtml(item.context || '')}">${escapeHtml(item.context || 'N/A')}</div></td>
                <td style="font-size:12px;">${escapeHtml(item.source || item.source_email || 'Email')}</td>
                <td style="font-size:11px; color:#9ca3af;">${item.created_at ? new Date(item.created_at).toLocaleDateString() : '--'}</td>
            </tr>
        `;
    }).join('');
}

async function fetchMetrics() {
    try {
        const res = await fetch('/api/metrics');
        const data = await res.json();
        document.getElementById('metric-avg-dur').textContent = `${data.average_run_duration_ms || 0} ms`;
        document.getElementById('metric-tot-scanned').textContent = data.total_emails_scanned || 0;
        document.getElementById('metric-tot-att').textContent = data.total_attachments_processed || 0;
        document.getElementById('metric-reg-count').textContent = data.registered_unique_codes || 0;
    } catch (e) {
        console.error('Failed fetching metrics:', e);
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
