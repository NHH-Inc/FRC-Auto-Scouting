"""Contract D -- invoking the analysis binary.

    analysis --job <path/to/job.json> --out <output/dir>

On success: exit 0, and events.jsonl, tracks.jsonl and result.json exist in <out>.
On failure: nonzero exit, human-readable reason on stderr.
Progress arrives on stdout as one JSON object per line: {"progress": 0.42, "stage": "tracking"}
"""

import json
import subprocess
from pathlib import Path


class AnalysisOrchestrator:
    def __init__(self, binary_path: str, output_base_dir: str = "/data/jobs"):
        self.binary_path = binary_path
        self.output_base_dir = Path(output_base_dir)

    def run_job(self, job_data: dict, on_progress=None) -> dict:
        job_id = job_data["job_id"]
        job_dir = self.output_base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        job_config_path = job_dir / "job.json"
        with open(job_config_path, "w", encoding="utf-8") as handle:
            json.dump(job_data, handle)

        cmd = [self.binary_path, "--job", str(job_config_path), "--out", str(job_dir)]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Drain stdout as it arrives so the progress bar is live rather than arriving all at
        # once when the process exits. Do NOT call communicate() afterwards -- stdout is
        # already consumed here, and mixing the two can deadlock.
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # Contract D says stdout is JSON lines; anything else is the binary being
                # chatty. Ignore it rather than failing the run.
                continue
            if on_progress is not None:
                on_progress(message.get("progress"), message.get("stage"))

        process.stdout.close()
        returncode = process.wait()
        stderr = process.stderr.read() if process.stderr else ""
        if process.stderr:
            process.stderr.close()

        if returncode != 0:
            raise RuntimeError(
                f"analysis exited {returncode}: {stderr.strip() or 'no reason on stderr'}"
            )

        outputs = {
            "events_path": str(job_dir / "events.jsonl"),
            "tracks_path": str(job_dir / "tracks.jsonl"),
            "result_path": str(job_dir / "result.json"),
        }
        missing = [name for name, path in outputs.items() if not Path(path).exists()]
        if missing:
            raise RuntimeError(
                "analysis exited 0 but did not write: " + ", ".join(sorted(missing))
            )

        # result.json carries box_sample_rate, which component 3 needs in order to know how
        # much to interpolate between box samples -- but no Contract E endpoint exposes it.
        # See contracts/OPEN_QUESTIONS.md #2.
        try:
            with open(outputs["result_path"], "r", encoding="utf-8") as handle:
                outputs["result"] = json.load(handle)
        except (OSError, json.JSONDecodeError):
            outputs["result"] = {}

        return outputs
