import os

from langchain_postgres import PGVector
from langchain_mistralai import MistralAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from ..db import get_sqlalchemy_url

EMBEDDING_MODEL = "mistral-embed"


def collection_for(job_id: str) -> str:
    """
    Every job gets its own collection. This is load-bearing: a single shared
    collection name lets one video's chunks answer questions about another.
    """
    if not job_id:
        raise ValueError("job_id is required — vector stores are never shared across jobs")
    return f"job_{job_id}"


def get_embeddings():
    return MistralAIEmbeddings(
        model = EMBEDDING_MODEL,
        mistral_api_key = os.getenv("MISTRAL_API_KEY"),
    )


def build_vector_store(transcript : str, job_id : str) -> PGVector:
    print(f"Building vector Store for job {job_id}")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size = 500,
        chunk_overlap = 50
    )
    chunks = splitter.split_text(transcript)

    docs = [
        Document(page_content=chunk, metadata = {'chunk_index' : i, 'job_id' : job_id})
        for i,chunk in enumerate(chunks)
    ]

    embeddings = get_embeddings()
    vector_store = PGVector.from_documents(
        documents = docs,
        embedding = embeddings,
        collection_name = collection_for(job_id),
        connection = get_sqlalchemy_url(),
        use_jsonb = True,
    )

    return vector_store


def load_vector_store(job_id : str) -> PGVector:
    embeddings = get_embeddings()
    vector_store = PGVector(
        collection_name = collection_for(job_id),
        embeddings = embeddings,
        connection = get_sqlalchemy_url(),
        use_jsonb = True,
    )

    return vector_store


def get_retriever(vector_store : PGVector, k : int = 4):
    return vector_store.as_retriever(
        search_type = 'similarity',
        search_kwargs = {"k":k}
    )


def delete_vector_store(job_id : str) -> None:
    """Drop this job's collection so vectors don't accumulate across many videos."""
    load_vector_store(job_id).delete_collection()
