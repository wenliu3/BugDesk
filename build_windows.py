"""Build the portable Windows executable and delivery ZIP."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import argparse
import re

ROOT = Path(__file__).resolve().parent
RELEASE_DIR = ROOT / "release"
DELIVERY = RELEASE_DIR / "BugDesk-Windows"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release')
    args = parser.parse_args()
    if args.release and not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', args.release):
        parser.error('release must be a semantic version')
    delivery = RELEASE_DIR / ('BugDesk-Windows-' + args.release) if args.release else DELIVERY
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "BugDesk", "--icon", str(ROOT / "assets" / "bugdesk.ico"), "--version-file", str(ROOT / "assets" / "version.txt"), "--add-data", str(ROOT / "web") + ";web", str(ROOT / "app.py")], cwd=ROOT, check=True)
    delivery.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "dist" / "BugDesk.exe", delivery / "BugDesk.exe")
    shutil.copy2(ROOT / "使用说明.txt", delivery / "使用说明.txt")
    shutil.copy2(ROOT / "LICENSE", delivery / "LICENSE")
    (delivery / "portable.flag").write_text("BugDesk stores drafts beside this file in BugDesk-data. Remove this flag to use the Windows local application-data directory.\n", encoding="utf-8")
    license_path = Path(sys.base_prefix) / "LICENSE.txt"
    if not license_path.exists():
        license_path = Path(sys.base_prefix) / "LICENSE"
    if license_path.exists():
        shutil.copy2(license_path, delivery / "Python-LICENSE.txt")
    archive = RELEASE_DIR / ('BugDesk-Windows-' + args.release + '.zip') if args.release else RELEASE_DIR / "BugDesk-Windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for name in ('BugDesk.exe', '使用说明.txt', 'portable.flag', 'LICENSE', 'Python-LICENSE.txt'):
            item = delivery / name
            if item.is_file():
                package.write(item, "BugDesk-Windows/" + item.name)
    print(str(archive))

if __name__ == "__main__":
    main()
