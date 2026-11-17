# [E] Polcom – dansk Discord-vagtbot

Polcom registrerer politiets vagter, fører log, viser ugentlig aktivitet og laver Excel-rapporter.

## Funktioner
- Danske knapper til STEMPEL IND og STEMPEL UD.
- Kun medlemmer med den valgte politirolle kan stemple.
- Ledelsesrolle kan se vagtoversigt og hente Excel.
- Log over start og slut i en valgfri kanal.
- Automatisk ugentlig rapport hver søndag kl. 20.00 (Europe/Copenhagen).
- SQLite-database, så vagter overlever genstarter.

## Slash-kommandoer
- `/opsætning` – vælg politirolle, ledelsesrolle, logkanal og rapportkanal. Kræver Discord-administrator.
- `/vagtpanel` – send stempelknapperne i den kanal, kommandoen bruges i.
- `/mine_timer` – se egne registrerede timer.
- `/vagtoversigt` – ledelsens oversigt for de seneste 7 dage.
- `/excelrapport` – hent `.xlsx` for de seneste 7 dage.

## 1. Opret botten hos Discord
1. Gå til https://discord.com/developers/applications
2. Vælg **New Application** og kald den `[E] Polcom`.
3. Åbn **Bot** og vælg **Reset Token**. Kopiér tokenet og opbevar det hemmeligt.
4. Under **Installation** / **OAuth2** vælg scopes `bot` og `applications.commands`.
5. Giv botten tilladelserne `Send Messages`, `Embed Links`, `Attach Files`, `Read Message History` og `View Channels`.
6. Brug installationslinket til at invitere botten til politiets Discord.

## 2. Hosting 24/7
Projektet indeholder en Dockerfile og Procfile og kan køre på en hostingtjeneste, der understøtter en permanent worker/container.
**Vigtigt:** Vælg vedvarende disk/volume til filen `polcom.sqlite3`. Uden vedvarende lagring kan databasen forsvinde ved genstart eller genudrulning.
Sæt miljøvariablen `DISCORD_TOKEN` til bot-tokenet. Sæt eventuelt `DATABASE_PATH` til placeringen på den vedvarende disk.

## 3. Første opsætning i Discord
Når botten er online:
1. Kør `/opsætning` som administrator.
2. Vælg politiets rolle, ledelsens rolle, logkanal og rapportkanal.
3. Kør `/vagtpanel` i kanalen, hvor betjentene skal stemple.

## Sikkerhed
- Del aldrig bot-tokenet med andre eller i screenshots.
- Hvis tokenet bliver delt, skal det nulstilles i Discord Developer Portal.
- Giv kun botten de nødvendige kanalrettigheder.
- Sørg for at botten har adgang til log- og rapportkanalerne.

## Bemærkninger
- Rapportperioden er de seneste 7 døgn, ikke en kalenderuge fra mandag til søndag.
- Vagter, der stadig er aktive, vises som åbne i Excel-rapporten, men tæller først med i timetotalen, når de stemples ud.
- Botten forhindrer dobbelt indstempling og bevarer aktive vagter ved genstart.
