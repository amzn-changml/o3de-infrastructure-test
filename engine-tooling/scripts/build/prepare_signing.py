#
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
#
"""Cross-platform installer signing-material setup for the package workflows.

Extracted from the inline "Configure signing" steps of windows-package.yml and
linux-package.yml so those workflows stay thin adapters over ci_build.py.

What it does per platform:
  Windows: reads the base64 CodeSigning.Dlib.dll (O3DE_MS_DLIB_B64) and the
           metadata JSON (O3DE_MS_METADATA_JSON) from the environment, writes them
           into <signing-dir> as CodeSigning.Dlib.dll + metadata.json, and emits the
           O3DE_MS_DLIB_PATH / O3DE_MS_METADATA_PATH env assignments that
           scripts/signer/Platform/Windows/signer.ps1 keys off of.
  Linux:   reads the GPG private key (O3DE_GPG_PRIVATE_KEY) and optional passphrase
           (O3DE_GPG_PASSPHRASE) from the environment, imports the key into the GPG
           keyring (and warms gpg-agent so dpkg-sig can sign non-interactively).
           scripts/signer/Platform/Linux/signer.sh reads the keyring directly, so no
           env assignments are needed for Linux.

Absent secrets => unsigned build (signing_configured=false), matching prior behavior.

OUTPUT CONTRACT (stdout, one directive per line; anything else is human-readable log
that the workflow may ignore):
    ENV KEY=VALUE       -> workflow appends "KEY=VALUE" to $GITHUB_ENV
    OUTPUT KEY=VALUE    -> workflow appends "KEY=VALUE" to $GITHUB_OUTPUT
Everything the workflow needs is on ENV/OUTPUT lines; log lines go to stderr.
This script never writes to $GITHUB_ENV / $GITHUB_OUTPUT itself.
"""

import argparse
import base64
import os
import subprocess
import sys


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _emit_output(key, value):
    print('OUTPUT {}={}'.format(key, value), flush=True)


def _emit_env(key, value):
    print('ENV {}={}'.format(key, value), flush=True)


def prepare_windows(signing_dir):
    dlib_b64 = os.environ.get('O3DE_MS_DLIB_B64', '').strip()
    metadata_json = os.environ.get('O3DE_MS_METADATA_JSON', '').strip()

    if not dlib_b64 or not metadata_json:
        _log('Signing secrets not configured; producing an unsigned installer.')
        _emit_output('signing_configured', 'false')
        return 0

    os.makedirs(signing_dir, exist_ok=True)
    dlib_path = os.path.join(signing_dir, 'CodeSigning.Dlib.dll')
    meta_path = os.path.join(signing_dir, 'metadata.json')

    with open(dlib_path, 'wb') as f:
        f.write(base64.b64decode(dlib_b64))
    with open(meta_path, 'w', encoding='utf-8') as f:
        f.write(metadata_json)

    # signer.ps1 auto-engages MS Trusted Signing when these point at a valid dlib + metadata.
    _emit_env('O3DE_MS_DLIB_PATH', dlib_path)
    _emit_env('O3DE_MS_METADATA_PATH', meta_path)
    _emit_output('signing_configured', 'true')
    _log('Signing configured (MS Trusted Signing).')
    return 0


def prepare_linux(signing_dir):
    private_key = os.environ.get('O3DE_GPG_PRIVATE_KEY', '')
    passphrase = os.environ.get('O3DE_GPG_PASSPHRASE', '')

    if not private_key.strip():
        _log('Signing secrets not configured; producing an unsigned package.')
        _emit_output('signing_configured', 'false')
        return 0

    # signer.sh signs the .deb with the last private key in the keyring (via dpkg-sig).
    subprocess.run(['gpg', '--batch', '--import'],
                   input=private_key.encode('utf-8'), check=True)

    if passphrase.strip():
        # Warm gpg-agent so dpkg-sig can sign non-interactively later.
        fpr_proc = subprocess.run(['gpg', '--list-keys', '--with-colons'],
                                  stdout=subprocess.PIPE, check=True)
        fingerprints = [line.split(':')[9]
                        for line in fpr_proc.stdout.decode('utf-8', 'replace').splitlines()
                        if line.startswith('fpr:') and len(line.split(':')) > 9 and line.split(':')[9]]
        if fingerprints:
            fpr = fingerprints[-1]
            subprocess.run(
                ['gpg', '--batch', '--pinentry-mode', 'loopback', '--passphrase', passphrase,
                 '--local-user', fpr, '--sign', '--armor'],
                input=b'test', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    _emit_output('signing_configured', 'true')
    _log('Signing configured (GPG / dpkg-sig).')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Set up installer signing material.')
    parser.add_argument('--platform', required=True, choices=['Windows', 'Linux'],
                        help='Target platform.')
    parser.add_argument('--signing-dir', default=os.path.join(os.getcwd(), 'signing'),
                        help='Directory to write signing material into (Windows).')
    args = parser.parse_args()

    if args.platform == 'Windows':
        return prepare_windows(args.signing_dir)
    return prepare_linux(args.signing_dir)


if __name__ == '__main__':
    sys.exit(main())
