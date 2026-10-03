# Installation & Quickstart — RSR ErrorSentinel AI

## 1. System Requirements
- Python 3.10, 3.11, or 3.12
- OS: Windows, Linux, or macOS
- SQLite 3 (or PostgreSQL for production)

---

## 2. Environment Setup

```bash
# Clone or navigate to the repository
cd "E:\ai agent"

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 3. Configuration Setup

Copy the template file to `.env`:

```bash
cp .env.example .env
```

---

## 4. Run Preflight Check

Verify your configuration:

```bash
python main.py --check-config
```

---

## 5. Instant Offline Demo

Run the end-to-end interactive demo without needing any external API credentials:

```bash
python main.py --demo
```

---

## 6. Start the Web Dashboard & API Server

```bash
python main.py
```

Access the dashboard at [http://127.0.0.1:8000](http://127.0.0.1:8000) and API documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
