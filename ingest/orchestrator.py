import subprocess
import json
import os
from pathlib import Path

class AnalysisOrchestrator:
    def __init__(self, binary_path: str, output_base_dir: str = "/data/jobs"):
        self.binary_path = binary_path
        self.output_base_dir = Path(output_base_dir)

    def run_job(self, job_data: dict):
        job_id = job_data["job_id"]
        job_dir = self.output_base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        job_config_path = job_dir / "job.json"

        # Write job config for the C++ backend
        with open(job_config_path, "w") as f:
            json.dump(job_data, f)

        # Invoke C++ binary (Contract D)
        cmd = [
            self.binary_path,
            "--job", str(job_config_path),
            "--out", str(job_dir)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Handle progress reporting (Contract D)
        for line in process.stdout:
            try:
                progress_data = json.loads(line)
                print(f"Job {job_id} progress: {progress_data.get('progress')} - {progress_data.get('stage')}")
                # In a real app, this would update the DB or a websocket
            except json.JSONDecodeError:
                pass

        stdout, stderr = process.communicate()

        if process.returncode != 0:
            raise Exception(f"Analysis failed: {stderr}")

        return {
            "events_path": str(job_dir / "events.jsonl"),
            "tracks_path": str(job_dir / "tracks.jsonl"),
            "result_path": str(job_dir / "result.json")
        }
