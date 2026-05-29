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
        # Extract title from first line if starts with #
        lines = content.split("\n", 2)
        title = lines[0].lstrip("#").strip() if lines[0].startswith("#") else fname
        body = lines[2].strip() if len(lines) > 2 else content
        chapters.append({"filename": fname, "title": title, "body": body})
    return chapters


def text_to_xhtml(title, body):
    """Convert plain text body to XHTML content."""
    paragraphs = []
    for para in body.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        # Subheadings (lines starting with ##)
        if para.startswith("## "):
            paragraphs.append(f"<h2>{para[3:].strip()}</h2>")
        elif para.startswith("# "):
            paragraphs.append(f"<h2>{para[2:].strip()}</h2>")
        else:
            # Preserve line breaks within a paragraph
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
    """Try to find the original epub from input/ or a backup location."""
    # The original is deleted after translation, so we store a backup
    backup_path = f"input/.originals/{book_slug}.epub"
    if os.path.exists(backup_path):
        return backup_path
    return None


def extract_images_from_epub(epub_path):
    """Extract all image items from an epub."""
    book = epub.read_epub(epub_path)
    images = {}
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            images[item.get_name()] = item
    return images


def extract_cover_image(epub_path):
    """Try to find the cover image from the original epub."""
    book = epub.read_epub(epub_path)
    # Try metadata cover
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            name_lower = item.get_name().lower()
            if "cover" in name_lower:
                return item
    # Fallback: first image
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            return item
    return None


def build_epub(book_slug, chapters, original_epub_path, output_path):
    """Build a new epub from translated chapters, reusing original images."""
    book = epub.EpubBook()
    book.set_identifier(f"eptran-{book_slug}-tr")
    book.set_title(book_slug.replace("_", " "))
    book.set_language("tr")
    book.add_author("eptran")

    epub_items = []
    images_added = set()

    # Load images from original epub if available
    original_images = {}
    original_book = None
    if original_epub_path and os.path.exists(original_epub_path):
        original_book = epub.read_epub(original_epub_path)
        for item in original_book.get_items():
            if item.get_type() == ebooklib.ITEM_IMAGE:
                original_images[item.get_name()] = item
            if item.get_type() == ebooklib.ITEM_COVER:
                original_images[item.get_name()] = item

        # Add all images from original epub
        for name, item in original_images.items():
            img_item = epub.EpubItem(
                uid=f"img_{name.replace('/', '_').replace('.', '_')}",
                file_name=name,
                media_type=item.media_type,
                content=item.get_content(),
            )
            book.add_item(img_item)
            images_added.add(name)

        # Try to set cover
        cover_item = extract_cover_image(original_epub_path)
        if cover_item:
            book.set_cover(cover_item.get_name(), cover_item.get_content())

    # Add chapters
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

    # Also import image-only pages from original epub (illustration pages)
    if original_book:
        for item in original_book.get_items():
            if item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text().strip()
            imgs = soup.find_all("img")
            # If page has images but minimal text → keep as illustration page
            if imgs and len(text) < 200:
                ill_id = f"illus_{item.get_name().replace('/', '_').replace('.', '_')}"
                # Rewrite img src to use correct relative paths
                ill_item = epub.EpubHtml(
                    title="İllüstrasyon",
                    file_name=f"Text/illus_{ill_id}.xhtml",
                    lang="tr",
                )
                ill_item.set_content(item.get_content())
                book.add_item(ill_item)
                epub_items.append(ill_item)

    # Default CSS
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
