"""Simulatore + misuratore: rimanda i cicli del test set all'API a una certa velocita',
aspetta che finiscano e calcola le metriche. Il workload e' sempre lo stesso (cicli_test.txt).

Esempio: python replay.py prova1 10                (tag "prova1", 10 cicli/s, tutti i cicli di test)
         python replay.py prova1 10 50 "4 worker"  (solo i primi 50 cicli, nota per il csv)

Il tag entra nell'id dei lavori (es. "prova1-ciclo-12"): rilanciare con lo stesso tag
rimanda gli stessi lavori -> esperimento "input ripetuto".
"""
import csv, json, statistics, sys, time, urllib.request
import numpy as np
import comune

ATTESA_MAX = 300  # secondi massimi che aspetto la fine dei lavori


def invia(url, id_lavoro, ciclo):
    req = urllib.request.Request(url, json.dumps({"id": id_lavoro, "ciclo": int(ciclo)}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["duplicato"]


def conta_non_finiti(con, filtro):
    return con.execute("SELECT COUNT(*) FROM jobs WHERE id LIKE ? AND stato!='fatto'", filtro).fetchone()[0]


if __name__ == "__main__":
    tag, velocita = sys.argv[1], float(sys.argv[2])
    cicli = np.loadtxt(comune.CARTELLA / "cicli_test.txt", dtype=int)
    if len(sys.argv) > 3:
        cicli = cicli[:int(sys.argv[3])]
    nota = sys.argv[4] if len(sys.argv) > 4 else ""
    c = comune.cfg["api"]
    url = f"http://{c['host']}:{c['porta']}/jobs"

    # invio a ritmo costante: il ciclo i parte all'istante inizio + i/velocita
    inizio, duplicati = time.time(), 0
    for i, ciclo in enumerate(cicli):
        time.sleep(max(0, inizio + i / velocita - time.time()))
        duplicati += invia(url, f"{tag}-ciclo-{ciclo}", ciclo)
    fine_invio = time.time()

    con, filtro = comune.apri_db(), (f"{tag}-%",)
    pendenti_a_fine_invio = conta_non_finiti(con, filtro)
    while conta_non_finiti(con, filtro) and time.time() - fine_invio < ATTESA_MAX:
        time.sleep(0.2)

    righe = con.execute("SELECT inviato, iniziato, finito, t_calcolo, t_cpu, tentativi FROM jobs "
                        "WHERE id LIKE ? AND stato='fatto'", filtro).fetchall()
    durata = max(r[2] for r in righe) - min(r[0] for r in righe) if righe else 0
    attesa = [r[1] - r[0] for r in righe]        # in coda prima che un worker lo prenda
    end_to_end = [r[2] - r[0] for r in righe]    # da invio a risultato visibile all'operatore
    calcolo = [r[3] for r in righe]              # solo feature + predict, senza ritardo finto
    media = lambda v: statistics.mean(v) if v else 0
    risultato = {
        "tag": tag, "nota": nota, "velocita_invio": velocita, "inviati": len(cicli), "duplicati": duplicati,
        "completati_unici": len(righe),
        "throughput_job_s": round(len(righe) / durata, 2) if durata else 0,
        "calcolo_medio_ms": round(media(calcolo) * 1000, 2),
        "attesa_coda_media_s": round(media(attesa), 3),
        "end_to_end_medio_s": round(media(end_to_end), 3),
        "end_to_end_p95_s": round(float(np.percentile(end_to_end, 95)), 3) if end_to_end else 0,
        "pendenti_a_fine_invio": pendenti_a_fine_invio,
        "rimasti_incompleti": conta_non_finiti(con, filtro),
        # core occupati in media dai worker = secondi CPU totali / secondi di durata
        "core_medi_usati": round(sum(r[4] for r in righe) / durata, 2) if durata else 0,
        "ripresi_dopo_crash": sum(1 for r in righe if r[5] > 1),
    }
    for k, v in risultato.items():
        print(f"{k:24s} {v}")

    file_csv = comune.CARTELLA / "risultati" / "esperimenti.csv"
    file_csv.parent.mkdir(exist_ok=True)
    nuovo = not file_csv.exists()
    with open(file_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, risultato.keys())
        if nuovo:
            w.writeheader()
        w.writerow(risultato)
