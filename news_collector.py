import os
import time
import requests
import feedparser
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class JejuNewsPipeline:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def fetch_jejusori_web(self):
        articles = []
        urls = [
            "https://www.jejusori.net/news/articleList.html",
            "https://www.jejusori.net/news/articleList.html?page=2"
        ]
        for url in urls:
            try:
                res = requests.get(url, headers=self.headers, verify=False, timeout=8)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    link_tags = soup.find_all('a', href=lambda h: h and 'articleView.html?idxno=' in h)
                    
                    for a in link_tags:
                        title = a.get_text(strip=True)
                        href = a.get('href', '')
                        if not title or len(title) < 5 or "댓글" in title or "기사보기" in title:
                            continue
                        link = "https://www.jejusori.net" + href if href.startswith('/') else href
                        if not link.startswith('http'):
                            link = "https://www.jejusori.net/news/" + href
                            
                        articles.append({
                            "category": "제주의소리",
                            "title": title,
                            "link": link,
                            "published": "최근 24시간 내",
                            "summary": title
                        })
            except Exception as e:
                print(f"웹 수집 예외: {e}")
        return articles

    def fetch_jejusori_rss(self):
        articles = []
        rss_urls = [
            "https://www.jejusori.net/rss/allArticle.xml",
            "https://www.jejusori.net/rss/S1N1.xml"
        ]
        for url in rss_urls:
            try:
                feed = feedparser.parse(url, request_headers=self.headers)
                for entry in feed.entries:
                    title = entry.get('title', '').strip()
                    if title and len(title) >= 5:
                        summary = entry.get('summary', '') or entry.get('description', '')
                        clean_summary = BeautifulSoup(summary, "html.parser").get_text(strip=True) if summary else title
                        articles.append({
                            "category": "제주의소리",
                            "title": title,
                            "link": entry.get('link', ''),
                            "published": entry.get('published', '최근 24시간 내'),
                            "summary": clean_summary if clean_summary else title
                        })
            except Exception as e:
                print(f"RSS 수집 예외: {e}")
        return articles

    def fetch_google_rss_fallback(self):
        articles = []
        url = "https://news.google.com/rss/search?q=site:jejusori.net&hl=ko&gl=KR&ceid=KR:ko"
        try:
            feed = feedparser.parse(url, request_headers=self.headers)
            for entry in feed.entries[:20]:
                title = entry.get('title', '').strip()
                if title.endswith("- 제주의소리"):
                    title = title[:-10].strip()
                if title and len(title) >= 5:
                    articles.append({
                        "category": "제주의소리",
                        "title": title,
                        "link": entry.get('link', ''),
                        "published": entry.get('published', '최근 24시간 내'),
                        "summary": title
                    })
        except Exception as e:
            print(f"구글 백업 예외: {e}")
        return articles

    def classify_article(self, title, summary):
        text = f"{title} {summary}"
        tags = []
        if "위성곤" in text:
            tags.append("위성곤")
        if "제주도정" in text or "도정" in text:
            tags.append("제주도정")
        if not tags:
            tags.append("일반현안")
        return ",".join(tags)

    def run(self):
        all_articles = []
        all_articles.extend(self.fetch_jejusori_web())
        if len(all_articles) < 5:
            all_articles.extend(self.fetch_jejusori_rss())
        if len(all_articles) < 5:
            all_articles.extend(self.fetch_google_rss_fallback())

        df = pd.DataFrame(all_articles)
        if not df.empty:
            df = df.drop_duplicates(subset=['title'])
            df['tag'] = df.apply(lambda r: self.classify_article(r['title'], r['summary']), axis=1)
            df = df.head(40)
        else:
            df = pd.DataFrame([{
                "category": "제주의소리",
                "title": "현재 최신 기사를 불러오는 중입니다. 잠시 후 [뉴스 수집] 버튼을 눌러주세요.",
                "link": "https://www.jejusori.net",
                "published": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "summary": "네트워크 연결 상태를 확인 중입니다.",
                "tag": "일반현안"
            }])

        df.to_csv("jeju_daily_news.csv", index=False, encoding="utf-8-sig")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] '제주의소리' 최신 기사 {len(df)}건 최신화 완료.")
        return df

if __name__ == "__main__":
    pipeline = JejuNewsPipeline()
    pipeline.run()
