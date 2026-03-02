"""Database access layer for Snippets backend."""

from pathlib import Path

import psycopg2
import psycopg2.extras


def get_connection(database_url: str):
    conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def init_db(database_url: str):
    """Initialize DB: connect and run schema."""
    conn = get_connection(database_url)
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, "r") as f:
        sql = f.read()
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    return conn


# --- Users ---

def create_user(conn, email: str, password_hash: str) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
        (email, password_hash),
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def get_user_by_email(conn, email: str) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    return cur.fetchone()


# --- Notes ---

def create_note(conn, body: str, user_id: int, source_id: int | None = None,
                locator_type: str | None = None, locator_value: str | None = None) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notes (body, user_id, source_id, locator_type, locator_value) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (body, user_id, source_id, locator_type, locator_value),
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def update_note_source(conn, note_id: int, source_id: int, user_id: int):
    cur = conn.cursor()
    cur.execute(
        "UPDATE notes SET source_id = %s WHERE id = %s AND user_id = %s",
        (source_id, note_id, user_id),
    )
    conn.commit()


def get_note(conn, note_id: int, user_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM notes WHERE id = %s AND user_id = %s", (note_id, user_id))
    return cur.fetchone()


def get_all_notes(conn, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM notes WHERE user_id = %s ORDER BY created_at ASC", (user_id,))
    return cur.fetchall()


def get_notes_by_source(conn, source_id: int, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM notes WHERE source_id = %s AND user_id = %s ORDER BY created_at ASC",
        (source_id, user_id),
    )
    return cur.fetchall()


def get_notes_by_tag(conn, tag_id: int, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT n.* FROM notes n
           JOIN note_tags nt ON n.id = nt.note_id
           WHERE nt.tag_id = %s AND n.user_id = %s
           ORDER BY n.created_at ASC""",
        (tag_id, user_id),
    )
    return cur.fetchall()


def get_notes_by_author(conn, author_id: int, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT n.* FROM notes n
           JOIN sources s ON n.source_id = s.id
           JOIN source_authors sa ON sa.source_id = s.id
           WHERE sa.id = %s AND n.user_id = %s
           ORDER BY n.created_at ASC""",
        (author_id, user_id),
    )
    return cur.fetchall()


def get_sourceless_notes(conn, note_ids: list[int], user_id: int) -> list[int]:
    if not note_ids:
        return []
    placeholders = ",".join("%s" for _ in note_ids)
    cur = conn.cursor()
    cur.execute(
        f"SELECT id FROM notes WHERE id IN ({placeholders}) AND source_id IS NULL AND user_id = %s",
        note_ids + [user_id],
    )
    rows = cur.fetchall()
    return [r["id"] for r in rows]


def bulk_update_note_source(conn, note_ids: list[int], source_id: int, user_id: int):
    if not note_ids:
        return
    placeholders = ",".join("%s" for _ in note_ids)
    cur = conn.cursor()
    cur.execute(
        f"UPDATE notes SET source_id = %s WHERE id IN ({placeholders}) AND user_id = %s",
        [source_id] + note_ids + [user_id],
    )
    conn.commit()


# --- Sources ---

def create_source(conn, name: str, user_id: int, source_type_id: int | None = None,
                  year: str | None = None, url: str | None = None,
                  accessed_date: str | None = None, edition: str | None = None,
                  pages: str | None = None, extra_notes: str | None = None,
                  publisher_id: int | None = None) -> int:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sources (name, user_id, source_type_id, year, url, accessed_date, edition, pages, extra_notes, publisher_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, user_id, source_type_id, year, url, accessed_date, edition, pages, extra_notes, publisher_id),
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def get_source(conn, source_id: int, user_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM sources WHERE id = %s AND user_id = %s", (source_id, user_id))
    return cur.fetchone()


def search_sources(conn, prefix: str, user_id: int, limit: int = 20) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sources WHERE name ILIKE %s AND user_id = %s ORDER BY name LIMIT %s",
        (f"{prefix}%", user_id, limit),
    )
    return cur.fetchall()


def get_recent_sources(conn, user_id: int, limit: int = 10) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT s.* FROM sources s
           LEFT JOIN notes n ON n.source_id = s.id
           WHERE s.user_id = %s
           GROUP BY s.id
           ORDER BY MAX(COALESCE(n.created_at, s.created_at)) DESC
           LIMIT %s""",
        (user_id, limit),
    )
    return cur.fetchall()


def get_all_sources(conn, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM sources WHERE user_id = %s ORDER BY name", (user_id,))
    return cur.fetchall()


def get_sources_by_author(conn, author_last: str, author_first: str, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT s.* FROM sources s
           JOIN source_authors sa ON sa.source_id = s.id
           WHERE LOWER(sa.last_name) = LOWER(%s) AND LOWER(sa.first_name) = LOWER(%s)
           AND s.user_id = %s
           ORDER BY s.name""",
        (author_last, author_first, user_id),
    )
    return cur.fetchall()


# --- Source Types ---

def get_source_types(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM source_types ORDER BY id")
    return cur.fetchall()


def get_source_type(conn, type_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM source_types WHERE id = %s", (type_id,))
    return cur.fetchone()


def create_source_type(conn, name: str) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO source_types (name) VALUES (%s) RETURNING id", (name,))
    row = cur.fetchone()
    conn.commit()
    return row["id"]


# --- Publishers ---

def find_publisher(conn, name: str) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM source_publishers WHERE LOWER(name) = LOWER(%s)", (name,))
    return cur.fetchone()


def create_publisher(conn, name: str, city: str | None = None) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO source_publishers (name, city) VALUES (%s, %s) RETURNING id", (name, city)
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def get_or_create_publisher(conn, name: str, city: str | None = None) -> int:
    existing = find_publisher(conn, name)
    if existing:
        return existing["id"]
    return create_publisher(conn, name, city)


def search_publishers(conn, prefix: str, limit: int = 20) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM source_publishers WHERE name ILIKE %s ORDER BY name LIMIT %s",
        (f"{prefix}%", limit),
    )
    return cur.fetchall()


def search_publisher_cities(conn, prefix: str, limit: int = 20) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT city FROM source_publishers WHERE city IS NOT NULL AND city ILIKE %s ORDER BY city LIMIT %s",
        (f"{prefix}%", limit),
    )
    rows = cur.fetchall()
    return [r["city"] for r in rows]


# --- Authors ---

def add_author(conn, source_id: int, first_name: str, last_name: str, order: int) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO source_authors (source_id, first_name, last_name, author_order) VALUES (%s, %s, %s, %s) RETURNING id",
        (source_id, first_name, last_name, order),
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def get_authors_for_source(conn, source_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM source_authors WHERE source_id = %s ORDER BY author_order",
        (source_id,),
    )
    return cur.fetchall()


def get_all_authors(conn, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT sa.* FROM source_authors sa
           JOIN sources s ON sa.source_id = s.id
           WHERE s.user_id = %s
           ORDER BY sa.last_name, sa.first_name""",
        (user_id,),
    )
    return cur.fetchall()


def get_recent_authors(conn, user_id: int, limit: int = 10) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT sa.* FROM source_authors sa
           JOIN sources s ON sa.source_id = s.id
           WHERE s.user_id = %s
           GROUP BY sa.id, sa.source_id, sa.first_name, sa.last_name, sa.author_order
           ORDER BY MAX(s.created_at) DESC
           LIMIT %s""",
        (user_id, limit),
    )
    return cur.fetchall()


def search_authors(conn, prefix: str, user_id: int, limit: int = 20) -> list[dict]:
    p = f"{prefix}%"
    cur = conn.cursor()
    cur.execute(
        """SELECT sa.* FROM source_authors sa
           JOIN sources s ON sa.source_id = s.id
           WHERE (sa.last_name ILIKE %s OR sa.first_name ILIKE %s) AND s.user_id = %s
           ORDER BY sa.last_name, sa.first_name LIMIT %s""",
        (p, p, user_id, limit),
    )
    return cur.fetchall()


def search_author_last_names(conn, prefix: str, user_id: int, limit: int = 20) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT sa.last_name FROM source_authors sa
           JOIN sources s ON sa.source_id = s.id
           WHERE sa.last_name ILIKE %s AND s.user_id = %s
           ORDER BY sa.last_name LIMIT %s""",
        (f"{prefix}%", user_id, limit),
    )
    rows = cur.fetchall()
    return [r["last_name"] for r in rows]


def search_author_first_names(conn, prefix: str, user_id: int, limit: int = 20) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT sa.first_name FROM source_authors sa
           JOIN sources s ON sa.source_id = s.id
           WHERE sa.first_name ILIKE %s AND s.user_id = %s
           ORDER BY sa.first_name LIMIT %s""",
        (f"{prefix}%", user_id, limit),
    )
    rows = cur.fetchall()
    return [r["first_name"] for r in rows]


# --- Tags ---

def get_or_create_tag(conn, name: str, user_id: int) -> int:
    name = name.strip().lower()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tags WHERE name = %s AND user_id = %s", (name, user_id))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        "INSERT INTO tags (name, user_id) VALUES (%s, %s) RETURNING id", (name, user_id)
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def get_tag(conn, tag_id: int, user_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM tags WHERE id = %s AND user_id = %s", (tag_id, user_id))
    return cur.fetchone()


def get_tag_by_name(conn, name: str, user_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tags WHERE name = %s AND user_id = %s", (name.strip().lower(), user_id)
    )
    return cur.fetchone()


def search_tags(conn, prefix: str, user_id: int, limit: int = 20) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tags WHERE name ILIKE %s AND user_id = %s ORDER BY name LIMIT %s",
        (f"{prefix.lower()}%", user_id, limit),
    )
    return cur.fetchall()


def get_all_tags(conn, user_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM tags WHERE user_id = %s ORDER BY name", (user_id,))
    return cur.fetchall()


def get_recent_tags(conn, user_id: int, limit: int = 10) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT t.* FROM tags t
           JOIN note_tags nt ON t.id = nt.tag_id
           JOIN notes n ON n.id = nt.note_id
           WHERE t.user_id = %s
           GROUP BY t.id, t.name, t.user_id
           ORDER BY MAX(n.created_at) DESC
           LIMIT %s""",
        (user_id, limit),
    )
    return cur.fetchall()


def add_tag_to_note(conn, note_id: int, tag_id: int):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO note_tags (note_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (note_id, tag_id),
    )
    conn.commit()


def remove_tag_from_note(conn, note_id: int, tag_id: int):
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM note_tags WHERE note_id = %s AND tag_id = %s",
        (note_id, tag_id),
    )
    conn.commit()


def get_tags_for_note(conn, note_id: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT t.* FROM tags t
           JOIN note_tags nt ON t.id = nt.tag_id
           WHERE nt.note_id = %s
           ORDER BY t.name""",
        (note_id,),
    )
    return cur.fetchall()


def get_tags_for_notes(conn, note_ids: list[int]) -> dict[int, list[dict]]:
    """Return {note_id: [tag_rows]} for a batch of note ids."""
    if not note_ids:
        return {}
    placeholders = ",".join("%s" for _ in note_ids)
    cur = conn.cursor()
    cur.execute(
        f"""SELECT nt.note_id, t.* FROM tags t
            JOIN note_tags nt ON t.id = nt.tag_id
            WHERE nt.note_id IN ({placeholders})
            ORDER BY t.name""",
        note_ids,
    )
    rows = cur.fetchall()
    result: dict[int, list] = {nid: [] for nid in note_ids}
    for r in rows:
        result[r["note_id"]].append(r)
    return result


# --- Citation ---

def build_citation(conn, source_id: int, user_id: int) -> str:
    """Build an MLA-ish citation string for a source."""
    src = get_source(conn, source_id, user_id)
    if not src:
        return ""
    parts = []
    authors = get_authors_for_source(conn, source_id)
    if authors:
        author_strs = []
        for a in authors:
            if a["last_name"] and a["first_name"]:
                author_strs.append(f'{a["last_name"]}, {a["first_name"]}')
            elif a["last_name"]:
                author_strs.append(a["last_name"])
            elif a["first_name"]:
                author_strs.append(a["first_name"])
        if len(author_strs) == 1:
            parts.append(author_strs[0] + ".")
        elif len(author_strs) == 2:
            parts.append(f"{author_strs[0]}, and {author_strs[1]}.")
        elif len(author_strs) > 2:
            parts.append(f"{author_strs[0]}, et al.")

    parts.append(f'*{src["name"]}*.')

    if src["source_type_id"]:
        st = get_source_type(conn, src["source_type_id"])
        if st:
            parts.append(st["name"] + ".")

    if src["edition"]:
        parts.append(f'{src["edition"]} ed.')

    if src["publisher_id"]:
        cur = conn.cursor()
        cur.execute("SELECT * FROM source_publishers WHERE id = %s", (src["publisher_id"],))
        pub = cur.fetchone()
        if pub:
            pub_str = pub["name"]
            if pub["city"]:
                pub_str = f'{pub["city"]}: {pub_str}'
            parts.append(pub_str + ",")

    if src["year"]:
        parts.append(f'{src["year"]}.')

    if src["pages"]:
        parts.append(f'pp. {src["pages"]}.')

    if src["url"]:
        parts.append(src["url"] + ".")

    if src["accessed_date"]:
        parts.append(f'Accessed {src["accessed_date"]}.')

    return " ".join(parts)
