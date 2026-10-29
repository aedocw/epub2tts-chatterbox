"""
EPUB Export Library

This module provides functions to convert EPUB files to plain text with proper
chapter detection and naming. It can be used standalone or integrated into
any TTS (text-to-speech) project.

Example usage:
    from epub2tts_chatterbox.epub_export import export_epub, export_epub_to_dict

    # Export to text file
    chapters = export_epub('book.epub', 'book.txt', naming_method='auto')

    # Or get chapters as a dictionary (no file written)
    book_data = export_epub_to_dict('book.epub', naming_method='auto')
    for chapter in book_data['chapters']:
        print(f"Chapter: {chapter['title']}")
        print(f"Content: {chapter['text'][:100]}...")
"""

import os
import re
import warnings
import zipfile

from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
from lxml import etree
from PIL import Image

warnings.filterwarnings("ignore", module="ebooklib.epub")

# XML namespaces for EPUB parsing
NAMESPACES = {
    "calibre": "http://calibre.kovidgoyal.net/2009/metadata",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "opf": "http://www.idpf.org/2007/opf",
    "u": "urn:oasis:names:tc:opendocument:xmlns:container",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def build_toc_map(toc):
    """
    Build a mapping from filename to TOC title.

    Args:
        toc: The EPUB's table of contents (book.toc attribute).

    Returns:
        dict: Mapping from filename (without anchor) to chapter title.
    """
    toc_map = {}

    def _process_toc_items(items):
        for item in items:
            if hasattr(item, 'href') and hasattr(item, 'title'):
                # Remove anchor part (e.g., "html/ch01.html#section1" -> "html/ch01.html")
                filename = item.href.split('#')[0]
                toc_map[filename] = item.title
            elif hasattr(item, '__iter__'):
                _process_toc_items(item)

    _process_toc_items(toc)
    return toc_map


def get_chapter_titles_by_method(chap, item_name=None, item_id=None, toc_map=None):
    """
    Get chapter titles using different detection methods.

    Args:
        chap: The chapter content (HTML bytes or string).
        item_name: The filename of the item (for TOC lookup).
        item_id: The ID of the item in the EPUB spine (for fallback naming).
        toc_map: Pre-built mapping from filename to TOC title.

    Returns:
        dict: Mapping from method name to chapter title (or None if not found).
              Keys: 'toc', 'heading', 'class', 'fallback'
    """
    soup = BeautifulSoup(chap, "html.parser")
    titles = {}

    # Method 1: TOC lookup by filename
    if toc_map and item_name:
        titles['toc'] = toc_map.get(item_name)

    # Method 2: Heading tags
    for tag in ['h1', 'h2', 'h3']:
        heading = soup.find(tag)
        if heading and heading.text.strip():
            titles['heading'] = heading.text.strip()
            break
    if 'heading' not in titles:
        titles['heading'] = None

    # Method 3: CSS classes
    for class_name in ['chapter', 'chapter-title', 'title', 'heading', 'chapterhead']:
        element = soup.find(class_=class_name)
        if element and element.text.strip():
            titles['class'] = element.text.strip()
            break
    if 'class' not in titles:
        titles['class'] = None

    # Method 4: Fallback to item ID
    if item_id:
        titles['fallback'] = item_id.replace('.xhtml', '').replace('.html', '').replace('_', ' ').title()
    else:
        titles['fallback'] = None

    return titles


def extract_chapter_content(chap, item_name=None, item_id=None, toc_map=None, naming_method='auto', verbose=True):
    """
    Extract chapter title and paragraphs from an EPUB chapter.

    Args:
        chap: The chapter content (HTML bytes or string).
        item_name: The filename of the item (for TOC lookup).
        item_id: The ID of the item in the EPUB spine (for fallback naming).
        toc_map: Pre-built mapping from filename to TOC title.
        naming_method: Method to use for chapter naming ('auto', 'toc', 'heading', 'class', 'fallback').
        verbose: If True, print status messages.

    Returns:
        tuple: (chapter_title, paragraphs_list)
    """
    soup = BeautifulSoup(chap, "html.parser")

    # Get titles from all methods
    titles = get_chapter_titles_by_method(chap, item_name, item_id, toc_map)

    chapter_title = None

    if naming_method == 'auto':
        # Priority: TOC > heading > class > fallback
        if titles.get('toc'):
            chapter_title = titles['toc']
            if verbose:
                print(f"Found title in TOC: '{chapter_title}'")
        elif titles.get('heading'):
            chapter_title = titles['heading']
            if verbose:
                print(f"Found title in heading tag: '{chapter_title}'")
        elif titles.get('class'):
            chapter_title = titles['class']
            if verbose:
                print(f"Found title in CSS class: '{chapter_title}'")
        else:
            chapter_title = titles.get('fallback')
            if verbose:
                print(f"No title found, using fallback: '{chapter_title}'")
    else:
        # Use the specified method, with fallback if not available
        chapter_title = titles.get(naming_method)
        if chapter_title:
            if verbose:
                print(f"Using {naming_method} title: '{chapter_title}'")
        else:
            chapter_title = titles.get('fallback')
            if verbose:
                print(f"Method '{naming_method}' unavailable, using fallback: '{chapter_title}'")

    # Remove footnotes (links with only numbers)
    for a in soup.findAll("a", href=True):
        if not any(char.isalpha() for char in a.text):
            a.extract()

    # Remove superscript numbers (e.g., footnote markers)
    for sup in soup.findAll("sup"):
        if sup.text.isdigit():
            sup.extract()

    # Extract paragraphs
    paragraphs = []
    chapter_paragraphs = soup.find_all("p")
    if not chapter_paragraphs:
        if verbose:
            print(f"No <p> tags found in '{chapter_title or item_id}'. Trying <div>.")
        chapter_paragraphs = soup.find_all("div")

    for p in chapter_paragraphs:
        paragraph_text = "".join(p.strings).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    return chapter_title, paragraphs


def get_epub_cover(epub_path):
    """
    Extract cover image from an EPUB file.

    Args:
        epub_path: Path to the EPUB file.

    Returns:
        file-like object containing the cover image, or None if not found.
    """
    try:
        with zipfile.ZipFile(epub_path) as z:
            t = etree.fromstring(z.read("META-INF/container.xml"))
            rootfile_path = t.xpath("/u:container/u:rootfiles/u:rootfile",
                                    namespaces=NAMESPACES)[0].get("full-path")

            t = etree.fromstring(z.read(rootfile_path))
            cover_meta = t.xpath("//opf:metadata/opf:meta[@name='cover']",
                                namespaces=NAMESPACES)
            if not cover_meta:
                return None
            cover_id = cover_meta[0].get("content")

            cover_item = t.xpath("//opf:manifest/opf:item[@id='" + cover_id + "']",
                                namespaces=NAMESPACES)
            if not cover_item:
                return None
            cover_href = cover_item[0].get("href")
            cover_path = os.path.join(os.path.dirname(rootfile_path), cover_href)
            if os.name == 'nt' and '\\' in cover_path:
                cover_path = cover_path.replace("\\", "/")
            return z.open(cover_path)
    except (FileNotFoundError, KeyError, IndexError):
        return None


def preview_chapter_names(book, sourcefile=None, max_samples=6):
    """
    Preview chapter names using different naming methods and let user choose interactively.

    Args:
        book: The EPUB book object (from epub.read_epub()).
        sourcefile: Path to the source EPUB file (for display purposes).
        max_samples: Maximum number of sample chapters to show.

    Returns:
        str: The chosen naming method ('auto', 'toc', 'heading', 'class', 'fallback').
    """
    # Get the table of contents and build the map
    toc = getattr(book, 'toc', [])
    toc_map = build_toc_map(toc)

    spine_ids = [spine_tuple[0] for spine_tuple in book.spine if spine_tuple[1] == 'yes']
    items = {item.get_id(): item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT}

    # Collect sample chapters with content
    samples = []
    for spine_id in spine_ids:
        if len(samples) >= max_samples:
            break
        item = items.get(spine_id)
        if item is None:
            continue

        soup = BeautifulSoup(item.get_content(), "html.parser")
        text_content = soup.get_text(strip=True)
        if len(text_content) < 100:  # Skip near-empty pages
            continue

        titles = get_chapter_titles_by_method(
            item.get_content(),
            item_name=item.get_name(),
            item_id=spine_id,
            toc_map=toc_map
        )
        samples.append(titles)

    # Check if all methods produce the same results
    methods = ['toc', 'heading', 'class', 'fallback']
    method_results = {m: [s.get(m) for s in samples] for m in methods}

    # Filter to methods that have at least some results
    available_methods = {m: results for m, results in method_results.items()
                        if any(r is not None for r in results)}

    # Check if methods produce meaningfully different results
    unique_results = set()
    for m, results in available_methods.items():
        unique_results.add(tuple(r for r in results if r is not None))

    if len(unique_results) <= 1:
        # All methods produce the same results, use auto
        print("All naming methods produce similar results. Using automatic selection.")
        return 'auto'

    # Show preview and let user choose
    print("\n" + "=" * 70)
    print("CHAPTER NAMING PREVIEW")
    print("=" * 70)
    print("\nDifferent methods found different chapter names. Here's a comparison:\n")

    # Show table header
    print(f"{'#':<3} {'TOC':<30} {'Heading':<30} {'Fallback':<20}")
    print("-" * 83)

    for i, sample in enumerate(samples, 1):
        toc_name = (sample.get('toc') or '-')[:28]
        heading_name = (sample.get('heading') or '-')[:28]
        fallback_name = (sample.get('fallback') or '-')[:18]
        print(f"{i:<3} {toc_name:<30} {heading_name:<30} {fallback_name:<20}")

    print("\n" + "-" * 83)
    print("\nAvailable naming methods:")
    print("  1. auto    - Automatic (TOC > Heading > Class > Fallback)")
    print("  2. toc     - Use Table of Contents names")
    print("  3. heading - Use HTML heading tags (h1, h2, h3)")
    print("  4. fallback- Use file IDs as chapter names")
    print("  5. skip    - Skip preview, use automatic selection")

    while True:
        try:
            choice = input("\nChoose naming method [1-5, default=1]: ").strip()
        except EOFError:
            return 'auto'
        if choice == '' or choice == '1':
            return 'auto'
        elif choice == '2':
            return 'toc'
        elif choice == '3':
            return 'heading'
        elif choice == '4':
            return 'fallback'
        elif choice == '5':
            return 'auto'
        else:
            print("Invalid choice. Please enter 1-5.")


def clean_text(text):
    """
    Clean text for TTS output.

    Args:
        text: Raw text string.

    Returns:
        Cleaned text string.
    """
    clean = re.sub(r'[\s\n]+', ' ', text)
    clean = re.sub(r'[\u201c\u201d]', '"', clean)  # Curly double quotes to standard
    clean = re.sub(r'[\u2018\u2019]', "'", clean)  # Curly single quotes to standard
    clean = re.sub(r'--', ', ', clean)
    clean = re.sub(r'\u2014', ', ', clean)  # Em dash
    return clean.strip()


def export_epub_to_dict(epub_path, naming_method=None, verbose=True, interactive=True):
    """
    Export EPUB to a dictionary structure (no file written).

    Args:
        epub_path: Path to the EPUB file.
        naming_method: Chapter naming method ('auto', 'toc', 'heading', 'class', 'fallback').
                      If None and interactive=True, shows preview for user to choose.
        verbose: If True, print status messages.
        interactive: If True and naming_method is None, show interactive preview.

    Returns:
        dict: {
            'title': str,
            'author': str,
            'cover_image': PIL.Image or None,
            'chapters': [{'title': str, 'paragraphs': [str], 'text': str}, ...]
        }
    """
    book = epub.read_epub(epub_path)

    # Get metadata
    title_meta = book.get_metadata("DC", "title")
    author_meta = book.get_metadata("DC", "creator")
    title = title_meta[0][0] if title_meta else "Unknown Title"
    author = author_meta[0][0] if author_meta else "Unknown Author"

    # Get cover image
    cover_image = None
    cover_file = get_epub_cover(epub_path)
    if cover_file:
        try:
            cover_image = Image.open(cover_file)
        except Exception:
            pass

    # Build TOC map
    toc = getattr(book, 'toc', [])
    toc_map = build_toc_map(toc)

    # Get naming method
    if naming_method is None and interactive:
        naming_method = preview_chapter_names(book, epub_path)
        if verbose:
            print(f"\nUsing '{naming_method}' naming method.\n")
    elif naming_method is None:
        naming_method = 'auto'

    # Extract chapters
    spine_ids = [spine_tuple[0] for spine_tuple in book.spine if spine_tuple[1] == 'yes']
    items = {item.get_id(): item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT}

    chapters = []
    for spine_id in spine_ids:
        item = items.get(spine_id)
        if item is None:
            continue

        chapter_title, paragraphs = extract_chapter_content(
            item.get_content(),
            item_name=item.get_name(),
            item_id=spine_id,
            toc_map=toc_map,
            naming_method=naming_method,
            verbose=verbose
        )

        if paragraphs and paragraphs != ['']:
            # Clean paragraphs
            cleaned_paragraphs = [clean_text(p) for p in paragraphs if p.strip()]
            chapters.append({
                'title': chapter_title or f"Chapter {len(chapters) + 1}",
                'paragraphs': cleaned_paragraphs,
                'text': '\n\n'.join(cleaned_paragraphs)
            })

    return {
        'title': title,
        'author': author,
        'cover_image': cover_image,
        'chapters': chapters
    }


def export_epub(epub_path, output_path=None, naming_method=None, verbose=True, interactive=True):
    """
    Export EPUB to a text file.

    Args:
        epub_path: Path to the EPUB file.
        output_path: Path for output text file. If None, uses epub_path with .txt extension.
        naming_method: Chapter naming method ('auto', 'toc', 'heading', 'class', 'fallback').
                      If None and interactive=True, shows preview for user to choose.
        verbose: If True, print status messages.
        interactive: If True and naming_method is None, show interactive preview.

    Returns:
        dict: Same as export_epub_to_dict()
    """
    if output_path is None:
        output_path = os.path.splitext(epub_path)[0] + '.txt'

    # Get book data
    book_data = export_epub_to_dict(
        epub_path,
        naming_method=naming_method,
        verbose=verbose,
        interactive=interactive
    )

    # Write to file
    if verbose:
        print(f"Exporting {epub_path} to {output_path}")

    with open(output_path, "w", encoding='utf-8') as file:
        file.write(f"Title: {book_data['title']}\n")
        file.write(f"Author: {book_data['author']}\n\n")
        file.write(f"# Title\n")
        file.write(f"{book_data['title']}, by {book_data['author']}\n\n")

        for chapter in book_data['chapters']:
            file.write(f"# {chapter['title']}\n\n")
            for paragraph in chapter['paragraphs']:
                file.write(f"{paragraph}\n\n")

    # Save cover image if available
    if book_data['cover_image']:
        cover_path = os.path.splitext(epub_path)[0] + '.png'
        book_data['cover_image'].save(cover_path)
        if verbose:
            print(f"Cover image saved to {cover_path}")

    return book_data


# Convenience function for backwards compatibility
def export(book, sourcefile, naming_method=None):
    """
    Legacy export function for backwards compatibility.

    Args:
        book: The EPUB book object (ignored, will re-read from sourcefile).
        sourcefile: Path to the source EPUB file.
        naming_method: Chapter naming method.

    Returns:
        list: List of chapter dictionaries with 'title' and 'paragraphs' keys.
    """
    book_data = export_epub(
        sourcefile,
        naming_method=naming_method,
        verbose=True,
        interactive=(naming_method is None)
    )
    # Return in legacy format
    return [{'title': ch['title'], 'paragraphs': ch['paragraphs']} for ch in book_data['chapters']]
