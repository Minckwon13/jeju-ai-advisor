import feedparser
import pandas as pd
from datetime import datetime
import urllib.parse

class JejuNewsPipeline:
    def __init__(self):
        # 제주 관련 핵심 키워드 및 제외 키워드 설정
        self.keywords = ["제주도정", "제주도지사 위성곤", "제주특별자치도", "제주도의회"]
        self.exclude_words = ["경기도", "충남", "경남", "경북", "전남", "전북", "충북", "강원", "서울시"]

    def fetch_news(self, keyword):
        # 타 지자체 기사 제외를 위한 검색 쿼리 구성
        query = f"{keyword} -경기도 -충남지사 -경남지사"
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(rss_url)
        
        articles = []
        for entry in feed.entries[:15]:
            title = entry.title
            summary = entry.summary if 'summary' in entry else ""
            
            # 1차 필터링: 제목이나 요약에 '제주' 또는 '위성곤'이 반드시 포함되어야 함
            if not ("제주" in title or "위성곤" in title or "제주" in summary):
                continue
                
            # 2차 필터링: 타 지자체 관련 단어가 포함된 경우 제외
            if any(ex in title for ex in self.exclude_words):
                continue

            articles.append({
                "category": keyword,
                "title": title,
                "link": entry.link,
                "published": entry.published if 'published' in entry else "",
                "summary": summary
            })
        return articles

    def run(self):
        all_articles = []
        for kw in self.keywords:
            all_articles.extend(self.fetch_news(kw))
            
        df = pd.DataFrame(all_articles)
        if not df.empty:
            df = df.drop_duplicates(subset=['title'])
            df.to_csv("jeju_daily_news.csv", index=False, encoding="utf-8-sig")
            print(f"[{datetime.now()}] 정제된 제주 현안 뉴스 {len(df)}건 수집 완료.")
        return df

if __name__ == "__main__":
    pipeline = JejuNewsPipeline()
    pipeline.run()
