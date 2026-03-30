# Uporabniški vodič

Ta aplikacija omogoča pregled turističnih kazalnikov za slovenske občine, destinacije, makro destinacije in turistične regije.

Namenjena je hitremu pregledu:

- stanja izbranega območja
- primerjave z drugimi območji
- zemljevida izbranega kazalnika
- najboljših in najslabših kazalnikov po skupinah
- AI komentarja in priporočil
- strukture prenočitev po trgih

## Prijava

Ob odprtju aplikacije se prikaže prijavno okno:

- `Prijava`
- vnosno polje `Geslo`
- gumb `Vstopi`

Za dostop vnesite pravilno geslo.

## Glavni deli aplikacije

Aplikacija ima dva glavna zavihka:

- `Kazalniki`
- `Struktura prenočitev po trgih`

## Zavihek `Kazalniki`

V tem zavihku lahko:

1. izberete `Pogled`
2. izberete območje
3. izberete skupino kazalnikov s slikovnimi gumbi
4. izberete `Kazalnik za zemljevid`
5. po potrebi vključite dodatne kazalnike za dashboard

### Kaj prikazuje zavihek

- povzetek izbranega območja
- primerjavo s Slovenijo
- zemljevid kazalnika
- tabelo območij ali občin
- najboljše in najslabše kazalnike po posameznih skupinah
- AI komentar in priporočila za izbrano območje

### Skupine kazalnikov

Kazalniki so razdeljeni v skupine:

- `Družbeni kazalniki`
- `Okoljski kazalniki`
- `Ekonomski nastanitveni in tržni turistični kazalniki`
- `Ekonomsko poslovni kazalniki turistične dejavnosti`

Vsaka skupina ima svojo ločeno top/bottom analizo.

## Zavihek `Struktura prenočitev po trgih`

V tem zavihku lahko:

- izberete leto
- izberete pogled območij
- izberete območje
- pregledate strukturo prenočitev po trgih

Prikazana sta:

- tortni prikaz
- tabela deležev po trgih

Pri pogledu občin znotraj območja lahko dodatno izberete posamezno občino.

## Kako uporabljati aplikacijo

### Za splošno primerjavo območij

1. V zavihku `Kazalniki` izberite `Pogled`.
2. Pri izboru območja izberite `Vsa območja`.
3. Izberite skupino kazalnikov.
4. Izberite kazalnik za zemljevid.
5. Preglejte zemljevid in tabelo območij.

### Za analizo posameznega območja

1. Izberite želeno območje.
2. Izberite skupino kazalnikov.
3. Izberite glavni kazalnik za zemljevid.
4. Preglejte KPI prikaz, zemljevid, tabelo občin in top/bottom analizo.
5. Na dnu preberite `AI komentar in priporočila za območje`.

## AI komentar

AI komentar temelji na vseh top/bottom rezultatih po skupinah kazalnikov.

To pomeni, da komentar upošteva:

- družbene kazalnike
- okoljske kazalnike
- nastanitvene in tržne kazalnike
- poslovne kazalnike turistične dejavnosti

Če AI klic ni na voljo, aplikacija samodejno prikaže rezervni komentar.

## Opombe pri interpretaciji

- Pri nekaterih kazalnikih je nižja vrednost boljša od višje.
- Nekateri kazalniki so iz top/bottom analize namenoma izločeni.
- Kumulativni kazalniki niso primerjani samo po velikosti, ampak na način, ki zmanjša vpliv velikosti območja.
- Pri določenih ekonomskih in poslovnih kazalnikih se lahko prikaže dodatno opozorilo glede interpretacije.

## Nalaganje lastnih podatkov

V levi stranski vrstici lahko po želji naložite:

- svoj Excel z indikatorji
- svoj GeoJSON

Če datotek ne naložite, aplikacija uporabi privzete podatke iz projekta.

## Najpogostejše težave

### Ne morem vstopiti v aplikacijo

Preverite, ali je geslo pravilno.

### Ne vidim zemljevida

Možno je, da manjka GeoJSON datoteka ali pa se imena občin ne ujemajo pravilno.

### AI komentar se ne prikaže

V tem primeru aplikacija običajno prikaže rezervni komentar. Razlog je lahko manjkajoč API ključ ali težava pri AI klicu.

### Kazalnik manjka

Kazalnik morda ni vključen v trenutno izbrano skupino ali pa ni pravilno vpisan v vhodnih podatkih.

## Za skrbnike projekta

Za tehnične podrobnosti, strukturo kode, dodajanje novih kazalnikov in nastavitve okolja glejte glavni [README](./README.md).

