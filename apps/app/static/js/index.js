document.addEventListener('DOMContentLoaded', function() {
    const polygonInput = document.getElementById('polygon_coords');
    const form = document.getElementById('searchForm');
    const categorySelect = document.getElementById('category');
    const customCategoryInput = document.getElementById('customCategory');
    const submitBtn = document.getElementById('submitBtn');
    const submitBtnText = document.getElementById('submitBtnText');
    const searchProgress = document.getElementById('searchProgress');
    const searchProgressMessage = document.getElementById('searchProgressMessage');
    const resultsPanel = document.getElementById('searchResultsPanel');
    const resultsList = document.getElementById('searchResultsList');
    const resultsCount = document.getElementById('resultsCount');
    const resultsMeta = document.getElementById('resultsMeta');
    const resetBtn = document.getElementById('resetBtn');

    if (
        !form
        || !polygonInput
        || !categorySelect
        || !customCategoryInput
        || !searchProgress
        || !searchProgressMessage
        || !resetBtn
    ) {
        return;
    }

    let drawnItems = null;
    const updateCustomCategoryVisibility = () => {
        const isCustom = categorySelect.value === 'custom';
        customCategoryInput.classList.toggle('hidden', !isCustom);
        customCategoryInput.required = isCustom;
    };

    categorySelect.addEventListener('change', updateCustomCategoryVisibility);
    updateCustomCategoryVisibility();

    const tileProviders = [
        {
            url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            options: {
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 19
            }
        },
        {
            url: 'https://{s}.tile.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
            options: {
                attribution: '&copy; OpenStreetMap, &copy; CartoDB',
                subdomains: 'abcd',
                maxZoom: 20
            }
        },
        {
            url: 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
            options: {
                attribution: '&copy; OpenStreetMap contributors',
                subdomains: 'abc',
                maxZoom: 19
            }
        }
    ];

    if (typeof L !== 'undefined') {
        const mapElement = document.getElementById('map');
        if (mapElement) {
            // Inicjalizacja mapy
            const map = L.map(mapElement).setView([52.23, 21.01], 12); // Srodek na Warszawe

            let providerIndex = 0;
            let tileLayer = null;
            let fallbackCount = 0;

            const setTileLayer = () => {
                if (tileLayer) {
                    map.removeLayer(tileLayer);
                }

                const provider = tileProviders[providerIndex];
                console.info('Leaflet tile provider:', provider.url);
                tileLayer = L.tileLayer(provider.url, provider.options);
                tileLayer.on('loading', () => {
                    console.info('Leaflet tiles loading...');
                });
                tileLayer.on('tileerror', () => {
                    if (providerIndex < tileProviders.length - 1) {
                        fallbackCount += 1;
                        providerIndex += 1;
                        setTileLayer();
                        pushToast('Przelaczono na zapasowe zrodlo mapy.', 'warn');
                        return;
                    }
                    if (fallbackCount >= tileProviders.length - 1) {
                        pushToast(
                            'Nie mozna pobrac kafelkow mapy. Sprawdz internet lub blokady w przegladarce.',
                            'error'
                        );
                    }
                });
                tileLayer.addTo(map);
            };

            setTileLayer();
            setTimeout(() => map.invalidateSize(), 120);

            drawnItems = new L.FeatureGroup();
            map.addLayer(drawnItems);

            const drawControl = new L.Control.Draw({
                edit: { featureGroup: drawnItems },
                draw: {
                    polygon: true,
                    polyline: false,
                    rectangle: true,
                    circle: false,
                    marker: false,
                    circlemarker: false
                }
            });
            map.addControl(drawControl);

            const storePolygon = (layer) => {
                drawnItems.clearLayers(); // Tylko jeden obszar na raz
                drawnItems.addLayer(layer);
                const coords = layer.getLatLngs()[0].map(latlng => ({
                    lat: latlng.lat,
                    lng: latlng.lng
                }));
                polygonInput.value = JSON.stringify(coords);
            };

            map.on(L.Draw.Event.CREATED, function (event) {
                storePolygon(event.layer);
            });
            map.on(L.Draw.Event.EDITED, function (event) {
                const editedLayer = event.layers.getLayers()[0];
                if (editedLayer) {
                    storePolygon(editedLayer);
                }
            });
        }
    } else {
        pushToast('Nie mozna zaladowac bibliotek Leaflet.', 'error');
    }

    const extractPlaces = (payload) => {
        if (!payload || typeof payload !== 'object') {
            return [];
        }

        const firstKey = Object.keys(payload).find((key) => key.startsWith('polygon_search_'))
            || Object.keys(payload)[0];
        const placesMap = firstKey ? payload[firstKey] : null;

        if (!placesMap || typeof placesMap !== 'object') {
            return [];
        }

        return Object.values(placesMap);
    };

    const renderEmptyState = (queryText, searchMessage = '') => {
        resultsPanel.classList.remove('hidden');
        resultsCount.textContent = '0';
        resultsMeta.textContent = `Brak wynikow dla zapytania: ${queryText}${
            searchMessage ? ` — ${searchMessage}` : ''
        }`;
        resultsList.innerHTML = `
            <div class="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-3 text-sm text-slate-600 dark:text-slate-300">
                Nie znaleziono firm dla wybranego obszaru.
            </div>
        `;
    };

    const renderResults = (payload, queryText) => {
        const places = extractPlaces(payload);
        if (!places.length) {
            renderEmptyState(queryText, payload?.search_message || '');
            return 0;
        }

        resultsPanel.classList.remove('hidden');
        resultsCount.textContent = String(places.length);
        resultsMeta.textContent = `Zapytanie: ${queryText}${
            payload?.search_message ? ` — ${payload.search_message}` : ''
        }`;
        resultsList.innerHTML = '';

        places.forEach((place) => {
            const wrapper = document.createElement('article');
            wrapper.className = 'rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/60 p-4';

            const name = place?.name || place?.displayName?.text || 'Firma bez nazwy';
            const address = place?.address || place?.formattedAddress || 'Brak adresu';
            const phone = place?.phone || place?.nationalPhoneNumber || 'Brak numeru telefonu';
            const website = place?.website || place?.websiteUri || '';
            const email = place?.osm_email || '';

            const title = document.createElement('h4');
            title.className = 'text-sm font-semibold text-slate-900 dark:text-slate-100';
            title.textContent = name;

            const addressEl = document.createElement('p');
            addressEl.className = 'mt-2 text-xs text-slate-600 dark:text-slate-300';
            addressEl.textContent = address;

            const phoneEl = document.createElement('p');
            phoneEl.className = 'mt-1 text-xs text-slate-500 dark:text-slate-300';
            phoneEl.textContent = `Tel: ${phone}`;

            wrapper.appendChild(title);
            wrapper.appendChild(addressEl);
            wrapper.appendChild(phoneEl);

            if (email) {
                const emailEl = document.createElement('p');
                emailEl.className = 'mt-1 text-xs text-slate-500 dark:text-slate-300';
                emailEl.textContent = `E-mail z OSM: ${email}`;
                wrapper.appendChild(emailEl);
            }

            if (website) {
                const link = document.createElement('a');
                link.className = 'mt-2 inline-flex text-xs text-brand-600 hover:text-brand-700';
                link.href = website;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = 'Strona www';
                wrapper.appendChild(link);
            }

            resultsList.appendChild(wrapper);
        });

        return places.length;
    };

    // Obsługa Resetu
    resetBtn.addEventListener('click', () => {
        if (drawnItems) {
            drawnItems.clearLayers();
        }
        polygonInput.value = "";
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const coords = polygonInput.value;
        if (!coords) {
            pushToast("Prosze narysowac obszar na mapie.", "error");
            return;
        }

        if (!categorySelect.value) {
            pushToast("Wybierz kategorię firmy.", "error");
            return;
        }

        const queryText = categorySelect.value === 'custom'
            ? customCategoryInput.value.trim()
            : categorySelect.options[categorySelect.selectedIndex].text;
        if (categorySelect.value === 'custom' && !queryText) {
            pushToast("Wpisz własną kategorię.", "error");
            return;
        }

        try {
            const parsed = JSON.parse(coords);
            if (!Array.isArray(parsed) || parsed.length < 3) {
                pushToast("Poligon musi miec co najmniej 3 punkty.", "error");
                return;
            }
        } catch (_err) {
            pushToast("Niepoprawny format poligonu.", "error");
            return;
        }

        const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value
            || getCsrfToken();
        const formData = new FormData(form);
        let slowSearchTimer = null;

        form.setAttribute('aria-busy', 'true');
        searchProgress.classList.remove('hidden');
        searchProgressMessage.textContent =
            'Wyszukiwanie trwa. Pobieranie danych OpenStreetMap może chwilę potrwać.';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.classList.add('opacity-70', 'cursor-not-allowed');
            if (submitBtnText) {
                submitBtnText.textContent = 'Wyszukiwanie...';
            }
        }
        slowSearchTimer = window.setTimeout(() => {
            searchProgressMessage.textContent =
                'Wyszukiwanie nadal trwa. Usługa OpenStreetMap może być chwilowo obciążona.';
        }, 8000);

        try {
            const response = await fetch(window.location.pathname, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {})
                },
                body: formData
            });

            const payload = await response.json().catch(() => ({}));

            if (!response.ok) {
                const errorMessage = payload?.error || 'Wystapil blad podczas wyszukiwania.';
                pushToast(errorMessage, 'error');
                return;
            }

            const placesCount = renderResults(payload, queryText);
            if (payload?.search_warning) {
                pushToast(payload.search_warning, 'warn');
            }
            if (placesCount > 0) {
                pushToast('Wyszukiwanie zakonczone.', 'success');
            } else {
                pushToast('Brak wynikow dla wybranego zapytania.', 'warn');
            }
        } catch (_err) {
            pushToast('Nie udalo sie polaczyc z serwerem.', 'error');
        } finally {
            if (slowSearchTimer !== null) {
                window.clearTimeout(slowSearchTimer);
            }
            form.setAttribute('aria-busy', 'false');
            searchProgress.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.classList.remove('opacity-70', 'cursor-not-allowed');
                if (submitBtnText) {
                    submitBtnText.textContent = 'Uruchom wyszukiwanie';
                }
            }
        }
    });
});