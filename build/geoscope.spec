# Build from the repository root with: pyinstaller build/geoscope.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
datas = [
    (str(root / "app" / "templates"), "app/templates"),
    (str(root / "app" / "static"), "app/static"),
]
datas += collect_data_files("certifi")
a = Analysis(
    [str(root / "run_geoscope.py")],
    pathex=[str(root)],
    hiddenimports=collect_submodules("app") + ["certifi"],
    datas=datas,
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="GEOscope", console=False)
