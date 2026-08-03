// Pricing Table Generator — Frontend
const API_URL = ''; // Injected during deploy
const GOOGLE_CLIENT_ID = ''; // Injected during deploy

// ── Auth state ────────────────────────────────────────────────────────────────
let _idToken   = null;
let _userEmail = null;
let _userName  = null;

window.onGoogleSignIn = async function(credentialResponse) {
    _idToken = credentialResponse.credential;
    try {
        const payload = JSON.parse(atob(_idToken.split('.')[1]));
        _userEmail = payload.email;
        _userName  = payload.name || payload.email;
    } catch (e) {
        showSigninError('Could not read token. Please try again.');
        return;
    }
    try {
        await apiFetch('/auth/check', 'GET');
    } catch (e) {
        if (e.status === 403) {
            showSigninError(`${_userEmail} is not authorised. Only @company-domain.com accounts are allowed.`);
        } else {
            showSigninError('Sign-in failed: ' + (e.message || 'Unknown error'));
        }
        _idToken = null; _userEmail = null; _userName = null;
        return;
    }
    sessionStorage.setItem('ptg_token', _idToken);
    sessionStorage.setItem('ptg_email', _userEmail);
    sessionStorage.setItem('ptg_name',  _userName);
    showApp();
};

function showApp() {
    document.getElementById('signin-screen').style.display = 'none';
    document.getElementById('app').style.display = 'flex';
    const pill = document.getElementById('user-pill');
    const avatarEl = document.getElementById('user-pill-avatar');
    const nameEl   = document.getElementById('user-pill-name');
    const signoutEl = document.getElementById('btn-signout');
    if (pill && _userName) {
        pill.style.display = 'flex';
        avatarEl.textContent = _userName.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
        nameEl.textContent   = _userName.split(' ')[0];
    }
    if (signoutEl) signoutEl.style.display = 'inline-block';
}

function signOut() {
    sessionStorage.removeItem('ptg_token');
    sessionStorage.removeItem('ptg_email');
    sessionStorage.removeItem('ptg_name');
    _idToken = null; _userEmail = null; _userName = null;
    document.getElementById('app').style.display = 'none';
    document.getElementById('signin-screen').style.display = 'flex';
    // Reset Google's one-tap so sign-in button renders fresh
    if (window.google?.accounts?.id) google.accounts.id.disableAutoSelect();
}

function showSigninError(msg) {
    const el = document.getElementById('signin-error');
    el.textContent = msg;
    el.style.display = 'block';
}

async function apiFetch(path, method, body) {
    const headers = { 'Content-Type': 'application/json' };
    if (_idToken) headers['Authorization'] = `Bearer ${_idToken}`;
    const resp = await fetch(`${API_URL}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const e = new Error(err.error || `HTTP ${resp.status}`);
        e.status = resp.status;
        throw e;
    }
    return resp.json();
}

// Thin wrappers used in generate/parse/status calls (keeps auth header on all API calls)
async function apiPost(path, body) { return apiFetch(path, 'POST', body); }
async function apiGet(path)        { return apiFetch(path, 'GET'); }

// ── Shared helpers ────────────────────────────────────────────────────────────

function esc(str) {
    const d = document.createElement('div');
    d.textContent = String(str || '');
    return d.innerHTML;
}

// Customer name history — stored in localStorage, shown via datalist
const CUSTOMER_HISTORY_KEY = 'ptg_customer_names';
function loadCustomerHistory() {
    try { return JSON.parse(localStorage.getItem(CUSTOMER_HISTORY_KEY) || '[]'); } catch { return []; }
}
function saveCustomerName(name) {
    if (!name) return;
    const history = loadCustomerHistory().filter(n => n !== name);
    history.unshift(name);
    localStorage.setItem(CUSTOMER_HISTORY_KEY, JSON.stringify(history.slice(0, 20)));
    refreshCustomerDatalist();
}
function refreshCustomerDatalist() {
    const dl = document.getElementById('customer-name-list');
    if (!dl) return;
    const history = loadCustomerHistory();
    dl.innerHTML = history.map(n => `<option value="${esc(n)}">`).join('');
}

// ── Cloud tab switching ───────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Restore session if token saved
    const savedToken = sessionStorage.getItem('ptg_token');
    const savedEmail = sessionStorage.getItem('ptg_email');
    const savedName  = sessionStorage.getItem('ptg_name');
    if (savedToken && savedEmail) {
        _idToken = savedToken; _userEmail = savedEmail; _userName = savedName || savedEmail;
        // Re-validate token on load
        apiFetch('/auth/check', 'GET')
            .then(() => showApp())
            .catch(() => {
                sessionStorage.removeItem('ptg_token');
                sessionStorage.removeItem('ptg_email');
                sessionStorage.removeItem('ptg_name');
                _idToken = null; _userEmail = null; _userName = null;
            });
    }
    // Feature tabs
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
        });
    });

    // Cloud provider tabs
    document.querySelectorAll('.cloud-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.cloud-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.cloud-panel').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`cloud-panel-${tab.dataset.cloud}`).classList.add('active');
        });
    });

    initAWS();
    initGCP();
    initAzure();
    refreshCustomerDatalist();
});


// ══════════════════════════════════════════════════════════════════════════════
// AWS TAB
// ══════════════════════════════════════════════════════════════════════════════

let awsFile = null;
let awsData = null;

function initAWS() {
    const uploadArea = document.getElementById('aws-upload-area');
    const fileInput  = document.getElementById('aws-file-input');

    // Upload area always active — Parse button enabled when both name AND file present
    uploadArea.style.opacity = '1';
    uploadArea.style.pointerEvents = 'auto';

    const awsUpdateParseBtn = () => {
        const hasName = document.getElementById('aws-customer-name').value.trim().length > 0;
        document.getElementById('aws-btn-parse').disabled = !(hasName && awsFile);
    };
    document.getElementById('aws-customer-name').addEventListener('input', awsUpdateParseBtn);

    document.getElementById('aws-upload-browse').addEventListener('click', e => { e.stopPropagation(); fileInput.click(); });
    uploadArea.addEventListener('click', e => { if (e.target.id === 'aws-btn-clear' || e.target.id === 'aws-upload-browse') return; if (!awsFile) fileInput.click(); });
    uploadArea.addEventListener('dragover',  e => { e.preventDefault(); uploadArea.classList.add('dragover'); });
    uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
    uploadArea.addEventListener('drop', e => {
        e.preventDefault(); uploadArea.classList.remove('dragover');
        const f = e.dataTransfer.files[0];
        if (f && f.name.endsWith('.json')) awsStageFile(f, awsUpdateParseBtn);
        else awsSetStatus('Please drop a .json file', 'error');
    });
    fileInput.addEventListener('change', () => { if (fileInput.files[0]) awsStageFile(fileInput.files[0], awsUpdateParseBtn); });
    document.getElementById('aws-btn-clear').addEventListener('click', () => { awsClearFile(); awsUpdateParseBtn(); });
    document.getElementById('aws-btn-parse').addEventListener('click', awsParse);
    document.getElementById('aws-btn-generate').addEventListener('click', awsGenerate);
    document.getElementById('aws-btn-open-table').addEventListener('click', awsOpenTable);

    document.getElementById('aws-currency-select').addEventListener('change', function() {
        const cur = this.value;
        document.getElementById('aws-currency-label').textContent = cur;
        document.getElementById('aws-rate-link').href = `https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page`;
        document.getElementById('aws-myr-rate').value = cur === 'SGD' ? '1.35' : '4.4';
        awsInvalidate('Currency changed — please regenerate.');
    });
    document.getElementById('aws-myr-rate').addEventListener('change', () => awsInvalidate('Rate changed — please regenerate.'));
}

function awsStageFile(file, callback) {
    awsFile = file;
    document.getElementById('aws-upload-prompt').style.display = 'none';
    document.getElementById('aws-upload-ready').style.display = 'flex';
    document.getElementById('aws-file-name').textContent = file.name;
    awsSetStatus('');
    if (callback) callback();
}

async function awsParse() {
    if (!awsFile) return;
    const btn = document.getElementById('aws-btn-parse');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"><i></i><i></i><i></i></span>Parsing...';
    awsSetStatus('');
    try {
        const text = await awsFile.text();
        awsData = JSON.parse(text);
        if (!awsData.Groups || !awsData['Total Cost']) throw new Error('Not a valid AWS Pricing Calculator export');
        awsRenderPreview(awsData);
        document.getElementById('aws-btn-generate').disabled = false;
        const awsParsedName = document.getElementById('aws-customer-name').value.trim();
        if (awsParsedName) saveCustomerName(awsParsedName);
        awsSetStatus(`✓ Parsed ${Object.keys(awsData.Groups || {}).length} groups`, 'success');
    } catch(e) {
        awsSetStatus(e.message, 'error');
        document.getElementById('aws-btn-generate').disabled = true;
    } finally {
        btn.disabled = false; btn.textContent = 'Parse Estimate';
    }
}

function awsClearFile() {
    awsFile = null; awsData = null;
    document.getElementById('aws-file-input').value = '';
    document.getElementById('aws-upload-prompt').style.display = 'block';
    document.getElementById('aws-upload-ready').style.display = 'none';
    document.getElementById('aws-btn-parse').disabled = true;
    document.getElementById('aws-btn-generate').disabled = true;
    document.getElementById('aws-preview-panel').innerHTML = '<div class="preview-placeholder"><p>Enter customer name and upload a JSON export, then click Parse Estimate.</p></div>';
    awsResetOpenButton(); awsSetStatus('');
    window._awsHtml = null;
    document.getElementById('aws-open-prompt').style.display = 'none';
}


// Recursively collect all services from a group node at any nesting depth.
// Returns [{...svc, _path: ['GroupA','SubGroup']}, ...] where _path is the
// full tuple of sub-group keys from group root down to the Services node.
// Services at the group root have _path = [].
function awsCollectServices(node, path) {
    path = path || [];
    const out = [];
    if (Array.isArray(node)) {
        node.forEach(s => out.push({ ...s, _path: path }));
        return out;
    }
    if (node && typeof node === 'object') {
        if (Array.isArray(node.Services)) {
            // Collect flat services at this level first
            node.Services.forEach(s => out.push({ ...s, _path: path }));
            // Then recurse into any sibling sub-group keys
            Object.entries(node).forEach(([key, val]) => {
                if (key !== 'Services') {
                    out.push(...awsCollectServices(val, path.concat(key)));
                }
            });
            return out;
        }
        Object.entries(node).forEach(([key, val]) => {
            out.push(...awsCollectServices(val, path.concat(key)));
        });
    }
    return out;
}

function awsRenderPreview(data, groupStatuses) {
    const customer = data.Name || 'Unknown';
    const totalMonthly = parseFloat(data['Total Cost']?.monthly || 0);
    const calcUrl = data.Metadata?.['Share Url'] || '';

    const groups = Object.entries(data.Groups || {})
        .filter(([n]) => !n.includes('To put in RFP'))
        .map(([gname, gdata], i) => {
            const clean = gname.replace(/^Original Grouping\s*>\s*/, '').trim();
            const services = awsCollectServices(gdata);
            const total = services.reduce((sum, s) => sum + parseFloat(s['Service Cost']?.monthly || 0), 0);
            return { name: clean, rawName: gname, total, services, index: i };
        });

    let html = `<div style="margin-bottom:16px;padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;">
  <div style="font-size:14px;font-weight:700;">${esc(customer)}</div>
  <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">
    Total: <strong style="color:var(--text);">USD ${totalMonthly.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</strong>
    &nbsp;·&nbsp; ${(totalMonthly*12).toLocaleString('en-US',{minimumFractionDigits:2})}/yr &nbsp;·&nbsp; ${data.Metadata?.Currency||'USD'}
  </div>
  ${calcUrl ? `<a href="${calcUrl}" target="_blank" style="font-size:11px;color:var(--aws);margin-top:6px;display:inline-block;">Open in AWS Calculator ↗</a>` : ''}
</div>`;

    groups.forEach((g, i) => {
        const statusEl = !groupStatuses ? '' : (
            groupStatuses[i]==='done' ? '<span style="color:var(--success);font-size:12px;">✓</span>' :
            groupStatuses[i]==='processing' ? '<span class="group-spinner"><i></i><i></i><i></i></span>' :
            '<span style="width:8px;height:8px;border-radius:50%;background:var(--border);display:inline-block;"></span>'
        );
        html += `<div class="pricing-group" id="aws-group-row-${i}">
  <div class="pricing-group-header aws-header" onclick="this.parentElement.classList.toggle('open')">
    <span style="display:flex;align-items:center;gap:6px;"><span class="chevron">▶</span>${esc(g.name)}<span class="group-status-indicator">${statusEl}</span></span>
    <span style="display:flex;align-items:center;gap:8px;">
      <span style="font-size:12px;color:var(--text-muted);">${g.services.length} service${g.services.length!==1?'s':''}</span>
      <span style="font-weight:700;">USD ${g.total.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</span>
    </span>
  </div>
  <div class="pricing-services">`;

        // Group services by their _path for hierarchical heading display in preview
        // Build an ordered list of (pathKey, services[]) preserving insertion order
        const pathSections = [];
        const pathMap = {};
        g.services.forEach(svc => {
            const key = JSON.stringify(svc._path || []);
            if (!pathMap[key]) { pathMap[key] = []; pathSections.push({ path: svc._path || [], services: pathMap[key] }); }
            pathMap[key].push(svc);
        });

        // Assign dot-numbers to every unique path prefix
        const prefixCounters = {};
        const pathNumbers = {};
        function getPathNumber(path) {
            const k = JSON.stringify(path);
            if (pathNumbers[k]) return pathNumbers[k];
            const parentKey = JSON.stringify(path.slice(0,-1));
            prefixCounters[parentKey] = (prefixCounters[parentKey] || 0) + 1;
            const n = prefixCounters[parentKey];
            const parentNum = pathNumbers[parentKey] || '';
            pathNumbers[k] = parentNum ? `${parentNum}.${n}` : String(n);
            return pathNumbers[k];
        }
        pathSections.forEach(({ path }) => {
            for (let d = 1; d <= path.length; d++) getPathNumber(path.slice(0, d));
        });

        const emittedPrefixes = new Set();
        pathSections.forEach(({ path, services: svcs }) => {
            // Emit headings for any new path prefix
            for (let d = 1; d <= path.length; d++) {
                const prefix = path.slice(0, d);
                const pk = JSON.stringify(prefix);
                if (!emittedPrefixes.has(pk)) {
                    emittedPrefixes.add(pk);
                    const num = pathNumbers[pk] || '';
                    const indent = '\u00a0'.repeat(4 * (d - 1));
                    html += `<div class="pricing-subgroup-header" style="padding-left:${(d-1)*12}px">${indent}<b>${num}. ${esc(prefix[d-1])}</b></div>`;
                }
            }
            svcs.forEach(svc => {
                const monthly = parseFloat(svc['Service Cost']?.monthly || 0);
                const props = Object.entries(svc.Properties || {});
                const id = Math.random().toString(36).substr(2,6);
                const label = svc.Description ? `${esc((svc['Service Name']||'').trim())} — <em>${esc(svc.Description)}</em>` : esc((svc['Service Name']||'').trim());
                const indent = path.length > 0 ? `padding-left:${path.length * 12}px` : '';
                html += `<div class="pricing-service" style="${indent}" onclick="var p=document.getElementById('p-${id}');p.style.display=p.style.display==='block'?'none':'block'">
    <span style="display:flex;align-items:center;gap:5px;"><span class="svc-chevron">▾</span>${label}</span>
    <span>${monthly.toFixed(2)}</span></div>`;
                if (props.length) {
                    html += `<div class="pricing-props" id="p-${id}">`;
                    props.forEach(([k,v]) => { html += `<div>${esc(k)}: ${esc(String(v))}</div>`; });
                    html += `</div>`;
                }
            });
        });
        html += `  </div></div>`;
    });
    document.getElementById('aws-preview-panel').innerHTML = html;
}

function awsUpdateGroupStatus(index, status) {
    const row = document.getElementById(`aws-group-row-${index}`);
    if (!row) return;
    const span = row.querySelector('.group-status-indicator');
    if (!span) return;
    span.innerHTML = status === 'done' ? '<span style="color:var(--success);font-size:12px;">✓</span>' : '<span class="group-spinner"><i></i><i></i><i></i></span>';
}


async function awsGenerate() {
    if (!awsData) return;
    const customerName = document.getElementById('aws-customer-name').value.trim() || awsData.Name || 'Customer';
    const myrRate = parseFloat(document.getElementById('aws-myr-rate').value) || 4.4;
    const currency = document.getElementById('aws-currency-select').value;
    const btn = document.getElementById('aws-btn-generate');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"><i></i><i></i><i></i></span>Generating...';
    awsResetOpenButton(); awsSetStatus('Submitting job...');
    awsRenderPreview(awsData);
    try {
        const { job_id, groups, total_groups } = await apiPost('/api/generate', { json: awsData, myr_rate: myrRate, currency, customer_name: customerName });
        groups.forEach((_, i) => awsUpdateGroupStatus(i, 'processing'));
        awsSetStatus(`Claude is processing ${total_groups} group${total_groups>1?'s':''}...`);
        const result = await pollForResult(job_id, groups, awsUpdateGroupStatus);
        window._awsHtml = result.html;
        awsSetOpenButtonReady();
        awsSetStatus(`✓ Done — ${result.customer_name}`, 'success');
        document.getElementById('aws-open-prompt').style.display = 'block';
    } catch(e) {
        awsSetStatus(e.message, 'error');
        document.getElementById('aws-open-prompt').style.display = 'none';
    } finally {
        btn.disabled = false; btn.textContent = 'Generate Table';
    }
}

function awsOpenTable() {
    if (!window._awsHtml) return;
    const blob = new Blob([window._awsHtml], { type: 'text/html' });
    window.open(URL.createObjectURL(blob), '_blank');
}

function awsSetOpenButtonReady() {
    const btn = document.getElementById('aws-btn-open-table');
    btn.disabled = false; btn.classList.add('ready');
    document.getElementById('aws-open-hint').style.display = 'block';
}
function awsResetOpenButton() {
    const btn = document.getElementById('aws-btn-open-table');
    btn.disabled = true; btn.classList.remove('ready');
    document.getElementById('aws-open-hint').style.display = 'none';
}
function awsInvalidate(reason) {
    if (!window._awsHtml) return;
    window._awsHtml = null; awsResetOpenButton();
    document.getElementById('aws-open-prompt').style.display = 'none';
    awsSetStatus(reason);
}
function awsSetStatus(msg, type = '') {
    const el = document.getElementById('aws-status-area');
    el.textContent = msg; el.className = 'status-area' + (type ? ` ${type}` : '');
}


// ══════════════════════════════════════════════════════════════════════════════
// GCP TAB
// ══════════════════════════════════════════════════════════════════════════════

let gcpData = null; // parsed + grouped from pasted text

function initGCP() {
    document.getElementById('gcp-btn-parse').addEventListener('click', gcpParse);
    document.getElementById('gcp-btn-generate').addEventListener('click', gcpGenerate);
    document.getElementById('gcp-btn-open-table').addEventListener('click', gcpOpenTable);

    // Enable Parse button only when both customer name AND paste area have content
    const gcpUpdateParseBtn = () => {
        const hasName = document.getElementById('gcp-customer-name').value.trim().length > 0;
        const hasPaste = document.getElementById('gcp-paste-area').value.trim().length > 0;
        document.getElementById('gcp-btn-parse').disabled = !(hasName && hasPaste);
    };

    // If paste or name changes after a parse, invalidate so user must re-parse
    // gcpUpdateParseBtn is called at the end so button state stays correct
    const gcpInvalidateOnChange = () => {
        if (gcpData) {
            gcpData = null;
            document.getElementById('gcp-btn-generate').disabled = true;
            gcpResetOpenButton();
            document.getElementById('gcp-open-prompt').style.display = 'none';
            gcpSetStatus('Paste changed — please parse again.');
        }
        gcpUpdateParseBtn();
    };
    document.getElementById('gcp-paste-area').addEventListener('input', gcpInvalidateOnChange);
    document.getElementById('gcp-customer-name').addEventListener('input', gcpInvalidateOnChange);

    document.getElementById('gcp-currency-select').addEventListener('change', function() {
        const cur = this.value;
        document.getElementById('gcp-currency-label').textContent = cur;
        document.getElementById('gcp-rate-link').href = `https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page`;
        document.getElementById('gcp-usd-rate').value = cur === 'SGD' ? '1.35' : '4.4';
        gcpInvalidate('Currency changed — please regenerate.');
    });
    document.getElementById('gcp-usd-rate').addEventListener('change', () => gcpInvalidate('Rate changed — please regenerate.'));
}

function gcpParse() {
    const customerName = document.getElementById('gcp-customer-name').value.trim();
    const text = document.getElementById('gcp-paste-area').value.trim();
    if (!customerName) { gcpSetStatus('Please enter a customer name first.', 'error'); return; }
    if (!text) { gcpSetStatus('Please paste your GCP estimate first.', 'error'); return; }

    const btn = document.getElementById('gcp-btn-parse');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"><i></i><i></i><i></i></span>Parsing...';
    gcpSetStatus('Claude is reading the estimate...');

    apiPost('/api/parse-gcp', { text })
    .then(result => {
        if (result.error) throw new Error(result.error);
        if (!result.groups || !result.groups.length) throw new Error('Could not detect any service groups. Make sure you copied from the GCP Calculator estimate page.');

        // Extract authoritative total directly from raw text using regex — avoids floating point issues
        const totalMatch = text.match(/Total estimated cost\$?([\d,]+(?:\.\d+)?)/i);
        const authTotal = totalMatch ? parseFloat(totalMatch[1].replace(/,/g, '')) : result.total;

        gcpData = { groups: result.groups, total: authTotal, calcUrl: '' };
        gcpRenderPreview(gcpData);
        document.getElementById('gcp-btn-generate').disabled = false;
        const gcpParsedName = document.getElementById('gcp-customer-name').value.trim();
        if (gcpParsedName) saveCustomerName(gcpParsedName);
        gcpSetStatus(`✓ Parsed ${result.groups.length} group${result.groups.length !== 1 ? 's' : ''}, ${result.groups.reduce((s,g) => s + g.services.length, 0)} services`, 'success');
    })
    .catch(e => {
        gcpSetStatus(e.message, 'error');
        document.getElementById('gcp-btn-generate').disabled = true;
    })
    .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Parse Estimate';
        // Re-check if both fields still have content
        const hasName = document.getElementById('gcp-customer-name').value.trim().length > 0;
        const hasPaste = document.getElementById('gcp-paste-area').value.trim().length > 0;
        btn.disabled = !(hasName && hasPaste);
    });
}



function gcpRenderPreview(data, groupStatuses) {
    const customerName = document.getElementById('gcp-customer-name').value || 'Unknown';
    const calcUrl = data.calcUrl || '';
    const totalMonthly = data.groups.reduce((s, g) => s + g.total, 0);

    let html = `<div style="margin-bottom:16px;padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;">
  <div style="font-size:14px;font-weight:700;">${esc(customerName)}</div>
  <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">
    Total: <strong style="color:var(--text);">USD ${totalMonthly.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</strong>
    &nbsp;·&nbsp; ${(totalMonthly*12).toLocaleString('en-US',{minimumFractionDigits:2})}/yr &nbsp;·&nbsp; USD
  </div>
  ${calcUrl ? `<a href="${calcUrl}" target="_blank" style="font-size:11px;color:var(--gcp);margin-top:6px;display:inline-block;">Open in GCP Calculator ↗</a>` : ''}
</div>`;

    data.groups.forEach((g, i) => {
        const statusEl = !groupStatuses ? '' : (
            groupStatuses[i]==='done' ? '<span style="color:var(--success);font-size:12px;">✓</span>' :
            groupStatuses[i]==='processing' ? '<span class="group-spinner"><i></i><i></i><i></i></span>' :
            '<span style="width:8px;height:8px;border-radius:50%;background:var(--border);display:inline-block;"></span>'
        );
        html += `<div class="pricing-group" id="gcp-group-row-${i}">
  <div class="pricing-group-header gcp-header" onclick="this.parentElement.classList.toggle('open')">
    <span style="display:flex;align-items:center;gap:6px;"><span class="chevron">▶</span>${esc(g.name)}<span class="group-status-indicator">${statusEl}</span></span>
    <span style="display:flex;align-items:center;gap:8px;">
      <span style="font-size:12px;color:var(--text-muted);">${g.services.length} service${g.services.length!==1?'s':''}</span>
      <span style="font-weight:700;">USD ${g.total.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</span>
    </span>
  </div>
  <div class="pricing-services">`;

        g.services.forEach(svc => {
            const id = Math.random().toString(36).substr(2,6);
            html += `<div class="pricing-service" onclick="var p=document.getElementById('p-${id}');p.style.display=p.style.display==='block'?'none':'block'">
    <span style="display:flex;align-items:center;gap:5px;"><span class="svc-chevron">▾</span>${esc(svc.name)}</span>
    <span>${(svc.cost||0).toFixed(2)}</span></div>`;
            const fields = svc.fields || [];
            if (fields.length) {
                html += `<div class="pricing-props" id="p-${id}" style="display:none">`;
                fields.forEach(f => {
                    const costStr = (f.cost !== null && f.cost !== undefined) ? ` <span style="color:var(--text);">($${f.cost.toFixed(2)})</span>` : '';
                    html += `<div>${esc(f.key)}: ${esc(f.value)}${costStr}</div>`;
                });
                html += `</div>`;
            }
        });
        html += `  </div></div>`;
    });

    document.getElementById('gcp-preview-panel').innerHTML = html;
}

function gcpUpdateGroupStatus(index, status) {
    const row = document.getElementById(`gcp-group-row-${index}`);
    if (!row) return;
    const span = row.querySelector('.group-status-indicator');
    if (!span) return;
    span.innerHTML = status === 'done' ? '<span style="color:var(--success);font-size:12px;">✓</span>' : '<span class="group-spinner"><i></i><i></i><i></i></span>';
}

async function gcpGenerate() {
    if (!gcpData) return;
    const customerName = document.getElementById('gcp-customer-name').value || 'Customer';
    const usdRate  = parseFloat(document.getElementById('gcp-usd-rate').value) || 4.4;
    const currency = document.getElementById('gcp-currency-select').value;
    const btn = document.getElementById('gcp-btn-generate');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"><i></i><i></i><i></i></span>Generating...';
    gcpResetOpenButton(); gcpSetStatus('Submitting job...');
    try {
        const { job_id, groups, total_groups } = await apiPost('/api/generate-gcp', { groups: gcpData.groups, customer_name: customerName, usd_rate: usdRate, currency, calc_url: gcpData.calcUrl || '' });
        groups.forEach((_, i) => gcpUpdateGroupStatus(i, 'processing'));
        gcpSetStatus(`Claude is processing ${total_groups} group${total_groups>1?'s':''}...`);
        const result = await pollForResult(job_id, groups, gcpUpdateGroupStatus);
        window._gcpHtml = result.html;
        gcpSetOpenButtonReady();
        gcpSetStatus(`✓ Done — ${result.customer_name}`, 'success');
        document.getElementById('gcp-open-prompt').style.display = 'block';
    } catch(e) {
        gcpSetStatus(e.message, 'error');
        document.getElementById('gcp-open-prompt').style.display = 'none';
    } finally {
        btn.disabled = false; btn.textContent = 'Generate Table';
    }
}

function gcpOpenTable() {
    if (!window._gcpHtml) return;
    const blob = new Blob([window._gcpHtml], { type: 'text/html' });
    window.open(URL.createObjectURL(blob), '_blank');
}
function gcpSetOpenButtonReady() {
    const btn = document.getElementById('gcp-btn-open-table');
    btn.disabled = false; btn.classList.add('ready');
    document.getElementById('gcp-open-hint').style.display = 'block';
}
function gcpResetOpenButton() {
    const btn = document.getElementById('gcp-btn-open-table');
    btn.disabled = true; btn.classList.remove('ready');
    document.getElementById('gcp-open-hint').style.display = 'none';
}
function gcpInvalidate(reason) {
    if (!window._gcpHtml) return;
    window._gcpHtml = null; gcpResetOpenButton();
    document.getElementById('gcp-open-prompt').style.display = 'none';
    gcpSetStatus(reason);
}
function gcpSetStatus(msg, type = '') {
    const el = document.getElementById('gcp-status-area');
    el.textContent = msg; el.className = 'status-area' + (type ? ` ${type}` : '');
}


// ══════════════════════════════════════════════════════════════════════════════
// SHARED — polling (used by both AWS and GCP)
// ══════════════════════════════════════════════════════════════════════════════

async function pollForResult(jobId, groups, updateStatusFn, maxWait = 300000, interval = 3000) {
    const deadline = Date.now() + maxWait;
    const doneSet = new Set();
    while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, interval));
        let data;
        try { data = await apiGet(`/api/status?job_id=${jobId}`); } catch (e) { continue; }
        if (data.status === 'error') throw new Error(data.error || 'Generation failed');
        if (data.groups_done) {
            data.groups_done.forEach(name => {
                const i = (groups || []).indexOf(name);
                if (i >= 0 && !doneSet.has(i)) { doneSet.add(i); updateStatusFn(i, 'done'); }
            });
        }
        if (data.status === 'done') {
            (groups || []).forEach((_, i) => updateStatusFn(i, 'done'));
            return data;
        }
    }
    throw new Error('Timed out. Please try again.');
}


// ══════════════════════════════════════════════════════════════════════════════
// AZURE TAB
// ══════════════════════════════════════════════════════════════════════════════

let azureFile = null;
let azureData = null;

function initAzure() {
    const uploadArea = document.getElementById('azure-upload-area');
    const fileInput  = document.getElementById('azure-file-input');

    // Upload area always active — Parse button enabled when both name AND file present
    uploadArea.style.opacity = '1';
    uploadArea.style.pointerEvents = 'auto';

    const azureUpdateParseBtn = () => {
        const hasName = document.getElementById('azure-customer-name').value.trim().length > 0;
        document.getElementById('azure-btn-parse').disabled = !(hasName && azureFile);
    };
    document.getElementById('azure-customer-name').addEventListener('input', azureUpdateParseBtn);

    document.getElementById('azure-upload-browse').addEventListener('click', e => { e.stopPropagation(); fileInput.click(); });
    uploadArea.addEventListener('click', e => { if (e.target.id === 'azure-btn-clear' || e.target.id === 'azure-upload-browse') return; if (!azureFile) fileInput.click(); });
    uploadArea.addEventListener('dragover',  e => { e.preventDefault(); uploadArea.classList.add('dragover'); });
    uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
    uploadArea.addEventListener('drop', e => {
        e.preventDefault(); uploadArea.classList.remove('dragover');
        const f = e.dataTransfer.files[0];
        if (f && f.name.endsWith('.xlsx')) azureStageFile(f, azureUpdateParseBtn);
        else azureSetStatus('Please drop a .xlsx file', 'error');
    });
    fileInput.addEventListener('change', () => { if (fileInput.files[0]) azureStageFile(fileInput.files[0], azureUpdateParseBtn); });
    document.getElementById('azure-btn-clear').addEventListener('click', () => { azureClearFile(); azureUpdateParseBtn(); });
    document.getElementById('azure-btn-parse').addEventListener('click', azureParse);
    document.getElementById('azure-btn-generate').addEventListener('click', azureGenerate);
    document.getElementById('azure-btn-open-table').addEventListener('click', azureOpenTable);

    document.getElementById('azure-currency-select').addEventListener('change', function() {
        const cur = this.value;
        document.getElementById('azure-currency-label').textContent = cur;
        document.getElementById('azure-usd-rate').value = cur === 'SGD' ? '1.35' : '4.4';
        azureInvalidate('Currency changed — please regenerate.');
    });
    document.getElementById('azure-usd-rate').addEventListener('change', () => azureInvalidate('Rate changed — please regenerate.'));
}

function azureStageFile(file, callback) {
    azureFile = file;
    document.getElementById('azure-upload-prompt').style.display = 'none';
    document.getElementById('azure-upload-ready').style.display = 'flex';
    document.getElementById('azure-file-name').textContent = file.name;
    azureSetStatus('');
    if (callback) callback();
}

async function azureParse() {
    if (!azureFile) return;
    const customerName = document.getElementById('azure-customer-name').value.trim() || 'Customer';
    const btn = document.getElementById('azure-btn-parse');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"><i></i><i></i><i></i></span>Parsing...';
    azureSetStatus('Uploading estimate...');

    // Yield to browser to let dots render before heavy work
    await new Promise(r => setTimeout(r, 50));

    try {
        // FileReader.readAsDataURL — browser handles base64 encoding natively, no main thread blocking
        const base64 = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(azureFile);
        });

        // Yield again before JSON.stringify to keep spinner alive during serialisation
        await new Promise(r => requestAnimationFrame(() => setTimeout(r, 0)));

        const payload = { xlsx_b64: base64, filename: azureFile.name, customer_name: customerName };

        // POST — returns job_id immediately (async processing)
        const { job_id } = await apiPost('/api/parse-azure', payload);

        // Poll for result
        azureSetStatus('Claude is reading the estimate...');
        const result = await pollForAzureParse(job_id);

        azureData = result;
        azureData.customer_name = customerName;
        azureRenderPreview(azureData);
        document.getElementById('azure-btn-generate').disabled = false;
        saveCustomerName(customerName);
        azureSetStatus(`✓ Parsed ${result.groups.length} group${result.groups.length !== 1 ? 's' : ''}, ${result.groups.reduce((s,g) => s + g.services.length, 0)} services`, 'success');
    } catch(e) {
        azureSetStatus(e.message, 'error');
        document.getElementById('azure-btn-generate').disabled = true;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Parse Estimate';
        const hasName = document.getElementById('azure-customer-name').value.trim().length > 0;
        btn.disabled = !(hasName && azureFile);
    }
}

async function pollForAzureParse(jobId, maxWait = 120000, interval = 2000) {
    const deadline = Date.now() + maxWait;
    while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, interval));
        let data;
        try { data = await apiGet(`/api/status?job_id=${jobId}`); } catch(e) { continue; }
        if (data.status === 'error') throw new Error(data.error || 'Parse failed');
        if (data.status === 'done') return data;
    }
    throw new Error('Timed out. Please try again.');
}

function azureClearFile() {
    azureFile = null; azureData = null;
    document.getElementById('azure-file-input').value = '';
    document.getElementById('azure-upload-prompt').style.display = 'block';
    document.getElementById('azure-upload-ready').style.display = 'none';
    document.getElementById('azure-btn-parse').disabled = true;
    document.getElementById('azure-btn-generate').disabled = true;
    document.getElementById('azure-preview-panel').innerHTML = '<div class="preview-placeholder"><p>Upload an Azure estimate .xlsx to see the summary.</p></div>';
    azureResetOpenButton(); azureSetStatus('');
    window._azureHtml = null;
    document.getElementById('azure-open-prompt').style.display = 'none';
}

function azureRenderPreview(data, groupStatuses) {
    const customerName = document.getElementById('azure-customer-name').value.trim() || data.customer_name || 'Azure Estimate';
    const totalMonthly = data.total || 0;

    let html = `<div style="margin-bottom:16px;padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;">
  <div style="font-size:14px;font-weight:700;">${esc(customerName)}</div>
  <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">
    Total: <strong style="color:var(--text);">USD ${totalMonthly.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</strong>
    &nbsp;·&nbsp; ${(totalMonthly*12).toLocaleString('en-US',{minimumFractionDigits:2})}/yr &nbsp;·&nbsp; USD
  </div>
</div>`;

    (data.groups || []).forEach((g, i) => {
        const statusEl = !groupStatuses ? '' : (
            groupStatuses[i]==='done' ? '<span style="color:var(--success);font-size:12px;">✓</span>' :
            groupStatuses[i]==='processing' ? '<span class="group-spinner"><i></i><i></i><i></i></span>' :
            '<span style="width:8px;height:8px;border-radius:50%;background:var(--border);display:inline-block;"></span>'
        );
        html += `<div class="pricing-group" id="azure-group-row-${i}">
  <div class="pricing-group-header azure-header" onclick="this.parentElement.classList.toggle('open')">
    <span style="display:flex;align-items:center;gap:6px;"><span class="chevron">▶</span>${esc(g.name)}<span class="group-status-indicator">${statusEl}</span></span>
    <span style="display:flex;align-items:center;gap:8px;">
      <span style="font-size:12px;color:var(--text-muted);">${g.services.length} service${g.services.length!==1?'s':''}</span>
      <span style="font-weight:700;">USD ${g.total.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</span>
    </span>
  </div>
  <div class="pricing-services">`;

        g.services.forEach(svc => {
            const id = Math.random().toString(36).substr(2,6);
            const displayName = svc.service_type ? `${esc(svc.name)} <span style="color:var(--text-muted);font-weight:400;">(${esc(svc.service_type)})</span>` : esc(svc.name);
            html += `<div class="pricing-service" onclick="var p=document.getElementById('p-${id}');p.style.display=p.style.display==='block'?'none':'block'">
    <span style="display:flex;align-items:center;gap:5px;"><span class="svc-chevron">▾</span>${displayName}</span>
    <span>${(svc.cost||0).toFixed(2)}</span></div>`;
            if (svc.description) {
                const lines = svc.description.split('\n').filter(l => l.trim());
                html += `<div class="pricing-props" id="p-${id}" style="display:none">`;
                lines.forEach(l => { html += `<div>${esc(l.trim())}</div>`; });
                html += `</div>`;
            }
        });
        html += `  </div></div>`;
    });

    document.getElementById('azure-preview-panel').innerHTML = html;
}

function azureUpdateGroupStatus(index, status) {
    const row = document.getElementById(`azure-group-row-${index}`);
    if (!row) return;
    const span = row.querySelector('.group-status-indicator');
    if (!span) return;
    span.innerHTML = status === 'done' ? '<span style="color:var(--success);font-size:12px;">✓</span>' : '<span class="group-spinner"><i></i><i></i><i></i></span>';
}

async function azureGenerate() {
    if (!azureData) return;
    const customerName = document.getElementById('azure-customer-name').value.trim() || azureData.customer_name || 'Customer';
    const usdRate  = parseFloat(document.getElementById('azure-usd-rate').value) || 4.4;
    const currency = document.getElementById('azure-currency-select').value;
    const btn = document.getElementById('azure-btn-generate');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"><i></i><i></i><i></i></span>Generating...';
    azureResetOpenButton(); azureSetStatus('Submitting job...');
    // Yield to browser to let spinner render
    await new Promise(r => requestAnimationFrame(() => setTimeout(r, 50)));
    try {
        const { job_id, groups, total_groups } = await apiPost('/api/generate-azure', { groups: azureData.groups, customer_name: customerName, usd_rate: usdRate, currency });
        groups.forEach((_, i) => azureUpdateGroupStatus(i, 'processing'));
        azureSetStatus(`Claude is processing ${total_groups} group${total_groups>1?'s':''}...`);
        const result = await pollForResult(job_id, groups, azureUpdateGroupStatus);
        window._azureHtml = result.html;
        azureSetOpenButtonReady();
        azureSetStatus(`✓ Done — ${result.customer_name}`, 'success');
        document.getElementById('azure-open-prompt').style.display = 'block';
    } catch(e) {
        azureSetStatus(e.message, 'error');
        document.getElementById('azure-open-prompt').style.display = 'none';
    } finally {
        btn.disabled = false; btn.textContent = 'Generate Table';
    }
}

function azureOpenTable() {
    if (!window._azureHtml) return;
    const blob = new Blob([window._azureHtml], { type: 'text/html' });
    window.open(URL.createObjectURL(blob), '_blank');
}
function azureSetOpenButtonReady() {
    const btn = document.getElementById('azure-btn-open-table');
    btn.disabled = false; btn.classList.add('ready');
    document.getElementById('azure-open-hint').style.display = 'block';
}
function azureResetOpenButton() {
    const btn = document.getElementById('azure-btn-open-table');
    btn.disabled = true; btn.classList.remove('ready');
    document.getElementById('azure-open-hint').style.display = 'none';
}
function azureInvalidate(reason) {
    if (!window._azureHtml) return;
    window._azureHtml = null; azureResetOpenButton();
    document.getElementById('azure-open-prompt').style.display = 'none';
    azureSetStatus(reason);
}
function azureSetStatus(msg, type = '') {
    const el = document.getElementById('azure-status-area');
    el.textContent = msg; el.className = 'status-area' + (type ? ` ${type}` : '');
}
