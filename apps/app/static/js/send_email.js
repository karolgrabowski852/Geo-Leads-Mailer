const searchSelect = document.getElementById('searches');
const companySelect = document.getElementById('reciver');
const selectAllSearchesBtn = document.getElementById('selectAllSearches');
const selectAllCompaniesBtn = document.getElementById('selectAllCompanies');
const summarySearches = document.getElementById('summarySearches');
const summaryCompanies = document.getElementById('summaryCompanies');
const summaryFiles = document.getElementById('summaryFiles');
const fileInput = document.getElementById('attachments');
const fileList = document.getElementById('fileList');
const dropZone = document.getElementById('dropZone');
const clearBtn = document.getElementById('clearBtn');
const submitBtn = document.getElementById('submitBtn');
const customEmailsInput = document.getElementById('customEmails');
const customValidSpan = document.getElementById('customEmailsValid');
const customInvalidSpan = document.getElementById('customEmailsInvalid');
const customChips = document.getElementById('customEmailsChips');

function clearSelect(el) { el.innerHTML = ''; }
function getSelectedValues(el) { return Array.from(el.selectedOptions).map(o => o.value); }

function extractEmails(raw) {
    if (!raw || typeof raw !== 'string') return [];
    const emailRe = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig;
    const badExt = /\.(png|jpg|jpeg|svg|gif|webp)$/i;
    const out = new Set();
    for (const email of raw.match(emailRe) || []) {
        if (!badExt.test(email)) out.add(email.toLowerCase());
    }
    return Array.from(out);
}

function parseCustomEmails() {
    const raw = customEmailsInput.value;
    const splitted = raw.split(/[\s,;]+/).filter(Boolean);
    const emailRe = /^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i;
    const valid = [];
    const invalid = [];
    const seen = new Set();

    for (const token of splitted) {
        const t = token.trim();
        if (!t) continue;
        if (emailRe.test(t) && !seen.has(t.toLowerCase())) {
            valid.push(t.toLowerCase());
            seen.add(t.toLowerCase());
        } else if (!emailRe.test(t)) {
            invalid.push(t);
        }
    }

    customValidSpan.textContent = valid.length;
    customInvalidSpan.textContent = invalid.length;
    customChips.innerHTML = '';

    valid.forEach(v => {
        const span = document.createElement('span');
        span.className = 'px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300 text-[11px]';
        span.textContent = v;
        customChips.appendChild(span);
    });

    if (invalid.length) {
        invalid.slice(0, 5).forEach(iv => {
            const span = document.createElement('span');
            span.className = 'px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300 text-[11px]';
            span.textContent = iv;
            customChips.appendChild(span);
        });
    }
    return valid;
}

customEmailsInput?.addEventListener('input', parseCustomEmails);

function updateSummary() {
    summarySearches.textContent = getSelectedValues(searchSelect).length;
    summaryCompanies.textContent = getSelectedValues(companySelect).length;
    summaryFiles.textContent = fileInput.files.length;
}

searchSelect.addEventListener('change', async () => {
    clearSelect(companySelect);
    const searchIds = getSelectedValues(searchSelect);
    if (searchIds.length === 0) {
        updateSummary();
        return;
    }

    const seen = new Set();
    for (const searchId of searchIds) {
        const resp = await fetch(`/get_companies_for_search?search_id=${encodeURIComponent(searchId)}`);
        const data = await resp.json();
        (data.companies || []).forEach(c => {
            extractEmails(c.email).forEach(em => {
                if (!seen.has(em)) seen.add(em);
            });
        });
    }

    Array.from(seen).forEach(em => {
        const opt = document.createElement('option');
        opt.value = em;
        opt.textContent = em;
        companySelect.appendChild(opt);
    });
    updateSummary();
});

// Przyciski „Wybierz wszystkie”
selectAllSearchesBtn.addEventListener('click', () => {
    Array.from(searchSelect.options).forEach(o => o.selected = true);
    searchSelect.dispatchEvent(new Event('change'));
});

selectAllCompaniesBtn.addEventListener('click', () => {
    Array.from(companySelect.options).forEach(o => o.selected = true);
    updateSummary();
});

// Przeciąganie i upuszczanie plików
fileInput.addEventListener('change', () => {
    fileList.innerHTML = '';
    Array.from(fileInput.files).forEach(f => {
        const li = document.createElement('li');
        li.className = 'flex items-center gap-2 text-slate-600 dark:text-slate-300';
        const name = document.createElement('span');
        name.className = 'truncate max-w-[160px]';
        name.textContent = f.name;
        const size = document.createElement('span');
        size.className = 'text-[10px] text-slate-400';
        size.textContent = `${(f.size / 1024).toFixed(1)} KB`;
        li.append(name, size);
        fileList.appendChild(li);
    });
    updateSummary();
});

['dragenter', 'dragover'].forEach(evt => dropZone.addEventListener(evt, e => {
    e.preventDefault();
    dropZone.classList.add('ring-2', 'ring-brand-500/60');
}));

['dragleave', 'drop'].forEach(evt => dropZone.addEventListener(evt, e => {
    e.preventDefault();
    dropZone.classList.remove('ring-2', 'ring-brand-500/60');
}));

dropZone.addEventListener('drop', e => {
    const dt = e.dataTransfer;
    if (!dt?.files?.length) return;
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event('change'));
});

clearBtn.addEventListener('click', () => {
    Array.from(searchSelect.options).forEach(o => o.selected = false);
    clearSelect(companySelect);
    fileInput.value = '';
    fileList.innerHTML = '';
    updateSummary();
});

companySelect.addEventListener('change', updateSummary);

document.getElementById('sendEmailForm').addEventListener('submit', e => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.classList.add('cursor-wait');
    const original = submitBtn.querySelector('span').textContent;
    submitBtn.querySelector('span').textContent = 'Dodawanie do kolejki...';

    const form = e.currentTarget;
    const recipients = Array.from(companySelect.selectedOptions).map(o => o.value);
    const custom = parseCustomEmails();

    custom.forEach(c => {
        if (!recipients.includes(c)) recipients.push(c);
    });

    const fd = new FormData(form);
    fd.delete('reciver');
    recipients.forEach(r => fd.append('recipients[]', r));

    fetch('/send_email', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': getCsrfToken() }
    })
        .then(async response => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || 'Nie udało się dodać wiadomości do kolejki.');
            }
            return data;
        })
        .then(data => {
            pushToast(`Dodano do kolejki ${data.queued} wiadomości. Odstęp: ${data.delay_min} min`, 'success');
        })
        .catch(err => {
            pushToast('Błąd: ' + translateMessage(err.message), 'error');
        })
        .finally(() => {
            submitBtn.disabled = false;
            submitBtn.classList.remove('cursor-wait');
            submitBtn.querySelector('span').textContent = original;
        });
});