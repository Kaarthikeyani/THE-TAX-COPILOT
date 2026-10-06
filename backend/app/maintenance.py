"""Backup, restore, key check and data helpers.   Run from backend/:

  python -m app.maintenance backup                  copy the database to data/backups/
  python -m app.maintenance restore <file.db>       replace the database with a backup (current one is saved first)
  python -m app.maintenance key-check               can the stored SMS text still be decrypted with the current key?
  python -m app.maintenance add-rule KEYWORD category      append a merchant rule to data/user_rules.csv
  python -m app.maintenance add-example "TEXT" category    append a labelled training example
  python -m app.maintenance categories              list valid category names
Stop the server before `restore`.
"""
import csv
import shutil
import sys
from pathlib import Path

from .classifier import CATEGORY_META, USER_RULES_PATH
from .database import DB_PATH, backup_db
from .ml_classifier import TRAINING_CSV


def _need_cat(c):
    if c not in CATEGORY_META:
        sys.exit(f"Unknown category '{c}'. Run: python -m app.maintenance categories")


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "backup":
        p = backup_db("manual")
        print(f"Backup written: {p}" if p else "No database yet.")
    elif cmd == "restore":
        if not args:
            sys.exit("Usage: restore <backup.db>")
        src = Path(args[0])
        if not src.exists():
            sys.exit(f"Not found: {src}")
        if DB_PATH.exists():
            print(f"Current database saved first: {backup_db('before-restore')}")
        shutil.copyfile(src, DB_PATH)
        for ext in ("-wal", "-shm"):
            Path(str(DB_PATH) + ext).unlink(missing_ok=True)
        print(f"Restored {src.name}. Start the app again.")
    elif cmd == "key-check":
        from .database import SessionLocal
        from .models import Transaction
        from .security import decrypt_text, key_source
        ok = bad = 0
        with SessionLocal() as db:
            for (tok,) in db.query(Transaction.raw_encrypted).all():
                if not tok:
                    continue
                if decrypt_text(tok).startswith("[unable"):
                    bad += 1
                else:
                    ok += 1
        print(f"key source: {key_source()} | readable: {ok} | unreadable: {bad}")
        return 1 if bad else 0
    elif cmd == "add-rule":
        if len(args) != 2:
            sys.exit('Usage: add-rule KEYWORD category')
        _need_cat(args[1])
        with USER_RULES_PATH.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([args[0].upper(), args[1]])
        print("Added. Restart the app or call POST /model/retrain.")
    elif cmd == "add-example":
        if len(args) != 2:
            sys.exit('Usage: add-example "TEXT" category')
        _need_cat(args[1])
        with TRAINING_CSV.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([" ".join(args[0].split()).upper(), args[1]])
        print("Added. Call POST /model/retrain (or restart) to learn from it.")
    elif cmd == "categories":
        for k, v in CATEGORY_META.items():
            print(f"{k:24s} {v[0]:34s} tax section: {v[1]:8s} {'money in' if v[2] == 'income' else 'money out'}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
