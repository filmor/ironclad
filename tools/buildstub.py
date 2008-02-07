
import os
import sys

from tools.stubmaker import StubMaker


def generateOutput(outputFile, contents):
    f = open(outputFile, "w")
    try:
        f.write(contents)
    finally:
        f.close()


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(1)

    sourceDll = sys.argv[1]
    outputDir = sys.argv[2]
    overrideDir = None
    if len(sys.argv) == 4:
        overrideDir = sys.argv[3]

    sm = StubMaker(sourceDll, overrideDir)

    if not os.path.exists(outputDir):
        os.mkdir(outputDir)

    filename = os.path.splitext(os.path.basename(sourceDll))[0]

    os.chdir(outputDir)
    generateOutput("%s.c" % (filename, ), sm.generate_c())
    generateOutput("%s.asm" % (filename, ), sm.generate_asm())
    generateOutput("Makefile", sm.generate_makefile(filename))
    os.spawnl(os.P_WAIT, "make", "make")


if __name__ == "__main__":
    main()
