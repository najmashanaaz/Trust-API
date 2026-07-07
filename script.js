/**
 * frontend/script.js
 * ──────────────────
 * PURPOSE:
 *     Handles all user interactions, API fetching, sorting, filtering,
 *     countdown logic, and modal visualization on the dashboard.
 */

// ── Global State variables ────────────────────────────────────────────────────
let apisData = [];          // Will hold combined list of { statusInfo, reliabilityInfo }
let activeFilter = 'all';    // 'all' | 'up' | 'down'
let activeSort = 'name';    // 'name' | 'reliability' | 'latency'
let searchQuery = '';       // Tracks search input text
let countdownValue = 30;    // 30 seconds countdown (dashboard reads cached DB data, so frequent refresh is cheap)
let countdownInterval = null;

// ── DOM Elements ─────────────────────────────────────────────────────────────
const cardsContainer = document.getElementById('cards-container');
const searchInput = document.getElementById('search-input');
const statusFilter = document.getElementById('status-filter');
const sortSelect = document.getElementById('sort-select');
const countdownTimer = document.getElementById('countdown-timer');
const refreshBtn = document.getElementById('refresh-btn');

// Summary panel elements
const statTotal = document.getElementById('stat-total');
const statUp = document.getElementById('stat-up');
const statDown = document.getElementById('stat-down');
const statReliability = document.getElementById('stat-reliability');

// Modal Elements
const historyModal = document.getElementById('history-modal');
const modalApiName = document.getElementById('modal-api-name');
const modalApiUrl = document.getElementById('modal-api-url');
const modalTotalChecks = document.getElementById('modal-total-checks');
const modalUptimePct = document.getElementById('modal-uptime-pct');
const modalAvgLatency = document.getElementById('modal-avg-latency');
const historyTableBody = document.getElementById('history-table-body');
const closeModalBtn = document.getElementById('close-modal-btn');


// ── Fetch Operations ─────────────────────────────────────────────────────────

/**
 * Main function to load all dashboard data from the backend endpoints.
 * Combines results from /api/status and /api/reliability.
 */
async function loadDashboardData(showLoading = false) {
    if (showLoading) {
        cardsContainer.innerHTML = `
            <div class="loading-state">
                <i class="fa-solid fa-spinner fa-spin loading-spinner"></i>
                <p>Loading APIs and health statistics...</p>
            </div>
        `;
    }

    try {
        // Fetch current status and reliability configurations in parallel
        const [statusResponse, reliabilityResponse] = await Promise.all([
            fetch('/api/status'),
            fetch('/api/reliability')
        ]);

        if (!statusResponse.ok || !reliabilityResponse.ok) {
            throw new Error('Failed to retrieve monitoring information');
        }

        const statusPayload = await statusResponse.json();
        const reliabilityPayload = await reliabilityResponse.json();

        const latestResults = statusPayload.results || [];

        // Combine the status array with their historical reliability data
        apisData = latestResults.map(item => {
            const relInfo = reliabilityPayload.find(r => r.api_id === item.api_id);
            return {
                id: item.api_id,
                name: item.api_name,
                url: item.api_url,
                status: item.status,
                responseTime: item.response_time,
                lastChecked: item.checked_at,
                // Stats attributes
                totalChecks: relInfo ? relInfo.stats.total_checks : 0,
                uptimePct: relInfo ? relInfo.stats.uptime_pct : 0,
                avgResponseMs: relInfo ? relInfo.stats.avg_response_ms : 0,
                reliabilityScore: relInfo ? relInfo.stats.reliability_score : 0
            };
        });

        updateSummaryMetrics();
        filterAndRenderCards();

        // Reset countdown timer since check ran
        resetCountdown();

    } catch (error) {
        console.error('Error fetching API status:', error);
        cardsContainer.innerHTML = `
            <div class="loading-state text-danger">
                <i class="fa-solid fa-triangle-exclamation" style="font-size: 2.5rem;"></i>
                <p>Error connecting to backend dashboard. Make sure the FastAPI server is running.</p>
                <button onclick="loadDashboardData(true)" class="btn btn-primary" style="margin-top: 1rem;">Retry</button>
            </div>
        `;
    }
}


// ── Summary Panel update ─────────────────────────────────────────────────────
function updateSummaryMetrics() {
    if (apisData.length === 0) return;

    const total = apisData.length;
    const upCount = apisData.filter(api => api.status === 'UP').length;
    const downCount = total - upCount;

    // Average reliability score
    const sumReliability = apisData.reduce((sum, api) => sum + api.reliabilityScore, 0);
    const avgReliability = Math.round(sumReliability / total);

    statTotal.textContent = total;
    statUp.textContent = upCount;
    statDown.textContent = downCount;
    statReliability.textContent = `${avgReliability}%`;
}


// ── Cards Render Pipeline ────────────────────────────────────────────────────
function filterAndRenderCards() {
    // 1. Text Search Filter
    let filtered = apisData.filter(api => {
        const query = searchQuery.toLowerCase();
        return api.name.toLowerCase().includes(query) || api.url.toLowerCase().includes(query);
    });

    // 2. Dropdown Status Filter
    if (activeFilter === 'up') {
        filtered = filtered.filter(api => api.status === 'UP');
    } else if (activeFilter === 'down') {
        filtered = filtered.filter(api => api.status === 'DOWN');
    }

    // 3. Sorting Actions
    filtered.sort((a, b) => {
        if (activeSort === 'name') {
            return a.name.localeCompare(b.name);
        } else if (activeSort === 'reliability') {
            return b.reliabilityScore - a.reliabilityScore; // Higher score first
        } else if (activeSort === 'latency') {
            // Put DOWN (latency=null) at the bottom
            const aTime = a.responseTime === null ? 999999 : a.responseTime;
            const bTime = b.responseTime === null ? 999999 : b.responseTime;
            return aTime - bTime; // Faster latency (smaller number) first
        }
        return 0;
    });

    // 4. Render
    if (filtered.length === 0) {
        cardsContainer.innerHTML = `
            <div class="loading-state">
                <i class="fa-solid fa-magnifying-glass" style="font-size: 2rem; color: var(--text-muted);"></i>
                <p>No matching APIs found for the selected filter.</p>
            </div>
        `;
        return;
    }

    cardsContainer.innerHTML = filtered.map(api => {
        const isUp = api.status === 'UP';
        const badgeClass = isUp ? 'up' : 'down';
        const responseText = isUp ? `${api.responseTime} ms` : 'N/A';
        const scoreClass = api.reliabilityScore >= 80 ? 'high' : (api.reliabilityScore >= 50 ? 'mid' : 'low');

        // Formats Iso Checked time into localized time string
        let formattedTime = 'Never';
        if (api.lastChecked) {
            const date = new Date(api.lastChecked + 'Z'); // append 'Z' for UTC parsing
            formattedTime = date.toLocaleTimeString(navigator.language, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }

        return `
            <article class="api-card glass-panel" onclick="openHistoryModal(${api.id}, '${api.name}', '${api.url}')">
                <div class="card-header">
                    <div class="api-title">
                        <h4>${api.name}</h4>
                        <div class="api-url-text">${api.url}</div>
                    </div>
                    <span class="status-badge ${badgeClass}">
                        <span class="pulse-dot"></span>${api.status}
                    </span>
                </div>
                
                <div class="card-stats">
                    <div class="stat-item">
                        <span class="stat-label">Latency</span>
                        <span class="stat-val latency">${responseText}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Uptime %</span>
                        <span class="stat-val">${api.uptimePct}%</span>
                    </div>
                </div>

                <div class="card-footer">
                    <span>Last checked: ${formattedTime}</span>
                    <span class="score-badge ${scoreClass}">Reliability: ${api.reliabilityScore}%</span>
                </div>
            </article>
        `;
    }).join('');
}


// ── Detailed Log Modal popup ───────────────────────────────────────────────
async function openHistoryModal(apiId, apiName, apiUrl) {
    // Populate simple initial values
    modalApiName.textContent = apiName;
    modalApiUrl.textContent = apiUrl;

    // Find cached information for quick summary values
    const cachedApi = apisData.find(item => item.id === apiId);
    if (cachedApi) {
        modalTotalChecks.textContent = cachedApi.totalChecks;
        modalUptimePct.textContent = `${cachedApi.uptimePct}%`;
        modalAvgLatency.textContent = cachedApi.avgResponseMs > 0 ? `${Math.round(cachedApi.avgResponseMs)} ms` : 'N/A';
    }

    // Set placeholder table state while loading
    historyTableBody.innerHTML = `
        <tr>
            <td colspan="3" class="placeholder-row">
                <i class="fa-solid fa-spinner fa-spin"></i> Loading historical log lines...
            </td>
        </tr>
    `;

    // Show modal container
    historyModal.classList.add('active');
    historyModal.setAttribute('aria-hidden', 'false');

    try {
        const response = await fetch(`/api/history/${apiId}`);
        if (!response.ok) throw new Error('Could not pull logs');

        const logs = await response.json();

        if (logs.length === 0) {
            historyTableBody.innerHTML = `
                <tr>
                    <td colspan="3" class="placeholder-row">No runs recorded for this API yet.</td>
                </tr>
            `;
            return;
        }

        historyTableBody.innerHTML = logs.map(log => {
            const isUp = log.status === 'UP';
            const statusClass = isUp ? 'text-success' : 'text-danger';
            const latencyVal = log.response_time != null ? `${log.response_time} ms` : 'N/A';
            const httpCode = log.http_status_code != null ? `HTTP ${log.http_status_code}` : '—';
            const errMsg = log.error_message ? `<span title="${log.error_message}" style="cursor:help;color:var(--text-muted);font-size:0.78rem;">⚠ ${log.error_message.substring(0, 60)}${log.error_message.length > 60 ? '…' : ''}</span>` : '';

            // Format check datetime to localized string
            const datetimeStr = new Date(log.checked_at + 'Z').toLocaleString();

            return `
                <tr>
                    <td>${datetimeStr}</td>
                    <td><span class="${statusClass}"><i class="fa-solid ${isUp ? 'fa-play' : 'fa-stop'}"></i> ${log.status}</span> <small style="color:var(--text-muted)">${httpCode}</small></td>
                    <td>${latencyVal}${errMsg}</td>
                </tr>
            `;
        }).join('');

    } catch (error) {
        console.error(error);
        historyTableBody.innerHTML = `
            <tr>
                <td colspan="3" class="placeholder-row text-danger">
                    <i class="fa-solid fa-triangle-exclamation"></i> Error loading historical entries.
                </td>
            </tr>
        `;
    }
}

function closeHistoryModal() {
    historyModal.classList.remove('active');
    historyModal.setAttribute('aria-hidden', 'true');
}


// ── Countdown Timer loop ─────────────────────────────────────────────────────
// The dashboard auto-refreshes every 30 seconds.
// This is cheap because the server only reads from SQLite — it never triggers
// real HTTP health checks.  The monitoring service handles those independently.
function startCountdown() {
    if (countdownInterval) clearInterval(countdownInterval);

    countdownInterval = setInterval(() => {
        countdownValue--;

        // Display as MM:SS (e.g. "0:25")
        const minutes = Math.floor(countdownValue / 60);
        const seconds = countdownValue % 60;
        countdownTimer.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;

        if (countdownValue <= 0) {
            loadDashboardData(false); // Fetch fresh data from DB
        }
    }, 1000);
}

function resetCountdown() {
    countdownValue = 30; // Reset to 30 seconds
    const minutes = Math.floor(countdownValue / 60);
    const seconds = countdownValue % 60;
    countdownTimer.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
}


// ── Event Handlers ───────────────────────────────────────────────────────────

// Search filtering (debounce free, real-time input check)
searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value;
    filterAndRenderCards();
});

// Dropdown status filter change
statusFilter.addEventListener('change', (e) => {
    activeFilter = e.target.value;
    filterAndRenderCards();
});

// Dropdown sort metrics change
sortSelect.addEventListener('change', (e) => {
    activeSort = e.target.value;
    filterAndRenderCards();
});

// Manual reload button
refreshBtn.addEventListener('click', () => {
    loadDashboardData(true);
});

// Close modal handlers
closeModalBtn.addEventListener('click', closeHistoryModal);

// Close modal when clicking on the grey background area
historyModal.addEventListener('click', (e) => {
    if (e.target === historyModal) {
        closeHistoryModal();
    }
});

// Close modal on Escape key press
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && historyModal.classList.contains('active')) {
        closeHistoryModal();
    }
});


// ── Application Initialization ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadDashboardData(true); // Initial fetch loading page
    startCountdown();        // Trigger countdown clock
});
