"""Componente di elaborazione: prende i lavori dalla coda (sqlite), classifica il ciclo, salva il risultato.

Piu' processi possono girare insieme: ognuno prende un lavoro alla volta in modo atomico.
Se un worker muore a meta', il suo lavoro resta "in_corso" e dopo `lease` secondi un altro lo riprende.

Esempio: python worker.py            (usa num_worker e ritardo del config.ini)
         python worker.py 4 0.5      (4 processi, 0.5 s di ritardo artificiale)
"""
import logging, multiprocessing, os, sys, time
import joblib
import comune

log = logging.getLogger("worker")


def lavora(ritardo, lease):
    nome = f"pid{os.getpid()}"
    con, misure = comune.apri_db(), comune.carica_misure()
    modello = joblib.load(comune.CARTELLA / "model.joblib")
    log.info("%s pronto", nome)
    while True:
        lavoro = comune.prendi_lavoro(con, nome, time.time(), lease)
        if not lavoro:
            time.sleep(0.05)  # coda vuota, riprovo tra poco
            continue
        id_lavoro, ciclo = lavoro
        t0, c0 = time.perf_counter(), time.process_time()
        etichetta = int(modello.predict([comune.feature(misure, ciclo)])[0])
        t_calcolo, t_cpu = time.perf_counter() - t0, time.process_time() - c0
        # ritardo finto per avere tempo di interrompere nelle demo: NON e' dentro t_calcolo
        time.sleep(ritardo)
        # "AND worker=?": se nel frattempo il lavoro e' stato ripreso da un altro, non sovrascrivo
        con.execute("UPDATE jobs SET stato='fatto', etichetta=?, finito=?, t_calcolo=?, t_cpu=?, ritardo=? "
                    "WHERE id=? AND worker=?",
                    (etichetta, time.time(), t_calcolo, t_cpu, ritardo, id_lavoro, nome))
        log.info("%s %s ciclo=%d -> %s (%.1f ms)", nome, id_lavoro, ciclo,
                 comune.ETICHETTE[etichetta], t_calcolo * 1000)


def configura_log():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(comune.CARTELLA / comune.cfg["worker"]["file_log"])])


def avvia(ritardo, lease):
    configura_log()  # su Windows i processi figli ripartono da zero: rifaccio il log
    lavora(ritardo, lease)


if __name__ == "__main__":
    c = comune.cfg["worker"]
    n = int(sys.argv[1]) if len(sys.argv) > 1 else c.getint("num_worker")
    ritardo = float(sys.argv[2]) if len(sys.argv) > 2 else c.getfloat("ritardo")
    configura_log()
    log.info("avvio %d worker, ritardo artificiale %.2f s", n, ritardo)
    processi = [multiprocessing.Process(target=avvia, args=(ritardo, c.getfloat("lease"))) for _ in range(n)]
    for p in processi:
        p.start()
    for p in processi:
        p.join()
