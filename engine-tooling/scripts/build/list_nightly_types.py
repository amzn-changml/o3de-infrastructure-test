#
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
"""Print the union of build types tagged for nightly/periodic packaging across platforms.

Thin wrapper around:
    ci_build.py --platform <P> --list-types --tag <TAG>

which prints the build_type names whose TAGS (in scripts/build/Platform/<P>/build_config.json)
contain <TAG>. This is the GHA-era stand-in for the Jenkins TAGS selection (Jenkinsfile
IsJobEnabled). Used as a logging/verification step in .github/workflows/nightly-package.yml so a
run records exactly which pipes are considered nightly. No build side effects; stdlib-only.
"""

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_PLATFORMS = ["Windows", "Linux"]


def list_types_for_platform(ci_build_py: Path, platform: str, tag: str) -> list:
    """Return the build types tagged <tag> for <platform>, or [] if none/platform unavailable."""
    result = subprocess.run(
        [sys.executable, str(ci_build_py), "--platform", platform, "--list-types", "--tag", tag],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Surface, don't swallow: an unsupported platform or a missing build_config is worth seeing.
        sys.stderr.write(
            f"[list_nightly_types] {platform}: ci_build.py exited {result.returncode}\n{result.stderr}"
        )
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default="nightly-installer",
        help="TAG to match against build_config.json TAGS arrays (default: nightly-installer).",
    )
    parser.add_argument(
        "--platform",
        dest="platforms",
        action="append",
        help="Platform to query (repeatable). Defaults to Windows and Linux.",
    )
    args = parser.parse_args()

    platforms = args.platforms or DEFAULT_PLATFORMS
    ci_build_py = Path(__file__).resolve().parent / "ci_build.py"

    union = []
    for platform in platforms:
        for build_type in list_types_for_platform(ci_build_py, platform, args.tag):
            print(f"{platform}: {build_type}")
            if build_type not in union:
                union.append(build_type)

    print(f"nightly build types (tag '{args.tag}'): {', '.join(union) if union else '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
