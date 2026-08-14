"""
Raccolta dati investimenti immobiliari — Salento (Fase 1)
============================================================

Cosa fa questo script:
1. Prova a recuperare le quotazioni OMI per zona di ciascun comune (da Requot.com)
2. Aggiorna il file data.json — LO STESSO FILE che legge il sito — con i nuovi numeri
3. Nessun database: solo un file JSON, come richiesto. Il sito lo legge direttamente.

Come si collega al resto del sistema (l'architettura "autonoma" a costo zero):
  Questo script  --(schedulato da GitHub Actions, es. ogni notte)-->
  aggiorna data.json  --(commit automatico nel repository)-->
  il sito statico (Netlify/GitHub Pages) si ripubblica da solo con i dati nuovi

  Nessun server da mantenere acceso: GitHub Actions lo accende, lo esegue, lo spegne.
  Vedi il file .github/workflows/aggiorna-dati.yml incluso insieme a questo script.

IMPORTANTE — leggi prima di usarlo:
- Scritto senza accesso a internet dal mio ambiente: i selettori per Requot.com sono
  una ricostruzione dai risultati di ricerca visti in conversazione, non da un test
  dal vivo. Vanno quasi certamente aggiustati la prima volta — vedi "# DA VERIFICARE".
- Il PUG (stato del piano urbanistico) resta raccolto A MANO per ora: non esiste una
  fonte unica automatizzabile per tutti i comuni (lo abbiamo verificato a fondo prima).
  Questo script aggiorna solo i campi automatizzabili (prezzo, canone, rendita);
  i campi "pug", "zonaCitata", "punteggio", "rel" restano quelli già in data.json
  finché qualcuno (tu, o io in una prossima sessione) non li aggiorna manualmente.

Uso:
    pip install requests beautifulsoup4
    python raccolta_dati_investimenti.py
"""

import json
import re
import time
import logging
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data.json"

# slug Requot per ciascun comune (nome come compare nell'URL, es. .../Porto-Cesareo.html)
SLUG_REQOT = {
    "Lecce (città)": "Lecce",
    "Otranto": "Otranto",
    "Gallipoli": "Gallipoli",
    "Porto Cesareo": "Porto-Cesareo",
    "Castro": "Castro",
    "Santa Cesarea Terme": "Santa-Cesarea-Terme",
    "Nardò": "Nardo",
    "Melendugno": "Melendugno",
    "Ugento": "Ugento",
    "Parabita": "Parabita",
    "Galatina": "Galatina",
    "Matino": "Matino",
    "Maglie": "Maglie",
    "Casarano": "Casarano",
    "Taviano": "Taviano",
    "Racale": "Racale",
    "Minervino di Lecce": "Minervino-Di-Lecce",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def carica_data_json() -> dict:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salva_data_json(dati: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)


def fetch_prezzo_medio_requot(nome_comune: str) -> float | None:
    """
    Prova a leggere il prezzo medio al mq degli appartamenti dalla pagina Requot
    del comune. Ritorna None se non riesce (il valore esistente in data.json
    resta invariato, non viene mai cancellato).

    DA VERIFICARE: pattern regex ricostruito da testo visto nei risultati di ricerca,
    non dall'HTML reale — controllare con `print(soup.prettify()[:3000])` al primo run.
    """
    slug = SLUG_REQOT.get(nome_comune)
    if not slug:
        log.warning(f"Nessuno slug Requot noto per '{nome_comune}' — salto.")
        return None

    url = f"https://www.requot.com/valutazione-immobili/{slug}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Errore di rete su {nome_comune}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    testo = soup.get_text(" ", strip=True)

    # Cerca un pattern tipo "quotazioni immobiliari medie" seguito da un valore in €/mq.
    # DA VERIFICARE contro l'HTML reale.
    match = re.search(r"quotazion\w+ immobiliar\w+ medi\w*[^0-9]{0,60}?(\d[\d.,]*)\s*€/mq", testo, re.I)
    if not match:
        log.warning(f"Pattern prezzo non trovato per {nome_comune} — parsing da rivedere.")
        return None

    return float(match.group(1).replace(".", "").replace(",", "."))


def main():
    dati = carica_data_json()
    oggi = date.today().isoformat()
    aggiornati = 0

    for comune in dati["comuni"]:
        nome = comune["nome"]
        log.info(f"Controllo {nome}…")
        nuovo_prezzo = fetch_prezzo_medio_requot(nome)

        if nuovo_prezzo is not None:
            vecchio = comune["prezzo"]
            comune["prezzo"] = nuovo_prezzo
            log.info(f"  {nome}: prezzo {vecchio} → {nuovo_prezzo} €/mq")
            aggiornati += 1
        else:
            log.info(f"  {nome}: nessun aggiornamento (dato precedente mantenuto)")

        time.sleep(2)  # pausa di cortesia tra le richieste

    dati["ultimo_aggiornamento"] = oggi
    salva_data_json(dati)
    log.info(f"Fatto. {aggiornati}/{len(dati['comuni'])} comuni aggiornati. "
             f"data.json salvato con timestamp {oggi}.")
    log.info("Nota: stato PUG, punteggio edificabilità e zone OMI restano quelli "
             "raccolti a mano — non toccati da questo script.")


if __name__ == "__main__":
    main()
