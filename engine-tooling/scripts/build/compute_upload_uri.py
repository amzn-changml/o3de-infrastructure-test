#
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
#
"""Cross-platform upload/installer URI computation for the package workflows.

Extracted from the inline "Compute upload/installer URI" steps of
windows-package.yml and linux-package.yml.

Given the installer S3 bucket (e.g. "s3://my-bucket") and the installer object key
(e.g. "/development/Latest/Windows/o3de_installer.exe") it computes:
  * CPACK_UPLOAD_URL  - the S3 prefix CPack uploads the installer under; CPack appends
                        <version>/<host>. This is the parent "directory" of the object.
  * installer_s3_uri  - the full s3:// URI the installer_test job pulls from.

Empty bucket => no S3 upload: emit an empty installer_s3_uri and no CPACK_UPLOAD_URL,
so the test job falls back to the locally built artifact (matching prior behavior).

OUTPUT CONTRACT (stdout, one directive per line; other lines are human-readable log):
    ENV KEY=VALUE       -> workflow appends "KEY=VALUE" to $GITHUB_ENV
    OUTPUT KEY=VALUE    -> workflow appends "KEY=VALUE" to $GITHUB_OUTPUT
This script never writes to $GITHUB_ENV / $GITHUB_OUTPUT itself.
"""

import argparse
import os
import posixpath
import sys


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description='Compute installer upload/download URIs.')
    parser.add_argument('--bucket', default=os.environ.get('INSTALLER_S3_BUCKET', ''),
                        help='Installer S3 bucket URI, e.g. s3://my-bucket (may be empty).')
    parser.add_argument('--s3-path', required=True,
                        help='Installer object key with leading slash, e.g. /dev/Latest/Windows/o3de_installer.exe')
    args = parser.parse_args()

    bucket = (args.bucket or '').strip()
    s3_path = args.s3_path

    if not bucket:
        # No bucket => skip S3 upload (and, on Linux, signing which requires upload).
        print('OUTPUT installer_s3_uri=', flush=True)
        _log('INSTALLER_S3_BUCKET not configured; skipping S3 upload.')
        return 0

    bucket = bucket.rstrip('/')
    # S3 keys use forward slashes regardless of host OS.
    upload_prefix = bucket + posixpath.dirname(s3_path)
    installer_uri = bucket + s3_path

    print('ENV CPACK_UPLOAD_URL={}'.format(upload_prefix), flush=True)
    print('OUTPUT installer_s3_uri={}'.format(installer_uri), flush=True)
    _log('Installer will be uploaded under: {}'.format(upload_prefix))
    return 0


if __name__ == '__main__':
    sys.exit(main())
