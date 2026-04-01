from __future__ import annotations

import os
import sys


_VENDOR_PATH = os.path.join(os.path.dirname(__file__), "vendor")
if _VENDOR_PATH not in sys.path:
    sys.path.insert(0, _VENDOR_PATH)

from .addon import register


register()
