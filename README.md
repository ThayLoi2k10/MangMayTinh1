## Setup

### 1. Create a Virtual Environment

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

With the virtual environment activated, run:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Verify Installation

Run the test suite to verify that the environment is configured correctly:

```bash
python -m pytest -q
```

### 4. Deactivate the Virtual Environment

When finished, run:

```bash
deactivate
```

**Note:** Activate the virtual environment before running the server, clients, or tests. The `.venv/` directory is local to your machine and should not be committed to Git.