{
  description = "STVID: satellite tools for video";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (
        pkgs:
        let
          pythonPackages = pkgs.python3Packages;
        in
        rec {
          hough3dlines = pkgs.stdenv.mkDerivation {
            pname = "hough3dlines";
            version = "unstable-2023-05-31";
            src = pkgs.fetchFromGitLab {
              owner = "pierros";
              repo = "hough3d-code";
              rev = "6e9c46413c8ac59d4a48ed108709719fb844927c";
              hash = "sha256-6gh7F645WIVtE8Y4ihv7ZuLxGlY8KS1k31xVkqLsBfg=";
            };
            buildInputs = [ pkgs.eigen ];
            makeFlags = [ "LIBEIGEN=${pkgs.eigen}/include/eigen3" ];
            installPhase = ''
              install -Dm755 hough3dlines $out/bin/hough3dlines
            '';
          };

          satpredict = pkgs.stdenv.mkDerivation {
            pname = "satpredict";
            version = "unstable-2025-01-01";
            src = pkgs.fetchFromGitHub {
              owner = "cbassa";
              repo = "satpredict";
              rev = "00c4e6ee60bc8918aad3f659e3c8067a77e761ae";
              hash = "sha256-BnHhLb3ptG4vKZTzhrksfgFsere4oJfmKlVukijCXtg=";
            };
            installPhase = ''
              install -Dm755 satpredict $out/bin/satpredict
            '';
          };

          astrometry-net = pkgs.stdenv.mkDerivation rec {
            pname = "astrometry-net";
            version = "0.98";
            src = pkgs.fetchFromGitHub {
              owner = "dstndstn";
              repo = "astrometry.net";
              rev = version;
              hash = "sha256-/YLDcPOQHw23s77s3XRVa6YV4CwT5CKs3f+m2pBLajY=";
            };
            nativeBuildInputs = with pkgs; [
              pkg-config
              swig
              makeWrapper
              which
            ];
            buildInputs = with pkgs; [
              cairo
              cfitsio
              gsl
              libjpeg
              libpng
              netpbm
              wcslib
              zlib
              bzip2
              (python3.withPackages (ps: [
                ps.astropy
                ps.numpy
                ps.setuptools
              ]))
            ];
            makeFlags = [
              "SYSTEM_GSL=yes"
              "INSTALL_DIR=$(out)"
            ];
            buildFlags = [
              "all"
              "py"
              "extra"
            ];
            installTargets = [ "install" ];
            postFixup = ''
              wrapProgram $out/bin/solve-field \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.netpbm ]} \
                --run 'if [ -n "$ASTROMETRY_CONFIG" ]; then set -- --config "$ASTROMETRY_CONFIG" "$@"; fi'
            '';
          };

          # STVID invokes the binary as `sextractor`; nixpkgs only installs `sex`
          sextractor = pkgs.runCommand "sextractor-alias" { } ''
            mkdir -p $out/bin
            ln -s ${pkgs.sextractor}/bin/sex $out/bin/sextractor
          '';

          zwoasi = pythonPackages.buildPythonPackage rec {
            pname = "zwoasi";
            version = "0.2.0";
            format = "wheel";
            src = pythonPackages.fetchPypi {
              inherit pname version;
              format = "wheel";
              dist = "py3";
              python = "py3";
              hash = "sha256-OkLSTSSn19QkFVH/Opkz+FXxGblfQy0wryYdXIplr9c=";
            };
            dependencies = [ pythonPackages.numpy ];
            doCheck = false;
          };

          represent = pythonPackages.buildPythonPackage rec {
            pname = "represent";
            version = "2.2.0";
            pyproject = true;
            src = pythonPackages.fetchPypi {
              inherit pname version;
              hash = "sha256-QD2qf4NgOQuEsUO3vx3XIJZaPpOiNJlJI8cSPMVdX+E=";
            };
            build-system = [ pythonPackages.hatchling ];
            doCheck = false;
          };

          rush = pythonPackages.buildPythonPackage rec {
            pname = "rush";
            version = "2021.4.0";
            pyproject = true;
            src = pythonPackages.fetchPypi {
              inherit pname version;
              hash = "sha256-gYYkB18DE/ZKTDi6YrxKZSbuMbRjmQyK6/A6mPWq8mQ=";
            };
            build-system = [ pythonPackages.setuptools ];
            dependencies = [ pythonPackages.attrs ];
            doCheck = false;
          };

          spacetrack = pythonPackages.buildPythonPackage rec {
            pname = "spacetrack";
            version = "1.4.0";
            pyproject = true;
            src = pythonPackages.fetchPypi {
              inherit pname version;
              hash = "sha256-/ktUw97eBJag7MQDkhFIGiWuT70O/15UGQRB8NRDTHQ=";
            };
            build-system = [ pythonPackages.setuptools ];
            dependencies = with pythonPackages; [
              filelock
              httpx
              logbook
              sniffio
              typing-extensions
              outcome
              platformdirs
              python-dateutil
              represent
              rush
            ];
            pythonRelaxDeps = [ "logbook" ];
            doCheck = false;
          };
        }
      );

      devShells = forAllSystems (
        pkgs:
        let
          inherit (self.packages.${pkgs.stdenv.hostPlatform.system})
            hough3dlines
            satpredict
            astrometry-net
            sextractor
            zwoasi
            spacetrack
            ;
          python = pkgs.python3.withPackages (
            ps: with ps; [
              astropy
              gpiozero
              matplotlib
              numpy
              opencv4
              pyyaml
              readchar
              scipy
              termcolor
            ]
            ++ [
              zwoasi
              spacetrack
            ]
          );
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              hough3dlines
              satpredict
              astrometry-net
              sextractor
            ];
            shellHook = ''
              export ST_DATADIR="$PWD"

              # The packaged astrometry.cfg lists no index files; point it at a
              # user-writable directory instead of the read-only store.
              export ASTROMETRY_INDEX_DIR="''${ASTROMETRY_INDEX_DIR:-$HOME/.local/share/astrometry}"
              export ASTROMETRY_CONFIG="''${XDG_RUNTIME_DIR:-/tmp}/stvid-astrometry.cfg"
              printf 'add_path %s\nautoindex\ninparallel\n' "$ASTROMETRY_INDEX_DIR" > "$ASTROMETRY_CONFIG"
            '';
          };
        }
      );
    };
}
