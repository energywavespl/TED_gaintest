# TED_gaintest

A desktop application for antenna/instrument gain testing and measurement automation.

## Overview

TED_gaintest is a Python-based application that integrates instrument control, configuration loaders, a simple UI, and a local database to perform and record gain tests and related measurements. It includes drivers for supported instruments and provides configuration management for antenna and software settings.

## Key Features

- Instrument control modules (e.g., Anritsu MA24510A, Vaunix LMS163)
- Configurable antenna and software loaders
- User management and encrypted user file (`users.enc`)
- Local database for storing measurements and metadata
- GUI front-end for test orchestration and result viewing

## Requirements

- Python 3.8+ (use a virtual environment)
- Install dependencies from `requirements.txt`

## Quick Install (Windows)

Open PowerShell and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

You can also run `Start_Installation.bat` to perform common setup steps.

## Run

From the project root (after activating the virtualenv):

```powershell
python main_app_V1.8.py
```

## Configuration

- General configuration files are located in the `config/` directory.
- Antenna configuration files live in `config/antenna_config_files/`.
- UI assets and app data are under `assets/` and `src/ui/assets/`.

If your instruments require specific drivers or communication settings, configure them in the corresponding files under `src/instruments/` and the `config/` folder.

## Project Structure (high level)

- `main_app_V1.8.py` — application entry point
- `requirements.txt` — Python dependencies
- `config/` — runtime and antenna configuration files
- `assets/` — icons and app assets
- `src/` — source code
  - `src/instruments/` — instrument drivers
  - `src/loaders/` — configuration loaders
  - `src/ui/` — UI and user management
  - `src/database/` — database handling

## Contributing

Contributions are welcome. Please open an issue or submit a pull request with a clear description of changes and any testing notes.


## Contact

For questions or help, open an issue in the repository.
