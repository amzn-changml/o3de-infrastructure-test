#
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
#

import argparse
import json
import os
import sys
import subprocess

# Maximum nested-pipe expansion depth. Guards against a pipe that references
# itself (directly or transitively) causing infinite recursion.
MAX_PIPE_DEPTH = 16

class Step:
    """A single expanded leaf step to execute as part of a pipe.

    name          : build_type key of the leaf in build_config.json
    config        : the leaf's config dict (COMMAND / PARAMETERS / PIPELINE_ENV)
    nonblocking   : True if this step may fail without aborting the pipe
    """
    def __init__(self, name, config):
        self.name = name
        self.config = config
        pipeline_env = config.get('PIPELINE_ENV') or {}
        self.nonblocking = str(pipeline_env.get('NONBLOCKING_STEP', '')).lower() == 'true'


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--platform', dest="build_platform", help="Platform to build")
    parser.add_argument('-t', '--type', dest="build_type", help="Target config type to build")
    parser.add_argument('-c', '--config', dest="build_config_filename",
                        default="build_config.json",
                        help="JSON filename in Platform/<platform> that defines build configurations for the platform")
    parser.add_argument('--stop-before', dest="stop_before", default=None,
                        help="When running a pipe, stop before executing this build type (exclusive)")
    parser.add_argument('--skip', dest="skip", action='append', default=[],
                        help="Skip this build type when expanding a pipe (repeatable)")
    parser.add_argument('--list-types', dest="list_types", action='store_true',
                        help="List the build_type names defined in the config and exit")
    parser.add_argument('--tag', dest="tag", default=None,
                        help="With --list-types, only list build types whose TAGS contain this tag")
    args = parser.parse_args()

    # Input validation
    if args.build_platform is None:
        print('[ci_build] No platform specified')
        sys.exit(-1)

    # --type is optional only when listing types
    if args.build_type is None and not args.list_types:
        print('[ci_build] No type specified')
        sys.exit(-1)

    return args


def resolve_paths(build_config_filename, build_platform):
    """Resolve the config file and the directories used to locate commands.

    Returns (script_dir, engine_dir, build_config_abspath) or None if the
    config file cannot be found (matching the original not-found behavior).
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    engine_dir = os.path.abspath(os.path.join(script_dir, '../..'))
    config_dir = os.path.abspath(os.path.join(script_dir, 'Platform', build_platform))
    build_config_abspath = os.path.join(config_dir, build_config_filename)
    if not os.path.exists(build_config_abspath):
        config_dir = os.path.abspath(os.path.join(engine_dir, 'restricted', build_platform, os.path.relpath(script_dir, engine_dir)))
        build_config_abspath = os.path.join(config_dir, build_config_filename)
        if not os.path.exists(build_config_abspath):
            print('[ci_build] File: {} not found'.format(build_config_abspath))
            return None
    return script_dir, engine_dir, build_config_abspath


def load_config(build_config_abspath):
    with open(build_config_abspath) as f:
        return json.load(f)


def resolve_build_type(build_config_json, build_type, build_config_abspath):
    """Look up a build_type entry, printing the original diagnostic if absent."""
    build_type_config = build_config_json.get(build_type)
    if build_type_config is None:
        print('[ci_build] Build type {} was not found in {}'.format(build_type, build_config_abspath))
    return build_type_config


def is_pipe(build_type_config):
    return bool(build_type_config) and 'steps' in build_type_config and 'COMMAND' not in build_type_config


def list_types(build_config_json, tag):
    """Print build_type names, optionally filtered by TAGS membership."""
    for name in build_config_json:
        entry = build_config_json[name]
        if not isinstance(entry, dict):
            continue
        if tag is not None and tag not in (entry.get('TAGS') or []):
            continue
        print(name)
    return 0


def expand_pipe(build_config_json, build_type, skip, _depth=0, _seen=None):
    """Expand a pipe build_type into an ordered list of leaf Step objects.

    Recurses one-or-more levels for nested pipes (a step that is itself a pipe),
    guarding against infinite recursion via depth limit and a visited set.
    Steps listed in `skip` are omitted. Returns a list of Step or None on error.
    """
    if _seen is None:
        _seen = set()
    if _depth > MAX_PIPE_DEPTH:
        print('[ci_build] Pipe expansion exceeded max depth {} at {} (possible recursive pipe)'.format(MAX_PIPE_DEPTH, build_type))
        return None
    if build_type in _seen:
        print('[ci_build] Recursive pipe detected: {} references itself'.format(build_type))
        return None
    _seen = _seen | {build_type}

    entry = resolve_build_type(build_config_json, build_type, '(config)')
    if entry is None:
        return None

    steps = []
    for step_name in entry['steps']:
        if step_name in skip:
            print('[ci_build] Skipping build step {} (--skip)'.format(step_name))
            continue
        step_config = resolve_build_type(build_config_json, step_name, '(config)')
        if step_config is None:
            return None
        if is_pipe(step_config):
            nested = expand_pipe(build_config_json, step_name, skip, _depth + 1, _seen)
            if nested is None:
                return None
            steps.extend(nested)
        else:
            steps.append(Step(step_name, step_config))
    return steps


def run_leaf(build_type, build_type_config, script_dir, engine_dir, build_platform,
             build_config_abspath, pipeline_env=None):
    """Execute one leaf build type. Preserves the original single-command
    behavior exactly. `pipeline_env` (optional) is a dict of PIPELINE_ENV values
    merged into the environment for pipe execution parity (Jenkins GetBuildEnvVars);
    it is None for plain standalone leaf calls so behavior is unchanged there.
    """
    cwd_dir = os.getcwd()

    # Load the command to execute
    build_cmd = build_type_config['COMMAND']
    if build_cmd is None:
        print('[ci_build] Build type {} in {} is missing required COMMAND entry'.format(build_type, build_config_abspath))
        return -1

    build_params = build_type_config['PARAMETERS']
    # Parameters are optional, so we could have none

    # build_cmd is relative to the folder where this file is
    build_cmd_path = os.path.join(script_dir, 'Platform/{}/{}'.format(build_platform, build_cmd))
    if not os.path.exists(build_cmd_path):
        config_dir = os.path.abspath(os.path.join(engine_dir, 'restricted', build_platform, os.path.relpath(script_dir, engine_dir)))
        build_cmd_path = os.path.join(config_dir, build_cmd)
        if not os.path.exists(build_cmd_path):
            print('[ci_build] File: {} not found'.format(build_cmd_path))
            return -1

    print('[ci_build] Executing \"{}\"'.format(build_cmd_path))
    print('  cwd = {}'.format(cwd_dir))
    print('  engine_dir = {}'.format(engine_dir))
    print('  parameters:')
    env_params = os.environ.copy()
    env_params['ENGINE_DIR'] = engine_dir
    # PIPELINE_ENV merge (pipe parity): platform + step PIPELINE_ENV values are
    # part of the build environment in the Jenkins layer (GetBuildEnvVars).
    if pipeline_env:
        for k in pipeline_env:
            env_params[k] = pipeline_env[k]
    for v in build_params:
        if v[:6] == "FORCE:":
            env_params[v[6:]] = build_params[v] 
            print('    {} = {} (forced)'.format(v[6:], env_params[v[6:]]))
        else:
            existing_param = env_params.get(v)
            if not existing_param:
                env_params[v] = build_params[v]
            print('    {} = {} {}'.format(v, env_params[v], '(environment override)' if existing_param else ''))
    print('--------------------------------------------------------------------------------', flush=True)
    process_return = subprocess.run([build_cmd_path], cwd=cwd_dir, env=env_params, shell=True)
    print('--------------------------------------------------------------------------------')
    if process_return.returncode != 0:
        print('[ci_build] FAIL: Command {} returned {}'.format(build_cmd_path, process_return.returncode), flush=True)
        return process_return.returncode
    else:
        print('[ci_build] OK', flush=True)

    return 0


def run_pipe(build_config_json, build_type, script_dir, engine_dir, build_platform,
             build_config_abspath, stop_before=None, skip=None):
    """Expand and execute a pipe build type step-by-step, in order.

    - A blocking step failure aborts immediately and returns its non-zero code.
    - A NONBLOCKING_STEP failure is warned and skipped; the pipe is marked
      unstable but continues. If any nonblocking step failed and no blocking
      step failed, the pipe returns 0 (Jenkins marks the build UNSTABLE, not
      FAILURE; this script has no separate unstable exit code).
    - `stop_before` halts before the named step is executed (exclusive).
    """
    skip = skip or []
    steps = expand_pipe(build_config_json, build_type, skip)
    if steps is None:
        return -1

    # Platform-level PIPELINE_ENV applies to every step (Jenkins merges it first).
    platform_pipeline_env = build_config_json.get('PIPELINE_ENV') or {}

    print('[ci_build] Pipe {} expands to {} step(s): {}'.format(
        build_type, len(steps), ', '.join(s.name for s in steps)), flush=True)

    unstable = False
    for step in steps:
        if stop_before is not None and step.name == stop_before:
            print('[ci_build] Stopping before build step {} (--stop-before)'.format(step.name), flush=True)
            break

        print('[ci_build] === Pipe {} step: {} ==='.format(build_type, step.name), flush=True)

        # Merge platform-level then step-level PIPELINE_ENV (step overrides platform).
        merged_env = dict(platform_pipeline_env)
        merged_env.update(step.config.get('PIPELINE_ENV') or {})

        ret = run_leaf(step.name, step.config, script_dir, engine_dir, build_platform,
                       build_config_abspath, pipeline_env=merged_env)
        if ret != 0:
            if step.nonblocking:
                print('[ci_build] WARN: Build step {} failed ({}) but it is a non-blocking step in pipe {}; continuing'.format(
                    step.name, ret, build_type), flush=True)
                unstable = True
            else:
                print('[ci_build] FAIL: Blocking build step {} failed ({}) in pipe {}; aborting pipe'.format(
                    step.name, ret, build_type), flush=True)
                return ret

    if unstable:
        print('[ci_build] Pipe {} completed with non-blocking step failures (UNSTABLE)'.format(build_type), flush=True)
    else:
        print('[ci_build] Pipe {} completed'.format(build_type), flush=True)
    return 0


def build(build_config_filename, build_platform, build_type,
          stop_before=None, skip=None):
    paths = resolve_paths(build_config_filename, build_platform)
    if paths is None:
        return -1
    script_dir, engine_dir, build_config_abspath = paths

    build_config_json = load_config(build_config_abspath)

    build_type_config = resolve_build_type(build_config_json, build_type, build_config_abspath)
    if build_type_config is None:
        return -1

    if is_pipe(build_type_config):
        return run_pipe(build_config_json, build_type, script_dir, engine_dir, build_platform,
                        build_config_abspath, stop_before=stop_before, skip=skip)

    return run_leaf(build_type, build_type_config, script_dir, engine_dir, build_platform,
                    build_config_abspath)


if __name__ == "__main__":
    args = parse_args()

    if args.list_types:
        paths = resolve_paths(args.build_config_filename, args.build_platform)
        if paths is None:
            sys.exit(-1)
        _, _, build_config_abspath = paths
        build_config_json = load_config(build_config_abspath)
        sys.exit(list_types(build_config_json, args.tag))

    ret = build(args.build_config_filename, args.build_platform, args.build_type,
                stop_before=args.stop_before, skip=args.skip)
    sys.exit(ret)
