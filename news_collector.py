import feedparser
import pandas as pd
from datetime import datetime, timedelta, timezone
import urllib.parse
import time

class JejuNewsPipeline:
    def __init__(self):
        # 1. 제주의소리 전수 수집 쿼리 (24시간 이내)
        self.jejosori_query = "site:jejosori.net when:1d"
        
        # 2. 제주 주요 언론사 24시간 이내 주요 현안 쿼리
        self.major_media_queries = [
            "site:hallailbo.co.kr when:1d",
            "site:jemin.com when:1d",
            "site:headlinejeju.co.kr when:1d",
            "site:jejudomin.co.kr when:1d",
            "제주도정 OR 제주도의회 OR 제주사회 when:1d"
        ]

    def fetch_rss(self, query, category_label):
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(rss_url)
        
        now = datetime.now(timezone.utc)
        time_limit = now - timedelta(hours=24)
        
        articles = []
        for entry in feed.entries:
            title = entry.title
            summary = entry.get('summary', '')
            published_parsed = entry.get('published_parsed')
            
            # 24시간 이내 발행 여부 재검증
            if published_parsed:
                pub_dt = datetime.fromtimestamp(time.mktime(published_parsed), tz=timezone.utc)
                if pub_dt < time_limit:
                    continue
            
            articles.append({
                "category": category_label,
                "title": title,
                "link": entry.link,
                "published": entry.get('published', ''),
                "summary": summary
            })
        return articles

    def run(self):
        all_articles = []
        
        # [단계 1] 제주의소리 24시간 기사 전체 수집
        jejosori_docs = self.fetch_rss(self.jejosori_query, "제주의소리(전수)")
        all_articles.extend(jejosori_docs)
        
        # [단계 2] 제주 주요 언론사 24시간 기사 수집
        for q in self.major_media_queries:
            media_docs = self.fetch_rss(q, "제주지역 주요뉴스")
            all_articles.extend(media_docs)
            
        df = pd.DataFrame(all_articles)
        if not df.empty:
            # 중복 기사 제거 및 CSV 저장
            df = df.drop_duplicates(subset=['title'])
            df.to_csv("jeju_daily_news.csv", index=False, encoding="utf-8-sig")
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 24시간 이내 제주 현안 뉴스 총 {len(df)}건 수집 완료.")
        return df

if __name__ == "__main__":
    pipeline = JejuNewsPipeline()
    pipeline.run()
