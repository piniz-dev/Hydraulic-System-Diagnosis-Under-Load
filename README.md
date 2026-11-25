# Diagnosi impianto idraulico sotto carico

Il sistema classifica la perdita interna della pompa su ogni ciclo del dataset UCI
*Condition Monitoring of Hydraulic Systems* e rende il risultato consultabile da un operatore,
anche quando arrivano cicli nuovi mentre altri sono ancora in elaborazione.

| Etichetta | Condizione |
|---|---|
| 0 | nessuna perdita |
| 1 | perdita debole |
| 2 | perdita grave |

L'etichetta riguarda il ciclo misurato, non un guasto futuro. Il target è la colonna 3 di `profile.txt`. Non entra mai tra gli input del modello.

## 1. Diagramma di architettura

```mermaid
flowchart LR
  replay["replay.py<br/>simula gli arrivi"] -->|POST /jobs| api["api.py<br/>accoda e risponde subito"]
  api -->|INSERT OR IGNORE| db[("jobs.db<br/>coda e archivio")]
  pagina["pagina operatore<br/>refresh ogni 1 s"] -->|GET / /stats /jobs| api
  db -->|UPDATE RETURNING<br/>presa atomica| worker["worker.py × N processi"]
  worker -->|feature mmap + model.joblib| db
```

`avvia.bat` fa partire questi pezzi. `replay.py` rimanda i cicli del test set. `api.py` scrive il lavoro e risponde senza classificare. Uno o più processi di `worker.py` prendono un lavoro alla volta, calcolano le feature, applicano `model.joblib` e salvano etichetta e tempi. La pagina su `http://127.0.0.1:8000` legge gli stessi record.

## 2. Codice sorgente e istruzioni di esecuzione

| File | Ruolo |
|---|---|
| `comune.py` | configurazione, dataset, 68 feature, coda sqlite |
| `train.ipynb` | download, addestramento, valutazione, salvataggio del modello |
| `model.joblib` | random forest scelto sulla validation |
| `cicli_test.txt` | workload fisso: indici del test set |
| `api.py` | ingresso dei lavori e pagina operatore |
| `worker.py` | classificazione in processi separati |
| `replay.py` | invio a ritmo costante e scrittura delle metriche |
| `test_coda.py` | duplicati, presa esclusiva, ripresa dopo il lease |
| `avvia.bat` | avvio completo: dati, API, worker, pagina e demo |
| `config.ini` | URL del dataset, database, host, porta, worker, lease |
| `risultati/valutazione_modello.txt` | metriche del modello |
| `risultati/esperimenti.csv` | metriche di sistema |

Dipendenze: Python 3 nel PATH, con `numpy`, `scikit-learn` e `joblib`.

```powershell
cd "Hydraulic-System-Diagnosis-Under-Load"
python -m pip install numpy scikit-learn joblib
```

### Avvio automatico

Doppio clic su `avvia.bat`, oppure:

```powershell
.\avvia.bat
```

Lo script, in ordine:

1. scarica il dataset in `data/` se i file non ci sono già (~70 MB la prima volta);
2. legge host e porta da `config.ini`;
3. se `http://127.0.0.1:8000/stats` non risponde, apre due finestre: `api.py` e `worker.py 1`;
4. aspetta che la pagina risponda;
5. apre il browser sulla pagina operatore;
6. invia 20 cicli del test set a 2 al secondo, con un tag nuovo `lancio-aaaammgg-hhmmss`, e aggiunge la riga a `risultati/esperimenti.csv`.

Se l'API è già accesa, non ne avvia una seconda e manda comunque i 20 cicli. Per fermare il programma si chiudono le finestre «API operatore» e «Worker». `model.joblib` e `cicli_test.txt` sono già nel repository. Per rifare addestramento e valutazione si apre `train.ipynb` e si fa Run All.

### Avvio manuale

Tre terminali, da questa cartella:

```powershell
python api.py
python worker.py 1
python replay.py demo 2 20
```

Poi aprire `http://127.0.0.1:8000`. `python test_coda.py` controlla duplicati e lease e non serve per la demo. Host, porta, numero di worker, ritardo artificiale e lease (30 s) stanno in `config.ini`. Per ripartire da una coda vuota cancellare `jobs.db`, `jobs.db-wal` e `jobs.db-shm`.

Argomenti utili:

```powershell
python worker.py 4 0.5          # 4 processi, 0.5 s di ritardo artificiale
python replay.py prova 10 50 "1 worker"   # tag, cicli/s, quanti cicli, nota nel csv
```

Lo stesso tag riusa gli stessi id (`prova-ciclo-12`): un secondo lancio è la prova di input ripetuto.

## 3. Giustificazione delle scelte

| Scelta | Perché |
|---|---|
| sqlite come coda e archivio | un solo componente; la coda sopravvive alla morte di un processo; i risultati restano consultabili |
| API che si limita ad accodare | un arrivo nuovo non aspetta le analisi in corso |
| worker come processi | il calcolo è CPU-bound e i thread Python si bloccano a vicenda per il GIL |
| id scelto dal client e `PRIMARY KEY` | un input ripetuto è ignorato dal database (`INSERT OR IGNORE`) |
| lease di 30 s | un lavoro `in_corso` senza risposta torna disponibile da solo |
| presa con `UPDATE … RETURNING` | due worker non prendono lo stesso lavoro |
| 68 feature (media, deviazione standard, minimo, massimo sui 17 sensori) e random forest | riassunto stabile di un ciclo da 60 s; si confronta con la regressione logistica e con la classe più frequente |
| misure in `.npy` con mmap | i worker condividono la stessa copia dei sensori invece di ricaricarla |

Limiti noti. Il client invia il numero del ciclo e il worker legge le misure da disco: il messaggio non contiene i campioni. Un solo file sqlite regge poche centinaia di scritture al secondo. Un lavoro più lungo del lease può essere ricalcolato; il risultato è deterministico, quindi la ripetizione non cambia l'etichetta. Il worker interrotto ricomincia il ciclo da capo.

## 4. Valutazione del modello

Divisione 60/20/20 stratificata (`random_state=0`): 1323 cicli di training, 441 di validation, 441 di test. Una riga è un ciclo intero, quindi i campioni di uno stesso ciclo non finiscono in due partizioni. Lo scaler sta nella pipeline ed è fittato solo sul training. Il modello si sceglie con la F1 macro sulla validation; il test si usa una volta, per il modello scelto e per il riferimento.

F1 macro sulla validation:

| Modello | F1 macro |
|---|---|
| riferimento (classe più frequente) | 0.237 |
| regressione logistica | 0.988 |
| random forest | 0.997 |

Scelto: random forest. Sul test (441 cicli) la matrice di confusione è diagonale e precision, recall e F1 valgono 1.00 per nessuna perdita (244), perdita debole (99) e perdita grave (98). Il riferimento, che predice sempre «nessuna perdita», ha accuracy 0.55 e F1 macro 0.24. Il report completo è in `risultati/valutazione_modello.txt`.

Limiti della valutazione. I cicli vicini nel tempo si somigliano e una divisione casuale può risultare più facile di una divisione per blocchi temporali. Il banco è uno solo, in laboratorio: i numeri non si trasferiscono a un impianto diverso senza nuovi dati.

## 5. Confronto sperimentale delle configurazioni

Il workload è sempre `cicli_test.txt`. Ogni lancio di `replay.py` aggiunge una riga a `risultati/esperimenti.csv`.

Definizione delle misure:

| Misura | Definizione |
|---|---|
| Lavori unici completati | righe `fatto` con quell'id; un id ripetuto non conta due volte |
| Throughput | lavori fatti / (ultimo `finito` − primo `inviato`), in lavori/s |
| Tempo di calcolo | solo feature + predict (`perf_counter`), in ms; il ritardo artificiale sta nella colonna `ritardo` e non entra qui |
| Tempo end-to-end | `finito` − `inviato`: quanto aspetta l'operatore |
| Lavoro ancora aperto | lavori non `fatto`; `pendenti_a_fine_invio` è il valore nell'istante in cui finisce l'invio |
| Risorse | secondi di CPU dei worker / durata, cioè i core occupati in media |

I run `prova` e `demo` sono la dimostrazione corta (20 cicli). Il confronto di configurazioni usa tutti i 441 cicli di `cicli_test.txt`, senza ritardo artificiale. La macchina ha 8 core fisici.

Un worker, carico crescente:

| Tag | Arrivi (cicli/s) | Completati | Throughput (job/s) | Calcolo (ms) | Attesa coda (s) | End-to-end (s) | p95 (s) | Pendenti a fine invio | Incompleti | Core medi |
|---|---|---|---|---|---|---|---|---|---|---|
| w1-v5 | 5 | 441 | 5.01 | 22.39 | 0.019 | 0.043 | 0.067 | 1 | 0 | 0.09 |
| w1-v20 | 20 | 441 | 20.01 | 22.90 | 0.021 | 0.046 | 0.075 | 1 | 0 | 0.42 |
| w1-v50 | 50 | 441 | 50.14 | 23.65 | 0.016 | 0.041 | 0.064 | 2 | 0 | 1.13 |
| w1-v100 | 100 | 441 | 62.17 | 27.22 | 1.437 | 1.466 | 2.497 | 135 | 0 | 1.62 |
| w1-v200 | 200 | 441 | 72.25 | 22.33 | 1.189 | 1.214 | 2.075 | 179 | 0 | 1.53 |

Fino a 50 cicli/s il throughput coincide con gli arrivi, l'attesa resta sotto 0.03 s e a fine invio restano 1 o 2 lavori. A 100 cicli/s il throughput scende a 62 lavori/s, l'attesa media sale a 1.44 s e 135 lavori sono ancora aperti quando l'invio termina. A 200 cicli/s il tetto è 72 lavori/s, con 179 pendenti. Il calcolo resta intorno a 23 ms: il tempo in più è coda, non il modello. Il sistema smette di reggere tra 50 e 100 arrivi al secondo.

Stesso carico, 441 cicli a 200 al secondo, cambiando solo i processi:

| Tag | Worker | Throughput (job/s) | Attesa coda (s) | End-to-end (s) | p95 (s) | Pendenti a fine invio | Core medi |
|---|---|---|---|---|---|---|---|
| w1-v200 | 1 | 72.25 | 1.189 | 1.214 | 2.075 | 179 | 1.53 |
| w2-v200 | 2 | 93.44 | 0.205 | 0.231 | 0.330 | 20 | 2.06 |
| w4-v200 | 4 | 77.72 | 0.038 | 0.069 | 0.160 | 6 | 1.69 |
| w8-v200 | 8 | 60.38 | 0.030 | 0.070 | 0.218 | 4 | 1.25 |

Il secondo processo alza il tetto a 93 lavori/s e porta l'attesa da 1.19 s a 0.21 s. Con 4 e 8 processi la coda vista dall'operatore quasi sparisce (6 e 4 pendenti, p95 sotto 0.22 s), ma il throughput non sale e i core medi restano intorno a 2, lontano dagli 8 core della macchina. Il calcolo per ciclo non cambia. Oltre due worker il limite non è più la CPU del modello: API e worker scrivono sullo stesso file sqlite, e il client non riesce più a sostenere 200 inserimenti al secondo. Nessun run lascia lavori incompleti.

## 6. Evidenze: interruzione e input ripetuto

**Input ripetuto.** Il secondo lancio di `python replay.py prova 10` rimanda gli stessi 20 id. L'API risponde `duplicato: true` (HTTP 200 invece di 202). Nel csv i duplicati sono 20, `completati_unici` resta 20 e nessun lavoro viene eseguito due volte. `test_coda.py` verifica lo stesso comportamento sul database: il secondo `INSERT` con la stessa chiave è ignorato.

**Interruzione.** `python test_coda.py` controlla il meccanismo: il lavoro resta `in_corso`, dopo il lease un altro worker lo riprende e `tentativi` passa a 2.

Dal vivo, tag `stop`: due worker con 2 s di ritardo artificiale, 30 cicli a 5 al secondo. I processi sono stati chiusi mentre 2 lavori erano `in_corso`, poi riavviati dopo il lease di 30 s. Nel csv: 30 completati, 0 incompleti, `ripresi_dopo_crash` = 2. Il calcolo medio resta 20 ms. L'end-to-end p95 di 16.6 s è l'attesa del lease, non l'analisi. Nessun lavoro accodato è andato perso. I due lavori interrotti sono stati ricalcolati da capo; l'etichetta non cambia perché il modello è deterministico.

## 7. Dimostrazione breve

Doppio clic su `avvia.bat`. Si aprono la pagina operatore e, se non erano già attivi, API e worker. Venti cicli passano da `in_coda` a `in_corso` a `fatto`, con una delle tre etichette. La pagina elenca stato, risultato, attesa, tempo di calcolo e tentativi, e si aggiorna ogni secondo.

I due run `demo` già nel csv chiudono entrambi 20 lavori unici, con throughput 2.13 e 2.08 job/s e nessun incompleto. Un lancio di `avvia.bat` fa lo stesso percorso con un tag `lancio-...`.
