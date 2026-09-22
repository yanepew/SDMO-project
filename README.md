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
