import sqlite3
import sys

user_key = sys.argv[1] if len(sys.argv) > 1 else "test_user"

con = sqlite3.connect("data/audit.db")
cur = con.cursor()

n = cur.execute(
    "SELECT COUNT(*) FROM memory_items WHERE user_key=?",
    (user_key,),
).fetchone()[0]

print(f"memory_items for {user_key} => {n}")

rows = cur.execute(
    "SELECT id, kind, substr(text,1,80) FROM memory_items WHERE user_key=? ORDER BY id DESC LIMIT 10",
    (user_key,),
).fetchall()

for r in rows:
    print(r)

con.close()