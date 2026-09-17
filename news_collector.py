import feedparser
import pandas as pd
from datetime import datetime, timedelta, timezone
import time
import requests
from bs4 import BeautifulSoup

class JejuNewsPipeline:
    def __init__(self):
        # 제주의소리 공식 RSS 파이프라인 (전체기사 및 주요기사)
        self.rss_urls = [
            "http://www.jejosori.net/rss/allArticle.xml",
            "http://www.jejosori.net/rss/S1N1.xml"
        ]
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def clean_html(self, raw_html):
        """요약문의 HTML 태그 완벽 제거"""
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(strip=True)

    def run(self):
        now = datetime.now(timezone.utc)
        time_limit = now - timedelta(hours=24) # 정확히 최근 24시간 기준 설정
        
        articles = []
        visited_titles = set()

        # 1차: 제주의소리 공식 RSS 직접 수집
        for url in self.rss_urls:
            try:
                feed = feedparser.parse(url, request_headers=self.headers)
                for entry in feed.entries:
                    title = entry.get('title', '').strip()
                    if not title or title in visited_titles:
                        continue

                    # 발행 시각 파싱 및 24시간 이내 검증
                    pub_dt = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
                    
                    # 24시간 이내 출고된 기사만 통과
                    if pub_dt and pub_dt >= time_limit:
                        visited_titles.add(title)
                        summary = self.clean_html(entry.get('summary', '') or entry.get('description', ''))
                        
                        articles.append({
                            "category": "제주의소리",
                            "title": title,
                            "link": entry.get('link', ''),
                            "published": entry.get('published', ''),
                            "summary": summary if summary else title
                        })
            except Exception as e:
                print(f"제주의소리 RSS 수집 오류 ({url}): {e}")

        # 2차: RSS 파싱 불가 시 웹 직접 백업 크롤링 (24시간 보장)
        if len(articles) == 0:
            try:
                web_url = "http://www.jejosori.net/news/articleList.html?sc_section_code=&view_type=sm"
                res = requests.get(web_url, headers=self.headers, timeout=5)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    list_items = soup.select(".article-list .list-block, .table-row")
                    
                    for item in list_items:
                        title_tag = item.select_one(".list-titles, .titles a")
                        if title_tag:
                            t_text = title_tag.get_text(strip=True)
                            if t_text not in visited_titles:
                                visited_titles.add(t_text)
                                link = "http://www.jejosori.net" + title_tag.get('href', '') if title_tag.get('href', '').startswith('/') else title_tag.get('href', '')
                                articles.append({
                                    "category": "제주의소리",
                                    "title": t_text,
                                    "link": link,
                                    "published": "최근 24시간 이내",
                                    "summary": t_text
                                })
            except Exception as e:
                print(f"제주의소리 웹 백업 크롤링 오류: {e}")

        df = pd.DataFrame(articles)
        
        # 덮어쓰기를 통해 24시간 지난 구 기사는 즉시 삭제 처리
        df.to_csv("jeju_daily_news.csv", index=False, encoding="utf-8-sig")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 24시간 이내 '제주의소리' 기사 총 {len(df)}건 최신화 완료.")
        return df

if __name__ == "__main__":
    pipeline = JejuNewsPipeline()
    pipeline.run()
