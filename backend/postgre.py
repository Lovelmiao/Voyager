import psycopg

conn = psycopg.connect(
    "postgresql://postgres:postgre@localhost:5432/agent",
    autocommit=True
)

with open("init.sql", "r", encoding="utf-8") as f:
    sql = f.read()

with conn.cursor() as cur:
    cur.execute(sql)

print("数据库初始化完成！")

conn.close()