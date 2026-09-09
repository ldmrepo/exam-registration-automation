"""Build only explicitly allowed public files; never bundle local evidence."""
from pathlib import Path
import hashlib
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = ['README.md', 'AGENTS.md', 'CLAUDE.md', 'install.ps1', 'CHANGELOG.md', '.gitignore']


def public_files():
    files = [ROOT / name for name in TOP]
    if (ROOT / 'LICENSE').exists():
        files.append(ROOT / 'LICENSE')
    for folder in ['skills', 'scripts', 'tests']:
        files.extend(p for p in (ROOT / folder).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.md', '.py', '.yaml'))
    return sorted(files)


def main():
    files = public_files()
    for path in files:
        content = path.read_text(encoding='utf-8')
        if re.search(r'twk_[A-Za-z0-9]{12}_[A-Za-z0-9_-]{40,}', content):
            raise SystemExit('API key pattern found: ' + str(path.relative_to(ROOT)))
        if re.search(r'[CD]:[/\\](?:Users|work)[/\\]', content, re.I):
            raise SystemExit('Personal path found: ' + str(path.relative_to(ROOT)))
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    archive = out / 'exam-registration-automation-0.1.0-windows.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, 'exam-registration-automation/' + path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='utf-8')
    print(f'Built {archive.name}: {len(files)} files; SHA256 {digest}')


if __name__ == '__main__':
    main()
