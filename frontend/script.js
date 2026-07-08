/**
 * frontend/script.js
 * ──────────────────
 * PURPOSE:
 *     Handles all user interactions, API fetching, sorting, filtering,
 *     countdown logic, and modal visualization on the dashboard.
 */

// ── Global State variables ────────────────────────────────────────────────────
let apisData = [];          // Will hold combined list of { statusInfo, reliabilityInfo }
let activeFilter = 'all';    // 'all' | 'up' | 'down' | 'watchlist'
let activeSort = 'name';    // 'name' | 'reliability' | 'latency'
let searchQuery = '';       // Tracks search input text
let countdownValue = 30;    // 30 seconds countdown (dashboard reads cached DB data, so frequent refresh is cheap)
let countdownInterval = null;

let token = localStorage.getItem('trustapi_token') || null;
let userEmail = localStorage.getItem('userEmail') || null;
let watchlist = [];          // Array of API IDs in user's watchlist
let authMode = 'login';      // 'login' | 'signup'
let watchlistOnlyActive = false; // Toggle state for watchlist filter

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

// Auth elements
const authModal = document.getElementById('auth-modal');
const authTriggerBtn = document.getElementById('auth-trigger-btn');
const closeAuthModalBtn = document.getElementById('close-auth-modal-btn');
const authForm = document.getElementById('auth-form');
const authEmailInput = document.getElementById('auth-email');
const authPasswordInput = document.getElementById('auth-password');
const authError = document.getElementById('auth-error');
const authSubmitBtn = document.getElementById('auth-submit-btn');
const authSubmitText = document.getElementById('auth-submit-text');
const authSwitchLink = document.getElementById('auth-switch-link');
const authModalTitle = document.getElementById('auth-modal-title');
const authModalSubtitle = document.getElementById('auth-modal-subtitle');
const userProfile = document.getElementById('user-profile');
const userEmailDisplay = document.getElementById('user-email-display');
const logoutBtn = document.getElementById('logout-btn');
const watchlistOption = document.getElementById('watchlist-option');


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
    } else if (activeFilter === 'watchlist') {
        filtered = filtered.filter(api => watchlist.includes(api.id));
    }

    if (watchlistOnlyActive) {
        filtered = filtered.filter(api => watchlist.includes(api.id));
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

        const isWatched = watchlist.includes(api.id);
        const starHtml = token ? `
            <button class="watchlist-btn ${isWatched ? 'active' : ''}" onclick="toggleWatchlist(event, ${api.id})">
                <i class="fa-${isWatched ? 'solid' : 'regular'} fa-star"></i>
            </button>
        ` : '';

        return `
            <article class="api-card glass-panel" onclick="openHistoryModal(${api.id}, '${api.name}', '${api.url}')">
                <div class="card-header">
                    <div class="api-title">
                        <div class="api-title-row">
                            <h4>${api.name}</h4>
                            ${starHtml}
                        </div>
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


// ── Auth & Watchlist Operations ──────────────────────────────────────────────

// Toggle Auth Modal representation
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
    const confirmGroup = document.getElementById('auth-confirm-group');
    const confirmInput = document.getElementById('auth-confirm-password');

    if (confirmInput) {
        confirmInput.value = '';
    }

    if (authMode === 'login') {
        authModalTitle.textContent = "Welcome to PulseGuard";
        authModalSubtitle.textContent = "Login to watch your favorite APIs";
        authSubmitText.textContent = "Login";
        authSwitchLink.textContent = "Sign up";
        authSwitchLink.parentElement.firstChild.textContent = "Don't have an account? ";
        if (confirmGroup) confirmGroup.classList.add('hidden');
        if (confirmInput) confirmInput.removeAttribute('required');
    } else {
        authModalTitle.textContent = "Create Account";
        authModalSubtitle.textContent = "Sign up to track and organize your watchlist";
        authSubmitText.textContent = "Sign Up";
        authSwitchLink.textContent = "Login";
        authSwitchLink.parentElement.firstChild.textContent = "Already have an account? ";
        if (confirmGroup) confirmGroup.classList.remove('hidden');
        if (confirmInput) confirmInput.setAttribute('required', 'required');
    }
}

// Check session sanity checks on endpoint /api/me
async function checkSession() {
    if (!token) {
        updateAuthUI();
        return;
    }

    try {
        const response = await fetch('/api/me', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (response.status === 401) {
            // Token expired/invalid
            handleLogout();
            return;
        }

        if (!response.ok) throw new Error('Session check failed');

        const data = await response.json();
        userEmail = data.email;
        localStorage.setItem('userEmail', userEmail);
        updateAuthUI();
        await loadWatchlist();
    } catch (err) {
        console.error('Session verification error:', err);
        // Soft fail: keep token but don't load watchlist (potentially offline)
        updateAuthUI();
    }
}

function updateAuthUI() {
    const watchlistFilterWrapper = document.getElementById('watchlist-filter-wrapper');
    const watchlistFilterBtn = document.getElementById('watchlist-filter-btn');

    if (token) {
        authTriggerBtn.classList.add('hidden');
        userProfile.classList.remove('hidden');
        userEmailDisplay.textContent = userEmail;
        watchlistOption.classList.remove('hidden');
        if (watchlistFilterWrapper) watchlistFilterWrapper.classList.remove('hidden');
    } else {
        authTriggerBtn.classList.remove('hidden');
        userProfile.classList.add('hidden');
        watchlistOption.classList.add('hidden');
        if (watchlistFilterWrapper) watchlistFilterWrapper.classList.add('hidden');

        // Reset watchlist filter state
        watchlistOnlyActive = false;
        if (watchlistFilterBtn) {
            watchlistFilterBtn.classList.remove('btn-primary');
            watchlistFilterBtn.classList.add('btn-secondary');
            const icon = watchlistFilterBtn.querySelector('i');
            if (icon) icon.className = 'fa-regular fa-star';
        }

        if (activeFilter === 'watchlist') {
            activeFilter = 'all';
            statusFilter.value = 'all';
        }
    }
}

// Watchlist API calls
async function loadWatchlist() {
    if (!token) return;
    try {
        const response = await fetch('/api/watchlist', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (response.ok) {
            const data = await response.json();
            watchlist = data.map(item => item.id);
            filterAndRenderCards();
        }
    } catch (err) {
        console.error('Failed to load watchlist:', err);
    }
}

async function toggleWatchlist(event, apiId) {
    if (event) {
        event.stopPropagation(); // Avoid opening history modal
    }

    if (!token) {
        openAuthModal();
        return;
    }

    const isWatched = watchlist.includes(apiId);

    try {
        if (isWatched) {
            // Remove from watchlist
            const response = await fetch(`/api/watchlist/${apiId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            if (response.ok) {
                watchlist = watchlist.filter(id => id !== apiId);
                filterAndRenderCards();
            }
        } else {
            // Add to watchlist
            const response = await fetch('/api/watchlist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ api_id: apiId })
            });
            if (response.ok) {
                watchlist.push(apiId);
                filterAndRenderCards();
            }
        }
    } catch (err) {
        console.error('Error toggling watchlist:', err);
    }
}

function handleLogout() {
    token = null;
    userEmail = null;
    watchlist = [];
    localStorage.removeItem('trustapi_token');
    localStorage.removeItem('userEmail');
    updateAuthUI();
    filterAndRenderCards();
}

// Signup / Login Submit action Handler
authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    authError.classList.add('hidden');
    authError.textContent = '';

    const email = authEmailInput.value.trim();
    const password = authPasswordInput.value;

    const endpoint = authMode === 'login' ? '/api/login' : '/api/signup';

    authSubmitBtn.disabled = true;
    const originalBtnText = authSubmitText.textContent;
    authSubmitText.textContent = authMode === 'login' ? 'Logging in...' : 'Signing up...';

    if (authMode === 'signup') {
        const confirmPasswordVal = document.getElementById('auth-confirm-password').value;
        if (password !== confirmPasswordVal) {
            authError.textContent = "Passwords do not match";
            authError.classList.remove('hidden');
            authSubmitBtn.disabled = false;
            authSubmitText.textContent = authMode === 'login' ? 'Login' : 'Sign Up';
            return;
        }
    }

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'An error occurred. Please try again.');
        }

        // Success
        token = data.token;
        userEmail = data.email || email;
        localStorage.setItem('trustapi_token', token);
        localStorage.setItem('userEmail', userEmail);

        closeAuthModal();
        updateAuthUI();
        await loadWatchlist();

    } catch (err) {
        console.error(err);
        authError.textContent = err.message;
        authError.classList.remove('hidden');
    } finally {
        authSubmitBtn.disabled = false;
        authSubmitText.textContent = originalBtnText;
    }
});

// Event listeners for auth components
authTriggerBtn.addEventListener('click', openAuthModal);
closeAuthModalBtn.addEventListener('click', closeAuthModal);
logoutBtn.addEventListener('click', handleLogout);

authSwitchLink.addEventListener('click', (e) => {
    e.preventDefault();
    authMode = authMode === 'login' ? 'signup' : 'login';
    updateAuthModalLabels();
});

// Close auth modal when clicking background
authModal.addEventListener('click', (e) => {
    if (e.target === authModal) {
        closeAuthModal();
    }
});

// Watchlist filter toggle activation
const watchlistFilterBtn = document.getElementById('watchlist-filter-btn');
if (watchlistFilterBtn) {
    watchlistFilterBtn.addEventListener('click', () => {
        watchlistOnlyActive = !watchlistOnlyActive;
        if (watchlistOnlyActive) {
            watchlistFilterBtn.classList.remove('btn-secondary');
            watchlistFilterBtn.classList.add('btn-primary');
            const icon = watchlistFilterBtn.querySelector('i');
            if (icon) icon.className = 'fa-solid fa-star';
        } else {
            watchlistFilterBtn.classList.remove('btn-primary');
            watchlistFilterBtn.classList.add('btn-secondary');
            const icon = watchlistFilterBtn.querySelector('i');
            if (icon) icon.className = 'fa-regular fa-star';
        }
        filterAndRenderCards();
    });
}


// ── Application Initialization ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    checkSession();
    loadDashboardData(true); // Initial fetch loading page
    startCountdown();        // Trigger countdown clock
});
