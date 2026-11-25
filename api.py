"""API di ingresso + pagina operatore.

POST /jobs   {"ciclo": 0..2204, "id": "opzionale"}  -> 202 nuovo, 200 se l'id esisteva gia'
GET  /       pagina operatore (si aggiorna da sola)
GET  /stats  quanti lavori per stato
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

PAGINA = b"""<!doctype html><meta charset=utf-8><title>Operatore - pompa idraulica</title>
<style>body{font:14px sans-serif;margin:20px}td,th{padding:3px 8px;border-bottom:1px solid #ddd}
.fatto{color:green}.in_corso{color:orange}.in_coda{color:gray}</style>
<h2>Diagnosi perdita pompa</h2><div id=s></div><table id=t></table>
<script>
const E={0:'nessuna perdita',1:'perdita debole',2:'perdita grave'};
const ora=x=>x?new Date(x*1000).toLocaleTimeString():'';
async function giro(){
  const s=await (await fetch('/stats')).json();
  document.getElementById('s').textContent='in coda: '+(s.in_coda||0)+'   in corso: '+(s.in_corso||0)+'   fatti: '+(s.fatto||0);
  const j=await (await fetch('/jobs')).json();
  document.getElementById('t').innerHTML='<tr><th>id<th>ciclo<th>stato<th>risultato<th>inviato<th>finito<th>attesa totale (s)<th>calcolo (ms)<th>tentativi<th>worker'+
    j.map(r=>`<tr class=${r.stato}><td>${r.id}<td>${r.ciclo}<td>${r.stato}<td>${r.etichetta==null?'':E[r.etichetta]}<td>${ora(r.inviato)}<td>${ora(r.finito)}<td>${r.finito?(r.finito-r.inviato).toFixed(2):''}<td>${r.t_calcolo?(r.t_calcolo*1000).toFixed(1):''}<td>${r.tentativi}<td>${r.worker||''}`).join('');
}
giro();setInterval(giro,1000);
</script>"""


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
        nuovo = comune.inserisci(comune.apri_db(), id_lavoro, ciclo, time.time())
        self.rispondi(202 if nuovo else 200, {"id": id_lavoro, "duplicato": not nuovo})

    def do_GET(self):
        if self.path == "/":
            return self.rispondi(200, PAGINA, "text/html; charset=utf-8")
        con = comune.apri_db()
        if self.path == "/stats":
            return self.rispondi(200, dict(con.execute("SELECT stato, COUNT(*) FROM jobs GROUP BY stato")))
        if self.path == "/jobs":
            righe = con.execute(f"SELECT {','.join(COLONNE)} FROM jobs ORDER BY inviato DESC LIMIT 200")
            return self.rispondi(200, [dict(zip(COLONNE, r)) for r in righe])
        self.rispondi(404, {"errore": "non trovato"})

    def log_message(self, *args):
        pass  # sotto carico il log di ogni richiesta rallenta e basta


if __name__ == "__main__":
    c = comune.cfg["api"]
    comune.apri_db()
    print(f"pagina operatore: http://{c['host']}:{c['porta']}")
    ThreadingHTTPServer((c["host"], c.getint("porta")), Gestore).serve_forever()
