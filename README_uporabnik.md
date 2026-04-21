# Uporabniški vodič

Aplikacija je namenjena pregledu turističnih kazalnikov za slovenske občine,
destinacije, turistične regije, makro destinacije in Slovenijo.

Omogoča:

- pregled kazalnikov za izbrano območje
- primerjavo območij med seboj in s Slovenijo
- prikaz kazalnikov na zemljevidu
- top/bottom analizo po skupinah kazalnikov
- pregled strukture in sezonskosti turističnega prometa po trgih
- AI komentar in priporočila, če je AI omogočen

Tehnična navodila za namestitev, uvoz podatkov in vzdrževanje so v
[README.md](./README.md).

## Prijava

Ob odprtju aplikacije se prikaže prijavni obrazec.

1. Vnesite geslo.
2. Kliknite `Vstopi`.

Če geslo ni pravilno, aplikacija ostane na prijavnem zaslonu.

## Glavna Zavihka

Aplikacija ima dva glavna zavihka:

- `Kazalniki`
- `Turistični promet in sezonskost po trgih`

## Stranska Vrstica

V stranski vrstici so osnovne nastavitve:

- nalaganje lastnega Excela
- nalaganje lastnega GeoJSON-a
- vklop/izklop dashboard načina

Če lastnih datotek ne naložite, aplikacija uporabi privzete podatke. Na strežniku so
ti podatki lahko prebrani iz podatkovne baze, če je aplikacija tako nastavljena.

## Zavihek Kazalniki

V tem zavihku lahko:

1. izberete pogled območij
2. izberete posamezno območje ali `Vsa območja`
3. izberete skupino kazalnikov
4. izberete kazalnik za zemljevid
5. primerjate območja v tabelah in grafih
6. pregledate top/bottom analizo
7. preberete AI komentar, če je na voljo

Pogledi območij so odvisni od stolpcev v podatkih. Običajno so na voljo:

- `Turistične regije`
- `Vodilne destinacije`
- `Makrodestinacije`
- `Perspektivne destinacije`

## Skupine Kazalnikov

Kazalniki so razporejeni v skupine:

- `Družbeni kazalniki`
- `Okoljski kazalniki`
- `Ekonomski nastanitveni in tržni turistični kazalniki`
- `Ekonomsko poslovni kazalniki turistične dejavnosti`

Izbira skupine vpliva na sezname kazalnikov, top/bottom analizo in prikaz v
posameznih tabelah.

## Kako Brati Primerjave

Slovenija je osnovna primerjalna referenca.

Pri seštevnih kazalnikih, kot so prenočitve, prihodi, kapacitete ali število
obratov, aplikacija ne primerja samo absolutnih vrednosti. Upošteva tudi ustrezno
primerjalno osnovo, na primer ležišča, prebivalstvo ali število obratov.

Pri deležih, indeksih in povprečjih aplikacija prikazuje neposreden odmik od
slovenske vrednosti.

Pri nekaterih kazalnikih je nižja vrednost boljša. To je upoštevano v top/bottom
analizi.

## Top/Bottom Analiza

Top/bottom analiza pokaže najmočnejše in najšibkejše kazalnike izbranega območja.

Pomembno:

- analiza je ločena po skupinah kazalnikov
- nekateri kazalniki so namenoma izločeni
- velikost območja ne sme sama po sebi določiti rezultata
- pri razvrstitvi se upošteva tudi razpon vrednosti med primerljivimi območji

## AI Komentar

AI komentar povzame ključne ugotovitve iz top/bottom analize in podatkov o trgih.

Če AI ni na voljo, aplikacija prikaže rezervni komentar. Razlog je lahko:

- manjkajoč API ključ
- težava z internetno povezavo
- začasna napaka pri AI storitvi
- omejitev kvote

Če je nastavljen SQL cache, se že ustvarjen komentar pri enakih vhodnih podatkih
ponovno uporabi.

## Zavihek Turistični Promet In Sezonskost Po Trgih

V tem zavihku lahko analizirate:

- strukturo prenočitev po trgih
- rast prenočitev po trgih
- sezonskost prenočitev
- sezonskost prihodov
- PDB po trgih

Običajen potek:

1. izberite pogled območij
2. izberite območje
3. izberite leto
4. preglejte grafe in tabele

Če za izbrani pogled ali leto ni podatkov, aplikacija prikaže opozorilo.

## Nalaganje Lastnih Datotek

V stranski vrstici lahko naložite:

- Excel z indikatorji
- GeoJSON občin

To je začasni prepis privzetih podatkov za trenutno sejo. Ne spremeni podatkov v
podatkovni bazi in ne spremeni datotek na strežniku.

## Navodila Za Skrbnika Podatkov

Za redno posodabljanje podatkov je priporočeno, da Excel ostane urejevalni vir,
podatkovna baza pa produkcijski vir za aplikacijo.

Priporočen potek:

```text
uredite Excel -> zaženite uvoz -> ponovno zaženite aplikacijo ali počistite cache -> preverite aplikacijo
```

Uvoz podatkov:

```bash
python scripts/import_excel_to_db.py
```

Ta ukaz prebere Excel datoteke iz mape `data/`, jih uvozi v PostgreSQL/Supabase in
preveri, ali se vsebina v bazi ujema s prebranimi Excel podatki.

Aplikacija zaradi hitrosti začasno hrani podatke iz baze. Po uspešnem uvozu zato
ponovno zaženite Streamlit aplikacijo ali počistite Streamlit cache, če morajo biti
spremembe vidne takoj.

### Dodajanje Ali Odstranjevanje Kazalnika

1. Uredite `data/Skupna tabela občine.xlsx`, list `Skupna Tabela`.
2. Enak naziv kazalnika dodajte ali odstranite v `data/mapping.xlsx`.
3. Če kazalnik potrebuje posebno agregacijo, uredite `AGG_RULES` v kodi.
4. Zaženite uvoz v bazo.
5. Odprite aplikacijo in preverite prikaz.

### Posodobitev Vrednosti

1. Uredite vrednosti v Excelu.
2. Ne spreminjajte osnovnih stolpcev `Občine` in `Turistična regija`.
3. Zaženite uvoz v bazo.
4. Preverite vsaj en zemljevid, eno tabelo in en izbran kazalnik.

### Posodobitev Tržnih In Sezonskih Podatkov

Uredite ustrezno datoteko:

- `Sezonskost prenocitev po mesecih in trgih - YEAR.xlsx`
- `Sezonskost prihodov po mesecih in trgih - YEAR.xlsx`
- `Sezonskost PDB po mesecih in trgih - YEAR.xlsx`

Ohranite strukturo listov in glav:

- listi za ravni območij
- prva glava za trge
- druga glava za mesece

Nato zaženite uvoz v bazo.

### Posodobitev Zemljevida

1. Posodobite `data/si.json` ali `data/si_display.json`.
2. Preverite, ali se imena občin ujemajo s podatki.
3. Po potrebi ponovno zaženite aplikacijo.

## Najpogostejše Težave

### Ne Morem Vstopiti

Preverite, ali uporabljate pravilno geslo.

### Zemljevid Se Ne Prikaže

Možni razlogi:

- manjka GeoJSON
- imena občin v GeoJSON-u se ne ujemajo s podatki
- težava pri pripravi geometrije

### Kazalnik Manjka

Preverite:

- ali je stolpec v Excelu
- ali je enak naziv v `mapping.xlsx`
- ali je kazalnik v izbrani skupini
- ali je kazalnik namenoma izločen iz top/bottom analize

### Podatki Se Po Ureditvi Excela Niso Spremenili

Če aplikacija uporablja podatkovno bazo, samo urejanje Excela ni dovolj. Po urejanju
je treba zagnati:

```bash
python scripts/import_excel_to_db.py
```

Če je bil uvoz uspešen, spremembe pa še niso vidne, ponovno zaženite aplikacijo ali
počistite Streamlit cache. Podatki iz baze so zaradi hitrosti lahko začasno predpomnjeni.

### AI Komentar Se Ne Prikaže

Če AI ni na voljo, aplikacija prikaže rezervni komentar. Če se ne prikaže nič,
preverite nastavitve API ključa, povezavo in strežniške dnevnike.

Če se AI komentar ustvari, vendar aplikacija opozori, da ga ni bilo mogoče shraniti v
trajni cache, preverite nastavitev SQL povezave za AI cache in pravice uporabnika v bazi.
