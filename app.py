import os
import json
import re
import zipfile
import urllib.request
from datetime import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from news_collector import JejuNewsPipeline

# 1. 페이지 제목 수정
st.set_page_config(
    page_title="제주도정 현안대응 시스템",
    page_icon="🌋",
    layout="wide"
)

# ---------------------------------------------------------------------
# 📦 대용량 Vector DB 자동 다운로드 (알림 박스 제거 및 조용히 처리)
# ---------------------------------------------------------------------
def ensure_vector_db():
    db_dir = "./jeju_db"
    zip_path = "jeju_db.zip"
    
    download_url = "https://github.com/YOUR_GITHUB_ID/YOUR_REPO_NAME/releases/download/v1.0.0/jeju_db.zip"

    if not os.path.exists(db_dir):
        with st.spinner("시스템 데이터베이스를 준비 중입니다..."):
            if not os.path.exists(zip_path):
                try:
                    urllib.request.urlretrieve(download_url, zip_path)
                except Exception as e:
                    st.error(f"❌ DB 다운로드 실패: {e}")
                    return

            try:
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(".")
            except Exception as e:
                st.error(f"❌ DB 압축 해제 실패: {e}")

# ---------------------------------------------------------------------
# ⚙️ 사이드바 및 보안 API Key 설정
# ---------------------------------------------------------------------
st.sidebar.header("⚙️ 시스템 설정")

secure_api_key = ""
if "GEMINI_API_KEY" in st.secrets:
    secure_api_key = st.secrets["GEMINI_API_KEY"]
elif "GEMINI_API_KEY" in os.environ:
    secure_api_key = os.environ["GEMINI_API_KEY"]

if secure_api_key:
    active_api_key = secure_api_key
    st.sidebar.success("🔑 서버 보안 API Key 적용 완료")
else:
    active_api_key = st.sidebar.text_input(
        "Gemini API Key 직접 입력", 
        type="password",
        help="Google AI Studio에서 발급받은 키를 입력하세요."
    )

if st.sidebar.button("🔄 최신 제주 현안 및 도지사 동향 수집"):
    with st.spinner("제주 지역 현안 및 도정 관련 뉴스를 수집 중입니다..."):
        pipeline = JejuNewsPipeline()
        pipeline.run()
    st.sidebar.success("최신 뉴스 수집이 완료되었습니다!")

# RAG Vector DB 및 LLM 로드
@st.cache_resource
def load_policy_advisor(api_key):
    ensure_vector_db()
    
    embeddings = HuggingFaceEmbeddings(model_name="jhgan/ko-sroberta-multitask")
    vectorstore = Chroma(
        persist_directory="./jeju_db", 
        embedding_function=embeddings
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
    
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.6-flash", 
        google_api_key=api_key,
        temperature=0.2
    )
    return retriever, llm

# ---------------------------------------------------------------------
# 🛠️ 텍스트 추출 및 처리 헬퍼 함수
# ---------------------------------------------------------------------
def extract_text_from_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.find('title').get_text(strip=True) if soup.find('title') else "외부 입력 기사"
        paragraphs = [p.get_text(strip=True) for p in soup.find_all('p')]
        content = "\n".join(paragraphs[:10])
        return title, content if content else "본문 추출 실패"
    except Exception as e:
        return "URL 추출 오류", f"기사를 불러오는 중 오류 발생: {e}"

def extract_text_from_file(uploaded_file):
    if uploaded_file.name.endswith('.txt'):
        return uploaded_file.read().decode('utf-8')
    elif uploaded_file.name.endswith('.pdf'):
        if PdfReader is None:
            st.error("pypdf 패키지가 필요합니다.")
            return ""
        pdf_reader = PdfReader(uploaded_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    return ""

def parse_multi_agendas(full_text, llm):
    prompt = PromptTemplate.from_template("""
다음은 제주특별자치도정의 일일보고자료 또는 통합 보고서 텍스트이다.
문서 내 포함된 개별 안건들을 파싱하여 JSON 배열 형태로 반환하라.

[응답 형식 (JSON만 정확히 출력)]
[
  {{
    "id": 1,
    "title": "안건 제목",
    "dept": "소관부서명",
    "content": "해당 안건의 주요 보고 내용 및 상세 요약"
  }}
]

[보고서 텍스트]
{text}
""")
    chain = prompt | llm | StrOutputParser()
    result_str = chain.invoke({"text": full_text[:200000]})
    
    clean_json = result_str.strip()
    clean_json = re.sub(r"^`{3}(?:json)?\s*", "", clean_json, flags=re.IGNORECASE)
    clean_json = re.sub(r"\s*`{3}$", "", clean_json).strip()
    
    try:
        return json.loads(clean_json)
    except Exception as e:
        st.error(f"안건 구조화 파싱 실패: {e}")
        return []

# ---------------------------------------------------------------------
# 🖥️ 메인 UI 레이아웃
# ---------------------------------------------------------------------
# 1, 2. 타이틀 및 자막 수정
st.title("🌋 제주도정 현안대응 시스템")
st.caption("제주특별자치도 수석 전용 의사결정 지원 플랫폼")

col1, col2 = st.columns([1, 1.2])
analysis_target = {"title": "", "summary": ""}

with col1:
    st.subheader("📥 분석 대상 데이터 입력")
    tab1, tab2, tab3 = st.tabs(["📰 수집 뉴스 선택", "🔗 외부 URL 입력", "📁 문서 파일 업로드"])
    
    # [1] 수집 뉴스 선택 (깔끔한 라디오 버튼 방식)
    with tab1:
        if os.path.exists("jeju_daily_news.csv"):
            df = pd.read_csv("jeju_daily_news.csv")
            
            categories = ["전체"] + list(df['category'].unique()) if 'category' in df.columns else ["전체"]
            selected_cat = st.selectbox("📌 분야별 필터", categories)
            
            filtered_df = df if selected_cat == "전체" else df[df['category'] == selected_cat]
            display_df = filtered_df.head(10)
            
            if len(display_df) > 0:
                news_titles = display_df['title'].tolist()
                selected_title = st.radio(
                    "📰 분석할 현안 기사를 선택하세요:",
                    news_titles,
                    index=0
                )
                
                selected_news = display_df[display_df['title'] == selected_title].iloc[0]
                analysis_target["title"] = selected_news['title']
                analysis_target["summary"] = selected_news['summary']
            else:
                st.warning(f"'{selected_cat}' 카테고리에 수집된 제주 관련 기사가 없습니다.")
        else:
            st.warning("수집된 뉴스 데이터가 없습니다. 사이드바의 [최신 제주 현안 수집] 버튼을 눌러주세요.")

    # [2] 외부 URL 입력
    with tab2:
        input_url = st.text_input("분석할 뉴스/기사 URL을 입력하세요:")
        if input_url:
            with st.spinner("기사 본문을 읽어오는 중..."):
                url_title, url_content = extract_text_from_url(input_url)
                analysis_target["title"] = url_title
                analysis_target["summary"] = url_content
                st.success(f"**추출된 제목:** {url_title}")
                st.text_area("추출된 본문 미리보기", url_content[:500], height=150)

    # [3] 문서 파일 업로드
    with tab3:
        doc_type = st.radio(
            "문서 유형 선택:", 
            ["단일 안건 보고서", "다중 안건 통합보고서 (일일보고자료 등)"], 
            horizontal=True
        )
        uploaded_file = st.file_uploader("관련 보고서 파일 업로드 (TXT, PDF)", type=["txt", "pdf"])
        
        if uploaded_file is not None:
            raw_text = extract_text_from_file(uploaded_file)
            
            if doc_type == "단일 안건 보고서":
                analysis_target["title"] = f"업로드 문서: {uploaded_file.name}"
                analysis_target["summary"] = raw_text[:3000]
                st.success(f"'{uploaded_file.name}' 단일 문서 로드 완료!")
                st.text_area("문서 내용 미리보기", raw_text[:500], height=150)
            else:
                st.info("💡 다중 안건 보고서에서 세부 안건 목록을 자동 분류합니다.")
                if not active_api_key:
                    st.error("⚠️ API 키가 설정되지 않았습니다. 사이드바에 Gemini API Key를 입력하세요.")
                else:
                    if "parsed_agendas" not in st.session_state or st.session_state.get("file_name") != uploaded_file.name:
                        with st.spinner("AI가 보고서 내 개별 안건 목록을 분석 중입니다..."):
                            _, llm = load_policy_advisor(active_api_key)
                            parsed_agendas = parse_multi_agendas(raw_text, llm)
                            st.session_state["parsed_agendas"] = parsed_agendas
                            st.session_state["file_name"] = uploaded_file.name
                    
                    agendas = st.session_state.get("parsed_agendas", [])
                    if agendas:
                        st.success(f"총 **{len(agendas)}**개의 세부 안건이 확인되었습니다.")
                        agenda_options = [f"[{a.get('id', i+1)}] {a.get('title')} ({a.get('dept', '소관부서')})" for i, a in enumerate(agendas)]
                        selected_agenda_str = st.selectbox("분석할 안건을 선택하세요:", agenda_options)
                        
                        selected_idx = agenda_options.index(selected_agenda_str)
                        target_agenda = agendas[selected_idx]
                        analysis_target["title"] = f"[{target_agenda.get('dept', '도정현안')}] {target_agenda.get('title')}"
                        analysis_target["summary"] = target_agenda.get('content', '')
                        st.info(f"**선택 안건 상세 내용:**\n{analysis_target['summary']}")
                    else:
                        st.warning("안건 파싱 실패. 단일 안건 모드로 전환하여 검토하세요.")

# ---------------------------------------------------------------------
# 📋 3축 분석 및 보고서 출력
# ---------------------------------------------------------------------
with col2:
    st.subheader("📋 3축(정책·법률·정무) 분석 리포트")
    
    if st.button("🚀 현안 3축 분석 리포트 생성", type="primary", use_container_width=True):
        if not analysis_target["summary"]:
            st.warning("⚠️ 분석할 데이터가 선택되지 않았습니다.")
        elif not active_api_key:
            st.error("⚠️ Gemini API Key가 입력되지 않았습니다! 사이드바 입력창에 입력해 주세요.")
        else:
            with st.spinner("제주특별법 및 관련 도 조례 DB 검토 중..."):
                try:
                    retriever, llm = load_policy_advisor(active_api_key)
                    current_time = datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분")
                    
                    query = f"{analysis_target['title']} {analysis_target['summary']}"
                    relevant_docs = retriever.invoke(query)
                    context_law = "\n\n".join([f"[{doc.metadata.get('name', '관련 법령/조례')}]\n{doc.page_content}" for doc in relevant_docs])
                    
                    prompt_template = """
너는 제주특별자치도의 민선 9기 위성곤 도지사를 보좌하는 정책수석이야.
아래 제공된 현안 자료와 상위법령 및 제주도 조례 검색 데이터를 바탕으로 1페이지 정책 브리핑 리포트를 작성하라.

[현안 자료]
- 제목/안건명: {news_title}
- 내용 요약: {news_summary}

[검색된 참조 자치법규 및 상위법령]
{context_law}

[보고서 작성 가이드라인]
1. 보고서 상단 헤더:
   - 별도의 수신자/보고대상(예: 수신: 도지사 등)은 절대로 표기하지 말 것.
   - 작성자/발신자는 '작성자: 정책수석'으로만 명시할 것 (직급/등급 표기 금지).
   - 분석·보고 일시: {current_time} 표기.
2. 본문 작성 항목:
   - 현안 개요: 이슈 핵심 및 도정에 미치는 영향 요약 (2-3줄)
   - 법률적 검토: 제주특별법 특례 적용 여부, 관련 도 조례 저촉성 및 행정 조치 근거
   - 정무적 판단: 도민 정서 파급력, 여론 및 의회/언론 리스크 평가 (위험도: 상/중/하 명시)
   - 정책 대안: 단기 부서 조치 및 민선 9기 공약 연계 중장기 대책
   - 도정 메시지 방안: 공식 브리핑용 핵심 메시지(Key Message) 및 도민 설득 프레임

보고서는 격식 있고 명확한 어조로 작성할 것.
"""
                    prompt = PromptTemplate.from_template(prompt_template)
                    chain = prompt | llm | StrOutputParser()
                    
                    report = chain.invoke({
                        "news_title": analysis_target['title'],
                        "news_summary": analysis_target['summary'],
                        "context_law": context_law if context_law else "관련 법령/조례 검색 결과 없음",
                        "current_time": current_time
                    })
                    
                    st.markdown(report)
                    
                    # 4. 한글 깨짐 방지 처리 (UTF-8-SIG BOM 인코딩 적용)
                    utf8_bom_report = ("\ufeff" + report).encode("utf-8-sig")
                    
                    st.download_button(
                        label="📥 보고서 텍스트 다운로드",
                        data=utf8_bom_report,
                        file_name=f"정책수석보고_{analysis_target['title'][:10]}.txt",
                        mime="text/plain; charset=utf-8-sig",
                        use_container_width=True
                    )
                except Exception as e:
                    st.error(f"분석 중 오류 발생: {e}")
