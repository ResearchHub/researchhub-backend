import dataclasses
import os

from health_check import HealthCheck


@dataclasses.dataclass
class GitHashHealthCheck(HealthCheck):
    """
    No-op health check that reports the current Git hash.
    The Git hash is either read from a file called `git_hash.txt` in the
    current working directory, or by running `git rev-parse HEAD`.
    """

    git_hash: str = dataclasses.field(init=False)

    def __post_init__(self):
        git_hash = self._get_git_hash()
        self.git_hash = git_hash[:7] if git_hash else "unknown"

    async def run(self):
        # no-op: no active checks
        pass

    def _get_git_hash(self):
        long_hash = self._read_git_hash_from_file()

        if long_hash is None:
            long_hash = self._read_git_hash_from_process()

        return long_hash

    def _read_git_hash_from_file(self):
        git_hash = None
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(base_dir)
            file_path = os.path.join(parent_dir, "git_hash.txt")
            with open(file_path) as f:
                git_hash = f.read().strip()
        except FileNotFoundError:
            pass

        return git_hash

    def _read_git_hash_from_process(self):
        git_hash = None
        try:
            import subprocess

            git_hash = (
                subprocess.check_output(["git", "rev-parse", "HEAD"])
                .decode("utf-8")
                .strip()
            )
        except Exception:
            pass

        return git_hash
