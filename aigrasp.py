#!/usr/bin/env python3
"""AIGrasp: a local viewer to study what each commit changed, file by file, with the notes of whoever wrote it.

    python aigrasp.py [repository]           open the viewer on a repository (default: the current folder)
    python aigrasp.py template [repository]  print an empty notes file for the uncommitted changes
                         [--commit HASH] [--ext .cs .py]
    python aigrasp.py check [repository]     say what is wrong with the notes of a repository
                         [--file NAME.json]

Only the Python standard library and the `git` command are used. The server listens on this computer only.

Required Notice: Copyright (c) 2026 setzuDavide (https://github.com/setzuDavide/AIGrasp)
Licensed under the PolyForm Noncommercial License 1.0.0 (LICENSE.md). Companies need a licence from the author.
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.aigrasp.json')
NOTES_DIR = '.aigrasp'                      # inside each repository, kept out of commits (see ensure_notes_dir)
CHARS_PER_TOKEN = 3.0                          # notes are prose (Italian or English), JSON and code names: a rough
                                               # average, not measured. There is no tokenizer here, only estimates
WORKING = 'WORKING'                            # the pseudo-commit that stands for the uncommitted changes
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'   # what git diffs a first commit against
ZERO_BLOB = '0' * 40
MAX_FILE_BYTES = 3 * 1024 * 1024               # bigger files are only loaded when asked explicitly
TOKEN = secrets.token_urlsafe(24)              # the key of this run. It travels in the address the browser is
                                               # opened with, never in the page: only who started the server has it


class GitError(Exception):
    pass


def git(repo, args, stdin=None):
    """Runs git in the repository and returns its raw output."""
    flags = 0x08000000 if os.name == 'nt' else 0          # no console window flashing on Windows
    # fsmonitor off: it is a program named in the repository's own config, and git would run it
    done = subprocess.run(['git', '-C', repo, '-c', 'core.quotepath=false', '-c', 'core.fsmonitor=false'] + args,
                          input=stdin, capture_output=True, creationflags=flags)
    if done.returncode != 0:
        raise GitError(done.stderr.decode('utf-8', 'replace').strip() or 'git ' + ' '.join(args) + ' failed')
    return done.stdout


def text(raw):
    return raw.decode('utf-8', 'replace')


def repo_root(path):
    """The top folder of the repository that contains `path`, or None when it is not one."""
    if not path or not os.path.isdir(path):
        return None
    try:
        return os.path.normpath(text(git(path, ['rev-parse', '--show-toplevel'])).strip())
    except (GitError, OSError):
        return None


# ---------------------------------------------------------------------------------------------------------------
# Settings remembered between runs
# ---------------------------------------------------------------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def remember_repo(repo):
    config = load_config()
    recent = [r for r in config.get('recent', []) if os.path.normcase(r) != os.path.normcase(repo)]
    config['recent'] = [repo] + recent[:11]
    save_config(config)


def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------------
# Licence: nothing runs until the person using the program has accepted the terms, once
# ---------------------------------------------------------------------------------------------------------------

LICENCE_TERMS = 'PolyForm-Noncommercial-1.0.0'    # stored with the answer: new terms ask everybody again
LICENCE_QUESTION = """
AIGrasp is not free for every use.

  Personal and other noncommercial use is free, under the PolyForm Noncommercial
  License 1.0.0: read LICENSE.md, next to this program.

  Use inside a company, or for paid work, needs a written licence from the author
  first: see "Licence" in README.md.

Type "I agree" if you have read LICENSE.md and you use AIGrasp within its terms,
or with a licence from the author:"""


def require_licence():
    """Stops the program until whoever uses it has accepted the terms. The answer is kept in the settings file."""
    config = load_config()
    accepted = config.get('licence')
    if isinstance(accepted, dict) and accepted.get('terms') == LICENCE_TERMS:
        return
    print(LICENCE_QUESTION, file=sys.stderr)      # not on the output: `template` may be writing that to a file
    try:
        answer = input()
    except (EOFError, KeyboardInterrupt):         # nobody at the keyboard: a script, or an assistant's command
        answer = ''
    if answer.strip().strip('"').lower() != 'i agree':
        sys.exit('Not accepted: AIGrasp did not start. A person has to start it once and answer.')
    config['licence'] = {'terms': LICENCE_TERMS, 'accepted': time.strftime('%Y-%m-%d %H:%M:%S')}
    save_config(config)
    print('Thank you. Your answer is saved in ' + CONFIG_PATH + '\n', file=sys.stderr)


# ---------------------------------------------------------------------------------------------------------------
# Commits and their files
# ---------------------------------------------------------------------------------------------------------------

def has_commits(repo):
    try:
        git(repo, ['rev-parse', '--verify', '--quiet', 'HEAD'])
        return True
    except GitError:
        return False


def list_commits(repo, limit, skip, all_branches, query):
    if not has_commits(repo):
        return []
    separator = '%x1f'
    fields = ['%H', '%h', '%an', '%aI', '%s', '%P']
    args = ['log', '--format=' + separator.join(fields) + '%x1e', '-n', str(limit), '--skip', str(skip)]
    if all_branches:
        args.append('--all')
    if query:
        args += ['-i', '--fixed-strings', '--grep', query]
    commits = []
    for record in text(git(repo, args)).split('\x1e'):
        parts = record.strip('\n').split('\x1f')
        if len(parts) < 6:
            continue
        commits.append({'hash': parts[0], 'short': parts[1], 'author': parts[2], 'date': parts[3],
                        'subject': parts[4], 'parents': parts[5].split()})
    return commits


def is_dirty(repo):
    return bool(git(repo, ['status', '--porcelain', '-z']).strip(b'\0'))


def first_parent(repo, commit):
    parents = text(git(repo, ['rev-list', '--parents', '-n', '1', commit])).split()[1:]
    return parents[0] if parents else EMPTY_TREE


def parse_raw(raw):
    """`git diff --raw -z`: one record per changed file, with the blobs before and after."""
    files = []
    tokens = text(raw).split('\0')
    i = 0
    while i < len(tokens):
        head = tokens[i]
        i += 1
        if not head.startswith(':'):
            continue
        fields = head[1:].split(' ')
        status = fields[4][:1]
        path = tokens[i]
        i += 1
        old_path = path
        if status in ('R', 'C'):                 # renamed or copied: two paths, old then new
            path = tokens[i]
            i += 1
        files.append({'path': path, 'oldPath': old_path, 'status': status,
                      'oldBlob': fields[2], 'newBlob': fields[3], 'added': None, 'deleted': None, 'binary': False})
    return files


def parse_numstat(raw):
    """`git diff --numstat -z`: lines added and deleted for each path."""
    counts = {}
    tokens = text(raw).split('\0')
    i = 0
    while i < len(tokens):
        parts = tokens[i].split('\t')
        i += 1
        if len(parts) < 3:
            continue
        path = parts[2]
        if path == '':                           # a rename: the two paths follow as separate tokens
            path = tokens[i + 1]
            i += 2
        if parts[0] == '-':
            counts[path] = (None, None, True)
        else:
            counts[path] = (int(parts[0]), int(parts[1]), False)
    return counts


def commit_files(repo, commit):
    """Every file the commit changed. For WORKING: the uncommitted changes, untracked files included."""
    if commit == WORKING:
        base = 'HEAD' if has_commits(repo) else EMPTY_TREE
        files = parse_raw(git(repo, ['diff', '--raw', '-z', '-M', '--abbrev=40', base]))
        counts = parse_numstat(git(repo, ['diff', '--numstat', '-z', '-M', base]))
        known = {f['path'] for f in files}
        for path in text(git(repo, ['ls-files', '--others', '--exclude-standard', '-z'])).split('\0'):
            if path and path not in known:
                files.append({'path': path, 'oldPath': path, 'status': 'A', 'oldBlob': ZERO_BLOB, 'newBlob': ZERO_BLOB,
                              'added': None, 'deleted': None, 'binary': False, 'untracked': True})
    else:
        parent = first_parent(repo, commit)
        files = parse_raw(git(repo, ['diff', '--raw', '-z', '-M', '--abbrev=40', parent, commit]))
        counts = parse_numstat(git(repo, ['diff', '--numstat', '-z', '-M', parent, commit]))
    for f in files:
        if f['path'] in counts:
            f['added'], f['deleted'], f['binary'] = counts[f['path']]
        name = os.path.basename(f['path'])
        f['ext'] = os.path.splitext(name)[1].lower() if '.' in name[1:] else ''
    files.sort(key=lambda f: f['path'].lower())
    return files


def working_blob(repo, path):
    """The blob a file of the working folder would get if it were committed now."""
    try:
        return text(git(repo, ['hash-object', '--', path])).strip()
    except GitError:
        return None


def find_file(repo, commit, path):
    for f in commit_files(repo, commit):
        if f['path'] == path:
            return f
    return None


def read_working(repo, path):
    """The bytes of a file of the working folder, never of something outside the repository.

    A link is not followed: its content is where it points to, as git itself stores it. A repository can
    contain a link to any file of the computer, and following it would show that file.
    """
    full = os.path.join(repo, path)
    if os.path.islink(full):
        return os.readlink(full).encode('utf-8', 'replace')
    inside = os.path.realpath(repo) + os.sep
    if not os.path.realpath(full).startswith(inside):
        raise GitError('That path is outside the repository.')
    try:
        with open(full, 'rb') as f:
            return f.read()
    except OSError as error:
        raise GitError(str(error))


# ---------------------------------------------------------------------------------------------------------------
# File contents and the lines that changed
# ---------------------------------------------------------------------------------------------------------------

def read_lines(raw):
    """Bytes of a file -> its lines, or None for a binary file."""
    if b'\0' in raw[:8000]:
        return None
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = raw.decode('cp1252', 'replace')         # old Windows files, common in Unity projects
    lines = content.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return [line[:-1] if line.endswith('\r') else line for line in lines]


HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def parse_hunks(diff):
    hunks = []
    for line in text(diff).split('\n'):
        m = HUNK.match(line)
        if m:
            hunks.append({'os': int(m.group(1)), 'oc': int(m.group(2) or 1),
                          'ns': int(m.group(3)), 'nc': int(m.group(4) or 1)})
    return hunks


def file_view(repo, commit, path, force):
    """Both versions of a file, the changed line ranges and the notes written for it."""
    entry = find_file(repo, commit, path)
    if entry is None:
        return unchanged_view(repo, commit, path, force)
    status = entry['status']
    result = {'path': path, 'oldPath': entry['oldPath'], 'status': status, 'old': None, 'new': None, 'hunks': [],
              'binary': False, 'tooLarge': 0}

    old_raw = new_raw = None
    if status != 'A':
        old_raw = git(repo, ['cat-file', 'blob', entry['oldBlob']])
    if status != 'D':
        if commit == WORKING:
            new_raw = read_working(repo, path)
        else:
            new_raw = git(repo, ['cat-file', 'blob', entry['newBlob']])

    size = max(len(old_raw or b''), len(new_raw or b''))
    if size > MAX_FILE_BYTES and not force:
        result['tooLarge'] = size
        return result

    old_lines = read_lines(old_raw) if old_raw is not None else []
    new_lines = read_lines(new_raw) if new_raw is not None else []
    if old_lines is None or new_lines is None:
        result['binary'] = True
        return result
    result['old'], result['new'] = old_lines, new_lines

    options = ['diff', '-U0', '--no-color', '--no-ext-diff', '--no-textconv', '--diff-algorithm=histogram']
    if status == 'A':
        result['hunks'] = [{'os': 0, 'oc': 0, 'ns': 1, 'nc': len(new_lines)}] if new_lines else []
    elif status == 'D':
        result['hunks'] = [{'os': 1, 'oc': len(old_lines), 'ns': 0, 'nc': 0}] if old_lines else []
    elif commit == WORKING:
        base = 'HEAD' if has_commits(repo) else EMPTY_TREE
        result['hunks'] = parse_hunks(git(repo, options + ['-M', base, '--', entry['oldPath'], path]))
    else:
        result['hunks'] = parse_hunks(git(repo, options + [entry['oldBlob'], entry['newBlob']]))

    blob = entry['newBlob']
    if commit == WORKING and status != 'D':
        blob = working_blob(repo, path)
    result.update(notes_for_file(repo, path, blob if status != 'D' else entry['oldBlob'], status == 'D'))
    return result


def unchanged_view(repo, commit, path, force):
    """A file the commit did not touch, as it was at that commit: the same text on both sides, nothing marked."""
    if path not in tree_paths(repo, commit):
        raise GitError('There is no such file in this commit.')
    raw = read_working(repo, path) if commit == WORKING else git(repo, ['cat-file', 'blob', commit + ':' + path])
    result = {'path': path, 'oldPath': path, 'status': '=', 'old': None, 'new': None, 'hunks': [],
              'binary': False, 'tooLarge': 0, 'summary': '', 'notes': [], 'notesStale': False}
    if len(raw) > MAX_FILE_BYTES and not force:
        result['tooLarge'] = len(raw)
        return result
    lines = read_lines(raw)
    if lines is None:
        result['binary'] = True
        return result
    result['old'] = result['new'] = lines
    return result


# ---------------------------------------------------------------------------------------------------------------
# References: from a name written in a note to the place in the code it talks about
# ---------------------------------------------------------------------------------------------------------------
# A note says `Inventory.Add`, `Player` or `src/app.py:40`. The page asks where that is and gets a file and a
# line to jump to. Nothing here understands any programming language: a file is found by its name, and a
# definition by how the line that contains the name looks.

_trees = {}


def tree_paths(repo, commit):
    """Every file of a commit, as a set of paths. For WORKING: the tracked files plus the new ones not ignored."""
    key = (repo, commit)
    cached = _trees.get(key)
    if cached and (commit != WORKING or time.time() - cached[0] < 5):      # the working folder changes: 5 s only
        return cached[1]
    if commit == WORKING:
        raw = git(repo, ['ls-files', '-z', '--cached', '--others', '--exclude-standard'])
    else:
        raw = git(repo, ['ls-tree', '-r', '-z', '--name-only', commit])
    paths = {p for p in text(raw).split('\0') if p}
    if len(_trees) > 8:
        _trees.clear()
    _trees[key] = (time.time(), paths)
    return paths


REF_NAME = re.compile(r'^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$')
REF_PATH = re.compile(r'^(?P<path>[^\s:*?"<>|]+\.[A-Za-z0-9]{1,12})(?::(?P<line>\d+))?$')
DEFINING = r'(?:class|struct|enum|interface|record|def|function|func|fn|namespace|type|trait|module)'
NOT_A_DEFINITION = ('return ', 'new ', 'await ', 'yield ', 'else ', 'throw ')


def find_definition(lines, name, usage_too):
    """The line (from 1) where a name seems to be defined. With usage_too, failing that, where it first appears."""
    word = re.compile(r'(?<![\w.])' + re.escape(name) + r'\b')
    keyword = re.compile(r'\b' + DEFINING + r'\s+' + re.escape(name) + r'\b')
    declared = re.compile(r'[\w>\]?]\s+' + re.escape(name) + r'\s*(?:\(|=>|=(?!=)|;|\{|$)')   # "type name(", "type name ="
    with_body = statement = first = None
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(('//', '#', '*', '/*')) or not word.search(line):
            continue
        if first is None:
            first = number
        if keyword.search(line):
            return number
        if declared.search(line) and not stripped.startswith(NOT_A_DEFINITION):
            if not stripped.endswith(';'):                 # "void Move()" counts more than "int x = Move();"
                with_body = with_body or number
            else:
                statement = statement or number
    return with_body or statement or (first if usage_too else None)


class References:
    """Answers "where is this name?" for one commit and one file being read."""

    def __init__(self, repo, commit, current):
        self.repo, self.commit, self.current = repo, commit, current
        self.paths = tree_paths(repo, commit)
        self.changed = {f['path']: f for f in commit_files(repo, commit)}
        self.by_stem, self.by_base = {}, {}
        for path in self.paths:
            base = path.rsplit('/', 1)[-1]
            self.by_base.setdefault(base, []).append(path)
            self.by_stem.setdefault(base.rsplit('.', 1)[0] if '.' in base[1:] else base, []).append(path)
        self.contents = {}

    def lines(self, path, side='new'):
        """The lines of a file at this commit ('new') or just before it ('old'); [] when there is nothing to read."""
        key = (path, side)
        if key not in self.contents:
            entry = self.changed.get(path)
            try:
                if side == 'old':
                    raw = git(self.repo, ['cat-file', 'blob', entry['oldBlob']]) if entry and entry['status'] != 'A' else b''
                elif entry and entry['status'] == 'D':
                    raw = b''
                elif self.commit == WORKING:
                    raw = read_working(self.repo, path)
                else:
                    raw = git(self.repo, ['cat-file', 'blob', self.commit + ':' + path])
            except GitError:
                raw = b''
            self.contents[key] = (read_lines(raw) or []) if len(raw) <= MAX_FILE_BYTES else []
        return self.contents[key]

    def best(self, candidates):
        """Among files with the same name: one this commit changed, then one of the same type as the file being read."""
        extension = os.path.splitext(self.current)[1]
        return min(candidates, key=lambda p: (p not in self.changed, os.path.splitext(p)[1] != extension, len(p), p))

    def resolve(self, reference):
        reference = reference.strip()
        while reference.endswith('()'):
            reference = reference[:-2]

        match = REF_PATH.match(reference)
        if match:                                                  # "src/app.py", "app.py:40"
            wanted = match.group('path').replace('\\', '/')
            line = int(match.group('line')) if match.group('line') else None
            if wanted in self.paths:
                return {'path': wanted, 'line': line, 'side': 'new'}
            ending = [p for p in self.paths if p.endswith('/' + wanted)] or self.by_base.get(wanted, [])
            if ending:
                return {'path': self.best(ending), 'line': line, 'side': 'new'}

        if not REF_NAME.match(reference):
            return None
        parts = reference.split('.')
        if parts[0] in self.by_stem:                               # "Player", "Inventory.Add"
            path = self.best(self.by_stem[parts[0]])
            lines = self.lines(path)
            members = [parts[-1], parts[1]] if len(parts) > 1 else []
            for name in members + [parts[0]]:
                line = find_definition(lines, name, usage_too=name in members)
                if line:
                    return {'path': path, 'line': line, 'side': 'new'}
            return {'path': path, 'line': None, 'side': 'new'}

        name = parts[-1]                                           # "MoveTo": a name with no file of its own
        if self.current:
            for side in ('new', 'old'):
                line = find_definition(self.lines(self.current, side), name, usage_too=False)
                if line:
                    return {'path': self.current, 'line': line, 'side': side}
        found = []
        for path, entry in self.changed.items():
            if path != self.current and not entry.get('binary'):
                line = find_definition(self.lines(path), name, usage_too=False)
                if line:
                    found.append({'path': path, 'line': line, 'side': 'new'})
        return found[0] if len(found) == 1 else None               # defined in several files: no telling which


def resolve_references(repo, commit, current, names):
    references = References(repo, commit, current)
    resolved = {}
    for name in names[:400]:
        if isinstance(name, str) and len(name) <= 200:
            target = references.resolve(name)
            if target:
                target['inCommit'] = target['path'] in references.changed
                resolved[name] = target
    return resolved


# ---------------------------------------------------------------------------------------------------------------
# Notes: the explanations written for a version of a file
# ---------------------------------------------------------------------------------------------------------------
# A notes file is a JSON document in <repository>/.aigrasp/:
#   { "title": "...", "overview": "...", "files": [
#       { "path": "src/a.cs", "blob": "<git blob of the version the notes describe>", "summary": "...",
#         "notes": [ { "lines": [10, 24], "side": "new", "title": "...", "text": "..." } ] } ] }
# "lines" are 1-based and inclusive: of the new file, or of the old one when "side" is "old" (to explain a removal).
# Notes are matched by blob, so they follow the file through commit, amend and rebase without knowing any hash.
# Notes files are only added, never edited: a file explained again gets its notes in a new notes file. So the size
# of all the files is what writing the notes cost, and the time a file was last written is the time of its pass.

def load_note_sets(repo):
    """Every notes file of the repository, oldest first: where two describe the same version of a file, the
    last one, the newest, wins."""
    folder = os.path.join(repo, NOTES_DIR)
    sets = []
    if not os.path.isdir(folder):
        return sets
    found = []
    for name in os.listdir(folder):
        if name.endswith('.json'):
            try:
                found.append((os.path.getmtime(os.path.join(folder, name)), name))
            except OSError:
                continue
    for written, name in sorted(found):
        raw = ''
        try:
            with open(os.path.join(folder, name), encoding='utf-8-sig') as f:
                raw = f.read()
            data = json.loads(raw)
        except (OSError, ValueError) as error:
            sets.append({'name': name, 'error': str(error), 'files': [], 'written': written, 'chars': len(raw)})
            continue
        if isinstance(data, dict):
            data.update(name=name, written=written, chars=len(raw))
            data.setdefault('files', [])
            sets.append(data)
    return sets


def estimated_tokens(chars):
    return int(round(chars / CHARS_PER_TOKEN))


def notes_for_file(repo, path, blob, deleted=False):
    """The notes for this exact version of the file; failing that, the ones written for another version of it."""
    exact, other = None, None
    for note_set in load_note_sets(repo):
        for entry in note_set.get('files', []):
            if entry.get('path') != path:
                continue
            if blob and entry.get('blob') == blob and (not deleted or describes_removal(entry)):
                exact = entry
            else:
                other = entry
    chosen = exact or other
    if chosen is None:
        return {'summary': '', 'notes': [], 'notesStale': False}
    return {'summary': as_text(chosen.get('summary')), 'notes': clean_notes(chosen.get('notes')),
            'notesStale': exact is None}


def describes_removal(entry):
    """Notes about a deleted file talk about its old lines only. The same content, back when it was new, may
    have notes from an earlier commit: same blob, but they are not about the deletion."""
    return all(note['side'] == 'old' for note in clean_notes(entry.get('notes')))


def as_text(value):
    return value if isinstance(value, str) else ''


def clean_notes(notes):
    """Notes exactly as the page expects them. A notes file comes with the repository: it is somebody else's
    text, and whatever is not the right kind of value (a line number that is not a number) is replaced."""
    cleaned = []
    for note in notes if isinstance(notes, list) else []:
        if not isinstance(note, dict):
            continue
        lines = note.get('lines')
        if not (isinstance(lines, list) and 1 <= len(lines) <= 2 and all(type(n) is int for n in lines)):
            lines = [1, 1]
        first = max(lines[0], 1)
        cleaned.append({'lines': [first, max(lines[-1], first)], 'side': 'old' if note.get('side') == 'old' else 'new',
                        'title': as_text(note.get('title')), 'text': as_text(note.get('text'))})
    return cleaned


def annotate_files(repo, commit, files):
    """Marks the files that have notes, collects the overviews of the note sets that describe this commit and
    estimates the tokens spent writing notes, for this commit and for the whole repository."""
    sets = load_note_sets(repo)
    by_path = {}
    for note_set in sets:
        for entry in note_set.get('files', []):
            by_path.setdefault(entry.get('path'), []).append((note_set, entry))
    overviews, seen, errors = [], set(), [s for s in sets if s.get('error')]
    for f in files:
        candidates = by_path.get(f['path'])
        if not candidates:
            continue
        blob = f['oldBlob'] if f['status'] == 'D' else f['newBlob']
        if commit == WORKING and f['status'] != 'D':
            blob = working_blob(repo, f['path'])
        for note_set, entry in candidates:
            if entry.get('blob') == blob and (f['status'] != 'D' or describes_removal(entry)):
                f['notes'] = len(clean_notes(entry.get('notes')))
                f['summary'] = as_text(entry.get('summary'))
                if note_set['name'] not in seen:
                    seen.add(note_set['name'])
                    overviews.append({'name': note_set['name'], 'title': as_text(note_set.get('title')),
                                      'overview': as_text(note_set.get('overview')),
                                      'tokens': estimated_tokens(note_set['chars'])})
        if 'notes' not in f:
            f['notesStale'] = True
    earlier = earlier_passes(repo, commit, files, [s for s in sets if s['name'] not in seen and not s.get('error')])
    spent = [s for s in sets if s['name'] in seen] + earlier
    cost = {'files': len(spent), 'earlier': len(earlier), 'tokens': estimated_tokens(sum(s['chars'] for s in spent)),
            'repoFiles': len(sets), 'repoTokens': estimated_tokens(sum(s['chars'] for s in sets)),
            'charsPerToken': CHARS_PER_TOKEN}
    return overviews, [{'name': s['name'], 'error': s['error']} for s in errors], cost


def earlier_passes(repo, commit, files, unmatched):
    """The notes files of this commit that later ones replaced: a file explained again has a new blob, so the
    first notes no longer match anything, but writing them was part of the work. They are recognised by their
    paths (at least one file of the commit) and by when they were written: after the parent was committed and,
    for a commit, before it. Committer times are used, so after an amend or a rebase some may be missed."""
    paths = {f['path'] for f in files}
    if commit == WORKING:
        start, end = (commit_time(repo, 'HEAD') if has_commits(repo) else None), None
    else:
        parent = first_parent(repo, commit)
        start, end = (None if parent == EMPTY_TREE else commit_time(repo, parent)), commit_time(repo, commit)
    return [s for s in unmatched
            if (start is None or s['written'] > start) and (end is None or s['written'] <= end)
            and any(entry.get('path') in paths for entry in s.get('files', []) if isinstance(entry, dict))]


def commit_time(repo, revision):
    return int(text(git(repo, ['log', '-1', '--format=%ct', revision])).strip())


def ensure_notes_dir(repo):
    """Creates <repository>/.aigrasp and hides it from git for this clone only (nothing to commit or push)."""
    folder = os.path.join(repo, NOTES_DIR)
    os.makedirs(folder, exist_ok=True)
    try:
        git_dir = text(git(repo, ['rev-parse', '--git-common-dir'])).strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(repo, git_dir)
        exclude = os.path.join(git_dir, 'info', 'exclude')
        existing = ''
        if os.path.exists(exclude):
            with open(exclude, encoding='utf-8', errors='replace') as f:
                existing = f.read()
        if NOTES_DIR + '/' not in existing.split():
            os.makedirs(os.path.dirname(exclude), exist_ok=True)
            with open(exclude, 'a', encoding='utf-8') as f:
                f.write(('' if existing.endswith('\n') or not existing else '\n') + NOTES_DIR + '/\n')
    except (GitError, OSError):
        pass
    return folder


def notes_template(repo, commit, extensions):
    """An empty notes file for the files a commit (or the uncommitted work) changed: paths and blobs filled in."""
    files = []
    for f in commit_files(repo, commit):
        if extensions and f['ext'] not in extensions:
            continue
        if f['binary']:
            continue
        blob = f['oldBlob'] if f['status'] == 'D' else f['newBlob']
        if commit == WORKING and f['status'] != 'D':
            blob = working_blob(repo, f['path'])
        files.append({'path': f['path'], 'status': f['status'], 'blob': blob, 'summary': '', 'notes': []})
    return {'title': '', 'overview': '', 'files': files}


def blob_at(repo, revision, path):
    """The blob of a file in a commit, or None when the commit does not have it."""
    try:
        return text(git(repo, ['rev-parse', '--verify', '--quiet', revision + ':' + path])).strip() or None
    except GitError:
        return None


def line_count(repo, path, blob, current):
    """How many lines a version of a file has; None when git no longer has that version."""
    try:
        if blob == current:
            with open(os.path.join(repo, path), 'rb') as f:
                lines = read_lines(f.read())
        else:
            lines = read_lines(git(repo, ['cat-file', 'blob', blob]))
    except (GitError, OSError):
        return None
    return None if lines is None else len(lines)


def check_notes(repo, only):
    """What is wrong with the notes of a repository, as (report lines, problems).

    A problem is something the viewer cannot show properly: a file that is not valid JSON, a note without its
    text, a note that points outside the file. Notes written for an older version of a file are normal (they
    belong to an older commit) and are only reported, unless one notes file is being checked on its own:
    that is done right after writing it, when every entry must describe the file as it is now.
    """
    report, problems = [], []
    sets = load_note_sets(repo)
    for note_set in sets:
        name = note_set['name']
        if only and name != only:
            continue
        chars = note_set['chars']
        report.append('%s   %d characters, about %d tokens' % (name, chars, estimated_tokens(chars)))
        if note_set.get('error'):
            problems.append('%s: not valid JSON: %s' % (name, note_set['error']))
            continue
        for entry in note_set.get('files', []):
            path, blob = entry.get('path'), entry.get('blob')
            if not path or not blob:
                problems.append('%s: an entry without "path" or "blob"' % name)
                continue
            current = working_blob(repo, path) if os.path.isfile(os.path.join(repo, path)) else None
            committed = blob_at(repo, 'HEAD', path)
            if blob == current:
                version, previous = 'working folder', None if blob == committed else committed
            elif current is None and blob == committed:
                version, previous = 'deleted, not committed', blob        # the notes describe what was removed
            elif blob == committed:
                version, previous = 'last commit', blob_at(repo, 'HEAD~1', path)
            elif current is None and committed is None and blob == blob_at(repo, 'HEAD~1', path):
                version, previous = 'deleted by the last commit', blob
            else:
                version, previous = 'OLDER VERSION', None
                if only:
                    problems.append('%s: %s: the blob is not the file as it is now (%s)'
                                    % (name, path, current or committed or 'file not found'))
            counts = {'new': line_count(repo, path, blob, current),
                      'old': line_count(repo, path, previous, current) if previous else None}
            notes = entry.get('notes', [])
            report.append('  %-26s %2d notes  %s' % (version, len(notes), path))
            if not entry.get('summary'):
                problems.append('%s: %s: no "summary"' % (name, path))
            for index, note in enumerate(notes, 1):
                where = '%s: %s: note %d' % (name, path, index)
                lines, side = note.get('lines'), note.get('side', 'new')
                if not note.get('title') or not note.get('text'):
                    problems.append(where + ': no "title" or no "text"')
                if side not in ('new', 'old'):
                    problems.append(where + ': "side" must be "new" or "old"')
                    continue
                if (not isinstance(lines, list) or len(lines) != 2 or not all(isinstance(n, int) for n in lines)
                        or not 1 <= lines[0] <= lines[1]):
                    problems.append(where + ': "lines" must be [first, last], from 1, first <= last')
                elif counts[side] is not None and lines[1] > counts[side]:
                    problems.append('%s: lines %s go past the end of the %s file (%d lines)'
                                    % (where, lines, side, counts[side]))
    if only and not report:
        problems.append('%s: no such file in %s' % (only, os.path.join(repo, NOTES_DIR)))
    if sets and not only:
        chars = sum(s['chars'] for s in sets)
        report.append('\nAll the notes: %d files, %d characters, about %d tokens'
                      % (len(sets), chars, estimated_tokens(chars)))
    return report, problems


# ---------------------------------------------------------------------------------------------------------------
# The web server
# ---------------------------------------------------------------------------------------------------------------

class State:
    repo = None


def pick_folder():
    """Opens the system's folder dialog. It runs in its own process: Tk wants a main thread of its own."""
    script = ("import tkinter, tkinter.filedialog as d\n"
              "r = tkinter.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
              "print(d.askdirectory(title='Choose a git repository') or '')\n")
    try:
        done = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=600)
        return text(done.stdout).strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


class Handler(BaseHTTPRequestHandler):
    server_version = 'AIGrasp'

    def log_message(self, *args):
        pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def local_host(self):
        """A browser led to this server through another site's name (DNS rebinding) announces that name here."""
        return (self.headers.get('Host') or '').rsplit(':', 1)[0] in ('127.0.0.1', 'localhost')

    def allowed(self):
        """Only the page opened by whoever started this run may call the API: it alone has the token."""
        return self.local_host() and secrets.compare_digest(self.headers.get('X-Token') or '', TOKEN)

    def send_page(self):
        """The page carries no secret. What it may do is fixed here: run its own script, talk to this server.
        Even text injected into it could not run as a script or send anything anywhere else."""
        nonce = secrets.token_urlsafe(16)
        with open(os.path.join(APP_DIR, 'index.html'), encoding='utf-8') as f:
            body = f.read().replace('__NONCE__', nonce).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; script-src 'nonce-%s'; style-src 'unsafe-inline'; connect-src 'self'; "
                         "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" % nonce)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self, body=None):
        url = urlparse(self.path)
        if not self.local_host():
            self.send_error(403)
            return
        if url.path in ('/', '/index.html'):
            self.send_page()
            return
        if not url.path.startswith('/api/'):
            self.send_error(404)
            return
        if not self.allowed():
            self.send_json({'error': 'Not allowed.'}, 403)
            return
        try:
            self.send_json(self.api(url.path[5:], {k: v[0] for k, v in parse_qs(url.query).items()}, body))
        except GitError as error:
            self.send_json({'error': str(error)}, 400)
        except Exception as error:                                        # a bug must reach the page, not the void
            self.send_json({'error': type(error).__name__ + ': ' + str(error)}, 500)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length)) if 0 < length <= 1024 * 1024 else None
        except ValueError:
            body = None
        self.do_GET(body)

    def api(self, name, query, body=None):
        if name == 'state':
            return self.state()
        if name == 'repo':
            root = repo_root(query.get('path', '').strip().strip('"'))
            if root is None:
                raise GitError('That folder is not inside a git repository.')
            State.repo = root
            remember_repo(root)
            return self.state()
        if name == 'pick-folder':
            return {'path': pick_folder()}
        if name == 'language':
            config = load_config()
            config['language'] = 'it' if query.get('value') == 'it' else 'en'
            save_config(config)
            return self.state()

        repo = State.repo
        if repo is None:
            raise GitError('No repository chosen yet.')
        commit = query.get('commit', '')
        if name in ('files', 'file', 'refs') and commit != WORKING and not re.fullmatch(r'[0-9a-f]{7,40}', commit):
            raise GitError('Unknown commit.')

        if name == 'commits':
            skip = int(query.get('skip', 0))
            commits = list_commits(repo, min(int(query.get('limit', 80)), 500), skip,
                                   query.get('all') == '1', query.get('q', '').strip())
            return {'commits': commits, 'dirty': skip == 0 and is_dirty(repo)}
        if name == 'files':
            files = commit_files(repo, commit)
            overviews, errors, cost = annotate_files(repo, commit, files)
            return {'files': files, 'overviews': overviews, 'noteErrors': errors, 'notesCost': cost}
        if name == 'file':
            return file_view(repo, commit, query.get('path', ''), query.get('force') == '1')
        if name == 'refs':
            names = body.get('names') if isinstance(body, dict) else None
            return {'refs': resolve_references(repo, commit, query.get('path', ''), names if isinstance(names, list) else [])}
        raise GitError('Unknown request: ' + name)

    def state(self):
        repo = State.repo
        config = load_config()
        info = {'repo': repo, 'recent': config.get('recent', []), 'branch': None,
                'name': os.path.basename(repo) if repo else None,
                'language': 'it' if config.get('language') == 'it' else 'en'}
        if repo and has_commits(repo):
            info['branch'] = text(git(repo, ['rev-parse', '--abbrev-ref', 'HEAD'])).strip()
        return info


class LocalServer(ThreadingHTTPServer):
    # On Windows "reuse the address" lets a second program listen on the same port and take the requests
    allow_reuse_address = os.name != 'nt'


def serve(repo, port, open_browser):
    State.repo = repo
    if repo:
        remember_repo(repo)
    server = None
    for candidate in range(port, port + 20):
        try:
            server = LocalServer(('127.0.0.1', candidate), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit('No free port between %d and %d.' % (port, port + 19))
    url = 'http://127.0.0.1:%d/#t=%s' % (server.server_address[1], TOKEN)
    print('AIGrasp: ' + url + ('   (' + repo + ')' if repo else ''))
    print('Close this window, or press Ctrl+C, to stop it.')
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    arguments = sys.argv[1:]
    if not {'-h', '--help'} & set(arguments):     # reading the help is not using the program
        require_licence()
    if arguments and arguments[0] == 'template':
        parser = argparse.ArgumentParser(prog='aigrasp.py template')
        parser.add_argument('repository', nargs='?', default='.')
        parser.add_argument('--commit', default=WORKING, help='a commit hash (default: the uncommitted changes)')
        parser.add_argument('--ext', nargs='*', default=[], help='only these extensions, e.g. --ext .cs .py')
        options = parser.parse_args(arguments[1:])
        repo = repo_root(os.path.abspath(options.repository))
        if repo is None:
            sys.exit('Not a git repository: ' + options.repository)
        ensure_notes_dir(repo)
        commit = options.commit if options.commit == WORKING else text(git(repo, ['rev-parse', options.commit])).strip()
        extensions = {e.lower() if e.startswith('.') else '.' + e.lower() for e in options.ext}
        json.dump(notes_template(repo, commit, extensions), sys.stdout, indent=2, ensure_ascii=False)
        print()
        return

    if arguments and arguments[0] == 'check':
        parser = argparse.ArgumentParser(prog='aigrasp.py check')
        parser.add_argument('repository', nargs='?', default='.')
        parser.add_argument('--file', help='only this notes file (its name inside .aigrasp), just written')
        options = parser.parse_args(arguments[1:])
        repo = repo_root(os.path.abspath(options.repository))
        if repo is None:
            sys.exit('Not a git repository: ' + options.repository)
        report, problems = check_notes(repo, options.file)
        print('\n'.join(report))
        if problems:
            sys.exit('\nPROBLEMS\n  ' + '\n  '.join(problems))
        print('\nNo problems.')
        return

    parser = argparse.ArgumentParser(description='Study what each commit changed, file by file.')
    parser.add_argument('repository', nargs='?', help='a folder inside a git repository (default: the current folder)')
    parser.add_argument('--port', type=int, default=8777)
    parser.add_argument('--no-browser', action='store_true', help="don't open the browser")
    options = parser.parse_args(arguments)
    repo = repo_root(os.path.abspath(options.repository or '.'))
    if repo is None and options.repository:
        sys.exit('Not a git repository: ' + options.repository)
    if repo is None:
        recent = [r for r in load_config().get('recent', []) if repo_root(r)]
        repo = recent[0] if recent else None
    serve(repo, options.port, not options.no_browser)


if __name__ == '__main__':
    main()
