#!/usr/bin/env python3

from __future__ import annotations
import argparse
import heapq
import os
import pathlib
import subprocess
import typing


STAGING_DIRECTORY = pathlib.Path("/cluster/work/projects/nn9851k/PSI/HPLT")
MINHASH_PATH = pathlib.Path("/cluster/home/etiennes/project/PSI/tools/HPLT/minhash retrieval/target/release/hplt_minhash_retrieval")
QUERY_PATH = pathlib.Path("/cluster/home/etiennes/psi_query.jsonl")
OUTPUT_PATH = pathlib.Path("/cluster/projects/nn9851k/PSI/HPLT_minhash_matches")
HPLT_PATH = pathlib.Path("/nird/datalake/NS8112K/public/four/pool")

SLURM_ACCOUNT = "nn9851k"
SLURM_PARTITION = "small"
SLURM_TIME = "03-00" # This should be enough for 200 parallel jobs


def parse_command_argument() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run slurm scripts for HPLTv4 matching.")
    parser.add_argument("-n", "--nparallel", type=int, help="Number of parallel jobs to run.")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Write the job files to disk in ./run directory but do not run them.")

    args: argparse.Namespace = parser.parse_args()
    return args


class Partition:
    """
    A partition of files into `nbins` bins.

    Each bin contains a dictionary {file: size}.
    The bins are sorted by increasing total size.
    """

    def __init__(self: Partition, file: str, size: int, nbins: int):
        """Create a new file partition containing a single file of the given size."""
        self._data = [{} for _ in range(nbins - 1)] + [{file: size}]

    def diff(self: Partition) -> int:
        """The difference between the smallest and biggest bin in this partition."""
        return sum(self._data[-1].values()) - sum(self._data[0].values())

    def __lt__(self: Partition, rhs: Partition) -> bool:
        """Provide an ordering of partitions by differences."""
        return self.diff() < rhs.diff()

    def combine(self: Partition, rhs: Partition) -> None:
        """Add a partition to the current one, keeping the sorted bins invariant."""
        for i in range(len(self._data)):
            self._data[i] |= rhs._data[len(self._data) - i - 1]
        self._data.sort(key=lambda group: sum(group.values()))

    def compile(self: Partition) -> list[list[str]]:
        """Remove the size information to convert into a list of bins."""
        return list(map(lambda group: list(dict.keys(group)), self._data))


def karmarkar_karp(files: dict[str, int], nbins: int) -> list[list[str]]:
    """Partition a set of files into `nbins` groups of approximately the same size."""
    heap: list[Partition] = []
    for file, size in files.items():
        heapq.heappush(heap, Partition(file, size, nbins))

    while len(heap) > 1:
        lhs = heapq.heappop(heap)
        rhs = heapq.heappop(heap)
        lhs.combine(rhs)
        heapq.heappush(heap, lhs)

    return heap[0].compile()


def get_targets() -> dict[str, int]:
    """Get all HPLT data directories and their size."""
    directories: dict[str, int] = {}
    for dirpath, dirnames, filenames in HPLT_PATH.walk():
        if "text.zst" in filenames and "metadata.zst" in filenames:
            name: str = str(dirpath.relative_to(HPLT_PATH))
            directories[name] = sum((dirpath / filename).stat().st_size for filename in ["text.zst", "metadata.zst"])
    return directories


def build_run(index: int, partition: list[str], sizes: dict[str, int]) -> str:
    """Make a slurm job script for a given file list."""
    script: list[str] = [
            "#!/bin/bash",
            f"#SBATCH --job-name=PSI_HPLT_mh{index}",
            f"#SBATCH --account={SLURM_ACCOUNT}",
            f"#SBATCH --partition={SLURM_PARTITION}",
            f"#SBATCH --time={SLURM_TIME}",
            "#SBATCH --nodes=1",
            "#SBATCH --mem-per-cpu=4G",
            f'#SBATCH --output={OUTPUT_PATH}/slurm-%j-{index}.stdout',
            f'#SBATCH --error={OUTPUT_PATH}/slurm-%j-{index}.stderr',
        ]

    for directory in partition:
        for filename in ["text.zst", "metadata.zst"]:
            script.append(f'#STAGE IN "{HPLT_PATH/directory/filename}" "{STAGING_DIRECTORY/directory/filename}"')

    total_size: int = sum(sizes[directory] for directory in partition)
    current_size: int = 0

    script.append("set -o errexit -o nounset -o pipefail")
    script.append(f'cd "{STAGING_DIRECTORY}"')
    for directory in partition:
        output_file: str = directory.replace("/", "__")
        script.append(f'"{MINHASH_PATH}" "{QUERY_PATH}" "{directory}" --id="id" > {OUTPUT_PATH/output_file}.jsonl')
        current_size += sizes[directory]
        script.append(f'echo PROGRESS: [{current_size/total_size*100:.2f}%] {directory} done {current_size}/{total_size}')
    return "".join(f"{line}\n" for line in script)


def make_staging_hier(paths: Sequence[str]) -> None:
    """
    Make the staging directory hierarchy.

    The stage in slurm directives expect the directories to exist.
    """
    for path in paths:
        (STAGING_DIRECTORY / path).mkdir(parents=True, exist_ok=True)


def main(nparallel: int, dry_run: bool) -> None:
    targets: dict[str, int] = get_targets()
    make_staging_hier(targets.keys())
    partitions: list[list[str]] = karmarkar_karp(targets, nparallel)
    for i, partition in enumerate(partitions):
        index = f"{i:04}"
        script = build_run(index, partition, targets)
        if dry_run:
            output = pathlib.Path("run")
            output.mkdir(exist_ok=True)
            with (output / index).open("w") as file:
                print(script, file=file)
        else:
            result = subprocess.run(["sbatch"], input=script.encode("utf-8"))
            if result.returncode != 0:
                print(result)
                break

if __name__ == "__main__":
    args: argparse.Namespace = parse_command_argument()
    main(nparallel=args.nparallel, dry_run=args.dry_run)
