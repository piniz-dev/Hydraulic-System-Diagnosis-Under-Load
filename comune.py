"""Pezzi condivisi: config, dataset, calcolo delle feature, database dei lavori.

Lo importano train.ipynb, worker.py, api.py e replay.py.
"""
import configparser, io, pathlib, sqlite3, urllib.request, zipfile
import numpy as np

CARTELLA = pathlib.Path(__file__).parent
cfg = configparser.ConfigParser()
cfg.read(CARTELLA / "config.ini")
DATI = CARTELLA / cfg["dati"]["cartella"]

SENSORI = ["PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1", "FS1", "FS2",
           "TS1", "TS2", "TS3", "TS4", "VS1", "CE", "CP", "SE"]
ETICHETTE = {0: "nessuna perdita", 1: "perdita debole", 2: "perdita grave"}


def scarica_dataset():
    # scarico lo zip una volta sola e converto ogni sensore in .npy
    # (i txt sono: una riga = un ciclo di 60 s, una colonna = un campione)
    DATI.mkdir(exist_ok=True)
    if not (DATI / "PS1.txt").exists():
        zip_bytes = urllib.request.urlopen(cfg["dati"]["url"]).read()
        zipfile.ZipFile(io.BytesIO(zip_bytes)).extractall(DATI)
    for nome in SENSORI + ["profile"]:
        if not (DATI / f"{nome}.npy").exists():
            np.save(DATI / f"{nome}.npy", np.loadtxt(DATI / f"{nome}.txt"))


def carica_misure():
    # mmap: piu' processi worker condividono la stessa copia (~770 MB) invece di caricarla ognuno
    return {s: np.load(DATI / f"{s}.npy", mmap_mode="r") for s in SENSORI}


def etichette_vere():
    # profile.txt colonna 3 = perdita interna della pompa (0, 1, 2)
    return np.load(DATI / "profile.npy")[:, 2].astype(int)


def feature(misure, ciclo):
    # 17 sensori x (media, dev. std, min, max) = 68 numeri per ciclo
    return np.concatenate([[a.mean(), a.std(), a.min(), a.max()]
                           for a in (np.asarray(misure[s][ciclo]) for s in SENSORI)])


def apri_db():
    con = sqlite3.connect(CARTELLA / cfg["db"]["file"], timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")  # letture (pagina operatore) non bloccano le scritture
    con.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY,        -- chiave scelta dal client: stesso id = stesso lavoro
        ciclo INTEGER NOT NULL,
        stato TEXT NOT NULL DEFAULT 'in_coda',   -- in_coda | in_corso | fatto
        etichetta INTEGER,
        inviato REAL, iniziato REAL, finito REAL,   -- timestamp unix
        t_calcolo REAL,   -- secondi misurati di feature + predict
        t_cpu REAL,       -- tempo CPU della stessa parte
        ritardo REAL,     -- ritardo artificiale, tenuto separato
        tentativi INTEGER NOT NULL DEFAULT 0,
        worker TEXT)""")
    return con


def inserisci(con, id_lavoro, ciclo, adesso):
    # True = lavoro nuovo, False = id gia' visto (input ripetuto, viene ignorato)
    return con.execute("INSERT OR IGNORE INTO jobs(id, ciclo, inviato) VALUES(?,?,?)",
                       (id_lavoro, ciclo, adesso)).rowcount == 1


def prendi_lavoro(con, worker, adesso, lease):
    # in un'unica istruzione prendo il lavoro piu' vecchio in coda, oppure uno "in_corso"
    # da troppo tempo (il suo worker e' morto): cosi' due worker non prendono mai lo stesso
    return con.execute("""UPDATE jobs SET stato='in_corso', iniziato=?, worker=?, tentativi=tentativi+1
        WHERE id=(SELECT id FROM jobs
                  WHERE stato='in_coda' OR (stato='in_corso' AND iniziato<?)
                  ORDER BY inviato LIMIT 1)
        RETURNING id, ciclo""", (adesso, worker, adesso - lease)).fetchone()
