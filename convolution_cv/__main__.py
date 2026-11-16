"""Launch with python -m convolution_cv or convolution-analysis."""
import argparse

from . import __version__


def main():
    parser = argparse.ArgumentParser(description="Convolution Analysis desktop application")
    parser.add_argument("--version", action="version", version=f"Convolution Analysis {__version__}")
    parser.parse_args()
    from .ui import launch
    launch()


if __name__ == "__main__":
    main()
