from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="epub2tts-chatterbox",
    description="Tool to read an epub to audiobook using chatterbox TTS",
    author="Christopher Aedo aedo.dev",
    author_email="c@aedo.dev",
    url="https://github.com/aedocw/epub2tts-chatterbox",
    license="GPL 3.0",
    version="1.1.1",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        'console_scripts': [
            'epub2tts-chatterbox = epub2tts_chatterbox:main'
        ]
    },
)
