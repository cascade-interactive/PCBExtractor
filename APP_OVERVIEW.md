# PCB Layer Extractor App Overview

PCB Layer Extractor is a local Windows desktop utility for importing PCB Gerber layers, previewing their alignment, converting them into masks, and exporting a packed PNG where each image channel stores one PCB layer mask.

## What It Does

The app imports Gerber files for:

- Soldermask
- Paste
- Legend / silkscreen
- Signal

It renders the imported Gerbers as colorless masks, overlays them in a local preview, and exports them as a single RGBA PNG. The preview uses temporary colors only so the user can visually confirm that the layers line up correctly.

## Packed PNG Output

The exported PNG stores masks in image channels. By default:

- `R`: Soldermask
- `G`: Paste
- `B`: Legend / silkscreen
- `A`: Signal

The app also includes a channel changer so each mask can be assigned to a different output channel if needed. This allows the user to choose which PCB mask belongs in `R`, `G`, `B`, or `A` before export.

## Preview And Layer Controls

The local UI lets the user:

- Import each Gerber layer independently.
- Toggle layer visibility on and off.
- Invert each layer mask.
- Preview the overlaid layers before export.
- Reset the project with `File > New`.
- Export the packed PNG to a chosen folder.

Hidden layers are intended for preview control and should not accidentally alter the packed export unless the export settings say otherwise.

## Interface

PCB Layer Extractor uses a local desktop UI with a Windows 11-style Mica appearance. The app follows the system light or dark theme where supported.

Menus include:

- `File`
  - `New`
  - `Exit`
- `Edit`
  - Layer visibility controls
  - Preferences
- `Help`
  - `About`

## Notices

PCB Layer Extractor is provided as-is, without warranty of any kind.

Gerber files can vary by exporter, CAD tool, polarity conventions, units, aperture definitions, and layer naming. The user is responsible for confirming that imported files are assigned to the correct layer type and output channel.

The preview colors are not part of the exported mask data. They are only visual aids for checking alignment.

## Version

Version 1.0.0 (Beta)

Made by Alexander Bugar.

## Packages Used

PCB Layer Extractor uses:

- Python Tkinter for the local desktop UI.
- Gerbonara for Gerber parsing and geometry handling.
- Pillow for image and PNG generation.

## License

MIT License

Copyright (c) 2026 Alexander Bugar

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files, to deal in the software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software, subject to inclusion of the MIT license notice.

The software is provided as-is, without warranty of any kind, express or implied, including but not limited to warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability arising from use of the software.
