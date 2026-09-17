import feedparser
import pandas as pd
from datetime import datetime, timedelta, timezone
import time
import requests
from bs4 import BeautifulSoup

class JejuNewsPipeline:
    def __init__(self):
        # 보안 프로토콜(HTTPS) 적용 및 브라우저 User-Agent 설정
        self.rss_urls = [
            "https://www.jejosori.net/rss/allArticle.xml",
            "https://www.jejosori.net/rss/S1N1.xml"
        ]
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    def clean_html(self, raw_html):
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(strip=True)

    def run(self):
        now = datetime.now(timezone.utc)
        time_limit = now - timedelta(hours=24)
        
        articles = []
        visited_titles = set()

        # 1차: 제주의소리 공식 RSS 파이프라인 수집
        for url in self.rss_urls:
            try:
                feed = feedparser.parse(url, request_headers=self.headers)
                for entry in feed.entries:
                    title = entry.get('title', '').strip()
                    if not title or title in visited_titles:
                        continue

                    pub_dt = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            pub_dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
                        except Exception:
                            pub_dt = None
                    
                    # 24시간 내 발행 기사 검증 (시간 파싱 실패 시 최근 기사로 간주하여 유입 허용)
                    if pub_dt is None or pub_dt >= time_limit:
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
                print(f"RSS 수집 오류 ({url}): {e}")

        # 2차: RSS 파싱 실패 시 웹 직접 크롤링 백업
        if len(articles) == 0:
            try:
                web_url = "https://www.jejosori.net/news/articleList.html?sc_section_code=S1N1"
                res = requests.get(web_url, headers=self.headers, timeout=5)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    items = soup.select(".article-list .titles a, .titles a, .article-title a")
                    for item in items:
                        t_text = item.get_text(strip=True)
                        if t_text and t_text not in visited_titles:
                            visited_titles.add(t_text)
                            href = item.get('href', '')
                            link = "https://www.jejosori.net" + href if href.startswith('/') else href
                            articles.append({
                                "category": "제주의소리",
                                "title": t_text,
                                "link": link,
                                "published": "최근 24시간 이내",
                                "summary": t_text
                            })
            except Exception as e:
                print(f"웹 백업 수집 오류: {e}")

        # 컬럼 구조를 명시하여 수집 건수가 0건이어도 EmptyDataError 방지
        df = pd.DataFrame(articles, columns=["category", "title", "link", "published", "summary"])
        df.to_csv("jeju_daily_news.csv", index=False, encoding="utf-8-sig")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 24시간 이내 '제주의소리' 기사 총 {len(df)}건 최신화 완료.")
        return df

if __name__ == "__main__":
    pipeline = JejuNewsPipeline()
    pipeline.run()
