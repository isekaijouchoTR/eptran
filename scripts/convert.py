import os
import re
import json
import subprocess
from datetime import datetime, timezone

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from lxml import etree


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


def normalize(s):
    return re.sub(r'\W+', '', s.lower())


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

        lines = content.split("\n", 2)
        if lines[0].startswith("#"):
            raw_title = lines[0].lstrip("#").strip()
            body_raw = lines[2].strip() if len(lines) > 2 else ""
        else:
            raw_title = fname
            body_raw = content.strip()

        body_lines = body_raw.split("\n", 1)
        first_line = body_lines[0].strip()

        if normalize(first_line) and normalize(first_line) == normalize(raw_title):
            body_raw = body_lines[1].strip() if len(body_lines) > 1 else ""
        elif normalize(first_line) and len(first_line) < 120 and not first_line.endswith((".", "!", "?", "…")):
            raw_title = first_line
            body_raw = body_lines[1].strip() if len(body_lines) > 1 else ""

        chapters.append({"filename": fname, "title": raw_title, "body": body_raw})
    return chapters


def text_to_xhtml(title, body):
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
            if "[EPUB_IMAGE:" in para:
                para = re.sub(r'\[EPUB_IMAGE:(.*?)\]', r'<img src="../Images/\1" alt="image" />', para)

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


def get_spine_order(original_book):
    """Spine sırasına göre item listesi döndür."""
    spine_ids = [idref for idref, _ in original_book.spine]
    items_by_id = {item.id: item for item in original_book.get_items()}
    ordered = []
    for sid in spine_ids:
        if sid in items_by_id:
            ordered.append(items_by_id[sid])
    return ordered


def extract_cover_image(original_book):
    for item in original_book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            if "cover" in item.get_name().lower():
                return item
    for item in original_book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            return item
    return None


def build_epub(book_slug, chapters, original_epub_path, output_path):
    book = epub.EpubBook()
    book.set_identifier(f"eptran-{book_slug}-tr")
    book.set_language("tr")
    book.add_author("eptran")

    epub_items = []

    if original_epub_path and os.path.exists(original_epub_path):
        original_book = epub.read_epub(original_epub_path)

        title_meta = original_book.get_metadata('DC', 'title')
        book_title = title_meta[0][0] if title_meta else book_slug.replace("_", " ")
        book.set_title(book_title)

        for item in original_book.get_items():
            if item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER):
                safe_uid = f"img_{re.sub(r'[^a-zA-Z0-9_]', '_', item.get_name())}"
                img_item = epub.EpubItem(
                    uid=safe_uid,
                    file_name=item.get_name(),
                    media_type=item.media_type,
                    content=item.get_content(),
                )
                book.add_item(img_item)

        cover_item = extract_cover_image(original_book)
        if cover_item:
            book.set_cover(cover_item.get_name(), cover_item.get_content())

        spine_items = get_spine_order(original_book)
        chapter_index = 0

        for item in spine_items:
            if item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            soup = BeautifulSoup(item.get_content(), "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text().strip()
            imgs = soup.find_all("img")
            item_name = item.get_name()
            safe_name = item_name.replace('/', '_').replace('.', '_')

            base = os.path.basename(item_name).lower()
            is_insert = base.startswith("insert") or base.startswith("frontmatter") or base.startswith("bonus")
            is_image_page = bool(imgs) and len(text) < 300

            if is_insert or is_image_page:
                ill_item = epub.EpubHtml(
                    title="",
                    file_name=f"Text/orig_{safe_name}.xhtml",
                    lang="tr",
                )
                ill_item.set_content(item.get_content())
                book.add_item(ill_item)
                epub_items.append(ill_item)

            elif len(text) >= 300 and chapter_index < len(chapters):
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
                short_item = epub.EpubHtml(
                    title="",
                    file_name=f"Text/short_{safe_name}.xhtml",
                    lang="tr",
                )
                short_item.set_content(item.get_content())
                book.add_item(short_item)
                epub_items.append(short_item)

        if chapter_index < len(chapters):
            print(f"Uyarı: {len(chapters) - chapter_index} bölüm eşleştirilemedi.")

    else:
        print("Orijinal epub bulunamadı — PDF veya bağımsız metin modunda derleniyor.")
        book.set_title(book_slug.replace("_", " "))
        
        images_dir = f"output/{book_slug}/images"
        if os.path.exists(images_dir):
            for img_name in sorted(os.listdir(images_dir)):
                img_path = os.path.join(images_dir, img_name)
                if os.path.isdir(img_path):
                    continue
                ext = os.path.splitext(img_name)[1].lower()
                
                if ext in ('.jpg', '.jpeg'):
                    m_type = "image/jpeg"
                elif ext == '.png':
                    m_type = "image/png"
                elif ext == '.gif':
                    m_type = "image/gif"
                elif ext == '.webp':
                    m_type = "image/webp"
                else:
                    continue
                    
                with open(img_path, "rb") as f_img:
                    img_content = f_img.read()
                    
                epub_img_item = epub.EpubItem(
                    uid=f"img_{re.sub(r'[^a-zA-Z0-9_]', '_', img_name)}",
                    file_name=f"Images/{img_name}",
                    media_type=m_type,
                    content=img_content
                )
                book.add_item(epub_img_item)
            
            cover_candidates = [f for f in os.listdir(images_dir) if f.startswith("page_1_img_1") or f.startswith("page_2_img_1")]
            if cover_candidates:
                cover_name = sorted(cover_candidates)[0]
                with open(os.path.join(images_dir, cover_name), "rb") as f_img:
                    book.set_cover(f"Images/{cover_name}", f_img.read())

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
        if ch.title and not ch.file_name.startswith("Text/orig_")
        and not ch.file_name.startswith("Text/short_")
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
        print("Orijinal epub bulunamadı — PDF veya bağımsız metin modunda derleniyor.")

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
