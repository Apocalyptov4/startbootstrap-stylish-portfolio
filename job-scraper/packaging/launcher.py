"""Entry point of the packaged Job Radar program (see job-radar.spec)."""

import sys
import traceback

from jobscraper.server import main

if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except Exception:
        traceback.print_exc()
        code = 1
    if code:
        # Double-clicked programs close their window on exit; keep it open so the error can be read.
        input("\nSomething went wrong (see above). Press Enter to close this window.")
    sys.exit(code)
