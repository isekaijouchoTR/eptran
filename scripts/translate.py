import os
import json
import shutil
import subprocess
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from groq import Groq, RateLimitError
from datetime import datetime, timezone
import time
import re

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
STATUS_FILE = "status.json"


def git_push(message):
    subprocess.run(["git", "add", "-A"], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode != 0:
        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)


def write_status(data):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    git_push(f"status: {data.get('completed', 0)}/{data.get('total', '?')}")


def extract_chapters(epub_path):
    book = epub.read_epub(epub_path)
    chapters = []

    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")

        for tag in soup(["script", "style", "nav"]):
            tag.decompose()

        text = soup.get_text(separator="\n").strip()
        text = re.sub(r"\n{3,}", "\n\n", text)

        if len(text) < 300:
            continue

        title = item.get_name()
        heading = soup.find(["h1", "h2", "h3"])
        if heading:
            title = heading.get_text().strip()

        chapters.append({"name": item.get_name(), "title": title, "text": text})

    return chapters


def chunk_text(text, max_chars=12000):
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current += "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks


def parse_retry_seconds(error_message):
    match = re.search(r'try again in ([\dhms .]+)', str(error_message))
    if not match:
        return 3600

    time_str = match.group(1).strip()
    total = 0
    for h in re.findall(r'([\d.]+)h', time_str):
        total += float(h) * 3600
    for m in re.findall(r'([\d.]+)m', time_str):
        total += float(m) * 60
    for s in re.findall(r'([\d.]+)s', time_str):
        total += float(s)

    return int(total) + 10


def translate_chunk(client, text, chapter_title, chunk_index, total_chunks):
    context = f" (Parça {chunk_index + 1}/{total_chunks})" if total_chunks > 1 else ""
    prompt = (
        f"Aşağıdaki İngilizce metni Türkçeye çevir. "
        f"Çeviriyi doğal, akıcı ve edebi tut. "
        f"Karakterlerin sesini, tonunu ve yazı stilini koru. "
        f"Sadece çeviriyi döndür, başka hiçbir şey ekleme.\n\n"
        f"Bölüm: {chapter_title}{context}\n\n"
        f"{text}"
    )

    while True:
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.choices[0].message.content
        except RateLimitError as e:
            wait = parse_retry_seconds(e)
            print(f"Rate limit — {wait} saniye bekleniyor ({wait//60} dakika)...")
            time.sleep(wait)
        except Exception as e:
            print(f"Hata: {e} — 30 saniye sonra tekrar deneniyor...")
            time.sleep(30)


def backup_epub(epub_path, book_slug):
    """Save a copy of the original epub for later use by convert.py."""
    backup_dir = "input/.originals"
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = f"{backup_dir}/{book_slug}.epub"
    shutil.copy2(epub_path, backup_path)
    print(f"Orijinal epub yedeklendi: {backup_path}")
    return backup_path


def main():
    client = Groq(api_key=GROQ_API_KEY)

    input_files = [f for f in os.listdir("input") if f.endswith(".epub")]
    if not input_files:
        print("input/ klasöründe epub bulunamadı.")
        return

    epub_file = input_files[0]
    epub_path = f"input/{epub_file}"
    book_slug = re.sub(r"[^\w\-]", "_", epub_file.replace(".epub", ""))

    print(f"Kitap: {epub_file}")

    chapters = extract_chapters(epub_path)
    total = len(chapters)
    print(f"Toplam bölüm: {total}")

    output_dir = f"output/{book_slug}"
    os.makedirs(output_dir, exist_ok=True)
    completed_start = len([f for f in os.listdir(output_dir) if f.endswith(".txt")]) if os.path.exists(output_dir) else 0
    if completed_start > 0:
        print(f"Kaldığı yerden devam: {completed_start}/{total}")

    # Backup the original epub before anything else so convert.py can use images later
    backup_epub(epub_path, book_slug)

    status = {
        "status": "running",
        "book": book_slug,
        "epub_file": epub_file,
        "total": total,
        "completed": completed_start,
        "current_chapter": "",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_status(status)

    for i, chapter in enumerate(chapters):
        out_path = f"{output_dir}/{i+1:03d}_{book_slug}.txt"
        if os.path.exists(out_path):
            print(f"[{i+1}/{total}] Atlanıyor (zaten mevcut): {chapter['title']}")
            continue

        print(f"[{i+1}/{total}] {chapter['title']}")
        status["current_chapter"] = chapter["title"]
        write_status(status)

        chunks = chunk_text(chapter["text"])
        translated_parts = []

        for j, chunk in enumerate(chunks):
            translated = translate_chunk(client, chunk, chapter["title"], j, len(chunks))
            translated_parts.append(translated)
            time.sleep(2)

        full_translation = "\n\n".join(translated_parts)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# {chapter['title']}\n\n{full_translation}\n")

        status["completed"] = i + 1
        subprocess.run(["git", "add", out_path])
        write_status(status)

    os.remove(epub_path)
    subprocess.run(["git", "rm", epub_path], check=True)

    status["status"] = "completed"
    status["current_chapter"] = ""
    write_status(status)

    print("Çeviri tamamlandı.")


if __name__ == "__main__":
    main()
