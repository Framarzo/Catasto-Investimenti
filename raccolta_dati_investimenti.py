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


def _to_float(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _estrai_range(testo: str, categoria_regex: str) -> tuple[float, float] | None:
    """
    Cerca nel testo della pagina una frase del tipo:
    "i valori immobiliari dei negozi in queste zone variano da un minimo
     di 420 €/mq ... ad un massimo di 1.750 €/mq"
    e ne estrae il minimo e il massimo.

    DA VERIFICARE: pattern ricostruito da testo visto nei risultati di ricerca durante
    la conversazione, non da un controllo diretto dell'HTML — verificare al primo run
    stampando `testo[:2000]` per confermare la formulazione esatta usata dal sito.
    """
    pattern = re.compile(
        categoria_regex + r"[^0-9]{0,80}?minim\w*\s*(?:di\s*)?(\d[\d.,]*)\s*€/mq"
        r"[^0-9]{0,200}?massim\w*\s*(?:di\s*)?(\d[\d.,]*)\s*€/mq",
        re.I,
    )
    m = pattern.search(testo)
    if not m:
        return None
    return _to_float(m.group(1)), _to_float(m.group(2))


def fetch_valori_requot(nome_comune: str) -> dict:
    """
    Legge dalla pagina Requot del comune i range di prezzo per appartamenti,
    negozi e uffici. Ritorna un dizionario con le chiavi trovate; le categorie
    non trovate restano assenti (il valore esistente in data.json non viene
    mai cancellato da un mancato match — solo aggiornato se troviamo qualcosa
    di nuovo).
    """
    slug = SLUG_REQOT.get(nome_comune)
    if not slug:
        log.warning(f"Nessuno slug Requot noto per '{nome_comune}' — salto.")
        return {}

    url = f"https://www.requot.com/valutazione-immobili/{slug}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Errore di rete su {nome_comune}: {e}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    testo = soup.get_text(" ", strip=True)

    risultati = {}

    appartamenti = _estrai_range(testo, r"appartament\w+")
    if appartamenti:
        risultati["prezzo"] = appartamenti[1]  # usiamo il massimo come proxy del "medio-alto" della zona migliore;
        # in alternativa si può tenere sia min sia max — valutare quale serve meglio al sito una volta visti i dati reali

    negozi = _estrai_range(testo, r"negoz\w+")
    if negozi:
        risultati["negozi"] = {"min": negozi[0], "max": negozi[1]}

    uffici = _estrai_range(testo, r"uffic\w+")
    if uffici:
        risultati["uffici"] = {"min": uffici[0], "max": uffici[1]}

    if not risultati:
        log.warning(f"Nessun valore estratto per {nome_comune} — parsing da rivedere.")

    return risultati


def main():
    dati = carica_data_json()
    oggi = date.today().isoformat()
    aggiornati = 0

    for comune in dati["comuni"]:
        nome = comune["nome"]
        log.info(f"Controllo {nome}…")
        trovati = fetch_valori_requot(nome)

        if trovati:
            for campo, valore in trovati.items():
                comune[campo] = valore
            log.info(f"  {nome}: aggiornati i campi {list(trovati.keys())}")
            aggiornati += 1
        else:
            log.info(f"  {nome}: nessun aggiornamento (dati precedenti mantenuti)")

        time.sleep(2)  # pausa di cortesia tra le richieste

    dati["ultimo_aggiornamento"] = oggi
    salva_data_json(dati)
    log.info(f"Fatto. {aggiornati}/{len(dati['comuni'])} comuni aggiornati. "
             f"data.json salvato con timestamp {oggi}.")
    log.info("Nota: stato PUG, punteggio edificabilità e zone OMI restano quelli "
             "raccolti a mano — non toccati da questo script. Terreni non ancora inclusi.")


if __name__ == "__main__":
    main()
