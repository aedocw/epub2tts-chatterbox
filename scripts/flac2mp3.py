import subprocess
from pathlib import Path

INPUT_DIR = Path("input_flac")  # Directory containing .flac files
OUTPUT_FILE = Path("sample.wav")  # Your input for epub2tts_chatterbox


def main():
    flacs = sorted(INPUT_DIR.glob("*.flac"))
    if not flacs:
        raise RuntimeError("No .flac files found")

    list_file = Path("flac_list.txt")
    with list_file.open("w", encoding="utf-8") as f:
        for flac in flacs:
            # ffmpeg concat demuxer requires this format
            f.write(f"file '{flac.resolve()}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy" if OUTPUT_FILE.suffix == ".wav" else "libmp3lame",
        str(OUTPUT_FILE),
    ]

    subprocess.run(cmd, check=True)
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
