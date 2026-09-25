# ORSAY — lekki terminal internetowy

Polski terminal dla przeglądarki Samsung UE48H6400 (Orsay): natywny HTML, CSS i JavaScript ES5, Arial, granat i bursztyn. Nie wymaga widgetu Samsung, Node.js ani Reflex w wariancie samodzielnym. Komendy poniżej wykonuj w katalogu głównym repozytorium, nie wewnątrz `app`.

## Wymagania i instalacja

Python 3.13, dostęp do DNS i publicznego Internetu, aktualne certyfikaty CA. Telewizor musi mieć dostęp do komputera z usługą. Nie wyłączaj weryfikacji TLS. Minimalne zależności nie instalują frontendu ani bazy danych.

Linux/macOS:

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r app/requirements-proxy.txt
python -m app.terminal_server
```

Windows (PowerShell):

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r app\requirements-proxy.txt
.\.venv\Scripts\python.exe -m app.terminal_server
```

Aktywacja jest opcjonalna: `.\.venv\Scripts\Activate.ps1`, a następnie `python -m app.terminal_server`. Jeśli polityka PowerShell blokuje aktywację, użyj pełnych ścieżek powyżej, bez zmieniania polityki systemu.

Na komputerze otwórz `http://localhost:8080/terminal/`. Na telewizorze użyj adresu LAN tego komputera i portu 8080. Zapora powinna dopuszczać wyłącznie zaufane urządzenia. Serwer uruchamiany modułem nasłuchuje na wszystkich interfejsach; nie przekierowuj jego portu na routerze do publicznego Internetu.

## Uruchomienie usługi i HTTPS

Przykładowa komenda lokalnego procesu za reverse proxy:

```sh
python -m uvicorn app.terminal_server:server --host 127.0.0.1 --port 8080 --no-access-log --no-proxy-headers
```

Uruchamiaj jako nieuprzywilejowany użytkownik pod nadzorem menedżera usług systemu, z restartem po awarii i katalogiem roboczym repozytorium. Nie używaj `--reload`. Poniższy ogólny przykład Caddy używa fikcyjnej domeny; zastąp ją własną domeną z poprawnym DNS. Caddy uzyskuje certyfikat HTTPS automatycznie. Nie jest to konfiguracja żadnego istniejącego wdrożenia.

```text
terminal.example.org {
    reverse_proxy 127.0.0.1:8080
}
```

Nie dodawaj dyrektywy rejestrowania żądań ani cache. Dostęp ogranicz na zaporze lub prywatnej sieci/VPN; nie udostępniaj otwartego proxy. Utrzymaj przekazywanie całej ścieżki i query bez usuwania `/terminal` lub `/proxy`. Nie nadpisuj CSP odpowiedzi. Certyfikat wymaga rzeczywistej domeny i warunków wystawienia CA. Orsay może nie obsługiwać obecnych certyfikatów lub TLS: sprawdź na sprzęcie. Alternatywa to HTTP wyłącznie w odizolowanej, zaufanej sieci LAN, nigdy przez Internet. Nie osłabiaj TLS globalnie dla starego telewizora.

## Pliki projektu

- `app/__init__.py` — pakiet aplikacji.
- `app/app.py` — opcjonalny podgląd Reflex i adapter adresu terminala.
- `app/terminal_server.py` — niezależny serwer FastAPI i zasoby terminala.
- `app/proxy.py` — pobieranie, walidacja, przepisywanie dokumentów i strony błędów.
- `app/static/__init__.py` — pakiet zasobów.
- `app/static/terminal.txt` — ekran startowy HTML.
- `app/static/controls.txt` — skrypt ES5.
- `app/static/styles.txt` — arkusz terminala; pliki TXT są wysyłane jako HTML/JS/CSS z właściwym MIME.
- `app/test_proxy.py`, `app/test_terminal.py` — testy jednostkowe i ASGI.
- `app/requirements-proxy.txt` — minimalne zależności wariantu samodzielnego.
- `app/README.md`, `app/TERMINAL.md` — instrukcje i obsługa.
- `requirements.txt`, `rxconfig.py` — zależności i ustawienia opcjonalnego podglądu Reflex.
- `assets/` (`__init__.py`, `favicon.ico`, `placeholder.svg`) — zasoby podglądu.
- `reflex.lock/` (`__init__.py`, `package.json`, `bun.lock`) — pliki zależności podglądu.
- `apt-packages.txt` — lista dodatkowych pakietów systemowych.
- `plan.md`, `wireframe.json` — materiały projektu.

Podgląd na współczesnym komputerze: zainstaluj `python -m pip install -r requirements.txt`, potem `reflex run`. Na TV otwieraj bezpośrednio terminal, nie powłokę Reflex.

## Nawigacja i błędy

Każdy dokument HTML proxy zaczyna się paskiem nawigacji i formularzem aktualnego adresu docelowego (po przekierowaniach). Link prowadzi zwykłym GET do kolejnego `/proxy?url=...`. Wstecz i Dalej wywołują historię przeglądarki, Odśwież przeładowuje dokument. Nie ma historii po stronie serwera, routera SPA, fetch, Promise ani pamięci localStorage/sessionStorage. Ponowienie błędu to zwykły link do tego samego adresu. Brak wpisu historii oznacza brak działania Wstecz/Dalej.

Adres bez schematu dostaje HTTPS przez skrypt. Bez JS wymagany jest pełny adres. Serwer niezależnie waliduje każde żądanie. Błędy mają pełny polski dokument z zachowanym statusem HTTP: 400 niepoprawny adres, 403 blokada lub autoryzacja, 413 rozmiar, 415 typ/kodowanie, 502 pobranie/DNS/przekierowania, 504 czas oczekiwania. Opis nie ujawnia diagnostyki. Kontrolowane błędy nie generują tracebacków; nieoczekiwane awarie mogą trafiać do diagnostyki procesu.

## Bezpieczeństwo, prywatność i ograniczenia

- Wyłącznie publiczne HTTP/HTTPS na portach 80/443. Blokowane są m.in. localhost, adresy prywatne, link-local, zarezerwowane i niepubliczne odpowiedzi DNS. Każde przekierowanie jest ponownie sprawdzane; połączenie przypięte do sprawdzonego IP zachowuje Host i TLS SNI. Nie zmieniaj tych zabezpieczeń dla wygody.
- Maksymalnie 4 MiB na zasób, 5 przekierowań, ograniczone czasy połączenia i całego pobrania. Duże i nietypowe zasoby są odrzucane.
- Skrypty, osadzone ramki i aktywne elementy stron są usuwane. CSP dopuszcza własny skrypt terminala oraz własne arkusze; zdalne style i style inline dokumentu są usuwane, aby nie przykrywały paska. Bezpieczeństwo nie opiera się wyłącznie na CSP, którego stary TV może nie wspierać. Treść stron nie jest zaufana.
- Endpoint nadal obsługuje CSS i obrazy jako zasoby. Nie zapewnia pełnego wyglądu stron. Brak JS stron zdalnych, logowania, sesji, POST i pełnej zgodności z dynamicznymi witrynami. Zdalne formularze GET nie są pełną obsługą wyszukiwarek. Wideo, DRM, aplikacje SPA i część formatów obrazów nie będą działać.
- Proxy nie przekazuje Cookie, Authorization ani Referer klienta i nie zwraca Set-Cookie źródła. Nie przechowuje historii, kont, bazy, plików użytkowników ani trwałego cache. Dane są przetwarzane przejściowo w RAM; odpowiedzi mają `no-store`.
- Historia i adresy mogą pozostać na TV; URL znajduje się w query. Nie wpisuj sekretów ani danych osobowych. Serwer źródłowy widzi IP proxy. DNS, operator i dodatkowa infrastruktura mogą mieć własne logi; brak zapisu w aplikacji nie oznacza anonimowości. Wyłącz logi dostępu także na pośrednikach i u operatora; nie włączaj diagnostyki HTTP z pełnymi adresami.

## Weryfikacja

```sh
python -m unittest app.test_terminal app.test_proxy -v
```

Testy używają kontrolowanych odpowiedzi sieciowych: sprawdzają przepisywanie linku do kolejnego dokumentu, aktualny adres, sanitację, polskie błędy i statusy, CSP, zasoby ES5, brak sesji i blokady SSRF. Nie zastępują uruchomienia w przeglądarce. W tej zmianie nie wykonano testów automatycznych ani testu fizycznego urządzenia.

### Checklista Samsung UE48H6400

- [ ] Zanotuj wersję firmware; otwórz bezpośrednio `/terminal/`, nie podgląd Reflex.
- [ ] Przy 1280×720 i ustawieniach overscan sprawdź czytelność Arial, cały pasek, brak obcięcia kontrolek i mocny bursztynowy fokus.
- [ ] Pilot: strzałki, OK/Enter, klawiatura ekranowa, kursor wewnątrz adresu; z klawiaturą także Tab/Shift+Tab. Poza paskiem nawigacja treści pozostaje natywna dla TV.
- [ ] Otwórz publiczną prostą stronę przez HTTP i HTTPS; adres bez schematu, pusty adres i błędny schemat.
- [ ] Przejdź linkiem na drugą stronę; sprawdź aktualny URL, Wstecz, Dalej, Odśwież oraz Strona główna; powtórz po błędzie.
- [ ] Sprawdź query zawierające `?a=1&b=2`, względny link, kotwicę i przekierowanie do innej ścieżki.
- [ ] Sprawdź 403 dla localhost i adresu prywatnego, duży status, polski opis, poprawienie adresu i Spróbuj ponownie.
- [ ] Sprawdź obrazy, polskie znaki, długą treść i przewijanie. Pasek jest pierwszy w dokumencie, nie przyklejony do ekranu.
- [ ] Wyłącz JS: pełny adres i formularz muszą działać, historia przez przyciski samej przeglądarki.
- [ ] Sprawdź TLS/certyfikat na TV, brak sesji logowania i brak błędów skryptu przy powrocie ze strony błędu.
- [ ] Zamknij przeglądarkę, sprawdź jej historię oraz zasady prywatności urządzenia. Potwierdź brak logów dostępu pośredników.

Zgodność konkretnego firmware jest potwierdzona dopiero po przejściu tej listy na fizycznym telewizorze.
