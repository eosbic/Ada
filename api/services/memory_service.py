import os
import re
import json
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, Filter, FieldCondition, MatchValue

from langchain_google_genai import GoogleGenerativeAIEmbeddings


QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION = "agent_memory"
REPORTS_COLLECTION = "ada-excel-reports"
VECTOR_STORE1_COLLECTION = "vector_store1"
IMAGE_REPORTS_COLLECTION = "ada-image-reports"


client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    check_compatibility=False
)


embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    task_type="SEMANTIC_SIMILARITY",
    output_dimensionality=768,
)


def init_qdrant():
    try:
        collections = client.get_collections().collections
        names = [c.name for c in collections]

        for col in [COLLECTION, REPORTS_COLLECTION, VECTOR_STORE1_COLLECTION, IMAGE_REPORTS_COLLECTION]:
            if col not in names:
                client.create_collection(
                    collection_name=col,
                    vectors_config=VectorParams(size=768, distance=Distance.COSINE)
                )
                print(f"QDRANT: collection '{col}' created")
        _ensure_empresa_index(COLLECTION)
        _ensure_empresa_index(REPORTS_COLLECTION)
        _ensure_empresa_index(VECTOR_STORE1_COLLECTION)
        _ensure_empresa_index(IMAGE_REPORTS_COLLECTION)
    except Exception as e:
        print(f"QDRANT init warning: {e}")


def _ensure_empresa_index(collection_name: str):
    """Crea indice payload para filtro por empresa_id (requerido por Qdrant cloud)."""
    try:
        client.create_payload_index(
            collection_name=collection_name,
            field_name="empresa_id",
            field_schema="keyword",
            wait=True,
        )
        print(f"QDRANT: index 'empresa_id' ready on '{collection_name}'")
    except Exception as e:
        # Si ya existe o la API varía entre versiones, no romper startup.
        print(f"QDRANT: index ensure warning on '{collection_name}': {e}")


def search_memory(query: str, empresa_id: str = "") -> list:
    vector = embeddings.embed_query(query)
    query_filter = None
    if empresa_id:
        query_filter = Filter(
            must=[FieldCondition(key="empresa_id", match=MatchValue(value=empresa_id))]
        )
    results = client.query_points(
        collection_name=COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=5
    )
    return [r.payload.get("text", "") for r in results.points if r.payload.get("text")]


def store_memory(text: str, empresa_id: str = ""):
    vector = embeddings.embed_query(text)
    client.upsert(
        collection_name=COLLECTION,
        points=[{
            "id": str(uuid.uuid4()),
            "vector": vector,
            "payload": {"text": text, "empresa_id": empresa_id}
        }]
    )


def store_vector_knowledge(
    text: str,
    empresa_id: str,
    file_name: str = "",
    doc_type: str = "generic",
    metadata: dict | None = None,
    collection_name: str = VECTOR_STORE1_COLLECTION,
):
    vector = embeddings.embed_query(text)
    payload = {
        "text": text,
        "empresa_id": empresa_id,
        "file_name": file_name,
        "doc_type": doc_type,
        "metadata": metadata or {},
    }
    client.upsert(
        collection_name=collection_name,
        points=[{
            "id": str(uuid.uuid4()),
            "vector": vector,
            "payload": payload,
        }]
    )


def store_report(text: str, empresa_id: str, file_name: str, report_type: str = "excel"):
    vector = embeddings.embed_query(text)
    payload = {
        "text": text,
        "empresa_id": empresa_id,
        "file_name": file_name,
        "report_type": report_type,
    }
    client.upsert(
        collection_name=REPORTS_COLLECTION,
        points=[{
            "id": str(uuid.uuid4()),
            "vector": vector,
            "payload": payload,
        }]
    )

    # duplicate in vector store 1 for mandatory dual-source checks
    store_vector_knowledge(
        text=text,
        empresa_id=empresa_id,
        file_name=file_name,
        doc_type=report_type,
        metadata={"origin": "store_report"},
        collection_name=VECTOR_STORE1_COLLECTION,
    )


def search_reports_qdrant(query: str, empresa_id: str, limit: int = 5) -> list:
    try:
        vector = embeddings.embed_query(query)
        results = client.query_points(
            collection_name=REPORTS_COLLECTION,
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="empresa_id", match=MatchValue(value=empresa_id))]
            ),
            limit=limit
        )
        return [r.payload.get("text", "") for r in results.points if r.payload.get("text")]
    except Exception as e:
        print(f"QDRANT search_reports_qdrant error: {e}")
        return []


def search_vector_store1(query: str, empresa_id: str, limit: int = 5) -> list:
    try:
        vector = embeddings.embed_query(query)
        results = client.query_points(
            collection_name=VECTOR_STORE1_COLLECTION,
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="empresa_id", match=MatchValue(value=empresa_id))]
            ),
            limit=limit
        )
        return [r.payload.get("text", "") for r in results.points if r.payload.get("text")]
    except Exception as e:
        print(f"QDRANT search_vector_store1 error: {e}")
        return []


def store_image_report(text: str, empresa_id: str, file_name: str, metadata: dict | None = None):
    store_vector_knowledge(
        text=text,
        empresa_id=empresa_id,
        file_name=file_name,
        doc_type="image_analysis",
        metadata=metadata or {},
        collection_name=IMAGE_REPORTS_COLLECTION,
    )
    store_vector_knowledge(
        text=text,
        empresa_id=empresa_id,
        file_name=file_name,
        doc_type="image_analysis",
        metadata=metadata or {},
        collection_name=VECTOR_STORE1_COLLECTION,
    )


def search_reports(query: str, empresa_id: str = "") -> list:
    """Search reports in PostgreSQL with full-text + ILIKE fallback."""
    from api.database import sync_engine
    from sqlalchemy import text as sql_text

    if not empresa_id:
        return []

    try:
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", query)
        words = [w for w in clean.strip().split() if len(w) > 2]
        search_terms = " & ".join(words) if words else "reporte"

        with sync_engine.connect() as conn:
            rows = []

            try:
                result = conn.execute(
                    sql_text("""
                        SELECT title, source_file, markdown_content, alerts, created_at,
                               ts_rank(search_vector, to_tsquery('pg_catalog.spanish', :query)) as rank
                        FROM ada_reports
                        WHERE empresa_id = :empresa_id
                        AND is_archived = FALSE
                        AND search_vector @@ to_tsquery('pg_catalog.spanish', :query)
                        ORDER BY rank DESC
                        LIMIT 3
                    """),
                    {"empresa_id": empresa_id, "query": search_terms},
                )
                rows = result.fetchall()
            except Exception as e:
                print(f"REPORTS SEARCH full-text error: {e}")

            if not rows:
                like_words = [w for w in words if len(w) > 3]
                for word in reversed(like_words):
                    result = conn.execute(
                        sql_text("""
                            SELECT title, source_file, markdown_content, alerts, created_at,
                                   1.0 as rank
                            FROM ada_reports
                            WHERE empresa_id = :empresa_id
                            AND is_archived = FALSE
                            AND (
                                source_file ILIKE :like_query
                                OR title ILIKE :like_query
                                OR markdown_content ILIKE :like_query
                            )
                            ORDER BY created_at DESC
                            LIMIT 3
                        """),
                        {"empresa_id": empresa_id, "like_query": f"%{word}%"},
                    )
                    rows = result.fetchall()
                    if rows:
                        break

            if not rows:
                result = conn.execute(
                    sql_text("""
                        SELECT title, source_file, markdown_content, alerts, created_at,
                               0.1 as rank
                        FROM ada_reports
                        WHERE empresa_id = :empresa_id
                        AND is_archived = FALSE
                        ORDER BY created_at DESC
                        LIMIT 2
                    """),
                    {"empresa_id": empresa_id},
                )
                rows = result.fetchall()

        reports = []
        for row in rows:
            report_text = (
                f"[Reporte: {row.title} | Archivo: {row.source_file} | {row.created_at}]\n"
                f"{row.markdown_content[:2000]}"
            )
            if row.alerts:
                alerts = row.alerts if isinstance(row.alerts, list) else json.loads(row.alerts)
                if alerts:
                    alerts_text = "\nAlertas: " + ", ".join([a.get("message", "") for a in alerts[:3]])
                    report_text += alerts_text
            reports.append(report_text)

        return reports

    except Exception as e:
        print(f"ERROR search_reports: {e}")
        import traceback
        traceback.print_exc()
        return []
