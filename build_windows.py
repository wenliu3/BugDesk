"""Build the portable Windows executable and delivery ZIP."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import argparse
import re
import hashlib
import struct

from app import VERSION

ROOT = Path(__file__).resolve().parent
RELEASE_DIR = ROOT / "release"
DELIVERY = RELEASE_DIR / "BugDesk-Windows"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release')
    args = parser.parse_args()
    if args.release and not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', args.release):
        parser.error('release must be a semantic version')
    if args.release and args.release != VERSION:
        parser.error('release must match the application version: ' + VERSION)
    if struct.calcsize('P') != 8:
        parser.error('the Windows x64 release requires a 64-bit Python interpreter')
    skill_root = ROOT / 'integrations' / 'bugdesk-workbuddy'
    skill_version = re.search(r'^version: (.+)$', (skill_root / 'SKILL.md').read_text(encoding='utf-8'), re.M)
    if not skill_version or skill_version.group(1).strip() != VERSION:
        parser.error('the bundled skill version must match the application version')
    license_path = next((Path(sys.base_prefix) / name for name in ('LICENSE.txt', 'LICENSE', 'LICENSE_PYTHON.txt')
                         if (Path(sys.base_prefix) / name).is_file()), None)
    if license_path is None:
        parser.error('Python license file is required for the portable distribution')
    delivery = RELEASE_DIR / ('BugDesk-Windows-' + args.release) if args.release else DELIVERY
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "BugDesk", "--icon", str(ROOT / "assets" / "bugdesk.ico"), "--version-file", str(ROOT / "assets" / "version.txt"), "--add-data", str(ROOT / "web") + ";web", str(ROOT / "app.py")], cwd=ROOT, check=True)
    delivery.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "dist" / "BugDesk.exe", delivery / "BugDesk.exe")
    shutil.copy2(ROOT / "使用说明.txt", delivery / "使用说明.txt")
    shutil.copy2(ROOT / "WorkBuddy接入说明.txt", delivery / "WorkBuddy接入说明.txt")
    shutil.copy2(ROOT / "LICENSE", delivery / "LICENSE")
    (delivery / "portable.flag").write_text("BugDesk stores drafts beside this file in BugDesk-data. Remove this flag to use the Windows local application-data directory.\n", encoding="utf-8")
    shutil.copy2(license_path, delivery / "Python-LICENSE.txt")
    archive = RELEASE_DIR / ('BugDesk-Windows-' + args.release + '.zip') if args.release else RELEASE_DIR / "BugDesk-Windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for name in ('BugDesk.exe', '使用说明.txt', 'WorkBuddy接入说明.txt', 'portable.flag', 'LICENSE', 'Python-LICENSE.txt'):
            item = delivery / name
            if item.is_file():
                package.write(item, "BugDesk-Windows/" + item.name)
    skill_archive = RELEASE_DIR / ('BugDesk-WorkBuddy-Skill-' + VERSION + '.zip')
    with zipfile.ZipFile(skill_archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for name in ('SKILL.md', 'scripts/bugdesk.ps1', 'references/schema.md'):
            package.write(skill_root / name, name)
        package.write(ROOT / 'LICENSE', 'LICENSE')
    standalone = RELEASE_DIR / ('BugDesk-' + VERSION + '-Windows-x64.exe')
    shutil.copy2(delivery / 'BugDesk.exe', standalone)
    checksums = RELEASE_DIR / 'SHA256SUMS.txt'
    checksums.write_text(''.join(hashlib.sha256(item.read_bytes()).hexdigest() + '  ' + item.name + '\n'
                                for item in (standalone, archive, skill_archive)), encoding='ascii')
    for item in (standalone, archive, skill_archive, checksums):
        print(str(item))

if __name__ == "__main__":
    main()
