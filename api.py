"""API di ingresso + pagina operatore.

POST /jobs   {"ciclo": 0..2204, "id": "opzionale"}  -> 202 nuovo, 200 se l'id esisteva gia'
GET  /       pagina operatore (si aggiorna da sola)
GET  /stats  quanti lavori per stato
GET  /classi quanti cicli completati per classe (0, 1, 2)
GET  /jobs   ultimi 200 lavori con risultato e tempi

L'API non classifica niente: scrive il lavoro nella coda e risponde subito,
cosi' i nuovi arrivi non aspettano mai le analisi in corso.

Esempio: python api.py   ->   http://127.0.0.1:8000
"""
import json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import comune

NUM_CICLI = 2205
COLONNE = ["id", "ciclo", "stato", "etichetta", "inviato", "iniziato", "finito",
           "t_calcolo", "ritardo", "tentativi", "worker"]

PAGINA = comune.CARTELLA / "operatore.html"  # la pagina sta in un file a parte, piu' facile da modificare


class Gestore(BaseHTTPRequestHandler):
    def rispondi(self, codice, corpo, tipo="application/json"):
        corpo = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode()
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        if self.path != "/jobs":
            return self.rispondi(404, {"errore": "non trovato"})
        try:
            dati = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            ciclo = int(dati["ciclo"])
            if not 0 <= ciclo < NUM_CICLI:
                raise ValueError("ciclo fuori range")
            id_lavoro = str(dati.get("id") or f"ciclo-{ciclo}")[:100]
        except (ValueError, KeyError, TypeError):
            return self.rispondi(400, {"errore": 'serve {"ciclo": 0..2204, "id": opzionale}'})
        nuovo = comune.inserisci(comune.connetti(), id_lavoro, ciclo, time.time())
        self.rispondi(202 if nuovo else 200, {"id": id_lavoro, "duplicato": not nuovo})

    def do_GET(self):
        if self.path == "/":
            return self.rispondi(200, PAGINA.read_bytes(), "text/html; charset=utf-8")
        con = comune.connetti()
        if self.path == "/stats":
            return self.rispondi(200, dict(con.execute("SELECT stato, COUNT(*) FROM jobs GROUP BY stato")))
        if self.path == "/classi":
            return self.rispondi(200, dict(con.execute(
                "SELECT etichetta, COUNT(*) FROM jobs WHERE stato='fatto' GROUP BY etichetta")))
        if self.path == "/jobs":
            righe = con.execute(f"SELECT {','.join(COLONNE)} FROM jobs ORDER BY inviato DESC LIMIT 200")
            return self.rispondi(200, [dict(zip(COLONNE, r)) for r in righe])
        self.rispondi(404, {"errore": "non trovato"})

    def log_message(self, *args):
        pass  # sotto carico il log di ogni richiesta rallenta e basta


if __name__ == "__main__":
    c = comune.cfg["api"]
    comune.apri_db()  # schema e WAL una volta sola all'avvio
    print(f"pagina operatore: http://{c['host']}:{c['porta']}")
    ThreadingHTTPServer((c["host"], c.getint("porta")), Gestore).serve_forever()
