import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "seed":
        from adaptive_academy.seed import seed

        seed()
    else:
        print("usage: aa seed")


if __name__ == "__main__":
    main()
