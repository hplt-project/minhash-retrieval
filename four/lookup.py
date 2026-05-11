#!/usr/bin/env python3

from __future__ import annotations
import argparse
import collections
import contextlib
import dataclasses
import io
import itertools
import json
import pathlib
import typing
import urllib.request

import tqdm
import zstandard


HPLT_URL_PREFIX: str = "https://data.hplt-project.org/four/pool"


def parse_command_argument() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Lookup documents and metadata from minhash results.")
    parser.add_argument("-c", "--cache", type=pathlib.Path, help="Path to a cache directory to store downloaded data incrementally and continue from it.")
    parser.add_argument("output", type=pathlib.Path, help="Path where the jsonl containing documents and metadata will be written.")
    parser.add_argument("matches", type=pathlib.Path, help="Path to the jsonl containing the minhash output to lookup in HPLT.")

    args: argparse.Namespace = parser.parse_args()
    return args


def read_matches(matches_path: pathlib.Path) -> dict[int, list[dict[str, typing.Any]]]:
    """Read minhash matches."""
    matches: dict[int, list[dict[str, typing.Any]]] = collections.defaultdict(list)
    with matches_path.open() as matches_file:
        for line in matches_file:
            match = json.loads(line)
            matches[match["q"]].append(match)
    return matches


def select_matches(inputs: dict[int, list[dict[str, typing.Any]]]) -> list[dict[str, typing.Any]]:
    """Select the most similar match for each query document."""
    outputs: list[dict[str, typing.Any]] = []
    for matches in inputs.values():
        outputs.append(max(matches, key=lambda match: match["s"]))
    return outputs


@dataclasses.dataclass(init=False)
class FileLookupLocation:
    begin_offset: int
    end_offset: int
    line_skip: int
    qid: int

    def __init__(self: FileLookupLocation, data: dict[str, typing.Any], key: str) -> None:
        self.begin_offset = data[key]["b"]
        self.end_offset = data[key]["e"]
        self.line_skip = data[key]["l"]
        self.qid = data["q"]

    def offsets(self: FileLookupLocation) -> tuple[int, int]:
        return (self.begin_offset, self.end_offset)


@dataclasses.dataclass
class LookupLocations:
    metadata: dict[str, list[FileLookupLocation]]
    text: dict[str, list[FileLookupLocation]]


def aggregate_matches_for_lookup(matches: list[dict[str, typing.Any]]) -> LookupLocations:
    """Get a list of FileLookupLocation for each file with a match."""
    metadata: dict[str, list[FileLookupLocation]] = collections.defaultdict(list)
    text: dict[str, list[FileLookupLocation]] = collections.defaultdict(list)
    for match in matches:
        metadata[match["p"]].append(FileLookupLocation(match, "m"))
        text[match["p"]].append(FileLookupLocation(match, "t"))
    return LookupLocations(metadata, text)


def merge_intervals(locations: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Merge adjacent or overlapping intervals into one.

    This is to minimize the number of HTTP request to HPLT.
    """
    intervals: list[tuple[int, int]] = [locations[0]]
    for location in itertools.islice(locations, 1, None):
        if location[0] <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], location[1])
        else:
            intervals.append(location)
    return intervals


def hplt_fetch(file: str, subfile: str, brange: tuple[int, int]) -> bytes:
    """Download a chunk of HPLT data."""
    with urllib.request.urlopen(
            urllib.request.Request(f"{HPLT_URL_PREFIX}/{file}/{subfile}.zst",
                                   headers={"Range": f"bytes={brange[0]}-{brange[1]-1}"})) as file:
        data: bytes = file.read()
        assert(len(data) == brange[1]- brange[0])
        return data


def extract_buffer(compressed_data: bytes, compressed_range: tuple[int, int], target: tuple[int, int]) -> list[bytes]:
    """Uncompress zstd data into a list of lines."""
    decompressor = zstandard.ZstdDecompressor()
    begin: int = target[0] - compressed_range[0]
    end: int = target[1] - compressed_range[0]
    reader = decompressor.stream_reader(io.BytesIO(compressed_data[begin:end]), read_across_frames=True)
    return reader.readall().split(b'\n')


def load_cache_file(path: pathlib.Path) -> dict[int, dict[str, typing.Any]]:
    """Read a local HPLT cache file."""
    if path is None or not path.exists():
        return {}

    data: dict[int, dict[str, typing.Any]] = {}
    with path.open() as file:
        for line in file:
            sample: dict[str, typing.Any] = json.loads(line)
            data[sample["q"]] = sample["d"]
    return data


def hplt_file_lookup(file: str, subfile: str, locations: list[FileLookupLocation], cache_path: pathlib.Path | None) -> dict[int, dict[str, typing.Any]]:
    """
    Download the selected data from a given file.

    Given a file (e.g. CC-MAIN-2020-10/42), a subfile (e.g. text.zst) and a list of locations in that data, this function download the samples at the given locations.
    If a cache_path is given, data is downloaded only if it is not in cache, in which case, downloaded data is added to the cache.
    """
    locations.sort(key=FileLookupLocation.offsets)
    merged_ranges: list[tuple[int, int]] = merge_intervals([location.offsets() for location in locations])

    output: dict[int, dict[str, typing.Any]] = load_cache_file(cache_path)

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_context = cache_path.open("ab")
    else:
        cache_context = contextlib.nullcontext()

    range_index: int = -1
    compressed_data: bytes = b''
    last_location: tuple[int, int] = (-1, -1)
    data: list[bytes] = []
    with cache_context as cache_file:
        for location in locations:
            if location.qid in output:
                # This data point was already in the cache
                continue

            if range_index < 0 or location.begin_offset >= merged_ranges[range_index][1]:
                while range_index < 0 or location.begin_offset >= merged_ranges[range_index][1]:
                    range_index += 1
                compressed_data = hplt_fetch(file, subfile, merged_ranges[range_index])

            tlocation: tuple[int, int] = location.offsets()
            if tlocation != last_location:
                # There is certainly a smarter way of doing that, but the speed is dominated by downloading the data anyway.
                data = extract_buffer(compressed_data, merged_ranges[range_index], tlocation)
                last_location = tlocation

            sample: bytes = data[location.line_skip]
            output[location.qid] = json.loads(sample.decode())
            if cache_file is not None:
                cache_file.write(b'{"q":')
                cache_file.write(str(location.qid).encode())
                cache_file.write(b',"d":')
                cache_file.write(sample)
                cache_file.write(b'}\n')

    return output


def main(output_path: pathlib.Path, matches_path: pathlib.Path, cache_path: pathlib.Path | None) -> None:
    """Lookup documents and metadata from minhash results."""
    matches: dict[int, list[dict[str, typing.Any]]] = read_matches(matches_path)
    selected_matches: list[dict[str, typing.Any]] = select_matches(matches)
    lookup_locations: LookupLocations = aggregate_matches_for_lookup(selected_matches)
    text: dict[int, dict[str, typing.Any]] = {}
    metadata: dict[int, dict[str, typing.Any]] = {}
    for file, locations in tqdm.tqdm(lookup_locations.text.items(), desc="text lookup"):
        text.update(hplt_file_lookup(file, "text", locations, cache_path / file / "text.jsonl" if cache_path else None))
    for file, locations in tqdm.tqdm(lookup_locations.metadata.items(), desc="metadata lookup"):
        metadata.update(hplt_file_lookup(file, "metadata", locations, cache_path / file / "metadata.jsonl" if cache_path else None))
    with output_path.open("w") as output:
        for match in selected_matches:
            match["t"] = text[match["q"]]
            match["m"] = metadata[match["q"]]
            print(json.dumps(match), file=output)


if __name__ == "__main__":
    args: argparse.Namespace = parse_command_argument()
    main(output_path=args.output, matches_path=args.matches, cache_path=args.cache)
