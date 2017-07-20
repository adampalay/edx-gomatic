"""
Common gomatic pipeline patterns.

Responsibilities:
    Pipeline patterns should ...
        * expect ArtifactLocations as input.
            * It's the responsibility of the pipeline install script to ensure that the
              supplied artifacts don't refer to a job created by this pipeline.
        * not add PipelineMaterials (that should be handled by the pipeline-group script).
            * This allows pipeline pattern composition to be customized by pipeline groups.
        * return the pipeline that was created (or a list/namedtuple, if there were multiple pipelines).
"""
from collections import namedtuple
from functools import partial

from gomatic import GitMaterial, PipelineMaterial

from edxpipelines import constants, materials
from edxpipelines.materials import material_envvar_bash
from edxpipelines.patterns import jobs, stages
from edxpipelines.patterns.authz import Permission, ensure_permissions
from edxpipelines.utils import ArtifactLocation, EDP


def generate_ami_deployment_pipeline(configurator,
                                     pipeline_name,
                                     pipeline_group,
                                     asgard_api_endpoints,
                                     asgard_token,
                                     aws_access_key_id,
                                     aws_secret_access_key):
    """
    Args:
        configurator (GoCdConfigurator)
        pipeline_name (str):
        pipeline_group (str):
        asgard_api_endpoints (str): url of the asgard API
        asgard_token (str):
        aws_access_key_id (str):
        aws_secret_access_key (str):

    Returns:
        GoCdConfigurator
    """

    pipeline = configurator \
        .ensure_pipeline_group(pipeline_group) \
        .ensure_replacement_of_pipeline(pipeline_name) \
        .set_git_material(
            GitMaterial(
                "https://github.com/edx/tubular.git",
                polling=True,
                destination_directory="tubular",
                ignore_patterns=constants.MATERIAL_IGNORE_ALL_REGEX
            )
        )

    stages.generate_deploy_ami(pipeline,
                               asgard_api_endpoints,
                               asgard_token,
                               aws_access_key_id,
                               aws_secret_access_key,
                               manual_approval=True)
    return configurator


def generate_single_deployment_service_pipelines(configurator,
                                                 config,
                                                 play,
                                                 app_repo=None,
                                                 has_migrations=True,
                                                 application_user=None,
                                                 run_e2e_tests_after_deploy=False,
                                                 additional_migrations=None,
                                                 deployment='edx',
                                                 playbook_path_tpl=constants.PLAYBOOK_PATH_TPL):
    """
    Generates pipelines used to build and deploy a service to stage, loadtest,
    and prod, for only a single edx deployment.

    Pipelines are produced, named stage-{play}, loadtest-{play}, and prod-{play}.
    All are placed in a group with the same name as the play.

    stage-{play} polls a GitMaterial representing the service. When a change
    is detected on the master branch, it builds AMIs for stage and prod, deploys
    to stage, and gives pipeline operators the option of rolling back stage ASGs
    and migrations.

    prod-{play} requires a PipelineMaterial representing the upstream
    stage-{play} pipeline's build stage. When it completes successfully,
    prod-{play} is armed. Deployment to prod is then manually approved
    by a pipeline operator. This pipeline gives operators the option of rolling
    back prod ASGs and migrations.

    loadtest-{play} is independent of the stage-{play} and prod-{play} pipelines.
    It polls a GitMaterial representing the service. When a change is detected on the
    loadtest branch, it builds AMIs for loadtest, deploys to loadtest, and gives
    pipeline operators the option of rolling back loadtest ASGs and migrations.

    additional_migrations (list[edxpipelines.utils.MigrationAppInfo]): Additional applications to migrate.
            Will only run if has_migrations=True
    """
    if not additional_migrations:
        additional_migrations = []

    group = generate_service_pipeline_group(configurator, play)

    partial_app_material = partial(
        GitMaterial,
        app_repo or constants.EDX_REPO_TPL(play),
        # Material name is required to label pipelines with a commit SHA. GitMaterials
        # return their SHA when referenced by name.
        material_name=play,
        polling=True,
        destination_directory=play
    )

    generate_service_deployment_pipelines(
        group,
        config,
        partial_app_material(),
        continuous_deployment_edps=[EDP('stage', deployment, play)],
        manual_deployment_edps=[EDP('prod', deployment, play)],
        has_migrations=has_migrations,
        application_user=application_user,
        run_e2e_tests_after_deploy=run_e2e_tests_after_deploy,
        additional_migrations=additional_migrations,
        playbook_path_tpl=playbook_path_tpl,
    )
    generate_service_deployment_pipelines(
        group,
        config,
        partial_app_material(branch='loadtest'),
        continuous_deployment_edps=[EDP('loadtest', deployment, play)],
        configuration_branch='loadtest-{}'.format(play),
        has_migrations=has_migrations,
        application_user=application_user,
        run_e2e_tests_after_deploy=False,
        additional_migrations=additional_migrations,
        playbook_path_tpl=playbook_path_tpl,
    )


def generate_service_pipelines_with_edge(configurator,
                                         config,
                                         play,
                                         app_repo=None,
                                         has_migrations=True,
                                         application_user=None):
    """
    Generates pipelines used to build and deploy a service to stage-edx, loadtest-edx,
    prod-edx and prod-edx.

    Pipelines are produced, named stage-{play}, prod-{play},
    and loadtest-{play}. All are placed in a group with the same name as the play.

    stage-{play} polls a GitMaterial representing the service. When a change
    is detected on the master branch, it builds AMIs for stage-edx, prod-edx, and prod-edge, deploys
    to stage, and gives pipeline operators the option of rolling back stage ASGs
    and migrations.

    prod-{play} requires a PipelineMaterial representing the upstream
    stage-{play} pipeline's build stage. When it completes successfully,
    prod-{play} is armed. Deployment to prod-edx and prod-edge is then manually approved
    by a pipeline operator. This pipeline gives operators the option of rolling
    back prod-edx and prod-edge ASGs and migrations.

    loadtest-{play} is independent of the stage-{play}
    and prod-{play} pipelines. It polls a GitMaterial representing the service.
    When a change is detected on the loadtest branch, it builds AMIs for loadtest, deploys
    to loadtest, and gives pipeline operators the option of rolling back loadtest ASGs and migrations.
    """
    group = generate_service_pipeline_group(configurator, play)

    partial_app_material = partial(
        GitMaterial,
        app_repo or constants.EDX_REPO_TPL(play),
        # Material name is required to label pipelines with a commit SHA. GitMaterials
        # return their SHA when referenced by name.
        material_name=play,
        polling=True,
        destination_directory=play
    )

    generate_service_deployment_pipelines(
        group,
        config,
        partial_app_material(),
        continuous_deployment_edps=[EDP('stage', 'edx', play)],
        manual_deployment_edps=[EDP('prod', 'edx', play), EDP('prod', 'edge', play)],
        has_migrations=has_migrations,
        application_user=application_user,
    )
    generate_service_deployment_pipelines(
        group,
        config,
        partial_app_material(branch='loadtest'),
        continuous_deployment_edps=[EDP('loadtest', 'edx', play)],
        configuration_branch='loadtest-{}'.format(play),
        has_migrations=has_migrations,
        application_user=application_user,
    )


def generate_service_pipeline_group(configurator, play):
    """
    Create and return a new gomatic.PipelineGroup for the specified ``play``.
    """
    # Replace any existing pipeline group with a fresh one.
    configurator.ensure_removal_of_pipeline_group(play)
    pipeline_group = configurator.ensure_pipeline_group(play)

    # Create admin and operator roles to control pipeline group access.
    admin_role = '-'.join([play, 'admin'])
    ensure_permissions(configurator, pipeline_group, Permission.ADMINS, [admin_role])

    operator_role = '-'.join([play, 'operator'])
    ensure_permissions(configurator, pipeline_group, Permission.OPERATE, [operator_role])
    ensure_permissions(configurator, pipeline_group, Permission.VIEW, [operator_role])

    return pipeline_group


DeploymentStages = namedtuple('DeploymentStages', ['deploy', 'rollback_asgs', 'rollback_migrations', 'e2e_tests'])


def _generate_deployment_stages(pipeline, has_migrations, run_e2e_tests_after_deploy=False):
    """
    Create all stages needed for deployment and rollback inside a pipeline.

    Returns a DeploymentStages that contains each of those stages.
    """
    deploy = pipeline.ensure_stage(constants.DEPLOY_AMI_STAGE_NAME)

    e2e_tests = None

    if run_e2e_tests_after_deploy:
        e2e_tests = pipeline.ensure_stage(constants.E2E_TESTS_STAGE_NAME)

    # The next stage in the pipeline rolls back the ASG/AMI deployed by the
    # upstream deploy stage.
    rollback_asgs = pipeline.ensure_stage(constants.ROLLBACK_ASGS_STAGE_NAME)

    # Rollback stages always require manual approval from the operator.
    rollback_asgs.set_has_manual_approval()

    if has_migrations:
        # If the service has migrations, add an additional stage for rolling
        # back any migrations applied by the upstream deploy stage.
        rollback_migrations = pipeline.ensure_stage(constants.ROLLBACK_MIGRATIONS_STAGE_NAME)

        # Rollback stages always require manual approval from the operator.
        rollback_migrations.set_has_manual_approval()
    else:
        rollback_migrations = None

    return DeploymentStages(deploy, rollback_asgs, rollback_migrations, e2e_tests)


def generate_service_deployment_pipelines(
        pipeline_group,
        config,
        app_material,
        continuous_deployment_edps=(),
        manual_deployment_edps=(),
        configuration_branch=None,
        has_migrations=True,
        cd_pipeline_name=None,
        manual_pipeline_name=None,
        application_user=None,
        run_e2e_tests_after_deploy=False,
        additional_migrations=None,
        playbook_path_tpl=constants.PLAYBOOK_PATH_TPL,
):
    """
    Generates pipelines used to build and deploy a service to multiple environments/deployments.

    Two pipelines are produced, one for continuous deployment, and one for deployment that
    needs manual approval. Both are placed in a group with the same name as the play.


    Args:
        pipeline_group (gomatic.PipelineGroup): The group to create new pipelines in
        config (dict): Environment-independent config.
        app_material (gomatic.gomatic.gocd.materials.GitMaterial): Material representing
            the source of the app to be deployed.
        continuous_deployment_edps (list of EDP): A list of EDPs that should be deployed
            to after every change in app_material.
        manual_deployment_edps (list of EDP): A list of EDPs that should only be deployed
            to after waiting for manual approval.
        configuration_branch (str): The branch of the edx/configuration and edx/edx-internal repos to
            use when building AMIs and running plays. Defaults to master.
        has_migrations (bool): Whether to generate Gomatic for applying and
            rolling back migrations.
        cd_pipeline_name (str): The name of the continuous-deployment pipeline.
            Defaults to constants.ENVIRONMENT_PIPELINE_NAME_TPL
        manual_pipeline_name (str): The name of the manual deployment pipeline.
            Defaults to constants.ENVIRONMENT_PIPELINE_NAME_TPL
        application_user (str): Name of the user application user if different from the play name.
        run_e2e_tests_after_deploy (bool): Indicates if end-to-end tests should be triggered after
            deploying a continuous deployment EDP.
        additional_migrations (list[edxpipelines.utils.MigrationAppInfo]): Additional applications to migrate.
            Will only run if has_migrations=True
        playbook_path_tpl (str): Path to the playbook to run. Defaults to constants.PLAYBOOK_PATH_TPL
    """
    if not additional_migrations:
        additional_migrations = []

    continuous_deployment_edps = tuple(continuous_deployment_edps)
    manual_deployment_edps = tuple(manual_deployment_edps)

    all_edps = continuous_deployment_edps + manual_deployment_edps

    plays = {edp.play for edp in all_edps}
    if not plays:
        raise ValueError("generate_service_deployment_pipelines needs at least one EDP to deploy")
    if len(plays) > 1:
        raise ValueError(
            "generate_service_deployment_pipelines expects to only deploy "
            "a single service, but was passed multiple plays: {}".format(plays)
        )

    play = plays.pop()

    if cd_pipeline_name is None:
        cd_envs = {edp.environment for edp in continuous_deployment_edps}
        if len(cd_envs) > 1:
            raise ValueError(
                "Only one environment is allowed in continuous_deployment_edps "
                "if no cd_pipeline_name is specified"
            )
        cd_pipeline_name = constants.ENVIRONMENT_PIPELINE_NAME_TPL(environment=cd_envs.pop(), play=play)

    # Frame out the continuous deployment pipeline
    cd_pipeline = pipeline_group.ensure_replacement_of_pipeline(cd_pipeline_name)
    cd_pipeline.set_label_template(constants.DEPLOYMENT_PIPELINE_LABEL_TPL(app_material))
    build_stage = cd_pipeline.ensure_stage(constants.BUILD_AMI_STAGE_NAME)
    cd_deploy_stages = _generate_deployment_stages(cd_pipeline, has_migrations, run_e2e_tests_after_deploy)

    # Frame out the manual deployment pipeline (and wire it to the continuous deployment pipeline)
    if manual_deployment_edps:
        if manual_pipeline_name is None:
            manual_envs = {edp.environment for edp in manual_deployment_edps}
            if len(manual_envs) > 1:
                raise ValueError(
                    "Only one environment is allowed in manual_deployment_edps "
                    "if no manual_pipeline_name is specified"
                )
            manual_pipeline_name = constants.ENVIRONMENT_PIPELINE_NAME_TPL(environment=manual_envs.pop(), play=play)

        manual_pipeline = pipeline_group.ensure_replacement_of_pipeline(manual_pipeline_name)
        # The manual pipeline only requires successful completion of the continuous deployment
        # pipeline's AMI build stage, from which it will retrieve an AMI artifact.
        manual_pipeline.ensure_material(
            PipelineMaterial(
                cd_pipeline.name,
                constants.BUILD_AMI_STAGE_NAME,
                material_name=cd_pipeline.name
            )
        )

        # Pipelines return their label when referenced by name. We share the
        # label set for the CD pipeline with the manual pipeline.
        manual_pipeline.set_label_template('${{{}}}'.format(cd_pipeline.name))

        # The manual pipeline's first stage is a no-op 'armed stage' that will
        # be followed by a deploy stage requiring manual approval.
        stages.generate_armed_stage(manual_pipeline, constants.ARMED_STAGE_NAME)

        manual_deploy_stages = _generate_deployment_stages(manual_pipeline, has_migrations)
        manual_deploy_stages.deploy.set_has_manual_approval()

    else:
        manual_pipeline = None
        manual_deploy_stages = None

    # Set up the configuration/secure/internal materials
    configuration_material = materials.CONFIGURATION(branch=configuration_branch)
    secure_materials = {
        edp: materials.deployment_secure(edp.deployment)
        for edp in all_edps
    }
    internal_materials = {
        edp: materials.deployment_internal(edp.deployment, branch=configuration_branch)
        for edp in all_edps
    }

    # Ensure the materials that are common across environments
    for material in [
            materials.TUBULAR(),
            configuration_material,
            materials.EDX_ANSIBLE_PRIVATE(),
            materials.MCKA_ANSIBLE_PRIVATE(),
    ] + secure_materials.values() + internal_materials.values():
        cd_pipeline.ensure_material(material)
        if manual_pipeline:
            manual_pipeline.ensure_material(material)

    for material in [
            app_material,
    ]:
        cd_pipeline.ensure_material(material)

    # Add jobs to build all required AMIs
    for edp in all_edps:
        app_version_var = material_envvar_bash(app_material)
        overrides = {
            'app_version': app_version_var,
            '{}_VERSION'.format(play.upper()): app_version_var,
        }

        secure_material = secure_materials[edp]
        internal_material = internal_materials[edp]

        jobs.generate_build_ami(
            build_stage,
            edp,
            app_material.url,
            secure_material,
            internal_material,
            playbook_path_tpl(edp.play),
            config[edp],
            version_tags={
                edp.play: (app_material.url, app_version_var),
                'configuration': (configuration_material.url, material_envvar_bash(configuration_material)),
                'configuration_secure': (secure_material.url, material_envvar_bash(secure_material)),
                'configuration_internal': (internal_material.url, material_envvar_bash(internal_material)),
            },
            **overrides
        )

    # Create e2e_tests job
    if run_e2e_tests_after_deploy:
        for edp in continuous_deployment_edps:
            stage = cd_deploy_stages.e2e_tests
            config_edp = config[edp]

            # This conditional allow us to opt-in to running the Jenkins job for each EDP.
            if config_edp.get('jenkins_job_token') and config_edp.get('jenkins_job_name'):
                jobs.generate_run_jenkins_job(stage, config_edp)

    # Add jobs for deploying all required AMIs
    for (pipeline, deploy_stages, edps) in (
            (cd_pipeline, cd_deploy_stages, continuous_deployment_edps),
            (manual_pipeline, manual_deploy_stages, manual_deployment_edps),
    ):
        for edp in edps:
            ami_artifact_location = ArtifactLocation(
                cd_pipeline.name,
                constants.BUILD_AMI_STAGE_NAME,
                constants.BUILD_AMI_JOB_NAME_TPL(edp),
                constants.BUILD_AMI_FILENAME
            )
            jobs.generate_deploy_ami(
                deploy_stages.deploy,
                ami_artifact_location,
                edp,
                config[edp],
                has_migrations=has_migrations,
                application_user=application_user,
                additional_migrations=additional_migrations,
            )

            deployment_artifact_location = ArtifactLocation(
                pipeline.name,
                constants.DEPLOY_AMI_STAGE_NAME,
                constants.DEPLOY_AMI_JOB_NAME_TPL(edp),
                constants.DEPLOY_AMI_OUT_FILENAME
            )

            jobs.generate_rollback_asgs(
                deploy_stages.rollback_asgs,
                edp,
                deployment_artifact_location,
                config[edp],
            )

            if has_migrations:

                migration_info_location = ArtifactLocation(
                    pipeline.name,
                    constants.DEPLOY_AMI_STAGE_NAME,
                    constants.DEPLOY_AMI_JOB_NAME_TPL(edp),
                    constants.MIGRATION_OUTPUT_DIR_NAME_WITH_APP(application_user if application_user else edp.play),
                    is_dir=True
                )

                jobs.generate_rollback_migrations(
                    deploy_stages.rollback_migrations,
                    edp,
                    application_user if application_user else edp.play,
                    edp.play,
                    '/edx/app/{}'.format(edp.play),
                    constants.DB_MIGRATION_USER,
                    config[edp]['db_migration_pass'],
                    migration_info_location,
                    ami_artifact_location=ami_artifact_location,
                    config=config[edp],
                )
