"""
Common gomatic Jobs patterns.

Responsibilities:
    Job patterns should ...
        * return the created job (or a dict of jobs, if there are more than one).
        * expect ArtifactLocations as input.
            * It's the responsibility of the stage/pipeline to ensure that the
              supplied artifacts don't refer to a job in the same stage.
        * use constants for job names.
        * not specify environment variables (leave that to tasks).
        * only be used for common groupings of tasks that need to be parameterized
          (task patterns can be used directly from stage patterns or pipeline patterns).
        * ``ensure`` the scm materials needed for any non-pattern task to function.
"""
import edxpipelines.constants as constants
import edxpipelines.patterns.tasks as tasks
from edxpipelines.utils import path_to_artifact


def generate_build_ami(stage,
                       edp,
                       app_repo_url,
                       configuration_secure_material,
                       configuration_internal_material,
                       playbook_path,
                       env_config,
                       version_tags=None,
                       **kwargs):
    """
    Generates a job for creating a new AMI.

    Args:
        stage (gomatic.gocd.pipelines.Stage): Stage to which this job belongs.
        edp (edxpipelines.utils.EDP): Tuple indicating environment, deployment, and play
            for which an AMI will be created.
        app_repo_url (str): App repo's URL.
        configuration_secure_material (gomatic.gomatic.gocd.materials.GitMaterial): Secure
            configuration material. Destination directory expected to be 'configuration-secure'.
        configuration_internal_material (gomatic.gomatic.gocd.materials.GitMaterial): Internal
            configuration material. Destination directory expected to be 'configuration-internal'.
        playbook_path (str): Path to the Ansible playbook to run when creating the AMI.
        env_config (dict): Environment-specific secure config.
        version_tags (dict): An optional {app_name: (repo, version), ...} dict that
            specifies what versions to tag the AMI with.

    Returns:
        gomatic.gocd.pipelines.Job
    """
    job = stage.ensure_job(constants.BUILD_AMI_JOB_NAME_TPL(edp))

    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_package_install(job, 'tubular')
    tasks.generate_target_directory(job)

    # Locate the base AMI.
    tasks.generate_base_ami_selection(
        job,
        env_config['aws_access_key_id'],
        env_config['aws_secret_access_key'],
        edp=edp
    )

    # Launch a new instance on which to build the AMI.
    tasks.generate_launch_instance(
        job,
        aws_access_key_id=env_config['aws_access_key_id'],
        aws_secret_access_key=env_config['aws_secret_access_key'],
        ec2_vpc_subnet_id=env_config['ec2_vpc_subnet_id'],
        ec2_security_group_id=env_config['ec2_security_group_id'],
        ec2_instance_profile_name=env_config['ec2_instance_profile_name'],
        variable_override_path=path_to_artifact(constants.BASE_AMI_OVERRIDE_FILENAME),
    )

    # Run the Ansible play for the service.
    tasks.generate_run_app_playbook(
        job,
        playbook_path,
        edp,
        app_repo_url,
        private_github_key=env_config['github_private_key'],
        hipchat_token=env_config['hipchat_token'],
        configuration_secure_dir=configuration_secure_material.destination_directory,
        configuration_internal_dir=configuration_internal_material.destination_directory,
        disable_edx_services='true',
        COMMON_TAG_EC2_INSTANCE='true',
        **kwargs
    )

    # Create an AMI from the instance.
    tasks.generate_create_ami(
        job,
        edp.play,
        edp.deployment,
        edp.environment,
        app_repo_url,
        configuration_secure_material.url,
        env_config['aws_access_key_id'],
        env_config['aws_secret_access_key'],
        path_to_artifact(constants.LAUNCH_INSTANCE_FILENAME),
        configuration_secure_version=constants.CONFIGURATION_SECURE_VERSION,
        hipchat_token=env_config['hipchat_token'],
        version_tags=version_tags,
        **kwargs
    )

    tasks.generate_ami_cleanup(job, env_config['hipchat_token'], runif='any')

    return job


def generate_deploy_ami(stage, ami_artifact_location, edp, env_config, has_migrations=True):
    """
    Generates a job for deploying an AMI. Migrations are applied as part of this job.

    Args:
        stage (gomatic.gocd.pipelines.Stage): Stage to which this job belongs.
        ami_artifact_location (edxpipelines.utils.ArtifactLocation): Where to find
            the AMI artifact to deploy.
        edp (edxpipelines.utils.EDP): Tuple indicating environment, deployment, and play
            to which the AMI belongs.
        env_config (dict): Environment-specific secure config.
        has_migrations (bool): Whether to generate Gomatic for applying migrations.

    Returns:
        gomatic.gocd.pipelines.Job
    """
    job = stage.ensure_job(constants.DEPLOY_AMI_JOB_NAME)

    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_package_install(job, 'tubular')
    tasks.generate_target_directory(job)

    # Retrieve the AMI ID from the upstream build stage.
    tasks.retrieve_artifact(ami_artifact_location, job)
    variable_override_path = path_to_artifact(ami_artifact_location.file_name)

    if has_migrations:
        tasks.generate_launch_instance(
            job,
            aws_access_key_id=env_config['aws_access_key_id'],
            aws_secret_access_key=env_config['aws_secret_access_key'],
            ec2_vpc_subnet_id=env_config['ec2_vpc_subnet_id'],
            ec2_security_group_id=env_config['ec2_security_group_id'],
            ec2_instance_profile_name=env_config['ec2_instance_profile_name'],
            variable_override_path=variable_override_path,
        )

        # SSH key used to access the instance needs specific permissions.
        job.ensure_task(tasks.bash_task(
            'chmod 600 {key_pem_path}',
            key_pem_path=path_to_artifact(constants.KEY_PEM_FILENAME)
        ))

        tasks.generate_run_migrations(
            job,
            application_user=edp.play,
            application_name=edp.play,
            application_path='/edx/app/{}'.format(edp.play),
            db_migration_user=constants.DB_MIGRATION_USER,
            db_migration_pass=env_config['db_migration_pass'],
        )

        tasks.generate_ami_cleanup(job, env_config['hipchat_token'], runif='any')

    tasks.generate_deploy_ami(
        job,
        variable_override_path,
        env_config['asgard_api_endpoints'],
        env_config['asgard_token'],
    )

    return job


def generate_rollback_asgs(stage, deployment_artifact_location, config):
    """
    Generates a job for rolling back ASGs (code).

    Args:
        stage (gomatic.gocd.pipelines.Stage): Stage to which this job belongs.
        deployment_artifact_location (edxpipelines.utils.ArtifactLocation): Where to find
            the AMI artifact to roll back.
        config (dict): Environment-independent secure config.

    Returns:
        gomatic.gocd.pipelines.Job
    """
    job = stage.ensure_job(constants.ROLLBACK_ASGS_JOB_NAME)

    tasks.generate_package_install(job, 'tubular')
    tasks.generate_target_directory(job)

    # Retrieve build info from the upstream deploy stage.
    tasks.retrieve_artifact(deployment_artifact_location, job)
    deployment_artifact_path = path_to_artifact(deployment_artifact_location.file_name)

    tasks.generate_rollback_asg(
        job,
        deployment_artifact_path,
        config['asgard_api_endpoints'],
        config['asgard_token'],
        config['aws_access_key_id'],
        config['aws_secret_access_key'],
    )

    return job


def generate_rollback_migrations(
        stage,
        application_user,
        application_name,
        application_path,
        db_migration_user,
        db_migration_pass,
        migration_info_location,
        inventory_location=None,
        instance_key_location=None,
        ami_artifact_location=None,
        env_config=None,
        sub_application_name=None
):
    """
    Generates a job for rolling back database migrations.

    Args:
        stage (gomatic.gocd.pipelines.Stage): Stage this job will be part of
        migration_info_location (edxpipelines.utils.ArtifactLocation): Location of
            the migration output to roll back
        inventory_location (edxpipelines.utils.ArtifactLocation): Location of the
            ansible inventory
        instance_key_location (edxpipelines.utils.ArtifactLocation): Location of
            the key used to ssh in to the instance
        ami_artifact_location (edxpipelines.utils.ArtifactLocation): AMI to use when
            launching instance used to roll back migrations.
        env_config (dict): Environment-specific secure config.
        sub_application_name (str): additional command to be passed to the migrate app {cms|lms}

    Returns:
        gomatic.gocd.pipelines.Job
    """
    job_name = constants.ROLLBACK_MIGRATIONS_JOB_NAME

    if sub_application_name is not None:
        job_name += '_{}'.format(sub_application_name)

    job = stage.ensure_job(job_name)

    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_target_directory(job)

    is_instance_launch_required = ami_artifact_location and env_config

    if is_instance_launch_required:
        # Retrieve the AMI ID from the upstream build stage.
        tasks.retrieve_artifact(ami_artifact_location, job)
        variable_override_path = path_to_artifact(ami_artifact_location.file_name)

        tasks.generate_launch_instance(
            job,
            aws_access_key_id=env_config['aws_access_key_id'],
            aws_secret_access_key=env_config['aws_secret_access_key'],
            ec2_vpc_subnet_id=env_config['ec2_vpc_subnet_id'],
            ec2_security_group_id=env_config['ec2_security_group_id'],
            ec2_instance_profile_name=env_config['ec2_instance_profile_name'],
            variable_override_path=variable_override_path,
        )
    else:
        # The instance was launched elsewhere. Fetch the Ansible inventory to
        # use in reaching the EC2 instance.
        tasks.retrieve_artifact(inventory_location, job)

        # Fetch the SSH key to use in reaching the EC2 instance.
        tasks.retrieve_artifact(instance_key_location, job)

    # SSH key used to access the instance needs specific permissions.
    job.ensure_task(tasks.bash_task(
        'chmod 600 {key_pem_path}',
        key_pem_path=path_to_artifact(constants.KEY_PEM_FILENAME)
    ))

    # Fetch the migration output.
    tasks.retrieve_artifact(migration_info_location, job)

    tasks.generate_migration_rollback(
        job=job,
        application_user=application_user,
        application_name=application_name,
        application_path=application_path,
        db_migration_user=db_migration_user,
        db_migration_pass=db_migration_pass,
        sub_application_name=sub_application_name,
    )

    # If an instance was launched as part of this job, clean it up.
    if is_instance_launch_required:
        tasks.generate_ami_cleanup(job, env_config['hipchat_token'], runif='any')

    return job


def generate_merge_release_candidate(
        pipeline, stage, token, org, repo, target_branch, head_sha,
        fast_forward_only, reference_repo=None,
):
    """
    Generates a job that is used to merge a Git source branch into a target branch,
    optionally ensuring that the merge is a fast-forward merge.

    Args:
        pipeline (gomatic.Pipeline): The pipeline containing ``stage``.
        stage (gomatic.Stage): The stage to add the job to
        org (str): Name of the github organization that holds the repository (e.g. edx)
        repo (str): Name of repository (e.g edx-platform)
        target_branch (str): Name of the branch into which to merge the source branch
        head_sha (str): commit SHA or environment variable holding the SHA to tag as the release
        token (str): the github token used to create all these things. Will be an env_var 'GIT_TOKEN'
        fast_forward_only (bool): If True, force a fast-forward merge or fail.

    Returns:
        gomatic.Job
    """
    merge_branch_job = stage.ensure_job(constants.GIT_MERGE_RC_BRANCH_JOB_NAME)
    tasks.generate_package_install(merge_branch_job, 'tubular')
    tasks.generate_target_directory(merge_branch_job)
    tasks.generate_merge_branch(
        pipeline,
        merge_branch_job,
        token,
        org,
        repo,
        head_sha,
        target_branch,
        fast_forward_only,
        reference_repo=reference_repo,
    )
    return merge_branch_job


def generate_tag_commit(stage, tag_id, deploy_artifact, org, repo, head_sha):
    """
    Generates a stage that is used to tag a release SHA.

    Args:
        stage (gomatic.Stage): The stage to add the job to
        tag_id (str): A name to use to disambiguate instances of the tagging job
        deploy_artifact (ArtifactLocation): Location of deployment artifact file
        org (str): Name of the github organization that holds the repository (e.g. edx)
        repo (str): Name of repository (e.g edx-platform)
        head_sha (str): commit SHA or environment variable holding the SHA to tag as the release

    Returns:
        gomatic.Job
    """
    # Generate a job/task which tags the head commit of the source branch.
    # Instruct the task to auto-generate tag name/message by not sending them in.
    tag_job = stage.ensure_job(constants.GIT_TAG_SHA_JOB_NAME_TPL(tag_id))
    tasks.generate_package_install(tag_job, 'tubular')

    if deploy_artifact:
        # Fetch the AMI-deployment artifact to extract deployment time.
        tasks.retrieve_artifact(deploy_artifact, tag_job, constants.ARTIFACT_PATH)

    tasks.generate_tag_commit(
        tag_job,
        org,
        repo,
        commit_sha=head_sha,
        deploy_artifact_filename=deploy_artifact.file_name if deploy_artifact else None
    )
