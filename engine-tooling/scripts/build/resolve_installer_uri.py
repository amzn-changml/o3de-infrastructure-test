#
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
#
"""Resolve the installer URI for the installer_test job.

Extracted from the inline "Resolve installer URI" step of windows-package.yml.

Preference order:
  1. The S3 URI surfaced by the Build-Installer job (--s3-uri), when non-empty.
  2. Otherwise the first locally downloaded installer artifact matching --glob under
     --download-dir (searched recursively).

conftest.py treats file URIs by stripping the scheme, so a plain absolute path is
passed for the local case. If neither is available, this fails with a clear error.

OUTPUT CONTRACT (stdout, one directive per line; other lines are human-readable log):
    OUTPUT KEY=VALUE    -> workflow appends "KEY=VALUE" to $GITHUB_OUTPUT
This script never writes to $GITHUB_ENV / $GITHUB_OUTPUT itself. On failure it prints
a "::error::" line (GitHub log annotation) to stderr and exits non-zero.
"""

import argparse
import glob as globmod
import os
import sys


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description='Resolve the installer URI for testing.')
    parser.add_argument('--s3-uri', default='',
                        help='Preferred S3 installer URI (may be empty).')
    parser.add_argument('--download-dir', required=True,
                        help='Directory containing the downloaded installer artifact.')
    parser.add_argument('--glob', default='*.exe',
                        help='Filename glob for the local installer (default: *.exe).')
    args = parser.parse_args()

    s3_uri = (args.s3_uri or '').strip()
    if s3_uri:
        print('OUTPUT installer_uri={}'.format(s3_uri), flush=True)
        _log('Using S3 installer: {}'.format(s3_uri))
        return 0

    matches = sorted(globmod.glob(os.path.join(args.download_dir, '**', args.glob),
                                  recursive=True))
    if not matches:
        _log('::error::No installer found in S3 or artifact; cannot run installer_test.')
        return 1

    installer_path = matches[0]
    print('OUTPUT installer_uri={}'.format(installer_path), flush=True)
    _log('Using local installer: {}'.format(installer_path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
