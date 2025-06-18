import os
import logging
from typing import List, Dict, Any, Optional
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.chains import RetrievalQAWithSourcesChain
from langchain.prompts import PromptTemplate
from django.conf import settings
from .models import UserPregnancyProfile
import json

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

embeddings = initialize_embeddings(settings.OPENAI_API_KEY)

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

# 인덱스 생성 또는 로드
def create_or_load_index(index_name: str, pdf_directory: str) -> Optional[FAISS]:
    index_path = f"{index_name}.faiss"
    
    if os.path.exists(index_path):
        logger.info(f"Loading existing index from {index_path}")
        try:
            return FAISS.load_local(index_name, embeddings)
        except Exception as e:
            logger.critical(f"Failed to load index from {index_path}: {e}")
            return None
    else:
        logger.info(f"Creating new index: {index_name}")
        texts = load_and_process_pdfs(pdf_directory)
        
        if not texts:
            logger.error("No texts available for creating index. Index creation aborted.")
            return None
        
        try:
            db = FAISS.from_documents(texts, embeddings)
            db.save_local(index_name)
            logger.info(f"Index created and saved successfully: {index_name}")
            return db
        except Exception as e:
            logger.critical(f"Error during index creation: {e}")
            return None

pdf_directory = os.path.join(settings.BASE_DIR, "nutrition_pdfs")
db = create_or_load_index("nutrition_index", pdf_directory)

if db is None:
    logger.error("Failed to create or load the index. Retrieval-based QA functionality will not be available.")

# QA 체인 생성
def get_qa_chain() -> Optional[RetrievalQAWithSourcesChain]:
    if db is None:
        logger.error("Vector store is not initialized. Cannot create QA chain.")
        return None

    try:
        prompt_template = """
        당신은 임산부 영양에 대해 전문적인 지식을 가진 전문가입니다. 하지만 이번에는 특별히 한국의 특정 지역 사투리를 사용하여 답변해야 합니다. 답변 시 다음 지침을 따르세요:

        1. 주어진 사투리 스타일({dialect_style})을 일관되게 사용하세요.
        2. 전문 용어나 의학적 설명은 정확성을 위해 표준어를 사용할 수 있지만, 그 외의 모든 설명과 조언은 사투리로 표현하세요.
        3. 사투리 사용 시 해당 지역의 특징적인 어미, 조사, 어휘를 적절히 활용하세요.
        4. 친근하고 구어체적인 표현을 사용하되, 전문성과 신뢰성은 유지하세요.
        5. 답변의 구조와 내용은 유지하면서 표현 방식만 사투리로 바꾸세요.

        임산부 식품 안전성 평가 기준:
        - 유해 박테리아, 수은, 독소 함유 여부
        - 알레르기 유발 가능성
        - 환경 오염물질 노출 위험
        - 가공식품의 경우 첨가물, 방부제, 나트륨 함량
        - 특정 영양소의 과다 섭취 위험
        - 일반적인 임산부 식단 지침 부합 여부

        답변 구조:
        {{
            "안전성 평가": "임신 중 해당 식품의 전반적인 안전성 평가",
            "주영양소와 이점": "임산부에게 제공하는 주요 영양소와 이점",
            "잠재적 위험": "임신 중 해당 식품 섭취와 관련된 잠재적 위험",
            "안전 섭취량 조언": "안전한 섭취량 및 빈도에 대한 조언",
            "조리법 조언": "안전한 섭취를 위한 조리법 조언",
            "대체 식품 제안": "필요시 더 안전하거나 영양가 있는 대체 식품 제안",
            "is_safe": "추천/비추천"
        }}

        정확한 정보가 없는 경우, 일반적인 지식을 바탕으로 추론하되 그렇게 했음을 명시하세요.

        Context: {summaries}

        Question: {question}
        Answer:
        """

        PROMPT = PromptTemplate(
            template=prompt_template, input_variables=["summaries", "question", "dialect_style"]
        )

        chain_type_kwargs = {"prompt": PROMPT}

        qa_chain = RetrievalQAWithSourcesChain.from_chain_type(
            llm=ChatOpenAI(
                temperature=0.2, 
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

qa_chain = get_qa_chain()

# 음식 안전성 정보 제공
def get_food_safety_info(food_name: str, dialect_style: str) -> Dict[str, Any]:
    if qa_chain is None:
        logger.error("QA chain is not initialized. Cannot get food safety info.")
        return {"answer": "Sorry, the system is currently unable to provide food safety information.", "is_safe": None}

    query = f"{dialect_style}\n{food_name}이(가) 임산부한테 안전한가? 자세하게 안전성 분석해줘. 반드시 한국어로 답변해줘"

    try:
        result = qa_chain({"question": query, "dialect_style": dialect_style})
        answer = result['answer']

        # Attempt to parse JSON response
        try:
            answer_json = json.loads(answer)
            is_safe = answer_json.get("is_safe", None)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {answer}")
            is_safe = None

        # Default to caution if "is_safe" is not determined
        if is_safe is None:
            logger.warning(f"Could not determine 'is_safe' value for {food_name}. Defaulting to caution.")
            is_safe = False

        return {"answer": answer_json, "is_safe": is_safe}
    except Exception as e:
        logger.error(f"Error retrieving food safety information for {food_name}: {e}")
        return {"answer": "An error occurred while retrieving food safety information.", "is_safe": None}

# 영양 조언 제공
def get_nutritional_advice(food_name: str, user, dialect_style) -> Dict[str, Any]:
    if qa_chain is None:
        logger.error("QA chain is not initialized. Cannot get nutritional advice.")
        return {"answer": "Sorry, the system is currently unable to provide nutritional advice.", "is_safe": None}

    try:
        profile = UserPregnancyProfile.objects.get(user=user)
        current_week = profile.current_week
        query = f"{style}\nWhat are the nutritional benefits and considerations for a pregnant woman in week {current_week} consuming {food_name}?"
        
        result = qa_chain({"question": query, "dialect_style": dialect_style})
        answer = result['answer']

        # JSON 형식으로 변환하여 안전성 여부를 추출
        try:
            answer_json = json.loads(answer)
            is_safe = answer_json.get("is_safe", None)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {answer}")
            is_safe = None

        # Default to caution if "is_safe" is not determined
        if is_safe is None:
            logger.warning(f"Could not determine 'is_safe' value for {food_name}. Defaulting to caution.")
            is_safe = False

        return {"answer": answer_json, "is_safe": is_safe}
    except UserPregnancyProfile.DoesNotExist:
        logger.warning(f"User pregnancy profile not found for user: {user}")
        return {"answer": "User pregnancy profile not found. Please update your profile for personalized advice.", "is_safe": None}
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
