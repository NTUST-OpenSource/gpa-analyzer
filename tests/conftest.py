import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "0EJmpb9ISlZCbEfSFEcfsTGkNCk0DAB5-vsSN1_wLTo=")
os.environ.setdefault("COOKIE_SECURE", "false")
