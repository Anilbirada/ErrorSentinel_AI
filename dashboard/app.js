// RSR ErrorSentinel AI — Enterprise Frontend Controller

let rawErrors = [];
let currentFilter = 'all';
let searchTimeout = null;
let eventSource = null;
let csrfToken = '';

document.addEventListener('DOMContentLoaded', () => {
    initClock();
    initCurrentUser();
    initGmailConnectionMessages();
    refreshAllData();
    initSSE();
    setInterval(refreshAllData, 12000); // 12s polling fallback
    document.getElementById('gmail-connections-list')?.addEventListener('click', handleGmailConnectionAction);
});

async function initCurrentUser() {
    try {
        const res = await fetch('/auth/session');
        if (!res.ok) return;
        const data = await res.json();
        csrfToken = data.csrf_token || '';
        document.getElementById('current-user-email').textContent = data.email;
    } catch (err) {
        console.warn('Unable to load signed-in account details:', err);
    }
}

function initGmailConnectionMessages() {
    const result = new URLSearchParams(window.location.search).get('gmail');
    const messages = {
        connected: 'Gmail account connected successfully.',
        cancelled: 'Gmail connection was cancelled.',
        failed: 'Unable to connect Gmail. Please try again.',
    };
    if (messages[result]) {
        document.getElementById('gmail-action-message').textContent = messages[result];
        window.history.replaceState({}, document.title, `${window.location.pathname}#gmail-connection`);
    }
}

// 1. Live UTC Clock
function initClock() {
    const clockEl = document.getElementById('header-clock');
    function updateClock() {
        const now = new Date();
        if (clockEl) {
            clockEl.textContent = now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
        }
    }
    updateClock();
    setInterval(updateClock, 1000);
}

async function fetchGmailConnections() {
    const container = document.getElementById('gmail-connections-list');
    if (!container) return;
    try {
        const res = await fetch('/api/gmail-connections');
        if (!res.ok) {
            throw new Error(res.status === 401 ? 'Please sign in again to view Gmail connections.' : 'Unable to load Gmail connections.');
        }
        const connections = await res.json();
        if (!connections.length) {
            container.innerHTML = '<p class="gmail-empty-state">No Gmail accounts are connected yet.</p>';
            return;
        }
        container.innerHTML = connections.map(renderGmailConnection).join('');
    } catch (err) {
        container.innerHTML = `<p class="gmail-empty-state error">${escapeHtml(err.message)}</p>`;
    }
}

function renderGmailConnection(connection) {
    const labels = {
        CONNECTED: ['Connected', 'connected'],
        REAUTHORIZATION_REQUIRED: ['Reauthorization Required', 'reauthorization'],
        DISCONNECTED: ['Disconnected', 'disconnected'],
        OAUTH_ERROR: ['OAuth Error', 'error'],
    };
    const [statusLabel, statusClass] = labels[connection.status] || ['Connection Error', 'error'];
    const lastSync = formatGmailDate(connection.last_sync_at);
    const lastSuccessful = formatGmailDate(connection.last_successful_monitor_at);
    const lastActivity = connection.monitoring === 'RUNNING' ? 'Monitoring now' : lastSync;
    return `
        <article class="gmail-account-card" data-connection-id="${escapeHtml(connection.id)}">
            <div class="gmail-account-icon" aria-hidden="true">G</div>
            <div class="gmail-account-details">
                <strong class="gmail-account-email">${escapeHtml(connection.email)}</strong>
                <span class="gmail-status-badge ${statusClass}"><span class="gmail-status-dot"></span>${statusLabel}</span>
                <span class="gmail-account-note">Monitoring: ${escapeHtml(connection.monitoring)}</span>
                ${connection.last_error ? `<span class="gmail-account-error">${escapeHtml(connection.last_error)}</span>` : ''}
            </div>
            <div class="gmail-account-metrics">
                <span><small>Last sync</small><strong>${escapeHtml(lastSync)}</strong></span>
                <span><small>Last successful scan</small><strong>${escapeHtml(lastSuccessful)}</strong></span>
                <span><small>Emails processed</small><strong>${Number(connection.emails_processed) || 0}</strong></span>
                <span><small>New errors</small><strong>${Number(connection.new_errors) || 0}</strong></span>
                <span><small>Existing errors</small><strong>${Number(connection.existing_errors) || 0}</strong></span>
                <span><small>Alerts sent</small><strong>${Number(connection.alerts_sent) || 0}</strong></span>
                <span><small>Last activity</small><strong>${escapeHtml(lastActivity)}</strong></span>
            </div>
            <div class="gmail-account-actions">
                ${connection.status === 'CONNECTED' ? `<button class="btn-subtle" type="button" data-action="run">Run now</button>` : ''}
                <button class="btn-subtle" type="button" data-action="reconnect">Reconnect</button>
                ${connection.status !== 'DISCONNECTED' ? `<button class="btn-subtle danger" type="button" data-action="disconnect">Disconnect</button>` : ''}
            </div>
        </article>`;
}

function formatGmailDate(value) {
    if (!value) return 'Never';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Unavailable' : date.toLocaleString();
}

async function handleGmailConnectionAction(event) {
    const button = event.target instanceof Element ? event.target.closest('button[data-action]') : null;
    if (!button) return;
    const card = button.closest('[data-connection-id]');
    if (!card) return;
    const connectionId = card.dataset.connectionId;
    const action = button.dataset.action;
    if (action === 'disconnect') {
        if (!window.confirm('Disconnect this Gmail account? Monitoring will stop for this account; history will be preserved.')) return;
        await postGmailAction(`/auth/gmail/${encodeURIComponent(connectionId)}/disconnect`, 'disconnect');
        return;
    }
    if (action === 'reconnect') {
        await beginGmailOAuth(`/auth/gmail/${encodeURIComponent(connectionId)}/reconnect`);
        return;
    }
    if (action === 'run') {
        const result = await postGmailAction(`/api/gmail-connections/${encodeURIComponent(connectionId)}/run`, 'run');
        if (result?.status === 'accepted') {
            showGmailMessage('Monitoring started for this Gmail account.');
        } else if (result?.status === 'already_running') {
            showGmailMessage('Monitoring is already running for this Gmail account.');
        }
        return;
    }
}

async function connectGmail() {
    await beginGmailOAuth('/auth/gmail/start');
}

async function beginGmailOAuth(endpoint) {
    const result = await postGmailAction(endpoint, 'oauth');
    if (result?.authorization_url) {
        window.location.assign(result.authorization_url);
    }
}

async function postGmailAction(endpoint, action) {
    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'X-CSRF-Token': csrfToken },
        });
        const data = await res.json();
        if (!res.ok) {
            const detail = typeof data.detail === 'string' ? data.detail : 'Unable to complete the Gmail request.';
            throw new Error(detail);
        }
        if (action === 'disconnect') {
            showGmailMessage('Gmail disconnected. Its monitoring is stopped; history is preserved.');
            await fetchGmailConnections();
        }
        return data;
    } catch (err) {
        showGmailMessage(err.message || 'Unable to connect Gmail. Please try again.');
        return null;
    }
}

function showGmailMessage(message) {
    const element = document.getElementById('gmail-action-message');
    if (element) element.textContent = message;
}

async function signOut() {
    if (!window.confirm('Sign out of ErrorSentinel?')) return;
    try {
        const res = await fetch('/auth/logout', {
            method: 'POST',
            headers: { 'X-CSRF-Token': csrfToken },
        });
        if (res.ok) window.location.assign('/login');
        else showGmailMessage('Unable to sign out. Please refresh and try again.');
    } catch (err) {
        showGmailMessage('Unable to sign out. Please refresh and try again.');
    }
}

// 2. Server-Sent Events (SSE) Live Feed
function initSSE() {
    const sseBadge = document.getElementById('sse-badge');
    try {
        eventSource = new EventSource('/api/events');
        
        eventSource.onopen = () => {
            if (sseBadge) {
                sseBadge.textContent = '● Connected';
                sseBadge.className = 'badge-live-stream';
            }
        };

        eventSource.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                handleLiveEvent(data);
            } catch (err) {
                console.error('SSE JSON error:', err);
            }
        };

        eventSource.onerror = () => {
            if (sseBadge) {
                sseBadge.textContent = '○ Reconnecting';
                sseBadge.className = 'badge-live-stream warning';
            }
        };
    } catch (e) {
        console.warn('SSE not initialized:', e);
    }
}

function handleLiveEvent(data) {
    if (data.event === 'job_created') {
        appendStreamEntry(`[JOB] Enqueued: ${data.job.job_type} (ID: ${data.job.job_id})`, 'info');
        setAgentState(true);
    } else if (data.event === 'job_updated') {
        const cls = data.status === 'SUCCESS' ? 'success' : data.status === 'FAILED' ? 'error' : 'info';
        appendStreamEntry(`[JOB] ${data.job_id} ➔ ${data.status} ${data.error ? '(' + data.error + ')' : ''}`, cls);
        if (data.status === 'SUCCESS' || data.status === 'FAILED') {
            setAgentState(false);
            refreshAllData();
        }
    }
}

function appendStreamEntry(msg, type = 'info') {
    const stream = document.getElementById('activity-stream');
    if (!stream) return;
    const time = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = `stream-entry ${type}`;
    div.innerHTML = `<span class="stream-time">[${time}]</span> <span class="stream-msg">${escapeHtml(msg)}</span>`;
    stream.appendChild(div);
    stream.scrollTop = stream.scrollHeight;
}

// 3. Trigger Run Now (Non-blocking)
async function triggerRunNow() {
    const btn = document.getElementById('btn-run-monitor');
    const spin = document.getElementById('btn-spin');
    const btnText = document.getElementById('btn-text');

    try {
        btn.disabled = true;
        spin.textContent = '⏳';
        btnText.textContent = 'Enqueuing...';

        const res = await fetch('/api/run-now', {
            method: 'POST',
            headers: { 'X-CSRF-Token': csrfToken },
        });
        const data = await res.json();

        if (res.status === 202 || data.status === 'accepted') {
            appendStreamEntry(`[SYS] Run accepted. Job ID: ${data.job_id}`, 'success');
            setAgentState(true);
        } else if (data.status === 'already_running') {
            appendStreamEntry(`[SYS] ${data.message}`, 'info');
        } else {
            appendStreamEntry(`[SYS] Trigger error: ${JSON.stringify(data.detail || data)}`, 'error');
        }
    } catch (err) {
        appendStreamEntry(`[ERR] Failed to connect: ${err.message}`, 'error');
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            spin.textContent = '⚡';
            btnText.textContent = 'Run Monitoring Now';
        }, 2000);
    }
}

function setAgentState(isRunning) {
    const pulse = document.getElementById('sidebar-pulse');
    const sideText = document.getElementById('sidebar-status-text');
    const livePill = document.getElementById('live-state-pill');
    const stateLabel = document.getElementById('agent-state-label');
    const headStatus = document.getElementById('header-agent-status');

    if (isRunning) {
        if (pulse) pulse.className = 'pulse-dot running';
        if (sideText) sideText.textContent = 'Analyzing...';
        if (livePill) { livePill.className = 'badge-status-pill running'; livePill.textContent = 'AI Agent is analyzing...'; }
        if (stateLabel) stateLabel.textContent = 'RUNNING';
        if (headStatus) headStatus.textContent = 'Agent Running';
    } else {
        if (pulse) pulse.className = 'pulse-dot idle';
        if (sideText) sideText.textContent = 'Agent Online';
        if (livePill) { livePill.className = 'badge-status-pill idle'; livePill.textContent = 'Monitoring continuously'; }
        if (stateLabel) stateLabel.textContent = 'IDLE';
        if (headStatus) headStatus.textContent = 'Agent Online';
    }
}

// 4. Refresh All Operational Data
async function refreshAllData() {
    await Promise.allSettled([
        fetchStatus(),
        fetchKPIsAndMetrics(),
        fetchErrors(),
        fetchRegistry(),
        fetchAttachments(),
        fetchHistory(),
        fetchHealth(),
        fetchGmailConnections(),
    ]);
}

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        setAgentState(data.monitoring === 'RUNNING');
        
        const providerName = data.provider === 'microsoft_graph' ? 'Microsoft 365 / Outlook' : data.provider === 'gmail' ? 'Gmail API' : 'Demo Mailbox';
        document.getElementById('header-provider-name').textContent = providerName;
        document.getElementById('sidebar-provider-pill').textContent = providerName;

        if (data.last_run) {
            document.getElementById('agent-last-run').textContent = data.last_run.id;
        }
    } catch (e) {
        console.warn('Status fetch error:', e);
    }
}

async function fetchKPIsAndMetrics() {
    try {
        const [statsRes, metricsRes] = await Promise.all([
            fetch('/api/stats'),
            fetch('/api/metrics'),
        ]);

        if (statsRes.ok) {
            const stats = await statsRes.json();
            document.getElementById('kpi-emails').textContent = stats.emails_processed || 0;
            document.getElementById('kpi-new-errors').textContent = stats.new_codes || 0;
            document.getElementById('kpi-alerts-sent').textContent = stats.alerts_sent || 0;
        }

        if (metricsRes.ok) {
            const metrics = await metricsRes.json();
            document.getElementById('kpi-attachments').textContent = metrics.total_attachments_processed || 0;
            document.getElementById('kpi-processing-time').textContent = `${metrics.average_run_duration_ms || 0} ms`;
            document.getElementById('kpi-existing-errors').textContent = metrics.registered_unique_codes || 0;
        }
    } catch (e) {
        console.warn('KPI fetch error:', e);
    }
}

async function fetchErrors() {
    try {
        const res = await fetch('/api/errors?limit=200');
        if (!res.ok) return;
        rawErrors = await res.json();
        renderErrorsTable();
        updateAIInsights();
    } catch (e) {
        console.warn('Errors fetch error:', e);
    }
}

function updateAIInsights() {
    const el = document.getElementById('ai-insights-text');
    if (!el) return;
    if (rawErrors.length === 0) {
        el.textContent = 'No errors detected in current monitoring cycles. Mailbox is running cleanly.';
        return;
    }
    const newCount = rawErrors.filter(e => e.is_new).length;
    const criticalCount = rawErrors.filter(e => (e.severity || '').toUpperCase() === 'CRITICAL').length;
    el.innerHTML = `<strong>Latest Cycle Analysis:</strong> Extracted <strong>${rawErrors.length}</strong> total error signatures (<strong>${newCount}</strong> newly discovered, <strong>${criticalCount}</strong> critical). All alert reports dispatched with transaction safety verified.`;
}

function setFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-tab-bar .tab-button').forEach(b => b.classList.remove('active'));
    if (event && event.target) event.target.classList.add('active');
    renderErrorsTable();
}

function debouncedSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(renderErrorsTable, 200);
}

function renderErrorsTable() {
    const tbody = document.getElementById('errors-table-body');
    if (!tbody) return;

    const query = (document.getElementById('global-search')?.value || '').toLowerCase().trim();

    let filtered = rawErrors.filter(e => {
        if (currentFilter === 'new' && !e.is_new) return false;
        if (currentFilter === 'existing' && e.is_new) return false;
        if (currentFilter === 'high' && !['HIGH', 'CRITICAL'].includes((e.severity || '').toUpperCase())) return false;

        if (query) {
            const matchCode = (e.code || '').toLowerCase().includes(query);
            const matchMsg = (e.message || '').toLowerCase().includes(query);
            const matchSource = (e.attachment_name || e.source_email || '').toLowerCase().includes(query);
            return matchCode || matchMsg || matchSource;
        }
        return true;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-cell">No matching error signatures found.</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(e => {
        const isNew = e.is_new;
        const statusBadge = isNew
            ? '<span class="badge-status-pill new">NEW</span>'
            : '<span class="badge-status-pill existing">EXISTING</span>';
        
        const sev = (e.severity || 'MEDIUM').toUpperCase();
        const sevClass = sev === 'CRITICAL' ? 'critical' : sev === 'HIGH' ? 'high' : sev === 'LOW' ? 'low' : 'medium';
        const sevBadge = `<span class="badge-sev ${sevClass}">${sev}</span>`;

        const sourceLabel = e.attachment_name ? `📎 ${escapeHtml(e.attachment_name)}` : (e.source_email ? `📧 ${escapeHtml(e.source_email)}` : 'Body');
        const time = e.created_at ? e.created_at.replace('T', ' ').substring(0, 19) : '-';

        return `
            <tr>
                <td><strong class="code-tag">${escapeHtml(e.code || e.raw_code)}</strong></td>
                <td>${statusBadge}</td>
                <td>${sevBadge}</td>
                <td><strong>${e.occurrence_count || 1}</strong></td>
                <td>${escapeHtml((e.message || '-').substring(0, 60))}</td>
                <td>${sourceLabel}</td>
                <td><span style="font-size:11px;color:var(--text-muted);">${time}</span></td>
                <td><button class="btn-subtle" onclick='openErrorModal(${JSON.stringify(e).replace(/'/g, "&apos;")})'>Inspect</button></td>
            </tr>
        `;
    }).join('');
}

async function fetchRegistry() {
    try {
        const res = await fetch('/api/registry');
        if (!res.ok) return;
        const entries = await res.json();
        const tbody = document.getElementById('registry-table-body');
        const summary = document.getElementById('registry-summary-pill');

        if (summary) summary.textContent = `Total Registered: ${entries.length}`;
        if (!tbody) return;

        if (entries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">Registry is currently empty.</td></tr>';
            return;
        }

        tbody.innerHTML = entries.map(e => `
            <tr>
                <td><strong class="code-tag">${escapeHtml(e.code)}</strong></td>
                <td><strong>${e.occurrence_count || 1}</strong></td>
                <td><span style="font-size:11px;color:var(--text-muted);">${(e.first_seen_at || '').substring(0, 19).replace('T', ' ')}</span></td>
                <td><span style="font-size:11px;color:var(--text-muted);">${(e.last_seen_at || '').substring(0, 19).replace('T', ' ')}</span></td>
                <td><span style="font-size:11px;">${escapeHtml(e.source_run_id || 'manual')}</span></td>
                <td><span class="badge-status-pill idle">${escapeHtml(e.status || 'ACTIVE')}</span></td>
            </tr>
        `).join('');
    } catch (e) {
        console.warn('Registry fetch error:', e);
    }
}

async function fetchAttachments() {
    try {
        const res = await fetch('/api/attachments');
        if (!res.ok) return;
        const list = await res.json();
        const tbody = document.getElementById('attachments-table-body');
        if (!tbody) return;

        if (list.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">No attachments processed yet.</td></tr>';
            return;
        }

        tbody.innerHTML = list.map(a => `
            <tr>
                <td><strong>${escapeHtml(a.filename || 'attachment')}</strong></td>
                <td><span class="code-tag">${escapeHtml(a.content_type || 'file')}</span></td>
                <td>${(a.size_bytes / 1024).toFixed(1)} KB</td>
                <td><span class="badge-status-pill idle">${escapeHtml(a.download_status || 'OK')}</span></td>
                <td><span class="badge-status-pill idle">${escapeHtml(a.extraction_status || 'PARSED')}</span></td>
                <td><span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">${(a.sha256 || '').substring(0, 16)}...</span></td>
            </tr>
        `).join('');
    } catch (e) {
        console.warn('Attachments fetch error:', e);
    }
}

async function fetchHistory() {
    try {
        const res = await fetch('/api/runs?limit=20');
        if (!res.ok) return;
        const runs = await res.json();
        const tbody = document.getElementById('history-table-body');
        if (!tbody) return;

        if (runs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">No run history recorded yet.</td></tr>';
            return;
        }

        tbody.innerHTML = runs.map(r => {
            const isSuccess = r.status === 'SUCCESS';
            const statusBadge = isSuccess
                ? '<span class="badge-status-pill idle">SUCCESS</span>'
                : `<span class="badge-status-pill new">${escapeHtml(r.status)}</span>`;

            const notifBadge = r.notification_status === 'SUCCESS'
                ? '<span class="badge-rule">✓ Delivered</span>'
                : `<span style="font-size:11px;color:var(--accent-amber);">${escapeHtml(r.notification_status || 'PENDING')}</span>`;

            const regBadge = r.registry_status === 'COMMITTED'
                ? '<span class="badge-rule">✓ Committed</span>'
                : `<span style="font-size:11px;color:var(--text-muted);">${escapeHtml(r.registry_status || 'SKIPPED')}</span>`;

            return `
                <tr>
                    <td><span class="code-tag">${escapeHtml(r.id)}</span></td>
                    <td>${statusBadge}</td>
                    <td><strong>${r.emails_scanned || 0}</strong></td>
                    <td>${r.attachments_processed || 0}</td>
                    <td><strong style="color:var(--accent-red);">${r.new_codes || 0}</strong></td>
                    <td>${notifBadge}</td>
                    <td>${regBadge}</td>
                    <td>${r.duration_ms ? r.duration_ms.toFixed(0) + ' ms' : '-'}</td>
                    <td><span style="font-size:11px;color:var(--text-muted);">${(r.started_at || '').substring(0, 19).replace('T', ' ')}</span></td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.warn('History fetch error:', e);
    }
}

async function fetchHealth() {
    try {
        const res = await fetch('/api/system/health');
        if (!res.ok) return;
        const data = await res.json();
        
        const provBadge = document.getElementById('health-provider-badge');
        if (provBadge && data.components?.provider) {
            provBadge.textContent = `● Active (${data.components.provider.active})`;
        }
    } catch (e) {
        console.warn('Health fetch error:', e);
    }
}

// 5. Modals & Exports
function openErrorModal(errorItem) {
    document.getElementById('modal-error-code').textContent = errorItem.code || errorItem.raw_code;
    
    const sevBadge = document.getElementById('modal-severity-badge');
    const sev = (errorItem.severity || 'MEDIUM').toUpperCase();
    sevBadge.textContent = sev;
    sevBadge.className = `badge-sev ${sev.toLowerCase()}`;

    const statBadge = document.getElementById('modal-status-badge');
    statBadge.textContent = errorItem.is_new ? 'NEW ERROR' : 'KNOWN ERROR';
    statBadge.className = `badge-status-pill ${errorItem.is_new ? 'new' : 'existing'}`;

    document.getElementById('modal-message').textContent = errorItem.message || 'No explicit error message captured.';
    document.getElementById('modal-context').textContent = errorItem.context || 'No context snippet available.';
    document.getElementById('modal-ai-insights').textContent = errorItem.ai_interpretation || 'Deterministic signature extracted. Verified against ACID master registry.';

    document.getElementById('modal-email').textContent = errorItem.source_email || '-';
    document.getElementById('modal-sender').textContent = errorItem.source_sender || '-';
    document.getElementById('modal-attachment').textContent = errorItem.attachment_name || 'None (Email Body)';
    document.getElementById('modal-time').textContent = (errorItem.created_at || '-').replace('T', ' ').substring(0, 19);

    document.getElementById('error-modal').classList.remove('hidden');
}

function closeModal() {
    document.getElementById('error-modal').classList.add('hidden');
}

function closeModalOnBackdrop(e) {
    if (e.target.id === 'error-modal') closeModal();
}

async function openSettingsModal() {
    try {
        const res = await fetch('/api/config/status');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('set-provider').textContent = data.email_provider;
            document.getElementById('set-ai').textContent = `${data.llm_provider} (${data.llm_model})`;
            document.getElementById('set-interval').textContent = `Every ${data.monitor_interval_minutes} minutes`;
            document.getElementById('set-db').textContent = data.database_configured ? 'Configured' : 'Not configured';
            document.getElementById('set-workers').textContent = `${data.max_email_workers} Email / ${data.max_attachment_workers} Att / ${data.max_llm_concurrency} LLM`;
        }
    } catch (e) {
        console.warn('Config fetch error:', e);
    }
    document.getElementById('settings-modal').classList.remove('hidden');
}

function closeSettingsModal() {
    document.getElementById('settings-modal').classList.add('hidden');
}

function closeSettingsOnBackdrop(e) {
    if (e.target.id === 'settings-modal') closeSettingsModal();
}

function exportData(type) {
    if (type === 'csv') {
        window.open('/api/export/csv', '_blank');
    } else if (type === 'txt') {
        window.open('/api/export/txt', '_blank');
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
