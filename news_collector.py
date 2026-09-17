import os
import re
import time
import requests
import feedparser
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
import urllib3

# SSL 인증서 경고 비활성화 (서버 연동 오류 방지)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class JejuNewsPipeline:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def fetch_jejusori_web(self):
        """1차 시도: 제주의소리 전체기사 목록(articleList.html) 직접 스크래핑"""
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
                    # articleView.html?idxno= 링크 탐색
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
                print(f"웹 직접 수집 시도 중 예외 발생 ({url}): {e}")
                
        return articles

    def fetch_jejusori_rss(self):
        """2차 시도: 제주의소리 RSS 수집"""
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
                print(f"RSS 수집 시도 중 예외 발생 ({url}): {e}")
        return articles

    def fetch_google_rss_fallback(self):
        """3차 시도: 구글 뉴스 RSS 백업 수집 (site:jejusori.net)"""
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
            print(f"구글 RSS 백업 수집 시도 중 예외 발생: {e}")
        return articles

    def run(self):
        all_articles = []
        
        # 1차 웹 수집
        web_articles = self.fetch_jejusori_web()
        all_articles.extend(web_articles)
        
        # 부족할 경우 2차 RSS 및 3차 구글 백업 작동
        if len(all_articles) < 5:
            all_articles.extend(self.fetch_jejusori_rss())
        if len(all_articles) < 5:
            all_articles.extend(self.fetch_google_rss_fallback())

        df = pd.DataFrame(all_articles)
        
        if not df.empty:
            df = df.drop_duplicates(subset=['title'])
            df = df.head(30) # 최신 30개 기사 유효 보장
        else:
            # 수집 데이터가 없을 때 빈 CSV 방지용 기본 행 생성
            df = pd.DataFrame([{
                "category": "제주의소리",
                "title": "현재 제주의소리 최신 기사를 불러오는 중입니다. 잠시 후 [뉴스 수집]을 다시 눌러주세요.",
                "link": "https://www.jejusori.net",
                "published": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "summary": "네트워크 연결 상태를 확인 중입니다."
            }])

        # 덮어쓰기로 구 기사 폐기 및 최신화
        df.to_csv("jeju_daily_news.csv", index=False, encoding="utf-8-sig")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] '제주의소리' 최신 기사 {len(df)}건 수집 완료.")
        return df

if __name__ == "__main__":
    pipeline = JejuNewsPipeline()
    pipeline.run()
