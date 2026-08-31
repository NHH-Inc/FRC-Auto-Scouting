"""Windows binary resolution, exercised on every platform.

These deliberately pass ``os_name="nt"`` rather than patching the global ``os.name``.
Patching it would also change what ``pathlib.Path`` constructs, and a ``WindowsPath``
cannot be instantiated on Linux -- which is how this file used to fail CI while
passing locally on Windows.
"""

import tempfile
import unittest
from pathlib import Path

from ingest.orchestrator import AnalysisOrchestrator


class AnalysisOrchestratorTests(unittest.TestCase):
    def test_windows_adds_exe_suffix_when_cmake_binary_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "analysis"
            executable = binary.with_suffix(".exe")
            executable.write_bytes(b"test executable")

            orchestrator = AnalysisOrchestrator(str(binary), os_name="nt")

            self.assertEqual(orchestrator.binary_path, str(executable))

    def test_existing_path_is_unchanged_when_windows_exe_is_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "analysis"

            orchestrator = AnalysisOrchestrator(str(binary), os_name="nt")

            self.assertEqual(orchestrator.binary_path, str(binary))

    def test_windows_finds_visual_studio_release_binary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "bin" / "analysis"
            executable = binary.parent / "Release" / "analysis.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"test executable")

            orchestrator = AnalysisOrchestrator(str(binary), os_name="nt")

            self.assertEqual(orchestrator.binary_path, str(executable))
