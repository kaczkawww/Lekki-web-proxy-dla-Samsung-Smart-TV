# Terminal Orsay — obsługa

Samodzielny interfejs korzysta z natywnego HTML, CSS oraz JavaScript ES5. Nie ładuje bibliotek klienta, zewnętrznych fontów ani zasobów z innych serwisów. Pliki w katalogu static mają rozszerzenie .txt; serwer wysyła je z właściwymi typami HTML, CSS i JavaScript.

Uruchomienie samodzielnego interfejsu: `python -m app.terminal_server`. Otwórz port 8080 w przeglądarce; dokument startowy dostępny jest pod `/` i `/terminal/`. To wariant przeznaczony do otwarcia bezpośrednio na telewizorze — nie wymaga klienta Reflex. Standardowy start projektu Reflex zachowano jako adapter podglądu; jego zewnętrzna powłoka wymaga nowoczesnej przeglądarki i nie jest wariantem dla Orsay.

## Obsługa

- Pole adresu otrzymuje fokus po otwarciu. Tab i Shift+Tab zachowują natywne działanie.
- Strzałki przełączają kontrolki. W polu adresu lewo/prawo przesuwają kursor; przy granicy tekstu mogą przenieść fokus. Góra przenosi do paska nawigacji. Na silnikach bez informacji o pozycji kursora użyj góry lub Tab, aby opuścić pole.
- Enter/OK zatwierdza adres lub uruchamia zaznaczony przycisk. Obsługiwane są standardowe kody klawiatury 37–40 i 13. Nie jest wymagana instalacja widgetu Samsung ani rejestracja klawiszy przez API producenta.
- Formularz wysyła zwykły GET do `/proxy` z parametrem `url`. Pełne adresy HTTP/HTTPS są zachowywane; przy braku schematu dodawane jest HTTPS. Podstawowa kontrola adresu nie jest zabezpieczeniem serwerowego proxy.
- Bez JavaScript formularz nadal działa: trzeba wpisać pełny adres HTTP/HTTPS. Nawigacja historii wymaga JavaScript.
- Wstecz i Dalej korzystają wyłącznie z historii bieżącego okna, Odśwież przeładowuje dokument, Strona główna prowadzi do terminala. Przy braku odpowiedniego wpisu historii przyciski nie zmienią strony.

## Przeglądanie

Endpoint `/proxy` pobiera publiczne strony i przepisuje linki. Każdy dokument HTML zawiera najpierw zwarty pasek i bieżący adres, następnie treść. Zdalne skrypty i style dokumentu są usuwane; terminal pozostaje czytelny. Strona błędu zachowuje status HTTP, pasek oraz akcje Spróbuj ponownie i Strona główna. Nie ma przechowywania historii, analityki ani pamięci lokalnej aplikacji. Przeglądarka może zapisywać własną historię. Nie przekazuj w URL informacji poufnych.

Instalacja samodzielna bez Reflex, uruchomienie, ogólny przykład HTTPS, opis plików, bezpieczeństwo i checklista sprzętowa: [README](README.md).

## Sprawdzenie

Testy źródeł i odpowiedzi: `python -m unittest app.test_terminal app.test_proxy -v`.

Sprawdź ręcznie widok 1280×720, fokus, każdą strzałkę, Enter, Tab, pusty adres, adres bez schematu, HTTP, HTTPS i odrzucony schemat javascript:. Dla adresu zawierającego `?a=1&b=2` oba parametry powinny pozostać częścią pojedynczego parametru url. Sprawdź formularz z wyłączonym JavaScript oraz powrót przeglądarką ze strony błędu oraz przejście linkiem między dwiema stronami proxy.

Zgodność konkretnego firmware i klawiatury ekranowej wymaga sprawdzenia na fizycznym Samsung Orsay; testy źródeł nie zastępują testów sprzętowych. Nie wykonano takiej weryfikacji na urządzeniu. Instrukcje testowe nie są deklaracją zaliczenia testów.
