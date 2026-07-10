/**
 * frontend/script.js
 * ──────────────────
 * PURPOSE:
 *     Handles all user interactions, API fetching, sorting, filtering,
 *     countdown logic, modal visualization, failover badges, and
 *     backup config panel on the dashboard.
 */

// ── Global State ──────────────────────────────────────────────────────────────
let apisData = [];           // Combined list of { id, name, url, status, ... }
let failoverMap = {};        // api_id → { current_status, active_backup_id, backup_name }
let activeFilter = 'all';
let activeSort = 'name';
let searchQuery = '';
let countdownValue = 30;
let countdownInterval = null;

let token = localStorage.getItem('trustapi_token') || null;
let userEmail = localStorage.getItem('userEmail') || null;
let watchlist = [];
let authMode = 'login';
let watchlistOnlyActive = false;

// ── DOM Elements ──────────────────────────────────────────────────────────────
const cardsContainer    = document.getElementById('cards-container');
const searchInput       = document.getElementById('search-input');
const statusFilter      = document.getElementById('status-filter');
const sortSelect        = document.getElementById('sort-select');
const countdownTimer    = document.getElementById('countdown-timer');
const refreshBtn        = document.getElementById('refresh-btn');
const statTotal         = document.getElementById('stat-total');
const statUp            = document.getElementById('stat-up');
const statDown          = document.getElementById('stat-down');
const statReliability   = document.getElementById('stat-reliability');
const historyModal      = document.getElementById('history-modal');
const modalApiName      = document.getElementById('modal-api-name');
const modalApiUrl       = document.getElementById('modal-api-url');
const modalTotalChecks  = document.getElementById('modal-total-checks');
const modalUptimePct    = document.getElementById('modal-uptime-pct');
const modalAvgLatency   = document.getElementById('modal-avg-latency');
const historyTableBody  = document.getElementById('history-table-body');
const closeModalBtn     = document.getElementById('close-modal-btn');
const authModal         = document.getElementById('auth-modal');
const authTriggerBtn    = document.getElementById('auth-trigger-btn');
const closeAuthModalBtn = document.getElementById('close-auth-modal-btn');
const authForm          = document.getElementById('auth-form');
const authEmailInput    = document.getElementById('auth-email');
const authPasswordInput = document.getElementById('auth-password');
const authError         = document.getElementById('auth-error');
const authSubmitBtn     = document.getElementById('auth-submit-btn');
const authSubmitText    = document.getElementById('auth-submit-text');
const authSwitchLink    = document.getElementById('auth-switch-link');
const authModalTitle    = document.getElementById('auth-modal-title');
const authModalSubtitle = document.getElementById('auth-modal-subtitle');
const userProfile       = document.getElementById('user-profile');
const userEmailDisplay  = document.getElementById('user-email-display');
const logoutBtn         = document.getElementById('logout-btn');
const watchlistOption   = document.getElementById('watchlist-option');

// ── Dashboard Data Fetch ──────────────────────────────────────────────────────
async function loadDashboardData(showLoading = false) {
    if (showLoading) {
        cardsContainer.innerHTML = `
            <div class="loading-state">
                <i class="fa-solid fa-spinner fa-spin loading-spinner"></i>
                <p>Loading APIs and health statistics...</p>
            </div>`;
    }
    try {
        const [statusRes, reliabilityRes, failoverRes] = await Promise.all([
            fetch('/api/status'),
            fetch('/api/reliability'),
            fetch('/api/failover-status')
        ]);
        if (!statusRes.ok || !reliabilityRes.ok) throw new Error('Failed to fetch monitoring data');

        const statusPayload      = await statusRes.json();
        const reliabilityPayload = await reliabilityRes.json();
        // failover endpoint may not exist on first boot before DB init — soft fail
        const failoverPayload    = failoverRes.ok ? await failoverRes.json() : [];

        // Build failoverMap: api_id → failover state
        failoverMap = {};
        failoverPayload.forEach(f => { failoverMap[f.api_id] = f; });

        // Resolve backup name into failoverMap using reliability payload for name lookup
        const nameMap = {};
        reliabilityPayload.forEach(r => { nameMap[r.api_id] = r.api_name; });
        Object.values(failoverMap).forEach(f => {
            f.backup_name = f.active_backup_id ? (nameMap[f.active_backup_id] || `API#${f.active_backup_id}`) : null;
        });

        const latestResults = statusPayload.results || [];
        apisData = latestResults.map(item => {
            const relInfo = reliabilityPayload.find(r => r.api_id === item.api_id);
            const stats   = relInfo ? relInfo.stats : null;
            return {
                id:               item.api_id,
                name:             item.api_name,
                url:              item.api_url,
                status:           item.status,
                responseTime:     item.response_time,
                lastChecked:      item.checked_at,
                totalChecks:      stats ? stats.total_checks      : 0,
                uptimePct:        stats ? stats.uptime_pct        : 0,
                avgResponseMs:    stats ? stats.avg_response_ms   : 0,
                reliabilityScore: stats ? stats.reliability_score : 0,
                hasData:          stats ? (stats.status !== 'no_data') : false,
            };
        });

        updateSummaryMetrics();
        filterAndRenderCards();
        resetCountdown();
    } catch (err) {
        console.error('Dashboard fetch error:', err);
        cardsContainer.innerHTML = `
            <div class="loading-state text-danger">
                <i class="fa-solid fa-triangle-exclamation" style="font-size:2.5rem;"></i>
                <p>Error connecting to backend. Make sure the FastAPI server is running.</p>
                <button onclick="loadDashboardData(true)" class="btn btn-primary" style="margin-top:1rem;">Retry</button>
            </div>`;
    }
}

// ── Summary Metrics ───────────────────────────────────────────────────────────
function updateSummaryMetrics() {
    if (!apisData.length) return;
    const total    = apisData.length;
    const upCount  = apisData.filter(a => a.status === 'UP').length;
    const scored   = apisData.filter(a => a.hasData);
    const avgRel   = scored.length
        ? Math.round(scored.reduce((s, a) => s + a.reliabilityScore, 0) / scored.length)
        : 0;
    statTotal.textContent       = total;
    statUp.textContent          = upCount;
    statDown.textContent        = total - upCount;
    statReliability.textContent = `${avgRel}%`;
}

// ── Cards Render ──────────────────────────────────────────────────────────────
function filterAndRenderCards() {
    let filtered = apisData.filter(api => {
        const q = searchQuery.toLowerCase();
        return api.name.toLowerCase().includes(q) || api.url.toLowerCase().includes(q);
    });
    if (activeFilter === 'up')        filtered = filtered.filter(a => a.status === 'UP');
    else if (activeFilter === 'down') filtered = filtered.filter(a => a.status === 'DOWN');
    else if (activeFilter === 'watchlist') filtered = filtered.filter(a => watchlist.includes(a.id));
    if (watchlistOnlyActive)          filtered = filtered.filter(a => watchlist.includes(a.id));

    filtered.sort((a, b) => {
        if (activeSort === 'name')        return a.name.localeCompare(b.name);
        if (activeSort === 'reliability') return b.reliabilityScore - a.reliabilityScore;
        if (activeSort === 'latency') {
            const aT = a.responseTime == null ? 999999 : a.responseTime;
            const bT = b.responseTime == null ? 999999 : b.responseTime;
            return aT - bT;
        }
        return 0;
    });

    if (!filtered.length) {
        cardsContainer.innerHTML = `
            <div class="loading-state">
                <i class="fa-solid fa-magnifying-glass" style="font-size:2rem;color:var(--text-muted);"></i>
                <p>No matching APIs found.</p>
            </div>`;
        return;
    }

    cardsContainer.innerHTML = filtered.map(api => {
        const isUp       = api.status === 'UP';
        const badgeClass = isUp ? 'up' : 'down';
        const rtText     = (isUp && api.responseTime != null) ? `${api.responseTime} ms` : 'N/A';

        // Reliability score or "No data yet"
        const scoreHtml = api.hasData
            ? (() => {
                const sc = api.reliabilityScore >= 80 ? 'high' : api.reliabilityScore >= 50 ? 'mid' : 'low';
                return `<span class="score-badge ${sc}">Reliability: ${api.reliabilityScore}%</span>`;
              })()
            : `<span class="score-badge no-data-score">No data yet</span>`;

        // Uptime display
        const uptimeText = api.hasData ? `${api.uptimePct}%` : '—';

        // Last checked
        let formattedTime = 'Never';
        if (api.lastChecked) {
            const d = new Date(api.lastChecked + 'Z');
            formattedTime = d.toLocaleTimeString(navigator.language, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }

        // Failover badge
        const fo = failoverMap[api.id];
        const failoverBadge = (fo && fo.current_status === 'FAILED_OVER')
            ? `<div class="failover-badge"><i class="fa-solid fa-rotate-exclamation"></i> Failed Over to: ${fo.backup_name || `API#${fo.active_backup_id}`}</div>`
            : '';

        // Watchlist star
        const isWatched = watchlist.includes(api.id);
        const starHtml = token ? `
            <button class="watchlist-btn ${isWatched ? 'active' : ''}" onclick="toggleWatchlist(event,${api.id})">
                <i class="fa-${isWatched ? 'solid' : 'regular'} fa-star"></i>
            </button>` : '';

        // Escape quotes in name/url for onclick attributes
        const safeName = api.name.replace(/'/g, "\\'");
        const safeUrl  = api.url.replace(/'/g, "\\'");

        return `
        <article class="api-card glass-panel" onclick="openHistoryModal(${api.id},'${safeName}','${safeUrl}')">
            <div class="card-header">
                <div class="api-title">
                    <div class="api-title-row"><h4>${api.name}</h4>${starHtml}</div>
                    <div class="api-url-text">${api.url}</div>
                    ${failoverBadge}
                </div>
                <span class="status-badge ${badgeClass}">
                    <span class="pulse-dot"></span>${api.status || '—'}
                </span>
            </div>
            <div class="card-stats">
                <div class="stat-item">
                    <span class="stat-label">Latency</span>
                    <span class="stat-val latency">${rtText}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Uptime %</span>
                    <span class="stat-val">${uptimeText}</span>
                </div>
            </div>
            <div class="card-footer">
                <span>Last checked: ${formattedTime}</span>
                ${scoreHtml}
            </div>
        </article>`;
    }).join('');
}

// ── History Modal ─────────────────────────────────────────────────────────────
async function openHistoryModal(apiId, apiName, apiUrl) {
    modalApiName.textContent = apiName;
    modalApiUrl.textContent  = apiUrl;
    const cached = apisData.find(a => a.id === apiId);
    if (cached) {
        modalTotalChecks.textContent = cached.hasData ? cached.totalChecks : '—';
        modalUptimePct.textContent   = cached.hasData ? `${cached.uptimePct}%` : '—';
        modalAvgLatency.textContent  = (cached.hasData && cached.avgResponseMs > 0)
            ? `${Math.round(cached.avgResponseMs)} ms` : 'N/A';
    }
    historyTableBody.innerHTML = `<tr><td colspan="3" class="placeholder-row">
        <i class="fa-solid fa-spinner fa-spin"></i> Loading logs...</td></tr>`;
    historyModal.classList.add('active');
    historyModal.setAttribute('aria-hidden', 'false');
    try {
        const res  = await fetch(`/api/history/${apiId}`);
        if (!res.ok) throw new Error('Could not pull logs');
        const logs = await res.json();
        if (!logs.length) {
            historyTableBody.innerHTML = `<tr><td colspan="3" class="placeholder-row">No runs recorded yet.</td></tr>`;
            return;
        }
        historyTableBody.innerHTML = logs.map(log => {
            const isUp   = log.status === 'UP';
            const sc     = isUp ? 'text-success' : 'text-danger';
            const lat    = log.response_time != null ? `${log.response_time} ms` : 'N/A';
            const http   = log.http_status_code != null ? `HTTP ${log.http_status_code}` : '—';
            const err    = log.error_message
                ? `<span title="${log.error_message}" style="cursor:help;color:var(--text-muted);font-size:0.78rem;">⚠ ${log.error_message.substring(0,60)}${log.error_message.length>60?'…':''}</span>`
                : '';
            const dt     = new Date(log.checked_at + 'Z').toLocaleString();
            return `<tr>
                <td>${dt}</td>
                <td><span class="${sc}"><i class="fa-solid ${isUp?'fa-play':'fa-stop'}"></i> ${log.status}</span>
                    <small style="color:var(--text-muted)">${http}</small></td>
                <td>${lat}${err}</td></tr>`;
        }).join('');
    } catch (e) {
        historyTableBody.innerHTML = `<tr><td colspan="3" class="placeholder-row text-danger">
            <i class="fa-solid fa-triangle-exclamation"></i> Error loading logs.</td></tr>`;
    }
}
function closeHistoryModal() {
    historyModal.classList.remove('active');
    historyModal.setAttribute('aria-hidden', 'true');
}

// ── Countdown ─────────────────────────────────────────────────────────────────
function startCountdown() {
    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
        countdownValue--;
        const m = Math.floor(countdownValue / 60);
        const s = countdownValue % 60;
        countdownTimer.textContent = `${m}:${s.toString().padStart(2,'0')}`;
        if (countdownValue <= 0) loadDashboardData(false);
    }, 1000);
}
function resetCountdown() {
    countdownValue = 30;
    countdownTimer.textContent = '0:30';
}

// ── Backup Config Panel ───────────────────────────────────────────────────────
async function loadBackupConfigs() {
    const list = document.getElementById('backup-configs-list');
    if (!list) return;
    try {
        const res  = await fetch('/api/backup-config');
        if (!res.ok) throw new Error('fetch failed');
        const rows = await res.json();
        if (!rows.length) {
            list.innerHTML = `<span style="color:var(--text-muted);font-size:0.85rem;">No backup configs yet.</span>`;
            return;
        }
        list.innerHTML = rows.map(r => `
            <div class="backup-config-row">
                <div class="backup-config-row-info">
                    <strong>${r.primary_name}</strong>
                    <i class="fa-solid fa-arrow-right" style="font-size:0.75rem;"></i>
                    <strong>${r.backup_name}</strong>
                    <span class="priority-tag">priority ${r.priority}</span>
                </div>
                <button class="btn btn-danger" onclick="deleteBackupConfig(${r.id})">
                    <i class="fa-solid fa-trash-can"></i> Remove
                </button>
            </div>`).join('');
    } catch (e) {
        list.innerHTML = `<span style="color:var(--danger);font-size:0.85rem;">Failed to load configs.</span>`;
    }
}

async function deleteBackupConfig(configId) {
    try {
        const res = await fetch(`/api/backup-config/${configId}`, { method: 'DELETE' });
        if (res.ok) await loadBackupConfigs();
    } catch (e) { console.error(e); }
}

function populateBackupConfigDropdowns() {
    const primarySel = document.getElementById('bc-primary');
    const backupSel  = document.getElementById('bc-backup');
    if (!primarySel || !backupSel) return;
    const opts = apisData.map(a => `<option value="${a.id}">${a.name}</option>`).join('');
    primarySel.innerHTML = opts;
    backupSel.innerHTML  = opts;
}

document.addEventListener('DOMContentLoaded', () => {
    // Failover panel toggle
    const panelToggle = document.getElementById('failover-panel-toggle');
    const panelBody   = document.getElementById('failover-panel-body');
    if (panelToggle && panelBody) {
        panelToggle.addEventListener('click', () => {
            const open = panelBody.classList.toggle('open');
            panelToggle.classList.toggle('open', open);
            if (open) {
                populateBackupConfigDropdowns();
                loadBackupConfigs();
            }
        });
    }

    // Submit new backup config
    const bcSubmit = document.getElementById('bc-submit-btn');
    const bcError  = document.getElementById('bc-error');
    if (bcSubmit) {
        bcSubmit.addEventListener('click', async () => {
            bcError.classList.add('hidden');
            const primaryId = parseInt(document.getElementById('bc-primary').value);
            const backupId  = parseInt(document.getElementById('bc-backup').value);
            const priority  = parseInt(document.getElementById('bc-priority').value) || 1;
            if (primaryId === backupId) {
                bcError.textContent = 'Primary and backup must be different APIs.';
                bcError.classList.remove('hidden');
                return;
            }
            try {
                const res = await fetch('/api/backup-config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ primary_api_id: primaryId, backup_api_id: backupId, priority })
                });
                const data = await res.json();
                if (!res.ok) {
                    bcError.textContent = data.detail || 'Error creating config.';
                    bcError.classList.remove('hidden');
                    return;
                }
                await loadBackupConfigs();
            } catch (e) {
                bcError.textContent = 'Network error.';
                bcError.classList.remove('hidden');
            }
        });
    }
});

// ── Auth Helpers ──────────────────────────────────────────────────────────────
function openAuthModal() {
    authError.classList.add('hidden');
    authError.textContent = '';
    authEmailInput.value = '';
    authPasswordInput.value = '';
    authMode = 'login';
    updateAuthModalLabels();
    authModal.classList.add('active');
    authModal.setAttribute('aria-hidden', 'false');
}
function closeAuthModal() {
    authModal.classList.remove('active');
    authModal.setAttribute('aria-hidden', 'true');
}
function updateAuthModalLabels() {
    const cg = document.getElementById('auth-confirm-group');
    const ci = document.getElementById('auth-confirm-password');
    if (ci) ci.value = '';
    if (authMode === 'login') {
        authModalTitle.textContent    = 'Welcome to TrustAPI';
        authModalSubtitle.textContent = 'Login to watch your favorite APIs';
        authSubmitText.textContent    = 'Login';
        authSwitchLink.textContent    = 'Sign up';
        authSwitchLink.parentElement.firstChild.textContent = "Don't have an account? ";
        if (cg) cg.classList.add('hidden');
        if (ci) ci.removeAttribute('required');
    } else {
        authModalTitle.textContent    = 'Create Account';
        authModalSubtitle.textContent = 'Sign up to track and organize your watchlist';
        authSubmitText.textContent    = 'Sign Up';
        authSwitchLink.textContent    = 'Login';
        authSwitchLink.parentElement.firstChild.textContent = 'Already have an account? ';
        if (cg) cg.classList.remove('hidden');
        if (ci) ci.setAttribute('required', 'required');
    }
}

async function checkSession() {
    if (!token) { updateAuthUI(); return; }
    try {
        const res = await fetch('/api/me', { headers: { 'Authorization': `Bearer ${token}` } });
        if (res.status === 401) { handleLogout(); return; }
        if (!res.ok) throw new Error('session check failed');
        const data = await res.json();
        userEmail = data.email;
        localStorage.setItem('userEmail', userEmail);
        updateAuthUI();
        await loadWatchlist();
    } catch (e) { updateAuthUI(); }
}

function updateAuthUI() {
    const wfw = document.getElementById('watchlist-filter-wrapper');
    const wfb = document.getElementById('watchlist-filter-btn');
    if (token) {
        authTriggerBtn.classList.add('hidden');
        userProfile.classList.remove('hidden');
        userEmailDisplay.textContent = userEmail;
        watchlistOption.classList.remove('hidden');
        if (wfw) wfw.classList.remove('hidden');
    } else {
        authTriggerBtn.classList.remove('hidden');
        userProfile.classList.add('hidden');
        watchlistOption.classList.add('hidden');
        if (wfw) wfw.classList.add('hidden');
        watchlistOnlyActive = false;
        if (wfb) { wfb.classList.replace('btn-primary','btn-secondary'); wfb.querySelector('i').className='fa-regular fa-star'; }
        if (activeFilter === 'watchlist') { activeFilter = 'all'; statusFilter.value = 'all'; }
    }
}

async function loadWatchlist() {
    if (!token) return;
    try {
        const res = await fetch('/api/watchlist', { headers: { 'Authorization': `Bearer ${token}` } });
        if (res.ok) { const d = await res.json(); watchlist = d.map(i => i.id); filterAndRenderCards(); }
    } catch (e) { console.error(e); }
}

async function toggleWatchlist(event, apiId) {
    if (event) event.stopPropagation();
    if (!token) { openAuthModal(); return; }
    const isWatched = watchlist.includes(apiId);
    try {
        if (isWatched) {
            const r = await fetch(`/api/watchlist/${apiId}`, { method:'DELETE', headers:{'Authorization':`Bearer ${token}`} });
            if (r.ok) { watchlist = watchlist.filter(id => id !== apiId); filterAndRenderCards(); }
        } else {
            const r = await fetch('/api/watchlist', { method:'POST', headers:{'Content-Type':'application/json','Authorization':`Bearer ${token}`}, body: JSON.stringify({api_id: apiId}) });
            if (r.ok) { watchlist.push(apiId); filterAndRenderCards(); }
        }
    } catch (e) { console.error(e); }
}

function handleLogout() {
    token = null; userEmail = null; watchlist = [];
    localStorage.removeItem('trustapi_token');
    localStorage.removeItem('userEmail');
    updateAuthUI();
    filterAndRenderCards();
}

// ── Auth Form Submit ──────────────────────────────────────────────────────────
authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    authError.classList.add('hidden');
    const email    = authEmailInput.value.trim();
    const password = authPasswordInput.value;
    const endpoint = authMode === 'login' ? '/api/login' : '/api/signup';
    authSubmitBtn.disabled = true;
    const origText = authSubmitText.textContent;
    authSubmitText.textContent = authMode === 'login' ? 'Logging in...' : 'Signing up...';
    if (authMode === 'signup') {
        const cp = document.getElementById('auth-confirm-password').value;
        if (password !== cp) {
            authError.textContent = 'Passwords do not match';
            authError.classList.remove('hidden');
            authSubmitBtn.disabled = false;
            authSubmitText.textContent = origText;
            return;
        }
    }
    try {
        const res  = await fetch(endpoint, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email, password}) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'An error occurred.');
        token = data.token; userEmail = data.email || email;
        localStorage.setItem('trustapi_token', token);
        localStorage.setItem('userEmail', userEmail);
        closeAuthModal(); updateAuthUI(); await loadWatchlist();
    } catch (err) {
        authError.textContent = err.message;
        authError.classList.remove('hidden');
    } finally {
        authSubmitBtn.disabled = false;
        authSubmitText.textContent = origText;
    }
});

// ── Event Listeners ───────────────────────────────────────────────────────────
searchInput.addEventListener('input',  e => { searchQuery = e.target.value; filterAndRenderCards(); });
statusFilter.addEventListener('change', e => { activeFilter = e.target.value; filterAndRenderCards(); });
sortSelect.addEventListener('change',   e => { activeSort   = e.target.value; filterAndRenderCards(); });
refreshBtn.addEventListener('click',  () => loadDashboardData(true));
closeModalBtn.addEventListener('click', closeHistoryModal);
historyModal.addEventListener('click',  e => { if (e.target === historyModal) closeHistoryModal(); });
document.addEventListener('keydown',    e => { if (e.key === 'Escape' && historyModal.classList.contains('active')) closeHistoryModal(); });
authTriggerBtn.addEventListener('click', openAuthModal);
closeAuthModalBtn.addEventListener('click', closeAuthModal);
logoutBtn.addEventListener('click', handleLogout);
authSwitchLink.addEventListener('click', e => { e.preventDefault(); authMode = authMode==='login'?'signup':'login'; updateAuthModalLabels(); });
authModal.addEventListener('click', e => { if (e.target === authModal) closeAuthModal(); });

const watchlistFilterBtn = document.getElementById('watchlist-filter-btn');
if (watchlistFilterBtn) {
    watchlistFilterBtn.addEventListener('click', () => {
        watchlistOnlyActive = !watchlistOnlyActive;
        if (watchlistOnlyActive) {
            watchlistFilterBtn.classList.replace('btn-secondary','btn-primary');
            watchlistFilterBtn.querySelector('i').className = 'fa-solid fa-star';
        } else {
            watchlistFilterBtn.classList.replace('btn-primary','btn-secondary');
            watchlistFilterBtn.querySelector('i').className = 'fa-regular fa-star';
        }
        filterAndRenderCards();
    });
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    checkSession();
    loadDashboardData(true);
    startCountdown();
});
