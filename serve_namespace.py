import sys

from main import run_orchestrated_namespace_server, run_refusing_newer_vaults_plainly


def main(argv: list[str]) -> None:
    run_refusing_newer_vaults_plainly(lambda: run_orchestrated_namespace_server(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
