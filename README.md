# 38C3 CCC Congress Downloader

Dieses Repository beinhaltet ein Python-Skript (`main.py`), das automatisch **Talks** von der [relive.c3voc.de](https://relive.c3voc.de)-API herunterlädt, in einer SQLite-Datenbank ablegt und – falls keine `release_url` im JSON vorhanden ist – eine passende URL aus der Website [media.ccc.de/c/38c3](https://media.ccc.de/c/38c3) scrapt. Anschließend werden optional weitere Metadaten und Medien (HD-Video, Audios) von der entsprechenden Release-Seite (z. B. [media.ccc.de](https://media.ccc.de)) geladen.

## Features

- **Automatischer Download** mit Timeout-Handling  
  - Bei Timeout oder Verbindungsproblemen wird die unvollständig heruntergeladene Datei gelöscht und kann später erneut geladen werden.
- **Datenbank-Speicherung**  
  - In einer SQLite-Datenbank (`relive_data.sqlite`) werden Talk-Metadaten sowie Dateipfade zu den heruntergeladenen Ressourcen (z. B. Thumbnails, Muxed-Videos, HD-Videos, Audios) abgespeichert.
- **Release-URL-Scraping**  
  - Fehlt im JSON eine `release_url`, wird versucht, die Seite [media.ccc.de/c/38c3](https://media.ccc.de/c/38c3) zu scrapen, um die passende URL zu ermitteln.
- **Erweiterbares Parsing**  
  - Der Code durchsucht die Release-Seite (typischerweise [media.ccc.de](https://media.ccc.de)) nach Metadaten (Autoren, Beschreibung, HD-Video-Links, Audio-Links).

## Voraussetzungen

- **Python 3** (z. B. 3.9+)
- **Abhängigkeiten** (via `pip` installieren):
  - [requests](https://pypi.org/project/requests/)  
  - [beautifulsoup4 (bs4)](https://pypi.org/project/beautifulsoup4/)  
  - [sqlite3](https://docs.python.org/3/library/sqlite3.html) *(ist Teil der Standardbibliothek)*

### Installation
```bash
pip install requests beautifulsoup4
```
*(Je nach System ggf. `pip3` verwenden.)*

## Aufbau

- **`main.py`**: Hauptskript mit allen Funktionen für Datenbank-Handling, Downloads, Scraping und Metadaten-Parsing.  
- **`relive_data.sqlite`**: SQLite-Datenbank. Wird beim ersten Start erzeugt und in den folgenden Läufen mit Daten gefüllt.  
- **`download/`**: Ordner, in dem die heruntergeladenen Dateien (Videos, Audios, Thumbnails) gespeichert werden. Wird bei Bedarf automatisch angelegt.  

## SQL-Datenbankstruktur

Die SQLite-Datenbank `relive_data.sqlite` enthält zwei Tabellen:

### Tabelle `talks`
| Spalte        | Typ     | Beschreibung                                    |
|---------------|---------|------------------------------------------------|
| `id`          | INTEGER | Eindeutige ID des Talks (Primärschlüssel)      |
| `guid`        | TEXT    | Globally Unique Identifier                     |
| `title`       | TEXT    | Titel des Talks                                |
| `room`        | TEXT    | Raum, in dem der Talk stattfand                |
| `status`      | TEXT    | Status des Talks (`recorded`, `released`, ...) |
| `start`       | INTEGER | Startzeit als Unix-Timestamp                   |
| `duration`    | INTEGER | Dauer in Sekunden                              |
| `release_url` | TEXT    | URL zur Release-Seite                          |
| `authors`     | TEXT    | Autoren/Sprecher des Talks                     |
| `description` | TEXT    | Beschreibung des Talks                         |
| `last_mtime`  | INTEGER | Letzte Änderungszeit als Unix-Timestamp        |

### Tabelle `files`
| Spalte        | Typ     | Beschreibung                                    |
|---------------|---------|------------------------------------------------|
| `id`          | INTEGER | Eindeutige ID der Datei (Primärschlüssel)      |
| `talk_id`     | INTEGER | Verweis auf die `id` der zugehörigen `talks`-Tabelle |
| `file_type`   | TEXT    | Typ der Datei (`muxed`, `video_hd`, ...)        |
| `file_url`    | TEXT    | URL, von der die Datei heruntergeladen wurde   |
| `local_path`  | TEXT    | Lokaler Speicherpfad der Datei                 |

## Verwendung

1. **Projekt klonen oder herunterladen**  
   ```bash
   git clone https://github.com/carnyccc/38C3-Downloader.git
   cd 38C3-Downloader
   ```

2. **Abhängigkeiten installieren**  
   ```bash
   pip install requests beautifulsoup4
   ```

3. **Skript ausführen**  
   ```bash
   python main.py
   ```
   oder (je nach System/Python-Version):
   ```bash
   python3 main.py
   ```
   Das Skript lädt das JSON vom [relive.c3voc.de](https://relive.c3voc.de)-Server und speichert Metadaten in der Datenbank.  
   - **`muxed.mp4`** und **`thumb.jpg`** werden heruntergeladen, wenn verfügbar.  
   - Bei `status: "released"` und einer bestehenden `release_url` (oder wenn eine URL aus [media.ccc.de/c/38c3](https://media.ccc.de/c/38c3) gescraped werden konnte) werden weitere Metadaten (Autoren, Beschreibung) sowie HD- und Audio-Dateien geholt.

4. **Ergebnis**  
   - **Datenbank**: Die Datei `relive_data.sqlite` enthält zwei Tabellen:
     - `talks`: Talk-Metadaten (Titel, Status, Raum, Startzeit, Release-URL, …)  
     - `files`: Heruntergeladene Dateien (Art, URL, Pfad, …)  
   - **Dateien**: Im Ordner `download/<talk_id>/` findest du die heruntergeladenen Ressourcen (z. B. `muxed.mp4`, `video_hd.mp4`, `thumb.jpg`, …).

## Konfiguration anpassen

In `main.py` findest du folgende Optionen:

- **`DB_FILE`**: Standardmäßig `relive_data.sqlite`. Hier kannst du einen anderen Datenbank-Pfad einstellen.  
- **`DOWNLOAD_DIR`**: Standardverzeichnis für Downloads (`./download/`).  
- **`JSON_URL`**: URL zum relive-JSON. Momentan: `https://relive.c3voc.de/relive/38c3/index.json`.  
- **`MUXED_BASE`**: Basis-URL, um `muxed.mp4` zu laden (`https://cdn.c3voc.de/relive/38c3/`).  
- **`REQUEST_TIMEOUT`**: Timeout für `requests` (Standard: `(5, 60)`).  
- **`CHUNK_SIZE`**: Größe der Download-Chunks (Standard: 8192 Bytes).

## Weiterentwicklung

- **Scraping**: Momentan wird [media.ccc.de/c/38c3](https://media.ccc.de/c/38c3) durchsucht, um eine `release_url` zu finden, wenn diese im JSON fehlt. Falls sich die Seitenstruktur ändert oder ein anderer Kongress verwendet wird, muss ggf. die Scraping-Funktion (`get_release_url_from_website()`) angepasst werden.  
- **Metadaten**: Das Skript holt sich die Autoren und Beschreibung aus der Release-Seite sowie mögliche HD- oder Audio-Links. Du kannst die `parse_release_page()`-Funktion erweitern, falls du noch weitere Informationen benötigst.  
- **Dateien**: Momentan werden `muxed.mp4`, Thumbnails, HD-Videos sowie Audios heruntergeladen. Möchtest du weitere Formate (etwa `webm`, `opus`, …) unterstützen, passe die entsprechenden Code-Abschnitte in `parse_release_page()` an.

## Häufige Probleme

- **`release_url` im JSON ist `None`**:  
  Dann versucht das Skript, über `get_release_url_from_website()` eine passende URL aus [media.ccc.de/c/38c3](https://media.ccc.de/c/38c3) zu finden. Klappt das nicht, wird kein HD-Video oder Audio heruntergeladen, weil das Skript nicht weiß, welche Seite es parsen soll.  
- **Talk-Status nicht `"released"`**:  
  Standardmäßig werden HD-Videos & Metadaten nur bei `status == "released"` heruntergeladen. Bei `"recorded"` wird zwar `muxed.mp4` geholt, aber keine Release-Seite ausgelesen (um Fehlanfragen zu vermeiden).

## Lizenz

Keine explizite Lizenz. Bitte beachtet jedoch eventuelle Nutzungsbedingungen der Quellseiten (z. B. [relive.c3voc.de](https://relive.c3voc.de), [media.ccc.de](https://media.ccc.de)), insbesondere beim Download und/oder der Weitergabe von Videos und Metadaten.

---

### Kontakt & Feedback
Bei Fragen, Verbesserungsvorschlägen oder Problemen:
- Issue erstellen
- Pull Request senden


Viel Erfolg und Spaß beim Nutzen des Downloaders!
