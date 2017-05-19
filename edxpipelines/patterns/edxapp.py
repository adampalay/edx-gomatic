#!/usr/bin/env python

"""
Gomatic patterns for building the edxapp pipeline.
"""

import sys
from os import path
from gomatic import ExecTask, FetchArtifactFile

# Used to import edxpipelines files - since the module is not installed.
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

# pylint: disable=wrong-import-position
from edxpipelines import utils
from edxpipelines.patterns import stages, jobs, tasks
from edxpipelines.patterns.tasks import private_releases
from edxpipelines import constants
from edxpipelines.materials import (
    TUBULAR, CONFIGURATION, EDX_PLATFORM, EDX_PLATFORM_PRIVATE, EDX_SECURE, EDGE_SECURE,
    EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL, material_envvar_bash
)


STAGE_EDX_EDXAPP = utils.EDP('stage', 'edx', 'edxapp')
PROD_EDX_EDXAPP = utils.EDP('prod', 'edx', 'edxapp')
PROD_EDGE_EDXAPP = utils.EDP('prod', 'edge', 'edxapp')
EDXAPP_SUBAPPS = ['cms', 'lms']

# This pipeline contains the manual stage that gates a production deploy.
# That stage is automatically advanced by a separate release-advancing pipeline
# to trigger a production deployment.
EDXAPP_MANUAL_PIPELINE_NAME = "manual_verification_edxapp_prod_early_ami_build"


def private_public_merge_sync(edxapp_group, config):
    """
    Variables needed for this pipeline:
    - git_token
    - initial_poll_wait
    - max_poll_tries
    - poll_interval
    """
    pipeline = edxapp_group.ensure_replacement_of_pipeline('edxapp_private_public_merge_sync')

    edx_platform_private_sr = EDX_PLATFORM_PRIVATE(
        material_name='edx-platform-private',
        destination_directory='edx-platform-priv',
        ignore_patterns=frozenset()
    )
    pipeline.ensure_material(edx_platform_private_sr)
    pipeline.ensure_material(EDX_PLATFORM(branch='master', destination_directory='edx-plat'))
    pipeline.ensure_material(TUBULAR())
    stage = pipeline.ensure_stage(constants.PRIV_PUB_CREATE_MERGE_PR_STAGE_NAME)
    job = stage.ensure_job(constants.PRIV_PUB_CREATE_MERGE_PR_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')

    private_releases.generate_private_public_create_pr(
        job,
        config['git_token'],
        ('edx', 'edx-platform-private'),
        edx_platform_private_sr.branch,
        ('edx', 'edx-platform'),
        "master",
    )

    stage = pipeline.ensure_stage(constants.PUB_PRIV_POLL_MERGE_STAGE_NAME)
    job = stage.ensure_job(constants.PUB_PRIV_POLL_MERGE_JOB_NAME)

    pr_artifact_params = {
        'pipeline': pipeline.name,
        'stage': constants.PRIV_PUB_CREATE_MERGE_PR_STAGE_NAME,
        'job': constants.PRIV_PUB_CREATE_MERGE_PR_JOB_NAME,
        'src': FetchArtifactFile(constants.PRIVATE_PUBLIC_PR_FILENAME),
        'dest': constants.ARTIFACT_PATH
    }
    stages.generate_poll_tests_and_merge_pr(
        pipeline=pipeline,
        stage=stage,
        job=job,
        stage_name=None,
        job_name=None,
        pr_artifact_params=pr_artifact_params,
        artifact_filename=constants.PRIVATE_PUBLIC_PR_FILENAME,
        org='edx',
        repo='edx-platform',
        token=config['github_token'],
        initial_poll_wait=config['initial_poll_wait'],
        max_poll_tries=config['max_poll_tries'],
        poll_interval=config['poll_interval'],
        manual_approval=False
    )

    # Generate a task that keeps the private branch up-to-date by pushing the public branch to it.
    private_releases.generate_public_private_merge(
        job,
        ('edx', 'edx-platform-private'),
        edx_platform_private_sr.branch,
        ('edx', 'edx-platform'),
        "master",
    )

    return pipeline


def make_release_candidate(edxapp_group, config):
    """
    Variables needed for this pipeline:
    - git_token
    """
    pipeline = edxapp_group.ensure_replacement_of_pipeline('edxapp_cut_release_candidate')

    edx_platform_master = EDX_PLATFORM(material_name='edx-platform', branch=None, ignore_patterns=frozenset())
    pipeline.ensure_material(edx_platform_master)
    pipeline.ensure_material(TUBULAR())
    stage = pipeline.ensure_stage(constants.MAKE_RELEASE_CANDIDATE_STAGE_NAME)
    job = stage.ensure_job(constants.MAKE_RELEASE_CANDIDATE_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')

    tasks.generate_merge_branch(
        pipeline,
        job,
        config['git_token'],
        'edx',
        'edx-platform',
        "origin/{}".format(edx_platform_master.branch),
        EDX_PLATFORM().branch,
        fast_forward_only=True,
        reference_repo='edx-platform',
    )

    # These two options together make sure that the pipeline only triggers
    # from the timer trigger.
    pipeline.set_timer('0 0/5 15-18 ? * MON-FRI', only_on_changes=True)
    stage.set_has_manual_approval()

    return pipeline


def release_advancer(edxapp_group, config):
    """
    Variables needed for this pipeline:
    - gocd_username
    - gocd_password
    - gocd_url
    - hipchat_token
    """
    pipeline = edxapp_group.ensure_replacement_of_pipeline("edxapp_release_advancer")
    pipeline.set_label_template('${COUNT}')

    pipeline.ensure_material(TUBULAR(material_name='tubular'))

    stage = stages.generate_find_and_advance_release(
        pipeline,
        EDXAPP_MANUAL_PIPELINE_NAME,
        constants.MANUAL_VERIFICATION_STAGE_NAME,
        config['gocd_username'],
        config['gocd_password'],
        'https://{}'.format(config['gocd_url']),
        config['hipchat_token']
    )

    # For now, only trigger this pipeline manually. Later, it'll trigger on a cron.
    stage.set_has_manual_approval()

    return pipeline


def prerelease_materials(edxapp_group, config):
    """
    Generate the prerelease materials pipeline

    Args:
        edxapp_group (gomatic.PipelineGroup): Pipeline group this new pipeline will be attached.
        config (dict): the general configuration for this pipeline
        stage_config (dict): the stage_edx_edxapp configuration for this pipeline
        prod_edx_config (dict): the prod_edx_edxapp configuration for this pipeline
        prod_edge_config (dict): the prod_edge_edxapp configuration for this pipeline

    Returns:
        gomatic.Pipeline

    Variables needed for this pipeline:
    - gocd_username
    - gocd_password
    - gocd_url
    - configuration_secure_repo
    - hipchat_token
    - github_private_key
    - aws_access_key_id
    - aws_secret_access_key
    - ec2_vpc_subnet_id
    - ec2_security_group_id

    - ec2_instance_profile_name
    - base_ami_id

    Optional variables:
    - configuration_secure_version
    """
    pipeline = edxapp_group.ensure_replacement_of_pipeline("prerelease_edxapp_materials_latest")
    pipeline.set_label_template('${edx-platform[:7]}-${COUNT}')

    for material in (
            CONFIGURATION, EDX_SECURE, EDGE_SECURE,
            EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL,
    ):
        pipeline.ensure_material(material())

    pipeline.ensure_material(TUBULAR())
    pipeline.ensure_material(EDX_PLATFORM(material_name='edx-platform', ignore_patterns=frozenset()))

    stage = pipeline.ensure_stage(constants.PRERELEASE_MATERIALS_STAGE_NAME)
    job = stage.ensure_job(constants.PRERELEASE_MATERIALS_JOB_NAME)
    tasks.generate_package_install(job, 'tubular')

    private_releases.generate_create_private_release_candidate(
        job,
        config['git_token'],
        ('edx', 'edx-platform'),
        'master',
        EDX_PLATFORM().branch,
        ('edx', 'edx-platform-private'),
        'security-release',
        'release-candidate',
        target_reference_repo='edx-platform-private',
    )

    # This prevents the commit being released from being lost when the new
    # release-candidate is cut. However, this will require a janitor job to
    # deal with any releases that are never completed.
    tasks.generate_create_branch(
        pipeline, job, config['git_token'], 'edx', 'edx-platform',
        target_branch="release-candidate-$GO_PIPELINE_COUNTER",
        sha=material_envvar_bash(EDX_PLATFORM()))

    # Move the AMI selection jobs here in a single stage.
    stage = pipeline.ensure_stage(constants.BASE_AMI_SELECTION_STAGE_NAME)
    for edp in (
            STAGE_EDX_EDXAPP,
            PROD_EDX_EDXAPP,
            PROD_EDGE_EDXAPP,
    ):
        localized_config = config[edp]
        job = stage.ensure_job(constants.BASE_AMI_SELECTION_EDP_JOB_NAME(edp))
        tasks.generate_package_install(job, 'tubular')
        tasks.generate_base_ami_selection(
            job,
            localized_config['aws_access_key_id'],
            localized_config['aws_secret_access_key'],
            edp,
            config.get('base_ami_id')
        )

    return pipeline


def launch_and_terminate_subset_pipeline(
        pipeline_group,
        stage_builders,
        config,
        pipeline_name,
        ami_artifact=None,
        auto_run=False,
        post_cleanup_builders=None,
        pre_launch_builders=None,
):
    """
    Arguments:
        pipeline_group (gomatic.PipelineGroup): The group in which to create this pipeline
        stage_builders (list): a list of methods that will create pipeline stages used
            between instance launch and cleanup
        ami_artifact (ArtifactLocation): The ami to use to launch the
            instances on. If None, select that ami based on the supplied ``edp``.
        config (dict): the configuration dictionary
        pipeline_name (str): name of the pipeline
        auto_run (bool): Should this pipeline auto execute?
        post_cleanup_builders (list): a list of methods that will create pipeline stages used
            after the cleanup has run
        pre_launch_builders (list): a list of methods that will create pipeline stages used
            before instance launch

    Variables needed for this pipeline:
    - aws_access_key_id
    - aws_secret_access_key
    - ec2_vpc_subnet_id
    - ec2_security_group_id
    - ec2_instance_profile_name
    - base_ami_id

    Optional variables:
    - configuration_secure_version
    - configuration_internal_version
    """
    pipeline = pipeline_group.ensure_replacement_of_pipeline(pipeline_name)

    base_ami_id = config.get('base_ami_id')

    # We always need to launch the AMI, independent deploys are done with a different pipeline
    # if the pipeline has a migrate stage, but no building stages, look up the build information from the
    # upstream pipeline.
    if pre_launch_builders:
        for builder in pre_launch_builders:
            builder(pipeline, config)

    launch_stage = stages.generate_launch_instance(
        pipeline,
        config['aws_access_key_id'],
        config['aws_secret_access_key'],
        config['ec2_vpc_subnet_id'],
        config['ec2_security_group_id'],
        config['ec2_instance_profile_name'],
        base_ami_id,
        base_ami_id_artifact=ami_artifact,
        manual_approval=not auto_run
    )

    # Generate all the requested stages
    for builder in stage_builders:
        builder(pipeline, config)

    # Add the cleanup stage
    generate_cleanup_stages(pipeline, config, launch_stage)

    if post_cleanup_builders:
        for builder in post_cleanup_builders:
            builder(pipeline, config)

    return pipeline


def generate_build_stages(app_repo, edp, theme_url, configuration_secure_repo,
                          configuration_internal_repo, configuration_url, prerelease_merge_artifact):
    """
    Generate the stages needed to build an edxapp AMI.
    """
    def builder(pipeline, config):
        """
        A builder for the stages needed to build an edxapp AMI.
        """

        stages.generate_run_play(
            pipeline,
            'playbooks/edx-east/edxapp.yml',
            edp=edp,
            private_github_key=config['github_private_key'],
            app_repo=app_repo,
            configuration_secure_dir='{}-secure'.format(edp.deployment),
            configuration_internal_dir='{}-internal'.format(edp.deployment),
            hipchat_token=config['hipchat_token'],
            hipchat_room='release',
            configuration_version=material_envvar_bash(CONFIGURATION()),
            edxapp_theme_source_repo=theme_url,
            # Currently, edx-theme isn't exposed as a material. See https://openedx.atlassian.net/browse/TE-1874
            # edxapp_theme_version='$GO_REVISION_EDX_THEME',
            # edxapp_theme_name='$EDXAPP_THEME_NAME',
            disable_edx_services='true',
            COMMON_TAG_EC2_INSTANCE='true',
            cache_id='$GO_PIPELINE_COUNTER',
            override_artifacts=[
                prerelease_merge_artifact,
            ],
            timeout=60
        )

        configuration_secure_version = '$GO_REVISION_{}_SECURE'.format(edp.deployment.upper())
        configuration_internal_version = '$GO_REVISION_{}_INTERNAL'.format(edp.deployment.upper())

        stages.generate_create_ami_from_instance(
            pipeline,
            edp=edp,
            app_repo=app_repo,
            app_version=material_envvar_bash(EDX_PLATFORM()),
            hipchat_token=config['hipchat_token'],
            hipchat_room='release pipeline',
            aws_access_key_id=config['aws_access_key_id'],
            aws_secret_access_key=config['aws_secret_access_key'],
            version_tags={
                # We don't specify a tag for edx_platform. The edxapp play in configuration
                # adds a tag (for edx_app), and the create_ami.yml play adds an edxapp tag automatically.
                'configuration': (configuration_url, material_envvar_bash(CONFIGURATION())),
                'configuration_secure': (configuration_secure_repo, configuration_secure_version),
                'configuration_internal': (configuration_internal_repo, configuration_internal_version),
                'edxapp_theme': (theme_url, material_envvar_bash(EDX_MICROSITE())),
            }
        )

        return pipeline
    return builder


def generate_migrate_stages(pipeline, config):
    """
    Generate stages to manage the migration of an environment,
    and add them to ``pipeline``.

    Required Config Values:
        db_migration_pass
        migration_duration_threshold
        db_migration_user
        play_name
        application_path
        alert_from_address
        alert_to_addresses
    """
    #
    # Create the DB migration running stage.
    #
    ansible_inventory_location = utils.ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.ANSIBLE_INVENTORY_FILENAME
    )
    instance_ssh_key_location = utils.ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.KEY_PEM_FILENAME
    )
    launch_info_location = utils.ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.LAUNCH_INSTANCE_FILENAME
    )
    # Check the migration duration on the stage environment only.
    if pipeline.name.startswith('STAGE'):
        duration_threshold = config['migration_duration_threshold']
    else:
        duration_threshold = None

    for sub_app in EDXAPP_SUBAPPS:
        stages.generate_run_migrations(
            pipeline,
            db_migration_pass=config['db_migration_pass'],
            inventory_location=ansible_inventory_location,
            instance_key_location=instance_ssh_key_location,
            launch_info_location=launch_info_location,
            application_user=config['db_migration_user'],
            application_name=config['play_name'],
            application_path=config['application_path'],
            sub_application_name=sub_app,
            duration_threshold=duration_threshold,
            from_address=config['alert_from_address'],
            to_addresses=config['alert_to_addresses']
        )

    return pipeline


def generate_deploy_stages(ami_pairs,
                           stage_deploy_pipeline_artifact,
                           base_ami_artifact,
                           head_ami_artifact,
                           auto_deploy_ami=False):
    """
    Create a builder function that adds deployment stages to a pipeline.

    Args:
        ami_pairs (list<tuple>): A list of tuples. The first item in the tuple should be Artifact location of the
            base_ami ID that was running before deployment and the ArtifactLocation of the newly deployed AMI ID
            e.g. (ArtifactLocation
                    (pipeline='prerelease_edxapp_materials_latest',
                     stage='select_base_ami', job='select_base_ami_prod_edx_job',
                     file_name='ami_override.yml',
                     is_dir=False
                    ),
                  ArtifactLocation
                    (pipeline='PROD_edx_edxapp_B',
                     stage='build_ami',
                     job='build_ami_job',
                     file_name='ami.yml',
                     is_dir=False
                    )
                 )
        stage_deploy_pipeline_artifact (edxpipelines.utils.ArtifactLocation): The stage deploy ArtifactLocation
        base_ami_artifact (edxpipelines.utils.ArtifactLocation): Location of the Base AMI selection artifact.
        head_ami_artifact (edxpipelines.utils.ArtifactLocation): Location of the Head AMI selection artifact.
        auto_deploy_ami (bool): should this pipeline automatically deploy the AMI

    Returns:
        callable: pipeline builder
    """
    def builder(pipeline, config):
        """
        Add stages required to deploy edxapp to an environment to the
        supplied pipeline.

        Required Config Parameters:
            asgard_api_endpoints
            asgard_token
            aws_access_key_id
            aws_secret_access_key
            github_token
            edx_environment
        """
        stages.generate_deploy_ami(
            pipeline,
            config['asgard_api_endpoints'],
            config['asgard_token'],
            config['aws_access_key_id'],
            config['aws_secret_access_key'],
            head_ami_artifact,
            manual_approval=not auto_deploy_ami
        )

        pipeline.ensure_unencrypted_secure_environment_variables({'GITHUB_TOKEN': config['github_token']})
        stages.generate_deployment_messages(
            pipeline=pipeline,
            ami_pairs=ami_pairs,
            stage_deploy_pipeline_artifact=stage_deploy_pipeline_artifact,
            release_status=constants.ReleaseStatus[config['edx_environment']],
            confluence_user=config['jira_user'],
            confluence_password=config['jira_password'],
            base_ami_artifact=base_ami_artifact,
            head_ami_artifact=head_ami_artifact,
            message_tags=[
                ('edx', 'edx-platform', 'edxapp-from-pipeline'),
                ('edx', 'edx-platform-private', 'edx_platform'),
            ],
            github_token=config['github_token'],
        )
        return pipeline
    return builder


def generate_cleanup_stages(pipeline, config, launch_stage):
    """
    Create the stage to terminate the EC2 instance used to both build the AMI and run DB migrations.

    Required Config Parameters:
        aws_access_key_id
        aws_secret_access_key
        hipchat_token
    """
    instance_info_location = utils.ArtifactLocation(
        pipeline.name,
        launch_stage.name,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.LAUNCH_INSTANCE_FILENAME
    )
    stages.generate_terminate_instance(
        pipeline,
        instance_info_location,
        aws_access_key_id=config['aws_access_key_id'],
        aws_secret_access_key=config['aws_secret_access_key'],
        hipchat_token=config['hipchat_token'],
        runif='any'
    )
    return pipeline


def manual_verification(edxapp_deploy_group, config):
    """
    Variables needed for this pipeline:
    materials: A list of dictionaries of the materials used in this pipeline
    upstream_pipelines: a list of dictionaries of the upstream pipelines that feed in to the manual verification
    """
    pipeline = edxapp_deploy_group.ensure_replacement_of_pipeline(EDXAPP_MANUAL_PIPELINE_NAME)

    for material in (
            TUBULAR, CONFIGURATION, EDX_PLATFORM, EDX_SECURE, EDGE_SECURE,
            EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL
    ):
        pipeline.ensure_material(material())

    # What this accomplishes:
    # When a pipeline such as edx stage runs this pipeline is downstream. Since the first stage is automatic
    # the git materials will be carried over from the first pipeline.
    #
    # The second pipeline stage checks the result of the CI testing for the commit to release in the
    # primary code repository.
    # The third stage in this pipeline requires manual approval.
    #
    # This allows the overall workflow to remain paused while manual verification is completed and allows the git
    # materials to stay pinned.
    #
    # Once the third phase is approved, the workflow will continue and pipelines downstream will continue to execute
    # with the same pinned materials from the upstream pipeline.
    stages.generate_armed_stage(pipeline, constants.INITIAL_VERIFICATION_STAGE_NAME)

    # Add all materials for which to check CI tests in this list.
    stages.generate_check_ci(
        pipeline,
        config['github_token'],
        [EDX_PLATFORM()]
    )

    manual_verification_stage = pipeline.ensure_stage(constants.MANUAL_VERIFICATION_STAGE_NAME)
    manual_verification_stage.set_has_manual_approval()
    manual_verification_job = manual_verification_stage.ensure_job(constants.MANUAL_VERIFICATION_JOB_NAME)
    manual_verification_job.add_task(
        ExecTask(
            [
                '/bin/bash',
                '-c',
                'echo Manual Verification run number $GO_PIPELINE_COUNTER completed by $GO_TRIGGER_USER'
            ],
        )
    )

    return pipeline


def generate_e2e_test_stage(pipeline, config):
    """
    Add stages to run end-to-end tests against edxapp to the specified ``pipeline``.

    Required Config Parameters:
        jenkins_user_token
        jenkins_job_token
        jenkins_user_name
    """
    # For now, you can only trigger builds on a single jenkins server, because you can only
    # define a single username/token.
    # And all the jobs that you want to trigger need the same job token defined.
    # TODO: refactor when required so that each job can define their own user and job tokens
    pipeline.ensure_unencrypted_secure_environment_variables(
        {
            'JENKINS_USER_TOKEN': config['jenkins_user_token'],
            'JENKINS_JOB_TOKEN': config['jenkins_job_token']
        }
    )

    # Create the stage with the Jenkins jobs
    jenkins_stage = pipeline.ensure_stage(constants.JENKINS_VERIFICATION_STAGE_NAME)
    jenkins_user_name = config['jenkins_user_name']

    jenkins_url = "https://build.testeng.edx.org"
    jenkins_job_timeout = 60 * 60

    e2e_tests = jenkins_stage.ensure_job('edx-e2e-test')
    e2e_tests.timeout = str(jenkins_job_timeout + 60)
    tasks.generate_package_install(e2e_tests, 'tubular')
    tasks.trigger_jenkins_build(
        e2e_tests,
        jenkins_url,
        jenkins_user_name,
        'edx-e2e-tests',
        {},
        timeout=jenkins_job_timeout,
        custom_error_message="Need help troubleshooting e2e tests failures? "
                             "See here: https://openedx.atlassian.net/wiki/display/MBT/What+to+do+when+e2e+tests+fail"
    )

    microsites_tests = jenkins_stage.ensure_job('microsites-staging-tests')
    microsites_tests.timeout = str(jenkins_job_timeout + 60)
    tasks.generate_package_install(microsites_tests, 'tubular')
    tasks.trigger_jenkins_build(
        microsites_tests,
        jenkins_url,
        jenkins_user_name,
        'microsites-staging-tests', {
            'CI_BRANCH': 'kashif/white_label',
        },
        timeout=jenkins_job_timeout,
    )


def rollback_asgs(
        edxapp_deploy_group,
        pipeline_name,
        config,
        ami_pairs,
        stage_deploy_pipeline_artifact,
        base_ami_artifact,
        head_ami_artifact,
):
    """
    Arguments:
        edxapp_deploy_group (gomatic.PipelineGroup): The group in which to create this pipeline
        pipeline_name (str): The name of this pipeline
        config (dict): the configuraiton dictionary
        ami_pairs (list<tuple>): A list of tuples. The first item in the tuple should be Artifact location of the
            base_ami ID that was running before deployment and the ArtifactLocation of the newly deployed AMI ID
            e.g. (ArtifactLocation
                    (pipeline='prerelease_edxapp_materials_latest',
                     stage='select_base_ami', job='select_base_ami_prod_edx_job',
                     file_name='ami_override.yml',
                     is_dir=False
                    ),
                  ArtifactLocation
                    (pipeline='PROD_edx_edxapp_B',
                     stage='build_ami',
                     job='build_ami_job',
                     file_name='ami.yml',
                     is_dir=False
                    )
                 )
        stage_deploy_pipeline_artifact (edxpipelines.utils.ArtifactLocation): The edxapp staging deployment
            pipeline artifact
        base_ami_artifact (edxpipelines.utils.ArtifactLocation): ArtifactLocation of the base AMI selection
        head_ami_artifact (edxpipelines.utils.ArtifactLocation): ArtifactLocation of the head AMI selection

    Configuration Required:
        tubular_sleep_wait_time
        asgard_api_endpoints
        asgard_token
        aws_access_key_id
        aws_secret_access_key
        hipchat_token
    """
    pipeline = edxapp_deploy_group.ensure_replacement_of_pipeline(pipeline_name)\
                                  .ensure_environment_variables({'WAIT_SLEEP_TIME': config['tubular_sleep_wait_time']})

    for material in (
            TUBULAR, CONFIGURATION, EDX_PLATFORM, EDX_SECURE, EDGE_SECURE,
            EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL,
    ):
        pipeline.ensure_material(material())

    # Create the armed stage as this pipeline needs to auto-execute
    stages.generate_armed_stage(pipeline, constants.ARMED_JOB_NAME)

    # Create a single stage in the pipeline which will rollback to the previous ASGs/AMI.
    rollback_stage = stages.generate_rollback_asg_stage(
        pipeline,
        config['asgard_api_endpoints'],
        config['asgard_token'],
        config['aws_access_key_id'],
        config['aws_secret_access_key'],
        config['hipchat_token'],
        constants.HIPCHAT_ROOM,
        base_ami_artifact,
    )
    # Since we only want this stage to rollback via manual approval, ensure that it is set on this stage.
    rollback_stage.set_has_manual_approval()

    # Message PRs being rolled back
    pipeline.ensure_unencrypted_secure_environment_variables({'GITHUB_TOKEN': config['github_token']})
    stages.generate_deployment_messages(
        pipeline=pipeline,
        ami_pairs=ami_pairs,
        stage_deploy_pipeline_artifact=stage_deploy_pipeline_artifact,
        base_ami_artifact=base_ami_artifact,
        head_ami_artifact=head_ami_artifact,
        message_tags=[
            ('edx', 'edx-platform', 'edxapp-from-pipeline'),
            ('edx', 'edx-platform-private', 'edx_platform')
        ],
        release_status=constants.ReleaseStatus.ROLLED_BACK,
        confluence_user=config['jira_user'],
        confluence_password=config['jira_password'],
        github_token=config['github_token'],
    )

    return pipeline


def armed_stage_builder(pipeline, config):  # pylint: disable=unused-argument
    """
    Add an armed stage to pipeline.
    """
    stages.generate_armed_stage(pipeline, constants.ARM_PRERELEASE_STAGE)
    return pipeline


def rollback_database(edp, sub_app_migration_artifacts):
    """
    Arguments:
        edp (EDP): EDP that this builder will roll back
        sub_app_migration_artifacts (dict<str, edxpipelines.utils.ArtifactLocation>): Pipeline source of the migration
            information

    Configuration Required:
        aws_access_key_id
        aws_secret_access_key
        hipchat_token
        ec2_vpc_subnet_id
        ec2_security_group_id
        ec2_instance_profile_name
        db_migration_user
        db_migration_pass
        play_name`
        application_name
        edxapp_subapps
    """
    def builder(pipeline, config):
        """
        Add database rollback stages to ``pipeline``.
        """
        for material in (
                TUBULAR, CONFIGURATION, EDX_PLATFORM, EDX_SECURE, EDGE_SECURE,
                EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL,
        ):
            pipeline.ensure_material(material())

        ansible_inventory_location = utils.ArtifactLocation(
            pipeline.name,
            constants.LAUNCH_INSTANCE_STAGE_NAME,
            constants.LAUNCH_INSTANCE_JOB_NAME,
            constants.ANSIBLE_INVENTORY_FILENAME
        )
        instance_ssh_key_location = utils.ArtifactLocation(
            pipeline.name,
            constants.LAUNCH_INSTANCE_STAGE_NAME,
            constants.LAUNCH_INSTANCE_JOB_NAME,
            constants.KEY_PEM_FILENAME
        )

        # Create a a stage for migration rollback.
        for sub_app, migration_artifact in sub_app_migration_artifacts.items():
            stages.generate_rollback_migrations(
                pipeline,
                edp,
                db_migration_pass=config['db_migration_pass'],
                inventory_location=ansible_inventory_location,
                instance_key_location=instance_ssh_key_location,
                migration_info_location=migration_artifact,
                application_user=config['db_migration_user'],
                application_name=config['play_name'],
                application_path=config['application_path'],
                sub_application_name=sub_app
            )
        return pipeline
    return builder


def merge_back_branches(edxapp_deploy_group, pipeline_name, deploy_artifact, prerelease_merge_artifact, config):
    """
    Arguments:
        edxapp_deploy_group (gomatic.PipelineGroup): The group in which to create this pipeline
        pipeline_name (str): The name of this pipeline
        deploy_pipeline_name (str): The name of the deploy pipeline from which to fetch an artifact.

    Configuration Required:
        github_org
        github_repo
        rc_branch
        release_branch
        release_to_master_branch
        master_branch
        github_token
    """
    pipeline = edxapp_deploy_group.ensure_replacement_of_pipeline(pipeline_name)

    for material in (
            TUBULAR, CONFIGURATION, EDX_PLATFORM, EDX_SECURE, EDGE_SECURE,
            EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL
    ):
        pipeline.ensure_material(material())

    # Create a single stage in the pipeline which will:
    #   - merge the RC branch into the release branch
    #   - tag the release branch

    git_stage = pipeline.ensure_stage(constants.GIT_MERGE_RC_BRANCH_STAGE_NAME)

    jobs.generate_merge_release_candidate(
        pipeline,
        git_stage,
        token=config['github_token'],
        org='edx',
        repo='edx-platform',
        target_branch='release',
        head_sha=material_envvar_bash(EDX_PLATFORM()),
        fast_forward_only=True,
        reference_repo='edx-platform',
    )
    jobs.generate_tag_commit(
        git_stage,
        'edx-platform',
        deploy_artifact=deploy_artifact,
        org='edx',
        repo='edx-platform',
        head_sha=material_envvar_bash(EDX_PLATFORM()),
    )

    jobs.generate_tag_commit(
        git_stage,
        'edx-platform-private',
        deploy_artifact=deploy_artifact,
        org='edx',
        repo='edx-platform-private',
        head_sha_variable='edx_platform_version',
        head_sha_artifact=prerelease_merge_artifact,
    )

    # Create a single stage in the pipeline which will:
    #  - create a branch off the HEAD of release
    #  - create a PR to merge release into master
    stages.generate_create_branch_and_pr(
        pipeline,
        constants.CREATE_MASTER_MERGE_PR_STAGE_NAME,
        org=config['github_org'],
        repo=config['github_repo'],
        source_branch=config['release_branch'],
        new_branch=config['release_to_master_branch'],
        target_branch=config['master_branch'],
        pr_title='Merge release back to master',
        pr_body='Merge the release branch back to master via a temporary branch off release.',
        token=config['github_token'],
        manual_approval=False
    )

    # Create a single stage in the pipeline which will:
    #   - poll for successful completion of PR tests
    #   - merge the PR
    pr_artifact_params = {
        'pipeline': pipeline.name,
        'stage': constants.CREATE_MASTER_MERGE_PR_STAGE_NAME,
        'job': constants.CREATE_MASTER_MERGE_PR_JOB_NAME,
        'src': FetchArtifactFile(constants.CREATE_BRANCH_PR_FILENAME),
        'dest': constants.ARTIFACT_PATH
    }
    stages.generate_poll_tests_and_merge_pr(
        pipeline=pipeline,
        stage=None,
        job=None,
        stage_name=constants.CHECK_PR_TESTS_AND_MERGE_STAGE_NAME,
        job_name=constants.CHECK_PR_TESTS_AND_MERGE_JOB_NAME,
        pr_artifact_params=pr_artifact_params,
        artifact_filename=constants.CREATE_BRANCH_PR_FILENAME,
        org=config['github_org'],
        repo=config['github_repo'],
        token=config['github_token'],
        initial_poll_wait=config['initial_poll_wait'],
        max_poll_tries=config['max_poll_tries'],
        poll_interval=config['poll_interval'],
        manual_approval=False
    )

    return pipeline
