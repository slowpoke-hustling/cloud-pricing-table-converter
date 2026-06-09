// Pricing Table Generator — Frontend
const API_URL = ''; // Injected during deploy

let uploadedFile = null;
let parsedData = null;
let groupList = [];

function esc(str) {
    const d = document.createElement('div');
    d.textContent = String(str || '');
    return d.innerHTML;
}

document.addEventListener('DOMContentLoaded', () => {
    // Tab switching
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
        });
    });

    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');

    document.getElementById('upload-browse').addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });
    uploadArea.addEventListener('click', (e) => {
        if (e.target.id === 'btn-clear' || e.target.id === 'upload-browse') return;
        if (!uploadedFile) fileInput.click();
    });
    uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); uploadArea.classList.add('dragover'); });
    uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const f = e.dataTransfer.files[0];
        if (f && f.name.endsWith('.json')) handleFile(f);
        else setStatus('Please drop a .json file', 'error');
    });
    fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

    document.getElementById('btn-clear').addEventListener('click', clearFile);
    document.getElementById('btn-generate').addEventListener('click', generate);
    document.getElementById('btn-open-table').addEventListener('click', openTable);

    // Currency selector — update label, xe.com link, and invalidate generated table
    document.getElementById('currency-select').addEventListener('change', function() {
        const cur = this.value;
        document.getElementById('currency-label').textContent = cur;
        document.getElementById('rate-link').href =
            `https://www.xe.com/currencyconverter/convert/?Amount=1&From=USD&To=${cur}`;
        document.getElementById('myr-rate').value = cur === 'SGD' ? '1.35' : '4.4';
        invalidateGeneratedTable('Currency changed — please regenerate.');
    });

    // Exchange rate change — invalidate generated table
    document.getElementById('myr-rate').addEventListener('change', function() {
        invalidateGeneratedTable('Rate changed — please regenerate.');
    });
});

// ── File handling ─────────────────────────────────────────────────────────────

async function handleFile(file) {
    uploadedFile = file;
    document.getElementById('upload-prompt').style.display = 'none';
    document.getElementById('upload-ready').style.display = 'flex';
    document.getElementById('file-name').textContent = file.name;
    setStatus('');

    try {
        const text = await file.text();
        parsedData = JSON.parse(text);
        if (!parsedData.Groups || !parsedData['Total Cost']) {
            throw new Error('Not a valid AWS Pricing Calculator export');
        }
        renderPreview(parsedData);
        document.getElementById('btn-generate').disabled = false;
    } catch(e) {
        setStatus(e.message, 'error');
        document.getElementById('btn-generate').disabled = true;
    }
}

function clearFile() {
    uploadedFile = null;
    parsedData = null;
    groupList = [];
    document.getElementById('file-input').value = '';
    document.getElementById('upload-prompt').style.display = 'block';
    document.getElementById('upload-ready').style.display = 'none';
    document.getElementById('btn-generate').disabled = true;
    document.getElementById('preview-panel').innerHTML =
        '<div class="preview-placeholder"><p>Upload a JSON export to see the estimate summary.</p></div>';
    resetOpenButton();
    setStatus('');
    window._generatedHtml = null;
    document.getElementById('open-prompt').style.display = 'none';
}

// ── Estimate Preview ──────────────────────────────────────────────────────────

function renderPreview(data, groupStatuses) {
    const customer = data.Name || 'Unknown';
    const totalMonthly = parseFloat(data['Total Cost']?.monthly || 0);
    const calcUrl = data.Metadata?.['Share Url'] || '';
    const myrRate = parseFloat(document.getElementById('myr-rate').value) || 4.4;

    // Build group list
    const groups = Object.entries(data.Groups || {})
        .filter(([n]) => !n.includes('To put in RFP'))
        .map(([gname, gdata], i) => {
            const clean = gname.replace(/^Original Grouping\s*>\s*/, '').trim();
            let total = 0, services = [];

            // Normalize — some exports have group value as a list
            if (Array.isArray(gdata)) {
                gdata = { Services: gdata };
            }

            if (gdata.Services) {
                gdata.Services.forEach(s => { total += parseFloat(s['Service Cost'].monthly); services.push(s); });
            } else {
                Object.entries(gdata).forEach(([subName, sd]) => {
                    if (Array.isArray(sd)) {
                        sd.forEach(s => { total += parseFloat(s['Service Cost']?.monthly || 0); services.push({...s, _sub: subName}); });
                    } else if (sd && sd.Services) {
                        (sd.Services || []).forEach(s => { total += parseFloat(s['Service Cost'].monthly); services.push({...s, _sub: subName}); });
                    }
                });
            }
            return { name: clean, rawName: gname, total, services, index: i };
        });

    groupList = groups;

    // Summary header
    let html = `<div style="margin-bottom:16px;padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;">
  <div style="font-size:14px;font-weight:700;">${esc(customer)}</div>
  <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">
    Total: <strong style="color:var(--text);">USD ${totalMonthly.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</strong>
    &nbsp;·&nbsp; ${(totalMonthly*12).toLocaleString('en-US',{minimumFractionDigits:2})}/yr
    &nbsp;·&nbsp; ${data.Metadata?.Currency || 'USD'}
  </div>
  ${calcUrl ? `<a href="${calcUrl}" target="_blank" style="font-size:11px;color:var(--accent);margin-top:6px;display:inline-block;">Open in AWS Calculator ↗</a>` : ''}
</div>`;

    // Groups — collapsible, like SA Agent pricing tab
    groups.forEach((g, i) => {
        const statusEl = (() => {
            if (!groupStatuses) return '';
            const st = groupStatuses[i];
            if (st === 'done') return '<span style="color:var(--success);font-size:12px;">✓</span>';
            if (st === 'processing') return '<span class="group-spinner"></span>';
            return '<span style="width:8px;height:8px;border-radius:50%;background:var(--border);display:inline-block;"></span>';
        })();

        html += `<div class="pricing-group" id="group-row-${i}">
  <div class="pricing-group-header" onclick="this.parentElement.classList.toggle('open')">
    <span style="display:flex;align-items:center;gap:6px;">
      <span class="chevron">▶</span>${esc(g.name)}<span class="group-status-indicator">${statusEl}</span>
    </span>
    <span style="display:flex;align-items:center;gap:8px;">
      <span style="font-size:12px;color:var(--text-muted);">${g.services.length} service${g.services.length!==1?'s':''}</span>
      <span style="font-weight:700;">USD ${g.total.toLocaleString('en-US',{minimumFractionDigits:2})}/mo</span>
    </span>
  </div>
  <div class="pricing-services">`;

        g.services.forEach(svc => {
            const monthly = parseFloat(svc['Service Cost']?.monthly || 0);
            const props = Object.entries(svc.Properties || {});
            const id = Math.random().toString(36).substr(2,6);
            const label = svc.Description ? `${esc((svc['Service Name']||'').trim())} — <em>${esc(svc.Description)}</em>` : esc((svc['Service Name']||'').trim());
            const subLabel = svc._sub ? ` <span style="font-size:10px;color:var(--text-muted);">[${esc(svc._sub)}]</span>` : '';
            html += `<div class="pricing-service" onclick="var p=document.getElementById('p-${id}');p.style.display=p.style.display==='block'?'none':'block'">
    <span style="display:flex;align-items:center;gap:5px;"><span class="svc-chevron">▾</span>${label}${subLabel}</span>
    <span>${monthly.toFixed(2)}</span>
  </div>`;
            if (props.length) {
                html += `<div class="pricing-props" id="p-${id}">`;
                props.forEach(([k,v]) => { html += `<div>${esc(k)}: ${esc(String(v))}</div>`; });
                html += `</div>`;
            }
        });

        html += `  </div>
</div>`;
    });

    document.getElementById('preview-panel').innerHTML = html;
}

function updateGroupStatus(index, status) {
    const row = document.getElementById(`group-row-${index}`);
    if (!row) return;
    let statusSpan = row.querySelector('.group-status-indicator');
    if (!statusSpan) return;
    if (status === 'done') {
        statusSpan.innerHTML = '<span style="color:var(--success);font-size:12px;">✓</span>';
    } else if (status === 'processing') {
        statusSpan.innerHTML = '<span class="group-spinner"></span>';
    }
}

// ── Generate ──────────────────────────────────────────────────────────────────

async function generate() {
    if (!parsedData) return;

    const myrRate = parseFloat(document.getElementById('myr-rate').value) || 4.4;
    const currency = document.getElementById('currency-select').value;
    const btn = document.getElementById('btn-generate');

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Generating...';
    resetOpenButton();
    setStatus('Submitting job...');

    // Re-render preview with all groups in waiting state
    renderPreview(parsedData);

    try {
        const resp = await fetch(`${API_URL}/api/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ json: parsedData, myr_rate: myrRate, currency: currency }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || `Server error ${resp.status}`);
        }
        const { job_id, groups, total_groups } = await resp.json();

        // Mark all as processing
        groups.forEach((_, i) => updateGroupStatus(i, 'processing'));
        setStatus(`Claude is processing ${total_groups} group${total_groups > 1 ? 's' : ''}...`);

        // Poll until done
        const result = await pollForResult(job_id, groups);

        window._generatedHtml = result.html;
        setOpenButtonReady();
        setStatus(`✓ Done — ${result.customer_name}`, 'success');
        document.getElementById('open-prompt').style.display = 'block';

    } catch(e) {
        setStatus(e.message, 'error');
        document.getElementById('open-prompt').style.display = 'none';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Table';
    }
}

async function pollForResult(jobId, groups, maxWait = 300000, interval = 3000) {
    const deadline = Date.now() + maxWait;
    const doneSet = new Set();

    while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, interval));

        const resp = await fetch(`${API_URL}/api/status?job_id=${jobId}`);
        if (!resp.ok) continue;
        const data = await resp.json();

        if (data.status === 'error') throw new Error(data.error || 'Generation failed');

        // Update group statuses based on groups_done list
        if (data.groups_done) {
            data.groups_done.forEach(name => {
                const i = (groups || []).indexOf(name);
                if (i >= 0 && !doneSet.has(i)) {
                    doneSet.add(i);
                    updateGroupStatus(i, 'done');
                }
            });
            setStatus(`Claude is processing — ${data.completed} / ${data.total} chunks done...`);
        }

        if (data.status === 'done') {
            // Mark all done
            (groups || []).forEach((_, i) => updateGroupStatus(i, 'done'));
            return data;
        }
    }
    throw new Error('Timed out. Please try again.');
}

// ── Open table button ─────────────────────────────────────────────────────────

function setOpenButtonReady() {
    const btn = document.getElementById('btn-open-table');
    btn.disabled = false;
    btn.classList.add('ready');
    document.getElementById('open-hint').style.display = 'block';
}

function resetOpenButton() {
    const btn = document.getElementById('btn-open-table');
    btn.disabled = true;
    btn.classList.remove('ready');
    document.getElementById('open-hint').style.display = 'none';
}

function openTable() {
    if (!window._generatedHtml) return;
    const blob = new Blob([window._generatedHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function invalidateGeneratedTable(reason) {
    if (!window._generatedHtml) return; // nothing generated yet, nothing to do
    window._generatedHtml = null;
    resetOpenButton();
    document.getElementById('open-prompt').style.display = 'none';
    setStatus(reason);
}

function setStatus(msg, type = '') {
    const el = document.getElementById('status-area');
    el.textContent = msg;
    el.className = 'status-area' + (type ? ` ${type}` : '');
}

function readFile(file) {
    if (file && typeof file.text === 'function') return file.text();
    return new Promise((resolve, reject) => {
        if (!file || !(file instanceof Blob)) { reject(new Error('No valid file')); return; }
        const reader = new FileReader();
        reader.onload = e => resolve(e.target.result);
        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsText(file);
    });
}
