import sqlite3
con = sqlite3.connect("data/audit.db")
cur = con.cursor()
print("tool_calls:", cur.execute("select count(*) from tool_calls").fetchone()[0])
rows = cur.execute("select tool_name, ok, duration_ms from tool_calls order by id desc limit 5").fetchall()
for r in rows:
    print(r)
con.close()