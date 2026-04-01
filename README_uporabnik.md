# Uporabniški vodič

Aplikacija je namenjena pregledu turističnih kazalnikov za slovenske občine, destinacije, turistične regije in makro destinacije.

Omogoča:

- pregled stanja izbranega območja
- primerjavo z drugimi območji in s Slovenijo
- zemljevid izbranega kazalnika
- top/bottom analizo po skupinah kazalnikov
- AI komentar in priporočila
- pregled strukture prenočitev po trgih

Za tehnične podrobnosti glejte glavni [README](./README.md).

## Prijava

Ob odprtju aplikacije se prikaže prijavno okno:

- `Prijava`
- polje `Geslo`
- gumb `Vstopi`

Za uporabo aplikacije je potrebno pravilno geslo.

## Glavna zavihka

Aplikacija ima dva glavna zavihka:

- `Kazalniki`
- `Struktura prenočitev po trgih`

## Zavihek `Kazalniki`

V tem zavihku lahko:

1. izberete `Pogled`
2. izberete območje ali `Vsa območja`
3. izberete skupino kazalnikov s slikovnimi gumbi
4. izberete `Kazalnik za zemljevid`
5. po želji dodate do 6 kazalnikov v dashboard prikaz

### Kaj je prikazano

- povzetek izbranega območja
- primerjava s Slovenijo
- zemljevid izbranega kazalnika
- tabela območij ali občin
- najboljši in najslabši kazalniki po posameznih skupinah
- AI komentar in priporočila za izbrano območje

### Skupine kazalnikov

Top/bottom analiza je ločena po skupinah:

- `Družbeni kazalniki`
- `Okoljski kazalniki`
- `Ekonomski nastanitveni in tržni turistični kazalniki`
- `Ekonomsko poslovni kazalniki turistične dejavnosti`

Vsaka skupina ima svojo ločeno razvrstitev.

## Kako deluje top/bottom analiza

Aplikacija ne primerja vseh kazalnikov na enak način.

### Kumulativni kazalniki

Pri seštevnih kazalnikih, kot so:

- prenočitve
- prihodi turistov
- kapacitete
- število obratov

se regija ne primerja samo po absolutni velikosti. Namesto tega se primerja:

- delež regije v Sloveniji pri izbranem kazalniku
- proti ustrezni referenčni osnovi

Primer:

- prenočitve se primerjajo glede na delež stalnih ležišč
- kampi se primerjajo glede na delež vseh nastanitvenih obratov
- skupne kapacitete se primerjajo glede na delež prebivalstva

Tako velikost regije ne izkrivlja rezultatov.

### Ostali kazalniki

Pri kazalnikih, ki niso seštevni, se uporablja neposredni odmik od vrednosti Slovenije.

To velja na primer za:

- deleže
- povprečja
- indekse
- različne izračunane stopnje

### Končna razvrstitev

Končna top/bottom razvrstitev upošteva tudi to, kako zelo kazalnik odstopa glede na običajen razpon med primerljivimi območji iste ravni.

To pomeni:

- kazalniki različnih vrst so primerjani bolj pošteno
- en sam kazalnik ne prevlada samo zato, ker ima večjo številčno skalo

## Zavihek `Struktura prenočitev po trgih`

V tem zavihku lahko:

- izberete leto
- izberete pogled območij
- izberete območje
- pregledate strukturo prenočitev po trgih

Prikazana sta:

- tortni prikaz
- tabela deležev po trgih

## Kako uporabljati aplikacijo

### Za splošno primerjavo območij

1. V zavihku `Kazalniki` izberite `Pogled`.
2. Kot območje izberite `Vsa območja`.
3. Izberite skupino kazalnikov.
4. Izberite kazalnik za zemljevid.
5. Preglejte zemljevid in tabelo območij.

### Za analizo posameznega območja

1. Izberite želeno območje.
2. Izberite skupino kazalnikov.
3. Izberite glavni kazalnik za zemljevid.
4. Preglejte KPI prikaz, zemljevid in tabelo občin.
5. Preberite top/bottom analizo po skupinah.
6. Na dnu preberite `AI komentar in priporočila za območje`.

## AI komentar

AI komentar temelji na vseh top/bottom rezultatih po skupinah kazalnikov skupaj.

To pomeni, da komentar upošteva:

- družbene kazalnike
- okoljske kazalnike
- nastanitvene in tržne kazalnike
- poslovne kazalnike turistične dejavnosti

Če AI klic ni na voljo, aplikacija prikaže rezervni komentar. Če je v projektu nastavljen podatkovni cache, se ob enakih vhodnih podatkih že ustvarjen AI komentar ponovno uporabi.

## Nalaganje lastnih datotek

V levi stranski vrstici lahko po želji naložite:

- svoj Excel z indikatorji
- svoj GeoJSON

Če tega ne storite, aplikacija uporabi privzete datoteke iz projekta.

## Opombe pri interpretaciji

- Pri nekaterih kazalnikih je nižja vrednost boljša od višje.
- Nekateri kazalniki so iz top/bottom analize namenoma izločeni.
- Slovenija se uporablja kot osnovna primerjalna referenca.
- Pri določenih ekonomskih in poslovnih kazalnikih se lahko prikaže dodatno opozorilo glede interpretacije.

## Najpogostejše težave

### Ne morem vstopiti v aplikacijo

Preverite, ali je geslo pravilno.

### Ne vidim zemljevida

Možno je, da manjka GeoJSON ali pa se imena občin ne ujemajo dovolj natančno z vhodnimi podatki.

### AI komentar se ne prikaže

Če AI ni na voljo, aplikacija praviloma prikaže rezervni komentar. Razlog je lahko manjkajoč API ključ, izčrpana kvota ali težava pri klicu.

### Kazalnik manjka

Kazalnik morda:

- ni v izbrani skupini
- ni pravilno zapisan v vhodnih podatkih
- je namenoma izločen iz top/bottom analize
