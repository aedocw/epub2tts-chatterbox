import os
import sys
# Automatically enable MPS fallback on Apple Silicon macOS
# But prob not, see https://github.com/resemble-ai/chatterbox/blob/master/example_for_mac.py
if sys.platform == 'darwin':
    os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
import argparse
import contextlib
import io
import re
import subprocess
import time
import torch
import warnings
import torchaudio as ta
from tqdm import tqdm
from chatterbox.tts import ChatterboxTTS

from ebooklib import epub
from mutagen import mp4
import nltk
from nltk.tokenize import sent_tokenize
from pydub import AudioSegment

# Import EPUB export functions from the reusable library module
from epub2tts_chatterbox.epub_export import export

warnings.filterwarnings("ignore")

warnings.filterwarnings("ignore", module="ebooklib.epub")

def ensure_punkt():
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab")

def conditional_sentence_case(sent):
    # Split the sentence into words
    words = sent.split()
    length = len(words)
    # Iterate through words to check for three consecutive uppercase words
    for i in range(length - 2):
        if words[i].isupper() and words[i+1].isupper() and words[i+2].isupper():
            # Convert the entire sentence to lowercase and capitalize the first letter
            sent = ' '.join(words).lower().capitalize()
            break  # No need to continue checking once a match is found
    return sent

def format_time_adaptive(seconds):
    """Format time in adaptive format, showing only relevant units."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def get_book(sourcefile):
    book_contents = []
    book_title = sourcefile
    book_author = "Unknown"
    chapter_titles = []

    with open(sourcefile, "r", encoding="utf-8") as file:
        current_chapter = {"title": "blank", "paragraphs": []}
        initialized_first_chapter = False
        lines_skipped = 0
        for line in file:

            if lines_skipped < 2 and (line.startswith("Title") or line.startswith("Author")):
                lines_skipped += 1
                if line.startswith('Title: '):
                    book_title = line.replace('Title: ', '').strip()
                elif line.startswith('Author: '):
                    book_author = line.replace('Author: ', '').strip()
                continue

            line = line.strip()
            if line.startswith("#"):
                if current_chapter["paragraphs"] or not initialized_first_chapter:
                    if initialized_first_chapter:
                        book_contents.append(current_chapter)
                    current_chapter = {"title": None, "paragraphs": []}
                    initialized_first_chapter = True
                chapter_title = line[1:].strip()
                if any(c.isalnum() for c in chapter_title):
                    current_chapter["title"] = chapter_title
                    chapter_titles.append(current_chapter["title"])
                else:
                    current_chapter["title"] = "blank"
                    chapter_titles.append("blank")
            elif line:
                if not initialized_first_chapter:
                    chapter_titles.append("blank")
                    initialized_first_chapter = True
                if any(char.isalnum() for char in line):
                    sentences = sent_tokenize(line)
                    cleaned_sentences = [s for s in sentences if any(char.isalnum() for char in s)]
                    line = ' '.join(cleaned_sentences)
                    current_chapter["paragraphs"].append(line)

        # Append the last chapter if it contains any paragraphs.
        if current_chapter["paragraphs"]:
            book_contents.append(current_chapter)

    return book_contents, book_title, book_author, chapter_titles

def sort_key(s):
    # extract number from the string
    return int(re.findall(r'\d+', s)[0])

def check_for_file(filename):
    if os.path.isfile(filename):
        print(f"The file '{filename}' already exists.")
        overwrite = input("Do you want to overwrite the file? (y/n): ")
        if overwrite.lower() != 'y':
            print("Exiting without overwriting the file.")
            sys.exit()
        else:
            os.remove(filename)

def append_silence(tempfile, duration=1200):
    # if temppfile does not exist, return
    if not os.path.isfile(tempfile):
        print(f"File {tempfile} does not exist, skipping silence append.")
        return
    audio = AudioSegment.from_file(tempfile)
    # Create a silence segment
    silence = AudioSegment.silent(duration)
    # Append the silence segment to the audio
    combined = audio + silence
    # Save the combined audio back to file
    combined.export(tempfile, format="flac")

def move_model_to_device(model, device):
    """
    Move a ChatterboxTTS model between devices.

    ChatterboxTTS is not an nn.Module - it is a container holding three
    submodules plus a device string that generate() uses to place its inputs -
    so each piece has to be moved by hand.
    """
    model.t3.to(device)
    model.s3gen.to(device)
    model.ve.to(device)
    if model.conds is not None:
        model.conds.to(device)
    model.device = device
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return model


def wait_for_priority_process(model=None, script_path="/home/doc/repos/call-handling/check_missing_calls.py"):
    """
    Pause generation while the call transcription script is running.

    The GPU is shared with that script and it needs several GB to transcribe,
    so simply idling here is not enough - this process would keep its weights
    resident and starve it. While waiting, the model is parked on the CPU and
    its VRAM handed back, then restored once the priority process is done.
    """
    original_device = None
    try:
        while True:
            result = subprocess.run(["pgrep", "-f", script_path], capture_output=True)
            if result.returncode != 0:
                break

            if model is not None and original_device is None:
                original_device = model.device
                try:
                    print("Priority process detected, moving model to CPU to free GPU memory...")
                    move_model_to_device(model, "cpu")
                except Exception as e:
                    print(f"Could not move model to CPU: {e}")
                    original_device = None

            print(f"Waiting for priority process ({script_path}) to finish...")
            time.sleep(30)
    finally:
        if original_device is not None:
            print(f"Priority process finished, moving model back to {original_device}...")
            move_model_to_device(model, original_device)


def chatterbox_read(sentences, sample, filenames, model, exaggeration, cfg_weight, progress_bar=None):
    for i, sent in enumerate(sentences):
        wait_for_priority_process(model)
        clean_sent = conditional_sentence_case(sent.strip())
        max_attempts = 3
        # This "try 3 times" loop is probably not needed, actual failure was from a torch recursive error that was fixed
        for attempt in range(1, max_attempts + 1):
            try:
                # Suppress Chatterbox's internal per-sentence tqdm sampling bars
                with contextlib.redirect_stderr(io.StringIO()):
                    if sample == "none":
                        wav = model.generate(clean_sent)
                    else:
                        wav = model.generate(clean_sent, audio_prompt_path=sample, exaggeration=exaggeration, cfg_weight=cfg_weight)

                ta.save(filenames[i], wav, model.sr)
                # confirm the file was created
                if not os.path.isfile(filenames[i]):
                    raise FileNotFoundError(f"File {filenames[i]} was not created.")
                break  # Success, exit retry loop

            except Exception as e:
                if attempt < max_attempts:
                    print(f"Attempt {attempt} failed for sentence '{clean_sent}': {e} -- Retrying...")
                else:
                    print(f"Failed to process sentence '{clean_sent}' after {max_attempts} attempts. Error: {e}")

        if progress_bar is not None:
            progress_bar.update(1)

def combine_short_paragraphs(paragraphs, min_words=6):
    """
    Combine paragraphs that consist of a single sentence <min_words with next paragraph.
    """
    if not paragraphs:
        return []

    result = []
    i = 0

    while i < len(paragraphs):
        paragraph = paragraphs[i]

        # Check if this is a single short sentence
        sentences = sent_tokenize(paragraph)
        if len(sentences) == 1 and len(paragraph.split()) < min_words:
            # Combine with next paragraph if available
            if i + 1 < len(paragraphs):
                combined = paragraph + " " + paragraphs[i + 1]
                result.append(combined)
                i += 2  # Skip next paragraph
            else:
                # Last paragraph, just add it (will be merged later in sentence processing)
                result.append(paragraph)
                i += 1
        else:
            result.append(paragraph)
            i += 1

    return result

def combine_short_sentences(sentences, min_words=6, keep_threshold=8):
    """
    Combine short sentences within a paragraph.
    - Sentences with ≥keep_threshold words are left alone
    - Shorter sentences are combined to reach min_words
    """
    if not sentences:
        return []

    result = []
    current_chunk = ""

    for i, sentence in enumerate(sentences):
        word_count = len(sentence.split())

        # If we have no current chunk, start one
        if not current_chunk:
            current_chunk = sentence
            # If this sentence is long enough and it's not the last, emit it
            if word_count >= keep_threshold and i < len(sentences) - 1:
                result.append(current_chunk)
                current_chunk = ""
        else:
            # Add to current chunk
            current_chunk += " " + sentence

        # Check if current chunk is ready to emit
        chunk_words = len(current_chunk.split())
        if chunk_words >= keep_threshold or (chunk_words >= min_words and i < len(sentences) - 1):
            result.append(current_chunk)
            current_chunk = ""

    # Handle remaining chunk
    if current_chunk:
        if result and len(current_chunk.split()) < min_words:
            # Merge with previous
            result[-1] += " " + current_chunk
        else:
            result.append(current_chunk)

    return result

def read_book(book_contents, sample, notitles, exaggeration, cfg_weight):
    # Automatically detect the best available device
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"Attempting to use device: {device}")
    model = ChatterboxTTS.from_pretrained(device=device)

    # Initialize timing and progress tracking
    start_time = time.time()
    total_chars = sum(len(''.join(chapter['paragraphs'])) for chapter in book_contents)
    processed_chars = 0

    segments = []
    for i, chapter in enumerate(book_contents, start=1):
        paragraphpause = 600  # default pause between paragraphs in ms
        files = []
        partname = f"part{i}.flac"
        print("\n\n")

        if os.path.isfile(partname):
            print(f"{partname} exists, skipping to next chapter")
            segments.append(partname)
            # Track characters even for skipped chapters
            processed_chars += len(''.join(chapter['paragraphs']))
        else:
            # Calculate timing info before processing this chapter
            elapsed_time = time.time() - start_time
            elapsed_str = format_time_adaptive(elapsed_time)

            # Calculate ETA based on text processed
            if processed_chars > 0:
                time_per_char = elapsed_time / processed_chars
                remaining_chars = total_chars - processed_chars
                eta_seconds = remaining_chars * time_per_char
                eta_str = format_time_adaptive(eta_seconds)
                timing_info = f" | Elapsed: {elapsed_str} | ETA: {eta_str}"
            else:
                timing_info = f" | Elapsed: {elapsed_str}"

            print(f"Chapter ({i}/{len(book_contents)}): {chapter['title']}{timing_info}\n")
            if chapter["title"] == "":
                chapter["title"] = "blank"
            if chapter["title"] != "Title" and notitles != True:
                chapter['paragraphs'][0] = chapter['title'] + ". " + chapter['paragraphs'][0]

            # Combine short paragraphs first
            combined_paragraphs = combine_short_paragraphs(chapter["paragraphs"])

            # Pre-calculate sentences per paragraph for accurate progress tracking
            paragraph_sentences = [
                combine_short_sentences(sent_tokenize(p))
                for p in combined_paragraphs
            ]
            total_sentences = sum(len(s) for s in paragraph_sentences)

            with tqdm(total=total_sentences, desc=f"  {chapter['title'][:50]}", unit="sent", leave=True) as pbar:
                for pindex, (paragraph, sentences) in enumerate(zip(combined_paragraphs, paragraph_sentences)):
                    ptemp = f"pgraphs{pindex}.flac"
                    if os.path.isfile(ptemp):
                        pbar.update(len(sentences))  # advance past already-done paragraph
                    else:
                        filenames = [
                            "sntnc" + str(z) + ".wav" for z in range(len(sentences))
                        ]
                        chatterbox_read(sentences, sample, filenames, model, exaggeration, cfg_weight, pbar)
                        append_silence(filenames[-1], paragraphpause)
                        # combine sentences in paragraph
                        sorted_files = sorted(filenames, key=sort_key)
                        combined = AudioSegment.empty()
                        for file in sorted_files:
                            # try/except prob not needed, actual failure was from a torch recursive error that was fixed
                            try:
                                combined += AudioSegment.from_file(file)
                            except Exception as e:
                                print("FAILURE at sorted file combine")
                                print(f"File: {file}")
                                print(f"sorted files: {sorted_files}")
                                print(f"Unsorted: {filenames}")
                                sys.exit()
                        combined.export(ptemp, format="flac")
                        for file in sorted_files:
                            os.remove(file)
                    files.append(ptemp)
            # combine paragraphs into chapter
            append_silence(files[-1], 2000)
            combined = AudioSegment.empty()
            for file in files:
                combined += AudioSegment.from_file(file)
            combined.export(partname, format="flac")
            for file in files:
                os.remove(file)
            segments.append(partname)
            # Track processed characters for this chapter
            processed_chars += len(''.join(chapter['paragraphs']))
    return segments

def generate_metadata(files, author, title, chapter_titles):
    chap = 0
    start_time = 0
    with open("FFMETADATAFILE", "w") as file:
        file.write(";FFMETADATA1\n")
        file.write(f"ARTIST={author}\n")
        file.write(f"ALBUM={title}\n")
        file.write(f"TITLE={title}\n")
        file.write("DESCRIPTION=Made with https://github.com/aedocw/epub2tts-chatterbox\n")
        for file_name in files:
            duration = get_duration(file_name)
            file.write("[CHAPTER]\n")
            file.write("TIMEBASE=1/1000\n")
            file.write(f"START={start_time}\n")
            file.write(f"END={start_time + duration}\n")
            file.write(f"title={chapter_titles[chap]}\n")
            chap += 1
            start_time += duration

def get_duration(file_path):
    audio = AudioSegment.from_file(file_path)
    duration_milliseconds = len(audio)
    return duration_milliseconds

def make_m4b(files, sourcefile, speaker):
    filelist = "filelist.txt"
    speaker_file = os.path.basename(speaker)
    basefile = sourcefile.replace(".txt", "")
    outputm4a = f"{basefile}.m4a"
    speaker_name = os.path.splitext(speaker_file)[0]
    outputm4b = f"{basefile} ({speaker_name}).m4b"
    with open(filelist, "w") as f:
        for filename in files:
            filename = filename.replace("'", "'\\''")
            f.write(f"file '{filename}'\n")
    ffmpeg_command = [
        "ffmpeg",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        filelist,
        "-codec:a",
        "flac",
        "-f",
        "mp4",
        "-strict",
        "-2",
        outputm4a,
    ]
    subprocess.run(ffmpeg_command)
    ffmpeg_command = [
        "ffmpeg",
        "-i",
        outputm4a,
        "-i",
        "FFMETADATAFILE",
        "-map_metadata",
        "1",
        "-codec",
        "aac",
        outputm4b,
    ]
    subprocess.run(ffmpeg_command)
    os.remove(filelist)
    os.remove("FFMETADATAFILE")
    os.remove(outputm4a)
    for f in files:
        os.remove(f)
    return outputm4b

def add_cover(cover_img, filename):
    if not cover_img:
        return
    try:
        if os.path.isfile(cover_img):
            m4b = mp4.MP4(filename)
            with open(cover_img, "rb") as f:
                cover_image = f.read()
            m4b["covr"] = [mp4.MP4Cover(cover_image)]
            m4b.save()
        else:
            print(f"Cover image {cover_img} not found")
    except Exception as e:
        print(f"Failed to add cover image {cover_img}: {e}")

def validate_text_file(sourcefile, book_title, book_author, book_contents):
    """
    Validate that the text file contains required elements: title, author, and at least one chapter break.

    Args:
        sourcefile: Path to the source file
        book_title: Extracted book title
        book_author: Extracted book author
        book_contents: List of chapter dictionaries

    Raises:
        SystemExit: If validation fails
    """
    errors = []

    # Check if title was found (if it's still the filename, no title was extracted)
    if book_title == sourcefile:
        errors.append("- Missing 'Title:' line at the beginning of the file")

    # Check if author was found
    if book_author == "Unknown":
        errors.append("- Missing 'Author:' line at the beginning of the file")

    # Check if at least one chapter break was found
    # We need to verify the file has at least one line starting with #
    has_chapter_break = False
    with open(sourcefile, "r", encoding="utf-8") as file:
        for line in file:
            if line.strip().startswith("#"):
                has_chapter_break = True
                break

    if not has_chapter_break:
        errors.append("- Missing at least one chapter break line starting with '#'")

    # If there are any errors, display them and exit
    if errors:
        print("\n" + "="*70)
        print("ERROR: Text file validation failed")
        print("="*70)
        print("\nThe text file must contain the following elements:\n")
        print("1. A 'Title:' line at the beginning (e.g., 'Title: My Book')")
        print("2. An 'Author:' line at the beginning (e.g., 'Author: John Doe')")
        print("3. At least one chapter break line starting with '#' (e.g., '# Chapter 1')")
        print("\nMissing elements:")
        for error in errors:
            print(error)
        print("\nPlease correct the text file format and try again.")
        print("="*70 + "\n")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        prog="epub2tts-chatterbox",
        description="Read a text file to audiobook format",
    )
    parser.add_argument("sourcefile", type=str, help="The epub or text file to process")
    parser.add_argument(
        "--sample",
        type=str,
        help="Sample wav file to use for voice cloning",
    )
    parser.add_argument(
        "--cover",
        type=str,
        help="jpg image to use for cover",
    )
    parser.add_argument(
        "--notitles",
        action="store_true",
        help="Do not read chapter titles"
    )
    parser.add_argument(
        "--exaggeration",
        type=float,
        default=0.7,
        help="Exaggeration factor for voice cloning (default: 0.7)",
    )
    parser.add_argument(
        "--cfg_weight",
        type=float,
        default=0.4,
        help="CFG weight for voice cloning (default: 0.4)",
    )
    parser.add_argument(
        "--naming",
        type=str,
        choices=['auto', 'toc', 'heading', 'class', 'fallback'],
        default=None,
        help="Chapter naming method: auto (default, shows preview), toc, heading, class, or fallback",
    )

    args = parser.parse_args()
    print(args)

    ensure_punkt()

    #If we get an epub, export that to txt file, then exit
    if args.sourcefile.endswith(".epub"):
        book = epub.read_epub(args.sourcefile)
        export(book, args.sourcefile, naming_method=args.naming)
        sys.exit()

    book_contents, book_title, book_author, chapter_titles = get_book(args.sourcefile)

    # Validate the text file before proceeding
    validate_text_file(args.sourcefile, book_title, book_author, book_contents)
    if args.sample is not None:
        sample = args.sample
    else:
        sample = "none"
    files = read_book(book_contents, sample, args.notitles, args.exaggeration, args.cfg_weight)
    generate_metadata(files, book_author, book_title, chapter_titles)
    m4bfilename = make_m4b(files, args.sourcefile, sample)
    add_cover(args.cover, m4bfilename)
    
if __name__ == "__main__":
    main()
