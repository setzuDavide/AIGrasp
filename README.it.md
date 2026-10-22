# AIGrasp

Guarda cosa ha cambiato ogni commit, un file alla volta: a sinistra il file originale, a destra quello nuovo con le
righe cancellate in rosso e quelle aggiunte in verde, e accanto alle modifiche le spiegazioni di Claude.

Serve solo Python 3 e `git`. Gira tutto sul tuo computer.

## Avvio

- Al primo avvio chiede di accettare la licenza: vedi [Licenza](#licenza).
- Doppio clic su `AIGrasp.bat`: apre l'ultimo repository guardato.
- Trascina una cartella su `AIGrasp.bat`, oppure `AIGrasp.bat C:\percorso\repo`: apre quel repository.
- Dentro l'app, il pulsante con il nome del repository in alto permette di cambiarlo (con "Sfoglia…" o dai recenti).

## Tasti

| Tasto | Cosa fa |
|---|---|
| `↓` `↑` | file successivo e precedente |
| `N` `P` | modifica successiva e precedente nel file |
| `F` | schermo intero |
| `B` | mostra o nasconde la barra laterale |
| `O` | riepilogo del commit |
| `Backspace` | torna dove eri prima di seguire un riferimento |

Le etichette sotto "File" (`.cs`, `.meta`, …) nascondono o mostrano un tipo di file; con Alt+clic resta solo quel tipo.
`.meta` parte nascosto.

## Le note

Le spiegazioni stanno in `<repository>/.aigrasp/*.json`. La cartella è esclusa da git solo sul tuo computer
(`.git/info/exclude`), quindi non finisce nei commit.

```json
{
  "title": "Di cosa parla questo gruppo di modifiche",
  "overview": "Testo mostrato nel riepilogo del commit.",
  "files": [
    {
      "path": "src/Esempio.cs",
      "blob": "<blob git della versione del file che le note descrivono>",
      "summary": "Cosa è cambiato in questo file e perché.",
      "notes": [
        { "lines": [10, 24], "side": "new", "title": "Titolo", "text": "Cosa fa e perché." }
      ]
    }
  ]
}
```

- `lines` sono le righe (da 1, estremi compresi) del file nuovo; con `"side": "old"` sono righe del file originale,
  per spiegare qualcosa che è stato tolto.
- Nei testi valgono `` `codice` ``, `**grassetto**`, righe vuote per i paragrafi e righe che iniziano con `- ` per gli elenchi.
- Le note si agganciano al file tramite `blob`, non tramite il commit: scritte prima del commit, restano valide dopo.
  Se il file cambia ancora, l'app avvisa che le note sono di un'altra versione.
- I file di note si aggiungono e non si modificano mai. Un file spiegato di nuovo riceve le note in un nuovo file di
  note, anche dentro lo stesso commit; se due descrivono la stessa versione di un file, vince il più recente.
- Il riepilogo di un commit stima i token spesi per scrivere le sue note, compresi i file di note sostituiti da altri
  più recenti, e quelli di tutto il repository: i caratteri dei file di note divisi per 3. È una stima, non un
  conteggio.

### Riferimenti

Un nome scritto tra accenti gravi diventa un collegamento, se indica un punto del codice. Un clic apre il file a quella
riga; `Backspace` (o "← Indietro") riporta dove eri.

| Scritto così | Porta a |
|---|---|
| `` `Player` `` | il file con quel nome (`Player.cs`), alla riga dove il nome è definito |
| `` `Inventory.Add` `` | il file `Inventory`, alla definizione di `Add` |
| `` `src/app.py:40` `` | quel file, riga 40 |
| `` `MoveTo` `` | la definizione nel file che stai leggendo (anche nella versione originale), oppure nell'unico file modificato che la contiene |

Valgono tutti i file del repository a quel commit, anche quelli che il commit non ha modificato: si aprono senza
colori. L'app non conosce i linguaggi: trova i file dal nome e le definizioni da come è fatta la riga.

## Sicurezza

- Il server ascolta solo su questo computer (`127.0.0.1`) e non apre mai connessioni verso l'esterno.
- L'indirizzo che apre il browser contiene la chiave della sessione (`#t=…`): solo quella scheda può usare l'app.
  La chiave cambia a ogni avvio e non è scritta nella pagina.
- La pagina può eseguire solo il proprio script e parlare solo con questo server, quindi il testo che arriva da un
  repository (nomi di file, messaggi dei commit, note) viene mostrato e mai eseguito.
- Si leggono solo file del repository scelto: niente percorsi esterni, niente collegamenti simbolici seguiti.
- AIGrasp usa `git`. Una cartella ricevuta da altri **già con la sua `.git`** (per esempio in uno zip) può far
  eseguire programmi a git stesso: vale per AIGrasp come per `git status`. Un repository clonato non ha questo problema.

## Far scrivere le note a un assistente AI

Basta un file JSON e i due comandi qui sotto, quindi può farlo qualsiasi assistente capace di scrivere un file e di
lanciare un comando.

I due comandi:

```
python aigrasp.py template C:\percorso\repo --ext .cs
python aigrasp.py template C:\percorso\repo --commit <hash>
python aigrasp.py check C:\percorso\repo --file nome-delle-note.json
```

- `template` elenca i file cambiati con i `blob` già compilati.
- `check` controlla le note: JSON valido, testi presenti, righe dentro il file. Con `--file` pretende anche che ogni
  nota descriva il file com'è adesso. Senza `--file` guarda tutte le note del repository e segnala come
  `OLDER VERSION` quelle scritte per una versione precedente (normale per i commit vecchi). Scrive anche i caratteri e
  i token stimati di ogni file di note.

Dai all'assistente queste istruzioni, con il percorso di `aigrasp.py` sul tuo computer al posto di `<aigrasp.py>`:

```text
Alla fine di ogni lavoro che ha cambiato del codice in un repository git, spiega le modifiche per AIGrasp:
1. Lancia `python <aigrasp.py> template <repository>`: elenca i file cambiati con i loro blob.
2. Partendo da quell'elenco, scrivi un nuovo file `<repository>/.aigrasp/AAAA-MM-GG-nome-breve.json`: un titolo,
   un riepilogo del lavoro e, per ogni file, un riassunto e le note sulle righe cambiate (i numeri di riga li dà
   `git diff -U0`). Scrivi nella lingua in cui ti scrivo io.
3. Lancia `python <aigrasp.py> check <repository> --file <quel file>` e correggi quello che segnala.
Non modificare mai un file di note già scritto: se cambi di nuovo un file, scrivi un altro file di note solo con i
file cambiati di nuovo. Se un comando si ferma con "Not accepted", dimmelo e non rispondere tu alla sua domanda.
```

Una persona deve avviare AIGrasp una volta e accettare la licenza. Fino ad allora i due comandi si fermano con un
messaggio, e l'assistente deve riferirtelo invece di rispondere al posto tuo.

### GitHub Copilot in VS Code

1. Apri il riquadro comandi (`Ctrl+Shift+P`), lancia **Chat: New Instructions File** e scegli la posizione **User**:
   le istruzioni restano tue e non finiscono nei repository su cui lavori.
2. Nell'intestazione del file scrivi `applyTo: '**'` e sotto incolla il testo qui sopra.
3. Usa Copilot Chat in modalità **Agent**, quella che lancia i comandi nel terminale. Chiede il permesso prima di
   ognuno.

Per un solo repository, lo stesso testo può andare in `.github/copilot-instructions.md` o in `AGENTS.md` nella sua
radice, ma così viene committato insieme al codice.

### Claude Code

1. Crea il file `~/.claude/skills/aigrasp/SKILL.md` (tutti i tuoi progetti) oppure `.claude/skills/aigrasp/SKILL.md`
   dentro un solo repository.
2. Scrivi questa intestazione e sotto incolla il testo qui sopra:

   ```markdown
   ---
   name: aigrasp
   description: Spiega le modifiche al codice per AIGrasp. Da usare alla fine di ogni lavoro che ha cambiato del codice in un repository git.
   ---
   ```

3. Apri una nuova sessione: Claude Code trova la skill da solo e chiede il permesso prima di lanciare ogni comando.

## Licenza

Required Notice: Copyright (c) 2026 setzuDavide (https://github.com/setzuDavide/AIGrasp)

AIGrasp è pubblicato con la licenza [PolyForm Noncommercial 1.0.0](LICENSE.md). Il codice è pubblico, ma l'uso non è
libero per tutti:

- **L'uso personale e quello non commerciale sono gratuiti**: studio, progetti per hobby, scuole, enti senza scopo
  di lucro e gli altri casi elencati nella licenza.
- **Per usarlo in un'azienda, o per un lavoro pagato, serve prima una licenza scritta dell'autore.** Vale anche per
  l'uso interno. Le condizioni sono in [COMPANY-LICENSE.it.md](COMPANY-LICENSE.it.md); per chiederla apri una
  issue o scrivi a [@setzuDavide](https://github.com/setzuDavide).
- Il codice inviato a questo repository segue le condizioni di [CONTRIBUTING.md](CONTRIBUTING.md).

Al primo avvio AIGrasp mostra queste condizioni e aspetta che tu scriva `I agree`. La risposta viene salvata in
`~/.aigrasp.json`, quindi viene chiesta una volta per ogni utente del computer.
