from __future__ import annotations

from multiprocessing import freeze_support

from b2bdoc.desktop.main import main


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
