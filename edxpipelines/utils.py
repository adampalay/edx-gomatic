"""
Utility functions needed by edX gomatic code.
"""
from collections import namedtuple, defaultdict
from copy import copy

import yaml

from edxpipelines import constants


class MergeConflict(Exception):
    """Raised when a merge conflict is found when trying to deep-merge dictionaries."""
    pass


ArtifactLocation = namedtuple(
    "ArtifactLocation",
    [
        'pipeline', 'stage', 'job', 'file_name', 'is_dir'
    ]
)


# This sets the is_dir argument for ArtifactLocation to False by default
ArtifactLocation.__new__.__defaults__ = (False,)


EDP = namedtuple('EDP', ['environment', 'deployment', 'play'])
EDP.__new__.__defaults__ = (None, None)


class ConfigMerger(object):
    """
    A read-only dict-like object that handles merging the various environment/deploy specific
    variable files provided to it. Reading a string will return the applicable global config value,
    while reading an EDP will return the specialized config dictionary.
    """
    def __init__(self, variable_files, env_variable_files, env_deploy_variable_files, cmd_line_vars):
        self.variable_files = variable_files
        self.env_variable_files = env_variable_files
        self.env_deploy_variable_files = env_deploy_variable_files
        self.cmd_line_vars = cmd_line_vars
        self.realized_configs = defaultdict(dict)

    def __getitem__(self, key):
        if isinstance(key, basestring):
            return self[None][key]

        if key in self.realized_configs:
            return self.realized_configs[key]

        if key is None:
            self.realized_configs[key] = merge_files_and_dicts(self.variable_files, self.cmd_line_vars)
        else:
            applicable_files = list(self.variable_files)
            applicable_files.extend(
                file
                for (env, file)
                in self.env_variable_files
                if env == key.environment
            )
            applicable_files.extend(
                file
                for (env_deploy, file)
                in self.env_deploy_variable_files
                # N.B. it's important that this is [...], rather than (...),
                # because lists and tuples don't compare equal
                if [key.environment, key.deployment] == env_deploy.split('-', 1)
            )

            self.realized_configs[key] = merge_files_and_dicts(applicable_files, self.cmd_line_vars)

        return self.realized_configs[key]

    def get(self, key, default=None):
        """
        Return the config value for key, unless it doesn't exist, in which case return default.
        """
        try:
            return self[key]
        except KeyError:
            return default

    def by_environments(self):
        """
        Yield all per-environment configs stored in this ConfigMerger.
        """
        envs = set(env for (env, _) in self.env_variable_files)
        envs.update(env_deploy.split('-', 1)[0] for (env_deploy, _) in self.env_deploy_variable_files)
        for env in envs:
            yield self[EDP(env)]


def dict_merge(*args):
    """
    Wraps the _dict_merge function. Pass this method a bunch of dictionaries and they will be merged.

    dict_merge(dict1, dict2, dict3, dict4)

    Args:
        *args: a list of dictionaries

    Returns:
        dict: a merged dict

    """
    if len(args) < 1:
        return {}
    elif len(args) == 1:
        return args[0]

    return reduce(_deep_dict_merge, args)


def _deep_dict_merge(a, b):
    """
    Deep merges 2 dictionaries together.

    Args:
        a (dict): first dictionary
        b (dict): second dictionary

    Returns:
        dict: a and b merged in to a single dict

    Raises:
        TypeError: if a and b are not both dicts
        MergeConflict: if a key exists with different values between the two dictionaries
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        raise TypeError("Both arguments must be a dict. Can not merge {} and {}".format(a.__class__, b.__class__))

    ret_dict = copy(a)

    for key in b:
        if key in ret_dict:
            if isinstance(ret_dict[key], dict) and isinstance(b[key], dict):
                ret_dict[key] = _deep_dict_merge(ret_dict[key], b[key])
            elif ret_dict[key] == b[key]:
                pass  # same leaf value
            else:
                raise MergeConflict(
                    'Conflict at key: {} . A value: {} -- B value: {}'.format(
                        key, ret_dict[key], b[key]
                    )
                )
        else:
            ret_dict[key] = b[key]
    return ret_dict


def load_yaml_from_file(filename):
    """
    Loads a yaml file from disk

    Args:
        filename: path to the yaml file to open

    Returns:
        dict: representing the yaml in the file
    """
    with open(filename, 'r') as stream:
        return yaml.safe_load(stream)


def merge_files_and_dicts(file_paths, dicts):
    """
    Merges together yaml files with key/value pairs with dictonaries. Useful for parsing the inputs from the command
    line of a pipeline script

    Args:
        file_paths (list<str>): a list of strings to the input yaml files
        dicts (list<dict>): A list of dictionaries (can also be a list of (k,v) tuples)

    Returns:
        dict: all the parameters merged

    Raises:
        TypeError: if a and b are not both dicts
        MergeConflict: if a key exists with different values between the two dictionaries
    """
    file_variables = [load_yaml_from_file(f) for f in file_paths]
    dict_vars = []
    for dict_ in dicts:
        if isinstance(dict_, list):
            # try to convert to a dict as it could be a list of tuples from click
            dict_vars.append({k: v for k, v in dict_})
        elif isinstance(dict_, dict):
            dict_vars.append(dict_)
        else:
            raise ValueError("dicts contains an instance that is not a dictionary {}".format(dict_.__class__))

    file_variables.extend(dict_vars)
    return dict_merge(*file_variables)


def path_to_artifact(filename, artifact_path=constants.ARTIFACT_PATH):
    """
    Construct the path to the named artifact, relative to the base directory for job execution.

    Args:
        filename (str): Name of the artifact.

    Returns:
        str
    """
    return '{}/{}'.format(artifact_path, filename)
