from gomatic import *

import edxpipelines.constants as constants
import edxpipelines.patterns.tasks as tasks


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
    tasks.generate_requirements_install(job, 'tubular')
    job.add_task(ExecTask(
        [
            '/usr/bin/python',
            'scripts/cleanup-asgs.py'
        ],
        working_dir="tubular")
    )

    return stage


def generate_launch_instance(pipeline,
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
                             ec2_ebs_volume_size=constants.EC2_EBS_VOLUME_SIZE):
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

    Returns:

    """
    pipeline.ensure_encrypted_environment_variables(
        {
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key
        }
    )

    pipeline.ensure_environment_variables(
        {
            'EC2_VPC_SUBNET_ID': ec2_vpc_subnet_id,
            'EC2_SECURITY_GROUP_ID': ec2_security_group_id,
            'EC2_ASSIGN_PUBLIC_IP': 'no',
            'EC2_TIMEOUT': ec2_timeout,
            'EC2_REGION': ec2_region,
            'EBS_VOLUME_SIZE': ec2_ebs_volume_size,
            'EC2_INSTANCE_TYPE': ec2_instance_type,
            'EC2_INSTANCE_PROFILE_NAME': ec2_instance_profile_name,
            'NO_REBOOT': 'no',
            'BASE_AMI_ID': base_ami_id,
            'ANSIBLE_CONFIG': constants.ANSIBLE_CONTINUOUS_DELIVERY_CONFIG,
        }
    )

    stage = pipeline.ensure_stage(constants.LAUNCH_INSTANCE_STAGE_NAME)

    if manual_approval:
        stage.set_has_manual_approval()

    # Install the requirements.
    job = stage.ensure_job(constants.LAUNCH_INSTANCE_JOB_NAME)
    tasks.generate_requirements_install(job, 'tubular')
    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_launch_instance(job)

    return stage


def generate_run_play(pipeline,
                      playbook_with_path,
                      play,
                      deployment,
                      edx_environment,
                      app_repo,
                      private_github_key='',
                      hipchat_token='',
                      hipchat_room=constants.HIPCHAT_ROOM,
                      manual_approval=False,
                      configuration_secure_dir=constants.PRIVATE_CONFIGURATION_LOCAL_DIR,
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
        **kwargs (dict):
            k,v pairs:
                k: the name of the option to pass to ansible
                v: the value to use for this option

    Returns:
        gomatic.Stage
    """
    # setup the necessary environment variables
    pipeline.ensure_encrypted_environment_variables(
        {
            'HIPCHAT_TOKEN': hipchat_token,
            'PRIVATE_GITHUB_KEY': private_github_key
        }
    )
    pipeline.ensure_environment_variables(
        {
            'PLAY': play,
            'DEPLOYMENT': deployment,
            'EDX_ENVIRONMENT': edx_environment,
            'APP_REPO': app_repo,
            'ARTIFACT_PATH': '{}/'.format(constants.ARTIFACT_PATH),
            'HIPCHAT_ROOM': hipchat_room,
            'ANSIBLE_CONFIG': constants.ANSIBLE_CONTINUOUS_DELIVERY_CONFIG,
        }
    )

    stage = pipeline.ensure_stage(constants.RUN_PLAY_STAGE_NAME)
    if manual_approval:
        stage.set_has_manual_approval()

    # Install the requirements.
    job = stage.ensure_job(constants.RUN_PLAY_JOB_NAME)
    tasks.generate_requirements_install(job, 'tubular')
    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_target_directory(job)

    # fetch the key material
    artifact_params = {
        'pipeline': pipeline.name,
        'stage': constants.LAUNCH_INSTANCE_STAGE_NAME,
        'job': constants.LAUNCH_INSTANCE_JOB_NAME,
        'src': FetchArtifactFile("key.pem"),
        'dest': constants.ARTIFACT_PATH
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # fetch the launch_info.yml
    artifact_params['src'] = FetchArtifactFile('launch_info.yml')
    job.add_task(FetchArtifactTask(**artifact_params))

    # fetch the inventory file
    artifact_params['src'] = FetchArtifactFile('ansible_inventory')
    job.add_task(FetchArtifactTask(**artifact_params))

    tasks.generate_run_app_playbook(job, configuration_secure_dir, playbook_with_path, **kwargs)
    return stage


def generate_create_ami_from_instance(pipeline,
                                      play,
                                      deployment,
                                      edx_environment,
                                      app_repo,
                                      configuration_secure_repo,
                                      aws_access_key_id,
                                      aws_secret_access_key,
                                      configuration_repo=constants.PUBLIC_CONFIGURATION_REPO_URL,
                                      ami_creation_timeout="3600",
                                      ami_wait='yes',
                                      cache_id='',
                                      artifact_path=constants.ARTIFACT_PATH,
                                      hipchat_room=constants.HIPCHAT_ROOM,
                                      manual_approval=False,
                                      **kwargs):
    """
    Generates an artifact ami.yml:
        ami_id: ami-abcdefg
        ami_message: AMI creation operation complete
        ami_state: available

    Args:
        pipeline (gomatic.Pipeline):
        play (str): Play that was run on the instance (used for tagging)
        deployment (str):
        edx_environment (str):
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
    pipeline.ensure_encrypted_environment_variables(
        {
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key
        }
    )

    pipeline.ensure_environment_variables(
        {
            'PLAY': play,
            'DEPLOYMENT': deployment,
            'EDX_ENVIRONMENT': edx_environment,
            'APP_REPO': app_repo,
            'CONFIGURATION_REPO': configuration_repo,
            'CONFIGURATION_SECURE_REPO': configuration_secure_repo,
            'AMI_CREATION_TIMEOUT': ami_creation_timeout,
            'AMI_WAIT': ami_wait,
            'CACHE_ID': cache_id,  # gocd build number
            'ARTIFACT_PATH': artifact_path,
            'HIPCHAT_ROOM': hipchat_room,
            'ANSIBLE_CONFIG': constants.ANSIBLE_CONTINUOUS_DELIVERY_CONFIG,
        }
    )

    # Install the requirements.
    job = stage.ensure_job(constants.BUILD_AMI_JOB_NAME)
    tasks.generate_requirements_install(job, 'tubular')
    tasks.generate_requirements_install(job, 'configuration')

    tasks.generate_target_directory(job)

    # fetch the key material
    artifact_params = {
        'pipeline': pipeline.name,
        'stage': constants.LAUNCH_INSTANCE_STAGE_NAME,
        'job': constants.LAUNCH_INSTANCE_JOB_NAME,
        'src': FetchArtifactFile("launch_info.yml"),
        'dest': constants.ARTIFACT_PATH
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # Create an AMI from the instance
    tasks.generate_create_ami(job, **kwargs)

    return stage


def generate_deploy_ami(pipeline,
                        asgard_api_endpoints,
                        asgard_token,
                        aws_access_key_id,
                        aws_secret_access_key,
                        upstream_ami_artifact=None,
                        manual_approval=True
                        ):
    """
    Generates a stage which deploys an AMI via Asgard.

    if the variable upstream_ami_artifact is set information about which AMI to deploy will be pulled
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
    tasks.generate_requirements_install(job, 'tubular')

    # Setup the deployment output file
    artifact_path = '{}/{}'.format(
        constants.ARTIFACT_PATH,
        constants.DEPLOY_AMI_OUT_FILENAME
    )
    job.ensure_artifacts(set([BuildArtifact(artifact_path)]))

    job_command = [
        '/usr/bin/python',
        'scripts/asgard-deploy.py',
        '--out_file', '../{}'.format(artifact_path)
    ]

    if upstream_ami_artifact:
        artifact_params = {
            "pipeline": upstream_ami_artifact.pipeline,
            "stage": upstream_ami_artifact.stage,
            "job": upstream_ami_artifact.job,
            "src": FetchArtifactFile(upstream_ami_artifact.file_name),
            "dest": 'tubular'
        }
        job.add_task(FetchArtifactTask(**artifact_params))
        job_command.extend(['--config-file', upstream_ami_artifact.file_name])

    else:
        pipeline.ensure_environment_variables({'AMI_ID': None})
        job_command.extend(['--ami_id', "$AMI_ID"])

    # Make the artifact directory if it does not exist
    job.add_task(ExecTask(
        [
            '/bin/bash',
            '-c',
            'mkdir -p ../{}'.format(constants.ARTIFACT_PATH),
        ],
        working_dir="tubular")
    )

    # Execute the deployment script
    job.add_task(ExecTask(job_command, working_dir="tubular"))
    return stage


def generate_edp_validation(pipeline,
                            hipchat_auth_token,
                            hipchat_channels,
                            asgard_api_endpoints,
                            ami_deployment,
                            ami_environment,
                            ami_play,
                            manual_approval=False):
    """
    Generate stage which checks an AMI's environment/deployment/play (EDP) against the allowed EDP.
    Stage fails if the EDPs don't match.

    Args:
        pipeline (gomatic.Pipeline):
        hipchat_auth_token (str):
        hipchat_channels (str): The channels/users to notify
        asgard_api_endpoints (str): canonical URL for asgard.
        ami_deployment (str): typically one of: [edx, edge, etc...]
        ami_environment (str): typically one of: [stage, prod, loadtest, etc...]
        ami_play (str):
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    pipeline.ensure_environment_variables({'AMI_ID': None,
                                           'AMI_DEPLOYMENT': ami_deployment,
                                           'HIPCHAT_CHANNELS': hipchat_channels,
                                           'ASGARD_API_ENDPOINTS': asgard_api_endpoints,
                                           'AMI_ENVIRONMENT': ami_environment,
                                           'AMI_PLAY': ami_play}) \
        .ensure_encrypted_environment_variables({'HIPCHAT_TOKEN': hipchat_auth_token})

    stage = pipeline.ensure_stage("Validation")
    if manual_approval:
        stage.set_has_manual_approval()
    job = stage.ensure_job("EDPValidation")
    tasks.generate_requirements_install(job, 'tubular')
    job.add_task(
        ExecTask(
            [
                '/usr/bin/python',
                'scripts/validate_edp.py'
            ],
            working_dir='tubular'
        )
    )
    job.add_task(
        ExecTask(
            [
                '/bin/bash',
                '-c',
                '/usr/bin/python '
                'scripts/submit_hipchat_msg.py '
                '-m '
                '"${AMI_ID} is not tagged for ${AMI_ENVIRONMENT}-${AMI_DEPLOYMENT}-${AMI_PLAY}. '
                'Are you sure you\'re deploying the right AMI to the right app?" '
                '--color "red"'
            ],
            working_dir='tubular',
            runif='failed'
        )
    )

    return stage


def generate_run_migrations(pipeline,
                            db_migration_pass,
                            inventory_location,
                            instance_key_location,
                            launch_info_location,
                            application_user,
                            application_name,
                            application_path,
                            sub_application_name=None,
                            manual_approval=False):
    """
    Generate the stage that applies/runs migrations.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        db_migration_pass (str): Password for the DB user used to run migrations.
        inventory_location (ArtifactLocation): Location of inventory containing the IP address of the EC2 instance, for fetching.
        instance_key_location (ArtifactLocation): Location of SSH key used to access the EC2 instance, for fetching.
        launch_info_location (ArtifactLocation): Location of the launch_info.yml file for fetching
        application_user (str): Username to use while running the migrations
        application_name (str): Name of the application (e.g. edxapp, programs, etc...)
        application_path (str): path of the application installed on the target machine
        sub_application_name (str): any sub application to insert in to the migrations commands {cms|lms}
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    pipeline.ensure_environment_variables(
        {
            'APPLICATION_USER': application_user,
            'APPLICATION_NAME': application_name,
            'APPLICATION_PATH': application_path,
            'DB_MIGRATION_USER': 'migrate',
            'ARTIFACT_PATH': constants.ARTIFACT_PATH,
            'ANSIBLE_CONFIG': constants.ANSIBLE_CONTINUOUS_DELIVERY_CONFIG,
        }
    )
    pipeline.ensure_encrypted_environment_variables(
        {
            'DB_MIGRATION_PASS': db_migration_pass,
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

    # Fetch the Ansible inventory to use in reaching the EC2 instance.
    artifact_params = {
        "pipeline": inventory_location.pipeline,
        "stage": inventory_location.stage,
        "job": inventory_location.job,
        "src": FetchArtifactFile(inventory_location.file_name),
        "dest": constants.ARTIFACT_PATH
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # Fetch the SSH key to use in reaching the EC2 instance.
    artifact_params = {
        "pipeline": instance_key_location.pipeline,
        "stage": instance_key_location.stage,
        "job": instance_key_location.job,
        "src": FetchArtifactFile(instance_key_location.file_name),
        "dest": constants.ARTIFACT_PATH
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # ensure the target directoy exists
    tasks.generate_target_directory(job)

    # fetch the launch_info.yml
    artifact_params = {
        "pipeline": launch_info_location.pipeline,
        "stage": launch_info_location.stage,
        "job": launch_info_location.job,
        "src": FetchArtifactFile(launch_info_location.file_name),
        "dest": constants.ARTIFACT_PATH
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # The SSH key used to access the EC2 instance needs specific permissions.
    job.add_task(
        ExecTask(
            ['/bin/bash', '-c', 'chmod 600 {}'.format(instance_key_location.file_name)],
            working_dir=constants.ARTIFACT_PATH
        )
    )

    tasks.generate_requirements_install(job, 'configuration')
    tasks.generate_run_migrations(job, sub_application_name)

    # Cleanup EC2 instance if running the migrations failed.
    # I think this should be left for the terminate instance stage
    # tasks.generate_ami_cleanup(job, runif='failed')

    return stage


def generate_terminate_instance(pipeline,
                                instance_info_location,
                                aws_access_key_id,
                                aws_secret_access_key,
                                hipchat_auth_token,
                                ec2_region=constants.EC2_REGION,
                                artifact_path=constants.ARTIFACT_PATH,
                                runif='any',
                                manual_approval=False):
    """
    Generate the stage that terminates an EC2 instance.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        instance_info_location (ArtifactLocation): Location of YAML file containing instance info from the AMI-building stage, for fetching.
        runif (str): one of ['passed', 'failed', 'any'] Default: any - controls when the stage's terminate task is triggered in the pipeline
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage

    """
    pipeline.ensure_encrypted_environment_variables(
        {
            'AWS_ACCESS_KEY_ID': aws_access_key_id,
            'AWS_SECRET_ACCESS_KEY': aws_secret_access_key,
            'HIPCHAT_TOKEN': hipchat_auth_token
        }
    )
    pipeline.ensure_environment_variables(
        {
            'ARTIFACT_PATH': artifact_path,
            'EC2_REGION': ec2_region,
            'HIPCHAT_ROOM': constants.HIPCHAT_ROOM
        }
    )

    stage = pipeline.ensure_stage(constants.TERMINATE_INSTANCE_STAGE_NAME)
    if manual_approval:
        stage.set_has_manual_approval()

    # Fetch the instance info to use in reaching the EC2 instance.
    artifact_params = {
        'pipeline': instance_info_location.pipeline,
        'stage': instance_info_location.stage,
        'job': instance_info_location.job,
        'src': FetchArtifactFile(instance_info_location.file_name),
        'dest': constants.ARTIFACT_PATH
    }
    job = stage.ensure_job(constants.TERMINATE_INSTANCE_JOB_NAME)
    tasks.generate_requirements_install(job, 'configuration')
    job.add_task(FetchArtifactTask(**artifact_params))

    tasks.generate_ami_cleanup(job, runif=runif)

    return stage


def generate_rollback_asg_stage(
    pipeline,
    asgard_api_endpoints,
    asgard_token,
    aws_access_key_id,
    aws_secret_access_key,
    hipchat_auth_token,
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
            'HIPCHAT_TOKEN': hipchat_auth_token,
        }
    )

    stage = pipeline.ensure_stage(constants.ROLLBACK_ASGS_STAGE_NAME)
    # Important: Do *not* automatically rollback! Always manual...
    stage.set_has_manual_approval()
    job = stage.ensure_job(constants.ROLLBACK_ASGS_JOB_NAME)
    tasks.generate_requirements_install(job, 'tubular')

    artifact_params = {
        "pipeline": deploy_file_location.pipeline,
        "stage": deploy_file_location.stage,
        "job": deploy_file_location.job,
        "src": FetchArtifactFile(deploy_file_location.file_name),
        "dest": 'tubular'
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    job.add_task(ExecTask(
        [
            '/bin/bash',
            '-c',
            'mkdir -p ../target',
        ],
        working_dir="tubular")
    )

    artifact_path = '{}/{}'.format(
        constants.ARTIFACT_PATH,
        constants.ROLLBACK_AMI_OUT_FILENAME
    )
    job.ensure_artifacts(set([BuildArtifact(artifact_path)]))

    job.add_task(ExecTask(
        [
            '/usr/bin/python',
            'scripts/rollback_asg.py',
            '--config_file', deploy_file_location.file_name,
            '--out_file', '../{}'.format(artifact_path),
        ],
        working_dir="tubular")
    )
    return stage


def generate_ansible_stage(
    stage_name,
    task,
    pipeline,
    inventory_location,
    instance_key_location,
    launch_info_location,
    application_user,
    application_name,
    application_path,
    hipchat_auth_token,
    hipchat_room=constants.HIPCHAT_ROOM,
    manual_approval=False
):
    """
        Generate the stage with the given name, that runs the specified task.

        Args:
            stage_name (str): Name of the generated stage.
            task (function): Task to be executed by the stage.
            pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
            inventory_location (ArtifactLocation): Location of inventory containing the IP address of the EC2 instance, for fetching.
            instance_key_location (ArtifactLocation): Location of SSH key used to access the EC2 instance, for fetching.
            launch_info_location (ArtifactLocation): Location of the launch_info.yml file for fetching
            application_user (str): Username to use while running the migrations
            application_name (str): Name of the application (e.g. edxapp, programs, etc...)
            application_path (str): path of the application installed on the target machine
            hipchat_auth_token (str): HipChat authentication token
            hipchat_room (str): HipChat room where announcements should be made
            manual_approval (bool): Should this stage require manual approval?

        Returns:
            gomatic.Stage
        """

    pipeline.ensure_environment_variables(
        {
            'APPLICATION_USER': application_user,
            'APPLICATION_NAME': application_name,
            'APPLICATION_PATH': application_path,
            'HIPCHAT_ROOM': hipchat_room,
        }
    )
    pipeline.ensure_encrypted_environment_variables(
        {
            'HIPCHAT_TOKEN': hipchat_auth_token,
        }
    )

    stage = pipeline.ensure_stage(stage_name)

    if manual_approval:
        stage.set_has_manual_approval()
    job = stage.ensure_job(stage_name + '_job')

    # Fetch the Ansible inventory to use in reaching the EC2 instance.
    artifact_params = {
        "pipeline": inventory_location.pipeline,
        "stage": inventory_location.stage,
        "job": inventory_location.job,
        "src": FetchArtifactFile(inventory_location.file_name),
        "dest": 'configuration'
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # Fetch the SSH key to use in reaching the EC2 instance.
    artifact_params = {
        "pipeline": instance_key_location.pipeline,
        "stage": instance_key_location.stage,
        "job": instance_key_location.job,
        "src": FetchArtifactFile(instance_key_location.file_name),
        "dest": 'configuration'
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # ensure the target directoy exists
    tasks.generate_target_directory(job)

    # fetch the launch_info.yml
    artifact_params = {
        "pipeline": launch_info_location.pipeline,
        "stage": launch_info_location.stage,
        "job": launch_info_location.job,
        "src": FetchArtifactFile(launch_info_location.file_name),
        "dest": "target"
    }
    job.add_task(FetchArtifactTask(**artifact_params))

    # The SSH key used to access the EC2 instance needs specific permissions.
    job.add_task(
        ExecTask(
            ['/bin/bash', '-c', 'chmod 600 {}'.format(instance_key_location.file_name)],
            working_dir='configuration'
        )
    )

    tasks.generate_requirements_install(job, 'configuration')
    task(job)

    return stage


def generate_refresh_metadata(
    pipeline,
    inventory_location,
    instance_key_location,
    launch_info_location,
    application_user,
    application_name,
    application_path,
    hipchat_auth_token='',
    hipchat_room=constants.HIPCHAT_ROOM,
    manual_approval=False
):
    """
    Generate the stage that refreshes metadata for the discovery service.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        inventory_location (ArtifactLocation): Location of inventory containing the IP address of the EC2 instance, for fetching.
        instance_key_location (ArtifactLocation): Location of SSH key used to access the EC2 instance, for fetching.
        launch_info_location (ArtifactLocation): Location of the launch_info.yml file for fetching
        application_user (str): Username to use while running the migrations
        application_name (str): Name of the application (e.g. edxapp, programs, etc...)
        application_path (str): path of the application installed on the target machine
        hipchat_auth_token (str): HipChat authentication token
        hipchat_room (str): HipChat room where announcements should be made
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    return generate_ansible_stage(
        'refresh_metadata',
        tasks.generate_refresh_metadata,
        pipeline,
        inventory_location,
        instance_key_location,
        launch_info_location,
        application_user,
        application_name,
        application_path,
        hipchat_auth_token,
        hipchat_room,
        manual_approval
    )


def generate_update_index(
    pipeline,
    inventory_location,
    instance_key_location,
    launch_info_location,
    application_user,
    application_name,
    application_path,
    hipchat_auth_token='',
    hipchat_room=constants.HIPCHAT_ROOM,
    manual_approval=False
):
    """
    Generate the stage that refreshes metadata for the discovery service.

    Args:
        pipeline (gomatic.Pipeline): Pipeline to which to add the run migrations stage.
        inventory_location (ArtifactLocation): Location of inventory containing the IP address of the EC2 instance, for fetching.
        instance_key_location (ArtifactLocation): Location of SSH key used to access the EC2 instance, for fetching.
        launch_info_location (ArtifactLocation): Location of the launch_info.yml file for fetching
        application_user (str): Username to use while running the migrations
        application_name (str): Name of the application (e.g. edxapp, programs, etc...)
        application_path (str): path of the application installed on the target machine
        hipchat_auth_token (str): HipChat authentication token
        hipchat_room (str): HipChat room where announcements should be made
        manual_approval (bool): Should this stage require manual approval?

    Returns:
        gomatic.Stage
    """
    return generate_ansible_stage(
        'update_index',
        tasks.generate_update_index,
        pipeline,
        inventory_location,
        instance_key_location,
        launch_info_location,
        application_user,
        application_name,
        application_path,
        hipchat_auth_token,
        hipchat_room,
        manual_approval
    )


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
