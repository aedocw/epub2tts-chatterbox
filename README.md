> epub2tts-chatterbox is a free and open source python app to easily create a full-featured audiobook from an epub or text file using realistic voice-cloning text-to-speech by [Chatterbox](https://github.com/resemble-ai/chatterbox). CUDA compatible GPU is required, or Apple silicone.

## 🚀 Features

- [x] Creates standard format M4B audiobook file
- [x] Automatic chapter break detection
- [x] Embeds cover art if specified
- [x] Resumes where it left off if interrupted
- [x] NOTE: epub file must be DRM-free

## 📖 Usage

<details>
<summary> Usage instructions</summary>

_NOTE:_ If you want to specify where NLTK tokenizer will be stored (about 50mb), use an environment variable: `export NLTK_DATA="your/path/to/nltk_data"`

## OPTIONAL - activate the virutal environment if using

1. `source .venv/bin/activate`

## FIRST - extract epub contents to text and cover image to png:

1. `epub2tts-chatterbox mybook.epub`
2. **edit mybook.txt**, replacing `# Part 1` etc with desired chapter names, and removing front matter like table of contents and anything else you do not want read. **Note:** First two lines can be Title: and Author: to use that in audiobook metadata.

## Read text to audiobook:

- `epub2tts-chatterbox mybook.txt --cover mybook.png --sample <speaker sample>`
- Specify a speaking sample with `--sample <speaker>`. Ideally your speaking sample should be 30-60 seconds long and can be WAV or MP3 (or a few other formats I don't recall). Sample should be clean audio, no background music or sounds.

## All options

- `-h, --help` - show this help message and exit
- `--sample SampleAudioFile` - Speaker sample to use (example: george.wav)
- `--cover image.[jpg|png]` - Image to use for cover
- `--notitles` - Do not read chapter titles when creating audiobook

## Deactivate virtual environment

`deactivate`

</details>

## 🐞 Reporting bugs

<details>
<summary>How to report bugs/issues</summary>

Thank you in advance for reporting any bugs/issues you encounter! If you are having issues, first please [search existing issues](https://github.com/aedocw/epub2tts-chatterbox/issues) to see if anyone else has run into something similar previously.

If you've found something new, please open an issue and be sure to include:

1. The full command you executed
2. The platform (Linux, Windows, OSX, Docker)
3. Your Python version if not using Docker

</details>

## 🗒️ Release notes

<details>
<summary>Release notes </summary>

- 20250224: Changed to read individual setences rather than entire paragraph, for reading speed consistency
- 20250221: Added `--notitles` option
- 20250216: Initial release

</details>

## 📦 Install

Required Python version is 3.11.

_NOTE:_ If you want to specify where NLTK tokenizer will be stored (about 50mb), use an environment variable: `export NLTK_DATA="your/path/to/nltk_data"`

<details>
<summary>MAC INSTALLATION</summary>

This installation requires Python < 3.12 and [Homebrew](https://brew.sh/) (I use homebrew to install espeak, [pyenv](https://stackoverflow.com/questions/36968425/how-can-i-install-multiple-versions-of-python-on-latest-os-x-and-use-them-in-par) and ffmpeg).

```
#install dependencies
brew install mecab espeak pyenv ffmpeg
#install epub2tts-chatterbox
git clone https://github.com/aedocw/epub2tts-chatterbox
cd epub2tts-chatterbox
pyenv install 3.11
pyenv local 3.11
#OPTIONAL - install this in a virtual environment
python -m venv .venv && source .venv/bin/activate
pip install .
```

</details>

<details>
<summary>LINUX INSTALLATION</summary>

These instructions are for Ubuntu 24.04.1 LTS and 22.04 (20.04 showed some depedency issues), but should work (with appropriate package installer mods) for just about any distro. Ensure you have `ffmpeg` installed before use.

```
#install dependencies
sudo apt install espeak-ng ffmpeg python3-venv
#clone the repo
git clone https://github.com/aedocw/epub2tts-chatterbox
cd epub2tts-chatterbox
#OPTIONAL - install this in a virtual environment
python3 -m venv .venv && source .venv/bin/activate
pip install .
```

</details>

<details>
<summary>WINDOWS INSTALLATION</summary>

Running epub2tts in WSL2 with Ubuntu 22 is the easiest approach, but these steps should work for running directly in windows.

(TBD)

</details>

<details>
<summary>DOCKER RUN</summary>

Running epub2tts with Docker using `pytorch/pytorch` image makes it so you do not need to install anything beyond Docker in your base Windows environment.

Eventually chatterbox could create an image for ease of use on GCR. For now you must build it yourself. (TBD)

To get started:

1. Start the Docker Engine (Docker desktop/etc) or ensure it is running
2. run `docker compose build --no-cache` to build the [Dockerfile](/Dockerfile) image
3. Run the `epub2tts_chatterbox` script initially to create an input `.txt` file with all the labels/inputs for the voice conversion
   1. `docker compose run --rm epub2tts my_epub_name.epub`
4. Make any edits to the output `<epubname>.txt` you wish to have for your final output (titles/etc)
5. Run the tts conversion script specifying the `.txt` file as the input, and a `sample.wave` for your voice sampling with:
   1. `docker compose run --rm epub2tts phoenix_project.txt --sample sample.wav`
   2. This can take a very long time depending on your GPU

</details>

## Scripts

<details>
<summary>Flac2Mp3</summary>

If you have a collection of .flac files that you wish to combine for a single input file into the `--sample` argument a utility script is provided.

To get started:

1. Place all `.flac` files in [/scripts/input_flac](/scripts/input_flac/)
2. Navigate to the scripts directory with `cd scripts` from the project home
3. Run the conversion script with `python flac2mp3.py`
4. Checkout your stitched together `.wav` file in VLC Media Player (or similar) plays as intended
5. Move the output `sample.wav` to the docker volume directory or where you wish to reference it from

</details>

## Updating

<details>
<summary>UPDATING YOUR INSTALLATION</summary>

1. cd to repo directory
2. `git pull`
3. Activate virtual environment you installed epub2tts in if you installed in a virtual environment using "source .venv/bin/activate"
4. `pip install . --upgrade`
</details>

## Author

👤 **Christopher Aedo**

- Website: [aedo.dev](https://aedo.dev)
- GitHub: [@aedocw](https://github.com/aedocw)
- LinkedIn: [@aedo](https://linkedin.com/in/aedo)

👥 **Contributors**

[![Contributors](https://contrib.rocks/image?repo=aedocw/epub2tts-chatterbox)](https://github.com/aedocw/epub2tts-chatterbox/graphs/contributors)

## 🤝 Contributing

Contributions, issues and feature requests are welcome!\
Feel free to check the [issues page](https://github.com/aedocw/epub2tts-chatterbox/issues) or [discussions page](https://github.com/aedocw/epub2tts-chatterbox/discussions).

## Show your support

Give a ⭐️ if this project helped you!
