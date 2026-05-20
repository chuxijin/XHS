import os
from pathlib import Path
from shutil import copy, copytree
from distutils.sysconfig import get_python_lib
import sys


# https://blog.csdn.net/qq_25262697/article/details/129302819
# https://www.cnblogs.com/happylee666/articles/16158458.html
args = [
    'nuitka',
    '--standalone',
    '--windows-disable-console',
    '--follow-import-to=app',
    '--plugin-enable=pyside6,numpy',
    '--include-qt-plugins=sensible,styles',
    '--msvc=latest',
    '--show-memory',
    '--show-progress',
    '--windows-icon-from-ico=app/resource/images/logo.ico',
    '--include-module=app',
    '--nofollow-import-to=numpy,scipy,PIL,pywin,colorthief,pycryptodome',
    '--follow-import-to=win32com,win32gui,win32print,qfluentwidgets,qfluentwidgetspro,app',
    '--output-dir=dist/gallery',
    'gallery.py',
]
os.system(' '.join(args))

# copy site-packages to dist folder
dist_folder = Path("dist/gallery/gallery.dist")
site_packages = Path(get_python_lib())

copied_libs = [
    "numpy", "numpy.libs", "scipy", "scipy.libs",
    "PIL", "Crypto", "urllib3", "colorthief.py"
]

for src in copied_libs:
    src = site_packages / src
    dist = dist_folder / src.name

    print(f"Coping site-packages `{src}` to `{dist}`")

    if src.is_file():
        copy(src, dist)
    else:
        copytree(src, dist)


# copy standard library
copied_files = ["ctypes", "hashlib.py", "hmac.py", "random.py", "secrets.py", "uuid.py"]
for file in copied_files:
    src = site_packages.parent / file
    dist = dist_folder / src.name

    print(f"Coping stand library `{src}` to `{dist}`")

    if src.is_file():
        copy(src, dist)
    else:
        copytree(src, dist)


# copy pyd
suffix = ".pyd" if sys.platform == "win32" else ".so"
copied_dlls = ["_uuid"]
for dll in copied_dlls:
    src = site_packages.parent.parent / "DLLs" / (dll + suffix)
    dist = dist_folder / src.name

    print(f"Coping stand library `{src}` to `{dist}`")
    copy(src, dist)
