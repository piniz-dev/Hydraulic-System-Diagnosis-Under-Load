"""Controllo della coda: duplicati ignorati, un lavoro a un solo worker, ripresa dopo crash.

Esempio: python test_coda.py
"""
import tempfile, pathlib
import comune

comune.cfg["db"]["file"] = str(pathlib.Path(tempfile.mkdtemp()) / "test.db")
con = comune.apri_db()

# input ripetuto: il secondo inserimento con lo stesso id viene ignorato
assert comune.inserisci(con, "a", 5, 100.0) is True
assert comune.inserisci(con, "a", 5, 101.0) is False
assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1

# il primo worker lo prende, il secondo trova la coda vuota
assert comune.prendi_lavoro(con, "w1", 200.0, lease=30) == ("a", 5)
assert comune.prendi_lavoro(con, "w2", 201.0, lease=30) is None

# w1 "muore": dopo il lease il lavoro viene ripreso da w2, al secondo tentativo
assert comune.prendi_lavoro(con, "w2", 231.0, lease=30) == ("a", 5)
assert con.execute("SELECT worker, tentativi FROM jobs").fetchone() == ("w2", 2)
print("ok")
