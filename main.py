import sys

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from gerberstep.self_test import run
        sys.exit(run(sys.argv[2]))
    else:
        from gerberstep.app import main
        main()
