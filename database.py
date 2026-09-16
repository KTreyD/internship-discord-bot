import os
import sqlite3

# On Fly.io this is pointed at the mounted volume (e.g. /data/internships.db)
# so the dedup database survives redeploys instead of resetting on the
# ephemeral container filesystem and re-posting every job.
DB_PATH = os.getenv("DB_PATH", "internships.db")

def create_connection():
    connection = sqlite3.connect(DB_PATH)
    return connection

def create_table(connection):
    cursor = connection.cursor()
    sql = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_url TEXT UNIQUE NOT NULL,
        title TEXT,
        company TEXT,
        majors TEXT,
        date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        posted_to_discord INTEGER DEFAULT 0,
        discord_channel_ids TEXT
    )
    """
    cursor.execute(sql)
    connection.commit()

def insert_job(connection, job_data):
    cursor = connection.cursor()
    sql = """
    INSERT INTO jobs (job_url,title,company,majors,posted_to_discord,discord_channel_ids)
    VALUES (?,?,?,?,?,?)
"""
    values = (job_data["url"],job_data["title"],job_data["company"],job_data["majors"],job_data["posted"],job_data["channelIDs"])
    cursor.execute(sql,values)
    connection.commit()

def check_job_exists(connection, job_url):
    cursor = connection.cursor()
    sql = "SELECT job_url FROM jobs WHERE job_url = ?"
    cursor.execute(sql, (job_url,))
    row = cursor.fetchone()
    if row is not None:
        return True
    else:
        return False

def update_posted_status(connection, job_url, channel_ids):
    cursor = connection.cursor()
    sql = """
    UPDATE jobs
    SET posted_to_discord = 1, discord_channel_ids = ?
    WHERE job_url = ?

"""
    channelids = ','.join(str(id) for id in channel_ids)
    cursor.execute(sql,(channelids,job_url,))
    connection.commit()

#def get_all_jobs():

if __name__ == "__main__":
    conn = create_connection()
    print("Connection created!")
    
    create_table(conn)
    print("Table created!")
    
    # Test inserting a job
    #test_job = {
       # "url": "https://example.com/job2",
       # "title": "Software Engineer Intern",
        #"company": "Google",
        #"majors": "computer,electrical",
        #"posted": 0,
        #"channelIDs": ""
   # }
    
   # insert_job(conn, test_job)
    #print("Job inserted!")

    #cursor = conn.cursor()
    #cursor.execute("SELECT * FROM jobs")
    #rows = cursor.fetchall()
    #print("Jobs in database:", rows)

    print("Checking if job1 exists:", check_job_exists(conn, "https://example.com/job1"))
    print("Checking if job999 exists:", check_job_exists(conn, "https://example.com/job999"))

    print("Before update:")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_url = ?", ("https://example.com/job1",))
    print(cursor.fetchone())

    update_posted_status(conn, "https://example.com/job1", [123456, 789012])

    print("After update:")
    cursor.execute("SELECT * FROM jobs WHERE job_url = ?", ("https://example.com/job1",))
    print(cursor.fetchone())
