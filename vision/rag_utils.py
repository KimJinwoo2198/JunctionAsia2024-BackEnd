import os
import logging
from typing import List, Dict, Any, Optional, cast
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS, Chroma
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import langchain.chains as lc_chains
from langchain.prompts import PromptTemplate
from django.conf import settings
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
        - 항목을 나누지 말고, 하나의 연속된 설명으로 요약하세요.
        - 단, 판정 목적을 위해 최종 불리언 필드만 포함하세요.
        - 유효한 JSON으로만 출력합니다.

        출력(JSON 스키마):
        {{
          "summary": "임산부 관점에서의 안전성/영양/주의사항/섭취 팁을 하나의 문단 이상으로 자연스럽게 요약",
          "is_safe": true 또는 false
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

# 음식 안전성 정보 제공
def get_food_safety_info(food_name: str, dialect_style: str = "표준어") -> Dict[str, Any]:
    chain = get_qa_chain()
    if chain is None:
        logger.error("QA chain is not initialized. Cannot get food safety info.")
        return {"answer": "Sorry, the system is currently unable to provide food safety information.", "is_safe": None}

    query = f"{dialect_style}\n{food_name}이(가) 임산부한테 안전한가? 자세하게 안전성 분석해줘. 반드시 한국어로 답변해줘"

    try:
        result = chain.invoke({"question": query, "dialect_style": dialect_style})
        answer = result['answer']

        # Attempt to parse JSON response (extract JSON object if extra text is present)
        try:
            extracted = re.search(r"\{[\s\S]*\}", answer)
            json_str = extracted.group(0) if extracted else answer
            answer_json = json.loads(json_str)
            summary_text = answer_json.get("summary", "")
            is_safe = answer_json.get("is_safe", None)
        except json.JSONDecodeError:
            summary_text = answer.strip()
            is_safe = None

        # Default to caution if "is_safe" is not determined (no noisy warnings)
        if is_safe is None:
            is_safe = False

        return {"summary": summary_text, "is_safe": is_safe}
    except Exception as e:
        logger.error(f"Error retrieving food safety information for {food_name}: {e}")
        return {"answer": "An error occurred while retrieving food safety information.", "is_safe": None}

# 영양 조언 제공
def get_nutritional_advice(food_name: str, user, dialect_style) -> str:
    chain = get_qa_chain()
    if chain is None:
        logger.error("QA chain is not initialized. Cannot get nutritional advice.")
        return {"answer": "Sorry, the system is currently unable to provide nutritional advice.", "is_safe": None}

    try:
        # 주차 정보가 있으면 포함하고, 없으면 기본 컨텍스트로 처리(로그 경고 없음)
        try:
            profile = UserPregnancyProfile.objects.get(user=user)  # type: ignore
            current_week = profile.current_week
            week_context = f"{current_week}주차 임산부가"
        except UserPregnancyProfile.DoesNotExist:  # type: ignore
            week_context = "임산부가"

        query = (
            f"{dialect_style}\n"
            f"{week_context} {food_name}을(를) 섭취할 때의 영양적 이점과 고려사항을 자연스럽게 하나의 요약으로 알려줘."
        )

        result = chain.invoke({"question": query, "dialect_style": dialect_style})
        answer = result['answer']

        # JSON 형식에서 summary만 추출 (필요시 JSON만 추출)
        try:
            extracted = re.search(r"\{[\s\S]*\}", answer)
            json_str = extracted.group(0) if extracted else answer
            answer_json = json.loads(json_str)
            summary_text = answer_json.get("summary", "")
        except json.JSONDecodeError:
            summary_text = answer.strip()

        return summary_text
    except Exception as e:
        logger.error(f"Error retrieving nutritional advice for {food_name}: {e}")
        return {"answer": "An error occurred while retrieving nutritional advice.", "is_safe": None}

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
