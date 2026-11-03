document.addEventListener('DOMContentLoaded', () => {
    const path = location.pathname.replace(/\/$/, '');
    document.querySelectorAll('nav a.nav-link').forEach(a => {
        if (a.getAttribute('href').replace(/\/$/, '') === path) {
            a.classList.add('active', 'text-slate-900', 'dark:text-white');
        }
    });

    document.getElementById('themeToggle')?.addEventListener('click', () => {
        const dark = document.documentElement.classList.contains('dark');
        setTheme(dark ? 'light' : 'dark');
    });
});

// Token CSRF: najpierw ukryte pole formularza, w ostatecznosci ciasteczko
// (CSRF_COOKIE_HTTPONLY = False, wiec jest czytelne dla JS).
function getCsrfToken() {
    const field = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (field?.value) return field.value;

    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
}

function pushToast(msg, type = 'info', ttl = 4200) {
    const host = document.getElementById('toastHost');
    if (!host) return;

    const colors = {
        info: 'bg-slate-800 text-white',
        success: 'bg-emerald-600 text-white',
        error: 'bg-rose-600 text-white',
        warn: 'bg-amber-500 text-slate-900'
    };

    const el = document.createElement('div');
    el.className = `pointer-events-auto shadow-soft rounded-md px-4 py-3 text-sm font-medium flex items-start gap-3 w-full sm:w-auto max-w-sm ${colors[type] || colors.info}`;
    el.innerHTML = `
        <span class='flex-1 leading-snug'>${msg}</span>
        <button class='shrink-0 opacity-70 hover:opacity-100 transition' aria-label='Close'>&times;</button>
    `;

    const close = () => {
        el.classList.add('animate-fade-out');
        setTimeout(() => el.remove(), 280);
    };

    el.querySelector('button').addEventListener('click', close);
    host.appendChild(el);
    setTimeout(close, ttl);
}