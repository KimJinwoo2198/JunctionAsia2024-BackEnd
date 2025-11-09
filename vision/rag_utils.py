import os
import logging
import hashlib
from typing import List, Dict, Any, Optional, cast
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS, Chroma
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import langchain.chains as lc_chains
from langchain.prompts import PromptTemplate
from django.conf import settings
from django.core.cache import cache
from vision.models import UserPregnancyProfile
# 타입 체커가 Django 동적 속성(objects, DoesNotExist)을 인식하지 못하는 문제 방지
UserPregnancyProfile = cast(Any, UserPregnancyProfile)
import json
import re

# Logger 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI Embeddings 초기화
def initialize_embeddings(api_key: str) -> OpenAIEmbeddings:
    try:
        embeddings = OpenAIEmbeddings(openai_api_key=api_key)
        logger.info("OpenAI embeddings initialized successfully.")
        return embeddings
    except Exception as e:
        logger.critical(f"Failed to initialize OpenAI embeddings: {e}")
        raise

def get_embeddings() -> OpenAIEmbeddings:
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return initialize_embeddings(api_key)

# PDF 파일 로드 및 처리
def load_and_process_pdfs(directory: str) -> List[Dict[str, Any]]:
    logger.info(f"Loading PDFs from directory: {directory}")
    
    if not os.path.exists(directory):
        logger.error(f"Directory does not exist: {directory}")
        return []
    
    try:
        loader = DirectoryLoader(directory, glob="*.pdf", loader_cls=PyPDFLoader)
        documents = loader.load()
        logger.info(f"Loaded {len(documents)} documents from {directory}")
        
        if not documents:
            logger.warning("No documents were loaded. Please check the directory for PDF files.")
            return []

        # Document에 소스 파일명을 추가
        for doc in documents:
            source_file = os.path.basename(doc.metadata.get('source', 'Unknown source'))
            doc.page_content += f"\nSource: {source_file}"

        # 텍스트 분할
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        texts = text_splitter.split_documents(documents)
        logger.info(f"Split documents into {len(texts)} text chunks")
        
        return texts
    except Exception as e:
        logger.error(f"Error during PDF loading and processing: {e}")
        return []

def create_or_load_index(index_name: str, pdf_directory: str):
    embeddings = get_embeddings()

    # FAISS 우선 시도
    faiss_dir = os.path.join(settings.BASE_DIR, index_name)
    faiss_file = os.path.join(faiss_dir, "index.faiss")
    try:
        if os.path.exists(faiss_file):
            logger.info(f"Loading existing FAISS index from {faiss_dir}")
            try:
                return FAISS.load_local(faiss_dir, embeddings, allow_dangerous_deserialization=True)
            except TypeError:
                # 구버전 시그니처 대응
                return FAISS.load_local(faiss_dir, embeddings)
        else:
            logger.info(f"Creating new FAISS index: {index_name}")
            texts = load_and_process_pdfs(pdf_directory)
            if not texts:
                logger.error("No texts available for creating index. Index creation aborted.")
                return None
            db_local = FAISS.from_documents(texts, embeddings)
            db_local.save_local(faiss_dir)
            logger.info(f"FAISS index created and saved successfully: {faiss_dir}")
            return db_local
    except Exception as e:
        logger.critical(f"Error using FAISS vector store (will fallback to Chroma): {e}")

    # Chroma 폴백
    chroma_dir = os.path.join(settings.BASE_DIR, f"{index_name}_chroma")
    try:
        if os.path.isdir(chroma_dir):
            logger.info(f"Loading existing Chroma index from {chroma_dir}")
            return Chroma(persist_directory=chroma_dir, embedding_function=embeddings)

        logger.info(f"Creating new Chroma index: {chroma_dir}")
        texts = load_and_process_pdfs(pdf_directory)
        if not texts:
            logger.error("No texts available for creating index. Index creation aborted.")
            return None
        db_local = Chroma.from_documents(documents=texts, embedding=embeddings, persist_directory=chroma_dir)
        # Chroma는 자동 퍼시스트 설정이지만 명시적으로 보장
        try:
            db_local.persist()
        except Exception:
            pass
        logger.info(f"Chroma index created and saved successfully: {chroma_dir}")
        return db_local
    except Exception as e:
        logger.critical(f"Error during Chroma index creation/loading: {e}")
        return None

pdf_directory = os.path.join(settings.BASE_DIR, "nutrition_pdfs")
db = None
qa_chain: Optional[Any] = None
GUIDANCE_CACHE_TIMEOUT = 1800  # 30분 캐시

# QA 체인 생성
def get_qa_chain() -> Optional[Any]:
    global db, qa_chain
    if qa_chain is not None:
        return qa_chain
    if db is None:
        db = create_or_load_index("nutrition_index", pdf_directory)
        if db is None:
            logger.error("Failed to create or load the index. Retrieval-based QA functionality will not be available.")
            logger.error("Vector store is not initialized. Cannot create QA chain.")
            return None

    try:
        prompt_template = """
        당신은 임산부 영양에 대해 전문적인 지식을 가진 전문가입니다. 이번 답변은 반드시 한국어로, 그리고 유효한 JSON으로만 출력해야 합니다. 추가 텍스트(설명, 문장, 주석, 코드 블록)를 절대 포함하지 마세요.

        사투리 지침:
        1. 주어진 사투리 스타일({dialect_style})을 일관되게 사용하세요.
        2. 전문 용어나 의학적 설명은 정확성을 위해 표준어를 사용할 수 있으나, 그 외 설명은 사투리로 표현하세요.

        임산부 식품 안전성 평가 시 고려 요소(내부 참고):
        - 병원성 미생물/독소, 중금속(수은 등)
        - 알레르기 유발 가능성
        - 환경 오염물질 노출 위험
        - 첨가물/나트륨 과다 등 가공식품 리스크
        - 특정 영양소 과다 섭취 위험
        - 일반 임산부 식단 지침 부합 여부

        출력 형식 지침:
        - JSON 하나만 출력하고, 스키마의 모든 필드를 채우세요.
        - 각 필드는 최소 한 문장 이상으로 자연스럽게 작성하세요.

        출력(JSON 스키마 - 반드시 그대로 따르세요):
        {{
          "safety_summary": "임산부 관점에서의 안전성/주의사항/섭취 팁을 자연스럽게 요약",
          "is_safe": true 또는 false,
          "nutritional_advice": "임산부에게 필요한 영양 조언을 자연스럽게 요약"
        }}

        Context: {summaries}

        Question: {question}
        Answer(JSON only):
        """

        PROMPT = PromptTemplate(
            template=prompt_template, input_variables=["summaries", "question", "dialect_style"]
        )

        chain_type_kwargs = {"prompt": PROMPT}

        qa_chain = lc_chains.RetrievalQAWithSourcesChain.from_chain_type(
            llm=ChatOpenAI(
                temperature=0.0,
                openai_api_key=settings.OPENAI_API_KEY
            ),
            chain_type="stuff",
            retriever=db.as_retriever(search_kwargs={"k": 5}),
            chain_type_kwargs=chain_type_kwargs,
            return_source_documents=True
        )
        logger.info("QA chain created successfully.")
        return qa_chain
    except Exception as e:
        logger.critical(f"Error during QA chain creation: {e}")
        return None

# 체인은 최초 사용 시 생성됩니다.

# 내부 헬퍼
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
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return False

def _resolve_stage_context(user: Optional[Any]) -> Dict[str, str]:
    default_context = {"week_context": "임산부가", "cache_tag": "generic"}
    if user is None:
        return default_context
    try:
        profile = UserPregnancyProfile.objects.get(user=user)  # type: ignore
        current_week = getattr(profile, "current_week", None)
        if current_week:
            return {
                "week_context": f"{current_week}주차 임산부가",
                "cache_tag": f"week:{current_week}"
            }
    except UserPregnancyProfile.DoesNotExist:  # type: ignore
        pass
    return default_context

def get_food_guidance(food_name: str, dialect_style: str = "표준어", user: Optional[Any] = None) -> Dict[str, Any]:
    chain = get_qa_chain()
    if chain is None:
        logger.error("QA chain is not initialized. Cannot get food guidance.")
        return {
            "safety_summary": "현재 시스템이 안전성 정보를 제공할 수 없습니다.",
            "is_safe": False,
            "nutritional_advice": "현재 시스템이 영양 조언을 제공할 수 없습니다."
        }

    stage_context = _resolve_stage_context(user)
    normalized_food = food_name.strip()
    cache_payload = f"{normalized_food.lower()}|{dialect_style}|{stage_context['cache_tag']}"
    cache_key = f"food_guidance:{hashlib.sha256(cache_payload.encode('utf-8')).hexdigest()}"

    cached = cache.get(cache_key)
    if cached:
        return cached

    query = (
        f"{dialect_style}\n"
        f"{stage_context['week_context']} {normalized_food}을(를) 섭취할 때의 안전성 평가와 영양 조언을 하나의 응답으로 제공해줘. "
        "JSON 스키마 지침을 반드시 지키고 다른 텍스트는 출력하지 마."
    )

    try:
        result = chain.invoke({"question": query, "dialect_style": dialect_style})
        answer = result.get("answer", "")
        parsed = _extract_json(answer)

        if not parsed:
            logger.error("QA chain response could not be parsed. Raw answer: %s", answer)
            guidance = {
                "safety_summary": "응답을 해석할 수 없어 기본 주의 조언을 제공합니다.",
                "is_safe": False,
                "nutritional_advice": "의료 전문가와 상담하여 적절한 섭취량을 확인하세요."
            }
        else:
            safety_summary = parsed.get("safety_summary") or parsed.get("summary") or ""
            nutritional_advice = parsed.get("nutritional_advice") or parsed.get("nutrition_summary") or ""
            is_safe = _coerce_bool(parsed.get("is_safe"))

            if not safety_summary:
                safety_summary = "임산부가 섭취 시 주의 사항을 의료 전문가와 상의하세요."
            if not nutritional_advice:
                nutritional_advice = "개인별 영양 상태에 따라 전문 의료진의 조언을 받는 것이 좋습니다."

            guidance = {
                "safety_summary": safety_summary,
                "is_safe": is_safe,
                "nutritional_advice": nutritional_advice
            }

        cache.set(cache_key, guidance, GUIDANCE_CACHE_TIMEOUT)
        return guidance
    except Exception as e:
        logger.error(f"Error retrieving food guidance for {food_name}: {e}")
        return {
            "safety_summary": "정보를 가져오는 중 오류가 발생했습니다.",
            "is_safe": False,
            "nutritional_advice": "정보를 가져오는 중 오류가 발생했습니다."
        }

# 음식 안전성 정보 제공
def get_food_safety_info(food_name: str, dialect_style: str = "표준어") -> Dict[str, Any]:
    guidance = get_food_guidance(food_name, dialect_style=dialect_style)
    return {"summary": guidance["safety_summary"], "is_safe": guidance["is_safe"]}

# 영양 조언 제공
def get_nutritional_advice(food_name: str, user, dialect_style) -> str:
    guidance = get_food_guidance(food_name, dialect_style=dialect_style, user=user)
    return guidance["nutritional_advice"]

# 인덱스 업데이트
def update_index(new_pdf_path: str):
    if db is None:
        logger.error("Vector store is not initialized. Cannot update index.")
        return

    try:
        new_texts = load_and_process_pdfs(new_pdf_path)
        
        if not new_texts:
            logger.warning(f"No new texts found in {new_pdf_path}. Index update aborted.")
            return
        
        db.add_documents(new_texts)
        db.save_local("nutrition_index")
        logger.info(f"Index updated with new documents from: {new_pdf_path}")
    except Exception as e:
        logger.error(f"Error during index update with new PDFs from {new_pdf_path}: {e}")
