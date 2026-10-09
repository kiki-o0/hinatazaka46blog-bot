import os
import re
import time
import json
from datetime import datetime, timezone
from urllib.parse import urljoin
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.hinatazaka46.com"
FEED_BASE_URL = "https://kiki-o0.github.io/hinatazaka46blog-bot/"
STATE_FILE = "last_blogs.json"

MEMBER_MAPPING = {
    # 2期生
    "12": "金村 美玖", "14": "小坂 菜緒",
    # 3期生・新3期生
    "21": "上村 ひなの", "22": "高橋 未来虹", "23": "森本 茉莉",
    # 4期生
    "25": "石塚 瑶季", "27": "小西 夏菜実", "28": "清水 理央", "29": "正源司 陽子", 
    "30": "竹内 希来里", "31": "平尾 帆夏", "32": "平岡 海月", "33": "藤嶌 果歩", 
    "34": "宮地 すみれ", "35": "山下 葉留花", "36": "渡辺 莉奈",
    # 5期生
    "37": "大田 美月", "38": "大野 愛実", "39": "片山 紗希", "40": "蔵盛 妃那乃", 
    "41": "坂井 新奈", "42": "佐藤 優羽", "43": "下田 衣珠季", "44": "高井 俐香", 
    "45": "鶴崎 仁香", "46": "松尾 桜"
}

def parse_date_to_iso(date_str):
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
        img_html = f'<p><a href="{safe_url}"><img src="{safe_url}" alt=""></a></p>'
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
                    safe_line = escape(line)
                    linked_line = re.sub(r'(https?://[a-zA-Z0-9./?=_-]+)', r'<a href="\1" target="_blank">\1</a>', safe_line)
                    elements.append("<p>" + linked_line + "</p>")
                    
    return chr(10).join(elements), detailed_date

def generate_feed_for_member(member_id, state):
    member_name = MEMBER_MAPPING.get(member_id, f"メンバー{member_id}")
    safe_member_name = member_name.replace(" ", "").replace("　", "")
    
    member_state = state.get(member_id, [])
    if not isinstance(member_state, list):
        print(f"[{member_id}] [警告] 古い形式の記憶を見つけたため、新しく作り直します。")
        member_state = []
        
    known_urls = { entry["url"]: entry for entry in member_state if isinstance(entry, dict) and "url" in entry }
    
    list_url = f"{BASE_URL}/s/official/diary/member/list?ima=0000&ct={member_id}"
    print(f"[{member_id}] [RSS取得中] {member_name} のブログ一覧にアクセスしています...")
    try:
        res = requests.get(list_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"[{member_id}] [エラー] リスト取得失敗: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    posts = soup.find_all("div", class_="p-blog-article")
    if not posts:
        print(f"[{member_id}] [スキップ] {member_name} の新着記事が見つかりません")
        return
        
    new_member_state = []
    feed_updated = None
    
    print(f"[{member_id}] [解析中] {member_name} の記事を処理します（最大15件）")
    
    for post in posts:
        if len(new_member_state) >= 15:
            break
            
        post_a = post.find("a", class_="c-button-blog-detail")
        if not post_a:
            post_a = post.find("div", class_="c-blog-article__title")
            if post_a:
                post_a = post_a.find("a")
            if not post_a:
                continue
                
        href = post_a.get("href", "")
        article_url = urljoin(BASE_URL, href)
            
        title_tag = post.find(class_="c-blog-article__title")
        title = title_tag.text.strip() if title_tag and title_tag.text.strip() else "無題"
            
        post_name_tag = post.find(class_="c-blog-article__name")
        if post_name_tag:
            post_author = post_name_tag.text.strip()
            safe_post_author = post_author.replace(" ", "").replace("　", "")
            if not safe_member_name.startswith("メンバー") and safe_post_author != safe_member_name:
                print(f"  -> [除外] 他メンバー（{post_author}）の記事を検知: スキップします")
                continue
        
        if article_url in known_urls:
            print(f"  -> [高速スキップ] 既知の記事です（データ復元）: {title}")
            known_data = known_urls[article_url]
            new_member_state.append(known_data)
            if not feed_updated:
                feed_updated = known_data["updated"]
            continue
        
        print(f"  -> [新規取得中] 記事タイトル: {title}")
        try:
            content, detailed_date = parse_article(article_url)
            print(f"     => [成功] 記事解析完了")
        except Exception as e:
            print(f"     => [エラー] 記事解析失敗 ({article_url}): {e}")
            continue
            
        time.sleep(3)
        
        if not detailed_date:
            date_tag = post.find(class_="c-blog-article__date")
            detailed_date = date_tag.text.strip() if date_tag else ""
            
        entry_updated = parse_date_to_iso(detailed_date)
        if not feed_updated:
            feed_updated = entry_updated
            
        new_member_state.append({
            "url": article_url,
            "title": title,
            "updated": entry_updated,
            "content": content
        })

    if not new_member_state:
        print(f"[{member_id}] [スキップ] {member_name} の有効なブログ記事はありませんでした")
        return
        
    if not feed_updated:
        feed_updated = datetime.now(timezone.utc).isoformat()
        
    entries_xml = ""
    for entry_data in new_member_state:
        entries_xml += f"""
  <entry>
    <title>{escape(entry_data['title'])}</title>
    <id>{escape(entry_data['url'])}</id>
    <link href="{escape(entry_data['url'])}"/>
    <updated>{escape(entry_data['updated'])}</updated>
    <author>
      <name>{escape(member_name)}</name>
    </author>
    <content type="html"><![CDATA[
{entry_data['content']}
    ]]></content>
  </entry>"""
        
    feed_filename = f"feed_{member_id}.xml"
    feed_url = f"{FEED_BASE_URL}{feed_filename}"
    
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>日向坂46｜{escape(member_name)} 公式ブログ</title>
  <id>{escape(feed_url)}</id>
  <updated>{escape(feed_updated)}</updated>
  <link href="{escape(feed_url)}" rel="self"/>{entries_xml}
</feed>
"""
    with open(f"feeds/{feed_filename}", "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"[{member_id}] [完了] {member_name} のフィード生成 (feeds/{feed_filename})")
    
    state[member_id] = new_member_state

def main():
    print("=== [処理開始] 全メンバーのRSS生成を開始します ===")
    os.makedirs("feeds", exist_ok=True)
    
    if os.path.exists(STATE_FILE):
        print("-> [読込] 過去のブログ履歴データを読み込みます...")
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            print(f"-> [警告] 履歴ファイルの読み込みに失敗しました。新規で作成します: {e}")
            state = {}
    else:
        print("-> [読込] 過去の履歴がありません。新規で全取得します。")
        state = {}

    for member_id in MEMBER_MAPPING.keys():
        generate_feed_for_member(member_id, state)
        time.sleep(3)
        
    print(f"=== [保存] ブログ履歴データを {STATE_FILE} に保存します ===")
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"-> [エラー] 履歴ファイルの保存に失敗しました: {e}")
        
    print("=== [処理完了] 全てのRSS生成が正常に終了しました ===")

if __name__ == "__main__":
    main()
