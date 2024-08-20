import sqlite3
import uuid

DB_FILE_PATH = 'instance/site.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def update_journals_table(conn):
    conn.execute('ALTER TABLE journals ADD COLUMN uuid TEXT')
    journals = conn.execute('SELECT id FROM journals').fetchall()
    for journal in journals:
        conn.execute('UPDATE journals SET uuid = ? WHERE id = ?', (str(uuid.uuid4()), journal['id']))
    conn.execute('PRAGMA foreign_keys=off')
    conn.execute('CREATE TABLE journals_new (id TEXT PRIMARY KEY, user_id INTEGER, week_ending TEXT, data TEXT)')
    conn.execute('INSERT INTO journals_new (id, user_id, week_ending, data) SELECT uuid, user_id, week_ending, data FROM journals')
    conn.execute('DROP TABLE journals')
    conn.execute('ALTER TABLE journals_new RENAME TO journals')
    conn.execute('PRAGMA foreign_keys=on')

def update_journal_fields_table(conn):
    conn.execute('ALTER TABLE journal_fields ADD COLUMN uuid TEXT')
    journal_fields = conn.execute('SELECT id FROM journal_fields').fetchall()
    for field in journal_fields:
        conn.execute('UPDATE journal_fields SET uuid = ? WHERE id = ?', (str(uuid.uuid4()), field['id']))
    conn.execute('PRAGMA foreign_keys=off')
    conn.execute('CREATE TABLE journal_fields_new (id TEXT PRIMARY KEY, user_id INTEGER, field_name TEXT)')
    conn.execute('INSERT INTO journal_fields_new (id, user_id, field_name) SELECT uuid, user_id, field_name FROM journal_fields')
    conn.execute('DROP TABLE journal_fields')
    conn.execute('ALTER TABLE journal_fields_new RENAME TO journal_fields')
    conn.execute('PRAGMA foreign_keys=on')

def main():
    conn = get_db_connection()
    try:
        update_journals_table(conn)
        update_journal_fields_table(conn)
        conn.commit()
    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    main()
