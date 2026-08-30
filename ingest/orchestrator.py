"""Contract D -- invoking the analysis binary.

    analysis --job <job.json> --season <season.json> --out <output/dir>

On success: exit 0, and events.jsonl, tracks.jsonl and result.json exist in <out>.
On failure: nonzero exit, human-readable reason on stderr.
Progress arrives on stdout as one JSON object per line: {"progress": 0.42, "stage": "tracking"}
"""

import json
import os
import subprocess
from pathlib import Path

# The subset of error_code values component 1 is allowed to report.
ANALYSIS_ERROR_CODES = {"analysis_failed", "timeout", "internal", "no_match_data"}


def resolve_binary_path(binary_path: str) -> str:
    """Use the Windows ``.exe`` that CMake produces without making Linux config Windows-only."""
    path = Path(binary_path)
    if os.name == "nt" and not path.suffix:
        # Ninja/single-config builds use ``bin\\analysis.exe``; Visual Studio multi-config
        # builds use ``bin\\Release\\analysis.exe``. The config stays portable either way.
        candidates = (
            path.with_suffix(".exe"),
            path.parent / "Release" / f"{path.name}.exe",
        )
        for windows_binary in candidates:
            if windows_binary.is_file():
                return str(windows_binary)
    return binary_path


class AnalysisOrchestrator:
    def __init__(self, binary_path: str, output_base_dir: str = "/data/jobs"):
        self.binary_path = resolve_binary_path(binary_path)
        self.output_base_dir = Path(output_base_dir)

    def run_job(self, job_data: dict, season_path: str, on_progress=None) -> dict:
        job_id = job_data["job_id"]
        job_dir = self.output_base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        job_config_path = job_dir / "job.json"
        with open(job_config_path, "w", encoding="utf-8") as handle:
            json.dump(job_data, handle)

        # Contract D v2: the season config is passed in, so component 1 reads phase
        # boundaries and field dimensions from the same file component 3 does.
        cmd = [
            self.binary_path,
            "--job", str(job_config_path),
            "--season", str(season_path),
            "--out", str(job_dir),
        ]

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
            # Contract D: the LAST line of stderr is an error_code enum value, so
            # component 2 can classify without parsing prose.
            lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
            code = lines[-1].strip() if lines else ""
            reason = "\n".join(lines[:-1]) if len(lines) > 1 else (code or "no reason on stderr")
            err = RuntimeError(f"analysis exited {returncode}: {reason}")
            err.error_code = code if code in ANALYSIS_ERROR_CODES else None
            raise err

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
