{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  nativeBuildInputs = with pkgs.buildPackages; [
    cargo
    rustc
    (python3.withPackages (ps: with ps; [
      tqdm
      zstandard
    ]))
  ];

  CARGO_TARGET_DIR = "/tmp/cargo/minhash";
}
