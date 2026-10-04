"""Angel One details-ஐ .env file-ல் save செய்யும். (.env GitHub-க்கு போகாது)"""
import re
from getpass import getpass
from pathlib import Path
import pyotp

ROOT = Path(__file__).resolve().parent.parent
print("\n Angel One details type pannunga.")
print(" MPIN, TOTP secret type pannum podhu screen-la theriyaadhu. ORE THADAVAI type/paste panni Enter pannunga.\n")

api = input(" API Key       : ").strip()
client = input(" Client ID     : ").strip().upper()

while True:
    mpin = getpass(" MPIN (4 digit): ").strip()
    if re.fullmatch(r"\d{4}", mpin):
        print("   ✓ MPIN 4 digits OK")
        break
    print(f"   ✗ MPIN 4 numbers mattum irukkanum (neenga {len(mpin)} characters type panneenga). Thirumba type pannunga.")

while True:
    totp = getpass(" TOTP secret   : ").strip().replace(" ", "").upper()
    try:
        code = pyotp.TOTP(totp).now()
        if len(totp) < 16:
            raise ValueError
        print(f"   ✓ TOTP secret OK ({len(totp)} letters). Ippo code: {code}")
        print("     (Google Authenticator-la scan pannirundha, adhula irukura code-um idhuvum same-aa irukkanum)")
        break
    except Exception:
        print("   ✗ TOTP secret thappu. QR code keezha irukura neenda text code-a copy panni paste pannunga.")

(ROOT / ".env").write_text(
    f"BROKER=angel\nANGEL_API_KEY={api}\nANGEL_CLIENT_ID={client}\nANGEL_MPIN={mpin}\nANGEL_TOTP_SECRET={totp}\n",
    encoding="utf-8")
print("\n ✅ .env saved. Adutha step: python scripts/test_angel_login.py\n")
