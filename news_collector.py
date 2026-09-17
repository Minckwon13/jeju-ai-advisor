import feedparser
import pandas as pd
import urllib.parse
import re
from datetime import datetime

class JejuNewsPipeline:
    def __init__(self):
        # 민선 9기 도정 및 도지사 전용 태그 강화 카테고리 매핑
        self.category_keywords = {
            "도지사/핵심도정": ["위성곤", "제주도지사", "제주특별자치도지사", "도지사 공약", "제주도정"],
            "정무/의회": ["제주도의회", "제주 정치", "도정질문", "제주 정당"],
            "특별법/특례": ["제주특별법", "행정체제개편", "상급종합병원", "제주 특례"],
            "민생/경제": ["제주 물가", "제주 관광", "제주 농축산", "제주 수산", "제주 민생"],
            "환경/도시": ["제주 쓰레기", "제주 지하수", "제주 풍력", "제주 도시계획", "제주 환경"],
            "4·3/복지": ["제주 4·3", "제주 복지", "제주 돌봄"]
        }

    def clean_text(self, text):
        """HTML 태그 및 불필요한 특수문자 정제"""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'&[^;]+;', '', text)
        return text.strip()

    def fetch_rss_news(self, keyword, category):
        encoded = urllib.parse.quote(keyword)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(rss_url)
        
        articles = []
        for entry in feed.entries[:10]: # 키워드당 상위 10개 수집
            title = self.clean_text(entry.title)
            summary = self.clean_text(entry.summary if 'summary' in entry else "")
            
            articles.append({
                "category": category,
                "keyword": keyword,
                "title": title,
                "link": entry.link,
                "published": getattr(entry, 'published', datetime.now().strftime("%Y-%m-%d %H:%M")),
                "summary": summary[:250] + "..." if len(summary) > 250 else summary,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        return articles

    def run(self):
        all_articles = []
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 실시간 제주 현안 및 도지사 동향 뉴스 수집 시작...")
        
        for cat, keywords in self.category_keywords.items():
            for kw in keywords:
                articles = self.fetch_rss_news(kw, cat)
                all_articles.extend(articles)
        
        df = pd.DataFrame(all_articles)
        if not df.empty:
            # 기사 제목 기준 중복 제거 및 인덱스 재정렬
            df = df.drop_duplicates(subset=['title']).reset_index(drop=True)
            df.to_csv("jeju_daily_news.csv", index=False, encoding="utf-8-sig")
            
            gov_news_cnt = len(df[df['category'] == "도지사/핵심도정"])
            print(f"✅ 수집 완료: 총 {len(df)}건 수집 (도지사/핵심도정 관련 기사: {gov_news_cnt}건)")
            print("💾 'jeju_daily_news.csv' 파일에 저장되었습니다.")
        else:
            print("⚠️ 수집된 뉴스가 없습니다.")
        return df

if __name__ == "__main__":
    pipeline = JejuNewsPipeline()
    pipeline.run()