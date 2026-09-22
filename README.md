# Legacy Hospital Edge–Cloud Monitoring System

This repository contains a simulated legacy hospital monitoring system for a
software development, maintenance, and operations project.

The purpose of the project is to analyze and modernize a small legacy
edge-cloud system for a transition toward post-quantum cryptography (PQC).

> **Important:** This project uses completely synthetic patient data. It must
> not be used with real patients, real hospital data, or production systems.

## System Components

The system contains three simulated Python components:

1. **Legacy Device**
   - Simulates a limited-capability bedside health-monitoring device.
   - Generates heart-rate and blood-oxygen readings.
   - Simulates a 2 KB payload/memory constraint.
   - Waits between sensor readings to simulate limited processing capability.
   - Encrypts readings using legacy ChaCha20 encryption.
   - Sends encrypted readings to the edge gateway.

2. **Edge Gateway**
   - Receives encrypted readings from legacy devices.
   - Decrypts device messages.
   - Maps a device ID to synthetic patient and room information.
   - Detects unhealthy readings:
     - heart rate below 40 BPM,
     - heart rate above 100 BPM,
     - blood oxygen below 90%.
   - Prints an alert for a nurse/reception system.
   - Aggregates hourly minimum, maximum, and average values.
   - Sends aggregated information to the cloud through a REST API.

3. **Cloud Service**
   - Provides a REST API.
   - Receives processed hourly data from the gateway.
   - Stores data in an in-memory Python dictionary.
   - Groups stored records by patient name.

## Architecture

```text
+-------------------+
| Legacy Device     |
|-------------------|
| Generates readings|
| ChaCha20 encrypts |
+---------+---------+
          |
          | HTTP POST /device-data
          | encrypted payload
          v
+-------------------+
| Edge Gateway      |
|-------------------|
| Decrypts readings |
| Looks up patient  |
| Creates alerts    |
| Aggregates hourly |
+---------+---------+
          |
          | HTTP POST /aggregates
          | processed aggregate
          v
+-------------------+
| Cloud Service     |
|-------------------|
| REST API          |
| In-memory storage |
| Data by patient   |
+-------------------+

```

# How to run the setup on Windows

```markdown
## Running on Windows

These instructions use **Windows PowerShell**.

### 1. Clone the repository

```powershell
git clone https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
cd YOUR-REPOSITORY
```

### 2. Check Python installation

Python 3.10 or newer is required.

```powershell
python --version
```

If Python is not found, install it from:

```text
https://www.python.org/downloads/
```

During installation, select **Add Python to PATH**.

### 3. Create a virtual environment

Run this from the repository root:

```powershell
python -m venv .venv
```

### 4. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

After activation, your PowerShell prompt should begin with:

```text
(.venv)
```

### 5. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Allow PowerShell scripts temporarily

If PowerShell blocks `.ps1` scripts, run this command once in the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

This is temporary and applies only to the currently open PowerShell window.

### 7. Start the full simulation automatically

Run:

```powershell
.\scripts\run_demo.ps1
```

The script starts:

1. Cloud service at `http://127.0.0.1:8002`
2. Edge gateway at `http://127.0.0.1:8001`
3. Legacy device simulator

Press `Ctrl+C` to stop the legacy device. The gateway will attempt to send its current aggregate data to the cloud before shutdown.

### 8. View cloud data

While the services are running, open these URLs in a browser:

```text
http://127.0.0.1:8002/health
http://127.0.0.1:8002/patients
http://127.0.0.1:8002/database
```

To view gateway status:

```text
http://127.0.0.1:8001/health
http://127.0.0.1:8001/pending-aggregates
```

---

## Running Components Manually on Windows

Alternatively, open three PowerShell terminals. In each terminal, move to the repository directory and activate the virtual environment:

```powershell
cd PATH\TO\YOUR-REPOSITORY
.\.venv\Scripts\Activate.ps1
```

### Terminal 1: Cloud service

```powershell
python -m cloud.cloud_service
```

### Terminal 2: Edge gateway

```powershell
python -m gateway.gateway_service
```

### Terminal 3: Legacy device

```powershell
python -m device.legacy_device
```

Stop the device with `Ctrl+C`. It requests that the gateway flush its current aggregate data to the cloud.

> Start services in this order: **cloud → gateway → device**.
```

Replace `YOUR-USERNAME`, `YOUR-REPOSITORY`, and `PATH\TO\YOUR-REPOSITORY` with your actual values.
