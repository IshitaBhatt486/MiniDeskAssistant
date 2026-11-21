"""
Print the requirements that are not installed (or whose installed version doesn't match), one per line.
tools/deploy.sh runs this on the Pi and gives the output to pip, so only missing packages are installed.

    .venv/bin/python scripts/missing_packages.py requirements.txt requirements-companion.txt ...

Nothing is printed when everything is already installed. Uses only the standard library and the copy of
`packaging` that ships inside pip, so it works in a fresh venv.
"""

from __future__ import annotations

import sys
from importlib import metadata

try:
    from packaging.requirements import InvalidRequirement, Requirement
except ImportError:
    from pip._vendor.packaging.requirements import InvalidRequirement, Requirement


def missing(path):
    for raw in open(path, encoding="utf-8"):
        line = raw.split(" #")[0].split("\t#")[0].strip()
        if not line or line.startswith(("#", "-")):       # comments and pip options (-r, --index-url ...)
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement:
            yield line                                     # let pip deal with (and explain) anything unusual
            continue
        if req.marker and not req.marker.evaluate():
            continue                                       # not for this platform / Python
        try:
            version = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            yield line
            continue
        if req.specifier and not req.specifier.contains(version, prereleases=True):
            yield line


def main(paths):
    for path in paths:
        for line in missing(path):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
