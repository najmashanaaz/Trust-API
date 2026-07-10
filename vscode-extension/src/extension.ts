/**
 * TrustAPI Monitor — VS Code Extension
 * src/extension.ts
 *
 * Features:
 *   1. Reliability warning when a new npm/pip package is installed
 *   2. Live downtime alerts via polling /api/dependency-scan
 *   3. Smart alternative suggestions on warning/alert
 *   4. Dependency Risk Dashboard (WebView panel)
 */

import * as vscode from 'vscode';
import * as https from 'https';
import * as http from 'http';
import * as fs from 'fs';
import * as path from 'path';

// ── Types ─────────────────────────────────────────────────────────────────────
interface PackageReliability {
  tracked: boolean;
  package?: string;
  api_id?: number;
  api_name?: string;
  current_status?: string | null;
  reliability_score?: number;
  uptime_pct?: number;
  stats_status?: string;
}

interface Alternative {
  api_id: number;
  api_name: string;
  reliability_score: number;
  stats_status: string;
}

// ── Extension-level state ─────────────────────────────────────────────────────
let statusBarItem: vscode.StatusBarItem;
let pollTimer: NodeJS.Timeout | undefined;
// api_id → last known status so we only fire once per outage
const lastKnownStatus: Map<number, string> = new Map();
let dashboardPanel: vscode.WebviewPanel | undefined;

// ── Helpers ───────────────────────────────────────────────────────────────────
function getBackendUrl(): string {
  return vscode.workspace
    .getConfiguration('trustapi')
    .get<string>('backendUrl', 'http://localhost:8000')
    .replace(/\/$/, '');
}

function getPollInterval(): number {
  return (
    vscode.workspace
      .getConfiguration('trustapi')
      .get<number>('pollIntervalSeconds', 60) * 1000
  );
}

function fetchJson<T>(url: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith('https') ? https : http;
    const req = lib.get(url, { timeout: 8000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try {
          resolve(JSON.parse(data) as T);
        } catch (e) {
          reject(new Error('Invalid JSON response'));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timed out')); });
  });
}

function postJson<T>(url: string, body: object): Promise<T> {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const parsed  = new URL(url);
    const lib     = parsed.protocol === 'https:' ? https : http;
    const options = {
      hostname: parsed.hostname,
      port:     parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
      path:     parsed.pathname + parsed.search,
      method:   'POST',
      headers:  {
        'Content-Type':   'application/json',
        'Content-Length': Buffer.byteLength(payload),
      },
      timeout: 8000,
    };
    const req = lib.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try { resolve(JSON.parse(data) as T); }
        catch (e) { reject(new Error('Invalid JSON response')); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timed out')); });
    req.write(payload);
    req.end();
  });
}

// ── 1. Read dependencies from workspace ──────────────────────────────────────
function getWorkspaceDependencies(): string[] {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) { return []; }
  const deps: string[] = [];

  for (const folder of folders) {
    // npm: package.json
    const pkgPath = path.join(folder.uri.fsPath, 'package.json');
    if (fs.existsSync(pkgPath)) {
      try {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
        const all = {
          ...(pkg.dependencies || {}),
          ...(pkg.devDependencies || {}),
        };
        deps.push(...Object.keys(all));
      } catch (_) { /* malformed package.json — skip */ }
    }

    // pip: requirements.txt
    const reqPath = path.join(folder.uri.fsPath, 'requirements.txt');
    if (fs.existsSync(reqPath)) {
      try {
        const lines = fs.readFileSync(reqPath, 'utf8').split('\n');
        for (const line of lines) {
          const name = line.trim().split(/[>=<!@\[]/)[0].trim();
          if (name && !name.startsWith('#')) { deps.push(name); }
        }
      } catch (_) { /* skip */ }
    }
  }
  return [...new Set(deps)]; // deduplicate
}

// ── 2. Feature 1: Reliability warning on package.json / requirements.txt save ─
function watchDependencyFiles(ctx: vscode.ExtensionContext): void {
  const watcher = vscode.workspace.createFileSystemWatcher(
    '**/{package.json,requirements.txt}'
  );

  let previousDeps: Set<string> = new Set(getWorkspaceDependencies());

  const checkNewDeps = async () => {
    const current = new Set(getWorkspaceDependencies());
    const added   = [...current].filter((d) => !previousDeps.has(d));
    previousDeps  = current;
    if (added.length === 0) { return; }

    for (const pkg of added) {
      try {
        const url  = `${getBackendUrl()}/api/package-reliability/${encodeURIComponent(pkg)}`;
        const data = await fetchJson<PackageReliability>(url);
        if (!data.tracked) { continue; }

        const score = data.reliability_score ?? 0;
        if (score < 80) {
          // Fetch alternatives
          let altText = '';
          if (data.api_id !== undefined) {
            try {
              const alts = await fetchJson<Alternative[]>(
                `${getBackendUrl()}/api/alternatives/${data.api_id}`
              );
              const top = alts.filter((a) => a.stats_status === 'ok').slice(0, 2);
              if (top.length > 0) {
                altText = `  Alternatives: ${top.map((a) => `${a.api_name} (${a.reliability_score}%)`).join(', ')}`;
              }
            } catch (_) { /* non-critical */ }
          }

          const msg = `⚠ TrustAPI: "${data.api_name}" reliability is ${score}% (below 80%).${altText}`;
          vscode.window.showWarningMessage(msg, 'View Dashboard').then((choice) => {
            if (choice === 'View Dashboard') {
              vscode.commands.executeCommand('trustapi.openDashboard');
            }
          });
        }
      } catch (_) { /* backend may be offline — fail silently */ }
    }
  };

  watcher.onDidChange(checkNewDeps);
  watcher.onDidCreate(checkNewDeps);
  ctx.subscriptions.push(watcher);
}

// ── 3. Feature 2 + 3: Polling for downtime alerts ────────────────────────────
async function pollForDowntime(): Promise<void> {
  const deps = getWorkspaceDependencies();
  if (deps.length === 0) { return; }

  try {
    const results = await postJson<PackageReliability[]>(
      `${getBackendUrl()}/api/dependency-scan`,
      { dependencies: deps }
    );

    statusBarItem.text  = '$(pulse) TrustAPI';
    statusBarItem.tooltip = 'TrustAPI: backend reachable';

    for (const item of results) {
      if (!item.tracked || item.api_id === undefined) { continue; }

      const prev    = lastKnownStatus.get(item.api_id);
      const current = item.current_status ?? null;

      // Transition UP → DOWN: fire alert once
      if (prev === 'UP' && current === 'DOWN') {
        let altText = '';
        try {
          const alts = await fetchJson<Alternative[]>(
            `${getBackendUrl()}/api/alternatives/${item.api_id}`
          );
          const top = alts.filter((a) => a.stats_status === 'ok').slice(0, 2);
          if (top.length > 0) {
            altText = `  Try: ${top.map((a) => a.api_name).join(' or ')}.`;
          }
        } catch (_) { /* non-critical */ }

        const msg = `🔴 TrustAPI: "${item.api_name}" just went DOWN.${altText}`;
        vscode.window.showErrorMessage(msg, 'View Dashboard').then((choice) => {
          if (choice === 'View Dashboard') {
            vscode.commands.executeCommand('trustapi.openDashboard');
          }
        });
      }

      if (current !== null) {
        lastKnownStatus.set(item.api_id, current);
      }
    }
  } catch (_) {
    // Backend offline — show muted status bar item, no error spam
    statusBarItem.text    = '$(warning) TrustAPI: backend unreachable';
    statusBarItem.tooltip = 'TrustAPI: Cannot reach backend. Is the FastAPI server running?';
  }
}

function startPolling(ctx: vscode.ExtensionContext): void {
  if (pollTimer) { clearInterval(pollTimer); }
  pollForDowntime(); // immediate first poll
  pollTimer = setInterval(pollForDowntime, getPollInterval());
  ctx.subscriptions.push({ dispose: () => { if (pollTimer) { clearInterval(pollTimer); } } });

  // Re-start if settings change (e.g. user changes poll interval)
  ctx.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('trustapi.pollIntervalSeconds') ||
          e.affectsConfiguration('trustapi.backendUrl')) {
        startPolling(ctx);
      }
    })
  );
}

// ── 4. Feature 4: Dependency Risk Dashboard (WebView) ────────────────────────
function getDashboardHtml(results: PackageReliability[], nonce: string, cspSource: string): string {
  const rows = results.map((item) => {
    if (!item.tracked) { return ''; }
    const score   = item.reliability_score ?? 0;
    const status  = item.current_status ?? '—';
    const noData  = item.stats_status === 'no_data';
    const color   = noData ? '#6e6e8c' : score >= 90 ? '#10b981' : score >= 70 ? '#f59e0b' : '#ef4444';
    const scoreDisplay = noData ? 'No data yet' : `${score}%`;
    const statusBadge  = status === 'UP'
      ? `<span style="color:#10b981;font-weight:700;">● UP</span>`
      : status === 'DOWN'
        ? `<span style="color:#ef4444;font-weight:700;">● DOWN</span>`
        : `<span style="color:#6e6e8c;">— N/A</span>`;

    return `
      <tr>
        <td style="padding:10px 14px;font-weight:600;color:#ededf5;">${item.api_name ?? item.package}</td>
        <td style="padding:10px 14px;font-family:monospace;color:#a3a3c2;font-size:0.85rem;">${item.package}</td>
        <td style="padding:10px 14px;">${statusBadge}</td>
        <td style="padding:10px 14px;font-weight:700;color:${color};">${scoreDisplay}</td>
        <td style="padding:10px 14px;">
          <div style="background:#1a1a2e;border-radius:4px;height:8px;width:120px;overflow:hidden;">
            <div style="background:${color};height:100%;width:${noData ? 0 : score}%;border-radius:4px;transition:width 0.4s;"></div>
          </div>
        </td>
      </tr>`;
  }).join('');

  const noTracked = results.filter(r => r.tracked).length === 0;
  const backendUrl = getBackendUrl();

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src ${cspSource} ${backendUrl} http://localhost:* https://localhost:*;">
  <title>TrustAPI Dependency Risk</title>
  <style>
    body { background:#0a0a14; color:#ededf5; font-family:'Segoe UI',sans-serif; padding:24px; margin:0; }
    h1   { font-size:1.4rem; margin-bottom:4px; }
    p.sub{ color:#a3a3c2; font-size:0.88rem; margin-bottom:20px; }
    table{ width:100%; border-collapse:collapse; }
    thead tr { border-bottom:1px solid rgba(255,255,255,0.08); }
    th   { padding:8px 14px; text-align:left; font-size:0.78rem; text-transform:uppercase;
           letter-spacing:0.05em; color:#6e6e8c; font-weight:500; }
    tbody tr { border-bottom:1px solid rgba(255,255,255,0.04); transition:background 0.2s; }
    tbody tr:hover { background:rgba(255,255,255,0.02); }
    .empty { color:#6e6e8c; padding:32px; text-align:center; font-size:0.95rem; }
    button { background:#5850ec; color:#fff; border:none; padding:8px 18px; border-radius:50px;
             cursor:pointer; font-size:0.88rem; margin-bottom:20px; }
    button:hover { background:#4f46e5; }
  </style>
</head>
<body>
  <h1>⚡ TrustAPI — Dependency Risk Dashboard</h1>
  <p class="sub">Live reliability scores for your tracked AI/cloud dependencies.</p>
  <button id="refresh-btn">↻ Refresh</button>
  ${noTracked
    ? `<p class="empty">No tracked AI/cloud dependencies found in this workspace.<br>
       Add packages like <code>openai</code>, <code>anthropic</code>, or <code>groq</code> to your package.json or requirements.txt.</p>`
    : `<table>
        <thead>
          <tr>
            <th>API / Service</th><th>Package</th><th>Status</th><th>Reliability</th><th>Score Bar</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
       </table>`
  }
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.getElementById('refresh-btn').addEventListener('click', () => {
      vscode.postMessage({ command: 'refresh' });
    });
  </script>
</body>
</html>`;
}

async function openDashboard(ctx: vscode.ExtensionContext): Promise<void> {
  if (dashboardPanel) {
    dashboardPanel.reveal(vscode.ViewColumn.One);
    await refreshDashboard();
    return;
  }

  dashboardPanel = vscode.window.createWebviewPanel(
    'trustapi.dashboard',
    'TrustAPI Dependency Risk',
    vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true }
  );

  dashboardPanel.onDidDispose(() => { dashboardPanel = undefined; }, null, ctx.subscriptions);

  dashboardPanel.webview.onDidReceiveMessage(
    (msg) => { if (msg.command === 'refresh') { refreshDashboard(); } },
    undefined,
    ctx.subscriptions
  );

  await refreshDashboard();
}

async function refreshDashboard(): Promise<void> {
  if (!dashboardPanel) { return; }

  const deps = getWorkspaceDependencies();
  let results: PackageReliability[] = [];

  try {
    if (deps.length > 0) {
      results = await postJson<PackageReliability[]>(
        `${getBackendUrl()}/api/dependency-scan`,
        { dependencies: deps }
      );
    }
  } catch (_) {
    // Backend offline — show empty state; status bar already shows warning
  }

  // Generate a fresh nonce for each render
  const nonce = Buffer.from(Math.random().toString(36) + Date.now().toString(36)).toString('base64');
  dashboardPanel.webview.html = getDashboardHtml(results, nonce, dashboardPanel.webview.cspSource);
}

// ── activate / deactivate ─────────────────────────────────────────────────────
export function activate(ctx: vscode.ExtensionContext): void {
  // Status bar item — always visible, bottom bar
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  statusBarItem.text    = '$(pulse) TrustAPI';
  statusBarItem.tooltip = 'TrustAPI Monitor active';
  statusBarItem.command = 'trustapi.openDashboard';
  statusBarItem.show();
  ctx.subscriptions.push(statusBarItem);

  // Register commands
  ctx.subscriptions.push(
    vscode.commands.registerCommand('trustapi.openDashboard', () => openDashboard(ctx)),
    vscode.commands.registerCommand('trustapi.refreshDashboard', () => refreshDashboard()),
  );

  // Feature 1: watch dependency files for newly added packages
  watchDependencyFiles(ctx);

  // Features 2 + 3: start polling for downtime
  startPolling(ctx);

  // Feature 4: auto-open dashboard on activation
  openDashboard(ctx);
}

export function deactivate(): void {
  if (pollTimer) { clearInterval(pollTimer); }
}
