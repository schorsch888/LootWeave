"""Portable source identities; local installation paths stay runtime-only."""
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(value):
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def source_label(path, *, game=None, steam_manifest=None):
    path = Path(path).resolve()
    if steam_manifest is not None and path == Path(steam_manifest).resolve():
        return 'steam://appmanifest_4623570.acf'
    if game is not None:
        try:
            return 'game://' + path.relative_to(Path(game).resolve()).as_posix()
        except ValueError:
            pass
    try:
        return 'repo://' + path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return 'external://source'


def resolve_source(label, *, game=None, steam_manifest=None):
    if label.startswith('repo://'):
        base, relative = REPO_ROOT, label[7:]
    elif label.startswith('game://'):
        if game is None:
            raise ValueError('A game source requires --game or DESKRAWL_GAME_DIR.')
        base, relative = Path(game).resolve(), label[7:]
    elif label.startswith('steam://'):
        if steam_manifest is not None:
            return Path(steam_manifest).resolve()
        if game is None:
            raise ValueError('Steam build verification requires --game or --steam-manifest.')
        return Path(game).resolve().parents[1] / 'appmanifest_4623570.acf'
    else:
        # Read legacy private local exports without serializing their path again.
        return repo_path(label)
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('Source reference escapes its logical root.')
    return path


def safe_error(error):
    """Suppress host paths included in library exception messages."""
    text = str(error)
    text = re.sub(r'(?i)(?<![\w])(?:[a-z]:[\\/]|/(?:Users|home)/)[^\r\n\"\']+', '<local-path>', text)
    return text
