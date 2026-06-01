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

STATUS_FILE = "status.json"


def get_groq_clients():
    """Mevcut GROQ_API_KEY_* ve GROQ_API_KEY değişkenlerinden client listesi oluştur."""
    clients = []

    # GROQ_API_KEY_1, _2, _3, _4 varsa ekle
    for i in range(1, 5):
        key = os.environ.get(f"GROQ_API_KEY_{i}")
        if key:
            clients.append({"client": Groq(api_key=key), "locked_until": 0, "id": i})
            print(f"Key {i} yüklendi.")

    # Tekli GROQ_API_KEY varsa ve listede yoksa ekle
    single_key = os.environ.get("GROQ_API_KEY")
    if single_key and not clients:
        clients.append({"client": Groq(api_key=single_key), "locked_until": 0, "id": "Default"})
        print("Tekli GROQ_API_KEY yüklendi.")

    if not clients:
        raise ValueError("Hiçbir GROQ_API_KEY bulunamadı. Lütfen çevre değişkenlerini kontrol edin.")

    print(f"Toplam {len(clients)} key aktif.")
    return clients


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

    return int(total) + 5


def translate_chunk(clients, key_index, text, chapter_title, chunk_index, total_chunks):
    """Kilitlenme durumlarını (Rate Limit) akıllıca takip ederek çeviri yapar."""
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
        current_time = time.time()
        
        # Müsait (kilitli olmayan) bir key bulana kadar dön
        available_keys = [c for c in clients if c["locked_until"] <= current_time]
        
        if not available_keys:
            # Eğer tüm keyler kilitliyse, kilidi en erken açılacak olanı bul ve bekle
            min_lock_release = min(c["locked_until"] for c in clients)
            wait_time = max(int(min_lock_release - current_time), 1)
            print(f"Tüm keyler limit dışı. En yakın key için {wait_time} saniye bekleniyor...")
            time.sleep(wait_time)
            continue

        # Sıradaki key_index'i mevcut kullanılabilir keylere eşitlemeye çalış
        # Eğer index dışı kaldıysa veya kilitliyse, müsait ilk keye odaklanıyoruz
        idx = key_index[0] % len(clients)
        if clients[idx]["locked_until"] > current_time:
            # Mevcut seçili olan kilitliyse, kilitli olmayan ilk keyin indexini al
            for i, c in enumerate(clients):
                if c["locked_until"] <= current_time:
                    idx = i
                    key_index[0] = i
                    break

        current_client_info = clients[idx]
        client = current_client_info["client"]
        key_id = current_client_info["id"]

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            # Başarılı çeviriden sonra bir sonraki key indexine geçiş hazırlığı
            key_index[0] = (idx + 1) % len(clients)
            return response.choices[0].message.content

        except RateLimitError as e:
            wait = parse_retry_seconds(e)
            print(f"Key {key_id} rate limit yedi! {wait} saniye kilitlendi. Sonraki key'e geçiliyor...")
            clients[idx]["locked_until"] = time.time() + wait
            key_index[0] = (idx + 1) % len(clients)
            
        except Exception as e:
            print(f"Sistemsel Hata: {e} — 30 saniye sonra tekrar deneniyor...")
            time.sleep(30)


def backup_epub(epub_path, book_slug):
    backup_dir = "input/.originals"
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = f"{backup_dir}/{book_slug}.epub"
    shutil.copy2(epub_path, backup_path)
    print(f"Orijinal epub yedeklendi: {backup_path}")
    return backup_path


def main():
    clients = get_groq_clients()
    key_index = [0]  # Paylaşılan mutable referans

    input_files = [f for f in os.listdir("input") if f.endswith(".epub")]

    if not input_files:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE) as f:
                prev = json.load(f)
            if prev.get("status") == "running":
                print("Status running ama input'ta epub yok. Durduruluyor.")
                return
        print("input/ klasöründe epub bulunamadı, yapılacak iş yok.")
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

        print(f"[{i+1}/{total}] Çevriliyor: {chapter['title']}")
        status["current_chapter"] = chapter["title"]
        write_status(status)

        chunks = chunk_text(chapter["text"])
        translated_parts = []

        for j, chunk in enumerate(chunks):
            translated = translate_chunk(clients, key_index, chunk, chapter["title"], j, len(chunks))
            translated_parts.append(translated)
            time.sleep(2)  # Kısa cooldown CoG limitlerine takılmamak için yararlı

        full_translation = "\n\n".join(translated_parts)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# {chapter['title']}\n\n{full_translation}\n")

        status["completed"] = i + 1
        subprocess.run(["git", "add", out_path])
        write_status(status)

    if os.path.exists(epub_path):
        os.remove(epub_path)
        subprocess.run(["git", "rm", epub_path], check=True)

    status["status"] = "completed"
    status["current_chapter"] = ""
    write_status(status)

    print("Çeviri başarıyla tamamlandı.")


if __name__ == "__main__":
    main()
