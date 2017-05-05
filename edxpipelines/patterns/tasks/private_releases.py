"""
Task patterns for private releases.
"""

from gomatic import BuildArtifact

from .common import tubular_task, generate_target_directory
from ... import constants


def generate_create_private_release_candidate(
        job, git_token, source_repo, source_base_branch, source_branch, target_repo,
        target_base_branch, target_branch, target_reference_repo=None,
):
    """
    Add a task that creates a new release-candidate by merging a set of approved
    PRs in the target repo.

    Arguments:
        job: The gomatic.Job to add this task to
        git_token: The token to authenticate with github
        source_repo: A tuple of (user, repo) specifying the repository to
            base the new branch from.
        source_base_branch: A branch name. Any PRs in target_repo that have
            been merged into this branch will be excluded.
        source_branch: A branch name. This is the branch that the PRs
            will be merged onto.
        target_repo: A tuple of (user, repo) specifying the repository to
            merge PRs from.
        target_base_branch: A branch name. This is the branch that PRs must target
            in order to be included in the merge.
        target_branch: A branch name. This is the branch that will be created by the
            merge (and will be force-pushed into target_repo).
        target_reference_repo: A path to an existing local checkout of the target_repo
            that can be used to speed up fresh clones.
    """
    # Gomatic forgot to expose ensure_unencrypted_secure_environment_variables,
    # so we have to reach behind the mangled name to get it ourselves.
    thing_with_environment_variables = job._Job__thing_with_environment_variables  # pylint: disable=protected-access
    thing_with_environment_variables.ensure_unencrypted_secure_environment_variables({
        'GIT_TOKEN': git_token,
    })

    job.ensure_environment_variables({
        'GIT_AUTHOR_NAME': 'edx-pipeline-bot',
        'GIT_AUTHOR_EMAIL': 'admin+edx-pipeline-bot@edx.org',
        'GIT_COMMITTER_NAME': 'edx-pipeline-bot',
        'GIT_COMMITTER_EMAIL': 'admin+edx-pipeline-bot@edx.org',
    })

    generate_target_directory(job)

    artifact_path = '{}/{}'.format(
        constants.ARTIFACT_PATH,
        constants.PRIVATE_RC_FILENAME
    )

    args = [
        '--token', '$GIT_TOKEN',
        '--target-repo', target_repo[0], target_repo[1],
        '--target-base-branch', target_base_branch,
        '--source-repo', source_repo[0], source_repo[1],
        '--source-base-branch', source_base_branch,
        '--target-branch', target_branch,
        '--source-branch', source_branch,
        '--out-file', artifact_path,
        '--sha-variable', 'edx_platform_version',
        '--repo-variable', 'edx_platform_repo',
    ]

    if target_reference_repo:
        args.extend(['--target-reference-repo', target_reference_repo])

    job.ensure_task(tubular_task(
        'merge-approved-prs',
        args,
        working_dir=None
    ))

    job.ensure_artifacts(set([BuildArtifact(artifact_path)]))


def generate_private_public_create_pr(
        job, git_token, private_repo, private_source_branch,
        public_repo, public_target_branch, private_reference_repo=None
):
    """
    Add a task that creates a pull request merging the private branch into the public repo
    with a specified public base branch.

    Arguments:
        job: The gomatic.Job to add this task to
        git_token: The token to authenticate with github
        private_repo: A tuple of (user, repo) specifying the private repository to
            base the new branch from.
        private_source_branch: A branch name. This is the branch that is pushed to
            the public repo for merging into the public target branch.
        public_repo: A tuple of (user, repo) specifying the repository to
            merge PRs from.
        public_target_branch: A branch name. This is the public branch which will
            be the base of the created PR.
        private_reference_repo: A path to an existing local checkout of the private_repo
            that can be used to speed up fresh clones.
    """
    # Gomatic forgot to expose ensure_unencrypted_secure_environment_variables,
    # so we have to reach behind the mangled name to get it ourselves.
    thing_with_environment_variables = job._Job__thing_with_environment_variables  # pylint: disable=protected-access
    thing_with_environment_variables.ensure_unencrypted_secure_environment_variables({
        'GIT_TOKEN': git_token,
    })

    generate_target_directory(job)

    artifact_path = '{}/{}'.format(
        constants.ARTIFACT_PATH,
        constants.PRIVATE_PUBLIC_PR_FILENAME
    )

    args = [
        '--token', '$GIT_TOKEN',
        '--private_org', private_repo[0],
        '--private_repo', private_repo[1],
        '--private_source_branch', private_source_branch,
        '--public_org', public_repo[0],
        '--public_repo', public_repo[1],
        '--public_source_branch', public_target_branch,
        '--output_file', artifact_path,
    ]

    if private_reference_repo:
        args.extend(['--reference_repo', private_reference_repo])

    job.ensure_task(tubular_task(
        'create_private_to_public_pr.py',
        args,
        working_dir=None
    ))

    job.ensure_artifacts(set([BuildArtifact(artifact_path)]))


def generate_public_private_merge(
        job, git_token, private_repo, private_target_branch,
        public_repo, public_source_branch, public_reference_repo=None
):
    """
    Add a task that creates a pull request merging the private branch into the public repo
    with a specified public base branch.

    Arguments:
        job: The gomatic.Job to add this task to
        git_token: The token to authenticate with github
        private_repo: A tuple of (user, repo) specifying the private repository to
            which the branch push will happen.
        private_target_branch: A branch name. This is the private branch to which the public
            branch is pushed to keep it in sync with the public branch.
        public_repo: A tuple of (user, repo) specifying the repository from which
            the public branch will be pushed.
        public_source_branch: A branch name. This is the public branch which will
            be pushed to the private branch.
        public_reference_repo: A path to an existing local checkout of the public_repo
            that can be used to speed up fresh clones.
    """
    # Gomatic forgot to expose ensure_unencrypted_secure_environment_variables,
    # so we have to reach behind the mangled name to get it ourselves.
    thing_with_environment_variables = job._Job__thing_with_environment_variables  # pylint: disable=protected-access
    thing_with_environment_variables.ensure_unencrypted_secure_environment_variables({
        'GIT_TOKEN': git_token,
    })

    generate_target_directory(job)

    artifact_path = '{}/{}'.format(
        constants.ARTIFACT_PATH,
        constants.PUBLIC_PRIVATE_PUSH_FILENAME
    )

    args = [
        '--token', '$GIT_TOKEN',
        '--private_org', private_repo[0],
        '--private_repo', private_repo[1],
        '--private_target_branch', private_target_branch,
        '--public_org', public_repo[0],
        '--public_repo', public_repo[1],
        '--public_source_branch', public_source_branch,
        '--output_file', artifact_path,
    ]

    if public_reference_repo:
        args.extend(['--reference_repo', public_reference_repo])

    job.ensure_task(tubular_task(
        'push_public_to_private.py',
        args,
        working_dir=None
    ))
