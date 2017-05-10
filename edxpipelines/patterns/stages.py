"""
Common gomatic stages.

Responsibilities:
    Stage patterns should ...
        * use constants for stage names.
        * not specify environment variables (leave that to tasks).
        * use explicit arguments (rather than a configuration dictionary).
        * return the created stage (or a list/namedtuple if there are multiple stages).
        * only be used for common groupings of jobs/tasks that need to be parameterized
          (task and job patterns can be used directly from pipeline patterns).
        * expect ArtifactLocations as input.
            * It's the responsibility of the calling pipeline to ensure that the
              supplied artifacts don't refer to the current stage.
        * ``ensure`` the scm materials needed for any non-pattern task to function.
"""

from gomatic import ExecTask, BuildArtifact, FetchArtifactTask

from edxpipelines import constants
from edxpipelines.patterns import (
    tasks,
    jobs
)
from edxpipelines.utils import ArtifactLocation
from edxpipelines.materials import github_id, material_envvar_bash


def generate_asg_cleanup(pipeline,
                         asgard_api_endpoints,
                         asgard_token,
                         aws_access_key_id,
                         aws_secret_access_key,
                         manual_approval=False):
    """
    Generates stage which calls the ASG cleanup script.

    Args:
        pipeline (gomatic.Pipeline):
        asgard_api_endpoints (str): canonical URL for asgard.
        asgard_token (str): Asgard token to use for authentication
        aws_access_key_id (str): AWS key ID for auth
        aws_secret_access_key (str): AWS secret key for auth
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    pipeline.ensure_environment_variables({'ASGARD_API_ENDPOINTS': asgard_api_endpoints})
    pipeline.ensure_encrypted_environment_variables(
        {
            'ASGARD_API_TOKEN': asgard_token,
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key,
        }
    )

    stage = pipeline.ensure_stage("ASG-Cleanup-Stage")
    if manual_approval:
        stage.set_has_manual_approval()

    job = stage.ensure_job("Cleanup-ASGS")
    tasks.generate_package_install(job, 'tubular')
    job.add_task(ExecTask(
        [
            'cleanup-asgs.py'
        ],
        working_dir="tubular"
    ))

    return stage


def generate_launch_instance(
        pipeline,
        aws_access_key_id,
        aws_secret_access_key,
        ec2_vpc_subnet_id,
        ec2_security_group_id,
        ec2_instance_profile_name,
        base_ami_id,
        manual_approval=False,
        ec2_region=constants.EC2_REGION,
        ec2_instance_type=constants.EC2_INSTANCE_TYPE,
        ec2_timeout=constants.EC2_LAUNCH_INSTANCE_TIMEOUT,
        ec2_ebs_volume_size=constants.EC2_EBS_VOLUME_SIZE,
        base_ami_id_artifact=None
):
    """
    Pattern to launch an AMI. Generates 3 artifacts:
        key.pem             - Private key material generated for this instance launch
        launch_info.yml     - yaml file that contains information about the instance launched
        ansible_inventory   - a list of private aws IP addresses that can be fed in to ansible to run playbooks

        Please check here for further information:
        https://github.com/edx/configuration/blob/master/playbooks/continuous_delivery/launch_instance.yml

    Args:
        pipeline (gomatic.Pipeline):
        aws_access_key_id (str): AWS key ID for auth
        aws_secret_access_key (str): AWS secret key for auth
        ec2_vpc_subnet_id (str):
        ec2_security_group_id (str):
        ec2_instance_profile_name (str):
        base_ami_id (str): the ami-id used to launch the instance
        manual_approval (bool): Should this stage require manual approval?
        ec2_region (str):
        ec2_instance_type (str):
        ec2_timeout (str):
        ec2_ebs_volume_size (str):
        base_ami_id_artifact (edxpipelines.utils.ArtifactLocation): overrides the base_ami_id and will force
                                                                       the task to run with the AMI built up stream.

    Returns:

    """
    stage = pipeline.ensure_stage(constants.LAUNCH_INSTANCE_STAGE_NAME)

    if manual_approval:
        stage.set_has_manual_approval()

    # Install the requirements.
    job = stage.ensure_job(constants.LAUNCH_INSTANCE_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')
    tasks.generate_requirements_install(job, 'configuration')

    if base_ami_id_artifact:
        tasks.retrieve_artifact(base_ami_id_artifact, job, constants.ARTIFACT_PATH)

    # Create the instance-launching task.
    tasks.generate_launch_instance(
        job,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        ec2_vpc_subnet_id=ec2_vpc_subnet_id,
        ec2_security_group_id=ec2_security_group_id,
        ec2_instance_profile_name=ec2_instance_profile_name,
        base_ami_id=base_ami_id,
        ec2_region=ec2_region,
        ec2_instance_type=ec2_instance_type,
        ec2_timeout=ec2_timeout,
        ec2_ebs_volume_size=ec2_ebs_volume_size,
        variable_override_path='{}/{}'.format(
            constants.ARTIFACT_PATH, base_ami_id_artifact.file_name
        ) if base_ami_id_artifact else None,
    )

    tasks.generate_ensure_python2(job)

    return stage


def generate_run_play(pipeline,
                      playbook_with_path,
                      edp,
                      app_repo,
                      private_github_key='',
                      hipchat_token='',
                      hipchat_room=constants.HIPCHAT_ROOM,
                      manual_approval=False,
                      configuration_secure_dir=constants.PRIVATE_CONFIGURATION_LOCAL_DIR,
                      configuration_internal_dir=constants.INTERNAL_CONFIGURATION_LOCAL_DIR,
                      override_artifacts=None,
                      timeout=None,
                      **kwargs):
    """
    TODO: This currently runs from the configuration/playbooks/continuous_delivery/ directory. Need to figure out how to
    pass in a configuration file to ansible-play correctly. TE-1608

    Assumes:
        - generate_launch_instance stage was used launch the instance preceding this stage.
        - Requires the ansible_inventory and key.pem files to be in the constants.ARTIFACT_DIRECTORY path
        - Play is run from the constants.PUBLIC_CONFIGURATION_DIR
        - Play is run using the constants.ANSIBLE_CONFIG configuration file

    Args:
        pipeline (gomatic.Pipeline):
        playbook_with_path (str):
        play (str):
        deployment (str):
        edx_environment (str):
        app_repo (str) :
        private_github_key (str):
        hipchat_token (str):
        hipchat_room (str):
        manual_approval (bool):
        configuration_secure_dir (str): The secure config directory to use for this play.
        timeout (int): GoCD job level inactivity timeout setting.
        **kwargs (dict):
            k,v pairs:
                k: the name of the option to pass to ansible
                v: the value to use for this option

    Returns:
        gomatic.Stage
    """
    stage = pipeline.ensure_stage(constants.RUN_PLAY_STAGE_NAME)
    if manual_approval:
        stage.set_has_manual_approval()

    # Install the requirements.
    job = stage.ensure_job(constants.RUN_PLAY_JOB_NAME)
    if timeout:
        job.timeout = str(timeout)

    tasks.generate_package_install(job, 'tubular')
    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_target_directory(job)

    for file_name in (
            constants.KEY_PEM_FILENAME,
            constants.LAUNCH_INSTANCE_FILENAME,
            constants.ANSIBLE_INVENTORY_FILENAME
    ):
        tasks.retrieve_artifact(
            ArtifactLocation(
                pipeline.name,
                constants.LAUNCH_INSTANCE_STAGE_NAME,
                constants.LAUNCH_INSTANCE_JOB_NAME,
                file_name,
            ),
            job,
            constants.ARTIFACT_PATH
        )

    override_files = []
    if not override_artifacts:
        override_artifacts = []

    for artifact in override_artifacts:
        tasks.retrieve_artifact(artifact, job, constants.ARTIFACT_PATH)
        override_files.append('{}/{}'.format(constants.ARTIFACT_PATH, artifact.file_name))

    tasks.generate_run_app_playbook(
        job=job,
        playbook_with_path=playbook_with_path,
        edp=edp,
        app_repo=app_repo,
        private_github_key=private_github_key,
        hipchat_token=hipchat_token,
        hipchat_room=hipchat_room,
        configuration_secure_dir=configuration_secure_dir,
        configuration_internal_dir=configuration_internal_dir,
        override_files=override_files,
        **kwargs)
    return stage


def generate_create_ami_from_instance(pipeline,
                                      edp,
                                      app_repo,
                                      aws_access_key_id,
                                      aws_secret_access_key,
                                      ami_creation_timeout=3600,
                                      ami_wait='yes',
                                      cache_id='',
                                      artifact_path=constants.ARTIFACT_PATH,
                                      hipchat_token='',
                                      hipchat_room=constants.HIPCHAT_ROOM,
                                      manual_approval=False,
                                      version_tags=None,
                                      **kwargs):
    """
    Generates an artifact ami.yml:
        ami_id: ami-abcdefg
        ami_message: AMI creation operation complete
        ami_state: available

    Args:
        pipeline (gomatic.Pipeline):
        edp (EDP):
        app_repo (str):
        configuration_secure_repo (str):
        aws_access_key_id (str):
        aws_secret_access_key (str):
        configuration_repo (str):
        ami_creation_timeout (str):
        ami_wait (str):
        cache_id (str):
        artifact_path (str):
        hipchat_room (str):
        manual_approval (bool):
        version_tags (dict): An optional {app_name: (repo, version), ...} dict that
            specifies what versions to tag the AMI with.
        **kwargs (dict):
            k,v pairs:
                k: the name of the option to pass to ansible
                v: the value to use for this option

    Returns:
        gomatic.Stage
    """
    stage = pipeline.ensure_stage(constants.BUILD_AMI_STAGE_NAME)
    if manual_approval:
        stage.set_has_manual_approval()

    # Install the requirements.
    job = stage.ensure_job(constants.BUILD_AMI_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')
    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_target_directory(job)

    launch_info_artifact = ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.LAUNCH_INSTANCE_FILENAME,
    )

    tasks.retrieve_artifact(launch_info_artifact, job)

    # Create an AMI from the instance
    tasks.generate_create_ami(
        job=job,
        play=edp.play,
        deployment=edp.deployment,
        edx_environment=edp.environment,
        app_repo=app_repo,
        launch_info_path='{}/{}'.format(constants.ARTIFACT_PATH, constants.LAUNCH_INSTANCE_FILENAME),
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        ami_creation_timeout=ami_creation_timeout,
        ami_wait=ami_wait,
        cache_id=cache_id,
        artifact_path=artifact_path,
        hipchat_token=hipchat_token,
        hipchat_room=hipchat_room,
        version_tags=version_tags,
        **kwargs)

    return stage


def generate_deploy_ami(
        pipeline,
        asgard_api_endpoints,
        asgard_token,
        aws_access_key_id,
        aws_secret_access_key,
        upstream_ami_artifact=None,
        manual_approval=True
):
    """
    Generates a stage which deploys an AMI via Asgard.

    if the variable upstream_ami_artifact is set, information about which AMI to deploy will be pulled
    from this pipeline/stage/file.

    if upstream_ami_artifact is not set, the environment variable AMI_ID will be used to determine what
    AMI to deploy

    Args:
        pipeline (gomatic.Pipeline):
        asgard_api_endpoints (str): canonical URL for asgard.
        asgard_token (str):
        aws_access_key_id (str):
        aws_secret_access_key (str):
        upstream_ami_artifact (ArtifactLocation): The location of yaml artifact that has the `ami_id`
        manual_approval (bool): Should this stage require manual approval?
    Returns:
        gomatic.Stage
    """
    pipeline.ensure_environment_variables(
        {
            'ASGARD_API_ENDPOINTS': asgard_api_endpoints,
            'WAIT_SLEEP_TIME': constants.TUBULAR_SLEEP_WAIT_TIME
        }
    ).ensure_encrypted_environment_variables(
        {
            'ASGARD_API_TOKEN': asgard_token,
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key,
        }
    )

    stage = pipeline.ensure_stage(constants.DEPLOY_AMI_STAGE_NAME)
    if manual_approval:
        stage.set_has_manual_approval()
    job = stage.ensure_job(constants.DEPLOY_AMI_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')
    # Make the artifact directory if it does not exist
    job.add_task(ExecTask(
        [
            '/bin/bash',
            '-c',
            'mkdir -p ../{}'.format(constants.ARTIFACT_PATH),
        ],
        working_dir="tubular"
    ))

    # Setup the deployment output file
    artifact_path = '{}/{}'.format(
        constants.ARTIFACT_PATH,
        constants.DEPLOY_AMI_OUT_FILENAME
    )
    job.ensure_artifacts(set([BuildArtifact(artifact_path)]))

    deploy_command =\
        'asgard-deploy.py ' \
        '--out_file ../{} '.format(artifact_path)

    if upstream_ami_artifact:
        tasks.retrieve_artifact(upstream_ami_artifact, job, 'tubular')
        deploy_command += '--config-file {}'.format(upstream_ami_artifact.file_name)

    else:
        pipeline.ensure_environment_variables({'AMI_ID': None})
        deploy_command += '--ami_id $AMI_ID'

    # Execute the deployment script
    job.add_task(ExecTask(['/bin/bash', '-c', deploy_command], working_dir="tubular"))
    return stage


def generate_run_migrations(pipeline,
                            db_migration_pass,
                            inventory_location,
                            instance_key_location,
                            launch_info_location,
                            application_user,
                            application_name,
                            application_path,
                            duration_threshold=None,
                            from_address=None,
                            to_addresses=None,
                            sub_application_name=None,
                            manual_approval=False):
    """
    Generate the stage that applies/runs migrations.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        db_migration_pass (str): Password for the DB user used to run migrations.
        inventory_location (ArtifactLocation): Location of inventory containing the IP
            address of the EC2 instance, for fetching.
        instance_key_location (ArtifactLocation): Location of SSH key used to access the
            EC2 instance, for fetching.
        launch_info_location (ArtifactLocation): Location of the launch_info.yml file for fetching
        application_user (str): Username to use while running the migrations
        application_name (str): Name of the application (e.g. edxapp, ecommerce, etc...)
        application_path (str): path of the application installed on the target machine
        duration_threshold (int): Threshold in seconds over which a migration duration will be alerted.
        from_address (str): Any migration duration email alert will be from this address.
        to_addresses (list(str)): List of To: addresses for migration duration email alerts.
        sub_application_name (str): any sub application to insert in to the migrations commands {cms|lms}
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    pipeline.ensure_environment_variables(
        {
            'ARTIFACT_PATH': constants.ARTIFACT_PATH,
            'ANSIBLE_CONFIG': constants.ANSIBLE_CONTINUOUS_DELIVERY_CONFIG
        }
    )
    if duration_threshold:
        pipeline.ensure_environment_variables(
            {
                'MAX_EMAIL_TRIES': constants.MAX_EMAIL_TRIES
            }
        )

    if sub_application_name is not None:
        stage_name = "{}_{}".format(constants.APPLY_MIGRATIONS_STAGE, sub_application_name)
    else:
        stage_name = constants.APPLY_MIGRATIONS_STAGE
    stage = pipeline.ensure_stage(stage_name)

    if manual_approval:
        stage.set_has_manual_approval()
    job = stage.ensure_job(constants.APPLY_MIGRATIONS_JOB)
    tasks.generate_package_install(job, 'tubular')

    # Fetch the Ansible inventory to use in reaching the EC2 instance.
    tasks.retrieve_artifact(inventory_location, job, constants.ARTIFACT_PATH)

    # Fetch the SSH key to use in reaching the EC2 instance.
    tasks.retrieve_artifact(instance_key_location, job, constants.ARTIFACT_PATH)

    # ensure the target directoy exists
    tasks.generate_target_directory(job)

    # fetch the launch_info.yml
    tasks.retrieve_artifact(launch_info_location, job, constants.ARTIFACT_PATH)

    # The SSH key used to access the EC2 instance needs specific permissions.
    job.add_task(
        ExecTask(
            ['/bin/bash', '-c', 'chmod 600 {}'.format(instance_key_location.file_name)],
            working_dir=constants.ARTIFACT_PATH
        )
    )

    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_run_migrations(
        job,
        application_user,
        application_name,
        application_path,
        constants.DB_MIGRATION_USER,
        db_migration_pass,
        sub_application_name
    )

    if duration_threshold:
        tasks.generate_check_migration_duration(
            job,
            constants.MIGRATION_RESULT_FILENAME,
            duration_threshold,
            from_address,
            to_addresses
        )

    return stage


def generate_rollback_migrations(pipeline,
                                 edp,
                                 db_migration_pass,
                                 inventory_location,
                                 instance_key_location,
                                 migration_info_location,
                                 application_user,
                                 application_name,
                                 application_path,
                                 sub_application_name=None,
                                 manual_approval=False):
    """
    Generate the stage that applies/runs migrations.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        edp (EDP): EDP that this stage will roll back
        db_migration_pass (str): Password for the DB user used to run migrations.
        inventory_location (ArtifactLocation): Location of inventory containing the IP
            address of the EC2 instance, for fetching.
        instance_key_location (ArtifactLocation): Location of SSH key used to access the EC2 instance, for fetching.
        migration_info_location (ArtifactLocation): Location of the migration files
        application_user (str): Username to use while running the migrations
        application_name (str): Name of the application (e.g. edxapp, ecommerce, etc...)
        application_path (str): path of the application installed on the target machine
        sub_application_name (str): any sub application to insert in to the migrations commands {cms|lms}
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    stage_name = constants.ROLLBACK_MIGRATIONS_STAGE_NAME
    if sub_application_name is not None:
        stage_name += "_{}".format(sub_application_name)
    stage = pipeline.ensure_stage(stage_name)

    if manual_approval:
        stage.set_has_manual_approval()

    jobs.generate_rollback_migrations(
        stage,
        edp,
        application_user=application_user,
        application_name=application_name,
        application_path=application_path,
        db_migration_user=constants.DB_MIGRATION_USER,
        db_migration_pass=db_migration_pass,
        migration_info_location=migration_info_location,
        inventory_location=inventory_location,
        instance_key_location=instance_key_location,
        sub_application_name=sub_application_name,
    )

    return stage


def generate_terminate_instance(pipeline,
                                instance_info_location,
                                aws_access_key_id,
                                aws_secret_access_key,
                                hipchat_token,
                                ec2_region=constants.EC2_REGION,
                                artifact_path=constants.ARTIFACT_PATH,
                                runif='any',
                                manual_approval=False):
    """
    Generate the stage that terminates an EC2 instance.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        instance_info_location (ArtifactLocation): Location of YAML file containing
            instance info from the AMI-building stage, for fetching.
        runif (str): one of ['passed', 'failed', 'any'] Default: any - controls when the
            stage's terminate task is triggered in the pipeline
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage

    """
    pipeline.ensure_encrypted_environment_variables(
        {
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key,
        }
    )
    pipeline.ensure_environment_variables(
        {
            'ARTIFACT_PATH': artifact_path,
            'EC2_REGION': ec2_region,
        }
    )

    stage = pipeline.ensure_stage(constants.TERMINATE_INSTANCE_STAGE_NAME)
    if manual_approval:
        stage.set_has_manual_approval()

    # Fetch the instance info to use in reaching the EC2 instance.
    job = stage.ensure_job(constants.TERMINATE_INSTANCE_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')
    tasks.generate_requirements_install(job, 'configuration')
    tasks.retrieve_artifact(instance_info_location, job, constants.ARTIFACT_PATH)

    tasks.generate_ami_cleanup(job, hipchat_token, runif=runif)

    return stage


def generate_cleanup_dangling_instances(pipeline,
                                        aws_access_key_id,
                                        aws_secret_access_key,
                                        name_match_pattern,
                                        max_run_hours,
                                        skip_if_tag,
                                        ec2_region=constants.EC2_REGION,
                                        runif='any',
                                        manual_approval=False):
    """
    Generate the stage that terminates all ec2 instances runnning for longer than a specified time.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        aws_access_key_id (str): The AWS access key ID
        aws_secret_access_key (str): The AWS secret access key
        name_match_pattern (str): pattern to match the name of the instances that should be terminated
        max_run_hours (int): number of hourse that should pass before terminating matching instances
        skip_if_tag (str): if this tag exists on an instance, it will not be terminated
        ec2_region (str): the EC2 region to connect
        runif (str): one of ['passed', 'failed', 'any'] Default: any - controls when the
            stage's terminate task is triggered in the pipeline
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage

    """
    pipeline.ensure_encrypted_environment_variables(
        {
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key,
        }
    )

    stage = pipeline.ensure_stage(constants.INSTANCE_JANITOR_STAGE_NAME)
    if manual_approval:
        stage.set_has_manual_approval()

    # Fetch the instance info to use in reaching the EC2 instance.
    job = stage.ensure_job(constants.INSTANCE_JANITOR_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')

    tasks.generate_janitor_instance_cleanup(job,
                                            name_match_pattern,
                                            max_run_hours,
                                            skip_if_tag,
                                            ec2_region,
                                            runif=runif)

    return stage


def generate_rollback_asg_stage(
        pipeline,
        asgard_api_endpoints,
        asgard_token,
        aws_access_key_id,
        aws_secret_access_key,
        hipchat_token,
        hipchat_room,
        deploy_file_location
):
    """
    Generates a stage which performs rollback to a previous ASG (or ASGs) via Asgard.
    If the previous ASG (or ASGs) fail health checks for some reason, a new ASGs with
    the provided AMI ID is created and used as the rollback ASG(s).
    This stage *always* requires manual approval.

    Args:
        pipeline (gomatic.Pipeline):
        asgard_api_endpoints (str): canonical URL for asgard.
        asgard_token (str):
        aws_access_key_id (str):
        aws_secret_access_key (str):
        deploy_file_location (ArtifactLocation): The location of YAML artifact from the previous deploy
            that has the previous ASG info along with `ami_id`, for rollback/re-deploy respectively.
    Returns:
        gomatic.Stage
    """
    pipeline.ensure_environment_variables(
        {
            'ASGARD_API_ENDPOINTS': asgard_api_endpoints,
            'HIPCHAT_ROOM': hipchat_room,
        }
    )
    pipeline.ensure_encrypted_environment_variables(
        {
            'ASGARD_API_TOKEN': asgard_token,
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key,
            'HIPCHAT_TOKEN': hipchat_token,
        }
    )

    stage = pipeline.ensure_stage(constants.ROLLBACK_ASGS_STAGE_NAME)
    # Important: Do *not* automatically rollback! Always manual...
    stage.set_has_manual_approval()
    job = stage.ensure_job(constants.ROLLBACK_ASGS_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')

    tasks.retrieve_artifact(deploy_file_location, job, 'tubular')

    job.add_task(ExecTask(
        [
            '/bin/bash',
            '-c',
            'mkdir -p ../target',
        ],
        working_dir="tubular"
    ))

    artifact_path = '{}/{}'.format(
        constants.ARTIFACT_PATH,
        constants.ROLLBACK_AMI_OUT_FILENAME
    )
    job.ensure_artifacts(set([BuildArtifact(artifact_path)]))

    job.add_task(ExecTask(
        [
            'rollback_asg.py',
            '--config_file', deploy_file_location.file_name,
            '--out_file', '../{}'.format(artifact_path),
        ],
        working_dir="tubular"
    ))
    return stage


def generate_armed_stage(pipeline, stage_name):
    """
    Generates a stage that can be used to "arm" a pipeline.

    When using a fan in or fan out GoCD will ensure the consistency of materials used between pipelines. To accomplish
     this all pipelines must be set to to trigger on success. This stage generates a simple echo statement that can
     be used to "arm" a pipeline. The stage that follows this must set the manual_approval flag via:
     set_has_manual_approval()

    Using this pattern allows a pipeline to be be set as automatic, but then pause and wait for input from the user.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add this stage.
        stage_name (str): Name of the stage.

    Returns:
        gomatic.Stage
    """
    armed_stage = pipeline.ensure_stage(stage_name)
    armed_job = armed_stage.ensure_job(constants.ARMED_JOB_NAME)
    armed_job.add_task(
        ExecTask(
            [
                '/bin/bash',
                '-c',
                'echo Pipeline run number $GO_PIPELINE_COUNTER armed by $GO_TRIGGER_USER'
            ],
        )
    )

    return armed_stage


def generate_deployment_messages(
        pipeline, ami_pairs, stage_deploy_pipeline,
        release_status, confluence_user, confluence_password, github_token,
        base_ami_artifact, head_ami_artifact, message_tags,
        manual_approval=False,
        wiki_parent_title=None, wiki_space=None, wiki_title=None
):
    """
    Creates a stage that will message the pull requests for a range of commits that the respective pull requests have
    been deployed to the staging environment.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to attach this stage
        prod_build_pipelines (list of gomatic.Pipeline): The build pipelines that produced the AMIs being deployed
        stage_deploy_pipeline: The pipeline that deployed to staging
        org (str): Name of the github organization that holds the repository (e.g. edx)
        repo (str): Name of repository (e.g edx-platform)
        release_status (ReleaseStatus): the current status of the release
        confluence_user (str): The confluence user to create the release page with
        confluence_password (str): The confluence password to create the release page with
        github_token (str): The github token to fetch PR data with
        base_ami_artifact (ArtifactLocation): The location of the artifact that specifies
            the base_ami and tags
        head_ami_artifact (ArtifactLocation): The location of the artifact that specifies
            the head_ami and tags
        message_tags (list of (org, repo, version_tag)): The list of org/repo pairs that should
            be messaged based on changes in the specified version tag between the base and head ami
            artifacts.
        manual_approval (bool): Should this stage require manual approval?
        ami_tag_app (str): The name of the version tag on the AMI to extract the version from (Optional)
        wiki_parent_title (str): The title of the parent page to publish the release page
            under (defaults to 'LMS/Studio Release Pages')
        wiki_space (str): The space to publish the release page in (defaults to 'ENG')
        wiki_title (str): The title of the release wiki page (defaults to '<Next Release Date> Release')

    Returns:
        gomatic.stage.Stage

    """
    message_stage = pipeline.ensure_stage(constants.MESSAGE_PR_STAGE_NAME)
    if manual_approval:
        message_stage.set_has_manual_approval()
    message_job = message_stage.ensure_job(constants.MESSAGE_PR_JOB_NAME)
    tasks.generate_package_install(message_job, 'tubular')

    for org, repo, version_tag in message_tags:
        tasks.generate_message_pull_requests_in_commit_range(
            pipeline, message_job, org, repo, github_token, release_status,
            base_ami_artifact=base_ami_artifact, base_ami_tag_app=version_tag,
            head_ami_artifact=head_ami_artifact, head_ami_tag_app=version_tag,
        )
    wiki_job = message_stage.ensure_job(constants.PUBLISH_WIKI_JOB_NAME)
    tasks.generate_package_install(wiki_job, 'tubular')

    if release_status == constants.ReleaseStatus.STAGED:
        parent_title = wiki_parent_title
        title = wiki_title
        space = wiki_space
        input_artifact = None
    else:
        parent_title = None
        title = None
        space = None
        input_artifact = ArtifactLocation(
            stage_deploy_pipeline.name,
            message_stage.name,
            constants.PUBLISH_WIKI_JOB_NAME,
            constants.RELEASE_WIKI_PAGE_ID_FILENAME,
        )

    tasks.generate_release_wiki_page(
        pipeline,
        wiki_job,
        confluence_user=confluence_user,
        confluence_password=confluence_password,
        github_token=github_token,
        release_status=release_status,
        ami_pairs=ami_pairs,
        parent_title=parent_title,
        space=space,
        title=title,
        input_artifact=input_artifact,
    )

    return message_stage


def generate_create_branch_and_pr(pipeline,
                                  stage_name,
                                  org,
                                  repo,
                                  source_branch,
                                  new_branch,
                                  target_branch,
                                  pr_title,
                                  pr_body,
                                  token,
                                  manual_approval):
    """
    Generates a stage that is used to:
    - create a new branch off the HEAD of a source branch
    - create a PR to merge the new branch into a target branch

    Args:
        pipeline (gomatic.Pipeline): Pipeline to attach this stage to
        stage_name (str): Name of the stage
        org (str): Name of the github organization that holds the repository (e.g. edx)
        repo (str): Name of repository (e.g edx-platform)
        source_branch (str): Name of the branch to use in creating the new branch
        new_branch (str): Name of the branch to create off the HEAD of the source branch
        target_branch (str): Name of the branch into which to merge the source branch
        pr_title (str): Title of the new PR
        pr_body (str): Body of the new PR
        token (str): the github token used to create all these things. Will be an env_var 'GIT_TOKEN'
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    git_stage = pipeline.ensure_stage(stage_name)
    if manual_approval:
        git_stage.set_has_manual_approval()
    git_job = git_stage.ensure_job(constants.CREATE_MASTER_MERGE_PR_JOB_NAME)
    tasks.generate_package_install(git_job, 'tubular')
    tasks.generate_target_directory(git_job)

    # Generate a task that creates a new branch off the HEAD of a source branch.
    tasks.generate_create_branch(
        pipeline,
        git_job,
        token,
        org,
        repo,
        target_branch=new_branch,
        source_branch=source_branch
    )

    # Generate a task that creates a pull request merging the new branch from above into a target branch.
    tasks.generate_create_pr(
        git_job,
        org,
        repo,
        new_branch,
        target_branch,
        pr_title,
        pr_body
    )

    return git_stage


def generate_poll_tests_and_merge_pr(pipeline,
                                     stage,
                                     job,
                                     stage_name,
                                     job_name,
                                     pr_artifact_params,
                                     artifact_filename,
                                     org,
                                     repo,
                                     token,
                                     initial_poll_wait,
                                     max_poll_tries,
                                     poll_interval,
                                     manual_approval):
    """
    Generates a stage that is used to:
    - poll for successful completion of PR tests
    - merge the PR

    Args:
        pipeline (gomatic.Pipeline): Pipeline to attach this stage to
        stage (gomatic.Stage): Stage to use when adding tasks -or- None
        job (gomatic.Job): Job to use when adding tasks -or- None
        stage_name (str): Name of the stage
        pr_artifact_params (dict): Params to use in creation of artifact-fetching task.
        artifact_filename (str): Filename of the artifact to fetch/read-in.
        org (str): Name of the github organization that holds the repository (e.g. edx)
        repo (str): Name of repository (e.g edx-platform)
        token (str): the github token used to create all these things. Will be an env_var 'GIT_TOKEN'
        initial_poll_wait (int): Number of seconds that will pass between 1st/2nd poll attempts.
        max_poll_tries (int): Maximum number of poll attempts that should occur before failing.
        poll_interval (int): Number of seconds between all poll attempts (after the 1st/2nd attempt interval).
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    pipeline.ensure_environment_variables(
        {
            'PR_TEST_INITIAL_WAIT_INTERVAL': str(initial_poll_wait),
            'MAX_PR_TEST_POLL_TRIES': str(max_poll_tries),
            'PR_TEST_POLL_INTERVAL': str(poll_interval)
        }
    )
    pipeline.ensure_unencrypted_secure_environment_variables(
        {
            'GIT_TOKEN': token
        }
    )
    if stage is None:
        git_stage = pipeline.ensure_stage(stage_name)
        if manual_approval:
            git_stage.set_has_manual_approval()
        git_job = git_stage.ensure_job(job_name)
    else:
        git_stage = stage
        git_job = job
    tasks.generate_package_install(git_job, 'tubular')
    tasks.generate_target_directory(git_job)

    # Fetch the PR-creation material.
    git_job.add_task(FetchArtifactTask(**pr_artifact_params))

    # Generate a task that poll the status of combined tests for a PR.
    tasks.generate_poll_pr_tests(
        git_job,
        org,
        repo,
        artifact_filename
    )

    # Generate a task that merges a PR that has passed all its tests in the previous task.
    tasks.generate_merge_pr(
        git_job,
        org,
        repo,
        artifact_filename
    )

    return git_stage


def generate_build_value_stream_map_url(pipeline):
    """
    Genrates a stage that is used to build and serialize the value_stream_map url for a pipeline.

    Generates 1 artifact:
        value_stream_map.yaml   - YAML file that contains the value_stream_map URL.

    Args:
        pipeline (gomatic.Pipeline):

    Returns:
        gomatic.Stage
    """
    # Create the stage
    stage = pipeline.ensure_stage(constants.BUILD_VALUE_STREAM_MAP_URL_STAGE_NAME)

    # Create the job
    job = stage.ensure_job(constants.BUILD_VALUE_STREAM_MAP_URL_JOB_NAME)

    # Add task to generate the directory where the value_stream_map.yaml file will be written.
    tasks.generate_target_directory(job)

    # Add task to upload the value_stream_map.yaml file.
    value_stream_map_filepath = '{artifact_path}/{file_name}'.format(
        artifact_path=constants.ARTIFACT_PATH,
        file_name=constants.VALUE_STREAM_MAP_FILENAME
    )
    job.ensure_artifacts(set([value_stream_map_filepath]))

    # Script to generate the value_stream_map_url and write it out to value_stream_map.yaml
    script = '''
        if [ -z "$GO_PIPELINE_NAME" ] || [ -z "$GO_PIPELINE_LABEL" ]; then
          echo "Error: missing GO_PIPELINE_NAME and/or GO_PIPELINE_LABEL" 1>&2
          exit 1
        fi
        printf -- '---\n- deploy_value_stream_map: "{base_url}/$GO_PIPELINE_NAME/$GO_PIPELINE_LABEL"' > {filepath}
    '''.format(base_url=constants.BASE_VALUE_STREAM_MAP_URL, filepath=value_stream_map_filepath)
    job.add_task(
        ExecTask(
            [
                '/bin/bash',
                '-c',
                script
            ]
        )
    )

    return stage


def generate_find_and_advance_release(
        pipeline,
        advance_pipeline_name,
        advance_pipeline_stage_name,
        gocd_user,
        gocd_password,
        gocd_url,
        hipchat_token,
        hipchat_room=constants.HIPCHAT_ROOM,
):
    """
    Generates a stage used to find the next release to advance and "manually" advance it.

    Args:
        pipeline (gomatic.Pipeline):
        advance_pipeline_name (str): Name of pipeline to advance.
        advance_pipeline_stage_name (str): Name of stage within pipeline to advance.
        gocd_user (str): GoCD username
        gocd_password (str): GoCD user's password
        gocd_url (str): URL of the GoCD instance
        hipchat_token (str): Auth token for HipChat posting.
        hipchat_room (str): HipChat room to use for posting.

    Returns:
        gomatic.Stage
    """
    stage = pipeline.ensure_stage(constants.RELEASE_ADVANCER_STAGE_NAME)
    job = stage.ensure_job(constants.RELEASE_ADVANCER_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')

    # Add task to generate the directory where the artifact file will be written.
    tasks.generate_target_directory(job)

    pipeline.ensure_unencrypted_secure_environment_variables(
        {
            'GOCD_PASSWORD': gocd_password
        }
    )
    job.ensure_encrypted_environment_variables(
        {
            'HIPCHAT_TOKEN': hipchat_token,
        }
    )

    tasks.generate_find_and_advance_release(
        job,
        gocd_user,
        gocd_url,
        advance_pipeline_name,
        advance_pipeline_stage_name,
        hipchat_room,
        out_file=constants.FIND_ADVANCE_PIPELINE_OUT_FILENAME
    )

    return stage


def generate_check_ci(
        pipeline,
        token,
        materials_to_check
):
    """
    Generates a stage used to check the CI combined test status of a commit.
    Used to gate a release on whether CI has successfully passed for the release code.

    Args:
        pipeline (gomatic.Pipeline):
        token (str): GitHub token used to check CI.
        materials_to_check (list(GitMaterial)): List of materials.

    Returns:
        gomatic.Stage
    """
    pipeline.ensure_unencrypted_secure_environment_variables(
        {
            'GIT_TOKEN': token
        }
    )
    stage = pipeline.ensure_stage(constants.CHECK_CI_STAGE_NAME)
    # Add a separate checking job for each org/repo.
    for material in materials_to_check:
        org, repo = github_id(material)
        repo_underscore = repo.replace('-', '_')
        job = stage.ensure_job(constants.CHECK_CI_JOB_NAME + '_' + repo_underscore)
        tasks.generate_package_install(job, 'tubular')

        cmd_args = [
            '--token', '$GIT_TOKEN',
            '--org', org,
            '--repo', repo,
            '--commit_hash', material_envvar_bash(material)
        ]
        job.add_task(tasks.tubular_task(
            'check_pr_tests_status.py',
            cmd_args
        ))

    return stage
