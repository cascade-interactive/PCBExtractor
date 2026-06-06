# PCB Layer Extractor

![Python](https://img.shields.io/badge/Python-3.13-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

I made this because I wanted an easy way to take Gerber files from a PCB project and turn the useful layers into one packed mask image for PCB render textures.

The app lets you import soldermask, paste, silkscreen/legend, and signal Gerbers, preview them together, and export a single RGBA PNG. Each mask can go into `R`, `G`, `B`, or `A`, so it is easier to plug into a material setup without manually lining everything up in an image editor.

## Setup

Install the Python deps:

```powershell
python -m pip install -r requirements.txt
```

Run it:

```powershell
python app.py
```

## Basic Use

Import the Gerber layers you care about, check the preview, invert any mask if the polarity is backwards, then export the packed PNG.

There is also a Preferences window under `Edit` where you can change dark mode and which layer goes into which RGBA channel by default. Preferences save under your user profile so they load again next time.
