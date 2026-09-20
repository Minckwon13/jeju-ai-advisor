import os
import json
import re
import zipfile
import urllib.request
from datetime import datetime, time, timedelta
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

# ---------------------------------------------------------------------
# 🖥️ 페이지 기본 설정
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="제주특별자치도 정책수석 의사결정 지원 시스템",
    page_icon="🌋",
    layout="wide"
)

# ---------------------------------------------------------------------
# 📦 Vector DB 자동 다운로드 및 압축 해제
# ---------------------------------------------------------------------
def ensure_vector_db():
    db_dir = "./jeju_db"
    zip_path = "jeju_db.zip"
    download_url = "https://github.com/YOUR_GITHUB_ID/YOUR_REPO_NAME/releases/download/v1.0.0/jeju_db.zip"

    if not os.path.exists(db_dir):
        if not os.path.exists(zip_path):
            try:
                urllib.request.urlretrieve(download_url, zip_path)
            except Exception as e:
                print(f"DB 다운로드 예외: {e}")
                return

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(".")
        except Exception as e:
            print(f"DB 압축해제 예외: {e}")

# ---------------------------------------------------------------------
# 🧠 Vector DB 검색기 로드 (RAG 데이터만 캐싱)
# ---------------------------------------------------------------------
@st.cache_resource
def load_vector_retriever():
    ensure_vector_db()
    embeddings = HuggingFaceEmbeddings(model_name="jhgan/ko-sroberta-multitask")
    vectorstore = Chroma(
        persist_directory="./jeju_db", 
        embedding_function=embeddings
    )
    return vectorstore.as_retriever(search_kwargs={"k": 5})

# ---------------------------------------------------------------------
# 🛡️ 자동 폴백(Fallback) 포함 LLM 호출 엔진
# ---------------------------------------------------------------------
def invoke_llm_with_fallback(prompt_template, input_data, api_key, primary_model):
    """선택한 모델 실패(404 등) 시 사용 가능한 모델로 자동 전환하여 호출"""
    candidate_models = [primary_model]
    
    # 폴백 후보 모델 순서 지정
    for fallback in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)
            
    last_exception = None
    
    for model_name in candidate_models:
        try:
            llm = ChatGoogleGenerativeAI(
                model=model_name, 
                google_api_key=api_key,
                temperature=0.2
            )
            chain = prompt_template | llm | StrOutputParser()
            result = chain.invoke(input_data)
            
            # 성공 시, 원래 선택한 모델과 다르면 안내 메시지 출력
            if model_name != primary_model:
                st.info(f"💡 선택하신 [{primary_model}] 모델의 API 접근이 불가하여, 호환되는 [{model_name}] 모델로 자동 전환되어 분석을 완결했습니다.")
            return result, model_name
        except Exception as e:
            last_exception = e
            err_str = str(e)
            # 404 / NOT_FOUND 에러인 경우 다음 후보 모델로 시도
            if "404" in err_str or "NOT_FOUND" in err_str or "not found" in err_str.lower():
                continue
            else:
                # 쿼터 초과(429) 등 기타 에러는 상위로 전달
                raise e
                
    raise last_exception

# ---------------------------------------------------------------------
# 📊 API 쿼터 현황 및 사용량 추적기
# ---------------------------------------------------------------------
def render_quota_tracker(selected_model):
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 API 호출 및 쿼터 현황")
    
    max_daily = 50 if "pro" in selected_model else 1500
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    if "last_date" not in st.session_state or st.session_state["last_date"] != today_str:
        st.session_state["last_date"] = today_str
        st.session_state["daily_call_count"] = 0
        
    used_calls = st.session_state.get("daily_call_count", 0)
    remaining_calls = max(0, max_daily - used_calls)
    usage_pct = min(1.0, used_calls / max_daily)
    
    st.sidebar.write(f"**오늘 사용량:** `{used_calls}` / `{max_daily}` 회")
    st.sidebar.progress(usage_pct)
    st.sidebar.caption(f"💡 잔여 예상 횟수: **{remaining_calls}회**")
    
    now = datetime.now()
    reset_time_today = datetime.combine(now.date(), time(17, 0, 0)) # 한국시간 17시 기준 (PST 00시)
    if now > reset_time_today:
        next_reset = reset_time_today + timedelta(days=1)
    else:
        next_reset = reset_time_today
        
    time_left = next_reset - now
    hours, remainder = divmod(int(time_left.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    st.sidebar.info(f"⏰ **일일 쿼터 리셋까지:** {hours}시간 {minutes}분 남음\n*(매일 오후 5시 자동 초기화)*")

def increment_usage_count():
    st.session_state["daily_call_count"] = st.session_state.get("daily_call_count", 0) + 1

# ---------------------------------------------------------------------
# ⚙️ 사이드바 시스템 설정
# ---------------------------------------------------------------------
st.sidebar.header("⚙️ 시스템 설정")

# 123번째 줄: Gemini API Key 입력 위치 (직접 입력 가능)
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

selected_model_display = st.sidebar.selectbox(
    "🤖 분석 엔진 선택:",
    [
        "gemini-2.0-flash (추천: 차세대 초고속·고성능)",
        "gemini-1.5-flash (표준: 높은 안정성 및 신속 처리)",
        "gemini-1.5-pro (심층 분석용)"
    ],
    index=0
)

if "2.0-flash" in selected_model_display:
    target_model = "gemini-2.0-flash"
    st.sidebar.info("🚀 **Gemini 2.0 Flash 활성화**: 최신 차세대 엔진으로 빠른 분석을 제공합니다.")
elif "pro" in selected_model_display:
    target_model = "gemini-1.5-pro"
    st.sidebar.info("🧠 **1.5 Pro 모델 활성화**: 자치법규 및 정책 심층 분석에 특화되어 있습니다.")
else:
    target_model = "gemini-1.5-flash"
    st.sidebar.info("⚡ **1.5 Flash 모델 활성화**: 신속하게 안건을 검토합니다.")

if st.sidebar.button("🔄 제주의소리 24시간 최신뉴스 수집"):
    with st.spinner("제주의소리 최근 24시간 기사를 수집 및 분류 중입니다..."):
        pipeline = JejuNewsPipeline()
        pipeline.run()
    st.sidebar.success("최신 뉴스 수집 완료!")
    st.rerun()

render_quota_tracker(target_model)

# ---------------------------------------------------------------------
# 🛠️ 텍스트 추출 헬퍼 함수
# ---------------------------------------------------------------------
def extract_text_from_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=7)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = soup.find('title').get_text(strip=True) if soup.find('title') else "외부 입력 기사"
        paragraphs = [p.get_text(strip=True) for p in soup.find_all('p') if len(p.get_text(strip=True)) > 20]
        content = "\n".join(paragraphs[:15])
        
        return title, content if content else "본문 추출 실패 (텍스트 분량이 부족합니다.)"
    except Exception as e:
        return "URL 추출 오류", f"기사를 불러오는 중 오류 발생: {e}"

def extract_text_from_file(uploaded_file):
    if uploaded_file.name.endswith('.txt'):
        return uploaded_file.read().decode('utf-8')
    elif uploaded_file.name.endswith('.pdf'):
        if PdfReader is None:
            st.error("pypdf 패키지가 설치되지 않았습니다.")
            return ""
        pdf_reader = PdfReader(uploaded_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    return ""

def parse_multi_agendas(full_text, api_key, model_name):
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
    try:
        result_str, _ = invoke_llm_with_fallback(
            prompt, 
            {"text": full_text[:200000]}, 
            api_key, 
            model_name
        )
        clean_json = result_str.strip()
        clean_json = re.sub(r"^`{3}(?:json)?\s*", "", clean_json, flags=re.IGNORECASE)
        clean_json = re.sub(r"\s*`{3}$", "", clean_json).strip()
        return json.loads(clean_json)
    except Exception as e:
        st.error(f"안건 구조화 파싱 실패: {e}")
        return []

# ---------------------------------------------------------------------
# 🖥️ 메인 UI 레이아웃
# ---------------------------------------------------------------------
st.title("🌋 제주도정 현안 대응 시스템")
st.caption("제주특별자치도 민선 9기 정책수석 전용 의사결정 지원 플랫폼")

col1, col2 = st.columns([1, 1.2])
analysis_target = {"title": "", "summary": ""}

with col1:
    st.subheader("📥 분석 대상 데이터 입력")
    tab1, tab2, tab3 = st.tabs(["📰 제주의소리 24h 기사", "🔗 외부 URL 입력", "📁 문서 파일 업로드"])
    
    # [1] 제주의소리 기사 선택
    with tab1:
        csv_file = "jeju_daily_news.csv"
        df = pd.DataFrame(columns=["category", "title", "link", "published", "summary", "tag"])
        
        if os.path.exists(csv_file) and os.path.getsize(csv_file) > 0:
            try:
                df = pd.read_csv(csv_file)
            except Exception:
                df = pd.DataFrame(columns=["category", "title", "link", "published", "summary", "tag"])

        if len(df) > 0:
            filter_option = st.selectbox(
                "📌 현안 분류 필터:",
                ["전체 (24h)", "제주도정 관련", "위성곤 도지사 관련", "일반 현안"]
            )
            
            if filter_option == "제주도정 관련":
                filtered_df = df[df['tag'].str.contains("제주도정", na=False)]
            elif filter_option == "위성곤 도지사 관련":
                filtered_df = df[df['tag'].str.contains("위성곤", na=False)]
            elif filter_option == "일반 현안":
                filtered_df = df[df['tag'].str.contains("일반현안", na=False)]
            else:
                filtered_df = df

            if len(filtered_df) > 0:
                news_titles = filtered_df['title'].tolist()
                selected_title = st.radio(
                    "📰 분석할 현안 기사를 선택하세요:",
                    news_titles,
                    index=0
                )
                selected_news = filtered_df[filtered_df['title'] == selected_title].iloc[0]
                analysis_target["title"] = selected_news['title']
                analysis_target["summary"] = selected_news['summary']
            else:
                st.warning(f"선택하신 필터('{filter_option}')에 해당하는 기사가 없습니다.")
        else:
            st.warning("수집된 기사가 없습니다. 사이드바의 [제주의소리 24시간 최신뉴스 수집] 버튼을 눌러주세요.")

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
                            parsed_agendas = parse_multi_agendas(raw_text, active_api_key, target_model)
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
# 📋 3축 심층 분석 및 보고서 출력
# ---------------------------------------------------------------------
with col2:
    st.subheader(f"📋 3축(정책·법률·정무) 심층 분석 [{target_model}]")
    
    if st.button("🚀 심층 3축 분석 보고서 생성", type="primary", use_container_width=True):
        if not analysis_target["summary"]:
            st.warning("⚠️ 분석할 데이터가 선택되지 않았습니다.")
        elif not active_api_key:
            st.error("⚠️ Gemini API Key가 입력되지 않았습니다! 사이드바 입력창에 입력해 주세요.")
        else:
            with st.spinner(f"[{target_model}] 엔진이 제주특별법 및 도 조례 DB를 정밀 분석 중입니다..."):
                try:
                    retriever = load_vector_retriever()
                    current_time = datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분")
                    
                    query = f"{analysis_target['title']} {analysis_target['summary']}"
                    relevant_docs = retriever.invoke(query)
                    context_law = "\n\n".join([f"[{doc.metadata.get('name', '관련 법령/조례')}]\n{doc.page_content}" for doc in relevant_docs])
                    
                    prompt_template = PromptTemplate.from_template("""
너는 제주특별자치도의 민선 9기 위성곤 도지사를 보좌하는 수석이야.
제시된 현안 자료와 상위법령/제주도 조례 검색 데이터를 바탕으로, 도지사님의 신속하고 정확한 정무적 판단을 지원할 1페이지 고품질 브리핑 리포트를 작성하라.

[현안 자료]
- 제목/안건명: {news_title}
- 내용 요약: {news_summary}

[검색된 참조 자치법규 및 상위법령]
{context_law}

[보고서 작성 가이드라인]
1. 보고서 헤더:
   - 별도의 수신자 표기(수신: 도지사 등)는 일체 제외.
   - 작성자: '작성자: 정책수석'으로 단일 표기.
   - 분석 일시: {current_time}

2. 3축 심층 분석 항목:
   - **현안 개요**: 이슈의 핵심, 갈등 발생 배경 및 도정에 미칠 직접적 파급력 (2-3줄)
   - **법률·조례 검토**: 
     * 검색된 제주특별법 특례 및 관련 도 조례 조항과의 연계성 검토
     * 도의 행정 조치(명령, 재정 지원, 조례 개정 등)에 대한 법적 당위성 및 저촉 여부 진단
   - **정무적 판단 & 리스크 평가**: 
     * 도민 민심, 지역 언론의 프레임, 제주도의회 대응 기류 분석
     * 정무적 위험도 명시 (**상 / 중 / 하**) 및 주요 리스크 요인 도출
   - **단계별 정책 대안**:
     * [단기] 소관 부서 즉시 조치 사항 (1~3일 내)
     * [중장기] 민선 9기 공약 및 제주 도정 비전과 연계한 근본 대책
   - **도정 홍보 및 메시지 방안**:
     * 도지사 공식 브리핑용 핵심 메시지 (Key Message 1~2줄)
     * 도민 설득 및 여론 반전을 위한 톤앤매너 프레임 가이드

격식 있고 간결하며, 정무적 통찰력이 돋보이는 어조로 작성할 것.
""")
                    
                    report, used_model = invoke_llm_with_fallback(
                        prompt_template,
                        {
                            "news_title": analysis_target['title'],
                            "news_summary": analysis_target['summary'],
                            "context_law": context_law if context_law else "관련 법령/조례 검색 결과 없음 (일반 지방자치법령 적용 필요)",
                            "current_time": current_time
                        },
                        active_api_key,
                        target_model
                    )
                    
                    increment_usage_count()
                    
                    st.markdown(report)
                    st.download_button(
                        label="📥 보고서 텍스트 다운로드",
                        data=report,
                        file_name=f"정책수석보고_{analysis_target['title'][:10]}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        retry_match = re.search(r"retry in ([\d\.]+)s", err_msg)
                        if retry_match:
                            seconds_wait = float(retry_match.group(1))
                            st.error(f"⚠️ **분당 호출 한도 초과!** 약 **{int(seconds_wait)}초 후**에 회복됩니다. 잠시 후 다시 시도해 주세요.")
                        else:
                            st.error("⚠️ **일일 무료 쿼터 한도를 모두 소진했습니다.** 오늘 오후 5시 자동 초기화 후 다시 사용 가능합니다.")
                    else:
                        st.error(f"분석 중 오류 발생: {e}")
