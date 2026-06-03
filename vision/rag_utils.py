import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, cast

import requests
from django.conf import settings
from django.core.cache import cache
from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader
from langchain_community.vectorstores import Chroma, FAISS
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from vision.models import UserPregnancyProfile

UserPregnancyProfile = cast(Any, UserPregnancyProfile)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GUIDANCE_CACHE_TIMEOUT = 1800
DEFAULT_LOCAL_RAG_MODEL = "gemma4:e4b"
DEFAULT_LOCAL_EMBED_MODEL = "bge-m3"
DEFAULT_OPENAI_RAG_MODEL = "gpt-4o-mini"
DEFAULT_RETRIEVAL_K = 5
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120
DEFAULT_OLLAMA_EMBED_BATCH_SIZE = 16

GUIDANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "safety_summary": {"type": "string"},
        "is_safe": {"type": "boolean"},
        "nutritional_advice": {"type": "string"},
    },
    "required": ["safety_summary", "is_safe", "nutritional_advice"],
    "additionalProperties": False,
}

RAG_SYSTEM_PROMPT = (
    "You are a cautious prenatal nutrition assistant. Use the provided retrieved "
    "context when it is relevant. If the context is incomplete, say so briefly "
    "inside the summary and give conservative general guidance. Return only valid "
    "JSON with keys safety_summary, is_safe, and nutritional_advice. Write the "
    "values in Korean. Do not include markdown, citations, or extra fields."
)


def _setting(name: str, default: Any = None) -> Any:
    return getattr(settings, name, os.getenv(name, default))


def _base_dir() -> str:
    return str(_setting("BASE_DIR", os.getcwd()))


def _vision_provider() -> str:
    return str(_setting("VISION_PROVIDER", "openai")).strip().lower()


def _rag_provider() -> str:
    return str(_setting("RAG_PROVIDER", _vision_provider())).strip().lower()


def _embedding_provider() -> str:
    return str(_setting("EMBEDDING_PROVIDER", _rag_provider())).strip().lower()


def _ollama_base_url() -> str:
    return str(_setting("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")


def _ollama_timeout_seconds() -> int:
    return int(_setting("OLLAMA_TIMEOUT_SECONDS", DEFAULT_OLLAMA_TIMEOUT_SECONDS))


def _ollama_rag_model() -> str:
    return str(_setting("OLLAMA_RAG_MODEL", _setting("OLLAMA_VISION_MODEL", DEFAULT_LOCAL_RAG_MODEL)))


def _ollama_embed_model() -> str:
    return str(_setting("OLLAMA_EMBED_MODEL", DEFAULT_LOCAL_EMBED_MODEL))


def _retrieval_k() -> int:
    return int(_setting("RAG_RETRIEVAL_K", DEFAULT_RETRIEVAL_K))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "default"


def _active_index_name(base_index_name: str = "nutrition_index") -> str:
    configured = _setting("RAG_INDEX_NAME")
    if configured:
        return str(configured)

    if _embedding_provider() in {"ollama", "local"}:
        return os.path.join(base_index_name, f"ollama_{_safe_name(_ollama_embed_model())}")

    return base_index_name


class OllamaEmbeddings:
    def __init__(self, model: str, base_url: str, timeout: int, batch_size: int) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.batch_size = batch_size

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = requests.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": batch},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            batch_embeddings = data.get("embeddings")
            if not isinstance(batch_embeddings, list):
                raise ValueError("Ollama embedding response did not include embeddings")
            embeddings.extend(batch_embeddings)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

    def __call__(self, text: str) -> List[float]:
        return self.embed_query(text)


def initialize_embeddings(api_key: str) -> Any:
    if _embedding_provider() in {"ollama", "local"}:
        logger.info("Initializing Ollama embeddings with model %s", _ollama_embed_model())
        return OllamaEmbeddings(
            model=_ollama_embed_model(),
            base_url=_ollama_base_url(),
            timeout=_ollama_timeout_seconds(),
            batch_size=int(_setting("OLLAMA_EMBED_BATCH_SIZE", DEFAULT_OLLAMA_EMBED_BATCH_SIZE)),
        )

    try:
        embeddings = OpenAIEmbeddings(openai_api_key=api_key)
        logger.info("OpenAI embeddings initialized successfully.")
        return embeddings
    except Exception as e:
        logger.critical("Failed to initialize OpenAI embeddings: %s", e)
        raise


def get_embeddings() -> Any:
    if _embedding_provider() in {"ollama", "local"}:
        return initialize_embeddings("")

    api_key = _setting("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return initialize_embeddings(api_key)


def load_and_process_pdfs(directory: str) -> List[Any]:
    logger.info("Loading PDFs from directory: %s", directory)

    if not os.path.exists(directory):
        logger.error("Directory does not exist: %s", directory)
        return []

    try:
        loader = DirectoryLoader(directory, glob="*.pdf", loader_cls=PyPDFLoader)
        documents = loader.load()
        logger.info("Loaded %s documents from %s", len(documents), directory)

        if not documents:
            logger.warning("No documents were loaded. Please check the directory for PDF files.")
            return []

        for doc in documents:
            source_file = os.path.basename(doc.metadata.get("source", "Unknown source"))
            doc.page_content += f"\nSource: {source_file}"

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        texts = text_splitter.split_documents(documents)
        logger.info("Split documents into %s text chunks", len(texts))
        return texts
    except Exception as e:
        logger.error("Error during PDF loading and processing: %s", e)
        return []


def create_or_load_index(index_name: str, pdf_directory: str) -> Optional[Any]:
    embeddings = get_embeddings()
    index_path = os.path.join(_base_dir(), index_name)
    faiss_file = os.path.join(index_path, "index.faiss")

    try:
        if os.path.exists(faiss_file):
            logger.info("Loading existing FAISS index from %s", index_path)
            try:
                return FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
            except TypeError:
                return FAISS.load_local(index_path, embeddings)

        logger.info("Creating new FAISS index: %s", index_path)
        texts = load_and_process_pdfs(pdf_directory)
        if not texts:
            logger.error("No texts available for creating index. Index creation aborted.")
            return None
        db_local = FAISS.from_documents(texts, embeddings)
        db_local.save_local(index_path)
        logger.info("FAISS index created and saved successfully: %s", index_path)
        return db_local
    except Exception as e:
        logger.critical("Error using FAISS vector store (will fallback to Chroma): %s", e)

    chroma_path = f"{index_path}_chroma"
    try:
        if os.path.isdir(chroma_path):
            logger.info("Loading existing Chroma index from %s", chroma_path)
            return Chroma(persist_directory=chroma_path, embedding_function=embeddings)

        logger.info("Creating new Chroma index: %s", chroma_path)
        texts = load_and_process_pdfs(pdf_directory)
        if not texts:
            logger.error("No texts available for creating index. Index creation aborted.")
            return None
        db_local = Chroma.from_documents(documents=texts, embedding=embeddings, persist_directory=chroma_path)
        try:
            db_local.persist()
        except Exception:
            pass
        logger.info("Chroma index created and saved successfully: %s", chroma_path)
        return db_local
    except Exception as e:
        logger.critical("Error during Chroma index creation/loading: %s", e)
        return None


pdf_directory = os.path.join(_base_dir(), "nutrition_pdfs")
db: Optional[Any] = None


def get_qa_chain() -> Optional[Any]:
    global db
    if db is not None:
        return db

    index_name = _active_index_name("nutrition_index")
    db = create_or_load_index(index_name, pdf_directory)
    if db is None:
        logger.error("Failed to create or load the index. Retrieval-based QA functionality will not be available.")
        return None

    logger.info("RAG vector store is ready with index %s.", index_name)
    return db


def _extract_json(answer: str) -> Optional[Dict[str, Any]]:
    if not answer:
        return None
    match = re.search(r"\{[\s\S]*\}", answer)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON from answer: %s", answer)
        return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "safe"}:
            return True
        if lowered in {"false", "0", "no", "n", "unsafe"}:
            return False
    return False


def _resolve_stage_context(user: Optional[Any]) -> Dict[str, str]:
    default_context = {"week_context": "pregnant user", "cache_tag": "generic"}
    if user is None:
        return default_context
    try:
        profile = UserPregnancyProfile.objects.get(user=user)  # type: ignore
        current_week = getattr(profile, "current_week", None)
        if current_week:
            return {
                "week_context": f"pregnant user at week {current_week}",
                "cache_tag": f"week:{current_week}",
            }
    except UserPregnancyProfile.DoesNotExist:  # type: ignore
        pass
    return default_context


def _format_source_documents(documents: Iterable[Any]) -> str:
    blocks = []
    for idx, doc in enumerate(documents, start=1):
        source = doc.metadata.get("source", "unknown") if hasattr(doc, "metadata") else "unknown"
        content = getattr(doc, "page_content", str(doc)).strip()
        blocks.append(f"[{idx}] Source: {source}\n{content[:1800]}")
    return "\n\n".join(blocks)


def _build_guidance_question(food_name: str, dialect_style: str, stage_context: Dict[str, str]) -> str:
    return (
        f"Food: {food_name}\n"
        f"User context: {stage_context['week_context']}\n"
        f"Style instructions: {dialect_style}\n"
        "Task: Assess whether this food is generally safe for a pregnant user, "
        "summarize key cautions, and provide nutrition advice. Return Korean JSON only."
    )


def _invoke_ollama_guidance(context: str, question: str) -> str:
    prompt = (
        f"Retrieved context:\n{context or 'No retrieved context was available.'}\n\n"
        f"Question:\n{question}\n\n"
        "Return exactly this JSON shape:\n"
        '{"safety_summary":"...","is_safe":false,"nutritional_advice":"..."}'
    )
    payload = {
        "model": _ollama_rag_model(),
        "messages": [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "format": GUIDANCE_SCHEMA,
        "think": False,
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": int(_setting("OLLAMA_RAG_NUM_PREDICT", 512)),
        },
    }
    response = requests.post(
        f"{_ollama_base_url()}/api/chat",
        json=payload,
        timeout=_ollama_timeout_seconds(),
    )
    response.raise_for_status()
    data = response.json()
    return data.get("message", {}).get("content", "")


def _invoke_openai_guidance(context: str, question: str) -> str:
    api_key = _setting("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    prompt = (
        f"{RAG_SYSTEM_PROMPT}\n\n"
        f"Retrieved context:\n{context or 'No retrieved context was available.'}\n\n"
        f"Question:\n{question}\n\n"
        "Return exactly this JSON shape:\n"
        '{"safety_summary":"...","is_safe":false,"nutritional_advice":"..."}'
    )
    llm = ChatOpenAI(
        model=str(_setting("OPENAI_RAG_MODEL", DEFAULT_OPENAI_RAG_MODEL)),
        temperature=0,
        openai_api_key=api_key,
    )
    response = llm.invoke(prompt)
    return str(getattr(response, "content", response))


def _normalize_guidance(parsed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not parsed:
        return {
            "safety_summary": "검색된 문서와 모델 응답을 안정적으로 해석하지 못해 보수적인 주의가 필요합니다.",
            "is_safe": False,
            "nutritional_advice": "개인 건강 상태와 임신 주수에 따라 달라질 수 있으니 의료 전문가와 상담하세요.",
        }

    safety_summary = parsed.get("safety_summary") or parsed.get("summary") or ""
    nutritional_advice = parsed.get("nutritional_advice") or parsed.get("nutrition_summary") or ""

    if not safety_summary:
        safety_summary = "임산부 섭취 안전성에 대한 구체 정보가 부족해 보수적인 주의가 필요합니다."
    if not nutritional_advice:
        nutritional_advice = "균형 잡힌 식단 안에서 적정량을 고려하고, 개인 상태에 따라 전문가와 상담하세요."

    return {
        "safety_summary": str(safety_summary),
        "is_safe": _coerce_bool(parsed.get("is_safe")),
        "nutritional_advice": str(nutritional_advice),
    }


def get_food_guidance(food_name: str, dialect_style: str = "표준어", user: Optional[Any] = None) -> Dict[str, Any]:
    store = get_qa_chain()
    if store is None:
        logger.error("Vector store is not initialized. Cannot get food guidance.")
        return {
            "safety_summary": "현재 시스템이 안전성 정보를 제공할 수 없습니다.",
            "is_safe": False,
            "nutritional_advice": "현재 시스템이 영양 조언을 제공할 수 없습니다.",
        }

    stage_context = _resolve_stage_context(user)
    normalized_food = food_name.strip()
    cache_payload = (
        f"{normalized_food.lower()}|{dialect_style}|{stage_context['cache_tag']}|"
        f"{_rag_provider()}|{_embedding_provider()}|{_ollama_rag_model()}|{_ollama_embed_model()}"
    )
    cache_key = f"food_guidance:{hashlib.sha256(cache_payload.encode('utf-8')).hexdigest()}"

    cached = cache.get(cache_key)
    if cached:
        return cached

    question = _build_guidance_question(normalized_food, dialect_style, stage_context)

    try:
        documents = store.similarity_search(question, k=_retrieval_k())
        context = _format_source_documents(documents)

        if _rag_provider() in {"ollama", "local"}:
            answer = _invoke_ollama_guidance(context, question)
        else:
            answer = _invoke_openai_guidance(context, question)

        guidance = _normalize_guidance(_extract_json(answer))
        cache.set(cache_key, guidance, GUIDANCE_CACHE_TIMEOUT)
        return guidance
    except Exception as e:
        logger.error("Error retrieving food guidance for %s: %s", food_name, e)
        return {
            "safety_summary": "정보를 가져오는 중 오류가 발생했습니다.",
            "is_safe": False,
            "nutritional_advice": "정보를 가져오는 중 오류가 발생했습니다.",
        }


def get_food_safety_info(food_name: str, dialect_style: str = "표준어") -> Dict[str, Any]:
    guidance = get_food_guidance(food_name, dialect_style=dialect_style)
    return {"summary": guidance["safety_summary"], "is_safe": guidance["is_safe"]}


def get_nutritional_advice(food_name: str, user: Any, dialect_style: str) -> str:
    guidance = get_food_guidance(food_name, dialect_style=dialect_style, user=user)
    return guidance["nutritional_advice"]


def update_index(new_pdf_path: str) -> None:
    global db
    if db is None:
        db = get_qa_chain()
    if db is None:
        logger.error("Vector store is not initialized. Cannot update index.")
        return

    try:
        new_texts = load_and_process_pdfs(new_pdf_path)
        if not new_texts:
            logger.warning("No new texts found in %s. Index update aborted.", new_pdf_path)
            return

        db.add_documents(new_texts)
        if hasattr(db, "save_local"):
            db.save_local(os.path.join(_base_dir(), _active_index_name("nutrition_index")))
        elif hasattr(db, "persist"):
            db.persist()
        logger.info("Index updated with new documents from: %s", new_pdf_path)
    except Exception as e:
        logger.error("Error during index update with new PDFs from %s: %s", new_pdf_path, e)
