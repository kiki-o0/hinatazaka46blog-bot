import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.hinatazaka46.com"
# ご自身のリポジトリ名に合わせて変更してください（今回は専用リポジトリなのでhinatazaka46blog-botです）
FEED_BASE_URL = "https://kiki-o0.github.io/hinatazaka46blog-bot/"

# メンバーの背番号リスト (日向坂46 現役・ブログ公開メンバーのみに絞り込み)
MEMBER_IDS = [
    # 卒業・ブログ閉鎖メンバーを除外
    "12", "14", # 2期生
    "21", "22", "23", "24", # 3期生・新3期生
    "25", "27", "28", "29", "30", "31", "32", "33", "34", "35", # 4期生
    "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46" # 5期生 (2025年3月加入)
]

def parse_date_to_iso(date_str):
    # ブログの投稿日時から確実な日付形式を作成
    m = re.findall(r'\d+', date_str)
    if len(m) >= 3:
        year, month, day = m[0], m[1], m[2]
        hour = m[3] if len(m) >= 4 else "00"
        minute = m[4] if len(m) >= 5 else "00"
        second = m[5] if len(m) >= 6 else "00"
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}T{hour.zfill(2)}:{minute.zfill(2)}:{second.zfill(2)}+09:00"
    return datetime.now(timezone.utc).isoformat()

def parse_article(url):
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    
    detailed_date = ""
    date_tags = soup.find_all(class_="c-blog-article__date")
    for tag in date_tags:
        text = tag.get_text(strip=True)
        if re.search(r'\d{1,2}:\d{2}', text):
            detailed_date = text
            break
            
    article = soup.find(class_="c-blog-article__text")
    if not article:
        return "", detailed_date
        
    for guide in article.find_all(class_=lambda x: x and 'app_guide' in x):
        guide.decompose()
        
    for img in article.find_all("img"):
        src = img.get("src", "")
        if not src or "app_guide" in src:
            img.decompose()
            continue
            
        img_url = urljoin(BASE_URL, src)
        safe_url = escape(img_url)
        img_html = f'<p><a href="{safe_url}"><img src="{safe_url}" alt="公式ブログ画像"></a></p>'
        img.replace_with(f"__IMG_START__{img_html}__IMG_END__")
        
    elements = []
    raw_text = article.get_text(separator="\n", strip=True)
    parts = re.split(r'__IMG_START__(.*?)__IMG_END__', raw_text)
    
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
            
        if i % 2 == 1:
            elements.append(part)
        else:
            for line in part.split("\n"):
                line = line.strip()
                if "からのメッセージを受け取る" in line or line == "日向坂46メッセージ" or line == "「日向坂46メッセージ」で":
                    continue
                if line:
                    elements.append("<p>" + escape(line) + "</p>")
                    
    return chr(10).join(elements), detailed_date

def generate_feed_for_member(member_id):
    list_url = f"{BASE_URL}/s/official/diary/member/list?ima=0000&ct={member_id}"
    try:
        res = requests.get(list_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"[{member_id}] リスト取得エラー: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    
    # メンバー名の取得方法を修正
    member_name = f"メンバー{member_id}"
    
    # 記事内の名前タグ、もしくはページタイトルからメンバー名を抽出する
    name_tag = soup.find(class_="c-blog-article__name")
    if name_tag:
        member_name = name_tag.text.strip()
    else:
        page_title = soup.title.text if soup.title else ""
        if "公式ブログ" in page_title:
            member_name = page_title.split("公式ブログ")[0].strip()

    posts = soup.find_all("div", class_="p-blog-article")
    if not posts:
        print(f"[{member_id}] 記事が見つかりません")
        return
        
    entries = []
    feed_updated = None
    
    for post in posts[:3]:
        post_a = post.find("a", class_="c-button-blog-detail")
        if not post_a:
            post_a = post.find("div", class_="c-blog-article__title").find("a")
            if not post_a:
                continue
            
        article_url = urljoin(BASE_URL, post_a["href"])
        
        title_tag = post.find(class_="c-blog-article__title")
        title = title_tag.text.strip() if title_tag else "無題"
        
        print(f"  -> 記事取得中: {title}")
        content, detailed_date = parse_article(article_url)
        time.sleep(1)
        
        if not detailed_date:
            date_tag = post.find(class_="c-blog-article__date")
            detailed_date = date_tag.text.strip() if date_tag else ""
            
        entry_updated = parse_date_to_iso(detailed_date)
        
        if not feed_updated:
            feed_updated = entry_updated
        
        entry = f"""
  <entry>
    <title>{escape(title)}</title>
    <id>{escape(article_url)}</id>
    <link href="{escape(article_url)}"/>
    <updated>{escape(entry_updated)}</updated>
    <author>
      <name>{escape(member_name)}</name>
    </author>
    <content type="html"><![CDATA[
{content}
    ]]></content>
  </entry>"""
        entries.append(entry)

    if not entries:
        return
        
    if not feed_updated:
        feed_updated = datetime.now(timezone.utc).isoformat()
        
    feed_filename = f"feed_{member_id}.xml"
    feed_url = f"{FEED_BASE_URL}{feed_filename}"
    
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>日向坂46｜{escape(member_name)} 公式ブログ</title>
  <id>{escape(feed_url)}</id>
  <updated>{escape(feed_updated)}</updated>
  <link href="{escape(feed_url)}" rel="self"/>{"".join(entries)}
</feed>
"""
    with open(f"feeds/{feed_filename}", "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"[{member_id}] {member_name} のフィード生成完了 (feeds/{feed_filename})")

def main():
    print("=== 全メンバーのRSS生成を開始します ===")
    os.makedirs("feeds", exist_ok=True)
    for member_id in MEMBER_IDS:
        generate_feed_for_member(member_id)
        time.sleep(1)
    print("=== 全ての処理が完了しました ===")

if __name__ == "__main__":
    main()
