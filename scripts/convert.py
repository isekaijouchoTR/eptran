import os
import re
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup


STATUS_FILE = "status.json"


def git_push(message):
    subprocess.run(["git", "add", "-A"], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode != 0:
        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)


def read_status():
    if not os.path.exists(STATUS_FILE):
        return {}
    with open(STATUS_FILE, encoding="utf-8") as f:
        return json.load(f)


def write_status(data):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    git_push(f"convert: {data.get('convert_status', '')}")


def load_txt_chapters(output_dir):
    """Load translated txt files in order."""
    txt_files = sorted(
        [f for f in os.listdir(output_dir) if f.endswith(".txt")]
    )
    chapters = []
    for fname in txt_files:
        path = os.path.join(output_dir, fname)
        with open(path, encoding="utf-8") as f:
            content = f.read()

        # İlk satır # ile başlıyorsa başlık olarak al, body geri kalan
        lines = content.split("\n", 2)
        if lines[0].startswith("#"):
            raw_title = lines[0].lstrip("#").strip()
            body_raw = lines[2].strip() if len(lines) > 2 else ""
        else:
            raw_title = fname
            body_raw = content.strip()

        # Body'nin ilk satırı başlığın çevirisi ise (tekrar eden başlık), atla
        body_lines = body_raw.split("\n", 1)
        first_line = body_lines[0].strip()

        # Eğer ilk satır başlığa çok benziyorsa (aynı veya çok kısa fark) atla
        def normalize(s):
            return re.sub(r'\W+', '', s.lower())

        if normalize(first_line) and normalize(first_line) == normalize(raw_title):
            # Tekrar eden başlığı atla
            body_raw = body_lines[1].strip() if len(body_lines) > 1 else ""
        elif normalize(first_line) and len(first_line) < 120 and not first_line.endswith((".", "!", "?", "…")):
            # İlk satır kısa ve noktalama ile bitmiyor → muhtemelen başlık çevirisi
            # Bunu gerçek başlık olarak kullan, orijinal İngilizce başlığı geç
            raw_title = first_line
            body_raw = body_lines[1].strip() if len(body_lines) > 1 else ""

        chapters.append({"filename": fname, "title": raw_title, "body": body_raw})
    return chapters


def text_to_xhtml(title, body):
    """Convert plain text body to XHTML content."""
    paragraphs = []
    for para in body.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if para.startswith("## "):
            paragraphs.append(f"<h2>{para[3:].strip()}</h2>")
        elif para.startswith("# "):
            paragraphs.append(f"<h2>{para[2:].strip()}</h2>")
        else:
            lines = para.split("\n")
            joined = "<br/>".join(line.strip() for line in lines if line.strip())
            paragraphs.append(f"<p>{joined}</p>")

    body_html = "\n".join(paragraphs)

    return f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="tr">
<head>
  <title>{title}</title>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
</head>
<body>
  <h1>{title}</h1>
  {body_html}
</body>
</html>"""


def find_original_epub(book_slug):
    backup_path = f"input/.originals/{book_slug}.epub"
    if os.path.exists(backup_path):
        return backup_path
    return None


def extract_cover_image(epub_path):
    book = epub.read_epub(epub_path)
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            if "cover" in item.get_name().lower():
                return item
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            return item
    return None


def build_epub(book_slug, chapters, original_epub_path, output_path):
    """Build epub, preserving original item order so images stay in place."""
    book = epub.EpubBook()
    book.set_identifier(f"eptran-{book_slug}-tr")
    book.set_title(book_slug.replace("_", " "))
    book.set_language("tr")
    book.add_author("eptran")

    epub_items = []

    if original_epub_path and os.path.exists(original_epub_path):
        original_book = epub.read_epub(original_epub_path)

        # Tüm görselleri ekle
        for item in original_book.get_items():
            if item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER):
                img_item = epub.EpubItem(
                    uid=f"img_{item.get_name().replace('/', '_').replace('.', '_')}",
                    file_name=item.get_name(),
                    media_type=item.media_type,
                    content=item.get_content(),
                )
                book.add_item(img_item)

        # Kapağı ayarla
        cover_item = extract_cover_image(original_epub_path)
        if cover_item:
            book.set_cover(cover_item.get_name(), cover_item.get_content())

        # Orijinal sırayı koruyarak bölümleri ve illustrasyonları yerleştir
        chapter_index = 0
        for item in original_book.get_items():
            if item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            soup = BeautifulSoup(item.get_content(), "html.parser")
            for tag in soup(["script", "style", "nav"]):
                tag.decompose()
            text = soup.get_text().strip()
            imgs = soup.find_all("img")

            safe_name = item.get_name().replace('/', '_').replace('.', '_')

            if imgs and len(text) < 200:
                # Illustrasyon sayfası → orijinali koru, yerinde bırak
                ill_item = epub.EpubHtml(
                    title="İllüstrasyon",
                    file_name=f"Text/illus_{safe_name}.xhtml",
                    lang="tr",
                )
                ill_item.set_content(item.get_content())
                book.add_item(ill_item)
                epub_items.append(ill_item)

            elif len(text) >= 300 and chapter_index < len(chapters):
                # Metin sayfası → çevrilmiş bölümle değiştir
                ch = chapters[chapter_index]
                chapter_index += 1
                ch_id = f"chapter_{chapter_index:03d}"
                xhtml = text_to_xhtml(ch["title"], ch["body"])
                epub_ch = epub.EpubHtml(
                    title=ch["title"],
                    file_name=f"Text/{ch_id}.xhtml",
                    lang="tr",
                )
                epub_ch.set_content(xhtml.encode("utf-8"))
                book.add_item(epub_ch)
                epub_items.append(epub_ch)

            else:
                # Kısa sayfa (telif, boş vb.) → orijinali koru
                short_item = epub.EpubHtml(
                    title="",
                    file_name=f"Text/short_{safe_name}.xhtml",
                    lang="tr",
                )
                short_item.set_content(item.get_content())
                book.add_item(short_item)
                epub_items.append(short_item)

    else:
        # Orijinal epub yoksa sadece çeviri bölümleri
        print("Orijinal epub bulunamadı — görselsiz epub oluşturulacak.")
        for i, ch in enumerate(chapters):
            ch_id = f"chapter_{i+1:03d}"
            xhtml = text_to_xhtml(ch["title"], ch["body"])
            epub_ch = epub.EpubHtml(
                title=ch["title"],
                file_name=f"Text/{ch_id}.xhtml",
                lang="tr",
            )
            epub_ch.set_content(xhtml.encode("utf-8"))
            book.add_item(epub_ch)
            epub_items.append(epub_ch)

    # CSS
    css = epub.EpubItem(
        uid="style_default",
        file_name="Style/default.css",
        media_type="text/css",
        content=b"""
body { font-family: serif; margin: 5%; text-align: justify; }
h1 { text-align: center; margin: 2em 0 1em; }
h2 { margin: 1.5em 0 0.5em; }
p { margin: 0.5em 0; text-indent: 1.5em; }
img { max-width: 100%; display: block; margin: auto; }
""",
    )
    book.add_item(css)

    book.toc = tuple(
        epub.Link(ch.file_name, ch.title, ch.id) for ch in epub_items
        if not ch.file_name.startswith("Text/illus_")
        and not ch.file_name.startswith("Text/short_")
        and ch.title
    )

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + epub_items

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    epub.write_epub(output_path, book)
    print(f"EPUB oluşturuldu: {output_path}")


def main():
    status = read_status()
    book_slug = status.get("book")

    if not book_slug:
        print("status.json'da book bilgisi yok.")
        return

    output_dir = f"output/{book_slug}"
    if not os.path.exists(output_dir):
        print(f"Çıktı dizini bulunamadı: {output_dir}")
        return

    print(f"Kitap: {book_slug}")

    chapters = load_txt_chapters(output_dir)
    print(f"Bölüm sayısı: {len(chapters)}")

    original_epub_path = find_original_epub(book_slug)
    if original_epub_path:
        print(f"Orijinal epub bulundu: {original_epub_path}")
    else:
        print("Orijinal epub bulunamadı — görselsiz epub oluşturulacak.")

    epub_out = f"output/{book_slug}/{book_slug}_tr.epub"

    status["convert_status"] = "running"
    write_status(status)

    build_epub(book_slug, chapters, original_epub_path, epub_out)

    status["convert_status"] = "completed"
    status["epub_output"] = epub_out
    write_status(status)

    print("Dönüşüm tamamlandı.")


if __name__ == "__main__":
    main()
