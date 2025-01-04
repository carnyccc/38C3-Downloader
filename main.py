#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main.py
--------
Beispielskript zum Herunterladen von Talks aus der relive.c3voc.de-API
und dem Einpflegen in eine SQLite-Datenbank, inklusive Metadaten von media.ccc.de.

Erweiterungen:
    - Download mit Connect-Timeout und Read-Timeout
    - Bei Fehler (Timeout oder Abbruch) wird die (teilweise) Datei gelöscht,
      damit beim nächsten Durchlauf erneut versucht wird.
    - (Optional) Prüfung der Dateigröße per HEAD-Request (auskommentiert).
    - Sollte es in den JSON-Daten keine 'release_url' geben, wird versucht,
      die URL aus der Website https://media.ccc.de/c/38c3 zu scrapen.
"""

import requests
import sqlite3
import os
from pathlib import Path
from bs4 import BeautifulSoup
import time

######################
# KONFIGURATION
######################

# Name der SQLite-Datenbank
DB_FILE = "relive_data.sqlite"

# Download-Verzeichnis (wird automatisch erstellt)
DOWNLOAD_DIR = Path("./download/")

# JSON-URL (relive.c3voc.de)
JSON_URL = "https://relive.c3voc.de/relive/38c3/index.json"

# Basis-URL für muxed-Dateien, wenn Status != "live"
MUXED_BASE = "https://cdn.c3voc.de/relive/38c3/"

# Chunk-Size für das Herunterladen in Bytes
CHUNK_SIZE = 8192

# Timeout-Einstellungen:
# (connect_timeout, read_timeout)
# connect_timeout = Zeit beim Verbindungsaufbau
# read_timeout    = Zeit zwischen einzelnen Paketen / wenn Download hängt
REQUEST_TIMEOUT = (5, 60)  # 5s connect, 60s read

######################
# DATENBANK-FUNKTIONEN
######################

def init_db():
    """
    Erstellt (falls nicht vorhanden) die Tabellen 'talks' und 'files' in der
    SQLite-Datenbank und gibt eine geöffnete Connection zurück.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Tabelle talks
    c.execute("""
    CREATE TABLE IF NOT EXISTS talks (
        id              INTEGER PRIMARY KEY,
        guid            TEXT,
        title           TEXT,
        room            TEXT,
        status          TEXT,
        start           INTEGER,
        duration        INTEGER,
        release_url     TEXT,
        authors         TEXT,
        description     TEXT,
        last_mtime      INTEGER
    )
    """)

    # Tabelle files
    c.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        talk_id         INTEGER,
        file_type       TEXT,
        file_url        TEXT,
        local_path      TEXT,
        FOREIGN KEY (talk_id) REFERENCES talks(id)
    )
    """)

    conn.commit()
    return conn


def upsert_talk(conn, talk_data):
    """
    Fügt einen Talk in die DB ein oder aktualisiert ihn, falls er bereits existiert.
    Parameter talk_data: dict mit keys:
        - id (int)
        - guid
        - title
        - room
        - status
        - start
        - duration
        - release_url (optional)
        - mtime (last_mtime)
    """
    c = conn.cursor()
    c.execute("SELECT id, last_mtime FROM talks WHERE id = ?", (talk_data["id"],))
    row = c.fetchone()

    if row is None:
        # Einfügen
        c.execute("""
            INSERT INTO talks (
                id, guid, title, room, status,
                start, duration, release_url, last_mtime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            talk_data["id"],
            talk_data.get("guid"),
            talk_data.get("title"),
            talk_data.get("room"),
            talk_data.get("status"),
            talk_data.get("start"),
            talk_data.get("duration"),
            talk_data.get("release_url"),
            talk_data.get("mtime", 0)
        ))
    else:
        # Aktualisieren, nur wenn mtime größer ist
        existing_mtime = row[1] if row[1] else 0
        if talk_data["mtime"] > existing_mtime:
            c.execute("""
                UPDATE talks
                SET guid = ?, title = ?, room = ?, status = ?,
                    start = ?, duration = ?, release_url = ?, last_mtime = ?
                WHERE id = ?
            """, (
                talk_data.get("guid"),
                talk_data.get("title"),
                talk_data.get("room"),
                talk_data.get("status"),
                talk_data.get("start"),
                talk_data.get("duration"),
                talk_data.get("release_url"),
                talk_data.get("mtime"),
                talk_data["id"]
            ))

    conn.commit()


def insert_or_ignore_file(conn, talk_id, file_type, file_url, local_path):
    """
    Fügt einen Eintrag in 'files' ein, falls er nicht bereits existiert.
    Parameter:
        - talk_id (int): ID des Talks (Fremdschlüssel)
        - file_type (str): z.B. "thumbnail", "muxed", "video_hd", "audio_deu_mp3", ...
        - file_url (str): URL, von der die Datei heruntergeladen wurde
        - local_path (Path oder str): Pfad, wo die Datei lokal gespeichert wurde
    """
    c = conn.cursor()
    c.execute("""
        SELECT id FROM files
        WHERE talk_id = ? AND file_type = ? AND file_url = ?
    """, (talk_id, file_type, file_url))
    row = c.fetchone()

    if row is None:
        c.execute("""
            INSERT INTO files (talk_id, file_type, file_url, local_path)
            VALUES (?, ?, ?, ?)
        """, (talk_id, file_type, file_url, str(local_path)))
        conn.commit()


######################
# DOWNLOAD & PARSING
######################

def download_file(url, dest_path):
    """
    Lädt die Datei von 'url' herunter und speichert sie unter 'dest_path'.
    - Falls die Datei bereits existiert und vollständig ist, wird nicht erneut geladen.
    - Bei (Timeout-)Fehler oder Abbruch wird die (ggf. angefangene) Datei gelöscht
      und False zurückgegeben, damit beim nächsten Skriptlauf erneut versucht wird.
    - Gibt True zurück, wenn der Download erfolgreich war (oder die Datei bereits vollständig existiert).
    """

    # Verzeichnis anlegen, falls nicht vorhanden
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # (Optional) Content-Length prüfen:
    expected_size = None
    try:
        head_resp = requests.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
        if head_resp.ok:
            if "Content-Length" in head_resp.headers:
                expected_size = head_resp.headers["Content-Length"]
                try:
                    expected_size = int(expected_size)
                except ValueError:
                    expected_size = None
    except requests.RequestException:
        # HEAD-Request ist optional. Falls er scheitert, ignorieren wir das hier.
        pass

    # Wenn lokaler Download existiert und Größe übereinstimmt, überspringen
    if expected_size and dest_path.exists() and dest_path.stat().st_size == expected_size:
        print(f"Datei bereits vollständig vorhanden: {dest_path}")
        return True

    # Falls Datei existiert (aber evtl. unvollständig), neu laden:
    if dest_path.exists():
        print(f"Datei existiert, wird aber neu geladen: {dest_path}")
        dest_path.unlink()  # Löschen, um von vorne zu beginnen

    print(f"Lade herunter: {url} -> {dest_path}")
    try:
        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    f.write(chunk)

        # Download abgeschlossen. Optional prüfen, ob Datei komplett ist:
        if expected_size and dest_path.stat().st_size != expected_size:
            print(f"Warnung: Datei {dest_path} hat andere Größe als erwartet!")
            return True

        print(f"Download erfolgreich abgeschlossen: {dest_path}")
        return True

    except requests.RequestException as e:
        print(f"Fehler beim Herunterladen von {url}: {e}")
        if dest_path.exists():
            dest_path.unlink()
        return False


def parse_release_page(release_url):
    """
    Lädt die Release-Seite (z.B. media.ccc.de) und extrahiert:
        - authors (z.B. "Alice, Bob")
        - description (aus <p class='description'>)
        - video_hd_url (Falls ein HD-Link vorhanden ist)
        - audio_urls (Liste von (filetype, url), z.B. ("audio_deu_mp3", "https://...mp3"))
    Gibt ein Dict zurück:
        {
            "authors": "...",
            "description": "...",
            "video_hd_url": "...",
            "audio_urls": [("audio_deu_mp3", "..."), ...]
        }
    """
    result = {
        "authors": "",
        "description": "",
        "video_hd_url": None,
        "audio_urls": []
    }

    try:
        resp = requests.get(release_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Fehler beim Laden der release_url: {release_url} -> {e}")
        return result

    soup = BeautifulSoup(resp.text, 'html.parser')

    # 1. Autor*innen
    persons_p = soup.find('p', class_='persons')
    if persons_p:
        authors_list = [a.get_text(strip=True) for a in persons_p.find_all('a')]
        result["authors"] = ", ".join(authors_list)

    # 2. Beschreibung
    desc_p = soup.find('p', class_='description')
    if desc_p:
        result["description"] = desc_p.get_text("\n", strip=True)

    # 3. HD-Video-Link
    hd_btn = soup.find('a', href=lambda x: x and "h264-hd" in x and x.endswith(".mp4"))
    if hd_btn:
        result["video_hd_url"] = hd_btn['href']

    # 4. Alle Audio-Links
    audio_btns = soup.find_all('a', class_='btn btn-default download audio')
    for a in audio_btns:
        href = a.get('href')
        if not href:
            continue
        classes = a.get('class', [])
        language = None
        for c in classes:
            if c in ["deu", "eng", "fra"]:
                language = c
        if ".mp3" in href:
            filetype = f"audio_{language}_mp3"
        elif ".opus" in href:
            filetype = f"audio_{language}_opus"
        else:
            filetype = f"audio_{language}_other"

        result["audio_urls"].append((filetype, href))

    return result

def get_release_url_from_website(talk_title):
    """
    Versucht, die Release-URL von https://media.ccc.de/c/38c3 anhand
    des Talk-Titels zu finden.
    """
    base_url = "https://media.ccc.de"
    index_url = f"{base_url}/c/38c3"

    try:
        resp = requests.get(index_url, timeout=(5, 60))  # Timeout anpassen nach Bedarf
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Alle event-preview-Container durchgehen
        event_previews = soup.find_all('div', class_='event-preview')
        for preview in event_previews:
            # a-Tag in h3
            caption = preview.find('div', class_='caption')
            if not caption:
                continue

            h3_tag = caption.find('h3')
            if not h3_tag:
                continue

            a_tag = h3_tag.find('a', href=True)
            if not a_tag:
                continue

            # href ist z. B. '/v/38c3-fnord-nachrichtenrckblick-2024'
            relative_href = a_tag['href']
            link_text = a_tag.get_text(strip=True)  # "Fnord-Nachrichtenrückblick 2024" usw.

            # Prüfen, ob der Talk-Titel (z. B. 'fnord' o. ä.) drinsteckt
            # (Je nachdem, wie ähnlich der JSON-Titel dem Linktext ist, 
            #  musst du hier eine passende Vergleichslogik bauen)
            if talk_title.lower() in link_text.lower():
                # Vollständige URL bauen
                release_url = base_url + relative_href
                return release_url

    except requests.RequestException as e:
        print(f"Fehler beim Scrapen der Release-URL von {index_url}: {e}")

    # Falls nichts gefunden oder Fehler aufgetreten ist
    return None

######################
# HAUPTFUNKTION
######################

def main():
    # 1. Datenbank initialisieren
    conn = init_db()

    # 2. JSON-Daten von relive.c3voc.de laden
    try:
        print("Lade JSON-Daten von", JSON_URL)
        r = requests.get(JSON_URL, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()  # data ist eine Liste von Dicts
    except Exception as e:
        print(f"Fehler beim Laden der JSON-Daten: {e}")
        return

    # 3. Durch die Einträge iterieren
    for entry in data:
        talk_id = int(entry["id"])
        talk_data = {
            "id": talk_id,
            "guid": entry.get("guid"),
            "title": entry.get("title"),
            "room": entry.get("room"),
            "status": entry.get("status"),
            "start": entry.get("start"),
            "duration": entry.get("duration"),
            "release_url": entry.get("release_url"),
            "mtime": entry.get("mtime", 0)
        }

        # Falls keine release_url im JSON vorhanden ist, versuchen wir, sie zu scrapen
        if talk_data["status"] in ["recorded", "released"] and not talk_data["release_url"]:
            scraped_url = get_release_url_from_website(talk_data["title"])
            if scraped_url:
                talk_data["release_url"] = scraped_url

        # In DB einfügen / aktualisieren
        upsert_talk(conn, talk_data)

        # Verzeichnis für den Talk
        dest_folder = DOWNLOAD_DIR / str(talk_id)

        # 3a. Wenn status != "live", muxed.mp4 herunterladen
        if talk_data["status"] in ["recorded", "released"]:
            muxed_url = f"{MUXED_BASE}{talk_id}/muxed.mp4"
            muxed_path = dest_folder / "muxed.mp4"
            success_muxed = download_file(muxed_url, muxed_path)
            if success_muxed:
                insert_or_ignore_file(conn, talk_id, "muxed", muxed_url, muxed_path)

        # 3b. Thumbnail herunterladen (falls vorhanden)
        thumbnail_url = entry.get("thumbnail")
        if thumbnail_url:
            if thumbnail_url.startswith("//"):
                thumbnail_url = "https:" + thumbnail_url
            thumb_path = dest_folder / "thumb.jpg"
            success_thumb = download_file(thumbnail_url, thumb_path)
            if success_thumb:
                insert_or_ignore_file(conn, talk_id, "thumbnail", thumbnail_url, thumb_path)

        # 3c. Wenn "released", zusätzliche Metadaten und Dateien (HD-Video, Audio)
        if talk_data["status"] in ["recorded", "released"] and talk_data["release_url"]:
            extra_info = parse_release_page(talk_data["release_url"])

            # Autoren + Beschreibung updaten (nur wenn wir was gefunden haben)
            if extra_info["authors"] or extra_info["description"]:
                c = conn.cursor()
                c.execute("""
                    UPDATE talks
                    SET authors = ?, description = ?
                    WHERE id = ?
                """, (extra_info["authors"], extra_info["description"], talk_id))
                conn.commit()

            # HD-Video
            if extra_info["video_hd_url"]:
                hd_url = extra_info["video_hd_url"]
                hd_path = dest_folder / "video_hd.mp4"
                success_hd = download_file(hd_url, hd_path)
                if success_hd:
                    insert_or_ignore_file(conn, talk_id, "video_hd", hd_url, hd_path)

            # Audio-Dateien
            for (filetype, url) in extra_info["audio_urls"]:
                filename = url.split("/")[-1]
                audio_path = dest_folder / filename
                success_audio = download_file(url, audio_path)
                if success_audio:
                    insert_or_ignore_file(conn, talk_id, filetype, url, audio_path)

    # 4. Verbindung zur Datenbank schließen
    conn.close()
    print("Fertig.")


# Skript-Einstiegspunkt
if __name__ == "__main__":
    main()
