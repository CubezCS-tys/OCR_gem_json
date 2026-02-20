/* =============================================
   ScanToText — Frontend Logic v3 (JWT auth)
   ============================================= */

const API = '';

let currentJobId    = null;
let currentPageCount = 0;
let authToken   = localStorage.getItem('scantotext_jwt')   || '';
let userEmail   = localStorage.getItem('scantotext_email') || '';
let appConfig   = {};

// ── DOM ────────────────────────────────────────────────────────────────────
const $  = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const show = (el) => el && el.classList.remove('hidden');
const hide = (el) => el && el.classList.add('hidden');

const dom = {
    uploadSection:   $('#upload-section'),
    fileSection:     $('#file-section'),
    processSection:  $('#processing-section'),
    resultSection:   $('#result-section'),
    errorSection:    $('#error-section'),
    loginSection:    $('#login-section'),
    loginAuthError:  $('#login-auth-error'),
    dropZone:        $('#drop-zone'),
    fileInput:       $('#file-input'),
    fileName:        $('#file-name'),
    fileMeta:        $('#file-meta'),
    pageCount:       $('#page-count-display'),
    pageCost:        $('#page-cost'),
    proNote:         $('#pro-note'),
    btnFree:         $('#btn-free'),
    btnPro:          $('#btn-pro'),
    btnRemove:       $('#btn-remove'),
    btnNew:          $('#btn-new'),
    btnRetry:        $('#btn-retry'),
    btnDownload:     $('#btn-download'),
    btnAuth:         $('#btn-auth'),
    btnManage:       $('#btn-manage'),
    accountBar:      $('#account-bar'),
    usageText:       $('#usage-text'),
    processingTitle: $('#processing-title'),
    processingMsg:   $('#processing-msg'),
    progressBar:     $('.progress-bar'),
    errorMsg:        $('#error-msg'),
    resultInfo:      $('#result-info'),
    formatBadges:    $('#format-badges'),
    planPrice:       $('#plan-price'),
};

// ── Auth helpers ───────────────────────────────────────────────────────────
function authHeaders(extra = {}) {
    const h = { ...extra };
    if (authToken) h['Authorization'] = `Bearer ${authToken}`;
    return h;
}

function storeAuth(token, email) {
    authToken = token;
    userEmail = email;
    localStorage.setItem('scantotext_jwt',   token);
    localStorage.setItem('scantotext_email', email);
}

function clearAuth() {
    authToken = '';
    userEmail = '';
    localStorage.removeItem('scantotext_jwt');
    localStorage.removeItem('scantotext_email');
}

// ── Init ────────────────────────────────────────────────────────────────────
async function init() {
    try {
        const res = await fetch(`${API}/api/config`);
        appConfig = await res.json();
        if (dom.planPrice) dom.planPrice.textContent = appConfig.plan_price_display || '£20';
    } catch(e) { /* ok */ }

    // Handle redirect back from /auth/google/callback or /subscribe/success
    const params = new URLSearchParams(window.location.search);
    const tok = params.get('token');
    const em  = params.get('email');
    const authErr = params.get('auth_error');
    if (tok && em) {
        storeAuth(tok, em);
        window.history.replaceState({}, '', '/');
        await refreshAccount();
        await ensureTrial();   // auto-activate trial for new users
        bindEvents();
        return;
    } else if (authErr) {
        // Show error in login modal
        const msgs = { state_mismatch: 'Login failed (security check). Please try again.', google_failed: 'Google sign-in failed. Please try again.', access_denied: 'Access was denied. Please try again.' };
        if (dom.loginAuthError) {
            dom.loginAuthError.textContent = msgs[authErr] || 'Sign-in failed. Please try again.';
            dom.loginAuthError.classList.remove('hidden');
        }
        show(dom.loginSection);
        window.history.replaceState({}, '', '/');
    }

    if (authToken) await refreshAccount();

    bindEvents();
}

// ── Events ──────────────────────────────────────────────────────────────────
function bindEvents() {
    dom.dropZone.addEventListener('click', () => dom.fileInput.click());
    dom.dropZone.addEventListener('dragover',  (e) => { e.preventDefault(); dom.dropZone.classList.add('drag-over'); });
    dom.dropZone.addEventListener('dragleave', ()  => dom.dropZone.classList.remove('drag-over'));
    dom.dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dom.dropZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    dom.fileInput.addEventListener('change', () => {
        if (dom.fileInput.files.length) handleFile(dom.fileInput.files[0]);
    });

    dom.btnFree.addEventListener('click', () => processDocument('free'));
    dom.btnPro.addEventListener('click',  () => processDocument('pro'));
    dom.btnRemove.addEventListener('click', resetUpload);
    dom.btnNew.addEventListener('click',    resetUpload);
    dom.btnRetry.addEventListener('click',  resetUpload);

    dom.btnAuth.addEventListener('click', showLogin);

    if (dom.btnManage) dom.btnManage.addEventListener('click', manageSubscription);

    // Subscribe buttons in pricing section
    $$('.subscribe-btn').forEach(btn => btn.addEventListener('click', () => {
        if (!authToken) { showLogin(); return; }
        startSubscription();
    }));
}

// ── File handling ───────────────────────────────────────────────────────────
async function handleFile(file) {
    const allowed = (appConfig.supported_formats || ['.pdf','.jpg','.jpeg','.png','.tiff','.tif','.webp','.bmp']);
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) {
        showError(`Unsupported format: ${ext}`);
        return;
    }
    const maxMb = appConfig.max_file_size_mb || 50;
    if (file.size > maxMb * 1024 * 1024) {
        showError(`File too large. Max ${maxMb} MB.`);
        return;
    }

    dom.fileName.textContent = file.name;
    const sizeMb = (file.size / 1024 / 1024).toFixed(1);
    dom.fileMeta.textContent = `${sizeMb} MB`;
    showOnly('fileSection');

    try {
        const fd = new FormData();
        fd.append('file', file);

        const res = await fetch(`${API}/api/upload`, { method: 'POST', body: fd });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
            throw new Error(err.detail || 'Upload failed');
        }
        const data = await res.json();
        currentJobId     = data.job_id;
        currentPageCount = data.page_count || 1;

        if (dom.pageCount) dom.pageCount.textContent = currentPageCount;
        updateProNote();
        showOnly('fileSection');
    } catch(err) {
        showError(err.message);
    }
}

function updateProNote() {
    if (!authToken) {
        dom.proNote.textContent = '7-day free trial available — no card needed';
        dom.proNote.style.color = '#7c3aed';
        return;
    }
    if (appConfig.demo_mode) {
        dom.proNote.textContent = 'Demo mode — no payment required';
        dom.proNote.style.color = '#10b981';
    } else {
        dom.proNote.textContent = `Will use ${currentPageCount} of your remaining pages`;
        dom.proNote.style.color = '';
    }
}

// ── Processing ───────────────────────────────────────────────────────────────
async function processDocument(tier) {
    if (!currentJobId) return;

    if (tier === 'pro' && !authToken) {
        showLogin();
        return;
    }

    // Collect selected formats for pro
    let selectedFormats = '';
    if (tier === 'pro') {
        const checked = [...$$('#format-picker input:checked')].map(el => el.value);
        if (checked.length === 0) { showError('Select at least one output format.'); return; }
        selectedFormats = checked.join(',');
    }

    const endpoint = tier === 'free'
        ? `${API}/api/process/free/${currentJobId}`
        : `${API}/api/process/pro/${currentJobId}?formats=${encodeURIComponent(selectedFormats)}`;

    const tierLabel = tier === 'free' ? 'Searchable PDF' : 'All Formats (Pro)';
    showProcessing(
        `Converting — ${tierLabel}`,
        tier === 'free' ? 'Running OCR engine...' : 'Running 3 AI engines in parallel...'
    );
    simulateProgress(tier === 'free' ? 25000 : 70000);

    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: authHeaders(),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Processing failed' }));
            throw new Error(err.detail || 'Processing failed');
        }
        const data = await res.json();
        dom.progressBar.style.width = '100%';
        if (tier === 'pro') await refreshAccount();
        showResult(data);
    } catch(err) {
        showError(err.message);
    }
}

function showResult(data) {
    dom.resultInfo.textContent = data.filename || '';
    dom.formatBadges.innerHTML = '';
    (data.formats || data.formats_produced || []).forEach(f => {
        const span = document.createElement('span');
        span.className   = 'format-badge';
        span.textContent = f;
        dom.formatBadges.appendChild(span);
    });
    dom.btnDownload.href = `${API}/api/download/${data.job_id}`;
    showOnly('resultSection');
}

// ── Auth ─────────────────────────────────────────────────────────────────────
function showLogin() {
    if (dom.loginAuthError) dom.loginAuthError.classList.add('hidden');
    show(dom.loginSection);
}

async function ensureTrial() {
    // Called after first login — activate trial if user has no plan
    if (!authToken) return;
    try {
        const accRes = await fetch(`${API}/api/account`, { headers: authHeaders() });
        if (!accRes.ok) return;
        const acc = await accRes.json();
        if (!acc.is_active) {
            await fetch(`${API}/api/trial`, { method: 'POST', headers: authHeaders() });
            await refreshAccount();
        }
    } catch(e) { /* ok */ }
}

async function refreshAccount() {
    if (!authToken) {
        hide(dom.accountBar);
        show(dom.btnAuth);
        dom.btnAuth.textContent = 'Free Trial';
        return;
    }
    try {
        const res = await fetch(`${API}/api/account`, { headers: authHeaders() });
        if (res.status === 401) {
            // Token expired
            clearAuth();
            hide(dom.accountBar);
            show(dom.btnAuth);
            return;
        }
        if (!res.ok) return;
        const acc = await res.json();

        show(dom.accountBar);
        hide(dom.btnAuth);
        let label = `${acc.pages_used} / ${acc.page_limit}`;
        if (acc.is_trial && acc.trial_active) {
            label += ` <span class="badge-trial">${acc.trial_days_left}d trial</span>`;
        }
        dom.usageText.innerHTML = label;
    } catch(e) { /* ok */ }
}

async function startSubscription() {
    if (!authToken) { showLogin(); return; }
    try {
        const res = await fetch(`${API}/api/subscribe`, {
            method: 'POST',
            headers: authHeaders(),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Checkout failed' }));
            throw new Error(err.detail);
        }
        const data = await res.json();
        if (data.url) {
            window.location.href = data.url;
        } else if (data.demo_mode) {
            await refreshAccount();
            updateProNote();
        }
    } catch(err) {
        showError(err.message);
    }
}

async function manageSubscription() {
    if (appConfig.demo_mode) { alert('Demo mode — management simulated.'); return; }
    try {
        const res = await fetch(`${API}/api/manage-subscription`, {
            method: 'POST',
            headers: authHeaders(),
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data.portal_url) window.location.href = data.portal_url;
    } catch(e) { /* ok */ }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showOnly(section) {
    ['uploadSection','fileSection','processSection','resultSection','errorSection'].forEach(s => {
        if (s === section) show(dom[s]); else hide(dom[s]);
    });
}

function showProcessing(title, msg) {
    dom.processingTitle.textContent = title;
    dom.processingMsg.textContent   = msg;
    dom.progressBar.style.width     = '0%';
    showOnly('processSection');
}

function showError(msg) {
    dom.errorMsg.textContent = msg;
    showOnly('errorSection');
}

function resetUpload() {
    currentJobId     = null;
    currentPageCount = 0;
    dom.fileInput.value          = '';
    dom.progressBar.style.width  = '0%';
    showOnly('uploadSection');
}

function simulateProgress(durationMs) {
    const start  = Date.now();
    const maxW   = 90;
    const iv = setInterval(() => {
        const pct = Math.min((Date.now() - start) / durationMs * maxW, maxW);
        dom.progressBar.style.width = pct + '%';
        if (pct >= maxW) clearInterval(iv);
    }, 200);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
init();
