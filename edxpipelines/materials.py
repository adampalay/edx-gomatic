"""
A set of standard overridable material definitions.
"""
import re
from functools import partial
from six.moves import urllib

from gomatic import GitMaterial
from edxpipelines import constants


class InvalidGitRepoURL(ValueError):
    """
    Raised when repo URL can't be parsed.
    """
    pass


def github_id(material):
    """
    Return the github (org, repo) parsed from ``material``s url, or
    raise an InvalidGitRepoURL if none could be parsed.
    """
    clone_url = urllib.parse.urlparse(material.url).geturl()
    match = re.match(r'.*[:/](?P<org>[^/]*)/(?P<repo>[^/.]*)', clone_url)
    if not match:
        raise InvalidGitRepoURL(material.url)
    return match.group('org'), match.group('repo')


def material_envvar_name(material):
    """
    Return the material revision's GoCD environment variable name.
    """
    suffix = material.material_name if material.material_name else material.destination_directory
    return 'GO_REVISION_{suffix}'.format(suffix=suffix.replace('-', '_').upper())


def material_envvar_bash(material):
    """
    Return the material revision's GoCD environment variable in de-referenced bash format.
    """
    return '${{{}}}'.format(material_envvar_name(material))


def deployment_secure(deployment, branch=None, polling=True, destination_directory=None, ignore_patterns=None):
    """
    Initialize a GitMaterial representing a deployment's secure configuration repo.

    Args:
        deployment (str): Deployment for which to create the material (e.g., 'edx', 'edge')

    Returns:
        GitMaterial
    """
    return GitMaterial(
        url='git@github.com:edx-ops/{}-secure.git'.format(deployment),
        branch=branch,
        polling=polling,
        destination_directory=destination_directory or '{}-secure'.format(deployment),
        ignore_patterns=ignore_patterns or constants.MATERIAL_IGNORE_ALL_REGEX,
        shallow=True,
    )


def deployment_internal(deployment, branch=None, polling=True, destination_directory=None, ignore_patterns=frozenset()):
    """
    Initialize a GitMaterial representing a deployment's internal configuration repo.

    Args:
        deployment (str): Deployment for which to create the material (e.g., 'edx', 'edge')

    Returns:
        GitMaterial
    """
    return GitMaterial(
        url='git@github.com:edx/{}-internal.git'.format(deployment),
        branch=branch,
        polling=polling,
        destination_directory=destination_directory or '{}-internal'.format(deployment),
        ignore_patterns=ignore_patterns or constants.MATERIAL_IGNORE_ALL_REGEX,
        shallow=True,
    )


TUBULAR = partial(
    GitMaterial,
    url="https://github.com/edx/tubular",
    destination_directory="tubular",
    ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX,
    shallow=True,
)

CONFIGURATION = partial(
    GitMaterial,
    url="https://github.com/edx/configuration",
    polling=True,
    destination_directory="configuration",
    ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX,
    shallow=True,
)

EDX_PLATFORM = partial(
    GitMaterial,
    url="https://github.com/edx/edx-platform",
    branch="release-candidate",
    polling=True,
    destination_directory="edx-platform",
    ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX,
    shallow=True,
)

EDX_PLATFORM_PRIVATE = partial(
    GitMaterial,
    url="https://github.com/edx/edx-platform-private",
    branch="security-release",
    polling=True,
    destination_directory="edx-platform-private",
    ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX,
    shallow=True,
)

EDX_SECURE = partial(deployment_secure, 'edx')

EDGE_SECURE = partial(deployment_secure, 'edge')

EDX_MICROSITE = partial(
    GitMaterial,
    url="git@github.com:edx/edx-microsite.git",
    branch="release",
    polling=True,
    destination_directory="edx-microsite",
    ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX,
    shallow=True,
)

EDX_INTERNAL = partial(deployment_internal, 'edx')

EDGE_INTERNAL = partial(deployment_internal, 'edge')

EDX_MKTG = partial(
    GitMaterial,
    url="git@github.com:edx/edx-mktg.git",
    polling=True,
    destination_directory="edx-mktg",
    ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX,
)

ECOM_SECURE = partial(
    GitMaterial,
    url="git@github.com:edx-ops/ecom-secure",
    polling=True,
    destination_directory="ecom-secure",
    ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX,
)

EDX_ORA2 = partial(
    GitMaterial,
    url='https://github.com/edx/edx-ora2',
    polling=True,
    destination_directory='edx-ora2'
)
