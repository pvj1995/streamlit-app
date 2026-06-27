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

Preverjanje brez uvoza v bazo:

```bash
python scripts/import_excel_to_db.py --dry-run
```

Ta ukaz prebere Excel datoteke iz mape `data/`, jih uvozi v PostgreSQL/Supabase in
preveri, ali se vsebina v bazi ujema s prebranimi Excel podatki.

Aplikacija zaradi hitrosti začasno hrani podatke iz baze. Po uspešnem uvozu zato
ponovno zaženite Streamlit aplikacijo ali počistite Streamlit cache, če morajo biti
spremembe vidne takoj.

### Dodajanje Ali Odstranjevanje Kazalnika

1. Uredite `data/yearly_indicator_input_draft.xlsx`.
2. Kazalnik dodajte ali posodobite v listu `metrics`. `metric_id` naj ostane stabilen.
3. Vrednosti dodajte v ustrezen list `Y####` kot stolpec z enakim `metric_id`.
4. V listu `metric_year_rules` dodajte vrstico za leto.
5. `source_column` pustite prazen za običajen prikaz `display_name + leto`; izpolnite ga samo, ko mora biti prikazno ime povsem ročno določeno ali brez letnice.
6. Skupino nastavite v `metrics.group` ali `metric_year_rules.group`; `legacy_mapping` se ne uporablja več.
7. Nastavite `aggregation_method`: `sum` za seštevne kazalnike, `wmean` ali `mean` za deleže, stopnje, povprečja, indekse in razmerja.
8. Pri `wmean` nastavite še `weight_metric_id` in po potrebi `weight_year`.
9. Nastavite `unit`, `format_type`, `decimal_places`, `selectable` in `lower_is_better`.
10. Če gre za primerjalni kazalnik, dodajte pravilo v `derived_metrics`.
11. Zaženite uvoz v bazo.
12. Odprite aplikacijo in preverite prikaz.

### Posodobitev Vrednosti

1. Uredite vrednosti v ustreznem listu `Y####`.
2. Ne spreminjajte `area_id` in ne preimenujte stolpcev `metric_id`, razen če posodobite tudi metapodatke.
3. Zaženite uvoz v bazo.
4. Preverite vsaj en zemljevid, eno tabelo in en izbran kazalnik.

### Primerjava Kazalnikov Po Letih

V zavihku `Kazalniki` aplikacija kazalnike z več leti združi pod eno ime brez letnice. Če ima
kazalnik več razpoložljivih let, lahko izberete:

- `Primerjava po letih`: trend izbranega kazalnika po letih
- `Posamično leto`: zemljevid, tabele in grafi za izbrano leto

Če ima kazalnik samo eno leto ali gre za primerjalno obdobje, se prikaže kot običajen posamični
kazalnik.

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

- ali je kazalnik v listu `metrics`
- ali obstaja vrstica za leto v `metric_year_rules`
- ali je `source_column` prazen za privzeto ime ali nastavljen na pričakovani ročni prikazni naziv
- ali ustrezen list `Y####` vsebuje stolpec `metric_id`
- ali je skupina nastavljena v `metrics.group` ali `metric_year_rules.group`
- ali je `selectable` nastavljen pravilno
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
