import sqlite3

conn = sqlite3.connect('scraper.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS scraper_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_added TEXT NOT NULL,
    instagram_url TEXT NOT NULL,
    username TEXT,
    followers TEXT,
    posts TEXT,
    platform TEXT,
    store_url TEXT,
    products_count INTEGER,
    products_json TEXT,
    website_content TEXT,
    status TEXT,
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()
conn.close()
print("✓ Database schema created: scraper.db")
