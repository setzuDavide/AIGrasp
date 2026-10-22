# AIGrasp

See what each commit changed, one file at a time: the original file on the left, the new one on the right with
removed lines in red and added lines in green, and next to the changes the notes of whoever wrote them. It was
made to study code written by an AI assistant, with the assistant's own explanations beside every change.

It needs only Python 3 and `git`. Everything runs on your computer and nothing is sent anywhere.

*Italiano: [README.it.md](README.it.md)*

## Start

```
python aigrasp.py C:\path\to\repository
```

- The first start asks you to accept the licence: see [Licence](#licence).
- With no path it opens the last repository you looked at.
- On Windows you can double click `AIGrasp.bat`, or drag a folder onto it.
- Inside the app, the button with the repository name lets you change repository.
- The `EN` / `IT` button switches language. The choice is saved in `~/.aigrasp.json`.

## Keys

| Key | What it does |
|---|---|
| `↓` `↑` | next and previous file |
| `N` `P` | next and previous change in the file |
| `F` | full screen |
| `B` | show or hide the sidebar |
| `O` | overview of the commit |
| `Backspace` | back to where you were before following a reference |

The labels under "Files" (`.py`, `.meta`, …) hide or show a type of file; Alt+click keeps only that type.

## Notes

The explanations live in `<repository>/.aigrasp/*.json`. The folder is kept out of git on your computer only
(`.git/info/exclude`), so it never ends up in a commit.

```json
{
  "title": "What this group of changes is about",
  "overview": "Text shown on the overview page of the commit.",
  "files": [
    {
      "path": "src/example.py",
      "blob": "<git blob of the version of the file the notes describe>",
      "summary": "What changed in this file and why.",
      "notes": [
        { "lines": [10, 24], "side": "new", "title": "Title", "text": "What it does and why." }
      ]
    }
  ]
}
```

- `lines` are lines of the new file (from 1, both ends included). With `"side": "old"` they are lines of the
  original file, to explain something that was removed.
- Texts support `` `code` ``, `**bold**`, empty lines between paragraphs and lines starting with `- ` for lists.
- Notes are tied to a file through its `blob`, not through a commit: written before the commit, they still
  match after it. If the file changes again, the app says the notes belong to another version.
- Notes files are only added, never edited. A file explained again gets its notes in a new notes file, even within
  the same commit; where two describe the same version of a file, the newest one wins.
- The overview of a commit estimates the tokens spent writing its notes, earlier notes files replaced by newer ones
  included, and those of the whole repository: the characters of the notes files divided by 3. It is an estimate,
  not a count.

Two commands help whoever writes them:

```
python aigrasp.py template C:\path\to\repository --ext .py
python aigrasp.py template C:\path\to\repository --commit <hash>
python aigrasp.py check C:\path\to\repository --file name-of-the-notes.json
```

- `template` lists the changed files with their `blob` already filled in.
- `check` validates the notes: valid JSON, texts present, lines inside the file. With `--file` it also requires
  every note to describe the file as it is now. It also prints the characters and the estimated tokens of each
  notes file.

### References

A name written between backticks becomes a link when it names a place in the code. A click opens the file at
that line; `Backspace` brings you back.

| Written like this | Goes to |
|---|---|
| `` `Player` `` | the file with that name (`Player.cs`), at the line where the name is defined |
| `` `Inventory.Add` `` | the file `Inventory`, at the definition of `Add` |
| `` `src/app.py:40` `` | that file, line 40 |
| `` `move_to` `` | its definition in the file you are reading (also in the original version), or in the only changed file that has one |

Every file of the repository at that commit works, including the ones the commit did not change. The app knows
no programming language: it finds files by name and definitions by the shape of the line.

## Getting an AI assistant to write the notes

The contract is a JSON file plus the two commands above, so any assistant that can write a file and run a command
can do it. Give it these instructions, with the path of `aigrasp.py` on your computer in place of `<aigrasp.py>`:

```text
At the end of every task that changed code in a git repository, explain the changes for AIGrasp:
1. Run `python <aigrasp.py> template <repository>`: it lists the changed files with their blobs.
2. From that list, write a new file `<repository>/.aigrasp/YYYY-MM-DD-short-name.json`: a title, an overview
   of the task, and for each file a summary and notes on the lines that changed (`git diff -U0` gives the line
   numbers). Write in the language I write to you in.
3. Run `python <aigrasp.py> check <repository> --file <that file>` and fix what it reports.
Never edit an older notes file: if you change a file again, write another notes file with only the files you
changed again. If a command stops with "Not accepted", tell me, and do not answer its question yourself.
```

A person has to start AIGrasp once and accept the licence. Until then the two commands stop with a message, and
the assistant should pass that message on instead of answering for you.

### GitHub Copilot in VS Code

1. Open the Command Palette (`Ctrl+Shift+P`), run **Chat: New Instructions File** and pick the **User** location:
   the instructions stay yours and do not end up in the repositories you work on.
2. Write `applyTo: '**'` in the header of the file and paste the text above under it.
3. Use Copilot Chat in **Agent** mode, the one that runs commands in the terminal. It asks before each one.

For one repository only, the same text can go in `.github/copilot-instructions.md` or in `AGENTS.md` at its root,
but then it is committed with the rest of the code.

### Claude Code

1. Create the file `~/.claude/skills/aigrasp/SKILL.md` (all your projects) or `.claude/skills/aigrasp/SKILL.md`
   inside one repository.
2. Write this header, then paste the text above under it:

   ```markdown
   ---
   name: aigrasp
   description: Explain code changes for AIGrasp. Use at the end of every task that changed code in a git repository.
   ---
   ```

3. Start a new session: Claude Code finds the skill by itself and asks before running each command.

## Security

- The server listens on this computer only (`127.0.0.1`) and never opens a connection to anywhere else.
- The address the browser is opened with carries the key of the session (`#t=…`): only that tab can use the app.
  The key changes at every start and is not written in the page.
- The page can only run its own script and only talk to this server, so text that comes from a repository (file
  names, commit messages, notes) is shown and never executed.
- Only files of the chosen repository are read: no outside paths, no symbolic links followed.
- AIGrasp runs `git`. A folder received from someone else **with its `.git` already inside** (in a zip, for
  example) can make git itself run programs: that holds for AIGrasp as it does for `git status`. A repository
  you cloned does not have this problem.

## Licence

Required Notice: Copyright (c) 2026 setzuDavide (https://github.com/setzuDavide/AIGrasp)

AIGrasp is published under the [PolyForm Noncommercial License 1.0.0](LICENSE.md). The source is public, but it
is not free for every use:

- **Personal and other noncommercial use is free**: study, hobby projects, schools, charities and the other
  cases the licence lists.
- **Use inside a company, or for paid work, needs a written licence from the author first.** That includes
  internal use. The terms are in [COMPANY-LICENSE.it.md](COMPANY-LICENSE.it.md) (in Italian); to ask for one, open
  an issue or write to [@setzuDavide](https://github.com/setzuDavide).
- Code sent to this repository comes under the terms in [CONTRIBUTING.md](CONTRIBUTING.md).

The first time it starts, AIGrasp shows these conditions and waits for you to type `I agree`. The answer is saved
in `~/.aigrasp.json`, so it is asked once for each user of the computer.
