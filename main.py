"""FastAPI backend for Snippets CLI."""

import os
from contextlib import asynccontextmanager
from datetime import datetime

import psycopg2.errors
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import auth as auth_module
import db

load_dotenv()


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ.get("DATABASE_URL", "postgresql://localhost/snippets")
    app.state.conn = db.init_db(database_url)
    yield
    app.state.conn.close()


_debug = os.environ.get("DEBUG", "false").lower() == "true"
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if _debug else None,
    redoc_url="/redoc" if _debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Auth dependency ---

_bearer = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Security(_bearer)) -> int:
    user_id = auth_module.decode_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


# --- Helpers ---

def to_dict(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def to_list(rows) -> list[dict]:
    return [to_dict(r) for r in rows]


def get_conn():
    return app.state.conn


# --- Pydantic models ---

class RegisterBody(BaseModel):
    email: str
    password: str


class CreateNoteBody(BaseModel):
    body: str
    source_id: int | None = None
    locator_type: str | None = None
    locator_value: str | None = None


class UpdateNoteSourceBody(BaseModel):
    source_id: int


class NoteIdsBody(BaseModel):
    note_ids: list[int]


class BulkSourceBody(BaseModel):
    note_ids: list[int]
    source_id: int


class AddTagToNoteBody(BaseModel):
    tag_id: int


class CreateSourceBody(BaseModel):
    name: str
    source_type_id: int | None = None
    year: str | None = None
    url: str | None = None
    accessed_date: str | None = None
    edition: str | None = None
    pages: str | None = None
    extra_notes: str | None = None
    publisher_id: int | None = None


class AddAuthorBody(BaseModel):
    first_name: str
    last_name: str
    order: int


class CreateSourceTypeBody(BaseModel):
    name: str


class GetOrCreatePublisherBody(BaseModel):
    name: str
    city: str | None = None


class GetOrCreateTagBody(BaseModel):
    name: str


# --- Health ---

@app.get("/health")
def health():
    return {"status": "ok"}


# --- Auth ---

@app.post("/auth/register")
def register(body: RegisterBody):
    conn = get_conn()
    if db.get_user_by_email(conn, body.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    hashed = auth_module.hash_password(body.password)
    user_id = db.create_user(conn, body.email, hashed)
    return {"token": auth_module.create_token(user_id)}


@app.post("/auth/login")
def login(body: RegisterBody):
    conn = get_conn()
    user = db.get_user_by_email(conn, body.email)
    if not user or not auth_module.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"token": auth_module.create_token(user["id"])}


# --- Notes ---

@app.post("/notes")
def create_note(body: CreateNoteBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    note_id = db.create_note(
        conn, body.body, user_id,
        source_id=body.source_id,
        locator_type=body.locator_type,
        locator_value=body.locator_value,
    )
    return {"id": note_id}


@app.get("/notes/sourceless-check")
def get_sourceless_notes_get():
    raise HTTPException(status_code=405, detail="Use POST")


@app.post("/notes/sourceless-check")
def get_sourceless_notes(body: NoteIdsBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return db.get_sourceless_notes(conn, body.note_ids, user_id)


@app.post("/notes/bulk-source")
def bulk_update_note_source(body: BulkSourceBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    db.bulk_update_note_source(conn, body.note_ids, body.source_id, user_id)
    return {"ok": True}


@app.post("/notes/tags/batch")
def get_tags_for_notes(body: NoteIdsBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    result = db.get_tags_for_notes(conn, body.note_ids)
    return {str(k): to_list(v) for k, v in result.items()}


@app.get("/notes")
def get_notes(
    source_id: int | None = Query(default=None),
    tag_id: int | None = Query(default=None),
    author_id: int | None = Query(default=None),
    user_id: int = Depends(get_current_user),
):
    conn = get_conn()
    if source_id is not None:
        return to_list(db.get_notes_by_source(conn, source_id, user_id))
    if tag_id is not None:
        return to_list(db.get_notes_by_tag(conn, tag_id, user_id))
    if author_id is not None:
        return to_list(db.get_notes_by_author(conn, author_id, user_id))
    return to_list(db.get_all_notes(conn, user_id))


@app.get("/notes/{note_id}")
def get_note(note_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    row = db.get_note(conn, note_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return to_dict(row)


@app.patch("/notes/{note_id}/source")
def update_note_source(note_id: int, body: UpdateNoteSourceBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    db.update_note_source(conn, note_id, body.source_id, user_id)
    return {"ok": True}


@app.get("/notes/{note_id}/tags")
def get_tags_for_note(note_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    if db.get_note(conn, note_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return to_list(db.get_tags_for_note(conn, note_id))


@app.post("/notes/{note_id}/tags")
def add_tag_to_note(note_id: int, body: AddTagToNoteBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    if db.get_note(conn, note_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Note not found")
    db.add_tag_to_note(conn, note_id, body.tag_id)
    return {"ok": True}


@app.delete("/notes/{note_id}/tags/{tag_id}")
def remove_tag_from_note(note_id: int, tag_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    if db.get_note(conn, note_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Note not found")
    db.remove_tag_from_note(conn, note_id, tag_id)
    return {"ok": True}


# --- Sources ---

@app.post("/sources")
def create_source(body: CreateSourceBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    source_id = db.create_source(
        conn, body.name, user_id,
        source_type_id=body.source_type_id,
        year=body.year,
        url=body.url,
        accessed_date=body.accessed_date,
        edition=body.edition,
        pages=body.pages,
        extra_notes=body.extra_notes,
        publisher_id=body.publisher_id,
    )
    return {"id": source_id}


@app.get("/sources/recent")
def get_recent_sources(user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.get_recent_sources(conn, user_id))


@app.get("/sources/search")
def search_sources(q: str = Query(default=""), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.search_sources(conn, q, user_id))


@app.get("/sources")
def get_sources(
    author_last: str | None = Query(default=None),
    author_first: str | None = Query(default=None),
    user_id: int = Depends(get_current_user),
):
    conn = get_conn()
    if author_last is not None and author_first is not None:
        return to_list(db.get_sources_by_author(conn, author_last, author_first, user_id))
    return to_list(db.get_all_sources(conn, user_id))


@app.get("/sources/{source_id}/citation")
def get_citation(source_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    citation = db.build_citation(conn, source_id, user_id)
    return {"citation": citation}


@app.get("/sources/{source_id}/authors")
def get_authors_for_source(source_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    if db.get_source(conn, source_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return to_list(db.get_authors_for_source(conn, source_id))


@app.post("/sources/{source_id}/authors")
def add_author(source_id: int, body: AddAuthorBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    if db.get_source(conn, source_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
    author_id = db.add_author(conn, source_id, body.first_name, body.last_name, body.order)
    return {"id": author_id}


@app.get("/sources/{source_id}")
def get_source(source_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    row = db.get_source(conn, source_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return to_dict(row)


# --- Source Types ---

@app.get("/source-types")
def get_source_types(user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.get_source_types(conn))


@app.post("/source-types")
def create_source_type(body: CreateSourceTypeBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    try:
        type_id = db.create_source_type(conn, body.name)
        return {"id": type_id}
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Source type '{body.name}' already exists")


@app.get("/source-types/{type_id}")
def get_source_type(type_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    row = db.get_source_type(conn, type_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source type not found")
    return to_dict(row)


# --- Publishers ---

@app.get("/publishers/search")
def search_publishers(q: str = Query(default=""), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.search_publishers(conn, q))


@app.get("/publishers/cities")
def search_publisher_cities(q: str = Query(default=""), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return db.search_publisher_cities(conn, q)


@app.post("/publishers/get-or-create")
def get_or_create_publisher(body: GetOrCreatePublisherBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    pub_id = db.get_or_create_publisher(conn, body.name, body.city)
    return {"id": pub_id}


# --- Authors ---

@app.get("/authors")
def get_all_authors(user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.get_all_authors(conn, user_id))


@app.get("/authors/recent")
def get_recent_authors(user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.get_recent_authors(conn, user_id))


@app.get("/authors/search")
def search_authors(q: str = Query(default=""), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.search_authors(conn, q, user_id))


@app.get("/authors/last-names")
def search_author_last_names(q: str = Query(default=""), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return db.search_author_last_names(conn, q, user_id)


@app.get("/authors/first-names")
def search_author_first_names(q: str = Query(default=""), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return db.search_author_first_names(conn, q, user_id)


# --- Tags ---

@app.get("/tags/recent")
def get_recent_tags(user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.get_recent_tags(conn, user_id))


@app.get("/tags/search")
def search_tags(q: str = Query(default=""), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.search_tags(conn, q, user_id))


@app.get("/tags/by-name")
def get_tag_by_name(name: str = Query(), user_id: int = Depends(get_current_user)):
    conn = get_conn()
    row = db.get_tag_by_name(conn, name, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return to_dict(row)


@app.post("/tags/get-or-create")
def get_or_create_tag(body: GetOrCreateTagBody, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    tag_id = db.get_or_create_tag(conn, body.name, user_id)
    return {"id": tag_id}


@app.get("/tags")
def get_all_tags(user_id: int = Depends(get_current_user)):
    conn = get_conn()
    return to_list(db.get_all_tags(conn, user_id))


@app.get("/tags/{tag_id}")
def get_tag(tag_id: int, user_id: int = Depends(get_current_user)):
    conn = get_conn()
    row = db.get_tag(conn, tag_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return to_dict(row)
