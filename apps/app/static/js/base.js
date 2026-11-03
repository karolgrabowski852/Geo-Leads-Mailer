document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-translate-error]').forEach(element => {
        element.textContent = translateMessage(element.textContent);
    });

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

function translateMessage(message) {
    if (typeof message !== 'string') return message;

    const text = message.trim();
    const translations = {
        'Login required': 'Zaloguj się, aby kontynuować.',
        'Authentication required': 'Wymagane uwierzytelnienie.',
        'Invalid credentials': 'Nieprawidłowa nazwa użytkownika lub hasło.',
        'This account is not a superuser.': 'To konto nie ma uprawnień administratora.',
        'Invalid input': 'Nieprawidłowe dane.',
        'Invalid search data.': 'Nieprawidłowe dane wyszukiwania.',
        'The polygon coordinates must be a list of points.': 'Współrzędne poligonu muszą być listą punktów.',
        'The polygon must be a list of points.': 'Poligon musi być listą punktów.',
        'The polygon must contain at least 3 points.': 'Poligon musi zawierać co najmniej 3 punkty.',
        'The polygon contains too many points.': 'Poligon zawiera zbyt wiele punktów.',
        'Invalid polygon point format.': 'Nieprawidłowy format punktu poligonu.',
        'Each polygon point must contain `lat` and `lng`.': 'Każdy punkt poligonu musi zawierać `lat` i `lng`.',
        'Polygon coordinates must be numbers.': 'Współrzędne poligonu muszą być liczbami.',
        'Polygon coordinates are out of range.': 'Współrzędne poligonu są poza zakresem.',
        'Invalid polygon coordinate format.': 'Nieprawidłowy format współrzędnych poligonu.',
        'Choose a category from the list.': 'Wybierz kategorię z listy.',
        'Enter a custom category.': 'Wpisz własną kategorię.',
        'A category must contain letters or numbers.': 'Kategoria musi zawierać litery lub cyfry.',
        'The category contains invalid characters.': 'Kategoria zawiera niedozwolone znaki.',
        'Choose a search category.': 'Wybierz kategorię wyszukiwania.',
        'Could not read the search cache.': 'Nie można odczytać pamięci podręcznej wyszukiwania.',
        'Map search is busy. Please try again shortly.': 'Wyszukiwarka map jest zajęta. Spróbuj ponownie za chwilę.',
        'Could not safely start the map search.': 'Nie można bezpiecznie rozpocząć wyszukiwania na mapie.',
        'Could not connect to OpenStreetMap. Please try again later.': 'Nie można połączyć się z OpenStreetMap. Spróbuj ponownie później.',
        'OpenStreetMap returned an invalid response.': 'OpenStreetMap zwrócił nieprawidłową odpowiedź.',
        'The OpenStreetMap search exceeded the available limits. Draw a smaller area and try again.': 'Wyszukiwanie w OpenStreetMap przekroczyło dostępne limity. Zaznacz mniejszy obszar i spróbuj ponownie.',
        'OpenStreetMap is temporarily overloaded. Please try again later.': 'OpenStreetMap jest tymczasowo przeciążony. Spróbuj ponownie później.',
        'No exact OSM tag was found for this phrase. A text search by object name was performed.': 'Nie znaleziono dokładnego znacznika OSM dla tej frazy. Wykonano wyszukiwanie tekstowe według nazwy obiektu.',
        'Could not save search results. Please try again.': 'Nie udało się zapisać wyników wyszukiwania. Spróbuj ponownie.',
        'Results were saved, but email extraction could not be queued for some websites.': 'Wyniki zapisano, ale nie udało się dodać do kolejki pobierania adresów e-mail dla części stron.',
        'Select at least one valid email address.': 'Wybierz co najmniej jeden prawidłowy adres e-mail.',
        'Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET on the server.': 'Logowanie Google nie jest skonfigurowane. Skontaktuj się z administratorem.',
        'Google OAuth session expired. Please try again.': 'Sesja Google OAuth wygasła. Spróbuj ponownie.',
        'Google OAuth did not return an email address.': 'Google OAuth nie zwrócił adresu e-mail.',
        'An error occurred during OAuth authentication.': 'Wystąpił błąd podczas uwierzytelniania OAuth.',
        'Gmail token encryption is not configured on the server.': 'Szyfrowanie tokenu Gmail nie jest skonfigurowane. Skontaktuj się z administratorem.',
        'OAuth successful.': 'Autoryzacja OAuth zakończyła się pomyślnie.',
        'This field is required.': 'To pole jest wymagane.',
        'Enter a valid value.': 'Wprowadź prawidłową wartość.',
        'Enter a whole number.': 'Wprowadź liczbę całkowitą.',
        'Enter a valid email address.': 'Wprowadź prawidłowy adres e-mail.',
        'Select a valid choice.': 'Wybierz prawidłową opcję.'
    };

    if (Object.prototype.hasOwnProperty.call(translations, text)) {
        return translations[text];
    }

    const invalidEmail = text.match(/^Invalid email address: (.+)$/);
    if (invalidEmail) {
        return `Nieprawidłowy adres e-mail: ${invalidEmail[1]}`;
    }

    const categoryLength = text.match(/^A custom category can contain at most (\d+) characters\.$/);
    if (categoryLength) {
        return `Własna kategoria może mieć maksymalnie ${categoryLength[1]} znaków.`;
    }

    const overpassStatus = text.match(/^OpenStreetMap returned HTTP (\d+)\. Please try again later\.$/);
    if (overpassStatus) {
        return `OpenStreetMap zwrócił błąd HTTP ${overpassStatus[1]}. Spróbuj ponownie później.`;
    }

    if (/^Select a valid choice\..+is not one of the available choices\.$/.test(text)) {
        return 'Wybierz prawidłową opcję.';
    }

    const characterLimit = text.match(/^Ensure this value has at most (\d+) characters \(it has \d+\)\.$/);
    if (characterLimit) {
        return `Wartość może zawierać maksymalnie ${characterLimit[1]} znaków.`;
    }

    const minimumCharacters = text.match(/^Ensure this value has at least (\d+) characters \(it has \d+\)\.$/);
    if (minimumCharacters) {
        return `Wartość musi zawierać co najmniej ${minimumCharacters[1]} znaków.`;
    }

    if (text === 'Could not connect to the server.' || text === 'Failed to fetch') {
        return 'Nie udało się połączyć z serwerem.';
    }

    return text;
}

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
    msg = translateMessage(msg);

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